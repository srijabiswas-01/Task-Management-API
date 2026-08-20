from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import Project, Team, TeamMember, User, WorkspaceMember, WorkspaceRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
DB = Annotated[Session, Depends(get_db)]


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DB,
) -> User:
    subject = decode_access_token(token)
    if subject is None or not subject.isdigit():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, int(subject))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_workspace_member(
    db: Session,
    workspace_id: int,
    user_id: int,
) -> WorkspaceMember:
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not membership.is_active:
        raise HTTPException(status_code=403, detail="Your workspace access is inactive")
    if membership.role != WorkspaceRole.admin:
        allocated = db.scalar(
            select(TeamMember.id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(
                Team.workspace_id == workspace_id,
                TeamMember.user_id == user_id,
            )
        )
        managed = db.scalar(select(Project.id).where(
            Project.workspace_id == workspace_id,
            Project.project_manager_id == user_id,
        ))
        if allocated is None and managed is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    return membership


def require_workspace_admin(
    db: Session,
    workspace_id: int,
    user_id: int,
) -> WorkspaceMember:
    membership = require_workspace_member(db, workspace_id, user_id)
    if membership.role != WorkspaceRole.admin:
        raise HTTPException(status_code=403, detail="Workspace admin required")
    return membership


def require_project_admin(
    db: Session, project_id: int, user_id: int
) -> WorkspaceMember:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = require_workspace_member(db, project.workspace_id, user_id)
    if membership.role != WorkspaceRole.admin and project.project_manager_id != user_id:
        raise HTTPException(status_code=403, detail="Project manager required")
    return membership


def require_project_contributor(db: Session, project_id: int, user_id: int) -> WorkspaceMember:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = require_workspace_member(db, project.workspace_id, user_id)
    if membership.role == WorkspaceRole.admin or project.project_manager_id == user_id:
        return membership
    allocated = db.scalar(
        select(TeamMember.id).where(
            TeamMember.project_id == project_id, TeamMember.user_id == user_id
        )
    )
    if allocated is None:
        raise HTTPException(status_code=403, detail="Project allocation required")
    return membership


def require_team_admin(db: Session, team_id: int, user_id: int) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_admin(db, team.workspace_id, user_id)
    return team
