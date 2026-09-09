from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.profile import profile_completion
from app.core.skills import parse_skills
from app.models import (
    GlobalDesignation, GlobalTeamMember, Project, Task, TaskAssignee,
    TaskStatus, TeamMember, User,
)


def build_member_report(db: Session, user_id: int, include_financials: bool = False) -> dict:
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id))
    if user is None or not (user.is_member or user.is_system_admin):
        raise HTTPException(status_code=404, detail="Member not found")
    membership = db.scalar(select(GlobalTeamMember).options(selectinload(GlobalTeamMember.team)).where(
        GlobalTeamMember.user_id == user.id
    ))
    tasks = list(db.scalars(
        select(Task).join(TaskAssignee).where(TaskAssignee.user_id == user.id)
        .options(selectinload(Task.task_assignees), selectinload(Task.checklist_items),
                 selectinload(Task.project).selectinload(Project.workspace))
        .order_by(Task.due_date, Task.id)
    ).unique().all())
    rates = {item.name: item.hourly_rate for item in db.scalars(select(GlobalDesignation)).all()}
    rate = rates.get(user.profile.professional_title, 0) if user.profile else 0
    capacity = db.scalar(select(func.max(TeamMember.weekly_capacity_hours)).where(TeamMember.user_id == user.id)) or 40
    all_project_hours = dict(db.execute(
        select(Task.project_id, func.coalesce(func.sum(TaskAssignee.planned_hours), 0))
        .join(TaskAssignee).group_by(Task.project_id)
    ).all())
    today = date.today()
    task_rows, project_map = [], {}
    for task in tasks:
        assignment = next(item for item in task.task_assignees if item.user_id == user.id)
        done_count = sum(item.is_done for item in task.checklist_items)
        health = "completed" if task.status == TaskStatus.done else "overdue" if task.due_date and task.due_date < today else "due_soon" if task.due_date and 0 <= (task.due_date - today).days <= 3 else "unscheduled" if not task.start_date or not task.due_date else "on_track"
        row = {"id": task.id, "title": task.title, "description": task.description,
            "project_id": task.project_id, "project_name": task.project.name,
            "workspace_name": task.project.workspace.name, "team_id": assignment.team_id,
            "responsibility": assignment.responsibility, "planned_hours": assignment.planned_hours or 0,
            "status": task.status.value, "priority": task.priority.value, "progress": task.progress,
            "start_date": task.start_date, "due_date": task.due_date, "health": health,
            "checklist_total": len(task.checklist_items), "checklist_done": done_count}
        task_rows.append(row)
        project = project_map.setdefault(task.project_id, {"id": task.project_id, "name": task.project.name,
            "workspace_name": task.project.workspace.name, "tasks": 0, "completed": 0, "active": 0,
            "overdue": 0, "progress_total": 0, "planned_hours": 0, "checklist_total": 0,
            "checklist_done": 0, "project_total_hours": int(all_project_hours.get(task.project_id, 0))})
        project["tasks"] += 1; project["completed"] += task.status == TaskStatus.done
        project["active"] += task.status != TaskStatus.done; project["overdue"] += health == "overdue"
        project["progress_total"] += task.progress; project["planned_hours"] += assignment.planned_hours or 0
        project["checklist_total"] += len(task.checklist_items); project["checklist_done"] += done_count
    projects = []
    for item in project_map.values():
        item["average_progress"] = round(item.pop("progress_total") / item["tasks"]) if item["tasks"] else 0
        item["contribution_percent"] = round(item["planned_hours"] * 100 / item["project_total_hours"]) if item["project_total_hours"] else 0
        if include_financials: item["planned_cost"] = item["planned_hours"] * rate
        projects.append(item)
    completion, missing = profile_completion(user, user.profile)
    active = [item for item in task_rows if item["status"] != "done"]
    hours = sum(item["planned_hours"] for item in active)
    workload = "no_assignments" if not active else "available" if hours < capacity * .5 else "balanced" if hours <= capacity else "high" if hours <= capacity * 1.25 else "overloaded"
    result = {"generated_at": datetime.now(timezone.utc), "member": {"id": user.id, "name": user.name,
        "email": user.email, "profile_image": user.profile.profile_image if user.profile else None,
        "role": "admin" if user.is_system_admin else "member", "department": user.profile.department if user.profile else None,
        "designation": user.profile.professional_title if user.profile else None,
        "skills": parse_skills(user.profile.skills if user.profile else None), "completion_percent": completion,
        "missing_fields": missing, "team_id": membership.team_id if membership else None,
        "team_name": membership.team.name if membership else None, "weekly_capacity_hours": capacity},
        "summary": {"projects": len(projects), "tasks": len(task_rows), "active": len(active),
            "completed": sum(item["status"] == "done" for item in task_rows),
            "overdue": sum(item["health"] == "overdue" for item in task_rows),
            "due_soon": sum(item["health"] == "due_soon" for item in task_rows),
            "average_progress": round(sum(item["progress"] for item in task_rows) / len(task_rows)) if task_rows else 0,
            "planned_hours": hours, "remaining_hours": round(sum(item["planned_hours"] * (100-item["progress"]) / 100 for item in active)),
            "checklist_total": sum(item["checklist_total"] for item in task_rows),
            "checklist_done": sum(item["checklist_done"] for item in task_rows), "workload": workload},
        "projects": sorted(projects, key=lambda item: item["name"].casefold()), "tasks": task_rows,
        "financials_visible": include_financials}
    if include_financials:
        result["summary"]["hourly_rate"] = rate
        result["summary"]["planned_cost"] = hours * rate
    return result
