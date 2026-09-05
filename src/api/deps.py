"""FastAPI dependencies: auth, and database sessions."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.api.auth import Role, User, authenticate
from src.api.trading_db import trading_session
from src.research.store.session import research_session

_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    user = authenticate(creds.credentials if creds else None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_owner(user: CurrentUser) -> User:
    """Gate for anything exposing the book. Applied to P3/P4 routes when they land."""
    if user.role is not Role.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return user


OwnerUser = Annotated[User, Depends(require_owner)]


def research_db() -> Iterator[Session]:
    with research_session() as session:
        yield session


ResearchDb = Annotated[Session, Depends(research_db)]


def trading_db() -> Iterator[Session]:
    with trading_session() as session:
        yield session


TradingDb = Annotated[Session, Depends(trading_db)]
