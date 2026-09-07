"""M5 Task 5.1: a roll request proposes. It never rolls.

The handler is a thin resolver around ``queue_roll_for_approval`` (the pipeline the intraday
monitor already uses): it resolves the position, fetches the chain through the same shared
helper (``roll_pipeline.fetch_roll_inputs``), and disambiguates the pipeline's ``None`` into the
five operator-meaningful reasons in ``docs/web/commands.md``'s roll_request table.

Mocking discipline matches ``tests/test_drain_promote.py``: only the IBKR/network boundary is
mocked (``get_positions``, the chain fetch, and the two blocking analytics fetches);
``generate_roll_candidates`` — the roll's real economics — runs for real, so a qualifying roll in
these tests is a roll that actually clears ``rolling.py``'s defensive bounds, and a
``no_qualifying_roll`` is one the real economics refused. No roll economics are mocked.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import (
    ApprovalStatus,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    TechnicalStats,
)


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(
        Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'roll_drain.db'}"
    )
    dbmod.init_db()


class _FakeChain:
    """Configures the IBKR/network boundary ``fetch_roll_inputs`` consults.

    ``will_offer_roll`` builds a chain whose current leg matches the seeded short (so
    ``_infer_current_mid`` resolves) and whose new leg clears the real ``generate_roll_candidates``
    defensive bounds at the given strike/dte/credit. ``will_offer_no_roll`` builds a chain where
    the only new leg fails the net-debit cap — the real economics refuse it, so the pipeline
    returns ``None`` and the handler reports ``no_qualifying_roll``.
    """

    def __init__(self, monkeypatch) -> None:
        self._monkeypatch = monkeypatch
        self.quotes: list[OptionQuote] = []
        self.iv = IVStats(symbol="NVDA", current_iv=30.0, iv_rank=60.0)
        self.tech = TechnicalStats(symbol="NVDA", price=170.0, rsi_14=55.0)
        self.side_effect: BaseException | None = None
        self._wired = False

    def will_offer_roll(
        self,
        position: PositionSnapshot,
        *,
        strike: float,
        dte: int,
        credit: float,
        new_delta: float = -0.30,
        current_mid: float = 0.65,
    ) -> None:
        new_mid = round(current_mid + credit, 2)
        new_expiry = date.today() + timedelta(days=dte)
        self.quotes = [
            # The current leg — matches the position so _infer_current_mid resolves. Its delta
            # is never read by the generator (only its mid); set it to the position's for honesty.
            OptionQuote(
                underlying=position.underlying or position.symbol,
                right=position.right or OptionRight.CALL,
                strike=position.strike or 180.0,
                expiry=position.expiry or (date.today() + timedelta(days=9)),
                bid=round(current_mid - 0.05, 2),
                ask=round(current_mid + 0.05, 2),
                volume=500,
                open_interest=2000,
                delta=position.delta,
                iv=0.30,
            ),
            # The roll target — a further-dated leg within the CC delta/dte band, reducing |delta|
            # by >= min_delta_reduction, clearing the net-debit cap, and (for a call rolled down
            # to a lower strike) a credit so require_breakeven_improvement is satisfied.
            OptionQuote(
                underlying=position.underlying or position.symbol,
                right=position.right or OptionRight.CALL,
                strike=strike,
                expiry=new_expiry,
                bid=round(new_mid - 0.05, 2),
                ask=round(new_mid + 0.05, 2),
                volume=500,
                open_interest=2000,
                delta=new_delta,
                iv=0.30,
            ),
        ]
        self.side_effect = None
        self._wire()

    def will_offer_two_rolls(
        self,
        position: PositionSnapshot,
        *,
        first: tuple[float, int, float],
        second: tuple[float, int, float],
        new_delta: float = -0.30,
        current_mid: float = 0.65,
    ) -> None:
        """A chain offering two distinct qualifying roll targets — ``first``/``second`` are
        ``(strike, dte, credit)`` tuples, both clearing the real defensive bounds. Used to prove
        the in-flight check considers every qualifying candidate, not just the current best:
        under ``defensive=True`` every candidate's ``roc_pct`` is 0 (rolls are judged on risk
        reduction, not yield, per D4), so ``generate_roll_candidates``'s ROC-desc sort is a
        no-op tie and ``candidates[0]`` is really just whichever quote the chain listed first —
        which can differ between two fetches taken minutes apart on a moving chain even though
        both quotes still qualify.
        """
        new_expiry_current = position.expiry or (date.today() + timedelta(days=9))
        quotes = [
            OptionQuote(
                underlying=position.underlying or position.symbol,
                right=position.right or OptionRight.CALL,
                strike=position.strike or 180.0,
                expiry=new_expiry_current,
                bid=round(current_mid - 0.05, 2),
                ask=round(current_mid + 0.05, 2),
                volume=500,
                open_interest=2000,
                delta=position.delta,
                iv=0.30,
            )
        ]
        for strike, dte, credit in (first, second):
            new_mid = round(current_mid + credit, 2)
            quotes.append(
                OptionQuote(
                    underlying=position.underlying or position.symbol,
                    right=position.right or OptionRight.CALL,
                    strike=strike,
                    expiry=date.today() + timedelta(days=dte),
                    bid=round(new_mid - 0.05, 2),
                    ask=round(new_mid + 0.05, 2),
                    volume=500,
                    open_interest=2000,
                    delta=new_delta,
                    iv=0.30,
                )
            )
        self.quotes = quotes
        self.side_effect = None
        self._wire()

    def will_offer_no_roll(
        self,
        position: PositionSnapshot,
        *,
        strike: float = 175.0,
        dte: int = 21,
        new_delta: float = -0.30,
        current_mid: float = 0.65,
    ) -> None:
        """A chain where the only new leg fails the net-debit cap: credit = -0.60 < -max_debit."""
        new_mid = round(current_mid - 0.60, 2)
        new_expiry = date.today() + timedelta(days=dte)
        self.quotes = [
            OptionQuote(
                underlying=position.underlying or position.symbol,
                right=position.right or OptionRight.CALL,
                strike=position.strike or 180.0,
                expiry=position.expiry or (date.today() + timedelta(days=9)),
                bid=round(current_mid - 0.05, 2),
                ask=round(current_mid + 0.05, 2),
                volume=500,
                open_interest=2000,
                delta=position.delta,
                iv=0.30,
            ),
            OptionQuote(
                underlying=position.underlying or position.symbol,
                right=position.right or OptionRight.CALL,
                strike=strike,
                expiry=new_expiry,
                bid=round(new_mid - 0.05, 2),
                ask=round(new_mid + 0.05, 2),
                volume=500,
                open_interest=2000,
                delta=new_delta,
                iv=0.30,
            ),
        ]
        self.side_effect = None
        self._wire()

    def will_fail(self, *, exc: BaseException) -> None:
        self.side_effect = exc
        self.quotes = []
        self._wire()

    def _wire(self) -> None:
        mp = self._monkeypatch
        if self.side_effect is not None:
            chain_mock = AsyncMock(side_effect=self.side_effect)
        else:
            chain_mock = AsyncMock(return_value=self.quotes)
        # fetch_roll_inputs deferred-imports these from their source modules at call time, so
        # patching the module attribute reaches both the monitor's path and the drain's.
        mp.setattr("src.ibkr.market_data.get_option_chain_quotes_async", chain_mock)
        mp.setattr(
            "src.analytics.iv.get_iv_stats",
            lambda sym, quotes=None: self.iv.model_copy(update={"symbol": sym}),
        )
        mp.setattr(
            "src.analytics.technicals.get_technical_stats",
            lambda sym, **_: self.tech.model_copy(update={"symbol": sym}),
        )
        self._wired = True


@pytest.fixture
def fake_chain(monkeypatch):
    return _FakeChain(monkeypatch)


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """A temp trading DB + fake bot + position/approval/order helpers, roll_request registered only."""
    _db_setup(tmp_path, monkeypatch)

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow, ApprovalRow, CandidateRow, OrderRow

    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()
    HANDLERS.update({k: v for k, v in saved_handlers.items() if k == "roll_request"})

    bot = AsyncMock()
    positions: list[PositionSnapshot] = []

    # The handler resolves the position from a live portfolio read, not a stored snapshot —
    # patching the source module the deferred import resolves from at call time.
    monkeypatch.setattr("src.ibkr.portfolio.get_positions", lambda ib: list(positions))

    def seed_short(
        position_symbol: str,
        *,
        underlying: str = "NVDA",
        delta: float = -0.45,
        dte: int = 9,
        strike: float = 180.0,
        right: str = "C",
        contracts: int = 1,
    ) -> PositionSnapshot:
        pos = PositionSnapshot(
            symbol=position_symbol,
            sec_type="OPT",
            position=-float(contracts),
            avg_cost=1.50,
            right=OptionRight.CALL if right == "C" else OptionRight.PUT,
            strike=strike,
            expiry=date.today() + timedelta(days=dte),
            delta=delta,
            underlying=underlying,
        )
        positions.append(pos)
        return pos

    def seed_long(
        position_symbol: str,
        *,
        underlying: str = "NVDA",
        strike: float = 180.0,
        dte: int = 9,
    ) -> PositionSnapshot:
        pos = PositionSnapshot(
            symbol=position_symbol,
            sec_type="OPT",
            position=1.0,
            avg_cost=1.50,
            right=OptionRight.CALL,
            strike=strike,
            expiry=date.today() + timedelta(days=dte),
            delta=0.30,
            underlying=underlying,
        )
        positions.append(pos)
        return pos

    def enqueue(kind: str, payload: dict) -> int:
        with session_scope() as s:
            row, _ = enqueue_command(s, kind=kind, payload=payload, requested_by="test")
            return row.id

    def status(cid: int) -> str:
        with session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            return row.status

    def result(cid: int) -> dict:
        with session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            return row.result or {}

    def approval_status(approval_id: int) -> str:
        with session_scope() as s:
            row = s.get(ApprovalRow, approval_id)
            assert row is not None
            return row.status

    def order_for_approval(approval_id: int) -> OrderRow | None:
        with session_scope() as s:
            row = s.query(OrderRow).filter(OrderRow.approval_id == approval_id).one_or_none()
            if row is None:
                return None
            s.expunge(row)
            return row

    def approval(approval_id: int) -> ApprovalRow:
        with session_scope() as s:
            row = s.get(ApprovalRow, approval_id)
            assert row is not None
            s.expunge(row)
            return row

    def pending_approval_count(*, underlying: str) -> int:
        with session_scope() as s:
            return (
                s.query(ApprovalRow)
                .join(CandidateRow, CandidateRow.candidate_id == ApprovalRow.candidate_id)
                .filter(
                    CandidateRow.underlying == underlying,
                    ApprovalRow.status == ApprovalStatus.PENDING.value,
                )
                .count()
            )

    def total_order_count() -> int:
        with session_scope() as s:
            return s.query(OrderRow).count()

    def seed_working_roll(
        candidate_id: str, *, approval_id: int | None = None, state: str = "queued"
    ) -> int:
        """Seed an ApprovalRow (the working order's origin) + its active OrderRow."""
        with session_scope() as s:
            approval = ApprovalRow(
                candidate_id=candidate_id,
                status=ApprovalStatus.APPROVED,
                snapshot={"underlying": "NVDA", "strategy": "roll"},
                expires_at=None,
                decided_at=None,
            )
            s.add(approval)
            s.flush()
            order = OrderRow(
                candidate_id=candidate_id,
                approval_id=approval_id if approval_id is not None else approval.id,
                state=state,
                snapshot={"underlying": "NVDA", "strategy": "roll"},
            )
            s.add(order)
            s.flush()
            return approval.id

    env = SimpleNamespace(
        bot=bot,
        ib=MagicMock(),  # a non-None sentinel; the fake chain mocks every real call
        enqueue=enqueue,
        status=status,
        result=result,
        approval_status=approval_status,
        order_for_approval=order_for_approval,
        approval=approval,
        pending_approval_count=pending_approval_count,
        total_order_count=total_order_count,
        seed_short=seed_short,
        seed_long=seed_long,
        seed_working_roll=seed_working_roll,
    )

    yield env

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


# ---------------------------------------------------------------------------
# The seven tests from the plan, plus the two extra distinguishable-outcome tests
# (chain fetch failure, position not found) the reason table requires.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_roll_request_raises_a_pending_approval(drain_env, fake_chain) -> None:
    from src.notify.command_drain import drain_once

    pos = drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_offer_roll(pos, strike=175.0, dte=21, credit=0.35)
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    result = drain_env.result(cid)
    approval_id = result["approval_id"]
    assert approval_id is not None
    assert result["candidate_id"]
    assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_a_roll_request_never_places_an_order(drain_env, fake_chain) -> None:
    """Two steps, always. The console proposes; the operator approves."""
    from src.notify.command_drain import drain_once

    pos = drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_offer_roll(pos, strike=175.0, dte=21, credit=0.35)
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    approval_id = drain_env.result(cid)["approval_id"]
    assert drain_env.order_for_approval(approval_id) is None
    assert drain_env.total_order_count() == 0


@pytest.mark.asyncio
async def test_no_qualifying_roll_is_a_real_answer(drain_env, fake_chain) -> None:
    from src.notify.command_drain import drain_once

    pos = drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_offer_no_roll(pos)
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "no_qualifying_roll"
    # A real answer leaves no proposal behind.
    assert drain_env.pending_approval_count(underlying="NVDA") == 0


@pytest.mark.asyncio
async def test_an_already_working_roll_is_distinguished(drain_env, fake_chain) -> None:
    """'A roll is already in flight' and 'no roll qualifies' are different answers."""
    from src.notify.command_drain import drain_once
    from src.strategies._scoring import make_candidate_id

    pos = drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_offer_roll(pos, strike=175.0, dte=21, credit=0.35)
    # The monitor already fired for this position, the operator approved it, and the order is
    # working — the deterministic candidate id is computable from the same inputs.
    new_expiry = date.today() + timedelta(days=21)
    candidate_id = make_candidate_id("roll", "NVDA", "C", 175.0, new_expiry)
    working_approval_id = drain_env.seed_working_roll(candidate_id)

    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    res = drain_env.result(cid)
    assert res["reason"] == "roll_already_working"
    assert res["detail"]["approval_id"] == working_approval_id
    assert drain_env.pending_approval_count(underlying="NVDA") == 0


@pytest.mark.asyncio
async def test_a_long_position_is_refused(drain_env) -> None:
    from src.notify.command_drain import drain_once

    drain_env.seed_long("NVDA  261017C00180000")
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "not_an_open_short"


@pytest.mark.asyncio
async def test_a_position_not_held_is_refused(drain_env) -> None:
    """The OCC symbol does not match anything the broker reports as held."""
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "position_not_found"


@pytest.mark.asyncio
async def test_a_roll_request_with_no_broker_fails_honestly(drain_env) -> None:
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "broker_unavailable"


@pytest.mark.asyncio
async def test_a_chain_fetch_failure_fails_with_chain_unavailable(drain_env, fake_chain) -> None:
    from src.notify.command_drain import drain_once

    drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_fail(exc=RuntimeError("no market data farm connection"))
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    res = drain_env.result(cid)
    assert res["reason"] == "chain_unavailable"
    assert res["detail"]["detail"] == "no market data farm connection"


@pytest.mark.asyncio
async def test_a_monitor_alert_and_a_web_request_produce_one_approval(
    drain_env, fake_chain
) -> None:
    """The monitor fires for the same position while a request is queued. One approval.

    This is the test that matters most. The monitor's path is ``queue_roll_for_approval`` called
    directly with the same chain the handler will fetch — same deterministic candidate id. The
    handler must refuse to raise a second approval for that candidate, mapping the in-flight
    proposal to ``roll_already_working`` with the existing approval's id so the receipt can link
    to it. ``has_active_order`` alone would not catch this (the monitor's approval is PENDING, no
    OrderRow yet) — the handler's pending-approval check is what closes the race the milestone's
    acceptance criterion demands.
    """
    from src.execution.roll_pipeline import queue_roll_for_approval
    from src.notify.command_drain import drain_once

    pos = drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_offer_roll(pos, strike=175.0, dte=21, credit=0.35)

    # The monitor fires while the web request sits queued: its own path raises approval #1.
    queued = queue_roll_for_approval(
        pos, fake_chain.quotes, fake_chain.iv, fake_chain.tech, chat_id="chat", ttl_minutes=120
    )
    assert queued is not None, (
        "the monitor's path must produce a proposal for this test to be meaningful"
    )
    monitor_approval_id = queued[0]

    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    res = drain_env.result(cid)
    assert res["reason"] == "roll_already_working"
    assert res["detail"]["approval_id"] == monitor_approval_id
    assert drain_env.pending_approval_count(underlying="NVDA") == 1


@pytest.mark.asyncio
async def test_an_in_flight_roll_is_caught_even_when_no_longer_top_ranked(
    drain_env, fake_chain
) -> None:
    """The race above still closes when the chain has moved enough, between the monitor's fetch
    and this one, that the monitor's candidate is no longer the top-ranked one.

    Under ``defensive=True`` every candidate's ``roc_pct`` is 0 (D4: a defensive roll is judged
    on risk reduction, not yield), so ``generate_roll_candidates``'s ROC-desc sort is a no-op tie
    and ``candidates[0]`` is really just whichever qualifying quote the chain listed first. Two
    fetches taken minutes apart can list qualifying strikes in a different order (or with a
    different one leading) even without either strike stopping being valid. A handler that only
    checked the single best candidate's id would miss this and race the monitor into a second
    approval for the same position; checking every qualifying candidate is what actually
    satisfies the milestone's "exactly one approval" acceptance criterion.
    """
    from src.execution.roll_pipeline import queue_roll_for_approval
    from src.notify.command_drain import drain_once

    pos = drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)

    # At t1 (the monitor's fetch) 172.5 is listed first and becomes the approval. Both dte 21
    # and dte 25 sit inside the covered_call dte window (7-28), so both quotes qualify.
    fake_chain.will_offer_two_rolls(pos, first=(172.5, 21, 0.50), second=(175.0, 25, 0.35))
    queued = queue_roll_for_approval(
        pos, fake_chain.quotes, fake_chain.iv, fake_chain.tech, chat_id="chat", ttl_minutes=120
    )
    assert queued is not None
    monitor_approval_id, monitor_cand = queued
    assert monitor_cand.strike == 172.5, "the test's premise: 172.5 must be first at t1"

    # At t2 (the web request) the chain lists 175 first instead. 172.5 — the monitor's
    # already-pending approval — still qualifies, just no longer first.
    fake_chain.will_offer_two_rolls(pos, first=(175.0, 25, 0.60), second=(172.5, 21, 0.50))
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    res = drain_env.result(cid)
    assert res["reason"] == "roll_already_working"
    assert res["detail"]["approval_id"] == monitor_approval_id
    assert drain_env.pending_approval_count(underlying="NVDA") == 1
