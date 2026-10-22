"""Task 14: Claude's reduce-only size cut on auto-opened cash-secured puts.

The one place an LLM value reaches a contract count. The properties these tests pin, and the order
they matter in: a cut can only LOWER the deterministic size (never raise it, never set a strike or
a price); anything malformed, out of range, missing, or produced by the local model changes
nothing; it is applied in paper and only RECORDED in live; a daily breaker stops a prompt or schema
regression from silently zeroing the book; and every override, applied or not, leaves a row."""

from __future__ import annotations

import itertools
import json
from datetime import date
from types import SimpleNamespace

import pytest

from src.common.config import ClaudeCutCfg, get_claude_cut_cfg, get_config
from src.common.market_hours import today_et
from src.common.schemas import (
    AutonomyLevel,
    ClaudeReview,
    MarketRegime,
    OptionRight,
    RollOrigin,
    ScoreCard,
    SizingNote,
    Strategy,
    TradeCandidate,
)
from src.engine.regime_limits import claude_cut, cut_applies, with_claude_cut
from src.notify import sender
from src.notify.formatters import _md, format_candidate
from src.storage.models import OrderRow, SizingActionRow

CFG = ClaudeCutCfg()  # shipped defaults: paper on, live off, breaker 4 / 50%


def _csp(
    cid: str = "csp-1",
    underlying: str = "TQQQ",
    contracts: int = 10,
    strike: float = 65.0,
    *,
    note: SizingNote | None = None,
    roll: bool = False,
) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=cid,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying=underlying,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date(2026, 11, 20),
        contracts=contracts,
        premium=1.5,
        collateral=strike * contracts * 100,
        roc_pct=0.8,
        annualized_yield_pct=18.0,
        breakeven=strike - 1.5,
        prob_otm=0.7,
        delta=-0.25,
        iv_rank=60.0,
        dte=29,
        scores=ScoreCard(symbol=underlying),
        blended_score=80.0,
        sizing=note,
        roll_from=(
            RollOrigin(
                strike=strike,
                expiry=date(2026, 10, 30),
                right=OptionRight.PUT,
                contracts=contracts,
                chain_id="chain-1",
                seq=1,
                original_expiry=date(2026, 10, 30),
                old_mid=1.0,
                new_mid=1.5,
            )
            if roll
            else None
        ),
    )


def _cc(cid: str = "cc-1", contracts: int = 4) -> TradeCandidate:
    return _csp(cid, "AAPL", contracts, 200.0).model_copy(
        update={"strategy": Strategy.COVERED_CALL, "right": OptionRight.CALL}
    )


def _review(
    cid: str,
    max_contracts: int | None,
    *,
    backend: str | None = "cli",
    reason: str = "FOMC falls inside the window (N2)",
) -> ClaudeReview:
    return ClaudeReview(
        candidate_id=cid,
        priority=1,
        recommendation="sell",
        why_attractive="a",
        risks="b",
        tradeoffs="c",
        assignment_considerations="d",
        max_contracts=max_contracts,
        size_reason=reason,
        backend=backend,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# The clamp
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("suggested", "backend", "expected"),
    [
        (3, "cli", 3),
        (0, "cli", 0),
        (10, "cli", 10),
        (12, "cli", 10),  # above the deterministic size: ignored, never raised
        (-1, "cli", 10),  # negative
        (None, "cli", 10),  # missing
        (True, "cli", 10),  # a bool is not an integer count
        (False, "cli", 10),
        (3.0, "cli", 10),  # not an int
        ("3", "cli", 10),  # text
        ([3], "cli", 10),
        (3, "ollama", 10),  # the local model's number is never applied
        (3, None, 10),  # an old review with no recorded backend
        (3, "CLI", 10),  # only the exact stamp the runner writes counts
        (0, "ollama", 10),
    ],
)
def test_claude_cut_is_clamped_and_ignored_when_untrusted(suggested, backend, expected) -> None:
    assert claude_cut(10, suggested, backend) == expected


def test_claude_cut_can_only_lower_the_size() -> None:
    """Exhaustive: for every size, suggestion and backend the answer is the deterministic size
    or Claude's own valid number below it, never above, never negative."""
    values = [None, True, False, -5, -1, 0, 1, 2, 3, 9, 10, 11, 99, 2.5, "2", [1]]
    for det, suggested, backend in itertools.product(range(0, 13), values, ("cli", "ollama", None)):
        n = claude_cut(det, suggested, backend)
        assert 0 <= n <= det, (det, suggested, backend, n)
        assert n == det or (
            backend == "cli"
            and isinstance(suggested, int)
            and not isinstance(suggested, bool)
            and n == suggested
        )


def test_a_zero_size_has_nothing_to_cut() -> None:
    assert claude_cut(0, 0, "cli") == 0
    assert claude_cut(0, 5, "cli") == 0


@pytest.mark.parametrize(
    ("is_live", "zeroed", "reviewed", "cfg", "expected"),
    [
        (False, 0, 0, CFG, (True, None)),
        (True, 0, 0, CFG, (False, "live_record_only")),  # live ships record-only
        (False, 0, 0, ClaudeCutCfg(apply_in_paper=False), (False, "paper_record_only")),
        (True, 0, 0, ClaudeCutCfg(apply_live=True), (True, None)),  # the operator switched it on
        (False, 3, 6, CFG, (True, None)),  # one short of the breaker's count
        (False, 4, 6, CFG, (False, "breaker")),  # 4 zeroed, 67% of the day's reviews
        (False, 4, 8, CFG, (True, None)),  # exactly 50% is not "more than" 50%
        (False, 5, 8, CFG, (False, "breaker")),
        (True, 4, 6, ClaudeCutCfg(apply_live=True), (False, "breaker")),  # the breaker is live too
        (False, 4, 0, CFG, (False, "breaker")),  # a lost reviewed counter fails safe
        (True, 9, 9, CFG, (False, "live_record_only")),  # record-only wins over the breaker's why
    ],
)
def test_cut_applies(is_live, zeroed, reviewed, cfg, expected) -> None:
    assert (
        cut_applies(is_live=is_live, zeroed_today=zeroed, reviewed_today=reviewed, cfg=cfg)
        == expected
    )


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_the_shipped_block_matches_the_defaults() -> None:
    cfg = get_claude_cut_cfg()
    assert (cfg.apply_in_paper, cfg.apply_live, cfg.breaker_min, cfg.breaker_pct) == (
        True,
        False,
        4,
        50,
    )


def test_the_block_refuses_an_unknown_key_and_a_silly_value() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        ClaudeCutCfg(apply_in_papper=False)  # a typo must not silently keep a default
    with pytest.raises(ValueError):
        ClaudeCutCfg(breaker_min=0)
    with pytest.raises(ValueError):
        ClaudeCutCfg(breaker_pct=0)
    with pytest.raises(ValueError):
        ClaudeCutCfg(breaker_pct=101)


def test_the_key_list_matches_the_model_fields() -> None:
    assert set(ClaudeCutCfg.KEYS) == set(ClaudeCutCfg.model_fields)


def test_the_cut_block_is_read_from_risk_limits(monkeypatch) -> None:
    monkeypatch.setitem(get_config().risk, "claude_cut", {"apply_live": True, "breaker_min": 2})
    cfg = get_claude_cut_cfg()
    assert cfg.apply_live is True and cfg.breaker_min == 2 and cfg.apply_in_paper is True


# --------------------------------------------------------------------------- #
# The note
# --------------------------------------------------------------------------- #


def test_the_cut_note_carries_claudes_number_and_reason() -> None:
    base = SizingNote(
        pre_regime_contracts=10,
        regime=MarketRegime.STRESSED,
        regime_index="QQQ",
        per_trade_cap=3,
        budget_multiplier=0.4,
    )
    cut = with_claude_cut(base, 3, 1, "FOMC inside the window")
    assert (cut.claude_suggested, cut.claude_reason) == (1, "FOMC inside the window")
    assert cut.pre_regime_contracts == 10 and cut.regime == MarketRegime.STRESSED  # untouched
    bare = with_claude_cut(None, 3, 1, "x")  # a candidate built without a context
    assert bare.claude_suggested == 1 and bare.pre_regime_contracts == 3


# --------------------------------------------------------------------------- #
# The auto branch
# --------------------------------------------------------------------------- #


class _Harness:
    """The auto branch with a recording Bot, halt switch off, and the config the real one reads."""

    def __init__(self, db, monkeypatch) -> None:
        self.db = db
        self.messages: list[dict] = []
        outer = self

        class _Bot:
            def __init__(self, token: str) -> None:
                self.token = token

            async def __aenter__(self) -> _Bot:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def send_message(self, **kw: object) -> None:
                outer.messages.append(kw)

        monkeypatch.setattr(sender, "Bot", _Bot)
        monkeypatch.setattr(sender, "is_halted", lambda: False)

    async def queue(
        self,
        candidates: list[TradeCandidate],
        reviews: list[ClaudeReview],
        *,
        is_live: bool = False,
    ) -> bool:
        cfg = SimpleNamespace(
            approval=SimpleNamespace(ttl_minutes=60),
            is_live=is_live,
            secrets=SimpleNamespace(telegram_thread_account="58"),
        )
        return await sender._auto_queue_candidates(
            candidates, cfg, "token", "chat", 52, reviews=reviews
        )

    def orders(self) -> list[OrderRow]:
        with self.db() as s:
            rows = s.query(OrderRow).order_by(OrderRow.id).all()
            s.expunge_all()
            return rows

    def actions(self, kind: str | None = None) -> list[SizingActionRow]:
        with self.db() as s:
            q = s.query(SizingActionRow).order_by(SizingActionRow.id)
            if kind:
                q = q.filter_by(kind=kind)
            rows = q.all()
            s.expunge_all()
            return rows

    def texts(self) -> list[str]:
        return [str(m["text"]) for m in self.messages]

    def seed_zero_cuts(self, n: int) -> None:
        """n earlier applied cuts-to-zero today (the breaker counts these)."""
        with self.db() as s:
            for i in range(n):
                s.add(
                    SizingActionRow(
                        candidate_id=f"zeroed-{i}",
                        underlying="TQQQ",
                        strategy="cash_secured_put",
                        right="P",
                        strike=60.0,
                        expiry=date(2026, 11, 20),
                        premium=1.0,
                        kind="claude_cut",
                        regime="normal",
                        deterministic_contracts=3,
                        sent_contracts=0,
                        reason="x",
                        action_day=today_et(),
                        record_key=f"zeroed-{i}",
                    )
                )

    def seed_reviewed(self, n: int) -> None:
        """n auto CSPs Claude has already reviewed today (the breaker's denominator)."""
        from src.storage.system_settings import set_setting

        set_setting(
            "claude_cut_state",
            json.dumps({"day": today_et().isoformat(), "reviewed": [f"rev-{i}" for i in range(n)]}),
        )


@pytest.fixture()
def h(db, monkeypatch) -> _Harness:
    monkeypatch.setitem(get_config().risk, "claude_cut", {})  # the shipped defaults
    return _Harness(db, monkeypatch)


async def test_auto_branch_applies_the_cut_and_records_it(h) -> None:
    cand = _csp("c1", contracts=10)
    assert await h.queue([cand], [_review("c1", 3)]) is True

    (order,) = h.orders()
    assert order.snapshot["contracts"] == 3  # frozen at Claude's lower number
    assert order.snapshot["collateral"] == 65.0 * 3 * 100
    assert order.snapshot["sizing"]["claude_suggested"] == 3
    assert order.snapshot["sizing"]["claude_reason"] == "FOMC falls inside the window (N2)"
    assert order.snapshot["strike"] == 65.0 and order.snapshot["premium"] == 1.5  # nothing else
    (row,) = h.actions("claude_cut")
    assert (row.deterministic_contracts, row.sent_contracts) == (10, 3)
    assert row.order_id == order.id and row.candidate_id == "c1"
    assert "FOMC" in row.reason
    assert h.actions("claude_cut_unapplied") == []


async def test_a_cut_never_raises_the_size_or_changes_anything_else(h) -> None:
    cand = _csp("c1", contracts=3)
    await h.queue([cand], [_review("c1", 50)])  # Claude asks for more than the card
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 3
    assert h.actions() == []  # an ignored value is not an override


async def test_keeping_the_size_records_nothing(h) -> None:
    await h.queue([_csp("c1", contracts=4)], [_review("c1", 4)])
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 4
    assert h.actions() == []


async def test_cut_to_zero_queues_nothing(h) -> None:
    cand = _csp("c1", contracts=3)
    sent = await h.queue([cand], [_review("c1", 0, reason="guidance cut reported (N4)")])
    assert h.orders() == []  # not queued
    (row,) = h.actions("claude_cut")
    assert (row.deterministic_contracts, row.sent_contracts, row.order_id) == (3, 0, None)
    assert sent is True  # the operator is told
    assert any(
        _md("Claude: not sending TQQQ 65P (3 lots): guidance cut reported (N4)") in t
        for t in h.texts()
    )

    # The next 15-minute cycle sees the same candidate and the same review: still nothing
    # queued, still one row, and no second message about it.
    n_messages = len(h.messages)
    await h.queue([cand], [_review("c1", 0, reason="guidance cut reported (N4)")])
    assert h.orders() == [] and len(h.actions("claude_cut")) == 1
    assert len(h.messages) == n_messages


async def test_a_later_review_that_keeps_the_size_corrects_the_record(h) -> None:
    cand = _csp("c1", contracts=3)
    await h.queue([cand], [_review("c1", 0)])
    await h.queue([cand], [_review("c1", 3)])  # next cycle's review keeps the size
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 3
    (row,) = h.actions("claude_cut")
    assert (row.deterministic_contracts, row.sent_contracts, row.order_id) == (3, 3, order.id)


async def test_live_mode_records_but_sends_the_deterministic_size(h) -> None:
    cand = _csp("c1", contracts=10)
    await h.queue([cand], [_review("c1", 3)], is_live=True)
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 10  # live: the system's own size goes out
    assert order.snapshot["sizing"] is None or order.snapshot["sizing"]["claude_suggested"] is None
    assert h.actions("claude_cut") == []
    (row,) = h.actions("claude_cut_unapplied")
    assert (row.deterministic_contracts, row.sent_contracts) == (10, 10)
    assert row.reason.startswith("live_record_only")
    assert "Claude suggested 3" in row.reason and "FOMC" in row.reason
    assert row.order_id == order.id


async def test_live_mode_cut_to_zero_still_sends_the_order(h) -> None:
    await h.queue([_csp("c1", contracts=5)], [_review("c1", 0)], is_live=True)
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 5
    (row,) = h.actions("claude_cut_unapplied")
    assert "Claude suggested 0" in row.reason


async def test_live_mode_applies_it_only_when_the_operator_switches_it_on(h, monkeypatch) -> None:
    monkeypatch.setitem(get_config().risk, "claude_cut", {"apply_live": True})
    await h.queue([_csp("c1", contracts=10)], [_review("c1", 3)], is_live=True)
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 3
    assert len(h.actions("claude_cut")) == 1


async def test_paper_mode_can_be_switched_to_record_only(h, monkeypatch) -> None:
    monkeypatch.setitem(get_config().risk, "claude_cut", {"apply_in_paper": False})
    await h.queue([_csp("c1", contracts=10)], [_review("c1", 3)])
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 10
    (row,) = h.actions("claude_cut_unapplied")
    assert row.reason.startswith("paper_record_only")


async def test_the_local_model_and_untrusted_reviews_change_nothing(h) -> None:
    cands = [_csp(f"c{i}", contracts=6, strike=60.0 + i) for i in range(4)]
    reviews = [
        _review("c0", 1, backend="ollama"),  # the local model
        _review("c1", 1, backend=None),  # a review from before the backend was recorded
        _review("c2", None),  # no number at all
        # A review object that skipped validation and carries a string / a bool / a float:
        ClaudeReview.model_construct(
            candidate_id="c3", max_contracts="1", backend="cli", size_reason="x"
        ),
    ]
    await h.queue(cands, reviews)
    assert [o.snapshot["contracts"] for o in h.orders()] == [6, 6, 6, 6]
    assert h.actions() == []
    for bad in (True, 1.0, -1, 7):
        h2 = ClaudeReview.model_construct(
            candidate_id="c3", max_contracts=bad, backend="cli", size_reason="x"
        )
        assert claude_cut(6, h2.max_contracts, h2.backend) == 6


async def test_ccs_and_rolls_are_never_cut(h) -> None:
    cc = _cc("cc-1", contracts=4)
    roll = _csp("roll-1", contracts=4, roll=True)
    await h.queue([cc, roll], [_review("cc-1", 0), _review("roll-1", 0)])
    assert sorted(o.snapshot["contracts"] for o in h.orders()) == [4, 4]
    assert h.actions() == []


async def test_a_candidate_with_no_review_is_untouched(h) -> None:
    await h.queue([_csp("c1", contracts=5)], [])
    assert [o.snapshot["contracts"] for o in h.orders()] == [5]
    await h.queue([_csp("c2", contracts=5, strike=61.0)], [_review("someone-else", 0)])
    assert [o.snapshot["contracts"] for o in h.orders()] == [5, 5]


async def test_an_existing_order_is_not_cut_or_recorded_again(h) -> None:
    cand = _csp("c1", contracts=10)
    await h.queue([cand], [_review("c1", 3)])
    await h.queue([cand], [_review("c1", 1)])  # a later cycle's different number
    assert len(h.orders()) == 1 and h.orders()[0].snapshot["contracts"] == 3
    (row,) = h.actions("claude_cut")
    assert row.sent_contracts == 3  # the order that went out is what was recorded


async def test_a_cut_is_recorded_once_per_day_however_often_it_is_seen(h) -> None:
    cand = _csp("c1", contracts=3)
    for _ in range(3):
        await h.queue([cand], [_review("c1", 0)])
    assert len(h.actions("claude_cut")) == 1


async def test_breaker_ignores_further_cuts_and_alerts_once(h) -> None:
    h.seed_zero_cuts(4)  # four auto CSPs already cut to zero today...
    h.seed_reviewed(6)  # ...of six that Claude reviewed: 67%
    seventh = _csp("c7", contracts=5)
    await h.queue([seventh], [_review("c7", 0)])
    (order,) = h.orders()
    assert order.snapshot["contracts"] == 5  # the breaker: the system's size goes out
    (row,) = h.actions("claude_cut_unapplied")
    assert row.reason.startswith("breaker") and row.sent_contracts == 5
    alerts = [
        t
        for t in h.texts()
        if "further cuts today are recorded but not applied" in t.replace("\\", "")
    ]
    assert len(alerts) == 1
    assert "4 of today" in alerts[0].replace("\\", "") and "58" == str(
        h.messages[-1]["message_thread_id"]
    )

    eighth = _csp("c8", contracts=5, strike=64.0)
    await h.queue([eighth], [_review("c8", 1)])
    assert [o.snapshot["contracts"] for o in h.orders()] == [5, 5]
    assert len(h.actions("claude_cut_unapplied")) == 2
    alerts = [
        t
        for t in h.texts()
        if "further cuts today are recorded but not applied" in t.replace("\\", "")
    ]
    assert len(alerts) == 1  # no second alert the same day


async def test_a_zero_cut_already_counted_is_not_blocked_by_itself(h) -> None:
    """The fourth zeroed candidate is evaluated again on the next cycle: its own earlier row must
    not count against it, or the breaker would flip a cut it had allowed into a sent order."""
    h.seed_zero_cuts(3)
    h.seed_reviewed(6)
    cand = _csp("c4", contracts=3)
    await h.queue([cand], [_review("c4", 0)])  # the fourth: 3 others zeroed, so it applies
    assert h.orders() == [] and len(h.actions("claude_cut")) == 4
    await h.queue([cand], [_review("c4", 0)])  # next cycle: 3 OTHERS zeroed, still applies
    assert h.orders() == [] and h.actions("claude_cut_unapplied") == []


async def test_only_claude_reviews_count_toward_the_breakers_denominator(h) -> None:
    cands = [_csp(f"c{i}", contracts=4, strike=60.0 + i) for i in range(3)]
    await h.queue(
        cands,
        [
            _review("c0", 4, backend="ollama"),
            _review("c1", 4),
            _review("c2", 4),
        ],
    )
    from src.storage.system_settings import get_setting

    state = json.loads(get_setting("claude_cut_state"))
    assert state["day"] == today_et().isoformat()
    assert sorted(state["reviewed"]) == ["c1", "c2"]  # the Ollama review is not Claude's


async def test_auto_summary_lists_each_applied_cut(h) -> None:
    cands = [
        _csp("c1", "TQQQ", contracts=10, strike=65.0),
        _csp("c2", "SOXL", contracts=3, strike=100.0),
        _csp("c3", "NVDA", contracts=2, strike=120.0),
    ]
    await h.queue(
        cands,
        [
            _review("c1", 3, reason="CPI print inside the window (N1)"),
            _review("c2", 0, reason="thesis-breaking story (N5)"),
            _review("c3", 2),
        ],
    )
    (text,) = h.texts()
    assert _md("Claude cut TQQQ 65P 10 → 3: CPI print inside the window (N1)") in text
    assert _md("Claude: not sending SOXL 100P (3 lots): thesis-breaking story (N5)") in text
    assert "NVDA" in text and "Claude cut NVDA" not in text  # the kept one has no cut line


# --------------------------------------------------------------------------- #
# The manual / OBSERVE card, and the entry point
# --------------------------------------------------------------------------- #


def test_manual_card_shows_claudes_suggestion_and_keeps_the_size() -> None:
    cand = _csp("c1", contracts=3)
    text = format_candidate(cand, _review("c1", 1, reason="earnings inside the window (F3)"))
    assert _md("Claude suggests 1 of 3: earnings inside the window (F3)") in text
    # The local model's number, a number above the card, a missing one, and a covered call show
    # no suggestion line.
    for review in (_review("c1", 1, backend="ollama"), _review("c1", 9), _review("c1", None)):
        assert "Claude suggests" not in format_candidate(cand, review)
    assert "Claude suggests" not in format_candidate(_cc("cc-1", 4), _review("cc-1", 1))


async def test_a_manual_card_is_approved_at_the_full_size(db, monkeypatch) -> None:
    """In MANUAL the human sees Claude's suggestion and approval still sends the card's size:
    nothing is cut, nothing is recorded, the frozen snapshot is the deterministic one."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.storage.models import ApprovalRow
    from src.storage.system_settings import set_autonomy_level
    from tests.test_notify import _cc_kwargs, _mock_cfg

    _mock_cfg(monkeypatch)
    set_autonomy_level(AutonomyLevel.MANUAL)
    instance = AsyncMock()
    instance.send_message.return_value = MagicMock(message_id=7)
    bot_cls = MagicMock()
    bot_cls.return_value.__aenter__ = AsyncMock(return_value=instance)
    bot_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    with patch("src.notify.sender.Bot", bot_cls):
        await sender.send_candidates([_csp("c1", contracts=3)], [_review("c1", 1)], **_cc_kwargs())
    with db() as s:
        approval = s.query(ApprovalRow).filter_by(candidate_id="c1").one()
        assert approval.snapshot["contracts"] == 3
        assert s.query(SizingActionRow).count() == 0
    assert "Claude suggests 1 of 3" in instance.send_message.call_args.kwargs["text"].replace(
        "\\", ""
    )


async def test_send_candidates_hands_the_reviews_to_the_auto_branch(db, monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.storage.system_settings import set_autonomy_level
    from tests.test_notify import _cc_kwargs, _mock_cfg

    _mock_cfg(monkeypatch)
    set_autonomy_level(AutonomyLevel.FULL)
    instance = AsyncMock()
    instance.send_message.return_value = MagicMock(message_id=7)
    bot_cls = MagicMock()
    bot_cls.return_value.__aenter__ = AsyncMock(return_value=instance)
    bot_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    with patch("src.notify.sender.Bot", bot_cls):
        await sender.send_candidates([_csp("c1", contracts=10)], [_review("c1", 3)], **_cc_kwargs())
    with db() as s:
        order = s.query(OrderRow).filter_by(candidate_id="c1").one()
        assert order.snapshot["contracts"] == 3
        assert s.query(SizingActionRow).filter_by(kind="claude_cut").count() == 1


# --------------------------------------------------------------------------- #
# The review fingerprint
# --------------------------------------------------------------------------- #


def test_fingerprint_changes_with_regime_or_picture() -> None:
    from src.orchestrator.scan import _candidates_review_hash, _review_fingerprint

    note = SizingNote(
        pre_regime_contracts=10,
        regime=MarketRegime.STRESSED,
        regime_index="QQQ",
        per_trade_cap=3,
        budget_multiplier=0.4,
    )
    base = _csp("c1", contracts=3, note=note)
    fp = _review_fingerprint(base, 15.0, regime="stressed", picture_version="v1")
    assert fp != _review_fingerprint(base, 15.0, regime="cautious", picture_version="v1")
    assert fp != _review_fingerprint(base, 15.0, regime="stressed", picture_version="v2")
    assert fp != _review_fingerprint(base, 15.0, regime="stressed", picture_version=None)
    # The deterministic size and its ceiling are part of what a review was based on.
    assert fp != _review_fingerprint(
        base.model_copy(update={"contracts": 2}), 15.0, regime="stressed", picture_version="v1"
    )
    lower_cap = base.model_copy(update={"sizing": note.model_copy(update={"per_trade_cap": 2})})
    assert fp != _review_fingerprint(lower_cap, 15.0, regime="stressed", picture_version="v1")

    # The hash reads the regime off each candidate's own note, and the picture off the call.
    same = _candidates_review_hash([base], 15.0, picture_version="v1")
    assert same == _candidates_review_hash([base], 15.0, picture_version="v1")
    assert same != _candidates_review_hash([base], 15.0, picture_version="v2")
    calmer = base.model_copy(
        update={"sizing": note.model_copy(update={"regime": MarketRegime.NORMAL})}
    )
    assert same != _candidates_review_hash([calmer], 15.0, picture_version="v1")
    # A candidate built with no context still hashes (no regime, no cap).
    assert _candidates_review_hash([_csp("c9")], 15.0)
