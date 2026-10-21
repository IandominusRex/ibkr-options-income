"""The scan hands one regime context to the sizer and the gate (Task 3).

The AST test in `test_regime_sizing_integration.py` proves every production caller *names* the
`sizing` keyword; these prove the value that reaches the sizer and the gate is the persisted
regime, in a full scan and in a one-name scan (`/scan TICKER`, promote).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.market_hours import today_et
from src.common.schemas import (
    IndexRegime,
    MarketRegime,
    RegimeInputs,
    RegimeState,
    SizingContext,
)
from src.strategies._evaluation import ScreenResult
from tests.test_drain_promote import _db_setup, _FakeChain
from tests.test_scan_review_reuse import _stub_pipeline

S = MarketRegime.STRESSED
N = MarketRegime.NORMAL


def _seed_regime(spy: MarketRegime, qqq: MarketRegime) -> None:
    from src.storage.regime_state import save_regime_state

    today = today_et()

    def ir(index: str, r: MarketRegime) -> IndexRegime:
        return IndexRegime(
            index=index,  # type: ignore[arg-type]
            base=r,
            base_date=today,
            since=today,
            base_since=today,
            effective=r,
            inputs=RegimeInputs(),
        )

    save_regime_state(RegimeState(as_of=datetime.now(UTC), spy=ir("SPY", spy), qqq=ir("QQQ", qqq)))


@pytest.mark.asyncio
async def test_a_full_scan_sizes_and_gates_with_the_persisted_regime(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    monkeypatch.setattr(get_config(), "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "t"}})
    _seed_regime(N, S)
    cand = _stub_pipeline(scanmod, monkeypatch, {"n": 0})

    seen: dict[str, object] = {}

    def screen(*args, **kwargs):
        seen["screen"] = kwargs.get("sizing")
        return ScreenResult(passed=[cand])

    def gate(scored, account, positions, **kwargs):
        seen["gate"] = kwargs.get("sizing")
        return [
            SimpleNamespace(candidate_id=c.candidate_id, verdict=SimpleNamespace(value="pass"))
            for c in scored
        ]

    monkeypatch.setattr(scanmod, "screen_csp_candidates", screen)
    monkeypatch.setattr(scanmod, "validate_candidates", gate)

    result = await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")
    assert result.regime is not None and result.regime.qqq.effective == S

    sizing = seen["screen"]
    assert isinstance(sizing, SizingContext)
    assert sizing.regimes == {"SPY": N, "QQQ": S}
    assert seen["gate"] is sizing  # one context, built once per scan, shared by sizer and gate


@pytest.mark.asyncio
async def test_a_one_name_scan_sizes_under_the_persisted_regime(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod

    _seed_regime(N, S)  # QQQ stressed: NVDA is tech-linked, so its per-trade ceiling is 3 of 10
    chain = _FakeChain(monkeypatch)
    chain.will_price_two_csp_strikes("NVDA", strikes=(155.0, 150.0))

    result = await scanmod._price_and_gate_ticker(MagicMock(), "NVDA")

    assert result.scored, "the roomy test account should price both strikes"
    for cand in result.scored:
        assert cand.contracts <= 3
        assert cand.sizing is not None
        assert cand.sizing.regime == S and cand.sizing.regime_index == "QQQ"
        assert cand.sizing.pre_regime_contracts > cand.contracts
    # and the same name with the regime normal is not trimmed
    _seed_regime(N, N)
    result_normal = await scanmod._price_and_gate_ticker(MagicMock(), "NVDA")
    assert max(c.contracts for c in result_normal.scored) > 3


@pytest.mark.asyncio
async def test_the_send_time_regate_receives_a_for_send_context(tmp_path, monkeypatch):
    """The order poll builds its own context before the write session, with queued orders
    excluded from the day's counts (they are the batch being re-validated)."""
    _db_setup(tmp_path, monkeypatch)
    import src.execution.approval as approval

    _seed_regime(N, S)
    seen: dict[str, object] = {}

    def fake_gate(cands, account, positions, **kwargs):
        seen["sizing"] = kwargs.get("sizing")
        return []

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr(approval, "get_config", lambda: mock_cfg)
    monkeypatch.setattr(approval, "is_rth", lambda: True)
    monkeypatch.setattr(approval, "validate_candidates", fake_gate)
    monkeypatch.setattr(approval, "get_positions", lambda ib: [])
    monkeypatch.setattr(
        approval,
        "get_account_snapshot_async",
        AsyncMock(
            return_value=SimpleNamespace(net_liquidation=100_000.0)  # evaluate_breakers reads it
        ),
    )
    monkeypatch.setattr(approval, "evaluate_breakers", lambda positions, nlv: None)
    monkeypatch.setattr(approval, "remaining_entry_allowance", lambda s: None)

    from src.storage.db import session_scope
    from tests.test_execution import _insert_candidate_row, _insert_queued_order, _make_candidate

    candidate = _make_candidate()
    with session_scope() as session:
        _insert_candidate_row(session, candidate)
        _insert_queued_order(session, candidate.candidate_id)

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    await approval.process_queued_orders(mock_ib, AsyncMock(), "99999")

    sizing = seen["sizing"]
    assert isinstance(sizing, SizingContext)
    assert sizing.for_send is True
    assert sizing.regimes == {"SPY": N, "QQQ": S}
