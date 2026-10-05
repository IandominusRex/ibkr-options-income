"""IBKR Flex Web Service client + Flex XML parser (spec §5.2; revisions R1, R6).

Configure once in Client Portal (SETUP.md "Trade ledger"): an Activity Flex Query with Trades
(Execution level), Cash Transactions, Corporate Actions and Conversion Rates; XML; date format
yyyyMMdd, time HHmmss, separator ';'. Option Exercises/Assignments/Expirations is not read in v1 —
those arrive as Trades rows (R1); confirm with ``scripts.ledger_flex_pull --dry-run``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from xml.etree import ElementTree

import httpx

from src.common.config import get_config
from src.common.schemas import (
    LedgerContract,
    LedgerImportResult,
    LedgerParseError,
    ParsedCashEvent,
    ParsedCorporateAction,
    ParsedExecution,
    ParsedFxRate,
    ParsedStatement,
)
from src.ledger.activity_csv import number_occurrences
from src.ledger.contracts import parse_et_timestamp, parse_ibkr_date, stock_contract
from src.ledger.ingest import ingest
from src.ledger.state import LEDGER_FLEX_LAST_RUN_KEY, LEDGER_FLEX_LAST_STATUS_KEY
from src.storage.system_settings import set_setting

log = logging.getLogger(__name__)

_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
_RETRY_CODES = frozenset({"1018", "1019"})
_CASH_TYPES = {
    "Dividends": "dividend",
    "Payment In Lieu Of Dividends": "dividend",
    "Withholding Tax": "withholding",
    "Deposits/Withdrawals": "deposit",
    "Broker Interest Received": "interest",
    "Broker Interest Paid": "interest",
    "Other Fees": "fee",
    "Commission Adjustments": "fee",
}


class FlexError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Flex error {code}: {message}")
        self.code = code


def _response_error(text: str) -> tuple[str, str]:
    root = ElementTree.fromstring(text)
    return (root.findtext("ErrorCode") or "?").strip(), (
        root.findtext("ErrorMessage") or ""
    ).strip()


def fetch_statement(
    token: str,
    query_id: str,
    *,
    client: httpx.Client | None = None,
    poll_interval: float = 10.0,
    timeout: float = 600.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Request a statement and poll until IBKR has generated it. Returns the statement XML."""
    own = client is None
    http = client or httpx.Client(timeout=60.0, headers={"User-Agent": "ibkr-options-income/1.0"})
    try:
        r = http.get(f"{_BASE}/SendRequest", params={"t": token, "q": query_id, "v": "3"})
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        if (root.findtext("Status") or "").strip() != "Success":
            raise FlexError(*_response_error(r.text))
        reference = (root.findtext("ReferenceCode") or "").strip()
        url = (root.findtext("Url") or "").strip() or f"{_BASE}/GetStatement"
        deadline = clock() + timeout
        while True:
            r = http.get(url, params={"t": token, "q": reference, "v": "3"})
            r.raise_for_status()
            if "<FlexQueryResponse" in r.text:
                return r.text
            code, message = _response_error(r.text)
            if code not in _RETRY_CODES:
                raise FlexError(code, message)
            if clock() >= deadline:
                raise FlexError("timeout", f"statement not ready after {timeout:.0f}s")
            sleep(poll_interval)
    finally:
        if own:
            http.close()


def _float(el: ElementTree.Element, attr: str, default: float | None = None) -> float:
    raw = (el.get(attr) or "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"missing {attr}")
        return default
    return float(raw)


def _int_or_none(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() and int(raw) != 0 else None


def _merge_codes(notes: str, open_close: str) -> str:
    """Merge ``openCloseIndicator`` tokens into ``notes`` (controller ruling, Task 10).

    Flex ``<Trade>`` elements carry ``openCloseIndicator`` ("O", "C", or "C;O") separately
    from ``notes`` — but the reporting layer's pure-close rule
    (``src/reporting/trade_ledger.py``: an order is a pure close iff its codes contain "C" and
    not "O") reads ``codes`` alone. Append any ``openCloseIndicator`` token ``notes`` doesn't
    already carry, keeping ``notes``'s own token order first and deduping.
    """
    tokens = [t for t in notes.split(";") if t]
    seen = set(tokens)
    for t in (t for t in open_close.split(";") if t):
        if t not in seen:
            tokens.append(t)
            seen.add(t)
    return ";".join(tokens)


def _flex_trade(el: ElementTree.Element) -> ParsedExecution | None:
    category = el.get("assetCategory")
    if category not in ("STK", "OPT"):
        return None
    if el.get("levelOfDetail") not in (None, "", "EXECUTION"):
        return None
    currency = el.get("currency") or "USD"
    contract: LedgerContract
    if category == "OPT":
        right = el.get("putCall")
        contract = LedgerContract(
            underlying=el.get("underlyingSymbol") or (el.get("symbol") or "").split()[0],
            sec_type="OPT",
            currency=currency,
            right="P" if right == "P" else "C",
            strike=_float(el, "strike"),
            expiry=parse_ibkr_date(el.get("expiry") or ""),
            multiplier=_float(el, "multiplier", 100.0),
        )
    else:
        contract = stock_contract(el.get("symbol") or "", currency)
    exec_id = (el.get("ibExecID") or "").strip() or None
    realized = (el.get("fifoPnlRealized") or "").strip()
    codes = _merge_codes(
        (el.get("notes") or "").strip(), (el.get("openCloseIndicator") or "").strip()
    )
    return ParsedExecution(
        contract=contract,
        trade_time=parse_et_timestamp(el.get("dateTime") or el.get("tradeDate") or ""),
        quantity=_float(el, "quantity"),
        price=_float(el, "tradePrice"),
        proceeds=_float(el, "proceeds", 0.0),
        commission=_float(el, "ibCommission", 0.0),
        codes=codes,
        exec_id=exec_id,
        perm_id=_int_or_none(el.get("ibOrderID")),
        account=el.get("accountId"),
        ibkr_realized_pnl=float(realized) if realized else None,
        source_kind="exec" if exec_id else "order",
        raw=dict(el.attrib),
    )


def _flex_cash(el: ElementTree.Element) -> ParsedCashEvent | None:
    kind = _CASH_TYPES.get(el.get("type") or "")
    if kind is None or el.get("levelOfDetail") not in (None, "", "DETAIL"):
        return None
    amount = _float(el, "amount")
    if kind == "deposit" and amount < 0:
        kind = "withdrawal"
    when = (
        (el.get("settleDate") if kind in ("deposit", "withdrawal") else None)
        or el.get("dateTime")
        or ""
    )
    return ParsedCashEvent(
        event_type=kind,  # type: ignore[arg-type]
        event_date=parse_ibkr_date(when.split(";")[0]),
        currency=el.get("currency") or "USD",
        amount=amount,
        description=(el.get("description") or "").strip(),
        underlying=(el.get("symbol") or None) if kind in ("dividend", "withholding") else None,
    )


def _flex_fx(root: ElementTree.Element) -> list[ParsedFxRate]:
    by_day: dict[str, dict[str, tuple[str, float]]] = defaultdict(dict)
    for el in root.iter("ConversionRate"):
        day, frm, to, rate = (
            el.get("reportDate"),
            el.get("fromCurrency"),
            el.get("toCurrency"),
            el.get("rate"),
        )
        if day and frm and to and rate:
            by_day[day][frm] = (to, float(rate))
    out: list[ParsedFxRate] = []
    for day, rates in by_day.items():
        if "USD" not in rates:
            continue
        base, usd_to_base = rates["USD"]
        d = parse_ibkr_date(day)
        out.append(ParsedFxRate(rate_date=d, currency=base, usd_rate=1.0 / usd_to_base))
        for currency, (_, fx_rate) in rates.items():
            if currency not in ("USD", base):
                out.append(
                    ParsedFxRate(rate_date=d, currency=currency, usd_rate=fx_rate / usd_to_base)
                )
    return out


def parse_flex_xml(text: str) -> ParsedStatement:
    root = ElementTree.fromstring(text)
    st = ParsedStatement()
    stmt = root.find(".//FlexStatement")
    if stmt is not None:
        st.account = stmt.get("accountId")
        st.period_start = (
            parse_ibkr_date(stmt.get("fromDate") or "") if stmt.get("fromDate") else None
        )
        st.period_end = parse_ibkr_date(stmt.get("toDate") or "") if stmt.get("toDate") else None
    for i, el in enumerate(root.iter("Trade"), start=1):
        try:
            e = _flex_trade(el)
            if e is not None:
                st.executions.append(e)
        except (ValueError, KeyError, TypeError) as exc:
            st.errors.append(LedgerParseError(line=i, section="Trades", message=str(exc)))
    for i, el in enumerate(root.iter("CashTransaction"), start=1):
        try:
            c = _flex_cash(el)
            if c is not None:
                st.cash_events.append(c)
        except (ValueError, KeyError, TypeError) as exc:
            st.errors.append(LedgerParseError(line=i, section="CashTransactions", message=str(exc)))
    for el in root.iter("CorporateAction"):
        try:
            st.corporate_actions.append(
                ParsedCorporateAction(
                    event_date=parse_ibkr_date((el.get("reportDate") or "").split(";")[0]),
                    underlying=el.get("underlyingSymbol") or el.get("symbol") or None,
                    description=(el.get("description") or "").strip(),
                    quantity=_float(el, "quantity", 0.0),
                    proceeds=_float(el, "proceeds", 0.0),
                    raw=dict(el.attrib),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            st.errors.append(LedgerParseError(line=0, section="CorporateActions", message=str(exc)))
    st.fx_rates = _flex_fx(root)
    number_occurrences(st)
    return st


def run_flex_pull(
    *, query_id: str | None = None, dry_run: bool = False
) -> LedgerImportResult | ParsedStatement | None:
    """Fetch, parse and ingest one Flex statement. None when Flex isn't configured."""
    cfg = get_config()
    token = cfg.secrets.ibkr_flex_token.strip()
    qid = (query_id or cfg.secrets.ibkr_flex_query_id).strip()
    if not token or not qid:
        log.warning("Flex pull skipped: IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID not set")
        return None
    now = datetime.now(UTC).isoformat()
    try:
        xml = fetch_statement(
            token,
            qid,
            poll_interval=cfg.ledger.flex_poll_interval_seconds,
            timeout=cfg.ledger.flex_poll_timeout_seconds,
        )
    except (FlexError, httpx.HTTPError) as exc:
        set_setting(LEDGER_FLEX_LAST_RUN_KEY, now)
        set_setting(LEDGER_FLEX_LAST_STATUS_KEY, f"failed: {exc}"[:200])
        raise
    statement = parse_flex_xml(xml)
    if dry_run:
        return statement
    result = ingest(statement, source="flex", filename=f"flex:{qid}")
    set_setting(LEDGER_FLEX_LAST_RUN_KEY, now)
    set_setting(
        LEDGER_FLEX_LAST_STATUS_KEY,
        "ok" if result.status == "ok" else f"failed: {result.reason}",
    )
    return result
