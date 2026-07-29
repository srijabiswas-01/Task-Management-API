from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import CurrentUser, DB, require_project_admin
from app.models import (
    BoardColumn,
    Project,
    ProjectBoard,
    Task,
    TaskBoardPosition,
    TaskStatus,
)
from app.routers.projects import accessible_project
from app.schemas import (
    BoardColumnCreate,
    BoardColumnRead,
    BoardColumnUpdate,
    BoardRead,
    BoardSetup,
    ColumnReorder,
    TaskMove,
)

router = APIRouter(tags=["Boards"])

KANBAN_COLUMNS = [
    ("Backlog", "#8b97ac", "backlog"),
    ("To do", "#6676d9", "todo"),
    ("In progress", "#e59a29", "in_progress"),
    ("Review", "#8557d8", "review"),
    ("Testing", "#27a0a0", "testing"),
    ("Done", "#23a06b", "done"),
]
SCRUM_COLUMNS = [
    ("Product backlog", "#8b97ac", "backlog"),
    ("Sprint backlog", "#6676d9", "todo"),
    ("In progress", "#e59a29", "in_progress"),
    ("Review", "#8557d8", "review"),
    ("Done", "#23a06b", "done"),
]


def _template(framework: str) -> list[tuple[str, str, str]]:
    return SCRUM_COLUMNS if framework == "scrum" else KANBAN_COLUMNS


def _board_for_project(db: Session, project_id: int) -> ProjectBoard | None:
    return db.scalar(select(ProjectBoard).where(ProjectBoard.project_id == project_id))


def ensure_board(db: Session, project: Project, framework: str = "kanban") -> ProjectBoard:
    board = _board_for_project(db, project.id)
    if board is None:
        board = ProjectBoard(project_id=project.id, framework=framework)
        db.add(board)
        db.flush()
        for position, (name, color, status) in enumerate(_template(framework)):
            db.add(
                BoardColumn(
                    board_id=board.id,
                    name=name,
                    color=color,
                    position=position,
                    system_status=status,
                )
            )
        db.flush()
    sync_task_positions(db, project, board)
    return board


def sync_task_positions(db: Session, project: Project, board: ProjectBoard) -> None:
    columns = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.position)
        ).all()
    )
    if not columns:
        return
    by_status = {column.system_status: column for column in columns if column.system_status}
    existing_task_ids = set(
        db.scalars(
            select(TaskBoardPosition.task_id)
            .join(BoardColumn)
            .where(BoardColumn.board_id == board.id)
        ).all()
    )
    column_counts = {
        column.id: len(
            db.scalars(
                select(TaskBoardPosition).where(
                    TaskBoardPosition.column_id == column.id
                )
            ).all()
        )
        for column in columns
    }
    for task in db.scalars(select(Task).where(Task.project_id == project.id)).all():
        if task.id in existing_task_ids:
            continue
        column = by_status.get(task.status.value, columns[0])
        db.add(
            TaskBoardPosition(
                task_id=task.id,
                column_id=column.id,
                position=column_counts[column.id],
            )
        )
        column_counts[column.id] += 1
    db.flush()


def board_response(db: Session, board: ProjectBoard) -> BoardRead:
    columns = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.position)
        ).all()
    )
    positions = db.scalars(
        select(TaskBoardPosition)
        .join(BoardColumn)
        .where(BoardColumn.board_id == board.id)
    ).all()
    return BoardRead(
        id=board.id,
        project_id=board.project_id,
        framework=board.framework,
        columns=[BoardColumnRead.model_validate(column) for column in columns],
        task_positions={
            item.task_id: {"column_id": item.column_id, "position": item.position}
            for item in positions
        },
    )


@router.get("/projects/{project_id}/board", response_model=BoardRead)
def get_board(project_id: int, db: DB, current_user: CurrentUser) -> BoardRead:
    project = accessible_project(db, project_id, current_user.id)
    board = ensure_board(db, project)
    db.commit()
    return board_response(db, board)


@router.put("/projects/{project_id}/board", response_model=BoardRead)
def setup_board(
    project_id: int,
    payload: BoardSetup,
    db: DB,
    current_user: CurrentUser,
) -> BoardRead:
    require_project_admin(db, project_id, current_user.id)
    project = accessible_project(db, project_id, current_user.id)
    board = _board_for_project(db, project.id)
    if board is None:
        board = ensure_board(db, project, payload.framework)
    elif payload.reset:
        task_positions = list(
            db.scalars(
                select(TaskBoardPosition)
                .join(BoardColumn)
                .where(BoardColumn.board_id == board.id)
            ).all()
        )
        for item in task_positions:
            db.delete(item)
        for column in list(
            db.scalars(
                select(BoardColumn).where(BoardColumn.board_id == board.id)
            ).all()
        ):
            db.delete(column)
        db.flush()
        board.framework = payload.framework
        for position, (name, color, status) in enumerate(_template(payload.framework)):
            db.add(
                BoardColumn(
                    board_id=board.id,
                    name=name,
                    color=color,
                    position=position,
                    system_status=status,
                )
            )
        db.flush()
        sync_task_positions(db, project, board)
    elif board.framework != payload.framework:
        has_positions = db.scalar(
            select(TaskBoardPosition.id)
            .join(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .limit(1)
        )
        if has_positions:
            raise HTTPException(
                status_code=409,
                detail="Move or remove board tasks before changing framework",
            )
        for column in list(
            db.scalars(
                select(BoardColumn).where(BoardColumn.board_id == board.id)
            ).all()
        ):
            db.delete(column)
        db.flush()
        board.framework = payload.framework
        for position, (name, color, status) in enumerate(_template(payload.framework)):
            db.add(
                BoardColumn(
                    board_id=board.id,
                    name=name,
                    color=color,
                    position=position,
                    system_status=status,
                )
            )
        db.flush()
        sync_task_positions(db, project, board)
    db.commit()
    return board_response(db, board)


@router.post(
    "/projects/{project_id}/board/columns",
    response_model=BoardColumnRead,
    status_code=201,
)
def create_column(
    project_id: int,
    payload: BoardColumnCreate,
    db: DB,
    current_user: CurrentUser,
) -> BoardColumn:
    require_project_admin(db, project_id, current_user.id)
    project = accessible_project(db, project_id, current_user.id)
    board = ensure_board(db, project)
    position = len(
        db.scalars(select(BoardColumn).where(BoardColumn.board_id == board.id)).all()
    )
    column = BoardColumn(
        board_id=board.id,
        name=payload.name.strip(),
        color=payload.color,
        position=position,
        system_status=payload.system_status,
    )
    db.add(column)
    db.commit()
    db.refresh(column)
    return column


def _accessible_column(
    db: Session, project_id: int, column_id: int
) -> BoardColumn:
    column = db.scalar(
        select(BoardColumn)
        .join(ProjectBoard)
        .where(
            BoardColumn.id == column_id,
            ProjectBoard.project_id == project_id,
        )
    )
    if column is None:
        raise HTTPException(status_code=404, detail="Board column not found")
    return column


@router.patch(
    "/projects/{project_id}/board/columns/{column_id}",
    response_model=BoardColumnRead,
)
def update_column(
    project_id: int,
    column_id: int,
    payload: BoardColumnUpdate,
    db: DB,
    current_user: CurrentUser,
) -> BoardColumn:
    require_project_admin(db, project_id, current_user.id)
    accessible_project(db, project_id, current_user.id)
    column = _accessible_column(db, project_id, column_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(column, field, value.strip() if field == "name" else value)
    db.commit()
    db.refresh(column)
    return column


@router.delete("/projects/{project_id}/board/columns/{column_id}", status_code=204)
def delete_column(
    project_id: int,
    column_id: int,
    db: DB,
    current_user: CurrentUser,
    move_to: int | None = Query(default=None),
) -> None:
    require_project_admin(db, project_id, current_user.id)
    accessible_project(db, project_id, current_user.id)
    column = _accessible_column(db, project_id, column_id)
    columns = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == column.board_id)
            .order_by(BoardColumn.position)
        ).all()
    )
    if len(columns) == 1:
        raise HTTPException(status_code=409, detail="A board needs at least one column")
    target = (
        _accessible_column(db, project_id, move_to)
        if move_to is not None
        else next(item for item in columns if item.id != column.id)
    )
    moving = list(
        db.scalars(
            select(TaskBoardPosition)
            .where(TaskBoardPosition.column_id == column.id)
            .order_by(TaskBoardPosition.position)
        ).all()
    )
    target_count = len(
        db.scalars(
            select(TaskBoardPosition).where(TaskBoardPosition.column_id == target.id)
        ).all()
    )
    for offset, item in enumerate(moving):
        item.column_id = target.id
        item.position = target_count + offset
    db.delete(column)
    db.flush()
    remaining = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == target.board_id)
            .order_by(BoardColumn.position)
        ).all()
    )
    for position, item in enumerate(remaining):
        item.position = position
    db.commit()


@router.put("/projects/{project_id}/board/column-order", response_model=BoardRead)
def reorder_columns(
    project_id: int,
    payload: ColumnReorder,
    db: DB,
    current_user: CurrentUser,
) -> BoardRead:
    require_project_admin(db, project_id, current_user.id)
    project = accessible_project(db, project_id, current_user.id)
    board = ensure_board(db, project)
    columns = list(
        db.scalars(select(BoardColumn).where(BoardColumn.board_id == board.id)).all()
    )
    if set(payload.column_ids) != {column.id for column in columns}:
        raise HTTPException(status_code=400, detail="Include every board column once")
    by_id = {column.id: column for column in columns}
    for index, column_id in enumerate(payload.column_ids):
        by_id[column_id].position = 10000 + index
    db.flush()
    for index, column_id in enumerate(payload.column_ids):
        by_id[column_id].position = index
    db.commit()
    return board_response(db, board)


@router.put("/tasks/{task_id}/board-position", response_model=BoardRead)
def move_task(
    task_id: int,
    payload: TaskMove,
    db: DB,
    current_user: CurrentUser,
) -> BoardRead:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_admin(db, task.project_id, current_user.id)
    project = accessible_project(db, task.project_id, current_user.id)
    board = ensure_board(db, project)
    target = _accessible_column(db, project.id, payload.column_id)
    item = db.scalar(
        select(TaskBoardPosition).where(TaskBoardPosition.task_id == task.id)
    )
    if item is None:
        item = TaskBoardPosition(task_id=task.id, column_id=target.id, position=0)
        db.add(item)
        db.flush()
    old_column_id = item.column_id
    item.column_id = target.id
    db.flush()
    target_items = list(
        db.scalars(
            select(TaskBoardPosition)
            .where(
                TaskBoardPosition.column_id == target.id,
                TaskBoardPosition.task_id != task.id,
            )
            .order_by(TaskBoardPosition.position)
        ).all()
    )
    target_items.insert(min(payload.position, len(target_items)), item)
    for index, target_item in enumerate(target_items):
        target_item.position = index
    if old_column_id != target.id:
        old_items = list(
            db.scalars(
                select(TaskBoardPosition)
                .where(TaskBoardPosition.column_id == old_column_id)
                .order_by(TaskBoardPosition.position)
            ).all()
        )
        for index, old_item in enumerate(old_items):
            old_item.position = index
    if target.system_status in {status.value for status in TaskStatus}:
        task.status = TaskStatus(target.system_status)
        if task.status == TaskStatus.done:
            task.progress = 100
    db.commit()
    return board_response(db, board)
