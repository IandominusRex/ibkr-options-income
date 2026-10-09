# tests/test_news_llm.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.common.config import get_config
from src.news import llm

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def _cfg(monkeypatch, **kw):
    cfg = get_config().news.llm
    for k, v in kw.items():
        monkeypatch.setattr(cfg, k, v)


def test_cli_first_then_ollama_fallback(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli_then_ollama")
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: None)
    monkeypatch.setattr(llm, "_ollama", lambda prompt, schema, cfg: '{"ok": 1}')
    res = llm.call_llm("p", schema={}, prefix="t", now=NOW)
    assert res == llm.LlmResult('{"ok": 1}', "ollama")
    from src.news.store.state import llm_calls

    assert llm_calls(datetime(2026, 10, 14).date()) == 2


def test_cap_stops_calls(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=1)
    calls = []
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: calls.append(1) or "x")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW).backend == "cli"
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is None
    assert calls == [1] and llm.cap_reached(NOW)


def test_cli_command_pins_news_model(monkeypatch) -> None:
    seen = {}

    def fake_run(prompt, prefix, parse_fn, *, cmd, timeout_seconds, max_retries):
        seen["cmd"] = cmd
        return parse_fn('{"type":"result","result":"{\\"a\\":1}"}')

    monkeypatch.setattr("src.claude.runner._run_cli", fake_run)
    out = llm._cli("p", "t", get_config().news.llm)
    assert out == '{"a":1}'
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "claude-sonnet-5-5"
    assert "--disallowedTools" in seen["cmd"]


def test_a_raising_backend_is_counted_and_falls_through(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli_then_ollama")

    def boom(prompt, prefix, cfg):
        raise RuntimeError("cli exploded")

    monkeypatch.setattr(llm, "_cli", boom)
    monkeypatch.setattr(llm, "_ollama", lambda prompt, schema, cfg: "fallback")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) == llm.LlmResult("fallback", "ollama")
    from src.news.store.state import llm_calls

    assert llm_calls(datetime(2026, 10, 14).date()) == 2


def test_ollama_only_never_touches_the_cli(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="ollama")
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: pytest.fail("cli must not run"))
    monkeypatch.setattr(llm, "_ollama", lambda prompt, schema, cfg: "local")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) == llm.LlmResult("local", "ollama")


def test_every_backend_failing_returns_none_and_still_counts(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli_then_ollama")
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: None)
    monkeypatch.setattr(llm, "_ollama", lambda prompt, schema, cfg: "")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is None
    from src.news.store.state import llm_calls

    assert llm_calls(datetime(2026, 10, 14).date()) == 2


def test_cap_applies_between_backends_in_one_call(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli_then_ollama", max_calls_per_day=1)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: None)
    monkeypatch.setattr(
        llm, "_ollama", lambda prompt, schema, cfg: pytest.fail("cap must stop ollama")
    )
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is None
    assert llm.cap_reached(NOW)


def test_cap_is_keyed_by_the_et_date_not_utc(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=1)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: "x")
    late_et = datetime(2026, 10, 15, 2, tzinfo=UTC)  # 22:00 ET on the 14th
    assert llm.call_llm("p", schema={}, prefix="t", now=late_et) is not None
    assert llm.cap_reached(NOW)  # same ET day, 11:00 ET on the 14th
    assert not llm.cap_reached(datetime(2026, 10, 15, 14, tzinfo=UTC))  # next ET day


def test_ollama_backend_passes_model_override_schema_and_timeout(monkeypatch) -> None:
    seen = {}

    def fake_generate(prompt, cfg, schema, *, timeout):
        seen.update(model=cfg.ollama_model, schema=schema, timeout=timeout, prompt=prompt)
        return "ok"

    monkeypatch.setattr("src.claude.ollama_runner._generate", fake_generate)
    cfg = get_config().news.llm.model_copy(
        update={"ollama_model": "tiny:1b", "timeout_seconds": 7.0}
    )
    assert llm._ollama("hello", {"type": "object"}, cfg) == "ok"
    assert seen == {
        "model": "tiny:1b",
        "schema": {"type": "object"},
        "timeout": 7.0,
        "prompt": "hello",
    }
    # no override: the trading pipeline's own claude.ollama_model is used
    llm._ollama("hello", {}, get_config().news.llm.model_copy(update={"ollama_model": ""}))
    assert seen["model"] == get_config().claude.ollama_model
