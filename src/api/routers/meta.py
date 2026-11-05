"""Liveness and identity. (`GET /nav`, the old rail manifest, was removed in web overhaul Part 4.)"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter

from src.api.deps import CurrentUser, ResearchDb
from src.api.models.common import Envelope
from src.api.trading_db import get_trading_engine
from src.data.breaker import breaker_states
from src.research.ingest.jobs import read_heartbeat

router = APIRouter()


class HealthResponse(Envelope):
    status: str
    research_db: bool
    trading_db: bool
    worker_heartbeat: datetime | None = None
    providers: dict[str, str] = {}


class MeResponse(Envelope):
    id: str
    role: str


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health(db: ResearchDb) -> HealthResponse:
    now = datetime.now(UTC)

    research_ok = True
    try:
        db.execute(sa.text("SELECT 1"))
    except Exception:
        research_ok = False

    trading_ok = True
    try:
        with get_trading_engine().connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception:
        trading_ok = False

    providers = breaker_states()
    any_breaker_open = any(state == "open" for state in providers.values())

    return HealthResponse(
        as_of=now,
        status="ok" if research_ok and trading_ok and not any_breaker_open else "degraded",
        research_db=research_ok,
        trading_db=trading_ok,
        worker_heartbeat=read_heartbeat(),
        providers=providers,
    )


@router.get("/me", response_model=MeResponse, tags=["meta"])
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(as_of=datetime.now(UTC), id=user.id, role=str(user.role))
