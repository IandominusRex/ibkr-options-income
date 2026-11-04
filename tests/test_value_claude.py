"""Claude's reads on the value side: acceptance, opinions, the effective verdict, the breaker and
the queue (value book spec §6.7, §8.2, §8.3, §8.5)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

import src.value.store as store
from src.common.config import ValueCfg, get_config
from src.common.value_ai_types import (
    AnalystCall,
    AnalystReply,
    AnalystRequest,
    AnalystResult,
    Drivers,
    KillTrigger,
    ListCall,
)
from src.value import claude_verdicts as cv
from src.value.claude_reads import (
    build_request,
    plan_auto_reads,
    queue_read,
    reads_left,
    render_card,
    run_queue,
)
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueClaudeNoteRow,
    ValueClaudeReadRow,
    ValueClaudeVerdictRow,
    ValueEffectiveRow,
    ValueKillTriggerRow,
    ValueReevaluationRow,
    ValueRunRow,
    init_value_db,
    value_session,
)
from src.value.ticker_file import persist
from tests.value_fixtures import financials, inputs

CFG = get_config().value
ON = CFG.model_copy(update={"claude": CFG.claude.model_copy(update={"enabled": True})})
NOW = datetime(2026, 11, 2, 15, 0)  # naive UTC, 10:00 ET
CHEAP = build_scorecard(inputs(close=30.0), CFG)  # deep: Python FV 46.85, READY
DEAR = build_scorecard(inputs(close=40.0), CFG)  # deep: Python WAIT
GOOD_DRIVERS = Drivers(growth=0.08, terminal=0.02, discount=0.10, margin=0.15)


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def _file(card, *, universe: str = "trading", rank: float = 0.9) -> None:
    with value_session() as s:
        persist(
            s,
            card,
            universe=universe,
            ranks={"deep_value": rank, "quality_growth": rank},
            filed="deep_value",
            cfg=CFG.ticker_file,
            session_row=False,
        )


def _result(read_id: int, *, verdict="READY", drivers=GOOD_DRIVERS, backend="cli", **reply):
    return AnalystResult(
        read_id=read_id,
        reply=AnalystReply(
            lists=[ListCall(list_name="deep_value", verdict=verdict, why="w", drivers=drivers)],
            profile="p",
            **reply,
        ),
        call=AnalystCall(model="sonnet", backend=backend, latency_ms=5, prompt="P", raw="R"),
    )


def _accept(card, result, *, kind="standard", reevaluation_id=None):
    with value_session() as s:
        read = ValueClaudeReadRow(
            symbol=card.symbol,
            kind=kind,
            reason="request",
            priority=0,
            requested_at=NOW,
            reevaluation_id=reevaluation_id,
        )
        s.add(read)
        s.flush()
        return cv.accept(
            s, read, result.model_copy(update={"read_id": read.id}), card, CFG, now=NOW
        )


def _verdicts():
    with value_session() as s:
        return list(s.scalars(select(ValueClaudeVerdictRow).order_by(ValueClaudeVerdictRow.id)))


def test_a_read_stores_the_bounded_drivers_and_pythons_capped_value(value_db) -> None:
    wild = Drivers(growth=0.40, terminal=0.03, discount=0.07, margin=0.30)
    out = _accept(CHEAP, _result(0, drivers=wild))
    assert out.verdicts == 1
    (v,) = _verdicts()
    assert v.verdict == "READY" and v.backend == "cli" and v.superseded is False
    assert v.fair_value == pytest.approx(1.5 * 46.853626592284414) and v.clamp_bound is True
    assert v.uncapped == pytest.approx(106.19430864505932)
    assert len(json.loads(v.clamps_json)) == 4  # every driver out of bounds, recorded
    assert v.accn == "0000000001-26-000001"
    with value_session() as s:
        read = s.scalars(select(ValueClaudeReadRow)).one()
        assert (read.status, read.model, read.prompt, read.raw) == ("done", "sonnet", "P", "R")
        assert s.scalars(select(ValueClaudeNoteRow)).one().profile == "p"


def test_a_malformed_reply_stores_the_call_and_nothing_else(value_db) -> None:
    result = AnalystResult(read_id=0, call=AnalystCall(error="unparseable", raw="?"))
    _accept(CHEAP, result)
    assert _verdicts() == []
    with value_session() as s:
        assert s.scalars(select(ValueClaudeReadRow)).one().status == "failed"
        assert s.scalars(select(ValueClaudeNoteRow)).all() == []


def test_between_filings_a_reread_can_lower_but_never_raise(value_db) -> None:
    _accept(
        CHEAP, _result(0, drivers=Drivers(growth=0.05, terminal=0.02, discount=0.10, margin=0.14))
    )
    low = _verdicts()[0].fair_value
    out = _accept(
        CHEAP, _result(0, drivers=Drivers(growth=0.12, terminal=0.025, discount=0.09, margin=0.16))
    )
    assert out.kept_earlier == 1
    first, second = _verdicts()
    assert first.superseded is True and second.fair_value == pytest.approx(low)
    assert "raised between filings" in second.clamps_json
    # a new 10-Q (a new accession) lets the drivers move either way
    filed = build_scorecard(inputs(close=30.0, fin=financials(accn="0000000001-26-000002")), CFG)
    _accept(
        filed, _result(0, drivers=Drivers(growth=0.12, terminal=0.025, discount=0.09, margin=0.16))
    )
    assert _verdicts()[-1].fair_value > low


def test_an_ollama_reply_is_stored_labelled_and_is_never_an_opinion(value_db) -> None:
    _accept(CHEAP, _result(0, backend="ollama"))
    (v,) = _verdicts()
    assert v.backend == "ollama"
    with value_session() as s:
        assert cv.opinions(s, [CHEAP], CFG.rules) == {}


def test_kill_triggers_are_bounded_and_replace_the_old_set(value_db) -> None:
    triggers = [
        KillTrigger(kind="dilution_above", threshold=25.0),  # bounded to 10
        KillTrigger(kind="net_debt_to_ebitda_above", threshold=None),  # no threshold: dropped
        KillTrigger(kind="guidance_cut"),
    ]
    _accept(CHEAP, _result(0, kill_triggers=triggers))
    _accept(CHEAP, _result(0, kill_triggers=[KillTrigger(kind="fcf_ttm_negative")]))
    with value_session() as s:
        rows = s.scalars(select(ValueKillTriggerRow).order_by(ValueKillTriggerRow.id)).all()
        assert [(r.kind, r.threshold, r.active) for r in rows] == [
            ("dilution_above", 10.0, False),
            ("guidance_cut", None, False),
            ("fcf_ttm_negative", None, True),
        ]


def test_a_review_writes_its_state_on_the_reevaluation(value_db) -> None:
    with value_session() as s:
        r = ValueReevaluationRow(
            shadow_id=1,
            symbol="STDY",
            list_name="deep_value",
            session=date(2026, 10, 30),
            last_session=date(2026, 10, 30),
            severity="major",
            triggers_json="[]",
            plan_before_json="{}",
            plan_after_json="{}",
            verdict_at_entry="READY",
            ruleset_version="v4",
            ruleset_hash="x",
            created_at=NOW,
        )
        s.add(r)
        s.flush()
        rid = r.id
    out = _accept(
        CHEAP,
        _result(0, review_state="BROKEN", review_why="lost a customer"),
        kind="review",
        reevaluation_id=rid,
    )
    assert out.review_state == "BROKEN"
    with value_session() as s:
        assert s.get(ValueReevaluationRow, rid).review_state == "BROKEN"


def test_opinions_recompute_on_tonights_card_and_the_effective_verdict_is_written(value_db) -> None:
    _accept(
        DEAR, _result(0, drivers=Drivers(growth=0.12, terminal=0.025, discount=0.09, margin=0.16))
    )
    with value_session() as s:
        ops = cv.opinions(s, [DEAR], CFG.rules)
        opinion, value = ops[("STDY", "deep_value")]
        # 16% x $16 of revenue a share, 12% for five years: 68.72, under the 70.28 cap
        assert opinion.fair_value == value.fair_value == pytest.approx(68.71811198864627)
        eff = cv.persist_effective(
            s, [DEAR], ops, applied=True, as_of=DEAR.as_of, now=NOW, review_above_pct=60.0
        )
        assert eff[("STDY", "deep_value")].verdict == "READY"  # Claude lifts Python's WAIT
        cv.persist_effective(
            s, [DEAR], ops, applied=False, as_of=DEAR.as_of, now=NOW, review_above_pct=60.0
        )
        row = s.get(ValueEffectiveRow, ("STDY", "deep_value"))
        assert (row.verdict, row.decided_by) == ("WAIT", "python")


def test_claude_applies_in_paper_in_live_only_with_apply_live_and_never_while_tripped(
    value_db,
) -> None:
    live_on = CFG.model_copy(update={"claude": CFG.claude.model_copy(update={"apply_live": True})})
    with value_session() as s:
        assert cv.applies(s, CFG, is_live=False) is True
        assert cv.applies(s, CFG, is_live=True) is False  # record-only in live
        assert cv.applies(s, live_on, is_live=True) is True
        cv.set_breaker(s, {"tripped": True, "reason": "x"}, NOW)
        assert cv.applies(s, CFG, is_live=False) is False
        cv.reset_breaker(s, NOW)
        assert cv.applies(s, CFG, is_live=False) is True


def _night(s, as_of: date, **claude: int) -> None:
    s.add(
        ValueRunRow(
            kind="nightly",
            started_at=NOW,
            as_of=as_of,
            ruleset_version="v4",
            ruleset_hash="x",
            summary_json=json.dumps({"claude": claude}),
        )
    )


def test_the_breaker_trips_on_the_ready_multiple_and_on_the_clamp_rate(value_db) -> None:
    with value_session() as s:
        for i in range(3):
            _night(s, date(2026, 10, 20 + i), ready=2, baseline_ready=1, values=2, clamped=0)
        # 6 + 2 READY against 3 baseline: below 3x (9); then tonight's 4 makes 10 > 9
        assert (
            cv.check_breaker(
                s, CFG, {"ready": 2, "baseline_ready": 0, "values": 1, "clamped": 0}, NOW
            )
            is False
        )
        assert (
            cv.check_breaker(
                s, CFG, {"ready": 4, "baseline_ready": 0, "values": 1, "clamped": 0}, NOW
            )
            is True
        )
        assert "Claude READY 10" in cv.breaker_state(s)["reason"]
    with value_session() as s:
        cv.reset_breaker(s, NOW)
        # clamp rate: 3 of 9 values (33% > 25%) with at least 8 values read
        tonight = {"ready": 0, "baseline_ready": 0, "values": 3, "clamped": 3}
        assert cv.check_breaker(s, CFG, tonight, NOW) is True
        assert "set 3 of 9" in cv.breaker_state(s)["reason"]


def test_the_queue_reads_the_top_unread_trading_names_and_stale_ones(value_db) -> None:
    _file(CHEAP)
    _file(build_scorecard(inputs(symbol="EVID", close=30.0), CFG), universe="evidence")
    with value_session() as s:
        assert plan_auto_reads(s, NOW, ON) == {"top": 1, "stale": 0}
        assert [r.symbol for r in s.scalars(select(ValueClaudeReadRow))] == ["STDY"]
    _accept(CHEAP, _result(0))
    with value_session() as s:
        assert plan_auto_reads(s, NOW, ON) == {"top": 0, "stale": 0}  # read, nothing changed
    filed = build_scorecard(inputs(close=30.0, fin=financials(accn="0000000001-26-000002")), CFG)
    _file(filed)
    with value_session() as s:
        assert plan_auto_reads(s, NOW, ON) == {"top": 0, "stale": 1}  # a new filing


def test_the_daily_caps_and_a_disabled_switch(value_db) -> None:
    _file(CHEAP)
    tight = ON.model_copy(
        update={"claude": ON.claude.model_copy(update={"standard_reads_per_day": 1})}
    )
    seen: list[AnalystRequest] = []

    def reader(req: AnalystRequest) -> AnalystResult:
        seen.append(req)
        return _result(req.read_id)

    with value_session() as s:
        queue_read(s, "STDY", kind="standard", reason="request", now=NOW)
    assert run_queue(reader, now=NOW, cfg=CFG) == {
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "waiting": 0,
    }
    assert run_queue(reader, now=NOW, cfg=tight)["done"] == 1
    (req,) = seen
    assert req.lists == ["deep_value", "quality_growth"] and req.bounds
    assert req.kill_menu["guidance_cut"] is None and req.model == get_config().claude.model
    with value_session() as s:
        assert reads_left(s, NOW, tight) == (0, 3)
        queue_read(s, "STDY", kind="standard", reason="request", now=NOW)
    assert run_queue(reader, now=NOW, cfg=tight)["done"] == 0  # today's cap is spent
    with value_session() as s:
        assert reads_left(s, NOW + timedelta(days=1), tight) == (1, 3)  # a new ET day


def test_the_request_carries_the_card_the_bounds_and_the_kind_model(value_db) -> None:
    models = ValueCfg(
        ruleset_version="v4", claude={"models": {"verdict": "claude-opus-4-7"}}
    ).model_copy(update={"rules": CFG.rules})
    row = ValueClaudeReadRow(id=9, symbol="STDY", kind="standard", reason="top", priority=3)
    req = build_request(row, CHEAP, models)
    assert req.model == "claude-opus-4-7" and req.read_id == 9
    assert "deep_value: Python READY · fair value 46.85" in req.card_text
    assert render_card(CHEAP).count("\n") >= 6


def test_the_operator_script_queues_a_read_and_resets_the_breaker(value_db, capsys) -> None:
    from scripts.value_claude import main

    assert main(["--read", "nvda"]) == 0
    assert main(["--read", "NVDA", "--reset-breaker"]) == 0
    out = capsys.readouterr().out
    assert "queued NVDA" in out and "NVDA: already queued" in out and "breaker reset" in out


def test_a_filing_read_stores_each_fact_with_its_grounding(value_db) -> None:
    from src.common.value_ai_types import FilingSection, ProposedFact
    from src.value.store import ValueClaudeFactRow

    sections = [
        FilingSection(
            accn="0000000001-26-000001",
            form="10-K",
            section="Item 7 MD&A",
            text="We now expect revenue to decline. A customer that was 18% of sales left.",
        )
    ]
    facts = [
        ProposedFact(
            kind="guidance_cut",
            accn="0000000001-26-000001",
            quote="We now expect revenue to decline.",
        ),
        ProposedFact(
            kind="customer_concentration",
            value=21.0,
            unit="pct",
            accn="0000000001-26-000001",
            quote="A customer that was 18% of sales left.",
        ),
    ]
    result = AnalystResult(
        read_id=0,
        reply=AnalystReply(facts=facts),
        call=AnalystCall(model="sonnet", backend="cli"),
    )
    with value_session() as s:
        read = ValueClaudeReadRow(
            symbol="STDY",
            kind="filing",
            reason="filing",
            priority=2,
            requested_at=NOW,
            accn="0000000001-26-000001",
        )
        s.add(read)
        s.flush()
        out = cv.accept(s, read, result, CHEAP, CFG, now=NOW, sections=sections)
        assert (out.facts, out.dropped) == (1, 1)
    with value_session() as s:
        rows = {r.kind: (r.grounded, r.why) for r in s.scalars(select(ValueClaudeFactRow))}
        assert rows == {
            "guidance_cut": (True, ""),
            "customer_concentration": (False, "the number is not in the quote"),
        }
        assert s.scalars(select(ValueClaudeNoteRow)).all() == []  # a filing read writes no prose


def test_filing_reads_are_queued_once_per_filing_and_wait_for_their_sections(value_db) -> None:
    from src.common.value_types import FilingEvent
    from src.value.claude_reads import plan_filing_reads

    _file(CHEAP)
    q10 = FilingEvent(accn="0000000001-26-000003", form="10-Q", filed=date(2026, 5, 5))
    with value_session() as s:
        assert plan_filing_reads(s, {"STDY": q10}, NOW) == 1
        assert plan_filing_reads(s, {"STDY": q10}, NOW) == 0  # already queued for that filing
    calls: list[AnalystRequest] = []
    no_sections = run_queue(calls.append, now=NOW, cfg=ON, sections_for=lambda sym, accn: [])
    assert no_sections["waiting"] == 1 and calls == []
    later = run_queue(
        calls.append, now=NOW + timedelta(days=8), cfg=ON, sections_for=lambda sym, accn: []
    )
    assert later["skipped"] == 1  # the sections never came: dropped after a week
