"""Task 12: the trade reviewer reads the market picture and the book, prior recommendations are
gone, and a review carries Claude's optional size fields (`max_contracts`, `size_reason`) and the
backend that produced it. The cut itself (Task 14) is clamped elsewhere; here the field must only
survive parsing as a plain integer or as None, and must never cost the review."""

from __future__ import annotations

import inspect
import json
import subprocess
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.claude.ollama_runner as ollama_mod
from src.claude import runner
from src.claude.parser import parse_claude_output, parse_ollama_review_output
from src.claude.prompts import strategist
from src.claude.prompts.strategist import build_prompt
from src.common.schemas import (
    ClaudeReview,
    MarketPicture,
    MarketRegime,
    OptionRight,
    PictureFact,
    PictureRegime,
    PictureStory,
    PositionSnapshot,
    ScaleInZone,
    SizingNote,
    Strategy,
)
from tests.test_claude import _make_account, _make_candidate, _make_valid_envelope, _review_dict

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)


def _csp(
    cid: str = "csp-1",
    underlying: str = "QQQ",
    contracts: int = 3,
    note: SizingNote | None = None,
):
    cand = _make_candidate(
        cid,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying=underlying,
        strike=60.0,
        right=OptionRight.PUT,
    )
    return cand.model_copy(update={"contracts": contracts, "sizing": note})


def _note(**kw) -> SizingNote:
    base: dict = dict(
        pre_regime_contracts=10,
        regime=MarketRegime.STRESSED,
        regime_index="QQQ",
        per_trade_cap=3,
        budget_multiplier=0.4,
    )
    base.update(kw)
    return SizingNote(**base)


def _picture(**kw) -> MarketPicture:
    base: dict = dict(
        version=NOW.isoformat(),
        built_at=NOW,
        regimes=[
            PictureRegime(
                index="SPY",
                effective=MarketRegime.NORMAL,
                base=MarketRegime.NORMAL,
                as_of=NOW,
            ),
            PictureRegime(
                index="QQQ",
                effective=MarketRegime.STRESSED,
                base=MarketRegime.STRESSED,
                as_of=NOW,
            ),
        ],
        facts=[PictureFact(label="VIX", value="23.4")],
        stories=[
            PictureStory(
                id=3,
                title="Tariff escalation",
                started_on=date(2026, 10, 12),
                description="Tariff headlines keep the index under its 50-day average.",
                evidence=["C41"],
            )
        ],
    )
    base.update(kw)
    return MarketPicture(**base)


def _save(picture: MarketPicture, *, stale: bool = False) -> None:
    from src.news.store.models import MarketPictureRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(picture.built_at),
                version=picture.version,
                payload=picture.model_dump(mode="json"),
                stale=stale,
            )
        )


# --------------------------------------------------------------------------- #
# The prompt
# --------------------------------------------------------------------------- #


def test_prompt_has_picture_and_book_and_no_prior_recommendations() -> None:
    prompt = build_prompt(
        [_csp()],
        _make_account(),
        picture_block="=== MARKET PICTURE ===\nQQQ: stressed\nS3 Tariff escalation (since Oct 12)",
        book_block="=== YOUR BOOK ===\nTQQQ: short 10 78P",
    )
    assert "=== MARKET PICTURE ===" in prompt and "S3 Tariff escalation" in prompt
    assert "=== YOUR BOOK ===" in prompt and "TQQQ: short 10 78P" in prompt
    # The picture sits with the other market context, the book just above the candidates.
    assert prompt.index("=== MARKET PICTURE ===") < prompt.index("=== PORTFOLIO SUMMARY ===")
    assert prompt.index("=== YOUR BOOK ===") < prompt.index("=== TRADE CANDIDATES ===")
    assert "PRIOR RECOMMENDATIONS" not in prompt
    # The old block is gone for good: no `history` parameter anywhere on the review path.
    assert "history" not in inspect.signature(build_prompt).parameters
    assert not hasattr(strategist, "_format_history")
    assert "history" not in inspect.signature(runner.review_candidates).parameters
    assert "history" not in inspect.signature(ollama_mod.review_candidates).parameters


def test_a_prompt_without_the_blocks_has_neither_header() -> None:
    prompt = build_prompt([_csp()], _make_account())
    assert "=== MARKET PICTURE ===" not in prompt and "=== YOUR BOOK ===" not in prompt


def test_ticker_scan_prompt_has_the_picture() -> None:
    prompt = build_prompt(
        [_csp()],
        _make_account(),
        single_ticker=True,
        picture_block="=== MARKET PICTURE ===\nQQQ: stressed",
        book_block="=== YOUR BOOK ===\nnothing open",
    )
    assert "=== MARKET PICTURE ===" in prompt and "=== YOUR BOOK ===" in prompt


def test_prompt_states_the_size_and_the_cut_rule() -> None:
    zone = ScaleInZone(
        anchor=66.0,
        anchor_source="order_snapshot",
        zone_low=57.0,
        zone_high=59.5,
        support=58.2,
        min_gap_pct=10.0,
        triggers=["near_money_put"],
    )
    cand = _csp(note=_note(scale_in=zone))
    cc = _make_candidate("cc-1")  # a covered call: no regime note
    prompt = build_prompt([cand, cc], _make_account())
    assert (
        "Size:             3 contracts (deterministic, after market-regime limits; "
        "regime stressed on QQQ)" in prompt
    )
    assert "Size:             1 contracts (deterministic)" in prompt
    assert "Next lot zone" in prompt and "$57.00" in prompt and "$59.50" in prompt
    # The cut rule: an integer from 0 up to the size, never above it, not for the regime itself.
    assert '"max_contracts"' in prompt and '"size_reason"' in prompt
    assert "from 0 to" in prompt
    assert "already price the regime" in prompt
    assert "Return the Size to keep it" in prompt
    # It cannot raise a size or touch anything else: the role text says so.
    assert "never raise" in prompt
    assert "cannot place, size, or block orders" not in prompt


def test_the_deep_dive_does_not_ask_for_a_cut() -> None:
    """Nothing consumes a cut from /scan TICKER, so the deep-dive prompt does not ask for one."""
    prompt = build_prompt([_csp(note=_note())], _make_account(), single_ticker=True)
    assert '"max_contracts"' not in prompt and "cannot place, size, or block orders" in prompt


# --------------------------------------------------------------------------- #
# ClaudeReview: the new fields and the parser
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [True, False, 3.5, 3.0, "three", "3", None, [3], {"n": 3}])
def test_malformed_max_contracts_keeps_the_review_and_is_none(bad) -> None:
    item = {**_review_dict(), "max_contracts": bad, "size_reason": "x"}
    reviews = parse_claude_output(_make_valid_envelope([item]))
    assert len(reviews) == 1  # the review survives
    assert reviews[0].max_contracts is None
    assert reviews[0].recommendation == "sell"


@pytest.mark.parametrize("ok", [0, 1, 3, 99, -2])
def test_an_integer_max_contracts_is_kept_as_is_for_the_clamp_to_judge(ok) -> None:
    item = {**_review_dict(), "max_contracts": ok, "size_reason": "FOMC inside the window (N2)"}
    (review,) = parse_claude_output(_make_valid_envelope([item]))
    assert review.max_contracts == ok
    assert review.size_reason == "FOMC inside the window (N2)"


def test_a_non_text_size_reason_does_not_cost_the_review() -> None:
    item = {**_review_dict(), "size_reason": ["a", "list"]}
    (review,) = parse_claude_output(_make_valid_envelope([item]))
    assert review.size_reason == ""


def test_the_new_fields_default_to_nothing() -> None:
    review = ClaudeReview.model_validate(_review_dict())
    assert (review.max_contracts, review.size_reason, review.backend) == (None, "", None)


def test_backend_in_the_model_output_is_ignored() -> None:
    """The backend is the runner's word, never the model's: a model that claims "cli" gets None
    from the parser, and the Ollama runner overwrites it with "ollama"."""
    forged = {**_review_dict(), "backend": "cli", "max_contracts": 1}
    (from_cli,) = parse_claude_output(_make_valid_envelope([forged]))
    assert from_cli.backend is None
    (from_ollama,) = parse_ollama_review_output(json.dumps({"reviews": [forged]}))
    assert from_ollama.backend is None

    cfg = MagicMock(
        enabled=True,
        backend="ollama",
        tool_research_enabled=False,
        ollama_timeout_seconds=60.0,
        tool_research_timeout_seconds=60.0,
        review_min_call_seconds=10.0,
    )
    with (
        patch.object(ollama_mod, "get_config") as get_cfg,
        patch.object(ollama_mod, "_generate", return_value=json.dumps({"reviews": [forged]})),
    ):
        get_cfg.return_value.claude = cfg
        (review,) = ollama_mod.review_candidates([_make_candidate("test-001")], _make_account())
    assert review.backend == "ollama"


def test_review_schema_accepts_the_new_fields() -> None:
    props = ollama_mod._REVIEW_ITEM["properties"]
    assert props["max_contracts"] == {"type": "integer"}
    assert props["size_reason"] == {"type": "string"}
    # Optional: a covered-call review leaves them out.
    assert "max_contracts" not in ollama_mod._REVIEW_ITEM["required"]
    assert "size_reason" not in ollama_mod._REVIEW_ITEM["required"]
    # And the model's own backend claim is not a schema property it can fill in.
    assert "backend" not in props


# --------------------------------------------------------------------------- #
# The runners stamp the backend
# --------------------------------------------------------------------------- #


def _cli_cfg(backend: str = "cli"):
    return SimpleNamespace(
        backend=backend,
        enabled=True,
        max_retries=0,
        timeout_seconds=5.0,
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="",
        effort="",
        disallowed_tools="",
        slim_context=False,
        workdir="",
        model_for=lambda kind: "",
        review_reuse_minutes=0,
    )


def _proc(rc: int, out: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, stdout=out, stderr="")


def test_runner_stamps_the_backend() -> None:
    envelope = _make_valid_envelope([{**_review_dict("test-001"), "max_contracts": 1}])
    with (
        patch.object(runner, "get_config") as cfg,
        patch.object(runner.subprocess, "run", return_value=_proc(0, envelope)),
    ):
        cfg.return_value.claude = _cli_cfg()
        (review,) = runner.review_candidates([_make_candidate("test-001")], _make_account())
    assert review.backend == "cli"

    # The Ollama fallback after a CLI failure is stamped "ollama", not "cli".
    ollama_json = json.dumps({"reviews": [{**_review_dict("test-001"), "max_contracts": 1}]})
    with (
        patch.object(runner, "get_config") as cfg,
        patch.object(ollama_mod, "get_config") as ocfg,
        patch.object(runner.subprocess, "run", return_value=_proc(1, "")),
        patch.object(ollama_mod, "_generate", return_value=ollama_json),
    ):
        cfg.return_value.claude = _cli_cfg("cli_then_ollama")
        ocfg.return_value.claude = MagicMock(
            enabled=True,
            tool_research_enabled=False,
            ollama_timeout_seconds=60.0,
            tool_research_timeout_seconds=60.0,
            review_min_call_seconds=10.0,
        )
        (review,) = runner.review_candidates([_make_candidate("test-001")], _make_account())
    assert review.backend == "ollama"


def test_the_runners_pass_the_picture_and_book_blocks_into_the_prompt() -> None:
    seen: dict = {}

    def _fake_build(*args, **kwargs):
        seen.update(kwargs)
        return "p"

    with (
        patch.object(runner, "get_config") as cfg,
        patch.object(runner, "build_prompt", side_effect=_fake_build),
        patch.object(runner.subprocess, "run", return_value=_proc(1, "")),
    ):
        cfg.return_value.claude = _cli_cfg()
        runner.review_candidates(
            [_make_candidate("test-001")],
            _make_account(),
            picture_block="PIC",
            book_block="BOOK",
        )
    assert seen["picture_block"] == "PIC" and seen["book_block"] == "BOOK"
    assert "history" not in seen


# --------------------------------------------------------------------------- #
# The picture block (news.db, read-only)
# --------------------------------------------------------------------------- #


def test_load_picture_block_renders_the_stored_picture(news_db) -> None:
    from src.claude.picture_context import load_picture_block

    _save(_picture())
    block = load_picture_block(NOW)
    assert block.startswith("=== MARKET PICTURE ===")
    assert "QQQ: stressed" in block and "VIX: 23.4" in block
    assert "S3 Tariff escalation (since Oct 12)" in block
    assert "STALE" not in block


def test_a_stale_picture_says_so(news_db) -> None:
    from src.claude.picture_context import load_picture_block

    _save(_picture(), stale=True)
    assert "PICTURE IS STALE" in load_picture_block(NOW)


def test_no_news_db_reads_as_unavailable_not_as_an_error() -> None:
    from src.claude.picture_context import load_picture, load_picture_block

    assert load_picture() is None  # the autouse fixture points news.db at a file that is not there
    assert load_picture_block(NOW) == "=== MARKET PICTURE ===\n(unavailable)"


def test_a_reader_that_blows_up_never_raises(monkeypatch) -> None:
    import src.claude.picture_context as pc

    def _boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(pc, "read_only_session", _boom)
    assert pc.load_picture() is None
    assert pc.load_picture_block(NOW).endswith("(unavailable)")


def test_the_picture_key_tracks_the_version_and_staleness(news_db) -> None:
    from src.claude.picture_context import load_picture, picture_key

    assert picture_key(None) is None
    _save(_picture())
    fresh = load_picture()
    assert fresh is not None
    assert picture_key(fresh) == NOW.isoformat()
    assert picture_key(fresh.model_copy(update={"stale": True})) != picture_key(fresh)


# --------------------------------------------------------------------------- #
# The book
# --------------------------------------------------------------------------- #


def _opt(
    underlying: str,
    right: OptionRight,
    strike: float,
    qty: float,
    expiry: date = date(2026, 10, 16),
    delta: float | None = None,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{underlying} {strike}{right.value}",
        sec_type="OPT",
        position=qty,
        avg_cost=1.0,
        right=right,
        strike=strike,
        expiry=expiry,
        underlying=underlying,
        delta=delta,
    )


def _stock(symbol: str, qty: float, cost: float) -> PositionSnapshot:
    return PositionSnapshot(symbol=symbol, sec_type="STK", position=qty, avg_cost=cost)


def test_book_lists_related_names_and_stopouts(monkeypatch) -> None:
    from src.claude.book_context import render_book
    from src.common.config import get_config

    monkeypatch.setattr(
        get_config(),
        "universe",
        {"sectors": {"TQQQ": "index", "UPRO": "index", "QQQ": "index", "BAC": "financials"}},
    )
    positions = [
        _opt("TQQQ", OptionRight.PUT, 78.0, -10, delta=-0.45),  # reviewed name, in the money
        _opt("TQQQ", OptionRight.PUT, 60.0, -3, date(2026, 11, 20), delta=-0.1),
        _opt("UPRO", OptionRight.PUT, 90.0, -2, delta=-0.2),  # same sector tag: related
        _stock("SOXL", 300, 21.4),  # tech-linked and TQQQ is tech-linked: related
        _stock("BAC", 1000, 41.0),  # unrelated
        _opt("BAC", OptionRight.CALL, 45.0, -10),  # unrelated
    ]
    text = render_book(
        [_csp("c1", "TQQQ")],
        positions,
        stopouts={"TQQQ": ["Oct 15: 78P Oct 16 x10 stopped out (sold $1.20, bought back $3.10)"]},
        tech_linked=["TQQQ", "SOXL", "QQQ"],
        net_delta=-1234.0,
        spots={"TQQQ": 76.1},
    )
    assert text.startswith("=== YOUR BOOK ===")
    assert "TQQQ" in text and "78P" in text and "ITM" in text  # 76.10 spot < 78 strike
    assert "60P" in text and "OTM" in text
    assert "UPRO" in text  # related by sector tag
    assert "SOXL" in text and "300 shares" in text and "$21.40" in text  # related: both tech-linked
    assert "stopped out" in text and "Oct 15" in text
    assert "BAC" not in text  # neither reviewed nor related
    assert "-1,234" in text  # the book's net delta


def test_book_with_nothing_to_show_says_so() -> None:
    from src.claude.book_context import render_book

    text = render_book([_csp("c1", "TQQQ")], [], stopouts={}, tech_linked=["TQQQ"], net_delta=None)
    assert text.startswith("=== YOUR BOOK ===")
    assert "no open positions" in text.lower()


def test_book_is_bounded() -> None:
    from src.claude.book_context import render_book

    positions = [_opt("TQQQ", OptionRight.PUT, 40.0 + i, -1) for i in range(80)]
    text = render_book(
        [_csp("c1", "TQQQ")], positions, stopouts={}, tech_linked=["TQQQ"], net_delta=None
    )
    assert len(text.splitlines()) <= 45 and "more" in text


def test_stopouts_come_from_loss_exit_fills(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.claude.book_context import load_stopouts
    from src.common.config import Config
    from src.storage.db import init_db, session_scope
    from src.storage.models import FillRow, OrderRow

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    init_db()
    today = date(2026, 10, 22)
    snap = {
        "underlying": "TQQQ",
        "strategy": "cash_secured_put",
        "right": "P",
        "strike": 78.0,
        "expiry": "2026-10-23",
        "premium": 1.2,
    }
    with session_scope() as s:
        s.add(OrderRow(candidate_id="open-1", state="filled", snapshot=snap, filled_qty=10))
        s.add(
            FillRow(
                order_id=2,
                candidate_id="open-1",
                action="BUY",
                filled_qty=10,
                avg_price=3.1,
                close_reason="loss_exit",
                filled_at=datetime(2026, 10, 21, 18, 0),
            )
        )
        # An old stop-out and a profit take are not shown.
        s.add(
            FillRow(
                order_id=3,
                candidate_id="open-1",
                action="BUY",
                filled_qty=1,
                avg_price=0.2,
                close_reason="profit_take",
                filled_at=datetime(2026, 10, 21, 18, 5),
            )
        )
        s.add(
            FillRow(
                order_id=4,
                candidate_id="open-1",
                action="BUY",
                filled_qty=1,
                avg_price=3.0,
                close_reason="loss_exit",
                filled_at=datetime(2026, 10, 1, 18, 0),
            )
        )
    out = load_stopouts(days=5, today=today)
    assert list(out) == ["TQQQ"] and len(out["TQQQ"]) == 1
    assert "Oct 21" in out["TQQQ"][0] and "78P" in out["TQQQ"][0] and "x10" in out["TQQQ"][0]


# --------------------------------------------------------------------------- #
# The scans hand both blocks to the reviewer (and no history)
# --------------------------------------------------------------------------- #


async def test_full_scan_passes_the_picture_and_the_book(tmp_path, monkeypatch, news_db) -> None:
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config
    from tests.test_scan_review_executor import _db_setup, _stub_scan

    _db_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        get_config(),
        "universe",
        {"would_own": ["AAPL"], "actively_wheeling": ["AAPL"], "sectors": {"AAPL": "tech"}},
    )
    _save(_picture(built_at=datetime.now(UTC), version=datetime.now(UTC).isoformat()))
    seen: dict = {}

    def _capture(*args, **kwargs):
        seen.update(kwargs)
        return []

    _stub_scan(scanmod, monkeypatch, review_side_effect=_capture)
    monkeypatch.setattr(
        scanmod,
        "get_positions",
        lambda ib: [_opt("AAPL", OptionRight.PUT, 150.0, -2, delta=-0.2)],
    )
    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")

    assert "=== MARKET PICTURE ===" in seen["picture_block"]
    assert "Tariff escalation" in seen["picture_block"]
    assert "=== YOUR BOOK ===" in seen["book_block"] and "AAPL" in seen["book_block"]
    assert "history" not in seen


async def test_ticker_scan_passes_the_picture_and_the_book(tmp_path, monkeypatch, news_db) -> None:
    import src.orchestrator.scan as scanmod
    from src.common.schemas import FundamentalStats, IVStats, TechnicalStats
    from tests.test_scan_review_executor import _account, _db_setup

    _db_setup(tmp_path, monkeypatch)
    _save(_picture(built_at=datetime.now(UTC), version=datetime.now(UTC).isoformat()))
    cand = _csp("t-1", "AAPL", contracts=1)
    priced = SimpleNamespace(
        quotes=[],
        iv_stats=IVStats(symbol="AAPL"),
        tech_stats=TechnicalStats(symbol="AAPL", price=200.0),
        fund_stats=FundamentalStats(symbol="AAPL"),
        positions=[_opt("AAPL", OptionRight.PUT, 150.0, -2)],
        account=_account(),
        stock_pos=None,
        is_held=False,
        csp_skip_reason=None,
        cc_passed=[],
        csp_passed=[cand],
        ticker_assessed=[],
    )
    monkeypatch.setattr(scanmod, "_price_and_gate_ticker", AsyncMock(return_value=priced))
    monkeypatch.setattr(
        "src.ibkr.contracts.qualify_stock_async", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])
    monkeypatch.setattr(scanmod, "get_sector_context", lambda symbol: None)
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: None)
    seen: dict = {}

    def _capture(*args, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(scanmod, "review_candidates", _capture)
    await scanmod.run_ticker_scan(
        MagicMock(), "AAPL", bot=AsyncMock(), chat_id="1", progress_msg_id=1
    )
    assert "Tariff escalation" in seen["picture_block"]
    assert "=== YOUR BOOK ===" in seen["book_block"] and "AAPL" in seen["book_block"]
    assert seen["single_ticker"] is True and "history" not in seen
