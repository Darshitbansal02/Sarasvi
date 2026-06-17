"""
Auth routes — registration, login (JWT issuance), and current-user lookup.

Replaces the previous passwordless email-lookup flow. Passwords are bcrypt-hashed
and never returned. A successful register/login returns a signed JWT access token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.deps import get_current_user
from app.database.engine import get_db_session
from app.models.user import User, default_learning_profile
from app.schemas.api_schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.utils.security import create_access_token, hash_password, verify_password

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db_session)):
    """Create a new account and return an access token."""
    email = _normalize_email(data.email)
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered. Please log in instead.",
        )

    user = User(
        email=email,
        name=data.name,
        password_hash=hash_password(data.password),
        learning_profile=data.learning_profile or default_learning_profile(),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    token = create_access_token(str(user.id))
    logger.info("auth.registered", user_id=str(user.id))
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db_session)):
    """Authenticate with email + password and return an access token."""
    email = _normalize_email(data.email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Always run a bcrypt verify (against a dummy hash when the user is missing)
    # so response timing doesn't leak whether the email exists.
    _DUMMY_HASH = "$2b$12$" + "x" * 53
    password_ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(str(user.id))
    logger.info("auth.login", user_id=str(user.id))
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return current_user
