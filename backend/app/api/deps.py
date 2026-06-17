"""
Shared API dependencies — authentication / current-user resolution.

`get_current_user` is the single trust boundary for HTTP routes: it validates a
Bearer JWT and loads the owning user. `resolve_session_owner` enforces that the
authenticated user owns the session they are acting on.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.engine import get_db_session
from app.models.session import Session
from app.models.user import User
from app.utils.security import decode_access_token

# auto_error=False so we can raise a consistent 401 with a WWW-Authenticate header.
_bearer = HTTPBearer(auto_error=False)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_user_from_token(token: str, db: AsyncSession) -> Optional[User]:
    """Resolve a User from a raw JWT string (shared by HTTP and WebSocket)."""
    claims = decode_access_token(token)
    if not claims:
        return None
    sub = claims.get("sub")
    if not sub:
        return None
    try:
        user_id = uuid.UUID(str(sub))
    except (ValueError, TypeError):
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """FastAPI dependency: return the authenticated user or raise 401."""
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_EXC
    user = await get_user_from_token(credentials.credentials, db)
    if user is None:
        raise _CREDENTIALS_EXC
    return user


async def resolve_session_owner(
    session_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Session:
    """
    Load a session and enforce that `current_user` owns it.
    Raises 404 if missing, 403 if owned by someone else.
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this session",
        )
    return session
