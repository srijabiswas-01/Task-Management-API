from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token, hash_password, verify_password
from app.core.skills import normalize_skills, parse_skills
from app.core.profile import profile_completion, validate_profile_image
from app.dependencies import CurrentUser, DB
from app.models import GlobalDepartment, GlobalDesignation, Project, Task, TaskAssignee, TeamMember, User, UserProfile
from app.schemas import Token, UserProfileRead, UserProfileUpdate, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])


def lock_registration_bootstrap(db: DB) -> None:
    """Serialize the empty-users check across application processes."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        # SQLite has no row-level locks. BEGIN IMMEDIATE takes the single writer
        # reservation before we inspect users, so a second registration waits.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    elif dialect == "postgresql":
        # A transaction-scoped advisory lock avoids adding bootstrap state to
        # the schema and is automatically released on commit or rollback.
        db.execute(text("SELECT pg_advisory_xact_lock(724031905)"))


@router.post("/register", response_model=UserRead, status_code=201)
def register(payload: UserRegister, db: DB) -> User:
    hashed_password = hash_password(payload.password)
    lock_registration_bootstrap(db)
    email = str(payload.email).strip().lower()
    exists = db.scalar(select(User).where(func.lower(User.email) == email))
    if exists:
        raise HTTPException(status_code=409, detail="Email is already registered")
    # The first account bootstraps the installation. Later accounts require
    # approval by an existing workspace administrator.
    is_first_account = db.scalar(select(func.count(User.id))) == 0
    user = User(
        name=payload.name.strip(),
        email=email,
        hashed_password=hashed_password,
        is_active=is_first_account,
        is_system_admin=is_first_account,
        is_member=is_first_account,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DB,
) -> Token:
    email = form.username.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your registration is waiting for administrator approval.",
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> User:
    return current_user


@router.get("/skill-catalog", response_model=list[str])
def skill_catalog(db: DB, current_user: CurrentUser) -> list[str]:
    values = db.scalars(
        select(UserProfile.skills).join(User).where(User.is_active.is_(True))
    ).all()
    catalog: dict[str, str] = {}
    for value in values:
        for skill in parse_skills(value):
            catalog.setdefault(skill.casefold(), skill)
    return sorted(catalog.values(), key=str.casefold)


def profile_response(db: DB, user: User) -> UserProfileRead:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    allocated = db.scalars(
        select(Project.name).join(TeamMember, TeamMember.project_id == Project.id)
        .where(TeamMember.user_id == user.id).distinct()
    ).all()
    task_allocated = db.scalars(
        select(Project.name)
        .join(Task, Task.project_id == Project.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(TaskAssignee.user_id == user.id)
        .distinct()
    ).all()
    managed = db.scalars(
        select(Project.name).where(Project.project_manager_id == user.id)
    ).all()
    projects = sorted(set(allocated) | set(task_allocated) | set(managed))
    completion_percent, missing_fields = profile_completion(user, profile)
    return UserProfileRead(
        name=user.name, email=user.email, project_count=len(projects), projects=projects,
        profile_image=profile.profile_image if profile else None,
        phone=profile.phone if profile else None,
        location=profile.location if profile else None,
        location_city=profile.location_city if profile else None,
        location_state=profile.location_state if profile else None,
        location_country=profile.location_country if profile else None,
        bio=profile.bio if profile else None,
        professional_title=profile.professional_title if profile else None,
        department=profile.department if profile else None,
        years_experience=profile.years_experience if profile else None,
        experience_start_date=profile.experience_start_date if profile else None,
        skills=profile.skills if profile else None,
        achievements=profile.achievements if profile else None,
        completion_percent=completion_percent, missing_fields=missing_fields,
    )


def profile_project_ids(db: DB, user_id: int) -> set[int]:
    legacy = db.scalars(select(TeamMember.project_id).where(TeamMember.user_id == user_id)).all()
    assigned = db.scalars(
        select(Task.project_id).join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(TaskAssignee.user_id == user_id).distinct()
    ).all()
    managed = db.scalars(select(Project.id).where(Project.project_manager_id == user_id)).all()
    return set(legacy) | set(assigned) | set(managed)


@router.get("/profile/projects")
def get_profile_projects(db: DB, current_user: CurrentUser) -> list[dict]:
    project_ids = profile_project_ids(db, current_user.id)
    if not project_ids:
        return []
    projects = db.scalars(
        select(Project).where(Project.id.in_(project_ids)).order_by(Project.name, Project.id)
    ).all()
    return [{"id": project.id, "name": project.name,
             "start_date": project.start_date, "end_date": project.end_date,
             "status": project.status.value,
             "is_manager": project.project_manager_id == current_user.id}
            for project in projects]


@router.get("/profile/projects/{project_id}")
def get_profile_project_detail(project_id: int, db: DB, current_user: CurrentUser) -> dict:
    if project_id not in profile_project_ids(db, current_user.id):
        raise HTTPException(status_code=404, detail="Project is not connected to your profile")
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.execute(
        select(Task, TaskAssignee)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(Task.project_id == project.id, TaskAssignee.user_id == current_user.id)
        .options(selectinload(Task.checklist_items))
        .order_by(Task.due_date, Task.id)
    ).all()
    tasks = [{"id": task.id, "title": task.title, "description": task.description,
              "responsibility": assignment.responsibility,
              "start_date": task.start_date, "due_date": task.due_date,
              "status": task.status.value, "priority": task.priority.value,
              "progress": task.progress, "planned_hours": assignment.planned_hours or 0,
              "checklist_total": len(task.checklist_items),
              "checklist_done": sum(item.is_done for item in task.checklist_items)}
             for task, assignment in rows]
    return {"id": project.id, "name": project.name,
            "start_date": project.start_date, "end_date": project.end_date,
            "status": project.status.value,
            "is_manager": project.project_manager_id == current_user.id,
            "average_progress": round(sum(item["progress"] for item in tasks) / len(tasks)) if tasks else 0,
            "tasks": tasks}


@router.get("/profile", response_model=UserProfileRead)
def get_profile(db: DB, current_user: CurrentUser) -> UserProfileRead:
    return profile_response(db, current_user)


@router.put("/profile", response_model=UserProfileRead)
def update_profile(
    payload: UserProfileUpdate, db: DB, current_user: CurrentUser
) -> UserProfileRead:
    validate_profile_image(payload.profile_image)
    current_user.name = payload.name.strip()
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
    if "professional_title" in payload.model_fields_set and payload.professional_title != profile.professional_title:
        raise HTTPException(status_code=403, detail="Only an admin can change your designation")
    if "department" in payload.model_fields_set and payload.department != profile.department:
        raise HTTPException(status_code=403, detail="Only an admin can change your department")
    for field, value in payload.model_dump(
        exclude={"name", "professional_title", "department"}, exclude_unset=True
    ).items():
        if field == "skills":
            value = normalize_skills(value)
        setattr(profile, field, value.strip() if isinstance(value, str) and field != "profile_image" else value)
    db.commit()
    db.refresh(current_user)
    return profile_response(db, current_user)
