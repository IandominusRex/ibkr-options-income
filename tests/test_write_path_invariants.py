"""The P2 write-path invariants, asserted in one findable place (M3 Task 3.6).

Several assertions overlap earlier tasks deliberately: an invariant with one
test has one point of failure. The invariants:

- Every ``/options/*`` and ``/commands*`` route is owner-gated — globbed, not
  hand-listed, so a new route cannot ship ungated.
- No route module imports the command engine — routes hold the read-only
  session; only ``src/api/commands.py`` writes.
- Telegram and the console cannot double-decide an approval into two orders.
- A crashed drain re-applies exactly once (the four idempotency layers, §4.5).
- The API still holds no broker connection — P2 added a write path, not an IB
  import.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import ApprovalStatus

_EXPIRY = date.today() + timedelta(days=30)


def _snapshot(*, contracts: int = 1) -> dict:
    return {
        "underlying": "NVDA",
        "strategy": "cash_secured_put",
        "right": "P",
        "strike": 190.0,
        "expiry": _EXPIRY.isoformat(),
        "contracts": contracts,
        "premium": 3.25,
        "blended_score": 72.0,
    }


# ---------------------------------------------------------------------------
# 1. Every /options and /commands route requires the owner
# ---------------------------------------------------------------------------


def test_every_options_route_requires_owner() -> None:
    """Globbed, not listed: a new route must not be able to ship ungated."""
    from fastapi.routing import APIRoute

    from src.api.deps import OwnerUser
    from src.api.main import create_app

    app = create_app()
    ungated: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not (path.startswith("/options") or path.startswith("/commands")):
            continue
        # OwnerUser must appear somewhere in the route's dependency chain.
        # DependWrapper objects expose `.call`; nested dependencies live in
        # `dependant.dependencies`.
        names = {getattr(d.call, "__name__", str(d.call)) for d in route.dependant.dependencies}
        nested = set()
        for d in route.dependant.dependencies:
            nested |= {
                getattr(sub.call, "__name__", str(sub.call)) for sub in d.dependant.dependencies
            }
        if OwnerUser.__name__ not in names and OwnerUser.__name__ not in nested:
            ungated.append(path)
    assert not ungated, f"routes missing the owner gate: {ungated}"


# ---------------------------------------------------------------------------
# 2. No route module imports the command engine
# ---------------------------------------------------------------------------


def test_no_route_module_imports_the_command_engine() -> None:
    """Routes hold the read-only session. Only src/api/commands.py may write."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    routers = root / "src" / "api" / "routers"
    offenders = [
        str(p.relative_to(root))
        for p in sorted(routers.glob("*.py"))
        if "get_command_engine" in p.read_text(encoding="utf-8")
        or "command_session" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"write handle leaked into a route module: {offenders}"


# ---------------------------------------------------------------------------
# 3 & 4. Drain idempotency — shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """Temp trading DB + fake bot + the helpers the two drain tests need."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'wpi.db'}")
    dbmod.init_db()

    from unittest.mock import AsyncMock

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow, ApprovalRow, OrderRow

    saved = dict(HANDLERS)
    HANDLERS.clear()
    HANDLERS.update({k: v for k, v in saved.items() if k in ("approve", "reject")})

    def seed_pending_approval() -> int:
        with dbmod.session_scope() as s:
            row = ApprovalRow(
                candidate_id="NVDA-cand-1",
                status=ApprovalStatus.PENDING,
                snapshot=_snapshot(),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
            s.add(row)
            s.flush()
            return row.id

    def decide(approval_id: int, status: ApprovalStatus) -> None:
        with dbmod.session_scope() as s:
            row = s.get(ApprovalRow, approval_id)
            assert row is not None
            row.status = status
            row.decided_at = datetime.now(UTC)

    def enqueue(kind: str, payload: dict) -> int:
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(s, kind=kind, payload=payload, requested_by="test")
            return row.id

    def order_count(approval_id: int) -> int:
        with dbmod.session_scope() as s:
            return s.query(OrderRow).filter(OrderRow.approval_id == approval_id).count()

    def unmark_applied(cid: int) -> None:
        with dbmod.session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            row.status = "pending"
            row.applied_at = None

    env = _Env(
        bot=AsyncMock(),
        seed_pending_approval=seed_pending_approval,
        decide=decide,
        enqueue=enqueue,
        order_count=order_count,
        unmark_applied=unmark_applied,
    )
    yield env
    HANDLERS.clear()
    HANDLERS.update(saved)


class _Env:
    def __init__(self, bot, seed_pending_approval, decide, enqueue, order_count, unmark_applied):
        self.bot = bot
        self.seed_pending_approval = seed_pending_approval
        self.decide = decide
        self.enqueue = enqueue
        self.order_count = order_count
        self.unmark_applied = unmark_applied


@pytest.mark.asyncio
async def test_telegram_and_the_console_cannot_double_order(drain_env) -> None:
    """Both surfaces decide the same approval. Exactly one order exists."""
    from src.notify.command_drain import drain_once

    approval_id = drain_env.seed_pending_approval()

    # Telegram acts first: the approval is decided via _process_button, the exact
    # function the Telegram callback runs (simulated through the same call the
    # drain's handler makes, so the mutation itself is identical).
    from src.notify.command_drain import _process_button

    found, _, _ = _process_button(approval_id, "approve")
    assert found is True

    # The console's command then arrives for the same approval.
    drain_env.enqueue("approve", {"approval_id": approval_id})
    await drain_once(None, drain_env.bot, "chat")

    # The four idempotency layers (§4.5) mean exactly one order exists.
    assert drain_env.order_count(approval_id) == 1


@pytest.mark.asyncio
async def test_a_crashed_drain_reapplies_exactly_once(drain_env) -> None:
    """Simulate: handler applied, process died before mark_applied. Retry is absorbed."""
    from src.notify.command_drain import drain_once

    approval_id = drain_env.seed_pending_approval()
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.order_count(approval_id) == 1

    # The crash: the command is retried as if mark_applied never ran.
    drain_env.unmark_applied(cid)
    await drain_once(None, drain_env.bot, "chat")

    # The retry hits _process_button's status guard (layer 2) and the unique
    # constraint (layer 4) — still exactly one order.
    assert drain_env.order_count(approval_id) == 1


# ---------------------------------------------------------------------------
# 5. The API still holds no broker connection
# ---------------------------------------------------------------------------


def test_the_api_still_holds_no_broker_connection() -> None:
    """P2 adds a write path. It must not have added an IB import along the way."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    api_dir = root / "src" / "api"
    offenders: list[str] = []
    for p in sorted(api_dir.rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        # Strip comments and docstrings crudely: a *code-level* import is what
        # would construct a connection. Match actual import statements only.
        for line in text.splitlines():
            code = line.split("#")[0].strip()
            if code.startswith("import ib_async") or code.startswith("from ib_async"):
                offenders.append(f"{p.relative_to(root)}: {code}")
    assert not offenders, f"ib_async reached the API layer: {offenders}"
