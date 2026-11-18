"""The data-gated envelope switches, their result files and the notices (risk-envelope Task 1).

A switch is a ``system_settings`` row that a human or a PASSed report sets. Every one reads its
default in live (``spxw_ready`` excepted), a report only ever turns a switch on, and a switch the
operator set by hand is never overwritten by a later report (plan ruling P11).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.common.schemas import EnvelopeReportResult
from src.storage import envelope_switches as sw


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _live(monkeypatch) -> None:
    from src.common.config import Config

    monkeypatch.setattr(Config, "is_live", property(lambda self: True))


def _report(
    dir_: Path,
    rid: str,
    *,
    passed: bool | None,
    switch: str = "slow_breaker",
    value: str = "12",
    metrics: dict | None = None,
) -> None:
    result = EnvelopeReportResult(
        id=rid,
        passed=passed,
        criterion="a rule",
        metrics=metrics if metrics is not None else {"n": 3.0},
        switch=switch,
        value_on_pass=value,
        written_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    (dir_ / f"{rid}.json").write_text(result.model_dump_json())


def test_a_missing_switch_reads_its_default() -> None:
    assert sw.get_switch("envelope_enforce") == "record"
    assert sw.get_switch("leveraged_entry") == "record"
    assert sw.get_switch("slow_breaker") == "off"
    assert sw.get_switch("cc_basis_floor") == "1.00"
    assert sw.get_switch("hedge_instrument") == "none"
    assert sw.switch_record("slow_breaker") is None


def test_set_switch_rejects_a_value_outside_its_set() -> None:
    with pytest.raises(ValueError):
        sw.set_switch("slow_breaker", "11", source="cli")
    with pytest.raises(ValueError):
        sw.set_switch("no_such_switch", "on", source="cli")
    assert sw.get_switch("slow_breaker") == "off"
    sw.set_switch("slow_breaker", "12", source="cli")
    assert sw.get_switch("slow_breaker") == "12"
    rec = sw.switch_record("slow_breaker")
    assert rec is not None
    assert rec["source"] == "cli" and rec["value"] == "12" and rec["set_at"]


def test_every_switch_reads_its_default_in_live(monkeypatch) -> None:
    for name, (default, allowed) in sw.SWITCHES.items():
        other = sorted(allowed - {default})[0]
        sw.set_switch(name, other, source="cli")
        assert sw.get_switch(name) == other, name  # stored value is read in paper
    _live(monkeypatch)
    for name, (default, _allowed) in sw.SWITCHES.items():
        if name == "spxw_ready":
            continue
        assert sw.get_switch(name) == default, name
    # spxw_ready is the one exception: it reads what was stored.
    sw.set_switch("spxw_ready", "spxw", source="cli")
    assert sw.get_switch("spxw_ready") == "spxw"


def test_an_unparseable_stored_switch_reads_its_default() -> None:
    from src.storage.system_settings import set_setting

    set_setting("envelope_switch:slow_breaker", "not json")
    assert sw.get_switch("slow_breaker") == "off"
    set_setting("envelope_switch:slow_breaker", json.dumps({"value": "99"}))
    assert sw.get_switch("slow_breaker") == "off"


def test_a_passed_report_turns_its_switch_on_once(tmp_path) -> None:
    _report(tmp_path, "E14", passed=True)
    msgs = sw.apply_reports(tmp_path)
    assert len(msgs) == 1
    assert sw.get_switch("slow_breaker") == "12"
    rec = sw.switch_record("slow_breaker")
    assert rec is not None and rec["source"] == "report:E14"
    assert "E14 PASS: slow_breaker -> 12" in msgs[0]
    assert "python -m scripts.envelope switch slow_breaker off" in msgs[0]
    # a second run with the same report changes nothing and says nothing
    assert sw.apply_reports(tmp_path) == []


def test_a_failed_report_changes_nothing(tmp_path) -> None:
    _report(tmp_path, "E14", passed=False)
    _report(tmp_path, "E15", passed=None, switch="tech_cap", value="on")
    assert sw.apply_reports(tmp_path) == []
    assert sw.get_switch("slow_breaker") == "off"
    assert sw.get_switch("tech_cap") == "off"
    assert sw.switch_record("slow_breaker") is None


def test_a_cli_set_switch_is_never_overwritten_by_a_report(tmp_path) -> None:
    sw.set_switch("slow_breaker", "off", source="cli")
    _report(tmp_path, "E14", passed=True)
    assert sw.apply_reports(tmp_path) == []
    assert sw.get_switch("slow_breaker") == "off"
    rec = sw.switch_record("slow_breaker")
    assert rec is not None and rec["source"] == "cli"


def test_a_later_report_may_replace_an_earlier_reports_value(tmp_path) -> None:
    _report(tmp_path, "E14", passed=True, value="15")
    sw.apply_reports(tmp_path)
    _report(tmp_path, "E14", passed=True, value="10")
    msgs = sw.apply_reports(tmp_path)
    assert len(msgs) == 1
    assert sw.get_switch("slow_breaker") == "10"


def test_the_notice_says_when_the_value_is_the_fallback(tmp_path) -> None:
    """Review fix 6: E14 writes passed=True with 15 when no threshold qualified; the notice must
    not read as a plain measured PASS."""
    _report(tmp_path, "E14", passed=True, value="15", metrics={"fell_back_to_15": "yes"})
    (msg,) = sw.apply_reports(tmp_path)
    assert msg.startswith("E14 PASS (fallback: no threshold qualified): slow_breaker -> 15")


def test_a_measured_pass_is_not_called_a_fallback(tmp_path) -> None:
    _report(tmp_path, "E14", passed=True, value="10", metrics={"fell_back_to_15": "no"})
    (msg,) = sw.apply_reports(tmp_path)
    assert "fallback" not in msg and msg.startswith("E14 PASS: slow_breaker -> 10")


def test_the_notice_names_what_the_switch_does_in_live(tmp_path) -> None:
    """Every switch but the two that default to `record` reads off in live; saying 'record-only'
    for them was wrong."""
    _report(tmp_path, "E14", passed=True)
    (msg,) = sw.apply_reports(tmp_path)
    assert "(paper only; off in live)" in msg and "record-only" not in msg
    _report(tmp_path, "L1", passed=True, switch="leveraged_entry", value="on")
    (msg,) = sw.apply_reports(tmp_path)
    assert "(paper; record-only in live)" in msg  # its live default really is `record`


def test_apply_reports_returns_one_notice_per_change(tmp_path) -> None:
    _report(tmp_path, "E14", passed=True)
    _report(tmp_path, "E15", passed=True, switch="tech_cap", value="on")
    _report(tmp_path, "H4", passed=False, switch="hedge_instrument", value="XND")
    msgs = sw.apply_reports(tmp_path)
    assert len(msgs) == 2
    assert sw.get_switch("tech_cap") == "on"
    assert sw.get_switch("hedge_instrument") == "none"


def test_an_unreadable_result_file_is_skipped_and_logged(tmp_path, caplog) -> None:
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "wrong.json").write_text(json.dumps({"id": "x"}))
    _report(tmp_path, "E14", passed=True, switch="slow_breaker", value="99")  # outside the set
    _report(tmp_path, "E15", passed=True, switch="tech_cap", value="on")
    with caplog.at_level("WARNING"):
        msgs = sw.apply_reports(tmp_path)
    assert len(msgs) == 1 and "E15" in msgs[0]
    assert "bad.json" in caplog.text
    assert sw.get_switch("slow_breaker") == "off"


def test_a_missing_report_directory_is_no_reports(tmp_path) -> None:
    assert sw.apply_reports(tmp_path / "nope") == []


def test_the_cli_sets_a_switch_and_notifies(monkeypatch, capsys) -> None:
    from unittest.mock import AsyncMock

    from scripts import envelope as cli

    notice = AsyncMock(return_value=True)
    monkeypatch.setattr(cli, "send_notice", notice)
    assert cli.main(["switch", "slow_breaker", "12"]) == 0
    assert sw.get_switch("slow_breaker") == "12"
    rec = sw.switch_record("slow_breaker")
    assert rec is not None and rec["source"] == "cli"
    notice.assert_awaited_once()
    assert cli.main(["switch", "slow_breaker", "11"]) == 1  # outside the set: refused
    assert sw.get_switch("slow_breaker") == "12"
    assert cli.main(["show"]) == 0
    assert "slow_breaker" in capsys.readouterr().out


async def test_the_eod_hook_sends_one_notice_per_change(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from src.notify import notices
    from src.orchestrator import eod_report

    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(notices, "send_notice", sent)
    monkeypatch.setattr(sw, "apply_reports", lambda *a, **k: ["a", "b"])
    await eod_report._apply_envelope_reports()
    assert [c.args[0] for c in sent.await_args_list] == ["a", "b"]

    def _boom(*a, **k):
        raise RuntimeError("bad dir")

    monkeypatch.setattr(sw, "apply_reports", _boom)
    await eod_report._apply_envelope_reports()  # never raises


async def test_send_notice_never_raises(monkeypatch) -> None:
    from src.common.config import get_config
    from src.notify import notices

    class _Boom:
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("telegram down")

    monkeypatch.setattr(notices, "Bot", _Boom)
    sec = get_config().secrets
    monkeypatch.setattr(sec, "telegram_bot_token", "t", raising=False)
    monkeypatch.setattr(sec, "telegram_chat_id", "1", raising=False)
    assert await notices.send_notice("hello") is False


async def test_send_notice_without_credentials_is_false(monkeypatch) -> None:
    from src.common.config import get_config
    from src.notify import notices

    sec = get_config().secrets
    monkeypatch.setattr(sec, "telegram_bot_token", "", raising=False)
    assert await notices.send_notice("hello") is False
