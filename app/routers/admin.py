from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.profile import profile_completion
from app.core.chat_access import sync_scoped_conversation_access
from app.core.skills import parse_skills
from app.core.member_report import build_member_report
from app.dependencies import CurrentUser, DB
from app.models import ChatConversation, ChatMessage, ChatNotification, ChatParticipant, ChatType, Comment, GlobalAnnouncement, GlobalDepartment, GlobalDesignation, GlobalSkill, GlobalTeamMember, OrganizationHoliday, Project, Task, TaskAssignee, TaskStatus, Team, TeamManager, TeamMember, User, UserProfile, Workspace, WorkspaceRole
from app.schemas import DepartmentCreate, DepartmentRead, DepartmentUpdate, DesignationCreate, DesignationRead, DesignationUpdate, GlobalAnnouncementSend, GlobalMemberAssign, GlobalSkillCreate, GlobalSkillRead, GlobalSkillUpdate, GlobalTeamMemberAdd, GlobalTeamMemberRead, HolidayCreate, HolidayRead, ProfileReminderResult, SkillMemberRead, TeamCreate, TeamMemberRead, TeamRead, TeamUpdate, UserDirectoryRead, UserProfileRead, UserProfileUpdate

router = APIRouter(prefix="/admin", tags=["System administration"])


@router.get("/members/{member_id}/report")
def admin_member_report(member_id: int, db: DB, current_user: CurrentUser) -> dict:
    require_system_admin(current_user)
    return build_member_report(db, member_id, include_financials=True)


def require_system_admin(current_user: CurrentUser) -> None:
    if not current_user.is_system_admin:
        raise HTTPException(status_code=403, detail="System administrator access required")


@router.get("/holidays", response_model=list[HolidayRead])
def list_holidays(db: DB, current_user: CurrentUser) -> list[OrganizationHoliday]:
    require_system_admin(current_user)
    return list(db.scalars(select(OrganizationHoliday).order_by(OrganizationHoliday.holiday_date)).all())


@router.post("/holidays", response_model=HolidayRead, status_code=201)
def create_holiday(payload: HolidayCreate, db: DB, current_user: CurrentUser) -> OrganizationHoliday:
    require_system_admin(current_user)
    if db.scalar(select(OrganizationHoliday.id).where(OrganizationHoliday.holiday_date == payload.holiday_date)):
        raise HTTPException(status_code=409, detail="A holiday already exists on this date")
    item = OrganizationHoliday(name=payload.name.strip(), holiday_date=payload.holiday_date, description=payload.description, is_active=True)
    db.add(item); db.commit(); db.refresh(item); return item


@router.delete("/holidays/{holiday_id}", status_code=204)
def delete_holiday(holiday_id: int, db: DB, current_user: CurrentUser) -> None:
    require_system_admin(current_user)
    item = db.get(OrganizationHoliday, holiday_id)
    if item is None: raise HTTPException(status_code=404, detail="Holiday not found")
    db.delete(item); db.commit()


def global_users(db: DB, newest_first: bool = False) -> list[User]:
    ordering = (
        (User.created_at.desc(), User.id.desc())
        if newest_first else
        (User.is_active.desc(), User.name, User.email)
    )
    return list(db.scalars(
        select(User).options(selectinload(User.profile)).order_by(*ordering)
    ).all())


def global_directory_item(db: DB, user: User) -> UserDirectoryRead:
    project_names = list(db.scalars(select(Project.name).join(TeamMember, TeamMember.project_id == Project.id).where(TeamMember.user_id == user.id).distinct()).all())
    project_names.extend(db.scalars(
        select(Project.name).join(Task, Task.project_id == Project.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(TaskAssignee.user_id == user.id).distinct()
    ).all())
    percent, missing = profile_completion(user, user.profile)
    role = WorkspaceRole.admin if user.is_system_admin else WorkspaceRole.member if user.is_member else None
    return UserDirectoryRead(user_id=user.id, name=user.name, email=user.email, is_active=user.is_active, is_member=user.is_member, is_system_admin=user.is_system_admin, role=role, professional_title=user.profile.professional_title if user.profile else None, department=user.profile.department if user.profile else None, profile_image=user.profile.profile_image if user.profile else None, projects=sorted(set(project_names)), completion_percent=percent, missing_fields=missing)


@router.get("/users", response_model=list[UserDirectoryRead])
def list_global_users(db: DB, current_user: CurrentUser) -> list[UserDirectoryRead]:
    require_system_admin(current_user)
    allocation_rows = db.execute(
        select(TeamMember.user_id, Project.name)
        .join(Project, Project.id == TeamMember.project_id)
        .distinct()
    ).all()
    task_assignment_rows = db.execute(
        select(TaskAssignee.user_id, Project.name)
        .join(Task, Task.id == TaskAssignee.task_id)
        .join(Project, Project.id == Task.project_id)
        .distinct()
    ).all()
    projects: dict[int, list[str]] = {}
    for user_id, project_name in allocation_rows:
        projects.setdefault(user_id, []).append(project_name)
    for user_id, project_name in task_assignment_rows:
        projects.setdefault(user_id, []).append(project_name)
    result: list[UserDirectoryRead] = []
    for user in global_users(db, newest_first=True):
        percent, missing = profile_completion(user, user.profile)
        result.append(UserDirectoryRead(
            user_id=user.id, name=user.name, email=user.email,
            is_active=user.is_active, is_member=user.is_member, is_system_admin=user.is_system_admin,
            role=WorkspaceRole.admin if user.is_system_admin else WorkspaceRole.member if user.is_member else None,
            professional_title=user.profile.professional_title if user.profile else None,
            department=user.profile.department if user.profile else None,
            profile_image=user.profile.profile_image if user.profile else None,
            projects=sorted(set(projects.get(user.id, []))),
            completion_percent=percent, missing_fields=missing,
        ))
    return result


@router.post("/announcements", response_model=ProfileReminderResult)
def send_global_announcement(payload: GlobalAnnouncementSend, db: DB, current_user: CurrentUser) -> ProfileReminderResult:
    require_system_admin(current_user)
    query = select(User).where(User.is_active.is_(True), User.is_member.is_(True))
    if payload.audience == "selected":
        user_ids = list(dict.fromkeys(payload.user_ids))
        query = query.where(User.id.in_(user_ids))
    users = list(db.scalars(query).all())
    if payload.audience == "selected" and len(users) != len(set(payload.user_ids)):
        raise HTTPException(status_code=400, detail="Select active Members or Admins only")
    title, body = payload.title.strip(), payload.message.strip()
    for user in users:
        db.add(GlobalAnnouncement(user_id=user.id, sent_by_id=current_user.id, title=title, message=body))
    if payload.audience == "all":
        conversation = db.scalar(select(ChatConversation).where(
            ChatConversation.workspace_id.is_(None), ChatConversation.scope_type == "global",
            ChatConversation.chat_type == ChatType.broadcast,
        ))
        if conversation is None:
            conversation = ChatConversation(workspace_id=None, scope_type="global", chat_type=ChatType.broadcast,
                name="Company announcements", created_by_id=current_user.id)
            db.add(conversation); db.flush()
        message = ChatMessage(conversation_id=conversation.id, sender_id=current_user.id,
            body=f"{title}\n\n{body}" if title else body)
        db.add(message); db.flush(); conversation.updated_at = datetime.now(timezone.utc)
        for user in users:
            if user.id != current_user.id:
                db.add(ChatNotification(message_id=message.id, conversation_id=conversation.id, workspace_id=None,
                    user_id=user.id, sender_id=current_user.id, title=title or conversation.name, message=body))
    else:
        for user in users:
            participant_ids = {current_user.id, user.id}
            conversation = None
            candidates = db.scalars(select(ChatConversation).options(selectinload(ChatConversation.participants)).where(
                ChatConversation.workspace_id.is_(None), ChatConversation.scope_type == "direct",
                ChatConversation.chat_type == ChatType.direct,
            )).all()
            for candidate in candidates:
                if {item.user_id for item in candidate.participants} == participant_ids:
                    conversation = candidate; break
            if conversation is None:
                conversation = ChatConversation(workspace_id=None, scope_type="direct", chat_type=ChatType.direct,
                    name=user.name, created_by_id=current_user.id)
                db.add(conversation); db.flush()
                db.add_all([ChatParticipant(conversation_id=conversation.id, user_id=user_id) for user_id in participant_ids])
            message = ChatMessage(conversation_id=conversation.id, sender_id=current_user.id,
                body=f"{title}\n\n{body}" if title else body)
            db.add(message); db.flush(); conversation.updated_at = datetime.now(timezone.utc)
            if user.id != current_user.id:
                db.add(ChatNotification(message_id=message.id, conversation_id=conversation.id, workspace_id=None,
                    user_id=user.id, sender_id=current_user.id, title=title or "Announcement", message=body))
    db.commit()
    return ProfileReminderResult(sent_count=len(users))


@router.patch("/users/{user_id}/member", response_model=UserDirectoryRead)
def assign_global_member(user_id: int, payload: GlobalMemberAssign, db: DB, current_user: CurrentUser) -> UserDirectoryRead:
    require_system_admin(current_user)
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id, User.is_active.is_(True)))
    if user is None: raise HTTPException(status_code=404, detail="Active user not found")
    department = db.scalar(select(GlobalDepartment).where(GlobalDepartment.name == payload.department.strip()))
    designation = db.scalar(select(GlobalDesignation).options(selectinload(GlobalDesignation.department)).where(GlobalDesignation.name == payload.professional_title.strip()))
    if department is None: raise HTTPException(status_code=400, detail="Select a valid department")
    if designation is None or designation.department_id != department.id: raise HTTPException(status_code=400, detail="Select a designation under the selected department")
    if user.profile is None:
        user.profile = UserProfile()
    user.profile.department = department.name
    user.profile.professional_title = designation.name
    for membership in db.scalars(select(GlobalTeamMember).where(GlobalTeamMember.user_id == user.id)).all():
        membership.designation = designation.name
    user.is_member = True
    if "role" in payload.model_fields_set:
        if user.id == current_user.id and payload.role.value != "admin":
            raise HTTPException(status_code=400, detail="You cannot remove your own administrator role")
        user.is_system_admin = payload.role.value == "admin"
    db.commit(); db.refresh(user)
    percent, missing = profile_completion(user, user.profile)
    global_role = WorkspaceRole.admin if user.is_system_admin else WorkspaceRole.member
    return UserDirectoryRead(user_id=user.id, name=user.name, email=user.email, is_active=user.is_active, is_member=True, is_system_admin=user.is_system_admin, role=global_role, professional_title=designation.name, department=department.name, profile_image=user.profile.profile_image, completion_percent=percent, missing_fields=missing)


@router.patch("/users/{user_id}/approve", response_model=UserDirectoryRead)
def approve_global_user(user_id: int, db: DB, current_user: CurrentUser) -> UserDirectoryRead:
    require_system_admin(current_user)
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id))
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True; db.commit(); db.refresh(user)
    return global_directory_item(db, user)


@router.patch("/users/{user_id}/access", response_model=UserDirectoryRead)
def update_global_user_access(user_id: int, is_active: bool, db: DB, current_user: CurrentUser) -> UserDirectoryRead:
    require_system_admin(current_user)
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id))
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id and not is_active: raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    if user.is_system_admin and not is_active:
        active_admins = db.scalar(select(func.count(User.id)).where(User.is_system_admin.is_(True), User.is_active.is_(True)))
        if active_admins <= 1: raise HTTPException(status_code=400, detail="The final administrator cannot be deactivated")
    user.is_active = is_active; db.commit(); db.refresh(user)
    return global_directory_item(db, user)


@router.get("/users/{user_id}/profile", response_model=UserProfileRead)
def get_global_user_profile(user_id: int, db: DB, current_user: CurrentUser) -> UserProfileRead:
    require_system_admin(current_user)
    from app.routers.workspaces import admin_profile_response
    user = db.get(User, user_id)
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    return admin_profile_response(db, user)


@router.put("/users/{user_id}/profile", response_model=UserProfileRead)
def update_global_user_profile(user_id: int, payload: UserProfileUpdate, db: DB, current_user: CurrentUser) -> UserProfileRead:
    require_system_admin(current_user)
    from app.routers.workspaces import update_admin_managed_profile
    user = db.get(User, user_id)
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    result = update_admin_managed_profile(db, 0, user, payload)
    if result.professional_title:
        memberships = db.scalars(select(GlobalTeamMember).where(GlobalTeamMember.user_id == user.id)).all()
        changed = False
        for membership in memberships:
            if membership.designation != result.professional_title:
                membership.designation = result.professional_title
                changed = True
        if changed:
            db.commit()
    return result


@router.delete("/users/{user_id}", status_code=204)
def delete_global_user(user_id: int, db: DB, current_user: CurrentUser) -> None:
    require_system_admin(current_user)
    user = db.get(User, user_id)
    if user is None: raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id: raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if user.is_system_admin:
        admins = db.scalar(select(func.count(User.id)).where(User.is_system_admin.is_(True)))
        if admins <= 1: raise HTTPException(status_code=400, detail="The final administrator cannot be deleted")
    for workspace in db.scalars(select(Workspace).where(Workspace.owner_id == user.id)).all(): workspace.owner_id = current_user.id
    for project in db.scalars(select(Project).where(Project.project_manager_id == user.id)).all(): project.project_manager_id = current_user.id
    for manager in db.scalars(select(TeamManager).where(TeamManager.user_id == user.id)).all(): manager.user_id = current_user.id
    for task in db.scalars(select(Task).where(Task.reporter_id == user.id)).all(): task.reporter_id = current_user.id
    for task in db.scalars(select(Task).where(Task.assignee_id == user.id)).all(): task.assignee_id = None
    for comment in db.scalars(select(Comment).where(Comment.author_id == user.id)).all(): db.delete(comment)
    db.delete(user); db.commit()


def global_skill_usage(db: DB) -> dict[str, int]:
    usage: dict[str, int] = {}
    for value in db.scalars(select(UserProfile.skills)).all():
        for name in parse_skills(value):
            usage[name.casefold()] = usage.get(name.casefold(), 0) + 1
    return usage


def global_skill_response(item: GlobalSkill, usage: dict[str, int]) -> GlobalSkillRead:
    return GlobalSkillRead.model_validate({
        "id": item.id, "name": item.name, "description": item.description,
        "usage_count": usage.get(item.name.casefold(), 0),
        "created_at": item.created_at, "updated_at": item.updated_at,
    })


@router.get("/skill-catalog-items", response_model=list[GlobalSkillRead])
def list_global_skill_catalog(db: DB, current_user: CurrentUser) -> list[GlobalSkillRead]:
    require_system_admin(current_user)
    existing = {item.name.casefold(): item for item in db.scalars(select(GlobalSkill)).all()}
    usage = global_skill_usage(db)
    for value in db.scalars(select(UserProfile.skills)).all():
        for name in parse_skills(value):
            if name.casefold() not in existing:
                item = GlobalSkill(name=name)
                db.add(item); existing[name.casefold()] = item
    db.commit()
    items = list(db.scalars(select(GlobalSkill).order_by(func.lower(GlobalSkill.name))).all())
    return [global_skill_response(item, usage) for item in items]


@router.post("/skill-catalog-items", response_model=GlobalSkillRead, status_code=201)
def create_global_skill(payload: GlobalSkillCreate, db: DB, current_user: CurrentUser) -> GlobalSkillRead:
    require_system_admin(current_user)
    name = " ".join(payload.name.split())
    if db.scalar(select(GlobalSkill.id).where(func.lower(GlobalSkill.name) == name.casefold())):
        raise HTTPException(status_code=409, detail="A skill with this name already exists")
    item = GlobalSkill(name=name, description=payload.description.strip() if payload.description else None)
    db.add(item); db.commit(); db.refresh(item)
    return global_skill_response(item, global_skill_usage(db))


@router.patch("/skill-catalog-items/{skill_id}", response_model=GlobalSkillRead)
def update_global_skill(skill_id: int, payload: GlobalSkillUpdate, db: DB, current_user: CurrentUser) -> GlobalSkillRead:
    require_system_admin(current_user)
    item = db.get(GlobalSkill, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    name = " ".join(payload.name.split())
    duplicate = db.scalar(select(GlobalSkill.id).where(func.lower(GlobalSkill.name) == name.casefold(), GlobalSkill.id != skill_id))
    if duplicate: raise HTTPException(status_code=409, detail="A skill with this name already exists")
    old_key = item.name.casefold()
    for profile in db.scalars(select(UserProfile).where(UserProfile.skills.is_not(None))).all():
        values = parse_skills(profile.skills)
        if any(value.casefold() == old_key for value in values):
            replaced = [name if value.casefold() == old_key else value for value in values]
            profile.skills = ", ".join(parse_skills(", ".join(replaced)))
    item.name = name; item.description = payload.description.strip() if payload.description else None
    db.commit(); db.refresh(item)
    return global_skill_response(item, global_skill_usage(db))


@router.delete("/skill-catalog-items/{skill_id}")
def delete_global_skill(skill_id: int, db: DB, current_user: CurrentUser) -> dict:
    require_system_admin(current_user)
    item = db.get(GlobalSkill, skill_id)
    if item is None: raise HTTPException(status_code=404, detail="Skill not found")
    key = item.name.casefold(); affected = 0
    for profile in db.scalars(select(UserProfile).where(UserProfile.skills.is_not(None))).all():
        values = parse_skills(profile.skills)
        remaining = [value for value in values if value.casefold() != key]
        if len(remaining) != len(values):
            affected += 1; profile.skills = ", ".join(remaining) or None
    db.delete(item); db.commit()
    return {"deleted": True, "affected_profiles": affected}


@router.get("/skills", response_model=list[SkillMemberRead])
def list_global_skills(db: DB, current_user: CurrentUser) -> list[SkillMemberRead]:
    require_system_admin(current_user)
    project_rows = db.execute(
        select(TeamMember.user_id, TeamMember.project_id).distinct()
    ).all()
    project_ids: dict[int, list[int]] = {}
    for user_id, project_id in project_rows:
        project_ids.setdefault(user_id, []).append(project_id)
    memberships = {item.user_id: item for item in db.scalars(
        select(GlobalTeamMember).options(selectinload(GlobalTeamMember.team))
    ).all()}
    active_counts = dict(db.execute(
        select(TaskAssignee.user_id, func.count(TaskAssignee.id)).join(Task)
        .where(Task.status != TaskStatus.done).group_by(TaskAssignee.user_id)
    ).all())
    hourly_rates = {item.name: item.hourly_rate for item in db.scalars(select(GlobalDesignation)).all()}
    users = [user for user in global_users(db) if user.is_active and (user.is_member or user.is_system_admin)]
    result = []
    for user in users:
        completion, _ = profile_completion(user, user.profile)
        membership = memberships.get(user.id)
        department = user.profile.department if user.profile else None
        designation = user.profile.professional_title if user.profile else None
        reason = None
        if completion < 50: reason = f"Profile is only {completion}% complete"
        elif not department: reason = "Department is not assigned"
        elif not designation: reason = "Designation is not assigned"
        elif membership is None: reason = "Member is not allocated to a team"
        result.append(SkillMemberRead(
            user_id=user.id, name=user.name, email=user.email,
            professional_title=designation, department=department,
            profile_image=user.profile.profile_image if user.profile else None,
            skills=parse_skills(user.profile.skills if user.profile else None),
            project_ids=project_ids.get(user.id, []), team_id=membership.team_id if membership else None,
            team_name=membership.team.name if membership else None, completion_percent=completion,
            total_active_tasks=active_counts.get(user.id, 0), hourly_rate=hourly_rates.get(designation, 0),
            is_eligible=reason is None, eligibility_reason=reason,
        ))
    return result


@router.get("/skill-projects")
def list_skill_assignment_projects(db: DB, current_user: CurrentUser) -> list[dict]:
    require_system_admin(current_user)
    rows = db.execute(
        select(Project.id, Project.name, Workspace.name)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .order_by(Workspace.name, Project.name)
    ).all()
    return [{"id": project_id, "name": project_name, "workspace_name": workspace_name} for project_id, project_name, workspace_name in rows]


@router.get("/team-member-analytics")
def team_member_analytics(db: DB, current_user: CurrentUser) -> dict:
    """Global, read-only resource analytics used by every dashboard toggle."""
    require_system_admin(current_user)
    users = [user for user in global_users(db) if user.is_member or user.is_system_admin]
    memberships = list(db.scalars(select(GlobalTeamMember).options(
        selectinload(GlobalTeamMember.team)
    )).all())
    membership_by_user = {item.user_id: item for item in memberships}
    teams = list(db.scalars(select(Team).options(
        selectinload(Team.manager_record).selectinload(TeamManager.user)
    ).order_by(Team.name)).all())
    projects = list(db.scalars(select(Project).options(selectinload(Project.workspace))).all())
    project_by_id = {item.id: item for item in projects}
    tasks = list(db.scalars(select(Task).options(selectinload(Task.task_assignees))).all())
    assignments_by_user: dict[int, list[tuple[Task, TaskAssignee]]] = {}
    assignments_by_team: dict[int, list[tuple[Task, TaskAssignee]]] = {}
    for task in tasks:
        for assignment in task.task_assignees:
            assignments_by_user.setdefault(assignment.user_id, []).append((task, assignment))
            if assignment.team_id:
                assignments_by_team.setdefault(assignment.team_id, []).append((task, assignment))
    rates = {item.name: item.hourly_rate for item in db.scalars(select(GlobalDesignation)).all()}
    today = date.today()
    member_rows = []
    for user in users:
        profile = user.profile
        completion, missing = profile_completion(user, profile)
        membership = membership_by_user.get(user.id)
        assignments = assignments_by_user.get(user.id, [])
        active = [(task, item) for task, item in assignments if task.status != TaskStatus.done]
        done = [(task, item) for task, item in assignments if task.status == TaskStatus.done]
        overdue = [(task, item) for task, item in active if task.due_date and task.due_date < today]
        hours = sum(item.planned_hours or 0 for _, item in active)
        rate = rates.get(profile.professional_title, 0) if profile else 0
        project_ids = sorted({task.project_id for task, _ in assignments})
        member_rows.append({
            "id": user.id, "name": user.name, "email": user.email,
            "profile_image": profile.profile_image if profile else None,
            "role": "admin" if user.is_system_admin else "member", "is_active": user.is_active,
            "department": profile.department if profile else None,
            "designation": profile.professional_title if profile else None,
            "skills": parse_skills(profile.skills if profile else None),
            "completion_percent": completion, "missing_fields": missing,
            "team_id": membership.team_id if membership else None,
            "team_name": membership.team.name if membership else None,
            "hourly_rate": rate, "active_tasks": len(active), "completed_tasks": len(done),
            "overdue_tasks": len(overdue), "planned_hours": hours,
            "planned_cost": hours * rate,
            "average_progress": round(sum(task.progress for task, _ in assignments) / len(assignments)) if assignments else 0,
            "project_ids": project_ids,
            "tasks": [{"id": task.id, "title": task.title, "project_id": task.project_id,
                "project_name": project_by_id[task.project_id].name, "status": task.status.value,
                "progress": task.progress, "due_date": task.due_date,
                "responsibility": item.responsibility, "planned_hours": item.planned_hours}
                for task, item in assignments],
        })
    team_rows = []
    for team in teams:
        team_members = [row for row in member_rows if row["team_id"] == team.id]
        assigned = assignments_by_team.get(team.id, [])
        unique_tasks = {task.id: task for task, _ in assigned}.values()
        active_tasks = [task for task in unique_tasks if task.status != TaskStatus.done]
        completed_tasks = [task for task in unique_tasks if task.status == TaskStatus.done]
        overdue_tasks = [task for task in active_tasks if task.due_date and task.due_date < today]
        hours = sum(item.planned_hours or 0 for task, item in assigned if task.status != TaskStatus.done)
        team_rows.append({"id": team.id, "name": team.name, "description": team.description,
            "manager_id": team.manager_user_id, "manager_name": team.manager_user.name if team.manager_user else None,
            "manager_designation": team.manager_designation, "members": len(team_members),
            "member_ids": [row["id"] for row in team_members], "active_tasks": len(active_tasks),
            "completed_tasks": len(completed_tasks), "overdue_tasks": len(overdue_tasks),
            "average_progress": round(sum(task.progress for task in unique_tasks) / len(unique_tasks)) if unique_tasks else 0,
            "planned_hours": hours, "planned_cost": sum(row["planned_cost"] for row in team_members),
            "project_ids": sorted({task.project_id for task in unique_tasks})})
    return {"generated_at": datetime.now(timezone.utc), "members": member_rows, "teams": team_rows,
        "projects": [{"id": item.id, "name": item.name, "workspace_id": item.workspace_id,
            "workspace_name": item.workspace.name, "budget": item.budget} for item in projects]}


@router.get("/departments", response_model=list[DepartmentRead])
def list_global_departments(db: DB, current_user: CurrentUser) -> list[GlobalDepartment]:
    require_system_admin(current_user)
    return list(db.scalars(select(GlobalDepartment).order_by(GlobalDepartment.name)).all())


@router.post("/departments", response_model=DepartmentRead, status_code=201)
def create_global_department(payload: DepartmentCreate, db: DB, current_user: CurrentUser) -> GlobalDepartment:
    require_system_admin(current_user)
    item = GlobalDepartment(name=payload.name.strip(), description=payload.description)
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.patch("/departments/{department_id}", response_model=DepartmentRead)
def update_global_department(department_id: int, payload: DepartmentUpdate, db: DB, current_user: CurrentUser) -> GlobalDepartment:
    require_system_admin(current_user)
    item = db.get(GlobalDepartment, department_id)
    if item is None: raise HTTPException(status_code=404, detail="Department not found")
    old_name = item.name
    for field, value in payload.model_dump(exclude_unset=True).items(): setattr(item, field, value.strip() if isinstance(value, str) else value)
    if item.name != old_name:
        for profile in db.scalars(select(UserProfile).where(UserProfile.department == old_name)).all(): profile.department = item.name
    db.commit(); db.refresh(item)
    return item


@router.delete("/departments/{department_id}", status_code=204)
def delete_global_department(department_id: int, db: DB, current_user: CurrentUser) -> None:
    require_system_admin(current_user)
    item = db.get(GlobalDepartment, department_id)
    if item is None: raise HTTPException(status_code=404, detail="Department not found")
    for profile in db.scalars(select(UserProfile).where(UserProfile.department == item.name)).all(): profile.department = None
    db.delete(item); db.commit()


def designation_response(item: GlobalDesignation) -> DesignationRead:
    return DesignationRead.model_validate(item).model_copy(update={"department_name": item.department.name if item.department else None})


@router.get("/designations", response_model=list[DesignationRead])
def list_global_designations(db: DB, current_user: CurrentUser) -> list[DesignationRead]:
    require_system_admin(current_user)
    items = db.scalars(select(GlobalDesignation).options(selectinload(GlobalDesignation.department)).order_by(GlobalDesignation.name)).all()
    return [designation_response(item) for item in items]


@router.post("/designations", response_model=DesignationRead, status_code=201)
def create_global_designation(payload: DesignationCreate, db: DB, current_user: CurrentUser) -> DesignationRead:
    require_system_admin(current_user)
    if db.get(GlobalDepartment, payload.department_id) is None: raise HTTPException(status_code=400, detail="Select a valid department")
    item = GlobalDesignation(name=payload.name.strip(), description=payload.description, department_id=payload.department_id, hourly_rate=payload.hourly_rate)
    db.add(item); db.commit(); db.refresh(item)
    return designation_response(item)


@router.patch("/designations/{designation_id}", response_model=DesignationRead)
def update_global_designation(designation_id: int, payload: DesignationUpdate, db: DB, current_user: CurrentUser) -> DesignationRead:
    require_system_admin(current_user)
    item = db.get(GlobalDesignation, designation_id)
    if item is None: raise HTTPException(status_code=404, detail="Designation not found")
    values = payload.model_dump(exclude_unset=True)
    if values.get("department_id") is not None and db.get(GlobalDepartment, values["department_id"]) is None: raise HTTPException(status_code=400, detail="Select a valid department")
    old_name = item.name
    for field, value in values.items(): setattr(item, field, value.strip() if isinstance(value, str) else value)
    if item.name != old_name:
        for profile in db.scalars(select(UserProfile).where(UserProfile.professional_title == old_name)).all(): profile.professional_title = item.name
        for allocation in db.scalars(select(TeamMember).where(TeamMember.designation == old_name)).all(): allocation.designation = item.name
        for membership in db.scalars(select(GlobalTeamMember).where(GlobalTeamMember.designation == old_name)).all(): membership.designation = item.name
        for manager in db.scalars(select(TeamManager).where(TeamManager.designation == old_name)).all(): manager.designation = item.name
    db.commit(); db.refresh(item)
    return designation_response(item)


@router.delete("/designations/{designation_id}", status_code=204)
def delete_global_designation(designation_id: int, db: DB, current_user: CurrentUser) -> None:
    require_system_admin(current_user)
    item = db.get(GlobalDesignation, designation_id)
    if item is None: raise HTTPException(status_code=404, detail="Designation not found")
    for profile in db.scalars(select(UserProfile).where(UserProfile.professional_title == item.name)).all(): profile.professional_title = None
    for allocation in db.scalars(select(TeamMember).where(TeamMember.designation == item.name)).all(): allocation.designation = ""
    for manager in db.scalars(select(TeamManager).where(TeamManager.designation == item.name)).all(): manager.designation = ""
    db.delete(item); db.commit()


def global_team_manager(db: DB, user_id: int) -> tuple[User, str]:
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id, User.is_active.is_(True), User.is_member.is_(True)))
    if user is None: raise HTTPException(status_code=400, detail="Select an active Member or Admin as team manager")
    completion, _ = profile_completion(user, user.profile)
    if completion < 50: raise HTTPException(status_code=400, detail=f"This member's profile is only {completion}% complete. At least 50% profile completion is required before project or team allocation.")
    designation = user.profile.professional_title if user.profile else None
    if not designation or db.scalar(select(GlobalDesignation.id).where(GlobalDesignation.name == designation)) is None: raise HTTPException(status_code=400, detail="Assign the manager's department and designation first")
    return user, designation


def ensure_single_team_affiliation(db: DB, user_id: int, team_id: int | None = None) -> None:
    """A manager or regular member may be affiliated with one global team only."""
    membership = db.scalar(
        select(GlobalTeamMember)
        .options(selectinload(GlobalTeamMember.team))
        .where(GlobalTeamMember.user_id == user_id)
    )
    if membership and membership.team_id != team_id:
        raise HTTPException(
            status_code=409,
            detail=f"This person already belongs to {membership.team.name}. Remove them from that team first.",
        )
    management = db.scalar(
        select(TeamManager)
        .options(selectinload(TeamManager.team))
        .where(TeamManager.user_id == user_id)
    )
    if management and management.team_id != team_id:
        raise HTTPException(
            status_code=409,
            detail=f"This person already manages {management.team.name}. Assign another manager to that team first.",
        )


@router.get("/teams", response_model=list[TeamRead])
def list_global_teams(db: DB, current_user: CurrentUser) -> list[Team]:
    require_system_admin(current_user)
    return list(db.scalars(select(Team).options(selectinload(Team.manager_record).selectinload(TeamManager.user)).order_by(Team.name)).all())


@router.post("/teams", response_model=TeamRead, status_code=201)
def create_global_team(payload: TeamCreate, db: DB, current_user: CurrentUser) -> Team:
    require_system_admin(current_user); _, manager_designation = global_team_manager(db, payload.manager_user_id)
    ensure_single_team_affiliation(db, payload.manager_user_id)
    team = Team(name=payload.name.strip(), description=payload.description, workspace_id=None)
    team.manager_record = TeamManager(user_id=payload.manager_user_id, designation=manager_designation)
    db.add(team); db.flush()
    db.add(GlobalTeamMember(team_id=team.id, user_id=payload.manager_user_id, designation=manager_designation))
    sync_scoped_conversation_access(db, payload.manager_user_id, active=True, team_id=team.id, global_team=True)
    db.commit(); db.refresh(team)
    return team


@router.patch("/teams/{team_id}", response_model=TeamRead)
def update_global_team(team_id: int, payload: TeamUpdate, db: DB, current_user: CurrentUser) -> Team:
    require_system_admin(current_user)
    team = db.get(Team, team_id)
    if team is None: raise HTTPException(status_code=404, detail="Team not found")
    values = payload.model_dump(exclude_unset=True); manager_user_id = values.pop("manager_user_id", team.manager_user_id); values.pop("manager_designation", None)
    if manager_user_id is None: raise HTTPException(status_code=400, detail="Every team requires a designated manager")
    _, designation = global_team_manager(db, manager_user_id)
    ensure_single_team_affiliation(db, manager_user_id, team.id)
    previous_manager_id = team.manager_user_id
    if team.manager_record is None: team.manager_record = TeamManager()
    team.manager_record.user_id = manager_user_id; team.manager_record.designation = designation.strip()
    if previous_manager_id != manager_user_id:
        if not db.scalar(select(GlobalTeamMember.id).where(GlobalTeamMember.team_id == team.id, GlobalTeamMember.user_id == manager_user_id)):
            db.add(GlobalTeamMember(team_id=team.id, user_id=manager_user_id, designation=designation.strip()))
        sync_scoped_conversation_access(db, manager_user_id, active=True, team_id=team.id, global_team=True)
        if previous_manager_id and not db.scalar(select(GlobalTeamMember.id).where(GlobalTeamMember.team_id == team.id, GlobalTeamMember.user_id == previous_manager_id)):
            sync_scoped_conversation_access(db, previous_manager_id, active=False, team_id=team.id, global_team=True)
    for field, value in values.items(): setattr(team, field, value.strip() if isinstance(value, str) else value)
    db.commit(); db.refresh(team)
    return team


@router.delete("/teams/{team_id}", status_code=204)
def delete_global_team(team_id: int, db: DB, current_user: CurrentUser) -> None:
    require_system_admin(current_user)
    team = db.get(Team, team_id)
    if team is None: raise HTTPException(status_code=404, detail="Team not found")
    db.delete(team); db.commit()


@router.get("/team-members", response_model=list[TeamMemberRead])
def list_global_team_members(db: DB, current_user: CurrentUser) -> list[TeamMember]:
    require_system_admin(current_user)
    return list(db.scalars(select(TeamMember).options(selectinload(TeamMember.user), selectinload(TeamMember.project)).order_by(TeamMember.created_at)).all())


@router.get("/global-team-members", response_model=list[GlobalTeamMemberRead])
def list_global_team_memberships(db: DB, current_user: CurrentUser) -> list[GlobalTeamMember]:
    require_system_admin(current_user)
    memberships = list(db.scalars(
        select(GlobalTeamMember)
        .options(selectinload(GlobalTeamMember.user).selectinload(User.profile))
        .order_by(GlobalTeamMember.created_at)
    ).all())
    changed = False
    for membership in memberships:
        current_designation = membership.user.profile.professional_title if membership.user.profile else None
        if current_designation and membership.designation != current_designation:
            membership.designation = current_designation
            changed = True
    if changed:
        db.commit()
    return memberships


@router.post("/teams/{team_id}/members", response_model=GlobalTeamMemberRead, status_code=201)
def add_global_team_member(team_id: int, payload: GlobalTeamMemberAdd, db: DB, current_user: CurrentUser) -> GlobalTeamMember:
    require_system_admin(current_user)
    team = db.get(Team, team_id)
    if team is None: raise HTTPException(status_code=404, detail="Team not found")
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == payload.user_id, User.is_active.is_(True), User.is_member.is_(True)))
    if user is None: raise HTTPException(status_code=400, detail="Select an active Member or Admin")
    completion, _ = profile_completion(user, user.profile)
    if completion < 50: raise HTTPException(status_code=400, detail=f"This member's profile is only {completion}% complete. At least 50% profile completion is required before team allocation.")
    if not user.profile or not user.profile.department or not user.profile.professional_title:
        raise HTTPException(status_code=400, detail="Assign the member's department and designation first")
    valid = db.scalar(select(GlobalDesignation.id).join(GlobalDepartment).where(GlobalDesignation.name == user.profile.professional_title, GlobalDepartment.name == user.profile.department))
    if valid is None: raise HTTPException(status_code=400, detail="Assign a valid department and designation first")
    ensure_single_team_affiliation(db, user.id, team_id)
    existing_membership = db.scalar(
        select(GlobalTeamMember)
        .options(selectinload(GlobalTeamMember.team))
        .where(GlobalTeamMember.user_id == user.id)
    )
    if existing_membership:
        if existing_membership.team_id == team_id:
            raise HTTPException(status_code=409, detail="Member is already in this team")
        raise HTTPException(
            status_code=409,
            detail=f"Member already belongs to {existing_membership.team.name}. Remove them from that team before assigning another team.",
        )
    membership = GlobalTeamMember(team_id=team_id, user_id=user.id, designation=user.profile.professional_title)
    db.add(membership); sync_scoped_conversation_access(db, user.id, active=True, team_id=team_id, global_team=True); db.commit(); db.refresh(membership)
    return db.scalar(select(GlobalTeamMember).options(selectinload(GlobalTeamMember.user).selectinload(User.profile)).where(GlobalTeamMember.id == membership.id))


@router.delete("/teams/{team_id}/members/{membership_id}", status_code=204)
def remove_global_team_member(team_id: int, membership_id: int, db: DB, current_user: CurrentUser) -> None:
    require_system_admin(current_user)
    membership = db.scalar(select(GlobalTeamMember).where(GlobalTeamMember.id == membership_id, GlobalTeamMember.team_id == team_id))
    if membership is None: raise HTTPException(status_code=404, detail="Team member not found")
    user_id = membership.user_id
    db.delete(membership); db.flush()
    still_manager = db.scalar(select(TeamManager.id).where(TeamManager.team_id == team_id, TeamManager.user_id == user_id))
    if not still_manager:
        sync_scoped_conversation_access(db, user_id, active=False, team_id=team_id, global_team=True)
    db.commit()
