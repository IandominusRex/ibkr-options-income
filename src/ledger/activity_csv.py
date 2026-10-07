"""IBKR Activity Statement CSV -> ParsedStatement (spec §5.1; revisions R1, R2, R7, R11).

The file is multi-section: column 0 is the section name, column 1 is Header/Data/SubTotal/
Total/Notes. A section can carry several Header rows (Trades has one per asset class), every
Data row is zipped against the most recent Header for its section. Rows are ORDER-level
(DataDiscriminator "Order"), never execution-level — they carry no execId (R2).
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from src.common.schemas import (
    LedgerContract,
    LedgerParseError,
    ParsedCashEvent,
    ParsedCorporateAction,
    ParsedExecution,
    ParsedFxRate,
    ParsedStatement,
)
from src.ledger.contracts import (
    et_date,
    parse_et_timestamp,
    parse_ibkr_date,
    parse_number,
    parse_option_symbol,
    stock_contract,
)

_TICKER_PREFIX = re.compile(r"^([A-Z0-9.]+)\(")
_PERIOD = re.compile(r"^(?P<a>[A-Za-z]+ \d{1,2}, \d{4}) - (?P<b>[A-Za-z]+ \d{1,2}, \d{4})$")
_OPTION_CATEGORY = "Equity and Index Options"


class NotAnActivityStatement(ValueError):
    """The text is not an IBKR Activity Statement CSV (wrong file, or a PDF)."""


class _Acc:
    def __init__(self) -> None:
        self.st = ParsedStatement()
        self.pending_options: list[tuple[str, dict[str, str], int]] = []
        self.multipliers: dict[str, float] = {}
        self.is_activity_statement = False


Handler = Callable[["_Acc", dict[str, str], int], None]


def _optional_number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return parse_number(value)


def _underlying_from(description: str) -> str | None:
    m = _TICKER_PREFIX.match(description.strip())
    return m.group(1) if m else None


def _is_total(rec: dict[str, str], key: str) -> bool:
    return rec.get(key, "").strip().startswith("Total")


def _statement(acc: _Acc, rec: dict[str, str], line: int) -> None:
    name, value = rec.get("Field Name", ""), rec.get("Field Value", "").strip()
    if name == "Title" and value == "Activity Statement":
        acc.is_activity_statement = True
    elif name == "Period":
        m = _PERIOD.match(value)
        if m:
            acc.st.period_start = datetime.strptime(m["a"], "%B %d, %Y").date()
            acc.st.period_end = datetime.strptime(m["b"], "%B %d, %Y").date()


def _account_info(acc: _Acc, rec: dict[str, str], line: int) -> None:
    name, value = rec.get("Field Name", ""), rec.get("Field Value", "").strip()
    if name == "Account":
        acc.st.account = value
    elif name == "Base Currency":
        acc.st.base_currency = value


def _execution(contract: LedgerContract, rec: dict[str, str]) -> ParsedExecution:
    return ParsedExecution(
        contract=contract,
        trade_time=parse_et_timestamp(rec["Date/Time"]),
        quantity=parse_number(rec["Quantity"]),
        price=parse_number(rec["T. Price"]),
        proceeds=parse_number(rec["Proceeds"]),
        commission=_optional_number(rec.get("Comm/Fee")) or 0.0,
        codes=rec.get("Code", "").strip(),
        ibkr_realized_pnl=_optional_number(rec.get("Realized P/L")),
        source_kind="order",
        raw=dict(rec),
    )


def _forex(acc: _Acc, rec: dict[str, str]) -> None:
    pair = rec.get("Symbol", "")
    if "." not in pair:
        return
    base, quote = pair.split(".", 1)
    price = parse_number(rec["T. Price"])
    day = et_date(parse_et_timestamp(rec["Date/Time"]))
    if base == "USD" and price > 0:
        acc.st.fx_rates.append(ParsedFxRate(rate_date=day, currency=quote, usd_rate=1.0 / price))
    elif quote == "USD":
        acc.st.fx_rates.append(ParsedFxRate(rate_date=day, currency=base, usd_rate=price))


def _trade(acc: _Acc, rec: dict[str, str], line: int) -> None:
    if rec.get("DataDiscriminator") != "Order":
        return
    asset = rec.get("Asset Category", "")
    if asset == "Forex":
        _forex(acc, rec)
    elif asset == _OPTION_CATEGORY:
        # Multipliers live in "Financial Instrument Information", which comes AFTER Trades in
        # the file — options are finalised once the whole file has been read.
        acc.pending_options.append((rec["Symbol"], rec, line))
    elif asset == "Stocks":
        acc.st.executions.append(_execution(stock_contract(rec["Symbol"], rec["Currency"]), rec))
    else:
        acc.st.errors.append(
            LedgerParseError(
                line=line,
                section="Trades:unsupported",
                message=f"asset category {asset!r} not imported",
            )
        )


def _cash(event_type: str, date_key: str = "Date") -> Handler:
    def handler(acc: _Acc, rec: dict[str, str], line: int) -> None:
        if _is_total(rec, "Currency") or not rec.get(date_key, "").strip():
            return
        amount = parse_number(rec["Amount"])
        kind = "withdrawal" if event_type == "deposit" and amount < 0 else event_type
        description = rec.get("Description", "").strip()
        acc.st.cash_events.append(
            ParsedCashEvent(
                event_type=kind,  # type: ignore[arg-type]
                event_date=parse_ibkr_date(rec[date_key]),
                currency=rec["Currency"].strip(),
                amount=amount,
                description=description,
                underlying=_underlying_from(description)
                if kind in ("dividend", "withholding")
                else None,
            )
        )

    return handler


def _corporate_action(acc: _Acc, rec: dict[str, str], line: int) -> None:
    if _is_total(rec, "Asset Category"):
        return
    description = rec.get("Description", "").strip()
    acc.st.corporate_actions.append(
        ParsedCorporateAction(
            event_date=parse_ibkr_date(rec["Report Date"]),
            underlying=_underlying_from(description),
            description=description,
            quantity=_optional_number(rec.get("Quantity")) or 0.0,
            proceeds=_optional_number(rec.get("Proceeds")) or 0.0,
            raw=dict(rec),
        )
    )


def _instrument(acc: _Acc, rec: dict[str, str], line: int) -> None:
    if rec.get("Asset Category") != _OPTION_CATEGORY:
        return
    mult = _optional_number(rec.get("Multiplier"))
    if mult:
        acc.multipliers[rec.get("Description", "").strip()] = mult


_HANDLERS: dict[str, Handler] = {
    "Statement": _statement,
    "Account Information": _account_info,
    "Trades": _trade,
    "Dividends": _cash("dividend"),
    "Withholding Tax": _cash("withholding"),
    "Deposits & Withdrawals": _cash("deposit", date_key="Settle Date"),
    "Fees": _cash("fee"),
    "Interest": _cash("interest"),
    "Corporate Actions": _corporate_action,
    "Financial Instrument Information": _instrument,
}


def number_occurrences(st: ParsedStatement) -> None:
    """Distinguish genuinely identical rows within one file so both survive dedupe (R2)."""
    seen: Counter[tuple[object, ...]] = Counter()
    for e in st.executions:
        sig: tuple[object, ...] = ("x", e.contract.ident, e.trade_time, e.quantity, e.price)
        e.occurrence_idx = seen[sig]
        seen[sig] += 1
    for c in st.cash_events:
        sig = ("c", c.event_type, c.event_date, c.currency, round(c.amount, 2), c.underlying)
        c.occurrence_idx = seen[sig]
        seen[sig] += 1
    for a in st.corporate_actions:
        sig = ("a", a.event_date, a.description)
        a.occurrence_idx = seen[sig]
        seen[sig] += 1


def parse_activity_csv(text: str) -> ParsedStatement:
    """Parse an Activity Statement. Raises NotAnActivityStatement for a PDF or a foreign CSV."""
    body = text.lstrip("﻿")
    if body.lstrip().startswith("%PDF"):
        raise NotAnActivityStatement("PDF statements aren't supported; download the CSV version")
    acc = _Acc()
    headers: dict[str, list[str]] = {}
    for line_no, row in enumerate(csv.reader(io.StringIO(body)), start=1):
        if len(row) < 2:
            continue
        section, kind = row[0].lstrip("﻿"), row[1]
        if kind == "Header":
            headers[section] = row[2:]
            continue
        if kind != "Data" or section not in _HANDLERS or section not in headers:
            continue
        rec = dict(zip(headers[section], row[2:], strict=False))
        try:
            _HANDLERS[section](acc, rec, line_no)
        except (ValueError, KeyError) as exc:
            acc.st.errors.append(LedgerParseError(line=line_no, section=section, message=str(exc)))
    if not acc.is_activity_statement:
        raise NotAnActivityStatement("missing the 'Statement / Title / Activity Statement' row")
    for symbol, rec, line_no in acc.pending_options:
        try:
            contract = parse_option_symbol(
                symbol,
                currency=rec["Currency"].strip(),
                multiplier=acc.multipliers.get(symbol.strip(), 100.0),
            )
            acc.st.executions.append(_execution(contract, rec))
        except (ValueError, KeyError) as exc:
            acc.st.errors.append(LedgerParseError(line=line_no, section="Trades", message=str(exc)))
    number_occurrences(acc.st)
    return acc.st
