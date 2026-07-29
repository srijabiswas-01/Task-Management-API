from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DB, require_project_admin
from app.models import (
    BoardColumn,
    ChecklistItem,
    Comment,
    Project,
    ProjectBoard,
    ProjectStatus,
    Task,
    TaskAssignee,
    TaskBoardPosition,
    TaskSchedule,
    TaskStatus,
    TeamMember,
    WorkspaceMember,
    WorkspaceRole,
)
from app.routers.projects import accessible_project
from app.schemas import (
    ChecklistItemCreate,
    ChecklistItemRead,
    ChecklistItemUpdate,
    CommentCreate,
    CommentRead,
    DashboardSummary,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)

router = APIRouter(tags=["Tasks"])


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
    task.task_assignees.clear()
    task.task_assignees.extend(
        TaskAssignee(user_id=user_id) for user_id in unique_ids
    )
    task.assignee_id = unique_ids[0] if unique_ids else None


def set_task_schedule(task: Task, start_at, end_at) -> None:
    if task.schedule is None:
        task.schedule = TaskSchedule()
    task.schedule.start_at = start_at
    task.schedule.end_at = end_at


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
        return
    item = db.scalar(
        select(TaskBoardPosition).where(TaskBoardPosition.task_id == task.id)
    )
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


def accessible_task(db: DB, task_id: int, user_id: int) -> Task:
    task = db.scalar(
        select(Task)
        .join(Project)
        .join(
            WorkspaceMember,
            WorkspaceMember.workspace_id == Project.workspace_id,
        )
        .where(Task.id == task_id, WorkspaceMember.user_id == user_id)
    )
    if task is None:
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
    legacy_assignee = values.pop("assignee_id")
    start_at = values.pop("start_at")
    end_at = values.pop("end_at")
    if not assignee_ids and legacy_assignee is not None:
        assignee_ids = [legacy_assignee]
    task = Task(
        project_id=project_id,
        reporter_id=current_user.id,
        **values,
    )
    set_task_assignees(db, task, project, assignee_ids)
    set_task_schedule(task, start_at, end_at)
    db.add(task)
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
        query = query.where(Task.assignee_id == assignee_id)
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
    legacy_assignee = values.pop("assignee_id", None)
    has_schedule = "start_at" in values or "end_at" in values
    start_at = values.pop("start_at", task.start_at)
    end_at = values.pop("end_at", task.end_at)
    if assignee_ids is not None:
        set_task_assignees(db, task, project, assignee_ids)
    elif legacy_assignee is not None:
        set_task_assignees(db, task, project, [legacy_assignee])
    if has_schedule:
        set_task_schedule(task, start_at, end_at)
    if values.get("status") == TaskStatus.done and "progress" not in values:
        values["progress"] = 100
    for field, value in values.items():
        setattr(task, field, value)
    if "status" in values:
        sync_board_column_to_status(db, task)
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
    require_project_admin(db, task.project_id, current_user.id)
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
    db.add(item)
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
    require_project_admin(db, task.project_id, current_user.id)
    item = db.scalar(
        select(ChecklistItem).where(
            ChecklistItem.id == item_id,
            ChecklistItem.task_id == task_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value.strip() if field == "text" else value)
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
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    project_ids_query = select(Project.id).where(Project.workspace_id == workspace_id)
    if membership.role != WorkspaceRole.admin:
        project_ids_query = (
            project_ids_query.join(TeamMember, TeamMember.project_id == Project.id)
            .where(TeamMember.user_id == current_user.id)
            .distinct()
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
