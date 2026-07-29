from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import (
    CurrentUser,
    DB,
    require_workspace_admin,
    require_workspace_member,
    require_team_admin,
)
from app.models import Project, Team, TeamMember, User, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas import (
    MemberAdd,
    MemberRead,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberRead,
    TeamRead,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    payload: WorkspaceCreate, db: DB, current_user: CurrentUser
) -> Workspace:
    workspace = Workspace(
        name=payload.name.strip(),
        description=payload.description,
        owner_id=current_user.id,
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=WorkspaceRole.admin,
        )
    )
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(db: DB, current_user: CurrentUser) -> list[Workspace]:
    return list(
        db.scalars(
            select(Workspace)
            .join(WorkspaceMember)
            .where(WorkspaceMember.user_id == current_user.id)
            .order_by(Workspace.created_at.desc())
        ).all()
    )


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner can delete this workspace",
        )
    db.delete(workspace)
    db.commit()


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: DB,
    current_user: CurrentUser,
) -> Workspace:
    require_workspace_admin(db, workspace_id, current_user.id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(
            workspace,
            field,
            value.strip() if field == "name" and value is not None else value,
        )
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> Workspace:
    require_workspace_member(db, workspace_id, current_user.id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.post("/{workspace_id}/members", response_model=MemberRead, status_code=201)
def add_member(
    workspace_id: int,
    payload: MemberAdd,
    db: DB,
    current_user: CurrentUser,
) -> WorkspaceMember:
    require_workspace_admin(db, workspace_id, current_user.id)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        raise HTTPException(
            status_code=404, detail="A registered user with that email was not found"
        )
    existing = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")
    member = WorkspaceMember(
        workspace_id=workspace_id, user_id=user.id, role=payload.role
    )
    db.add(member)
    db.commit()
    return db.scalar(
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user))
        .where(WorkspaceMember.id == member.id)
    )


@router.get("/{workspace_id}/members", response_model=list[MemberRead])
def list_members(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[WorkspaceMember]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(
        db.scalars(
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.user))
            .where(WorkspaceMember.workspace_id == workspace_id)
        ).all()
    )


@router.post("/{workspace_id}/teams", response_model=TeamRead, status_code=201)
def create_team(
    workspace_id: int,
    payload: TeamCreate,
    db: DB,
    current_user: CurrentUser,
) -> Team:
    require_workspace_admin(db, workspace_id, current_user.id)
    team = Team(workspace_id=workspace_id, **payload.model_dump())
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


@router.get("/{workspace_id}/teams", response_model=list[TeamRead])
def list_teams(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[Team]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(
        db.scalars(
            select(Team)
            .where(Team.workspace_id == workspace_id)
            .order_by(Team.created_at.desc())
        ).all()
    )


@router.delete("/{workspace_id}/members/{member_id}", status_code=204)
def remove_member(
    workspace_id: int, member_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.user_id == current_user.id:
        raise HTTPException(status_code=409, detail="You cannot remove yourself")
    allocations = list(
        db.scalars(
            select(TeamMember)
            .join(Team)
            .where(
                Team.workspace_id == workspace_id,
                TeamMember.user_id == member.user_id,
            )
        ).all()
    )
    for allocation in allocations:
        db.delete(allocation)
    db.delete(member)
    db.commit()


@router.delete("/{workspace_id}/teams/{team_id}", status_code=204)
def delete_team(
    workspace_id: int, team_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.workspace_id == workspace_id)
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    db.delete(team)
    db.commit()


@router.get(
    "/{workspace_id}/team-members", response_model=list[TeamMemberRead]
)
def list_team_members(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[TeamMember]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(
        db.scalars(
            select(TeamMember)
            .join(Team)
            .options(
                selectinload(TeamMember.user),
                selectinload(TeamMember.project),
            )
            .where(Team.workspace_id == workspace_id)
            .order_by(TeamMember.created_at)
        ).all()
    )


@router.post(
    "/{workspace_id}/teams/{team_id}/members",
    response_model=TeamMemberRead,
    status_code=201,
)
def allocate_team_member(
    workspace_id: int,
    team_id: int,
    payload: TeamMemberAdd,
    db: DB,
    current_user: CurrentUser,
) -> TeamMember:
    team = require_team_admin(db, team_id, current_user.id)
    if team.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Team not found")
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == payload.user_id,
        )
    )
    project = db.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if member is None or project is None:
        raise HTTPException(status_code=400, detail="Invalid member or project")
    existing = db.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == payload.user_id,
            TeamMember.project_id == payload.project_id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Member is already allocated")
    allocation = TeamMember(
        team_id=team_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        designation=payload.designation.strip(),
    )
    db.add(allocation)
    db.commit()
    return db.scalar(
        select(TeamMember)
        .options(
            selectinload(TeamMember.user),
            selectinload(TeamMember.project),
        )
        .where(TeamMember.id == allocation.id)
    )


@router.delete(
    "/{workspace_id}/teams/{team_id}/members/{allocation_id}", status_code=204
)
def remove_team_member(
    workspace_id: int,
    team_id: int,
    allocation_id: int,
    db: DB,
    current_user: CurrentUser,
) -> None:
    team = require_team_admin(db, team_id, current_user.id)
    if team.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Team not found")
    allocation = db.scalar(
        select(TeamMember).where(
            TeamMember.id == allocation_id, TeamMember.team_id == team_id
        )
    )
    if allocation is None:
        raise HTTPException(status_code=404, detail="Team member not found")
    db.delete(allocation)
    db.commit()
