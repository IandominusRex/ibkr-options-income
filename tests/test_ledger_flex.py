"""Flex Web Service client + parser (spec §5.2; R1, R6)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from src.ledger.flex import FlexError, fetch_statement, parse_flex_xml, run_flex_pull

SEND_OK = """<FlexStatementResponse timestamp="x"><Status>Success</Status>
<ReferenceCode>1234</ReferenceCode><Url>https://example.test/GetStatement</Url></FlexStatementResponse>"""
IN_PROGRESS = """<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"""
BAD_TOKEN = """<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode>
<ErrorMessage>Token has expired.</ErrorMessage></FlexStatementResponse>"""
STATEMENT = """<FlexQueryResponse queryName="ledger" type="AF"><FlexStatements count="1">
<FlexStatement accountId="U0000001" fromDate="20250710" toDate="20250718">
<Trades>
<Trade accountId="U0000001" currency="USD" assetCategory="OPT" symbol="NVDA  250718P00170000"
 underlyingSymbol="NVDA" strike="170" expiry="20250718" putCall="P" multiplier="100"
 dateTime="20250711;100000" quantity="-1" tradePrice="2" proceeds="200" ibCommission="-1.05"
 ibExecID="0001.01" ibOrderID="555" notes="O" levelOfDetail="EXECUTION" fifoPnlRealized="0"/>
<Trade accountId="U0000001" currency="USD" assetCategory="OPT" symbol="NVDA  250718P00170000"
 underlyingSymbol="NVDA" strike="170" expiry="20250718" putCall="P" multiplier="100"
 dateTime="20250718;162000" quantity="1" tradePrice="0" proceeds="0" ibCommission="0"
 ibExecID="" ibOrderID="" notes="C;Ep" levelOfDetail="EXECUTION" fifoPnlRealized="198.95"/>
<Trade accountId="U0000001" currency="USD" assetCategory="OPT" symbol="NVDA  250718P00170000"
 underlyingSymbol="NVDA" strike="170" expiry="20250718" putCall="P" multiplier="100"
 dateTime="20250711;100000" quantity="-1" tradePrice="2" proceeds="200" ibCommission="-1.05"
 ibExecID="" ibOrderID="555" notes="O" levelOfDetail="ORDER"/>
<Trade accountId="U0000001" currency="USD" assetCategory="CASH" symbol="USD.SGD"
 dateTime="20250711;100000" quantity="10" tradePrice="1.28" proceeds="-12.8" ibCommission="0"/>
</Trades>
<CashTransactions>
<CashTransaction type="Deposits/Withdrawals" currency="USD" amount="45000" dateTime="20250526"
 settleDate="20250526" description="Electronic Fund Transfer" symbol="" levelOfDetail="DETAIL"/>
<CashTransaction type="Dividends" currency="USD" amount="29.16" dateTime="20250613;202000"
 description="QDTE(US77926X3044) Cash Dividend" symbol="QDTE" levelOfDetail="DETAIL"/>
<CashTransaction type="Dividends" currency="USD" amount="29.16" dateTime="20250613"
 description="summary" symbol="QDTE" levelOfDetail="SUMMARY"/>
</CashTransactions>
<ConversionRates>
<ConversionRate reportDate="20250711" fromCurrency="USD" toCurrency="SGD" rate="1.28"/>
<ConversionRate reportDate="20250711" fromCurrency="EUR" toCurrency="SGD" rate="1.50"/>
</ConversionRates>
<CorporateActions>
<CorporateAction reportDate="20251118" dateTime="20251117;202500" description="OPEN(US6837121036) Spinoff"
 quantity="30" proceeds="0" symbol="OPENW" underlyingSymbol="OPEN"/>
</CorporateActions>
</FlexStatement></FlexStatements></FlexQueryResponse>"""

# A Trade whose codes live entirely in `openCloseIndicator`, not `notes` — exercises the
# controller ruling (Task 10): merge openCloseIndicator tokens into codes when notes doesn't
# already carry them, so this row still carries a "C"/"O" code for the reporting layer's
# pure-close test (codes contain "C" and not "O").
OPEN_CLOSE_ONLY = """<FlexQueryResponse><FlexStatements count="1">
<FlexStatement accountId="U0000001" fromDate="20250710" toDate="20250718">
<Trades>
<Trade accountId="U0000001" currency="USD" assetCategory="STK" symbol="AAPL"
 dateTime="20250711;100000" quantity="100" tradePrice="150" proceeds="-15000" ibCommission="-1.00"
 ibExecID="0002.01" notes="" openCloseIndicator="C" levelOfDetail="EXECUTION"/>
</Trades>
</FlexStatement></FlexStatements></FlexQueryResponse>"""

# notes already carries "O"; openCloseIndicator repeats it and adds nothing new — must not
# duplicate the existing token.
OPEN_CLOSE_DUPLICATE = """<FlexQueryResponse><FlexStatements count="1">
<FlexStatement accountId="U0000001" fromDate="20250710" toDate="20250718">
<Trades>
<Trade accountId="U0000001" currency="USD" assetCategory="STK" symbol="AAPL"
 dateTime="20250711;100000" quantity="-100" tradePrice="150" proceeds="15000" ibCommission="-1.00"
 ibExecID="0003.01" notes="O" openCloseIndicator="O" levelOfDetail="EXECUTION"/>
</Trades>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


def _client(responses: list[str]) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=queue.pop(0))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_retries_while_generation_is_in_progress() -> None:
    sleeps: list[float] = []
    text = fetch_statement(
        "t",
        "q",
        client=_client([SEND_OK, IN_PROGRESS, STATEMENT]),
        poll_interval=1.0,
        sleep=sleeps.append,
    )
    assert "<FlexQueryResponse" in text and sleeps == [1.0]


def test_fetch_raises_on_a_hard_error() -> None:
    with pytest.raises(FlexError) as exc:
        fetch_statement("t", "q", client=_client([BAD_TOKEN]), sleep=lambda _: None)
    assert exc.value.code == "1012"


def test_fetch_times_out() -> None:
    ticks = iter([0.0, 0.0, 1000.0])
    with pytest.raises(FlexError) as exc:
        fetch_statement(
            "t",
            "q",
            client=_client([SEND_OK, IN_PROGRESS, IN_PROGRESS]),
            timeout=10,
            sleep=lambda _: None,
            clock=lambda: next(ticks),
        )
    assert exc.value.code == "timeout"


def test_parse_trades_cash_fx_and_corporate_actions() -> None:
    st = parse_flex_xml(STATEMENT)
    assert st.account == "U0000001"
    assert len(st.executions) == 2  # ORDER-level duplicate and CASH row skipped
    opened = next(e for e in st.executions if e.quantity < 0)
    assert (opened.exec_id, opened.perm_id, opened.commission) == ("0001.01", 555, -1.05)
    assert opened.trade_time == datetime(2025, 7, 11, 14, 0, tzinfo=UTC)
    assert opened.contract.ident == "OPT:NVDA:20250718:P:170:USD"
    expired = next(e for e in st.executions if e.quantity > 0)
    assert (expired.exec_id, expired.codes, expired.source_kind) == (None, "C;Ep", "order")
    assert sorted(c.event_type for c in st.cash_events) == ["deposit", "dividend"]
    rates = {f.currency: f.usd_rate for f in st.fx_rates}
    assert rates["SGD"] == pytest.approx(1 / 1.28)
    assert rates["EUR"] == pytest.approx(1.50 / 1.28)
    assert st.corporate_actions[0].event_date == date(2025, 11, 18)


def test_open_close_indicator_merges_into_codes_when_notes_is_blank() -> None:
    """Controller ruling: notes="" + openCloseIndicator="C" must yield codes containing "C"."""
    st = parse_flex_xml(OPEN_CLOSE_ONLY)
    assert "C" in st.executions[0].codes


def test_open_close_indicator_does_not_duplicate_a_token_notes_already_has() -> None:
    st = parse_flex_xml(OPEN_CLOSE_DUPLICATE)
    assert st.executions[0].codes == "O"


def test_pull_is_a_noop_when_unconfigured(monkeypatch) -> None:
    from src.common.config import get_config

    monkeypatch.setattr(get_config().secrets, "ibkr_flex_token", "")
    assert run_flex_pull() is None


def test_cli_prints_not_configured_and_exits_zero(monkeypatch, capsys) -> None:
    """F13: unconfigured Flex is a normal, expected state for the CLI — exit 0, not 2."""
    import scripts.ledger_flex_pull as cli

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "run_flex_pull", lambda **kwargs: None)
    assert cli.main([]) == 0
    assert "not configured" in capsys.readouterr().out
