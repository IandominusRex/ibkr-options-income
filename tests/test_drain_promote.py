"""M4 Task 4.2: a promote is priced now and gated now, or it does not happen.

The API-boundary guard (`src.api.routers.commands.assert_promotable`, M4 Task 4.1) already
refuses a promote for a non-promotable stage before a command row can exist — but that guard
reads a *stored* `RiskVerdictRow`, a snapshot of what a past scan saw. This is the belt of the
belt-and-braces: the drain handler re-runs the single-ticker pricing + gating path
(`src.orchestrator.scan._price_and_gate_ticker`) for real, and only raises an approval when the
fresh run still clears the gate.

Mocking discipline (per the task brief): only the chain fetch (and the other IBKR/network
boundary calls `_stub_scan_common` in test_scan_buy_candidates_persistence.py already mocks) is
mocked. `screen_cc_candidates`/`screen_csp_candidates`, `score_candidates`, and
`validate_candidates` all run for real — the "gate rejected" scenario below is manufactured by
overloading the account's margin usage (a real, deterministic Rules Engine rejection that
applies regardless of the contract's own economics), not by faking the engine's verdict.
"""

from __future__ import annotations

import types
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import (
    AccountSnapshot,
    ApprovalStatus,
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    TechnicalStats,
)

# 24 DTE — inside the covered_call [7, 28] window (config/risk_limits.yaml).
_EXPIRY = date.today() + timedelta(days=24)


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()


def _account(*, maintenance_margin: float = 10_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=100_000.0,
        total_cash=70_000.0,
        buying_power=80_000.0,
        maintenance_margin=maintenance_margin,
        excess_liquidity=70_000.0,
    )


class _FakeChain:
    """Configures `get_option_chain_quotes_async` (the only mocked network boundary).

    `will_price` builds a realistic quote that clears the real delta/DTE/liquidity screens
    (see tests/test_strategies.py's known-good fixture combo, which this mirrors) and a stock
    position so `screen_cc_candidates` actually runs. `gate="reject"` swaps in an account with
    maintenance margin over `portfolio.max_margin_usage_pct` (50% by default) — a real,
    contract-agnostic Rules Engine rejection (`margin_limit`), so the *real* `validate_candidates`
    still runs and still says no, rather than a faked verdict.
    """

    def __init__(self, monkeypatch) -> None:
        self._monkeypatch = monkeypatch
        self.quotes: list[OptionQuote] = []
        self.side_effect: BaseException | None = None
        self.position: PositionSnapshot | None = None
        self.account: AccountSnapshot = _account()
        self._wired = False

    def will_price(
        self,
        symbol: str,
        *,
        strike: float,
        gate: str = "pass",
        premium: float = 2.50,
        delta: float = 0.28,
        dte: int = 24,
        held: bool = True,
    ) -> None:
        expiry = date.today() + timedelta(days=dte)
        self.quotes = [
            OptionQuote(
                underlying=symbol,
                right=OptionRight.CALL,
                strike=strike,
                expiry=expiry,
                bid=round(premium - 0.10, 2),
                ask=round(premium + 0.10, 2),
                volume=500,
                open_interest=2000,
                delta=delta,
                iv=0.28,
            )
        ]
        self.position = (
            PositionSnapshot(symbol=symbol, sec_type="STK", position=200.0, avg_cost=150.0)
            if held
            else None
        )
        self.account = _account(maintenance_margin=90_000.0) if gate == "reject" else _account()
        self._wire(symbol)

    def will_price_two_csp_strikes(
        self,
        symbol: str,
        *,
        strikes: tuple[float, float] = (155.0, 150.0),
        premium: float = 2.50,
        dte: int = 21,
    ) -> None:
        """A put chain offering TWO strikes on one name, both individually gate-clearing.

        The account is deliberately roomy (net-liq $2M, $600k excess liquidity) so nothing
        scarce is in play: 10 lots at either strike sit under the per-ticker collateral cap
        on their own, and both together stay under the risk-unit, cash, CSP and
        large-position ceilings. The only thing that can reject the runner-up is the risk
        gate's per-symbol dedupe — which the single-ticker deep-dive opts out of (C1).
        """
        expiry = date.today() + timedelta(days=dte)
        self.quotes = [
            OptionQuote(
                underlying=symbol,
                right=OptionRight.PUT,
                strike=strike,
                expiry=expiry,
                bid=round(premium - 0.10, 2),
                ask=round(premium + 0.10, 2),
                volume=500,
                open_interest=2000,
                delta=-0.25,
                iv=0.28,
            )
            for strike in strikes
        ]
        self.position = None  # no shares held → no covered calls, CSPs only
        self.account = AccountSnapshot(
            account="DU123456",
            net_liquidation=2_000_000.0,
            total_cash=700_000.0,
            buying_power=800_000.0,
            maintenance_margin=100_000.0,
            excess_liquidity=600_000.0,
        )
        self._wire(symbol)

    def will_vanish(self, symbol: str, *, other_strike: float = 999.0) -> None:
        """The chain succeeds but no longer offers the promoted strike."""
        expiry = date.today() + timedelta(days=24)
        self.quotes = [
            OptionQuote(
                underlying=symbol,
                right=OptionRight.CALL,
                strike=other_strike,
                expiry=expiry,
                bid=1.90,
                ask=2.10,
                volume=500,
                open_interest=2000,
                delta=0.28,
                iv=0.28,
            )
        ]
        self.position = None  # no held shares → no CC candidate at any strike
        self.account = _account()
        self._wire(symbol)

    def will_fail(self, *, exc: BaseException) -> None:
        self.side_effect = exc
        self._wire("N/A")

    def will_break_analytics(self, symbol: str, *, strike: float = 180.0) -> None:
        """The chain fetch succeeds but analytics fails outright — `TickerPricingAborted`
        ("analytics"), which the promote handler folds into `chain_unavailable` (M4 Task 4.2
        fix round: it is not a chain-fetch failure, but reports under the same "no fresh,
        honest price for this ticker" umbrella rather than inventing a fifth reason code)."""
        self.will_price(symbol, strike=strike, gate="pass")

        import src.orchestrator.scan as scanmod

        def _boom(sym: str, **_: object) -> TechnicalStats:
            raise RuntimeError("yfinance unreachable")

        self._monkeypatch.setattr(scanmod, "get_technical_stats", _boom)

    def _wire(self, symbol: str) -> None:
        import src.orchestrator.scan as scanmod

        mp = self._monkeypatch
        if self.side_effect is not None:
            mock = AsyncMock(side_effect=self.side_effect)
        else:
            mock = AsyncMock(return_value=self.quotes)
        mp.setattr(scanmod, "get_option_chain_quotes_async", mock)
        mp.setattr(scanmod, "get_positions", lambda ib: [self.position] if self.position else [])
        mp.setattr(scanmod, "get_account_snapshot_async", AsyncMock(return_value=self.account))
        mp.setattr(
            scanmod,
            "get_iv_stats",
            lambda sym, quotes=None: IVStats(symbol=sym, current_iv=28.0, iv_rank=65.0),
        )
        mp.setattr(
            scanmod,
            "get_technical_stats",
            lambda sym, **_: TechnicalStats(symbol=sym, price=170.0, rsi_14=55.0),
        )
        mp.setattr(
            scanmod,
            "get_fundamental_stats",
            lambda sym: FundamentalStats(symbol=sym, quality_flag=True),
        )
        self._wired = True


@pytest.fixture
def fake_chain(monkeypatch):
    return _FakeChain(monkeypatch)


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """A temp trading DB + fake bot + command/approval helpers, promote registered only."""
    _db_setup(tmp_path, monkeypatch)

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow, ApprovalRow, OrderRow, RiskVerdictRow

    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()
    HANDLERS.update({k: v for k, v in saved_handlers.items() if k == "promote"})

    bot = AsyncMock()
    bot.send_message = AsyncMock()

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

    def seed_assessed(
        candidate_id: str,
        *,
        stage: str,
        symbol: str,
        strike: float,
        strategy: str = "covered_call",
        expiry: date = _EXPIRY,
        premium: float = 1.00,
    ) -> None:
        """A stored assessment row — what a past scan saw. The promote handler never reads
        this; it exists only to document the (already-passed) M4 Task 4.1 precondition."""
        with session_scope() as s:
            s.add(
                RiskVerdictRow(
                    candidate_id=candidate_id,
                    run_id="seed-run",
                    symbol=symbol,
                    strategy=strategy,
                    strike=strike,
                    expiry=expiry,
                    verdict="pass" if stage == "passed" else "reject",
                    stage=stage,
                    reasons=[],
                    blended_score=80.0,
                    premium=premium,
                )
            )

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

    env = types.SimpleNamespace(
        bot=bot,
        ib=MagicMock(),  # a non-None sentinel; the fake chain mocks every real call
        enqueue=enqueue,
        status=status,
        result=result,
        seed_assessed=seed_assessed,
        approval_status=approval_status,
        order_for_approval=order_for_approval,
        approval=approval,
    )

    yield env

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


def _payload(
    *,
    candidate_id: str = "c1",
    symbol: str = "NVDA",
    strategy: str = "covered_call",
    strike: float = 180.0,
    expiry: date = _EXPIRY,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "symbol": symbol,
        "strategy": strategy,
        "strike": strike,
        "expiry": expiry.isoformat(),
    }


@pytest.mark.asyncio
async def test_a_still_passing_contract_becomes_a_pending_approval(drain_env, fake_chain) -> None:
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    approval_id = drain_env.result(cid)["approval_id"]
    assert approval_id is not None
    assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_the_deep_dive_shows_every_qualifying_strike_for_one_ticker(
    drain_env, fake_chain
) -> None:
    """C1: `_price_and_gate_ticker` must not dedupe a ticker against itself.

    The `/scan TICKER` deep-dive (and the promote that reuses its pricing path) exists so an
    operator can compare the strikes on ONE name. Every strike that individually clears the
    gate has to come back PASS; collapsing them to a single "winner" with `dedupe_pre_gate`
    would hide the alternatives the view is for. The real execution-committing gate is the
    order-approval re-validation, which keeps the dedupe on.
    """
    from src.orchestrator.scan import _price_and_gate_ticker

    fake_chain.will_price_two_csp_strikes("NVDA", strikes=(155.0, 150.0))

    priced = await _price_and_gate_ticker(drain_env.ib, "NVDA")

    csps = [c for c in priced.scored if c.strategy.value == "cash_secured_put"]
    assert {c.strike for c in csps} == {155.0, 150.0}, [c.strike for c in csps]
    verdicts = [priced.verdict_map[c.candidate_id] for c in csps]
    assert all(v.verdict.value == "pass" for v in verdicts), [
        (v.candidate_id, v.reasons) for v in verdicts
    ]
    assert all("dedupe_pre_gate" not in v.reasons for v in verdicts)
    assert {c.strike for c in priced.csp_passed} == {155.0, 150.0}


@pytest.mark.asyncio
async def test_promoting_the_lower_scored_sibling_still_succeeds(drain_env, fake_chain) -> None:
    """C1, through the promote handler: the runner-up strike on a name is still promotable.

    Before the opt-out, the deep-dive's gate rejected every strike but the best-scoring one
    with `dedupe_pre_gate`, so this promote came back `gate_rejected` — an operator could
    only ever promote whichever sibling happened to score highest.
    """
    from src.notify.command_drain import drain_once
    from src.orchestrator.scan import _price_and_gate_ticker

    fake_chain.will_price_two_csp_strikes("NVDA", strikes=(155.0, 150.0))

    # Ask the same pricing path the handler uses which sibling the gate ranks LAST —
    # `scored` is sorted by priority, and the pre-gate dedupe keeps the first survivor per
    # (underlying, strategy), so the last one is exactly the strike that used to be
    # `dedupe_pre_gate`-rejected. No assumption baked in about which strike that is.
    priced = await _price_and_gate_ticker(drain_env.ib, "NVDA")
    csps = [c for c in priced.scored if c.strategy.value == "cash_secured_put"]
    assert len(csps) == 2, [c.strike for c in csps]
    runner_up = csps[-1]

    drain_env.seed_assessed(
        "c1",
        stage="top_n",
        symbol="NVDA",
        strike=runner_up.strike,
        strategy="cash_secured_put",
        expiry=runner_up.expiry,
    )
    cid = drain_env.enqueue(
        "promote",
        _payload(
            symbol="NVDA",
            strategy="cash_secured_put",
            strike=runner_up.strike,
            expiry=runner_up.expiry,
        ),
    )

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied", drain_env.result(cid)
    approval_id = drain_env.result(cid)["approval_id"]
    assert approval_id is not None
    assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_a_promote_never_creates_an_approved_approval(drain_env, fake_chain) -> None:
    """A promote raises a proposal. Approving it is a separate human act."""
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    approval_id = drain_env.result(cid)["approval_id"]
    assert drain_env.approval_status(approval_id) != ApprovalStatus.APPROVED
    assert drain_env.order_for_approval(approval_id) is None


@pytest.mark.asyncio
async def test_a_now_rejected_contract_fails_with_the_gates_reasons(drain_env, fake_chain) -> None:
    """The gate changing its mind is the mechanism working."""
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="reject")
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    result = drain_env.result(cid)
    assert result["reason"] == "gate_rejected"
    # Surfaced verbatim from the real Rules Engine — not summarized, not softened.
    assert result["detail"]["reasons"] == ["margin_limit"]


@pytest.mark.asyncio
async def test_the_promoted_numbers_come_from_the_fresh_run(drain_env, fake_chain) -> None:
    """The stored row picks the contract. It supplies none of the numbers."""
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0, premium=1.00)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass", premium=2.50)
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    approval = drain_env.approval(drain_env.result(cid)["approval_id"])
    assert approval.snapshot["premium"] == 2.50  # not 1.00, the stale seeded row's value


@pytest.mark.asyncio
async def test_a_vanished_contract_fails_with_contract_not_priced(drain_env, fake_chain) -> None:
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_vanish("NVDA", other_strike=175.0)
    cid = drain_env.enqueue("promote", _payload(strike=180.0))

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    result = drain_env.result(cid)
    assert result["reason"] == "contract_not_priced"
    assert result["detail"]["priced_count"] == 1


@pytest.mark.asyncio
async def test_a_promote_with_no_broker_fails_honestly(drain_env) -> None:
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("promote", _payload())

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "broker_unavailable"


@pytest.mark.asyncio
async def test_a_replayed_promote_raises_no_second_approval(drain_env, fake_chain) -> None:
    """Idempotent against a replayed drain: an active order blocks a second approval.

    `has_active_order` (the same guard `queue_roll_for_approval` uses) only sees OrderRows —
    so "replayed" here means the first promote's approval was already turned into a QUEUED
    order before a second, distinct promote command for the identical contract is drained.
    """
    from src.notify.command_drain import drain_once
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")

    first = drain_env.enqueue("promote", _payload(candidate_id="c1"))
    await drain_once(drain_env.ib, drain_env.bot, "chat")
    assert drain_env.status(first) == "applied"
    first_approval_id = drain_env.result(first)["approval_id"]
    assert first_approval_id is not None

    # The first approval is already working an order (e.g. approved via M3's path).
    with session_scope() as s:
        candidate_id = drain_env.approval(first_approval_id).candidate_id
        s.add(
            OrderRow(
                candidate_id=candidate_id,
                approval_id=first_approval_id,
                state="queued",
                snapshot=drain_env.approval(first_approval_id).snapshot,
            )
        )

    second = drain_env.enqueue("promote", _payload(candidate_id="c1"))
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(second) == "applied"
    second_result = drain_env.result(second)
    assert second_result["approval_id"] is None
    assert second_result["note"] == "order_already_active"


@pytest.mark.asyncio
async def test_a_chain_fetch_failure_fails_with_chain_unavailable(drain_env, fake_chain) -> None:
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_fail(exc=RuntimeError("no market data farm connection"))
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    result = drain_env.result(cid)
    assert result["reason"] == "chain_unavailable"
    assert result["detail"]["detail"] == "no market data farm connection"


@pytest.mark.asyncio
async def test_a_ticker_pricing_abort_folds_into_chain_unavailable(drain_env, fake_chain) -> None:
    """An analytics/account-fetch failure is not a chain-fetch failure, but it reports under
    the same reason: no fresh, honest price for this ticker either way (M4 Task 4.2 fix round —
    `TickerPricingAborted` must not escape `_promote` uncaught as a bare `handler_error`)."""
    from src.notify.command_drain import drain_once

    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_break_analytics("NVDA", strike=180.0)
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    result = drain_env.result(cid)
    assert result["reason"] == "chain_unavailable"
    assert result["detail"]["stage"] == "analytics"
    assert result["detail"]["detail"] == "analytics error"


@pytest.mark.asyncio
async def test_a_dedupe_staged_promote_with_a_low_score_still_fails_with_score_below_minimum(
    drain_env, fake_chain, monkeypatch
) -> None:
    """The score-floor check is a legitimate re-derivation safeguard for every ORIGINAL
    stage except `score_floor` (final-review fix wave): a `dedupe`-staged contract is not
    "below the operator's configured minimum by design" the way a `score_floor` one is, so
    a fresh run scoring below a raised floor still fails here — proving the `score_floor`
    skip below is scoped precisely, not a blanket removal of the check."""
    from src.common.config import get_config
    from src.notify.command_drain import drain_once

    # A real candidate that clears every screen and the real Rules Engine, but with the
    # ranking floor raised above what it could ever score — the config knob a human tunes,
    # not a faked verdict.
    monkeypatch.setitem(get_config().weights, "min_candidate_score", 999.0)

    drain_env.seed_assessed("c1", stage="dedupe", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    result = drain_env.result(cid)
    assert result["reason"] == "score_below_minimum"
    assert result["detail"]["minimum"] == 999.0


@pytest.mark.asyncio
async def test_a_score_floor_staged_promote_succeeds_despite_the_low_score(
    drain_env, fake_chain, monkeypatch
) -> None:
    """Final-review fix wave: a `score_floor` promote must actually be able to succeed.

    A `score_floor` contract is, by definition, one whose score is below the configured
    minimum — that's the entire reason it's in that stage. `P2-design.md` §5.2 says
    `SCORE_FLOOR` is promotable *because* it's letting the operator go below a bar they
    configured themselves for this one contract, not re-enforcing the same bar. Before this
    fix, the unconditional `score_below_minimum` check made this structurally impossible.
    """
    from src.common.config import get_config
    from src.notify.command_drain import drain_once

    # Same "raise the floor above what it could ever score" setup as the dedupe test
    # above — the difference that matters is the ORIGINAL stored stage, `score_floor`.
    monkeypatch.setitem(get_config().weights, "min_candidate_score", 999.0)

    drain_env.seed_assessed("c1", stage="score_floor", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
    cid = drain_env.enqueue("promote", _payload())

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    approval_id = drain_env.result(cid)["approval_id"]
    assert approval_id is not None
    assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING
