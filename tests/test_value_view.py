"""The wheel's read-only window onto the value book (value book spec §9.1-§9.2, revision 4)."""

from __future__ import annotations

from datetime import date

from src.common import value_view as vv
from src.value.store import ValueAttributionRow, ValueEffectiveRow, value_session
from tests.value_book_fixtures import NOW, funding, order, proposal


def test_no_value_db_is_an_empty_book(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vv, "_path", lambda: tmp_path / "absent.db")
    book = vv.read_book(NOW)
    assert book is not None and book.holdings == {} and book.earmarked_usd == 0.0
    assert vv.put_ceiling("GOOGL") is None


def test_an_unreadable_value_db_fails_closed(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "value.db"
    bad.write_bytes(b"this is not a database")
    monkeypatch.setattr(vv, "_path", lambda: bad)
    assert vv.read_book(NOW) is None


def test_holdings_earmarks_freezes_and_requests(value_book_db) -> None:
    order("GOOGL", shares=10, filled=10, avg=150.0)
    order("GOOGL", shares=10, filled=4, avg=160.0, status="partial")
    order("GOOGL", side="sell", shares=5, filled=5, avg=170.0)
    order("META", shares=20, filled=0, avg=None, status="submitted")
    order("BAC", shares=30, filled=0, avg=None, status="cancelled")
    proposal("META", status="funding", cost=12_000.0)
    proposal("MU", status="pending", cost=5_000.0)  # not approved: no earmark
    funding("META", 4_000.0)
    funding("OLD", 1_000.0, status="lapsed")
    with value_session() as s:
        s.add(
            ValueAttributionRow(
                symbol="BAC", broker=130, wheel=100, value_filled=0, state="frozen", updated_at=NOW
            )
        )
    book = vv.read_book(NOW)
    assert book is not None
    g = book.holding("googl")
    assert (g.filled, g.pending_buy, g.pending_sell) == (9.0, 6.0, 0.0)  # 14 bought, 5 sold
    assert g.claimed == 15.0
    assert round(g.cost, 2) == round(9 * (10 * 150 + 4 * 160) / 14, 2)
    assert book.holding("META").claimed == 20.0 and book.holding("BAC").claimed == 0.0
    assert book.earmarked_usd == 12_000.0
    assert book.frozen == frozenset({"BAC"})
    assert [(r.symbol, r.needed_usd) for r in book.requests] == [("META", 4_000.0)]


def test_the_put_ceiling_is_the_highest_effective_ceiling_of_a_live_list(value_book_db) -> None:
    with value_session() as s:
        for list_name, verdict, ceiling in (
            ("deep_value", "WAIT", 140.0),
            ("quality_growth", "READY", 180.0),
        ):
            s.add(
                ValueEffectiveRow(
                    symbol="GOOGL",
                    list_name=list_name,
                    as_of=date(2026, 10, 30),
                    verdict=verdict,
                    decided_by="python",
                    python_verdict=verdict,
                    entry_ceiling=ceiling,
                    updated_at=NOW,
                )
            )
        s.add(
            ValueEffectiveRow(
                symbol="SICK",
                list_name="deep_value",
                as_of=date(2026, 10, 30),
                verdict="NO",
                decided_by="python",
                python_verdict="NO",
                entry_ceiling=50.0,
                updated_at=NOW,
            )
        )
    assert vv.put_ceiling("googl") == 180.0
    assert vv.put_ceiling("SICK") is None  # NO: no value-suggested put
