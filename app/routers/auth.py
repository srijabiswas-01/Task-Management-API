from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_password, verify_password
from app.core.skills import normalize_skills
from app.dependencies import CurrentUser, DB
from app.models import GlobalDepartment, GlobalDesignation, Project, TeamMember, User, UserProfile
from app.schemas import Token, UserProfileRead, UserProfileUpdate, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserRead, status_code=201)
def register(payload: UserRegister, db: DB) -> User:
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
        hashed_password=hash_password(payload.password),
        is_active=is_first_account,
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
    return UserProfileRead(
        name=user.name, email=user.email, project_count=len(projects), projects=projects,
        profile_image=profile.profile_image if profile else None,
        phone=profile.phone if profile else None, location=profile.location if profile else None,
        bio=profile.bio if profile else None,
        professional_title=profile.professional_title if profile else None,
        department=profile.department if profile else None,
        years_experience=profile.years_experience if profile else None,
        skills=profile.skills if profile else None,
        achievements=profile.achievements if profile else None,
    )


@router.get("/profile", response_model=UserProfileRead)
def get_profile(db: DB, current_user: CurrentUser) -> UserProfileRead:
    return profile_response(db, current_user)


@router.put("/profile", response_model=UserProfileRead)
def update_profile(
    payload: UserProfileUpdate, db: DB, current_user: CurrentUser
) -> UserProfileRead:
    if payload.professional_title and db.scalar(select(GlobalDesignation.id).where(
        GlobalDesignation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(GlobalDepartment.id).where(
        GlobalDepartment.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
    current_user.name = payload.name.strip()
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
    for field, value in payload.model_dump(exclude={"name"}).items():
        if field == "skills":
            value = normalize_skills(value)
        setattr(profile, field, value.strip() if isinstance(value, str) and field != "profile_image" else value)
    db.commit()
    db.refresh(current_user)
    return profile_response(db, current_user)
