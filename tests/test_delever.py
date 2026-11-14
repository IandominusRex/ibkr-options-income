"""De-lever proposals (risk-envelope Task 32; spec §3.7 items 2-3, ruling P10).

A de-lever sells a held leveraged ETF's shares (the wheel's own, not under a call) through the stock
order path and, optionally, buys its governing twin (QQQ for TQQQ, SOXX for SOXL) at up to the same
beta-dollars, each leg its own gated order, the buy only after the sell has filled."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.schemas import RepairProposal, RiskVerdict, StockOrderIntent, Verdict
from src.engine.repair import delever_proposals
from src.execution.stock_orders import StockOrderResult

NOW = datetime(2026, 11, 16, 21, 0, tzinfo=UTC)


def _inputs(*lines: BookLine) -> ShockInputs:
    return ShockInputs(
        lines=tuple(lines),
        betas={"QQQ": 1.1, "SOXX": 1.5, "TQQQ": 3.0, "SOXL": 4.0},
        betas_smh={},
        leverage={"TQQQ": 3, "SOXL": 3},
        governing={"TQQQ": "QQQ", "SOXL": "SOXX"},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=200_000.0,
    )


def _room() -> EnvelopeRoom:
    return EnvelopeRoom(
        s10_gross=20.0,
        s10_limit=18.0,
        uew=1.4,
        uew_limit=1.3,
        t20_gross=0.0,
        t20_limit=None,
        enforce="record",
        measured=True,
    )


def test_delever_sells_the_three_x_shares_and_buys_the_twin_up_to_equal_beta_dollars() -> None:
    inputs = _inputs(BookLine("TQQQ", "stock", 300.0, 60.0), BookLine("QQQ", "stock", 10.0, 500.0))
    [p] = delever_proposals(inputs, _room(), {"TQQQ": 300.0}, now=NOW, twin_spots={})
    assert (p.kind, p.symbol, p.shares, p.twin) == ("delever", "TQQQ", 300.0, "QQQ")
    sold_beta_dollars = p.shares * 60.0 * 3 * 1.1
    bought_beta_dollars = p.twin_shares * 500.0 * 1.1
    assert bought_beta_dollars <= sold_beta_dollars + 1e-6  # up to the same beta-dollars
    assert p.twin_shares == 108  # floor(300 x 60 x 3 / 500)
    # the same beta-dollars in the twin: S10 (a one-step linear move) holds at most where it was;
    # what goes is the leveraged ETF's gap and decay tail (spec §3.7 item 3)
    assert p.s10_after <= p.s10_before + 1e-6
    assert p.mark == 60.0 and p.twin_mark == 500.0
    sell_only = delever_proposals(
        _inputs(BookLine("TQQQ", "stock", 300.0, 60.0)),
        _room(),
        {"TQQQ": 300.0},
        now=NOW,
        twin_spots={"QQQ": 500.0},
    )[0]
    assert sell_only.twin_shares == 108  # the twin's price from the stored close when not held


def test_a_held_leveraged_etf_under_calls_delevers_only_the_uncovered_shares() -> None:
    inputs = _inputs(BookLine("SOXL", "stock", 500.0, 40.0))
    [p] = delever_proposals(inputs, _room(), {"SOXL": 300.0}, now=NOW, twin_spots={"SOXX": 250.0})
    assert p.shares == 300.0 and p.twin == "SOXX" and p.twin_shares == 144  # floor(300x40x3/250)


def test_no_twin_price_means_a_sell_only_proposal() -> None:
    inputs = _inputs(BookLine("TQQQ", "stock", 100.0, 60.0))
    [p] = delever_proposals(inputs, _room(), {"TQQQ": 100.0}, now=NOW, twin_spots={})
    assert p.twin == "QQQ" and p.twin_shares == 0  # never sized on a guessed price


def _proposal() -> RepairProposal:
    return RepairProposal(
        id=1,
        kind="delever",
        symbol="TQQQ",
        detail="",
        s10_before=20.0,
        s10_after=18.0,
        uew_before=1.4,
        uew_after=1.3,
        shares=300.0,
        twin="QQQ",
        twin_shares=108.0,
        mark=60.0,
        twin_mark=500.0,
    )


@pytest.fixture()
def legs(monkeypatch):
    """Record every leg the de-lever sends; each leg's result comes from *outcomes* by side."""
    from src.execution import repair_orders

    sent: list[StockOrderIntent] = []
    outcomes: dict[str, Any] = {}

    async def leg(ib: Any, intent: StockOrderIntent) -> StockOrderResult:
        sent.append(intent)
        status, filled = outcomes[intent.side]
        if status == "refused":
            return StockOrderResult("refused", intent, reasons=list(filled))
        return StockOrderResult(status, intent, filled=filled, avg_price=60.0)

    monkeypatch.setattr(repair_orders, "_leg", leg)
    monkeypatch.setattr(repair_orders, "decide", lambda *a, **k: True)
    return sent, outcomes


async def test_the_buy_leg_waits_for_the_sell_fill(legs) -> None:
    from src.execution.repair_orders import execute_delever

    sent, outcomes = legs
    outcomes.update({"SELL": ("cancelled", 0.0), "BUY": ("filled", 108.0)})
    await execute_delever(object(), _proposal(), with_twin=True)
    assert [i.side for i in sent] == ["SELL"]  # nothing filled: no buy
    sent.clear()
    outcomes["SELL"] = ("partial", 150.0)
    outcomes["BUY"] = ("filled", 54.0)
    await execute_delever(object(), _proposal(), with_twin=True)
    assert [(i.side, i.symbol, i.qty) for i in sent] == [("SELL", "TQQQ", 300), ("BUY", "QQQ", 54)]
    assert all(i.tapped and i.source == "repair" for i in sent)
    assert sent[0].ref_id != sent[1].ref_id  # each leg its own order
    sent.clear()
    outcomes["SELL"] = ("filled", 300.0)
    await execute_delever(object(), _proposal(), with_twin=False)
    assert [i.side for i in sent] == ["SELL"]  # "sell only"


async def test_the_buy_leg_passes_the_envelope(db, monkeypatch) -> None:
    """The twin's buy is a stock BUY like any other: the Rules Engine admits it only inside the
    envelope, at decision time and again at send time."""
    from src.execution import repair_orders, stock_orders

    async def quote(ib: Any, contract: Any, **_: Any) -> Any:
        return (
            stock_orders.StockQuote(59.9, 60.1)
            if contract == "TQQQ"
            else stock_orders.StockQuote(499.9, 500.1)
        )

    async def qualify(ib: Any, symbol: str) -> str:
        return symbol

    gated: list[tuple[str, str]] = []

    async def gate(ib: Any, intent: StockOrderIntent, mid: float) -> RiskVerdict:
        gated.append((intent.side, intent.symbol))
        if intent.side == "BUY":
            return RiskVerdict(candidate_id="x", verdict=Verdict.REJECT, reasons=["shock_budget"])
        return RiskVerdict(candidate_id="x", verdict=Verdict.PASS)

    async def execute(ib: Any, intent: StockOrderIntent, **_: Any) -> StockOrderResult:
        return StockOrderResult("filled", intent, filled=float(intent.qty), avg_price=60.0)

    monkeypatch.setattr(stock_orders, "qualify_stock", qualify)
    monkeypatch.setattr(stock_orders, "fetch_stock_quote", quote)
    monkeypatch.setattr(stock_orders, "send_time_gate", gate)
    monkeypatch.setattr(repair_orders, "execute_stock_order", execute)
    monkeypatch.setattr(repair_orders, "decide", lambda *a, **k: True)
    text = await repair_orders.execute_delever(object(), _proposal(), with_twin=True)
    assert gated == [("SELL", "TQQQ"), ("BUY", "QQQ")]
    assert "BUY 108 QQQ refused: shock_budget" in text
