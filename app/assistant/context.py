"""Build compact database context after applying Orbit's access rules."""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import GlobalTeamMember, Project, Task, TaskAssignee, Team, TeamManager, TeamMember, User
from app.core.skills import parse_skills


def accessible_project_ids(db: Session, user: User) -> set[int]:
    """Return projects visible to the user without relying on AI judgment."""
    if user.is_system_admin:
        return set(db.scalars(select(Project.id).join(Project.workspace).where(
            Project.workspace.has(organization_id=user.organization_id)
        )).all())
    managed = set(db.scalars(select(Project.id).where(Project.project_manager_id == user.id)).all())
    assigned = set(db.scalars(
        select(Task.project_id).join(TaskAssignee).where(TaskAssignee.user_id == user.id)
    ).all())
    managed_team_ids = set(db.scalars(select(TeamManager.team_id).where(TeamManager.user_id == user.id)).all())
    if managed_team_ids:
        assigned.update(db.scalars(
            select(Task.project_id).join(TaskAssignee).where(TaskAssignee.team_id.in_(managed_team_ids))
        ).all())
    return managed | assigned


def assistant_access_label(db: Session, user: User) -> tuple[str, str]:
    if user.is_system_admin:
        return "Administrator insight", "Global organization access"
    if not user.is_member:
        return "Account assistant", "Your own account and profile guidance only"
    managed = db.scalar(select(TeamManager.id).where(TeamManager.user_id == user.id))
    if managed:
        return "Team manager context", "Your profile, managed team and accessible projects"
    managed_project = db.scalar(select(Project.id).where(Project.project_manager_id == user.id))
    if managed_project:
        return "Project manager context", "Your profile and managed or assigned projects"
    return "Member assistant", "Your profile, assigned teams, projects and tasks"


def build_authorized_context(db: Session, user: User, *, workspace_id: int | None, project_id: int | None) -> dict:
    """Create bounded factual context; inaccessible resource IDs look nonexistent."""
    project_ids = accessible_project_ids(db, user)
    if project_id is not None and project_id not in project_ids:
        raise HTTPException(status_code=404, detail="Project is not available in your assistant scope")
    project_query = select(Project).where(Project.id.in_(project_ids))
    if workspace_id is not None:
        project_query = project_query.where(Project.workspace_id == workspace_id)
    if project_id is not None:
        project_query = project_query.where(Project.id == project_id)
    projects = list(db.scalars(project_query.order_by(Project.updated_at.desc()).limit(20)).all())
    visible_ids = [item.id for item in projects]
    task_query = select(Task).where(Task.project_id.in_(visible_ids)) if visible_ids else select(Task).where(False)
    managed_project_ids = set(db.scalars(select(Project.id).where(Project.project_manager_id == user.id)).all())
    managed_team_ids = set(db.scalars(select(TeamManager.team_id).where(TeamManager.user_id == user.id)).all())
    if not user.is_system_admin:
        task_query = task_query.outerjoin(TaskAssignee).where(or_(
            Task.project_id.in_(managed_project_ids), TaskAssignee.user_id == user.id,
            TaskAssignee.team_id.in_(managed_team_ids) if managed_team_ids else False,
        )).distinct()
    # Eager-load assignment and checklist relationships: they are part of the
    # grounded answer and this prevents per-task database queries.
    task_query = task_query.options(
        selectinload(Task.task_assignees),
        selectinload(Task.checklist_items),
    )
    tasks = list(db.scalars(task_query.order_by(Task.due_date.asc().nullslast()).limit(40)).all())
    team_ids = set(db.scalars(select(TeamManager.team_id).where(TeamManager.user_id == user.id)).all())
    team_ids.update(db.scalars(select(TaskAssignee.team_id).where(
        TaskAssignee.user_id == user.id, TaskAssignee.team_id.is_not(None)
    )).all())
    if user.is_system_admin:
        teams = list(db.scalars(select(Team).where(Team.organization_id == user.organization_id).order_by(Team.name).limit(30)).all())
    else:
        teams = list(db.scalars(select(Team).where(Team.id.in_(team_ids)).limit(20)).all()) if team_ids else []
    today = date.today()
    profile = user.profile
    if user.is_system_admin:
        people = list(db.scalars(select(User).options(selectinload(User.profile)).where(User.organization_id == user.organization_id, User.is_active.is_(True), or_(User.is_member.is_(True), User.is_system_admin.is_(True))).order_by(User.name).limit(50)).all())
    elif managed_team_ids:
        managed_user_ids = set(db.scalars(select(GlobalTeamMember.user_id).where(GlobalTeamMember.team_id.in_(managed_team_ids))).all())
        managed_user_ids.update(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id.in_(managed_team_ids))).all())
        people = list(db.scalars(select(User).options(selectinload(User.profile)).where(User.id.in_(managed_user_ids), User.is_active.is_(True)).order_by(User.name).limit(50)).all()) if managed_user_ids else []
    else:
        people = [user]
    person_ids = [person.id for person in people]
    workload_rows = db.execute(select(
        TaskAssignee.user_id,
        func.count(TaskAssignee.task_id),
        func.coalesce(func.sum(TaskAssignee.planned_hours), 0),
    ).join(Task).where(
        Task.project_id.in_(visible_ids), TaskAssignee.user_id.in_(person_ids),
    ).group_by(TaskAssignee.user_id)).all() if visible_ids and people else []
    workloads = {user_id: {"tasks": task_count, "planned_hours": planned_hours} for user_id, task_count, planned_hours in workload_rows}
    organization = None
    if user.is_system_admin:
        total_users, active_users, admins, members = db.execute(select(
            func.count(User.id),
            func.count(User.id).filter(User.is_active.is_(True)),
            func.count(User.id).filter(User.is_system_admin.is_(True)),
            func.count(User.id).filter(User.is_member.is_(True)),
        ).where(User.organization_id == user.organization_id)).one()
        organization = {"registered_users": total_users, "active_users": active_users, "pending_approval": total_users-active_users, "admins": admins, "members": members, "teams": len(teams)}
    task_statuses: dict[str, int] = {}
    priorities: dict[str, int] = {}
    for task in tasks:
        task_statuses[task.status.value] = task_statuses.get(task.status.value, 0) + 1
        priorities[task.priority.value] = priorities.get(task.priority.value, 0) + 1
    completed_tasks = task_statuses.get("done", 0)
    overdue_tasks = sum(
        1 for task in tasks
        if task.due_date and task.due_date < today and task.status.value != "done"
    )
    project_delivery = []
    for project in projects:
        project_tasks = [task for task in tasks if task.project_id == project.id]
        project_done = sum(task.status.value == "done" for task in project_tasks)
        project_overdue = sum(
            bool(task.due_date and task.due_date < today and task.status.value != "done")
            for task in project_tasks
        )
        project_delivery.append({
            "id": project.id,
            "name": project.name,
            "status": project.status.value,
            "start": str(project.start_date) if project.start_date else None,
            "end": str(project.end_date) if project.end_date else None,
            "tasks": len(project_tasks),
            "completed_tasks": project_done,
            "completion_rate": round(project_done * 100 / len(project_tasks), 1) if project_tasks else 0,
            "average_progress": round(sum(task.progress or 0 for task in project_tasks) / len(project_tasks), 1) if project_tasks else 0,
            "overdue_tasks": project_overdue,
            "planned_task_budget": sum(task.planned_budget or 0 for task in project_tasks),
            "actual_task_cost": sum(task.actual_cost or 0 for task in project_tasks),
            "estimated_hours": sum(task.estimated_hours or 0 for task in project_tasks),
        })
    return {
        "scope": "organization" if user.is_system_admin else "authorized resources only",
        "user": {"name": user.name, "role": "Admin" if user.is_system_admin else "Member" if user.is_member else "Not Added", "department": profile.department if profile else None, "designation": profile.professional_title if profile else None, "skills": parse_skills(profile.skills) if profile else []},
        "organization": organization,
        "summary": {
            "projects": len(projects), "tasks": len(tasks),
            "active_projects": sum(project.status.value == "active" for project in projects),
            "completed_projects": sum(project.status.value == "completed" for project in projects),
            "completed_tasks": completed_tasks,
            "task_completion_rate": round(completed_tasks * 100 / len(tasks), 1) if tasks else 0,
            "average_task_progress": round(sum(task.progress or 0 for task in tasks) / len(tasks), 1) if tasks else 0,
            "overdue_tasks": overdue_tasks,
            "due_next_7_days": sum(1 for task in tasks if task.due_date and today <= task.due_date <= today + timedelta(days=7)),
            "estimated_hours": sum(task.estimated_hours or 0 for task in tasks),
            "planned_task_budget": sum(task.planned_budget or 0 for task in tasks),
            "actual_task_cost": sum(task.actual_cost or 0 for task in tasks),
            "task_statuses": task_statuses,
            "task_priorities": priorities,
        },
        "projects": [{"id": p.id, "name": p.name, "status": p.status.value, "start": str(p.start_date), "end": str(p.end_date), "budget": p.budget if user.is_system_admin or p.project_manager_id == user.id else None} for p in projects],
        "tasks": [{
            "id": t.id,
            "project_id": t.project_id,
            "project_name": next((project.name for project in projects if project.id == t.project_id), "Unknown project"),
            "title": t.title,
            "status": t.status.value,
            "priority": t.priority.value,
            "progress": t.progress,
            "start": str(t.start_date) if t.start_date else None,
            "due": str(t.due_date) if t.due_date else None,
            "estimated_hours": t.estimated_hours,
            "planned_budget": t.planned_budget if user.is_system_admin or t.project_id in managed_project_ids else None,
            "checklist": {"done": t.checklist_done, "total": t.checklist_total},
            "remaining_checklist_items": [item.text for item in t.checklist_items if not item.is_done][:10],
            "assignments": [{
                "user_id": assignment.user_id,
                "team_id": assignment.team_id,
                "responsibility": assignment.responsibility,
                "planned_hours": assignment.planned_hours,
            } for assignment in t.task_assignees],
        } for t in tasks],
        "project_delivery": project_delivery,
        "managed_or_joined_teams": [{"id": team.id, "name": team.name} for team in teams],
        "authorized_people": [{"id": person.id, "name": person.name, "role": "Admin" if person.is_system_admin else "Member", "department": person.profile.department if person.profile else None, "designation": person.profile.professional_title if person.profile else None, "skills": parse_skills(person.profile.skills) if person.profile else [], "assigned_tasks": workloads.get(person.id, {}).get("tasks", 0), "planned_hours": workloads.get(person.id, {}).get("planned_hours", 0)} for person in people],
        "data_limits": "At most 20 projects, 40 tasks, 30 teams and 50 authorized people are supplied per answer.",
    }
