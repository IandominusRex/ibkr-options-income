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

# M6 Task 6.4: same sanctioned reuse for the controls tests — the control handlers'
# `drain_env` lives in tests/test_drain_controls.py (this file's own `drain_env`
# registers the approve/reject handlers; the controls one registers
# halt/resume/set_autonomy).
from tests.test_drain_controls import drain_env as controls_drain_env  # noqa: F401

# M4 Task 4.4: Task 4.2's `drain_env`/`fake_chain` fixtures (tests/test_drain_promote.py) are
# reused verbatim for the promote-refusal tests below rather than duplicating ~150 lines of
# fixture engineering — a deliberate, sanctioned exception to this repo's usual "no shared
# fixtures across test files" convention. `drain_env` is aliased on import because this file
# already defines its own `drain_env` fixture (for the approve/reject tests further down,
# registering different handlers). Both imported names are "unused" as far as static analysis
# can tell — pytest resolves them by the matching parameter name on the test functions that
# use them, below.
from tests.test_drain_promote import _payload as _promote_payload
from tests.test_drain_promote import drain_env as promote_drain_env  # noqa: F401
from tests.test_drain_promote import fake_chain  # noqa: F401

# M5 Task 5.4: same sanctioned reuse for the roll degradation tests — the roll_request handler's
# `drain_env`/`fake_chain` live in tests/test_drain_roll.py.
from tests.test_drain_roll import drain_env as roll_drain_env  # noqa: F401
from tests.test_drain_roll import fake_chain as roll_fake_chain  # noqa: F401

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


# ---------------------------------------------------------------------------
# 6. A browser cannot overrule the Rules Engine (M4 Task 4.4)
#
# The API-boundary guard (`assert_promotable`, Task 4.1) is the primary defence: it
# refuses a non-promotable stage with 409 before an `app_commands` row can even exist.
# These three tests are the belt to that brace — they prove the drain handler itself
# (Task 4.2) is a second, independent line of defence that does not trust the guard
# having run, and that the guard's own promotable set cannot silently widen.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_promote_path_exists_for_a_gate_rejected_contract(
    promote_drain_env,  # noqa: F811
    fake_chain,  # noqa: F811
) -> None:
    """Belt and braces: the API refuses it, and the drain would too.

    Bypass the API guard entirely, insert a promote command for a risk_gate contract
    directly, and assert the drain still refuses rather than raising an approval.

    `promote_drain_env.enqueue(...)` calls `enqueue_command` directly — it never goes
    through `src/api/routers/commands.py::post_commands`, so Task 4.1's `assert_promotable`
    guard (which only runs inside that router function) never runs at all. If the drain
    handler itself did not independently re-gate, this is exactly the shape of bug that
    would let a malformed or bypassed request reach an order: no HTTP layer stands between
    the enqueued command and the drain.

    `seed_assessed(..., stage="risk_gate")` documents what a real risk_gate-staged
    contract looks like in storage — the promote handler never reads this row (Task 4.2's
    entire design point is that it always re-derives from a fresh run, never trusts the
    stored stage). The actual rejection comes from `fake_chain.will_price(..., gate="reject")`,
    which overloads the account's margin usage so the real `validate_candidates` genuinely,
    independently says no during the fresh re-derivation — not from the stored label.
    """
    from src.notify.command_drain import drain_once
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    promote_drain_env.seed_assessed("c1", stage="risk_gate", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="reject")
    cid = promote_drain_env.enqueue("promote", _promote_payload(strike=180.0))

    await drain_once(promote_drain_env.ib, promote_drain_env.bot, "chat")

    assert promote_drain_env.status(cid) == "failed"
    result = promote_drain_env.result(cid)
    assert result["reason"] == "gate_rejected"
    assert "approval_id" not in result

    # Not filtered by candidate_id: ApprovalRow.candidate_id is the fresh run's own
    # TradeCandidate.candidate_id (a SHA1 hash from make_candidate_id), never the literal
    # payload string "c1" used to select which contract to look for — a filter on "c1" would
    # never match any row this handler could possibly write, making the check vacuous. This
    # test's DB is a fresh tmp_path-backed sqlite (via _db_setup), so an unconditional
    # zero-row count is the meaningful assertion: no approval of any shape was raised.
    with session_scope() as s:
        assert s.query(ApprovalRow).count() == 0


@pytest.mark.asyncio
async def test_the_promote_handler_runs_the_real_rules_engine(
    promote_drain_env,  # noqa: F811
    fake_chain,  # noqa: F811
) -> None:
    """A test that mocks validate_candidates proves nothing. Assert the real one is called."""
    from unittest.mock import patch

    from src.engine.risk_engine import validate_candidates as real_validate_candidates
    from src.notify.command_drain import drain_once

    promote_drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
    cid = promote_drain_env.enqueue("promote", _promote_payload(strike=180.0))

    with patch("src.orchestrator.scan.validate_candidates", wraps=real_validate_candidates) as spy:
        await drain_once(promote_drain_env.ib, promote_drain_env.bot, "chat")

    assert spy.called
    assert promote_drain_env.status(cid) == "applied"


def test_promotable_stages_match_the_spec_exactly() -> None:
    """A future edit that widens PROMOTABLE_STAGES must fail here first."""
    from src.api.routers.commands import PROMOTABLE_STAGES

    assert PROMOTABLE_STAGES == frozenset({"score_floor", "dedupe", "top_n"})


# ---------------------------------------------------------------------------
# 7. Roll degradation tests (M5 Task 5.4)
#
# The console proposes a roll; only an approved OrderRow reaches execute_roll. The handler is a
# thin resolver around queue_roll_for_approval; it must not reimplement the roll's economics, and
# the web path must run the same defensive policy the monitor does. Three invariants, each pinned
# by one test.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_roll_request_never_reaches_execute_roll_directly(
    roll_drain_env,  # noqa: F811
    roll_fake_chain,  # noqa: F811
) -> None:
    """The console proposes. Only an approved OrderRow reaches execute_roll.

    Belt and braces: a behavioral tripwire (a `wraps`-spy on `execute_roll` is never called when a
    roll_request is drained, and no OrderRow is created) plus a source scan proving neither the
    drain nor the roll pipeline imports `execute_roll` at all. If a future edit wired the
    executor into the propose path, the spy would catch it at runtime and the grep at lint time.
    """
    from pathlib import Path
    from unittest.mock import patch

    from src.execution.roll_executor import execute_roll
    from src.notify.command_drain import drain_once

    pos = roll_drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    roll_fake_chain.will_offer_roll(pos, strike=175.0, dte=21, credit=0.35)
    cid = roll_drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})

    with patch("src.execution.roll_executor.execute_roll", wraps=execute_roll) as spy:
        await drain_once(roll_drain_env.ib, roll_drain_env.bot, "chat")

    assert roll_drain_env.status(cid) == "applied"
    assert not spy.called
    assert roll_drain_env.total_order_count() == 0

    root = Path(__file__).resolve().parents[1]
    for rel in ("src/notify/command_drain.py", "src/execution/roll_pipeline.py"):
        text = (root / rel).read_text(encoding="utf-8")
        # The propose path must not import the executor or call execute_roll. Docstring mentions
        # of the function name are fine (the roll_pipeline module documents the gap it closes);
        # a code-level import or call is what would wire the two together.
        assert "import roll_executor" not in text, f"{rel} imports the roll executor"
        assert "from src.execution.roll_executor" not in text, f"{rel} imports the roll executor"
        assert "execute_roll(" not in text, f"{rel} calls execute_roll directly"


def test_the_roll_handler_adds_no_economic_bounds_of_its_own() -> None:
    """The roll's economic bounds live in rolling.py. The handler must not reimplement, tighten,
    or relax them. A source scan is the structural half of this; the behavioral half is the
    `defensive=True` spy test below proving the handler delegates to the same generator the
    pipeline uses."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "notify" / "command_drain.py").read_text(encoding="utf-8")
    for token in ("max_debit", "min_delta_reduction", "roc_pct"):
        assert token not in text, f"roll economics leaked into the drain: {token}"


@pytest.mark.asyncio
async def test_the_web_and_the_monitor_share_one_roll_policy(
    roll_drain_env,  # noqa: F811
    roll_fake_chain,  # noqa: F811
) -> None:
    """defensive=True in both paths. A web roll is not a different roll.

    The handler pre-checks by calling `generate_roll_candidates(..., defensive=True)` itself, and
    `queue_roll_for_approval` calls it again internally with the same flag. Wrapping the generator
    at both call sites (the handler's deferred-import source module and the pipeline's
    module-bound name) and asserting every recorded call passed `defensive=True` proves the web
    path and the monitor's path run one policy. The monitor shares it because it goes through the
    same `queue_roll_for_approval`.
    """
    from unittest.mock import patch

    from src.notify.command_drain import drain_once
    from src.strategies.rolling import generate_roll_candidates as real_generate

    pos = roll_drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    roll_fake_chain.will_offer_roll(pos, strike=175.0, dte=21, credit=0.35)
    cid = roll_drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})

    handler_calls: list[bool] = []
    pipeline_calls: list[bool] = []

    def handler_spy(*args: object, **kwargs: object) -> object:
        handler_calls.append(bool(kwargs.get("defensive")))
        return real_generate(*args, **kwargs)

    def pipeline_spy(*args: object, **kwargs: object) -> object:
        pipeline_calls.append(bool(kwargs.get("defensive")))
        return real_generate(*args, **kwargs)

    import src.execution.roll_pipeline as roll_pipeline

    with (
        patch("src.strategies.rolling.generate_roll_candidates", handler_spy),
        patch.object(roll_pipeline, "generate_roll_candidates", pipeline_spy),
    ):
        await drain_once(roll_drain_env.ib, roll_drain_env.bot, "chat")

    assert roll_drain_env.status(cid) == "applied"
    assert handler_calls, "the handler must pre-check by generating candidates itself"
    assert all(handler_calls), "the handler's generation call must pass defensive=True"
    assert pipeline_calls, "the pipeline must generate candidates internally"
    assert all(pipeline_calls), "the pipeline's generation call must pass defensive=True"


# ---------------------------------------------------------------------------
# M6 Task 6.4 — controls invariants.
#
# The three control kinds are the only write-path commands with no broker and
# no order anywhere near them; these tests pin that, and pin the single halt
# flag. `drain_env` is reused from tests/test_drain_controls.py under the
# sanctioned cross-file alias M4 Task 4.4 / M5 Task 5.4 established (this file's
# own `drain_env` registers the approve/reject handlers; the controls one
# registers halt/resume/set_autonomy).
# ---------------------------------------------------------------------------

# The controls `drain_env` is aliased on import at the top of this file
# (controls_drain_env), from tests/test_drain_controls.py.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,payload",
    [("halt", {"reason": "r"}), ("resume", {}), ("set_autonomy", {"level": "manual"})],
)
async def test_every_control_kind_applies_without_a_broker(
    controls_drain_env,  # noqa: F811
    kind,
    payload,
) -> None:
    """Parametrised over halt, resume, set_autonomy. None may need TWS."""
    from src.notify.command_drain import drain_once

    cid = controls_drain_env.enqueue(kind, payload)
    await drain_once(None, controls_drain_env.bot, "chat")
    assert controls_drain_env.status(cid) == "applied", f"{kind} must apply with ib=None"


def test_control_kinds_never_require_live_confirmation() -> None:
    """The live token gates order-reaching intents. A halt is not one: a halt must
    never be slowed by a second step — the deliberate M6 asymmetry, pinned here so
    adding a control kind to _LIVE_CONFIRM_KINDS fails loudly."""
    from src.api.models.commands import CommandKind
    from src.api.routers.commands import _LIVE_CONFIRM_KINDS

    for kind in (CommandKind.HALT, CommandKind.RESUME, CommandKind.SET_AUTONOMY):
        assert kind not in _LIVE_CONFIRM_KINDS, f"{kind} must never require live confirmation"


def test_the_halt_key_is_the_same_one_telegram_uses() -> None:
    """Two halt flags would be a catastrophe. Assert one key, from system_settings."""
    from pathlib import Path

    from src.storage.system_settings import HALT_KEY

    assert HALT_KEY == "execution_halted"
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "notify" / "command_drain.py").read_text(encoding="utf-8")
    assert "execution_halted" not in text, "use the HALT_KEY constant, never the literal"
