"""Liveness, identity, and the navigation manifest."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter

from src.api.deps import CurrentUser, ResearchDb
from src.api.models.common import Envelope
from src.api.trading_db import get_trading_engine
from src.research.ingest.jobs import read_heartbeat

router = APIRouter()


class HealthResponse(Envelope):
    status: str
    research_db: bool
    trading_db: bool
    worker_heartbeat: datetime | None = None


class MeResponse(Envelope):
    id: str
    role: str


class NavSection(Envelope):
    key: str
    label: str
    available: bool
    note: str | None = None


class NavResponse(Envelope):
    sections: list[NavSection]


# P2-P4 sections render an explicit placeholder rather than being hidden, so the finished
# shape of the product is legible from milestone 1. See design §9.
_SECTIONS: list[tuple[str, str, bool, str | None]] = [
    ("research", "Research", True, None),
    ("options", "Options", False, "Arrives in P2"),
    ("portfolio", "Portfolio", False, "Arrives in P3"),
    ("pnl", "P&L", False, "Arrives in P4"),
    ("universe", "Universe", True, None),
]


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

    return HealthResponse(
        as_of=now,
        status="ok" if research_ok and trading_ok else "degraded",
        research_db=research_ok,
        trading_db=trading_ok,
        worker_heartbeat=read_heartbeat(),
    )


@router.get("/me", response_model=MeResponse, tags=["meta"])
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(as_of=datetime.now(UTC), id=user.id, role=str(user.role))


@router.get("/nav", response_model=NavResponse, tags=["meta"])
def nav(user: CurrentUser) -> NavResponse:
    now = datetime.now(UTC)
    return NavResponse(
        as_of=now,
        sections=[
            NavSection(as_of=now, key=k, label=lbl, available=avail, note=note)
            for k, lbl, avail, note in _SECTIONS
        ],
    )
