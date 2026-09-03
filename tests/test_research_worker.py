"""The worker records a heartbeat and never dies on a failing job."""

from __future__ import annotations

import pytest

from src.research.ingest.jobs import read_heartbeat, record_heartbeat, run_job
from src.research.store.session import init_research_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_heartbeat_is_absent_before_the_worker_runs(db) -> None:
    assert read_heartbeat() is None


def test_heartbeat_is_recorded_and_read_back(db) -> None:
    record_heartbeat("symbols")
    assert read_heartbeat() is not None


def test_a_failing_job_is_swallowed_and_reported(db, caplog) -> None:
    def boom() -> None:
        raise RuntimeError("SEC is down")

    assert run_job("symbols", boom) is False
    assert "SEC is down" in caplog.text


def test_a_successful_job_reports_true_and_beats(db) -> None:
    assert run_job("symbols", lambda: 42) is True
    assert read_heartbeat() is not None


def test_a_failing_job_does_not_record_a_heartbeat(db) -> None:
    """A heartbeat means work succeeded. A lying heartbeat hides an outage."""

    def boom() -> None:
        raise RuntimeError("nope")

    run_job("symbols", boom)
    assert read_heartbeat() is None
