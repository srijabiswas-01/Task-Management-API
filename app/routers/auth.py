from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select, text

from app.core.security import create_access_token, hash_password, verify_password
from app.core.skills import normalize_skills, parse_skills
from app.core.profile import profile_completion, validate_profile_image
from app.dependencies import CurrentUser, DB
from app.models import GlobalDepartment, GlobalDesignation, Project, TeamMember, User, UserProfile
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
    managed = db.scalars(
        select(Project.name).where(Project.project_manager_id == user.id)
    ).all()
    projects = sorted(set(allocated) | set(managed))
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
