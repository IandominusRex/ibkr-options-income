"""Tests for the local-LLM (Ollama) backend: parser functions, ollama_runner, and the
`claude.backend` dispatcher in runner.py.

All tests mock httpx.post / subprocess.run — no live Ollama server or Claude CLI needed.
"""

from __future__ import annotations

import json
import json as json_mod
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

import src.claude.ollama_runner as ollama_mod
from src.claude.parser import (
    parse_ollama_journal_output,
    parse_ollama_review_output,
    parse_ollama_roll_output,
)
from src.claude.runner import review_candidates, review_roll, write_journal_narrative
from src.common.schemas import (
    AccountSnapshot,
    EODSummary,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    ScoreCard,
    Strategy,
    TradeCandidate,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=70_000.0,
    )


def _make_candidate() -> TradeCandidate:
    scores = ScoreCard(
        symbol="AAPL",
        iv_score=72.0,
        technical_score=65.0,
        fundamental_score=80.0,
        liquidity_score=90.0,
        assignment_safety_score=70.0,
    )
    return TradeCandidate(
        candidate_id="test-001",
        strategy=Strategy.COVERED_CALL,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date(2026, 7, 17),
        contracts=1,
        premium=1.50,
        collateral=18_000.0,
        roc_pct=0.83,
        annualized_yield_pct=18.5,
        breakeven=183.50,
        prob_otm=0.72,
        delta=0.28,
        iv_rank=65.0,
        dte=48,
        scores=scores,
        blended_score=74.5,
        rationale_tags=["high_iv_rank", "liquid"],
    )


def _review_dict(candidate_id: str = "test-001") -> dict:
    return {
        "candidate_id": candidate_id,
        "priority": 1,
        "recommendation": "sell",
        "why_attractive": "High IV rank provides above-average premium income.",
        "risks": "Earnings next quarter could cause a gap move against position.",
        "tradeoffs": "Caps upside above strike; delta provides moderate assignment risk.",
        "assignment_considerations": "Low probability given 0.28 delta; stock quality is high.",
        "rolling_considerations": "Could roll up-and-out if stock approaches strike before expiry.",
        "confidence": 0.82,
    }


def _ollama_response(payload: object) -> MagicMock:
    """A mocked httpx.Response for Ollama's /api/generate with format=json."""
    mock = MagicMock()
    mock.json.return_value = {"response": json.dumps(payload)}
    mock.raise_for_status.return_value = None
    return mock


def _completed_process(stdout: str, returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = returncode
    return mock


def _make_valid_cli_envelope(reviews: list[dict]) -> str:
    return json.dumps({"type": "result", "subtype": "success", "result": json.dumps(reviews)})


# --------------------------------------------------------------------------- #
# _generate — schema-constrained structured output (Task 10)
# --------------------------------------------------------------------------- #


def test_generate_sends_json_schema_format(monkeypatch):
    from src.claude import ollama_runner

    sent = {}

    class _R:
        def raise_for_status(self): ...
        def json(self):
            return {"response": '{"reviews": []}'}

    monkeypatch.setattr(
        ollama_runner.httpx, "post", lambda url, json, timeout: sent.update(json) or _R()
    )
    ollama_runner._generate("p", ollama_runner.get_config().claude)
    assert sent["format"]["type"] == "object" and "reviews" in sent["format"]["properties"]


def test_generate_accepts_an_explicit_schema_override(monkeypatch):
    """Roll/EOD callers pass their own format (a plain `"json"` string) instead of the review
    schema default."""
    from src.claude import ollama_runner

    sent = {}

    class _R:
        def raise_for_status(self): ...
        def json(self):
            return {"response": "{}"}

    monkeypatch.setattr(
        ollama_runner.httpx, "post", lambda url, json, timeout: sent.update(json) or _R()
    )
    ollama_runner._generate("p", ollama_runner.get_config().claude, schema="json")
    assert sent["format"] == "json"


# --------------------------------------------------------------------------- #
# parse_ollama_review_output
# --------------------------------------------------------------------------- #


def test_parse_ollama_review_output_valid_list():
    raw = json.dumps([_review_dict()])
    reviews = parse_ollama_review_output(raw)
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    assert reviews[0].recommendation == "sell"


def test_parse_ollama_review_output_single_dict_wrapped():
    raw = json.dumps(_review_dict())
    reviews = parse_ollama_review_output(raw)
    assert len(reviews) == 1


def test_parse_ollama_review_output_fenced():
    raw = "```json\n" + json.dumps([_review_dict()]) + "\n```"
    reviews = parse_ollama_review_output(raw)
    assert len(reviews) == 1


def test_parse_ollama_review_output_empty():
    assert parse_ollama_review_output("") == []


def test_parse_ollama_review_output_invalid_schema():
    raw = json.dumps([{"foo": "bar"}])
    assert parse_ollama_review_output(raw) == []


def test_parse_ollama_review_output_not_json():
    assert parse_ollama_review_output("not json at all {{{") == []


# --------------------------------------------------------------------------- #
# parse_ollama_roll_output / parse_ollama_journal_output
# --------------------------------------------------------------------------- #


def test_parse_ollama_roll_output_valid():
    raw = json.dumps(
        {
            "position_symbol": "AAPL 250718C00190000",
            "recommendation": "roll",
            "roll_target": "roll to $195 Aug 15 CC at 0.30 delta, $1.85 credit",
            "rationale": "Stock approaching strike with 10 DTE remaining.",
            "risks": "Further upside could require another roll.",
            "confidence": 0.7,
        }
    )
    review = parse_ollama_roll_output(raw)
    assert review is not None
    assert review.recommendation == "roll"


def test_parse_ollama_roll_output_empty():
    assert parse_ollama_roll_output("") is None


def test_parse_ollama_journal_output_valid():
    raw = json.dumps({"narrative": "A quiet day with one CSP expiring worthless."})
    assert parse_ollama_journal_output(raw) == "A quiet day with one CSP expiring worthless."


def test_parse_ollama_journal_output_missing_field():
    raw = json.dumps({"foo": "bar"})
    assert parse_ollama_journal_output(raw) is None


# --------------------------------------------------------------------------- #
# ollama_runner — review_candidates / review_roll / write_journal_narrative
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    """Reset the module-level circuit breaker before every test so failures don't leak."""
    ollama_mod._consecutive_failures = 0
    ollama_mod._circuit_open = False
    yield
    ollama_mod._consecutive_failures = 0
    ollama_mod._circuit_open = False


def _patch_ollama_cfg(**overrides):
    """Patch get_config().claude in both runner.py and ollama_runner.py to the same MagicMock."""
    defaults = dict(
        enabled=True,
        backend="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
        ollama_num_ctx=16384,
        ollama_keep_alive="10m",
        ollama_temperature=0.2,
        # Task 11 — off by default so every pre-existing test here (which mocks only one
        # httpx.post response and doesn't expect a NEWS-block fetch or a research turn) keeps
        # its exact single-shot `_generate` behaviour; a test that wants the new path opts in
        # explicitly via **overrides. `review_candidates` gates on `is True`, not truthiness,
        # so an unset MagicMock attribute (auto-truthy) can never accidentally enable this.
        tool_research_enabled=False,
        max_tool_rounds=2,
        tool_research_timeout_seconds=60.0,
        news_per_symbol=5,
        news_days=7,
        news_max_items=25,
        news_fetch_budget_seconds=30.0,
        review_min_call_seconds=60.0,
    )
    defaults.update(overrides)
    cfg = MagicMock(**defaults)
    runner_patch = patch("src.claude.runner.get_config")
    ollama_patch = patch("src.claude.ollama_runner.get_config")
    return cfg, runner_patch, ollama_patch


def test_ollama_backend_review_candidates_success():
    account = _make_account()
    candidates = [_make_candidate()]

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.post",
        return_value=_ollama_response([_review_dict()]),
    ) as mock_post:
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    url = mock_post.call_args.args[0]
    assert url == "http://localhost:11434/api/generate"
    body = mock_post.call_args.kwargs["json"]
    # Task 10: the review path is schema-constrained (REVIEW_SCHEMA), not the bare "json" mode.
    assert body["format"]["type"] == "object"
    assert "reviews" in body["format"]["properties"]
    assert body["model"] == "qwen2.5:14b-instruct"
    # Tunable generation params must flow from config into the request (num_ctx large enough to
    # avoid silent prompt/output truncation; keep_alive to skip per-call model reloads).
    assert body["keep_alive"] == "10m"
    assert body["options"]["num_ctx"] == 16384
    assert body["options"]["temperature"] == 0.2


def test_ollama_backend_connection_error_returns_empty():
    account = _make_account()
    candidates = [_make_candidate()]

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            reviews = review_candidates(candidates, account)

    assert reviews == []


# --------------------------------------------------------------------------- #
# Task 11 — bounded tool-calling research turn (ollama_tools.research_turn)
# --------------------------------------------------------------------------- #


def test_review_candidates_research_turn_calls_search_news_and_final_chat(monkeypatch):
    """With `tool_research_enabled`, `review_candidates` runs one `/api/chat` turn with
    `search_news` available, executes the model's single tool call, then makes a *separate*
    final `/api/chat` call carrying the accumulated messages, `format=REVIEW_SCHEMA`, and no
    `tools`. search_news must run exactly once and the review must still parse."""
    from src.claude import ollama_runner

    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg(
        tool_research_enabled=True,
        max_tool_rounds=2,
        tool_research_timeout_seconds=60.0,
    )

    # Skip the NEWS-block fetch itself — this test is about the tool-calling round-trip, not
    # news_context (covered by tests/test_news_context.py).
    monkeypatch.setattr(ollama_runner, "news_block_for_candidates", lambda *a, **k: ("", {}))

    search_calls: list[tuple] = []

    def _fake_search(query, *, days=7, limit=10):
        search_calls.append((query, days, limit))
        from src.data.protocols import NewsItem

        return [
            NewsItem(
                id="", title="AAPL guidance raised", source="Reuters", published=None, url=None
            )
        ]

    monkeypatch.setattr(
        "src.claude.ollama_tools.get_news_search_provider",
        lambda: MagicMock(search=_fake_search),
    )

    tool_call_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "search_news",
                    "arguments": {"query": "AAPL guidance", "days": 7},
                }
            }
        ],
    }
    final_content = json.dumps({"reviews": [_review_dict()]})

    requests: list[dict] = []

    def _fake_post(url, json, timeout):  # noqa: A002 - matches httpx.post's kwarg name
        requests.append({"url": url, "json": json, "timeout": timeout})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if len(requests) == 1:
            assert url == "http://localhost:11434/api/chat"
            assert "tools" in json
            resp.json.return_value = {"message": tool_call_message}
        else:
            assert url == "http://localhost:11434/api/chat"
            assert "tools" not in json
            assert json.get("format") is not None
            resp.json.return_value = {"message": {"content": final_content}}
        return resp

    monkeypatch.setattr("src.claude.ollama_tools.httpx.post", _fake_post)
    monkeypatch.setattr("src.claude.ollama_runner.httpx.post", _fake_post)

    with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
        mock_runner_cfg.return_value.claude = cfg
        mock_ollama_cfg.return_value.claude = cfg
        reviews = ollama_runner.review_candidates(candidates, account)

    assert len(search_calls) == 1
    assert search_calls[0][0] == "AAPL guidance"
    assert len(requests) == 2
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"


def test_review_candidates_research_turn_http_error_falls_back_to_single_shot(monkeypatch):
    """A `/api/chat` failure in the research turn (e.g. a model with no tool support, or a
    timeout) must fall back to the Task 10 single-shot `_generate` (`/api/generate`) path and
    still return a review — the research turn is enrichment, never a dependency."""
    from src.claude import ollama_runner

    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg(
        tool_research_enabled=True,
        max_tool_rounds=2,
        tool_research_timeout_seconds=60.0,
    )
    monkeypatch.setattr(ollama_runner, "news_block_for_candidates", lambda *a, **k: ("", {}))

    monkeypatch.setattr(
        "src.claude.ollama_tools.httpx.post",
        MagicMock(side_effect=httpx.ConnectError("no tool support")),
    )
    monkeypatch.setattr(
        "src.claude.ollama_runner.httpx.post",
        MagicMock(return_value=_ollama_response([_review_dict()])),
    )

    with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
        mock_runner_cfg.return_value.claude = cfg
        mock_ollama_cfg.return_value.claude = cfg
        reviews = ollama_runner.review_candidates(candidates, account)

    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"


def test_research_turn_returns_none_when_model_makes_no_tool_calls(monkeypatch):
    """Fix round 1: `research_turn` itself must return `None` — not the accumulated messages —
    when the model's `/api/chat` reply carries no `tool_calls`. Feeding that unconstrained reply
    into a second, `format`-constrained call was wasteful (the reply alone can run to ~1.7-2k
    tokens on a full prompt) and risked Ollama treating the trailing assistant turn as a prefill.
    """
    from src.claude import ollama_tools

    cfg = MagicMock(
        max_tool_rounds=2,
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_keep_alive="10m",
        ollama_temperature=0.2,
        ollama_num_ctx=16384,
        tool_research_timeout_seconds=60.0,
    )
    no_tool_call_message = {"role": "assistant", "content": "No search needed here."}

    def _fake_post(url, json, timeout):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": no_tool_call_message}
        return resp

    monkeypatch.setattr(ollama_tools.httpx, "post", _fake_post)

    assert ollama_tools.research_turn("prompt text with N1 already in it", cfg) is None


def test_review_candidates_falls_back_when_model_makes_no_tool_calls(monkeypatch):
    """End to end: when the model declines to call `search_news`, `review_candidates` must go
    straight to the single-shot `_generate` (`/api/generate`) path — exactly one `/api/chat`
    call (the declined research offer) plus one `/api/generate` call, never a second, wasted
    `/api/chat` call."""
    from src.claude import ollama_runner

    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg(
        tool_research_enabled=True, max_tool_rounds=2, tool_research_timeout_seconds=60.0
    )
    monkeypatch.setattr(ollama_runner, "news_block_for_candidates", lambda *a, **k: ("", {}))

    no_tool_call_message = {"role": "assistant", "content": "No search needed here."}
    chat_calls: list[dict] = []
    generate_calls: list[dict] = []

    def _dispatch(url, json, timeout):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if url.endswith("/api/chat"):
            chat_calls.append(json)
            resp.json.return_value = {"message": no_tool_call_message}
        else:
            generate_calls.append(json)
            resp = _ollama_response([_review_dict()])
        return resp

    monkeypatch.setattr("src.claude.ollama_tools.httpx.post", _dispatch)
    monkeypatch.setattr("src.claude.ollama_runner.httpx.post", _dispatch)

    with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
        mock_runner_cfg.return_value.claude = cfg
        mock_ollama_cfg.return_value.claude = cfg
        reviews = ollama_runner.review_candidates(candidates, account)

    assert len(chat_calls) == 1, "expected exactly one /api/chat call (the declined offer)"
    assert len(generate_calls) == 1, "expected exactly one /api/generate fallback call"
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"


def test_review_candidates_falls_back_when_final_chat_output_is_unparseable(monkeypatch):
    """Fix round 1: when the model DID call `search_news` but the final `format`-constrained
    `/api/chat` call returns content that parses to no reviews (malformed/empty),
    `review_candidates` must retry via the single-shot `_generate` path before recording a
    failure — previously this case had no fallback and the review was simply lost."""
    from src.claude import ollama_runner

    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg(
        tool_research_enabled=True, max_tool_rounds=2, tool_research_timeout_seconds=60.0
    )
    monkeypatch.setattr(ollama_runner, "news_block_for_candidates", lambda *a, **k: ("", {}))
    monkeypatch.setattr(
        "src.claude.ollama_tools.get_news_search_provider",
        lambda: MagicMock(search=lambda *a, **k: []),
    )

    tool_call_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "search_news", "arguments": {"query": "AAPL guidance"}}}
        ],
    }
    chat_call_count = 0
    generate_calls: list[dict] = []

    def _dispatch(url, json, timeout):
        nonlocal chat_call_count
        if url.endswith("/api/chat"):
            chat_call_count += 1
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if chat_call_count == 1:
                resp.json.return_value = {"message": tool_call_message}
            else:
                resp.json.return_value = {"message": {"content": "not valid json"}}
            return resp
        generate_calls.append(json)
        return _ollama_response([_review_dict()])

    monkeypatch.setattr("src.claude.ollama_tools.httpx.post", _dispatch)
    monkeypatch.setattr("src.claude.ollama_runner.httpx.post", _dispatch)

    with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
        mock_runner_cfg.return_value.claude = cfg
        mock_ollama_cfg.return_value.claude = cfg
        reviews = ollama_runner.review_candidates(candidates, account)

    assert chat_call_count == 2  # the tool-offer call + the final structured call
    assert len(generate_calls) == 1  # single-shot fallback after the unparseable chat output
    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"


# --------------------------------------------------------------------------- #
# Final review I2 — ONE deadline for the whole review path
#
# news fetch + research turn + final chat + single-shot fallback share
# D = tool_research_timeout_seconds + ollama_timeout_seconds (60 + 180 = 240s here). The NEWS
# fetch gets the first `news_fetch_budget_seconds` of it; each later call gets only what is
# left. The one exception is the floor (`review_min_call_seconds`, 60s here): the final chat
# is SKIPPED when less than the floor remains, and the single-shot fallback always gets at
# least the floor (capped at ollama_timeout_seconds) — so at most one call runs past D, by at
# most the floor, and the whole review is bounded by D + floor = 300s.
# --------------------------------------------------------------------------- #


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


_TOOL_CALL_MESSAGE = {
    "role": "assistant",
    "content": "",
    "tool_calls": [{"function": {"name": "search_news", "arguments": {"query": "AAPL guidance"}}}],
}


def _run_deadline_review(
    monkeypatch,
    *,
    news_s: float = 0.0,
    research_s: float = 0.0,
    research_calls_tool: bool = True,
    research_fails: bool = False,
    final_chat_ok: bool = True,
    research_enabled: bool = True,
):
    """Drive `review_candidates` on a fake monotonic clock. Returns (calls, news_kwargs) where
    calls is a list of (endpoint, timeout) in order."""
    from src.claude import news_context, ollama_runner, ollama_tools

    clock = _Clock()
    monkeypatch.setattr(ollama_runner.time, "monotonic", clock)
    monkeypatch.setattr(ollama_tools.time, "monotonic", clock)
    monkeypatch.setattr(news_context.time, "monotonic", clock)

    news_kwargs: dict = {}

    def _fake_news(candidates, **kwargs):
        news_kwargs.update(kwargs)
        clock.t += news_s
        return "", {}

    monkeypatch.setattr(ollama_runner, "news_block_for_candidates", _fake_news)
    monkeypatch.setattr(
        "src.claude.ollama_tools.get_news_search_provider",
        lambda: MagicMock(search=lambda *a, **k: []),
    )

    calls: list[tuple[str, float]] = []

    def _dispatch(url, json, timeout):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if url.endswith("/api/chat") and "tools" in json:
            calls.append(("research", timeout))
            clock.t += research_s
            if research_fails:
                raise httpx.ReadTimeout("research timed out")
            msg = _TOOL_CALL_MESSAGE if research_calls_tool else {"role": "assistant"}
            resp.json.return_value = {"message": msg}
            return resp
        if url.endswith("/api/chat"):
            calls.append(("final_chat", timeout))
            content = json_mod.dumps({"reviews": [_review_dict()]}) if final_chat_ok else "bad"
            resp.json.return_value = {"message": {"content": content}}
            return resp
        calls.append(("generate", timeout))
        return _ollama_response([_review_dict()])

    monkeypatch.setattr("src.claude.ollama_tools.httpx.post", _dispatch)
    monkeypatch.setattr("src.claude.ollama_runner.httpx.post", _dispatch)

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg(
        tool_research_enabled=research_enabled,
        tool_research_timeout_seconds=60.0,
        ollama_timeout_seconds=180.0,
    )
    with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
        mock_runner_cfg.return_value.claude = cfg
        mock_ollama_cfg.return_value.claude = cfg
        reviews = ollama_runner.review_candidates([_make_candidate()], _make_account())
    assert len(reviews) == 1
    return calls, news_kwargs


def test_deadline_news_fetch_gets_only_its_share(monkeypatch):
    _calls, news_kwargs = _run_deadline_review(monkeypatch)
    assert news_kwargs["deadline"] == 1000.0 + 30.0  # news_fetch_budget_seconds


def test_deadline_research_turn_timeout_is_capped_by_what_news_left(monkeypatch):
    calls, _ = _run_deadline_review(monkeypatch, news_s=30.0, research_s=60.0)
    # research gets min(60, 240-30); the final chat gets 240 - 30 - 60 = 150.
    assert calls == [("research", 60.0), ("final_chat", 150.0)]


def test_deadline_final_chat_gets_remaining_budget(monkeypatch):
    calls, _ = _run_deadline_review(monkeypatch, research_s=50.0)
    assert calls == [("research", 60.0), ("final_chat", 190.0)]


def test_deadline_final_chat_skipped_below_the_floor_and_fallback_gets_the_floor(monkeypatch):
    # news + research ate 200s of 240: 40s left < 60s floor -> no final chat; fallback = floor.
    calls, _ = _run_deadline_review(monkeypatch, news_s=30.0, research_s=170.0)
    assert calls == [("research", 60.0), ("generate", 60.0)]


def test_deadline_fallback_gets_only_the_remaining_budget(monkeypatch):
    # research turn fails after 150s -> fallback gets 240 - 150 = 90, not a fresh 180.
    calls, _ = _run_deadline_review(monkeypatch, research_s=150.0, research_fails=True)
    assert calls == [("research", 60.0), ("generate", 90.0)]


def test_deadline_fallback_after_a_failed_final_chat_gets_the_remainder(monkeypatch):
    calls, _ = _run_deadline_review(monkeypatch, research_s=50.0, final_chat_ok=False)
    # final chat got 190 and (on the fake clock) took no time; fallback gets what's left,
    # capped at ollama_timeout_seconds.
    assert calls == [("research", 60.0), ("final_chat", 190.0), ("generate", 180.0)]


def test_deadline_fallback_is_capped_at_ollama_timeout(monkeypatch):
    calls, _ = _run_deadline_review(monkeypatch, research_calls_tool=False)
    assert calls == [("research", 60.0), ("generate", 180.0)]


def test_deadline_research_disabled_keeps_single_shot_timeout(monkeypatch):
    calls, news_kwargs = _run_deadline_review(monkeypatch, research_enabled=False)
    assert calls == [("generate", 180.0)]
    assert news_kwargs == {}  # no NEWS fetch at all when research is off


def test_research_turn_skips_searches_once_the_deadline_has_passed(monkeypatch):
    """Tool EXECUTION after the research /api/chat also counts against the deadline: once it
    has passed, remaining search_news calls are not run."""
    from src.claude import ollama_tools

    clock = _Clock()
    monkeypatch.setattr(ollama_tools.time, "monotonic", clock)
    searches: list[str] = []

    def _search(query, *, days=7, limit=10):
        searches.append(query)
        clock.t += 20.0
        return []

    monkeypatch.setattr(ollama_tools, "get_news_search_provider", lambda: MagicMock(search=_search))
    two_calls = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "search_news", "arguments": {"query": "Q1"}}},
            {"function": {"name": "search_news", "arguments": {"query": "Q2"}}},
        ],
    }
    seen_timeouts: list[float] = []

    def _post(url, json, timeout):
        seen_timeouts.append(timeout)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": two_calls}
        return resp

    monkeypatch.setattr(ollama_tools.httpx, "post", _post)
    cfg = MagicMock(
        max_tool_rounds=2,
        ollama_host="http://localhost:11434",
        ollama_model="m",
        ollama_keep_alive="2m",
        ollama_temperature=0.2,
        ollama_num_ctx=16384,
        tool_research_timeout_seconds=60.0,
        news_days=7,
    )
    messages = ollama_tools.research_turn("prompt", cfg, deadline=clock.t + 15.0)
    assert seen_timeouts == [15.0]  # min(60, remaining 15)
    assert searches == ["Q1"]  # Q2 would start at t+20 > deadline
    assert messages is not None
    assert "budget" in messages[-1]["content"]


def test_ollama_backend_review_roll_success():
    pos = PositionSnapshot(
        symbol="AAPL250718C00190000",
        sec_type="OPT",
        position=-1,
        avg_cost=185.0,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=190.0,
        expiry=date(2026, 7, 18),
        delta=0.45,
    )
    quote = OptionQuote(
        underlying="AAPL", right=OptionRight.CALL, strike=190.0, expiry=date(2026, 7, 18)
    )
    alert = RollAlert(
        position_symbol="AAPL250718C00190000",
        underlying="AAPL",
        trigger="delta_drift",
        detail="Delta drifted to 0.45",
        current_delta=0.45,
        dte=10,
    )
    roll_payload = {
        "position_symbol": "AAPL250718C00190000",
        "recommendation": "hold",
        "roll_target": "",
        "rationale": "Still within tolerance.",
        "risks": "Could breach delta band if rally continues.",
        "confidence": 0.6,
    }

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch("src.claude.ollama_runner.httpx.post", return_value=_ollama_response(roll_payload)):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            review = review_roll(alert, pos, quote)

    assert review is not None
    assert review.recommendation == "hold"


def test_ollama_backend_write_journal_narrative_success():
    summary = EODSummary(
        date=date(2026, 6, 15),
        realized_pnl=120.0,
        unrealized_pnl=300.0,
        unrealized_pnl_delta=50.0,
        fills_today=2,
        open_positions=5,
        net_delta_exposure=-120.0,
        account=_make_account(),
    )
    payload = {"narrative": "Collected premium on two CSPs; no rolls today."}

    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()
    with patch("src.claude.ollama_runner.httpx.post", return_value=_ollama_response(payload)):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            narrative = write_journal_narrative(summary)

    assert narrative == "Collected premium on two CSPs; no rolls today."


# --------------------------------------------------------------------------- #
# dispatcher — cli_then_ollama fallback
# --------------------------------------------------------------------------- #


def test_cli_then_ollama_falls_back_when_cli_empty():
    """CLI returns unparseable/empty output -> dispatcher falls back to Ollama."""
    account = _make_account()
    candidates = [_make_candidate()]

    cfg = MagicMock(
        enabled=True,
        backend="cli_then_ollama",
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="",
        disallowed_tools="",
        max_retries=0,
        timeout_seconds=180.0,
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
        # Task 11 — off, so this test's single mocked httpx.post response (and its
        # assert_called_once()) still exercises exactly the Task 10 single-shot path.
        tool_research_enabled=False,
        # Final review I2 — the review's shared deadline reads these even with research off.
        tool_research_timeout_seconds=60.0,
        news_fetch_budget_seconds=30.0,
        review_min_call_seconds=60.0,
    )

    with patch("src.claude.runner.get_config") as mock_runner_cfg:
        mock_runner_cfg.return_value.claude = cfg
        with patch("src.claude.ollama_runner.get_config") as mock_ollama_cfg:
            mock_ollama_cfg.return_value.claude = cfg
            with patch(
                "src.claude.runner.subprocess.run",
                return_value=_completed_process("", returncode=1),
            ):
                with patch(
                    "src.claude.ollama_runner.httpx.post",
                    return_value=_ollama_response([_review_dict()]),
                ) as mock_post:
                    reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    assert reviews[0].candidate_id == "test-001"
    mock_post.assert_called_once()


def test_cli_then_ollama_skips_fallback_when_cli_succeeds():
    """CLI returns a valid review -> Ollama is never called."""
    account = _make_account()
    candidates = [_make_candidate()]
    envelope = _make_valid_cli_envelope([_review_dict()])

    cfg = MagicMock(
        enabled=True,
        backend="cli_then_ollama",
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="",
        disallowed_tools="",
        max_retries=0,
        timeout_seconds=180.0,
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
    )

    with patch("src.claude.runner.get_config") as mock_get_config:
        mock_get_config.return_value.claude = cfg
        with patch(
            "src.claude.runner.subprocess.run",
            return_value=_completed_process(envelope),
        ):
            with patch("src.claude.ollama_runner.httpx.post") as mock_post:
                reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    mock_post.assert_not_called()


def test_ollama_only_backend_skips_cli_subprocess():
    account = _make_account()
    candidates = [_make_candidate()]

    cfg = MagicMock(
        enabled=True,
        backend="ollama",
        ollama_host="http://localhost:11434",
        ollama_model="qwen2.5:14b-instruct",
        ollama_timeout_seconds=120.0,
        tool_research_enabled=False,
        tool_research_timeout_seconds=60.0,
        news_fetch_budget_seconds=30.0,
        review_min_call_seconds=60.0,
    )

    with patch("src.claude.runner.get_config") as mock_runner_cfg:
        mock_runner_cfg.return_value.claude = cfg
        with patch("src.claude.ollama_runner.get_config") as mock_ollama_cfg:
            mock_ollama_cfg.return_value.claude = cfg
            with patch("src.claude.runner.subprocess.run") as mock_subproc:
                with patch(
                    "src.claude.ollama_runner.httpx.post",
                    return_value=_ollama_response([_review_dict()]),
                ):
                    reviews = review_candidates(candidates, account)

    assert len(reviews) == 1
    mock_subproc.assert_not_called()


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #


def test_circuit_opens_after_threshold_connection_failures():
    """After _CIRCUIT_THRESHOLD consecutive connection failures the circuit opens."""
    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()

    with patch(
        "src.claude.ollama_runner.httpx.post",
        side_effect=httpx.ConnectError("refused"),
    ):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            for _ in range(ollama_mod._CIRCUIT_THRESHOLD):
                ollama_mod.review_candidates(candidates, account)

    assert ollama_mod._circuit_open is True
    assert ollama_mod._consecutive_failures >= ollama_mod._CIRCUIT_THRESHOLD


def test_circuit_open_skips_http_call():
    """When the circuit is open, no HTTP request is made."""
    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()

    ollama_mod._circuit_open = True
    ollama_mod._consecutive_failures = ollama_mod._CIRCUIT_THRESHOLD

    with patch("src.claude.ollama_runner.httpx.post") as mock_post:
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            result = ollama_mod.review_candidates(candidates, account)

    assert result == []
    mock_post.assert_not_called()


def test_circuit_resets_on_success():
    """A successful parse resets the failure counter and closes the circuit."""
    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()

    # Pre-load near the threshold.
    ollama_mod._consecutive_failures = ollama_mod._CIRCUIT_THRESHOLD - 1
    ollama_mod._circuit_open = False

    with patch(
        "src.claude.ollama_runner.httpx.post",
        return_value=_ollama_response([_review_dict()]),
    ):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            result = ollama_mod.review_candidates(candidates, account)

    assert len(result) == 1
    assert ollama_mod._consecutive_failures == 0
    assert ollama_mod._circuit_open is False


def test_circuit_opens_on_persistent_parse_failures():
    """Unparseable model output (empty-list parse result) also trips the circuit."""
    account = _make_account()
    candidates = [_make_candidate()]
    cfg, runner_patch, ollama_patch = _patch_ollama_cfg()

    # Ollama responds successfully but returns malformed JSON the schema rejects.
    bad_response = _ollama_response({"not": "a review list"})

    with patch("src.claude.ollama_runner.httpx.post", return_value=bad_response):
        with runner_patch as mock_runner_cfg, ollama_patch as mock_ollama_cfg:
            mock_runner_cfg.return_value.claude = cfg
            mock_ollama_cfg.return_value.claude = cfg
            for _ in range(ollama_mod._CIRCUIT_THRESHOLD):
                ollama_mod.review_candidates(candidates, account)

    assert ollama_mod._circuit_open is True


# --------------------------------------------------------------------------- #
# probe_ollama — startup/healthcheck reachability + model check
# --------------------------------------------------------------------------- #


def _tags_response(model_names: list[str]) -> MagicMock:
    """A mocked httpx.Response for Ollama's /api/tags."""
    mock = MagicMock()
    mock.json.return_value = {"models": [{"name": n} for n in model_names]}
    mock.raise_for_status.return_value = None
    return mock


def test_probe_ollama_ok_when_model_present():
    cfg, _, ollama_patch = _patch_ollama_cfg()
    cfg.ollama_model = "qwen3:14b"
    with patch(
        "src.claude.ollama_runner.httpx.get",
        return_value=_tags_response(["qwen3:14b", "qwen3:8b"]),
    ):
        with ollama_patch as mock_cfg:
            mock_cfg.return_value.claude = cfg
            ok, msg = ollama_mod.probe_ollama()
    assert ok is True
    assert "qwen3:14b" in msg


def test_probe_ollama_matches_untagged_config_value():
    """A config value without a tag (e.g. 'qwen3') matches any installed 'qwen3:*'."""
    cfg, _, ollama_patch = _patch_ollama_cfg()
    cfg.ollama_model = "qwen3"
    with patch(
        "src.claude.ollama_runner.httpx.get",
        return_value=_tags_response(["qwen3:14b"]),
    ):
        with ollama_patch as mock_cfg:
            mock_cfg.return_value.claude = cfg
            ok, _msg = ollama_mod.probe_ollama()
    assert ok is True


def test_probe_ollama_fails_when_model_not_pulled():
    cfg, _, ollama_patch = _patch_ollama_cfg()
    cfg.ollama_model = "qwen3:14b"
    with patch(
        "src.claude.ollama_runner.httpx.get",
        return_value=_tags_response(["qwen3:8b"]),
    ):
        with ollama_patch as mock_cfg:
            mock_cfg.return_value.claude = cfg
            ok, msg = ollama_mod.probe_ollama()
    assert ok is False
    assert "ollama pull qwen3:14b" in msg
    assert "qwen3:8b" in msg


def test_probe_ollama_fails_when_server_unreachable():
    cfg, _, ollama_patch = _patch_ollama_cfg()
    with patch(
        "src.claude.ollama_runner.httpx.get",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with ollama_patch as mock_cfg:
            mock_cfg.return_value.claude = cfg
            ok, msg = ollama_mod.probe_ollama()
    assert ok is False
    assert "not reachable" in msg
