"""GET /research/{symbol}/options — Task 6.3, the on-demand options-income lens.

Honest degradation is the whole point: a universe symbol gets real iv_rank/vrp_points
from the trading DB, read-only (§4.3); an off-universe symbol gets the same shape with
UNKNOWN rather than a percentile invented from a short series. coverage.option_chain is
always false in P1 (no IBKR connection in the API process). Leverage warnings (Task 5.4)
ride along via the shared warnings_for catalogue.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.store.models import QuoteRow, SymbolRow
from src.research.store.session import init_research_db, research_session
from src.storage.models import FundamentalCacheRow, IVHistoryRow, PriceHistoryRow

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    with research_session() as s:
        s.add_all(
            [
                # NVDA: in universe.yaml (would_own/watchlist/actively_wheeling).
                SymbolRow(symbol="NVDA", cik="1", name="NVIDIA Corp", is_etf=False),
                # RIVN: a known filer, but not in any universe.yaml list.
                SymbolRow(symbol="RIVN", cik="2", name="Rivian Automotive", is_etf=False),
                # SOXL: in universe.yaml AND config/universe.yaml -> leveraged_etfs.
                SymbolRow(symbol="SOXL", cik="3", name="Direxion Semis Bull 3X", is_etf=True),
            ]
        )

    return TestClient(create_app())


def _seed_iv(symbol: str, ivs: list[float]) -> None:
    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        for i, iv in enumerate(ivs):
            s.add(
                IVHistoryRow(symbol=symbol, obs_date=date(2026, 1, 1) + date.resolution * i, iv=iv)
            )


def _seed_prices(symbol: str, closes: list[float]) -> None:
    """31+ ascending daily closes, oldest first — enough for the read-only HV30 calc."""
    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        for i, close in enumerate(closes):
            d = date(2026, 1, 1) + date.resolution * i
            s.add(
                PriceHistoryRow(
                    symbol=symbol, obs_date=d, open=close, high=close, low=close, close=close
                )
            )


def _seed_quote(symbol: str, price: float) -> None:
    with research_session() as s:
        s.add(QuoteRow(symbol=symbol, price=price, change_pct=0.0, as_of=datetime.now(UTC)))


def _wiggly_closes(n: int, base: float = 100.0) -> list[float]:
    """Deterministic non-flat closes so log-return std (HV30) is a real, non-zero number."""
    return [base + (5.0 if i % 2 == 0 else -3.0) for i in range(n)]


def test_requires_auth(client) -> None:
    assert client.get("/research/NVDA/options").status_code == 401


def test_unknown_symbol_returns_404(client) -> None:
    assert client.get("/research/ZZZZ/options", headers=AUTH).status_code == 404


def test_route_registration_does_not_collide_with_search_or_symbol(client) -> None:
    """The /{symbol}/options route must not be swallowed by /search or /{symbol}."""
    assert client.get("/research/search?q=NVDA", headers=AUTH).status_code == 200
    r = client.get("/research/NVDA/options", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["symbol"] == "NVDA"


def test_universe_symbol_reports_in_universe_and_hot_tier(client) -> None:
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    assert r["in_universe"] is True
    assert r["tier"] == "hot"


def test_off_universe_symbol_reports_not_in_universe_and_cold_tier(client) -> None:
    r = client.get("/research/RIVN/options", headers=AUTH).json()
    assert r["in_universe"] is False
    assert r["tier"] == "cold"


def test_universe_symbol_gets_real_iv_rank_and_coverage_true(client) -> None:
    # Seeded oldest-first; obs_date DESC picks the last entry as "current" -> 0.80,
    # so rank = (80-30)/(80-30)*100 = 100.0.
    _seed_iv("NVDA", [0.30, 0.50, 0.80])
    _seed_prices("NVDA", _wiggly_closes(31))
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    assert r["coverage"]["iv_history"] is True

    iv_rank_check = next(c for c in r["checks"] if c["id"] == "options.iv_rank")
    assert iv_rank_check["state"] in ("PASS", "FAIL")
    assert iv_rank_check["actual"] == pytest.approx(100.0)

    vrp_check = next(c for c in r["checks"] if c["id"] == "options.vrp_positive")
    assert vrp_check["state"] in ("PASS", "FAIL")
    assert vrp_check["actual"] is not None


def test_off_universe_symbol_gets_unknown_iv_rank_and_coverage_false(client) -> None:
    """No iv_history at all for RIVN — must not invent a rank, not even from a short series."""
    r = client.get("/research/RIVN/options", headers=AUTH).json()
    assert r["coverage"]["iv_history"] is False

    iv_rank_check = next(c for c in r["checks"] if c["id"] == "options.iv_rank")
    assert iv_rank_check["state"] == "UNKNOWN"
    assert iv_rank_check["actual"] is None


def test_a_single_iv_observation_does_not_invent_a_rank(client) -> None:
    """One data point still counts as coverage, but min==max must never produce a rank."""
    _seed_iv("NVDA", [0.40])
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    assert r["coverage"]["iv_history"] is True  # history exists...

    iv_rank_check = next(c for c in r["checks"] if c["id"] == "options.iv_rank")
    assert iv_rank_check["state"] == "UNKNOWN"  # ...but no range means no rank


def test_option_chain_coverage_is_always_false(client) -> None:
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    assert r["coverage"]["option_chain"] is False

    oi_check = next(c for c in r["checks"] if c["id"] == "options.chain_open_interest")
    spread_check = next(c for c in r["checks"] if c["id"] == "options.spread_tight")
    assert oi_check["state"] == "UNKNOWN"
    assert spread_check["state"] == "UNKNOWN"


def test_leverage_warning_is_included_for_a_leveraged_name(client) -> None:
    r = client.get("/research/SOXL/options", headers=AUTH).json()
    assert any("Daily-reset decay" in w["title"] for w in r["warnings"])


def test_no_warning_for_an_ordinary_name(client) -> None:
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    assert r["warnings"] == []


def test_days_to_earnings_reads_from_the_fundamentals_cache(client) -> None:
    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        s.add(
            FundamentalCacheRow(
                symbol="NVDA",
                data_json="{}",
                next_earnings_date=(date.today() + timedelta(days=60)),
            )
        )
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    earnings_check = next(c for c in r["checks"] if c["id"] == "options.earnings_clear")
    assert earnings_check["state"] == "PASS"


def test_cc_yield_check_needs_a_quote_price_too(client) -> None:
    """cc_yield requires both current_iv and price; without a quote it stays UNKNOWN."""
    _seed_iv("NVDA", [0.30, 0.50, 0.80])
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    cc_yield_check = next(c for c in r["checks"] if c["id"] == "options.cc_yield")
    assert cc_yield_check["state"] == "UNKNOWN"

    _seed_quote("NVDA", 120.0)
    r = client.get("/research/NVDA/options", headers=AUTH).json()
    cc_yield_check = next(c for c in r["checks"] if c["id"] == "options.cc_yield")
    assert cc_yield_check["state"] in ("PASS", "FAIL")
