from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import CurrentUser, DB
from app.models import User
from app.schemas import Token, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserRead, status_code=201)
def register(payload: UserRegister, db: DB) -> User:
    email = payload.email.lower()
    exists = db.scalar(select(User).where(func.lower(User.email) == email))
    if exists:
        raise HTTPException(status_code=409, detail="Email is already registered")
    user = User(
        name=payload.name.strip(),
        email=email,
        hashed_password=hash_password(payload.password),
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
    user = db.scalar(
        select(User).where(func.lower(User.email) == form.username.lower())
    )
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> User:
    return current_user
