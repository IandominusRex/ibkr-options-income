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


def test_a_half_migrated_value_db_fails_closed_but_a_pre_part_5_one_is_empty(
    tmp_path, monkeypatch
) -> None:
    import sqlite3

    pre = tmp_path / "pre.db"  # before Part 5: no value_orders at all
    sqlite3.connect(pre).close()
    monkeypatch.setattr(vv, "_path", lambda: pre)
    book = vv.read_book(NOW)
    assert book is not None and book.holdings == {}
    half = tmp_path / "half.db"  # value_orders exists, a later table does not
    con = sqlite3.connect(half)
    con.execute(
        "CREATE TABLE value_orders (symbol TEXT, side TEXT, shares REAL, filled REAL, "
        "avg_price REAL, status TEXT)"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(vv, "_path", lambda: half)
    assert vv.read_book(NOW) is None  # never an empty book: the wheel would count V as its own


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


def test_a_sent_buy_is_earmarked_by_its_unfilled_remainder(value_book_db) -> None:
    """Review I-8: between 'sent' and the fill the wheel's gross cap must still see the buy:
    market_value counts filled shares only, so the working remainder (at its limit) is earmarked."""
    from src.value.store import ValueOrderRow

    pid = proposal("META", status="sent", cost=30_000.0)  # no order row yet: the full cost
    assert vv.read_book(NOW).earmarked_usd == 30_000.0
    with value_session() as s:
        s.add(
            ValueOrderRow(
                symbol="META",
                list_name="deep_value",
                side="buy",
                proposal_id=pid,
                shares=100,
                filled=40,
                limit_price=300.0,
                avg_price=299.0,
                status="partial",
                created_at=NOW,
            )
        )
    assert vv.read_book(NOW).earmarked_usd == 18_000.0  # 60 unfilled x 300
    with value_session() as s:
        row = s.query(ValueOrderRow).one()
        row.status = "cancelled"  # nothing is working any more
    assert vv.read_book(NOW).earmarked_usd == 0.0


# --- Part 6, Task 5: the read-only surface of /value -------------------------------------------


def test_read_ticker_file_summarises_one_name(value_book_db) -> None:
    from tests.value_book_fixtures import ticker_file

    ticker_file("GOOGL", effective={"deep_value": ("READY", "claude")})
    order("GOOGL", shares=10, filled=10, avg=100.0)
    order("GOOGL", side="sell", shares=4, filled=4, avg=110.0)
    view = vv.read_ticker_file("googl")
    assert view is not None and view.symbol == "GOOGL"
    assert view.effective == {"deep_value": ("READY", "claude")}
    assert (view.verdict_deep, view.fair_value_deep, view.mos_deep) == ("READY", 140.0, 0.3)
    assert view.held_shares == 6.0 and view.open_reevaluation is None
    assert view.freshness_json is None  # the column arrives in Task 8
    assert vv.read_ticker_file("NOPE") is None


def test_top_names_puts_ready_before_watch_by_rank(value_book_db) -> None:
    from tests.value_book_fixtures import ticker_file

    deep = {"deep_value": ("READY", "python")}
    ticker_file("LOWR", rank_deep=10.0, effective=deep)
    ticker_file("HIGH", rank_deep=90.0, effective=deep)
    ticker_file("WTCH", rank_deep=99.0, effective={"deep_value": ("WATCH", "python")})
    ticker_file("WAIT", rank_deep=99.0, effective={"deep_value": ("WAIT", "python")})
    ticker_file("HELD", rank_deep=99.0, universe="held:trading", effective=deep)
    names = vv.top_names("deep_value", 5)
    assert names is not None and [n.symbol for n in names] == ["HIGH", "LOWR", "WTCH"]
    assert [n.symbol for n in vv.top_names("deep_value", 1) or []] == ["HIGH"]
    assert vv.top_names("quality_growth") == []


def test_open_proposals_carry_the_fingerprint_a_tap_needs(value_book_db) -> None:
    from src.common.value_commands import proposal_fingerprint

    pending = proposal("GOOGL", status="pending")
    proposal("META", status="done")
    proposal("MU", status="sent", kind="buy")
    views = vv.open_proposals()
    assert views is not None and [v.symbol for v in views] == ["GOOGL", "MU"]
    first = views[0]
    assert first.id == pending and first.needs_tap is True
    assert first.fingerprint == proposal_fingerprint(pending, "buy", "GOOGL", 10.0, NOW)


def test_last_nightly_run_reads_only_finished_nightly_rows(
    value_book_db, tmp_path, monkeypatch
) -> None:
    from datetime import datetime

    from src.value.store import ValueRunRow

    def run(kind: str, finished: datetime | None) -> None:
        with value_session() as s:
            s.add(
                ValueRunRow(
                    kind=kind,
                    started_at=datetime(2026, 11, 1, 6, 0),
                    finished_at=finished,
                    as_of=date(2026, 10, 30),
                    ruleset_version="v4",
                    ruleset_hash="be30d1eaa915",
                )
            )

    assert vv.last_nightly_run() is None  # no run at all
    run("dry_run", datetime(2026, 11, 3, 9, 0))  # not a nightly
    run("nightly", None)  # started, never finished
    assert vv.last_nightly_run() is None
    run("nightly", datetime(2026, 11, 2, 9, 5))
    run("nightly", datetime(2026, 11, 3, 9, 7))
    run("lookup", datetime(2026, 11, 4, 9, 0))
    assert vv.last_nightly_run() == datetime(2026, 11, 3, 9, 7)
    monkeypatch.setattr(vv, "_path", lambda: tmp_path / "absent.db")
    assert vv.last_nightly_run() is None
