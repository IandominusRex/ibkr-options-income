"""FastAPI dependencies: auth, and database sessions."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.api.auth import Role, User, authenticate
from src.api.trading_db import trading_session
from src.research.store.models import SymbolRow
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


def assert_known_symbol(research: Session, symbol: str) -> str:
    """Raise 404 unless ``symbol`` (case-insensitive) is a known SEC filer in the research
    symbol directory. Returns the upper-cased symbol otherwise.

    Shared by ``routers/universe.py``'s thin ``POST``/``DELETE /universe/{list_name}/{symbol}``
    wrappers and ``routers/commands.py``'s generic ``POST /commands`` boundary check for
    ``universe_add``/``universe_remove`` (M7 final-review Fix 2) — without this check at the
    generic route too, an owner could smuggle an override for a symbol that does not exist in
    the research directory straight past the thin wrappers' validation.
    """
    upper = symbol.upper()
    if research.get(SymbolRow, upper) is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")
    return upper
