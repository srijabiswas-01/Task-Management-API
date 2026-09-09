from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUser, DB, require_project_admin, require_project_contributor, require_workspace_member
from app.models import (
    BoardColumn,
    ChecklistItem,
    ChecklistAction,
    Comment,
    Project,
    ProjectBoard,
    ProjectStatus,
    Task,
    TaskAssignee,
    TaskBoardPosition,
    TaskSchedule,
    TaskStatus,
    GlobalDesignation,
    GlobalTeamMember,
    OrganizationHoliday,
    TeamMember,
    Team,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from app.core.profile import profile_completion
from app.core.skills import parse_skills
from app.core.member_report import build_member_report
from app.routers.projects import accessible_project
from app.schemas import (
    ChecklistItemCreate,
    ChecklistItemRead,
    ChecklistItemUpdate,
    CommentCreate,
    CommentRead,
    DashboardSummary,
    ProjectRead,
    TaskCreate,
    TaskCompletionUpdate,
    TaskRead,
    TaskUpdate,
    WorkspaceOverviewRead,
)

router = APIRouter(tags=["Tasks"])


@router.get("/members/me/report")
def my_member_report(db: DB, current_user: CurrentUser) -> dict:
    return build_member_report(db, current_user.id, include_financials=False)


def set_task_assignees(
    db: DB, task: Task, project: Project, user_ids: list[int]
) -> None:
    unique_ids = list(dict.fromkeys(user_ids))
    if unique_ids:
        member_ids = set(
            db.scalars(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == project.workspace_id,
                    WorkspaceMember.user_id.in_(unique_ids),
                )
            ).all()
        )
        if member_ids != set(unique_ids):
            raise HTTPException(
                status_code=400,
                detail="Every assignee must be a workspace member",
            )
    selected_ids = set(unique_ids)
    existing_ids = {item.user_id for item in task.task_assignees}
    task.task_assignees[:] = [
        item
        for item in task.task_assignees
        if item.user_id in selected_ids
    ]
    task.task_assignees.extend(
        TaskAssignee(user_id=user_id)
        for user_id in unique_ids
        if user_id not in existing_ids
    )
    task.assignee_id = unique_ids[0] if unique_ids else None


def set_task_assignments(db: DB, task: Task, project: Project, assignments: list[dict]) -> None:
    user_ids = [item["user_id"] for item in assignments]
    if len(user_ids) != len(set(user_ids)):
        raise HTTPException(status_code=400, detail="Each member can be assigned only once per task")
    if assignments:
        pairs = set(db.execute(select(GlobalTeamMember.user_id, GlobalTeamMember.team_id).where(
            GlobalTeamMember.user_id.in_(user_ids)
        )).all())
        requested = {(item["user_id"], item["team_id"]) for item in assignments}
        if not requested.issubset(pairs):
            raise HTTPException(status_code=400, detail="Every assignee must belong to the selected team")
        users = list(db.scalars(select(User).options(selectinload(User.profile)).where(
            User.id.in_(user_ids), User.is_active.is_(True), User.is_member.is_(True)
        )).all())
        if len(users) != len(user_ids):
            raise HTTPException(status_code=400, detail="Every assignee must be an active Member or Admin")
        for user in users:
            completion, _ = profile_completion(user, user.profile)
            if completion < 50 or not user.profile or not user.profile.department or not user.profile.professional_title:
                raise HTTPException(status_code=400, detail=f"{user.name} is not eligible for task assignment")
            workspace_access = db.scalar(select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == project.workspace_id,
                WorkspaceMember.user_id == user.id,
            ))
            if workspace_access is None:
                db.add(WorkspaceMember(workspace_id=project.workspace_id, user_id=user.id, role=WorkspaceRole.member, is_active=True))
    task.task_assignees[:] = []
    task.task_assignees.extend(TaskAssignee(
        user_id=item["user_id"], team_id=item["team_id"],
        responsibility=(item.get("responsibility") or "").strip() or None,
        planned_hours=item.get("planned_hours"),
    ) for item in assignments)
    task.assignee_id = user_ids[0] if user_ids else None


def working_days(db: DB, start: date | None, end: date | None) -> int | None:
    if not start or not end:
        return None
    holidays = set(db.scalars(select(OrganizationHoliday.holiday_date).where(
        OrganizationHoliday.is_active.is_(True),
        OrganizationHoliday.holiday_date >= start,
        OrganizationHoliday.holiday_date <= end,
    )).all())
    days = 0
    current = start
    while current <= end:
        if current.weekday() != 6 and current not in holidays:
            days += 1
        current += timedelta(days=1)
    return days


def estimated_assignment_budget(db: DB, assignments: list[dict], total_hours: int | None) -> int | None:
    if not assignments or total_hours is None:
        return None
    users = {user.id: user for user in db.scalars(select(User).options(selectinload(User.profile)).where(
        User.id.in_([item["user_id"] for item in assignments])
    )).all()}
    designations = {item.name: item.hourly_rate for item in db.scalars(select(GlobalDesignation)).all()}
    default_hours = total_hours // len(assignments) if assignments else 0
    return sum((item.get("planned_hours") if item.get("planned_hours") is not None else default_hours) *
               designations.get(users[item["user_id"]].profile.professional_title, 0)
               for item in assignments if item["user_id"] in users and users[item["user_id"]].profile)


@router.get("/projects/{project_id}/task-planning-options")
def task_planning_options(project_id: int, db: DB, current_user: CurrentUser) -> dict:
    require_project_admin(db, project_id, current_user.id)
    project = accessible_project(db, project_id, current_user.id)
    teams = list(db.scalars(select(Team).where(
        (Team.workspace_id.is_(None)) | (Team.workspace_id == project.workspace_id)
    ).order_by(Team.name)).all())
    global_memberships = list(db.scalars(select(GlobalTeamMember).options(
        selectinload(GlobalTeamMember.user).selectinload(User.profile)
    ).where(GlobalTeamMember.team_id.in_([team.id for team in teams])).order_by(GlobalTeamMember.team_id, GlobalTeamMember.user_id)).all())
    legacy_memberships = list(db.scalars(select(TeamMember).options(
        selectinload(TeamMember.user).selectinload(User.profile)
    ).where(TeamMember.team_id.in_([team.id for team in teams])).order_by(TeamMember.team_id, TeamMember.user_id)).all())
    active_statuses = [status for status in TaskStatus if status != TaskStatus.done]
    hourly_rates = {item.name: item.hourly_rate for item in db.scalars(select(GlobalDesignation)).all()}
    task_counts = {
        (user_id, task_project_id): count
        for user_id, task_project_id, count in db.execute(
            select(TaskAssignee.user_id, Task.project_id, func.count(TaskAssignee.id))
            .join(Task)
            .where(Task.status.in_(active_statuses))
            .group_by(TaskAssignee.user_id, Task.project_id)
        ).all()
    }
    members = []
    seen_memberships: set[tuple[int, int]] = set()
    for membership in [*global_memberships, *legacy_memberships]:
        user = membership.user
        membership_key = (membership.team_id, user.id)
        if membership_key in seen_memberships:
            continue
        seen_memberships.add(membership_key)
        if not user.is_active or not user.is_member or not user.profile:
            continue
        completion, _ = profile_completion(user, user.profile)
        current_count = task_counts.get((user.id, project.id), 0)
        other_count = sum(
            count for (user_id, task_project_id), count in task_counts.items()
            if user_id == user.id and task_project_id != project.id
        )
        members.append({"user_id": user.id, "name": user.name, "profile_image": user.profile_image,
            "team_id": membership.team_id, "department": user.profile.department,
            "designation": user.profile.professional_title, "skills": parse_skills(user.profile.skills),
            "hourly_rate": hourly_rates.get(user.profile.professional_title, 0),
            "completion_percent": completion, "current_project_tasks": current_count,
            "other_project_tasks": other_count, "total_active_tasks": current_count + other_count})
    holidays = list(db.scalars(select(OrganizationHoliday).where(OrganizationHoliday.is_active.is_(True)).order_by(OrganizationHoliday.holiday_date)).all())
    return {"working_hours_per_day": 8, "teams": [{"id": team.id, "name": team.name} for team in teams],
        "members": members, "holidays": [{"date": str(item.holiday_date), "name": item.name} for item in holidays]}


def set_task_schedule(task: Task, start_at, end_at) -> None:
    if task.schedule is None:
        task.schedule = TaskSchedule()
    task.schedule.start_at = start_at
    task.schedule.end_at = end_at


def validate_task_project_dates(project: Project, start_date, due_date, start_at, end_at) -> None:
    if ((start_date and start_date < project.start_date) or
        (due_date and due_date > project.end_date) or
        (start_at and start_at.date() < project.start_date) or
        (end_at and end_at.date() > project.end_date)):
        raise HTTPException(status_code=400, detail="Task dates must be within the project dates")


def sync_board_column_to_status(db: DB, task: Task) -> None:
    board = db.scalar(
        select(ProjectBoard).where(ProjectBoard.project_id == task.project_id)
    )
    if board is None:
        return
    column = db.scalar(
        select(BoardColumn).where(
            BoardColumn.board_id == board.id,
            BoardColumn.system_status == task.status.value,
        )
    )
    if column is None:
        if task.status != TaskStatus.done:
            return
        column = db.scalar(
            select(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.position.desc())
        )
        if column is None:
            return
    item = db.scalar(
        select(TaskBoardPosition).where(TaskBoardPosition.task_id == task.id)
    )
    if item is not None and item.column_id == column.id:
        return
    next_position = len(
        db.scalars(
            select(TaskBoardPosition).where(
                TaskBoardPosition.column_id == column.id,
                TaskBoardPosition.task_id != task.id,
            )
        ).all()
    )
    if item is None:
        db.add(
            TaskBoardPosition(
                task_id=task.id,
                column_id=column.id,
                position=next_position,
            )
        )
    else:
        item.column_id = column.id
        item.position = next_position


def move_task_to_board_edge(db: DB, task: Task, completed: bool) -> None:
    board = db.scalar(select(ProjectBoard).where(ProjectBoard.project_id == task.project_id))
    if board is None:
        sync_board_column_to_status(db, task)
        return
    order = BoardColumn.position.desc() if completed else BoardColumn.position.asc()
    column = db.scalar(
        select(BoardColumn).where(BoardColumn.board_id == board.id).order_by(order)
    )
    if column is None:
        return
    item = db.scalar(select(TaskBoardPosition).where(TaskBoardPosition.task_id == task.id))
    next_position = db.scalar(
        select(func.count(TaskBoardPosition.task_id)).where(
            TaskBoardPosition.column_id == column.id,
            TaskBoardPosition.task_id != task.id,
        )
    ) or 0
    if item is None:
        db.add(TaskBoardPosition(task_id=task.id, column_id=column.id, position=next_position))
    else:
        item.column_id = column.id
        item.position = next_position


def accessible_task(db: DB, task_id: int, user_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        accessible_project(db, task.project_id, user_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post(
    "/projects/{project_id}/tasks", response_model=TaskRead, status_code=201
)
def create_task(
    project_id: int,
    payload: TaskCreate,
    db: DB,
    current_user: CurrentUser,
) -> Task:
    require_project_admin(db, project_id, current_user.id)
    project = accessible_project(db, project_id, current_user.id)
    values = payload.model_dump()
    assignee_ids = values.pop("assignee_ids")
    assignments = values.pop("assignments")
    checklist = values.pop("checklist")
    legacy_assignee = values.pop("assignee_id")
    start_at = values.pop("start_at")
    end_at = values.pop("end_at")
    validate_task_project_dates(project, values.get("start_date"), values.get("due_date"), start_at, end_at)
    calculated_days = working_days(db, values.get("start_date"), values.get("due_date"))
    if calculated_days is not None:
        values["estimated_days"] = calculated_days
        if values.get("estimated_hours") is None:
            values["estimated_hours"] = calculated_days * 8
    if values.get("planned_budget") is None and assignments:
        values["planned_budget"] = estimated_assignment_budget(db, assignments, values.get("estimated_hours"))
    if not assignee_ids and legacy_assignee is not None:
        assignee_ids = [legacy_assignee]
    task = Task(
        project_id=project_id,
        reporter_id=current_user.id,
        **values,
    )
    if assignments:
        set_task_assignments(db, task, project, assignments)
    else:
        set_task_assignees(db, task, project, assignee_ids)
    set_task_schedule(task, start_at, end_at)
    db.add(task)
    db.flush()
    for position, text_value in enumerate(dict.fromkeys(item.strip() for item in checklist if item.strip())):
        item = ChecklistItem(task_id=task.id, text=text_value, position=position)
        item.actions.append(ChecklistAction(user_id=current_user.id, action="created"))
        db.add(item)
    if checklist:
        db.flush()
        update_checklist_progress(db, task.id)
    db.commit()
    db.refresh(task)
    return task


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_tasks(
    project_id: int,
    db: DB,
    current_user: CurrentUser,
    status: TaskStatus | None = None,
    assignee_id: int | None = None,
    sprint_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Task]:
    accessible_project(db, project_id, current_user.id)
    query = select(Task).where(Task.project_id == project_id)
    if status is not None:
        query = query.where(Task.status == status)
    if assignee_id is not None:
        query = query.where(Task.id.in_(
            select(TaskAssignee.task_id).where(TaskAssignee.user_id == assignee_id)
        ))
    if sprint_id is not None:
        query = query.where(Task.sprint_id == sprint_id)
    return list(db.scalars(query.order_by(Task.created_at.desc()).limit(limit)).all())


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: DB, current_user: CurrentUser) -> Task:
    return accessible_task(db, task_id, current_user.id)


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: DB,
    current_user: CurrentUser,
) -> Task:
    task = accessible_task(db, task_id, current_user.id)
    require_project_admin(db, task.project_id, current_user.id)
    project = accessible_project(db, task.project_id, current_user.id)
    values = payload.model_dump(exclude_unset=True)
    assignee_ids = values.pop("assignee_ids", None)
    assignments = values.pop("assignments", None)
    legacy_assignee = values.pop("assignee_id", None)
    has_schedule = "start_at" in values or "end_at" in values
    start_at = values.pop("start_at", task.start_at)
    end_at = values.pop("end_at", task.end_at)
    validate_task_project_dates(
        project,
        values.get("start_date", task.start_date),
        values.get("due_date", task.due_date),
        start_at,
        end_at,
    )
    calculated_days = working_days(db, values.get("start_date", task.start_date), values.get("due_date", task.due_date))
    if calculated_days is not None:
        values["estimated_days"] = calculated_days
        if "estimated_hours" not in values:
            values["estimated_hours"] = calculated_days * 8
    if assignments is not None:
        set_task_assignments(db, task, project, assignments)
        if "planned_budget" not in values:
            values["planned_budget"] = estimated_assignment_budget(db, assignments, values.get("estimated_hours", task.estimated_hours))
    elif assignee_ids is not None:
        set_task_assignees(db, task, project, assignee_ids)
    elif legacy_assignee is not None:
        set_task_assignees(db, task, project, [legacy_assignee])
    if has_schedule:
        set_task_schedule(task, start_at, end_at)
    if values.get("status") == TaskStatus.done:
        checklist_items = list(db.scalars(select(ChecklistItem).where(ChecklistItem.task_id == task.id)).all())
        if checklist_items and any(not item.is_done for item in checklist_items):
            raise HTTPException(status_code=409, detail="Complete all checklist items before marking this task as done")
        values["progress"] = 100
    for field, value in values.items():
        setattr(task, field, value)
    checklist_items = list(db.scalars(select(ChecklistItem).where(ChecklistItem.task_id == task.id)).all())
    if checklist_items:
        task.progress = round(sum(item.is_done for item in checklist_items) / len(checklist_items) * 100)
        task.status = TaskStatus.done if task.progress == 100 else (TaskStatus.backlog if task.status == TaskStatus.done else task.status)
    if "status" in values:
        sync_board_column_to_status(db, task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/completion", response_model=TaskRead)
def update_task_completion(
    task_id: int,
    payload: TaskCompletionUpdate,
    db: DB,
    current_user: CurrentUser,
) -> Task:
    task = accessible_task(db, task_id, current_user.id)
    require_project_contributor(db, task.project_id, current_user.id)
    checklist_items = list(
        db.scalars(select(ChecklistItem).where(ChecklistItem.task_id == task.id)).all()
    )
    if payload.is_completed and checklist_items and any(not item.is_done for item in checklist_items):
        raise HTTPException(
            status_code=409,
            detail="Complete all checklist items before marking this task as done",
        )
    for item in checklist_items if not payload.is_completed else []:
        if item.is_done == payload.is_completed:
            continue
        item.is_done = payload.is_completed
        item.actions.append(
            ChecklistAction(
                user_id=current_user.id,
                action="completed" if payload.is_completed else "reopened",
            )
        )
    task.status = TaskStatus.done if payload.is_completed else TaskStatus.backlog
    task.progress = 100 if payload.is_completed else 0
    move_task_to_board_edge(db, task, payload.is_completed)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: DB, current_user: CurrentUser) -> None:
    task = accessible_task(db, task_id, current_user.id)
    require_project_admin(db, task.project_id, current_user.id)
    db.delete(task)
    db.commit()


@router.post(
    "/tasks/{task_id}/comments", response_model=CommentRead, status_code=201
)
def create_comment(
    task_id: int,
    payload: CommentCreate,
    db: DB,
    current_user: CurrentUser,
) -> Comment:
    task = accessible_task(db, task_id, current_user.id)
    require_project_contributor(db, task.project_id, current_user.id)
    comment = Comment(
        task_id=task_id, author_id=current_user.id, body=payload.body.strip()
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/tasks/{task_id}/comments", response_model=list[CommentRead])
def list_comments(
    task_id: int, db: DB, current_user: CurrentUser
) -> list[Comment]:
    accessible_task(db, task_id, current_user.id)
    return list(
        db.scalars(
            select(Comment)
            .where(Comment.task_id == task_id)
            .order_by(Comment.created_at)
        ).all()
    )


@router.delete("/tasks/{task_id}/comments/{comment_id}", status_code=204)
def delete_comment(
    task_id: int, comment_id: int, db: DB, current_user: CurrentUser
) -> None:
    accessible_task(db, task_id, current_user.id)
    comment = db.scalar(
        select(Comment).where(Comment.id == comment_id, Comment.task_id == task_id)
    )
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_id != current_user.id and not current_user.is_system_admin:
        raise HTTPException(
            status_code=403,
            detail="Only the comment author or an Admin can delete this comment",
        )
    db.delete(comment)
    db.commit()


@router.get(
    "/tasks/{task_id}/checklist",
    response_model=list[ChecklistItemRead],
)
def list_checklist(
    task_id: int, db: DB, current_user: CurrentUser
) -> list[ChecklistItem]:
    accessible_task(db, task_id, current_user.id)
    return list(
        db.scalars(
            select(ChecklistItem)
            .options(selectinload(ChecklistItem.actions))
            .where(ChecklistItem.task_id == task_id)
            .order_by(ChecklistItem.position)
        ).all()
    )


@router.post(
    "/tasks/{task_id}/checklist",
    response_model=ChecklistItemRead,
    status_code=201,
)
def create_checklist_item(
    task_id: int,
    payload: ChecklistItemCreate,
    db: DB,
    current_user: CurrentUser,
) -> ChecklistItem:
    task = accessible_task(db, task_id, current_user.id)
    require_project_admin(db, task.project_id, current_user.id)
    position = len(
        db.scalars(
            select(ChecklistItem).where(ChecklistItem.task_id == task_id)
        ).all()
    )
    item = ChecklistItem(
        task_id=task_id,
        text=payload.text.strip(),
        position=position,
    )
    item.actions.append(ChecklistAction(user_id=current_user.id, action="created"))
    db.add(item)
    db.flush()
    update_checklist_progress(db, task_id)
    db.commit()
    db.refresh(item)
    return item


def update_checklist_progress(db: DB, task_id: int) -> None:
    items = list(
        db.scalars(
            select(ChecklistItem).where(ChecklistItem.task_id == task_id)
        ).all()
    )
    task = db.get(Task, task_id)
    if task is not None:
        task.progress = (
            round(sum(1 for item in items if item.is_done) / len(items) * 100)
            if items
            else 0
        )
        if items and all(item.is_done for item in items):
            task.status = TaskStatus.done
            move_task_to_board_edge(db, task, True)
        elif task.status == TaskStatus.done:
            task.status = TaskStatus.backlog
            move_task_to_board_edge(db, task, False)


@router.patch(
    "/tasks/{task_id}/checklist/{item_id}",
    response_model=ChecklistItemRead,
)
def update_checklist_item(
    task_id: int,
    item_id: int,
    payload: ChecklistItemUpdate,
    db: DB,
    current_user: CurrentUser,
) -> ChecklistItem:
    task = accessible_task(db, task_id, current_user.id)
    values = payload.model_dump(exclude_unset=True)
    if set(values) == {"is_done"}:
        require_project_contributor(db, task.project_id, current_user.id)
    else:
        require_project_admin(db, task.project_id, current_user.id)
    item = db.scalar(
        select(ChecklistItem).where(
            ChecklistItem.id == item_id,
            ChecklistItem.task_id == task_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    changed_done = "is_done" in values and values["is_done"] != item.is_done
    for field, value in values.items():
        setattr(item, field, value.strip() if field == "text" else value)
    if changed_done:
        item.actions.append(ChecklistAction(
            user_id=current_user.id,
            action="completed" if item.is_done else "reopened",
        ))
    update_checklist_progress(db, task_id)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/tasks/{task_id}/checklist/{item_id}",
    status_code=204,
)
def delete_checklist_item(
    task_id: int,
    item_id: int,
    db: DB,
    current_user: CurrentUser,
) -> None:
    task = accessible_task(db, task_id, current_user.id)
    require_project_admin(db, task.project_id, current_user.id)
    item = db.scalar(
        select(ChecklistItem).where(
            ChecklistItem.id == item_id,
            ChecklistItem.task_id == task_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    db.delete(item)
    db.flush()
    update_checklist_progress(db, task_id)
    db.commit()


@router.get(
    "/workspaces/{workspace_id}/dashboard", response_model=DashboardSummary
)
def dashboard(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> DashboardSummary:
    membership = require_workspace_member(db, workspace_id, current_user.id)
    project_ids_query = select(Project.id).where(Project.workspace_id == workspace_id)
    if membership.role != WorkspaceRole.admin:
        allocated_project_ids = select(TeamMember.project_id).where(
            TeamMember.user_id == current_user.id
        )
        project_ids_query = project_ids_query.where(
            (Project.project_manager_id == current_user.id) |
            Project.id.in_(allocated_project_ids)
        )
    project_ids = list(db.scalars(project_ids_query).all())
    projects = db.scalar(
        select(func.count(Project.id)).where(Project.id.in_(project_ids))
    ) or 0
    active_projects = db.scalar(
        select(func.count(Project.id)).where(
            Project.id.in_(project_ids),
            Project.status == ProjectStatus.active,
        )
    ) or 0
    task_scope = select(Task.id).join(Project).where(
        Project.id.in_(project_ids)
    )
    tasks = db.scalar(select(func.count()).select_from(task_scope.subquery())) or 0
    completed = db.scalar(
        select(func.count(Task.id))
        .join(Project)
        .where(
            Project.id.in_(project_ids),
            Task.status == TaskStatus.done,
        )
    ) or 0
    overdue = db.scalar(
        select(func.count(Task.id))
        .join(Project)
        .where(
            Project.id.in_(project_ids),
            Task.due_date < date.today(),
            Task.status != TaskStatus.done,
        )
    ) or 0
    return DashboardSummary(
        projects=projects,
        active_projects=active_projects,
        tasks=tasks,
        completed_tasks=completed,
        overdue_tasks=overdue,
        completion_percent=round((completed / tasks * 100) if tasks else 0, 2),
    )


@router.get(
    "/workspaces/{workspace_id}/overview-data",
    response_model=WorkspaceOverviewRead,
)
def workspace_overview_data(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> WorkspaceOverviewRead:
    """Return the small, commonly needed workspace landing-page payload."""
    membership = require_workspace_member(db, workspace_id, current_user.id)
    project_query = select(Project).where(Project.workspace_id == workspace_id)
    if membership.role != WorkspaceRole.admin:
        allocated_ids = select(TeamMember.project_id).where(
            TeamMember.user_id == current_user.id
        )
        task_project_ids = select(Task.project_id).join(TaskAssignee).where(
            TaskAssignee.user_id == current_user.id
        )
        project_query = project_query.where(
            (Project.project_manager_id == current_user.id)
            | Project.id.in_(allocated_ids)
            | Project.id.in_(task_project_ids)
        )
    projects = list(db.scalars(project_query.order_by(Project.created_at.desc())).all())
    project_ids = [project.id for project in projects]
    active_projects = db.scalar(select(func.count(Project.id)).where(
        Project.id.in_(project_ids), Project.status == ProjectStatus.active
    )) or 0
    task_count = db.scalar(select(func.count(Task.id)).where(Task.project_id.in_(project_ids))) or 0
    completed = db.scalar(select(func.count(Task.id)).where(
        Task.project_id.in_(project_ids), Task.status == TaskStatus.done
    )) or 0
    overdue = db.scalar(select(func.count(Task.id)).where(
        Task.project_id.in_(project_ids), Task.due_date < date.today(),
        Task.status != TaskStatus.done,
    )) or 0
    return WorkspaceOverviewRead(
        projects=[ProjectRead.model_validate(project) for project in projects],
        dashboard=DashboardSummary(
            projects=len(projects), active_projects=active_projects, tasks=task_count,
            completed_tasks=completed, overdue_tasks=overdue,
            completion_percent=round((completed / task_count * 100) if task_count else 0, 2),
        ),
    )
