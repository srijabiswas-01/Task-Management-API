from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import (
    CurrentUser,
    DB,
    require_project_admin,
    require_workspace_admin,
    require_workspace_member,
)
from app.models import Project, ProjectBoard, Sprint, TeamMember, WorkspaceMember, WorkspaceRole
from app.schemas import (
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    SprintCreate,
    SprintRead,
    SprintUpdate,
)

router = APIRouter(tags=["Projects"])


def validate_project_manager(db: DB, workspace_id: int, user_id: int) -> None:
    manager = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.role == WorkspaceRole.admin,
    ))
    if manager is None:
        raise HTTPException(status_code=400, detail="Project manager must be a workspace admin")


def accessible_project(db: DB, project_id: int, user_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is not None:
        require_workspace_member(db, project.workspace_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_scrum_board(db: DB, project: Project) -> ProjectBoard:
    board = db.scalar(
        select(ProjectBoard).where(ProjectBoard.project_id == project.id)
    )
    if board is None or board.framework != "scrum":
        raise HTTPException(
            status_code=409,
            detail="Sprints are available only for Scrum projects",
        )
    return board


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=ProjectRead,
    status_code=201,
)
def create_project(
    workspace_id: int,
    payload: ProjectCreate,
    db: DB,
    current_user: CurrentUser,
) -> Project:
    require_workspace_admin(db, workspace_id, current_user.id)
    values = payload.model_dump()
    values["project_manager_id"] = values.get("project_manager_id") or current_user.id
    validate_project_manager(db, workspace_id, values["project_manager_id"])
    project = Project(workspace_id=workspace_id, **values)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get(
    "/workspaces/{workspace_id}/projects", response_model=list[ProjectRead]
)
def list_projects(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[Project]:
    require_workspace_member(db, workspace_id, current_user.id)
    query = select(Project).where(Project.workspace_id == workspace_id)
    return list(db.scalars(query.order_by(Project.created_at.desc())).all())


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: DB, current_user: CurrentUser) -> Project:
    return accessible_project(db, project_id, current_user.id)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: DB,
    current_user: CurrentUser,
) -> Project:
    project = accessible_project(db, project_id, current_user.id)
    require_project_admin(db, project.id, current_user.id)
    values = payload.model_dump(exclude_unset=True)
    if "project_manager_id" in values:
        if values["project_manager_id"] is None:
            raise HTTPException(status_code=400, detail="Every project requires a project admin")
        validate_project_manager(db, project.workspace_id, values["project_manager_id"])
    for field, value in values.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    db: DB,
    current_user: CurrentUser,
) -> None:
    project = accessible_project(db, project_id, current_user.id)
    require_project_admin(db, project.id, current_user.id)
    db.delete(project)
    db.commit()


@router.post(
    "/projects/{project_id}/sprints",
    response_model=SprintRead,
    status_code=201,
)
def create_sprint(
    project_id: int,
    payload: SprintCreate,
    db: DB,
    current_user: CurrentUser,
) -> Sprint:
    project = accessible_project(db, project_id, current_user.id)
    require_project_admin(db, project.id, current_user.id)
    require_scrum_board(db, project)
    if payload.is_active:
        for current in db.scalars(
            select(Sprint).where(
                Sprint.project_id == project_id,
                Sprint.is_active.is_(True),
            )
        ).all():
            current.is_active = False
    sprint = Sprint(project_id=project_id, **payload.model_dump())
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    return sprint


@router.get("/projects/{project_id}/sprints", response_model=list[SprintRead])
def list_sprints(
    project_id: int, db: DB, current_user: CurrentUser
) -> list[Sprint]:
    project = accessible_project(db, project_id, current_user.id)
    require_scrum_board(db, project)
    return list(
        db.scalars(
            select(Sprint)
            .where(Sprint.project_id == project_id)
            .order_by(Sprint.created_at.desc())
        ).all()
    )


@router.patch("/sprints/{sprint_id}", response_model=SprintRead)
def update_sprint(
    sprint_id: int,
    payload: SprintUpdate,
    db: DB,
    current_user: CurrentUser,
) -> Sprint:
    sprint = db.get(Sprint, sprint_id)
    if sprint is None:
        raise HTTPException(status_code=404, detail="Sprint not found")
    project = accessible_project(db, sprint.project_id, current_user.id)
    require_project_admin(db, project.id, current_user.id)
    require_scrum_board(db, project)
    values = payload.model_dump(exclude_unset=True)
    if values.get("is_active"):
        for current in db.scalars(
            select(Sprint).where(
                Sprint.project_id == project.id,
                Sprint.id != sprint.id,
                Sprint.is_active.is_(True),
            )
        ).all():
            current.is_active = False
    for field, value in values.items():
        setattr(sprint, field, value)
    db.commit()
    db.refresh(sprint)
    return sprint
