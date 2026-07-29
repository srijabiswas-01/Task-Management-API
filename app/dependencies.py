from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import User, WorkspaceMember, WorkspaceRole

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

