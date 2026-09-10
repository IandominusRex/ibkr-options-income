"""Task 6.1 — GET /pnl/system: the score-vs-outcome report's human reader.

The one P&L route that reads behind the src/claude/eval/ fence — CLAUDE.md says everything
eval/ produces "is read by a human, never auto-applied," and this route is that human's
reader. It must never recompute what score_outcome_report already produced.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.claude.eval.score_metrics import score_outcome_report
from tests.conftest import OWNER


def test_the_reports_notes_pass_through_verbatim(client, seed_closed_ledger_rows) -> None:
    """The read-only sentence is the most important text on the surface."""
    seed_closed_ledger_rows(n=12)
    expected = score_outcome_report().notes

    body = client.get("/pnl/system", headers=OWNER).json()
    assert body["report"]["notes"] == expected
    assert any("forbids any automatic feedback" in note for note in body["report"]["notes"])


def test_no_closed_trades_returns_the_reports_own_empty_case(client) -> None:
    r = client.get("/pnl/system", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["n_closed"] == 0
    assert any("No closed trades in window" in note for note in body["report"]["notes"])
    assert body["agreement"]["agreement_rate"] is None
    assert body["agreement"]["n_closed"] == 0


def test_the_route_does_not_recompute_the_report(
    client, seed_closed_ledger_rows, monkeypatch
) -> None:
    """If the report is wrong, it is fixed in score_metrics.py, not in a router."""
    seed_closed_ledger_rows(n=5)
    calls = []
    real = score_outcome_report

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr("src.api.routers.pnl.score_outcome_report", spy)
    client.get("/pnl/system", headers=OWNER)
    assert len(calls) == 1


def test_the_response_carries_the_reports_buckets_and_correlations_unchanged(
    client, seed_closed_ledger_rows
) -> None:
    seed_closed_ledger_rows(n=12)
    expected = score_outcome_report().model_dump(mode="json")

    body = client.get("/pnl/system", headers=OWNER).json()
    assert body["report"]["blended_score_buckets"] == expected["blended_score_buckets"]
    assert body["report"]["component_buckets"] == expected["component_buckets"]
    assert body["report"]["signal_correlations"] == expected["signal_correlations"]


def test_agreement_rate_is_a_real_number_with_closed_rows(client, seed_closed_ledger_rows) -> None:
    seed_closed_ledger_rows(n=10)
    body = client.get("/pnl/system", headers=OWNER).json()
    assert body["agreement"]["n_closed"] == 10
    assert body["agreement"]["agreement_rate"] is not None
    assert 0.0 <= body["agreement"]["agreement_rate"] <= 1.0
    assert body["agreement"]["claude_win_rate"] is not None
    assert body["agreement"]["baseline_win_rate"] is not None


def test_since_and_until_window_the_report_and_are_echoed_back(
    client, seed_closed_ledger_rows
) -> None:
    seed_closed_ledger_rows(n=4, offset_days=40)
    seed_closed_ledger_rows(n=4, offset_days=2)
    since = date.today() - timedelta(days=10)
    until = date.today()

    body = client.get(
        f"/pnl/system?since={since.isoformat()}&until={until.isoformat()}", headers=OWNER
    ).json()

    assert body["since"] == since.isoformat()
    assert body["until"] == until.isoformat()
    assert body["report"]["n_closed"] == 4
    assert body["agreement"]["n_closed"] == 4


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/system", headers=OWNER).status_code == 403
