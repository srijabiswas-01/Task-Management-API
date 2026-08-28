from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.profile import profile_completion
from app.core.skills import parse_skills
from app.dependencies import CurrentUser, DB
from app.models import Project, TeamMember, User
from app.schemas import SkillMemberRead, UserDirectoryRead

router = APIRouter(prefix="/admin", tags=["System administration"])


def require_system_admin(current_user: CurrentUser) -> None:
    if not current_user.is_system_admin:
        raise HTTPException(status_code=403, detail="System administrator access required")


def global_users(db: DB) -> list[User]:
    return list(db.scalars(
        select(User).options(selectinload(User.profile)).order_by(
            User.is_active.desc(), User.name, User.email
        )
    ).all())


@router.get("/users", response_model=list[UserDirectoryRead])
def list_global_users(db: DB, current_user: CurrentUser) -> list[UserDirectoryRead]:
    require_system_admin(current_user)
    allocation_rows = db.execute(
        select(TeamMember.user_id, Project.name)
        .join(Project, Project.id == TeamMember.project_id)
        .distinct()
    ).all()
    projects: dict[int, list[str]] = {}
    for user_id, project_name in allocation_rows:
        projects.setdefault(user_id, []).append(project_name)
    result: list[UserDirectoryRead] = []
    for user in global_users(db):
        percent, missing = profile_completion(user, user.profile)
        result.append(UserDirectoryRead(
            user_id=user.id, name=user.name, email=user.email,
            is_active=user.is_active,
            professional_title=user.profile.professional_title if user.profile else None,
            department=user.profile.department if user.profile else None,
            profile_image=user.profile.profile_image if user.profile else None,
            projects=sorted(set(projects.get(user.id, []))),
            completion_percent=percent, missing_fields=missing,
        ))
    return result


@router.get("/skills", response_model=list[SkillMemberRead])
def list_global_skills(db: DB, current_user: CurrentUser) -> list[SkillMemberRead]:
    require_system_admin(current_user)
    project_rows = db.execute(
        select(TeamMember.user_id, TeamMember.project_id).distinct()
    ).all()
    project_ids: dict[int, list[int]] = {}
    for user_id, project_id in project_rows:
        project_ids.setdefault(user_id, []).append(project_id)
    return [SkillMemberRead(
        user_id=user.id, name=user.name, email=user.email,
        professional_title=user.profile.professional_title if user.profile else None,
        department=user.profile.department if user.profile else None,
        profile_image=user.profile.profile_image if user.profile else None,
        skills=parse_skills(user.profile.skills if user.profile else None),
        project_ids=project_ids.get(user.id, []),
    ) for user in global_users(db)]
