# Milestone 3 — Fundamentals Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** EDGAR XBRL becomes normalised financial statements rendering on a ticker page, with
every figure traceable to the filing it came from.

**Spec:** `Web plan/P0-P1-design.md` §5.3, §5.4, §5.5. **Index:** `Web plan/P0-P1-IMPLEMENTATION-PLAN.md`.

**Depends on:** Milestone 2 complete.

**This is the largest and highest-risk milestone.** Five of its eight tasks are Sonnet, because
the failure mode here is *silent wrongness*: a revenue figure that is quietly the wrong concept,
or a restated number that quietly reverted, looks completely normal on screen.

---

## Reference: the EDGAR companyfacts shape

`https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json`

```json
{
  "cik": 320193,
  "entityName": "Apple Inc.",
  "facts": {
    "us-gaap": {
      "Revenues": {
        "label": "Revenues",
        "units": {
          "USD": [
            {"start": "2019-09-29", "end": "2020-09-26", "val": 274515000000,
             "accn": "0000320193-20-000096", "fy": 2020, "fp": "FY",
             "form": "10-K", "filed": "2020-10-30", "frame": "CY2020"}
          ]
        }
      },
      "Assets": {
        "units": {"USD": [
          {"end": "2020-09-26", "val": 323888000000, "accn": "...", "fy": 2020,
           "fp": "FY", "form": "10-K", "filed": "2020-10-30"}
        ]}
      }
    }
  }
}
```

**Two fact kinds, and conflating them is the classic bug:**
- **Duration facts** carry `start` and `end`. Income statement and cash flow.
- **Instant facts** carry only `end`. Balance sheet.

Asking for "annual revenue" and accepting an instant fact, or asking for "total assets" and
summing four durations, produces plausible nonsense.

---

## File structure

| File | Responsibility |
|---|---|
| `config/research_concepts.yaml` | Canonical line item to us-gaap concept map |
| `src/research/ingest/concepts.py` | Fact parsing, concept resolution, period selection |
| `src/research/ingest/fundamentals.py` | Orchestration: fetch, normalise, persist |
| `src/research/schemas.py` | `Fact`, `LineItemValue`, `NormalizedFinancials` |
| `src/api/models/research.py` | `Section[T]`, `AnalysisResponse` |
| `src/api/routers/research.py` | `GET /research/{symbol}` |
| `web/app/stock/[symbol]/page.tsx` | Ticker page |
| `web/components/stock/StatementsTable.tsx` | Statements with filing traceability |

---

## Task 3.1 — `FilingsProvider` and company facts `[SONNET]`

Sonnet: external data variance and the failure modes of a 20MB JSON document.

**Files:**
- Modify: `src/data/protocols.py`, `src/data/factory.py`, `src/data/edgar_backend.py`
- Test: `tests/test_edgar_companyfacts.py`

**Interfaces:**
- Consumes: `EdgarClient` (2.2).
- Produces:
  - `FilingsProvider` Protocol with
    `get_company_facts(cik: str) -> dict` (empty dict when unavailable, never raises)
  - `EdgarFilingsProvider`
  - `get_filings_provider() -> FilingsProvider`
  - `COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"`

- [x] **Step 1: Write the failing test**

Create `tests/test_edgar_companyfacts.py`:

```python
"""Company facts: CIK padding, ETag reuse, and fail-soft behaviour."""

from __future__ import annotations

import httpx
import pytest

from src.data.edgar_backend import EdgarClient, EdgarFilingsProvider

_FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"end": "2024-09-28", "val": 1}]}}}},
}


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr("src.data.edgar_backend._contact_email", lambda: "t@example.com")


def test_requests_a_zero_padded_cik() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_FACTS)

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    p.get_company_facts("320193")
    assert "CIK0000320193.json" in seen[0]


def test_already_padded_cik_is_not_double_padded() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_FACTS)

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    p.get_company_facts("0000320193")
    assert "CIK0000320193.json" in seen[0]


def test_returns_the_payload() -> None:
    p = EdgarFilingsProvider(
        client=EdgarClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_FACTS)))
    )
    assert p.get_company_facts("320193")["entityName"] == "Apple Inc."


def test_returns_empty_dict_on_404_rather_than_raising() -> None:
    """Not every filer has XBRL facts. A missing document degrades the page, not the request."""
    p = EdgarFilingsProvider(
        client=EdgarClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(404)), max_retries=0
        )
    )
    assert p.get_company_facts("320193") == {}


def test_blank_cik_short_circuits_without_a_request() -> None:
    called = False

    def handler(_r: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_FACTS)

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    assert p.get_company_facts("") == {}
    assert called is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_edgar_companyfacts.py -v`
Expected: FAIL with `ImportError: cannot import name 'EdgarFilingsProvider'`

- [x] **Step 3: Add the Protocol to `src/data/protocols.py`**

```python
@runtime_checkable
class FilingsProvider(Protocol):
    """XBRL company facts for one filer, keyed by CIK."""

    def get_company_facts(self, cik: str) -> dict:
        """Return the backend's full XBRL fact document for *cik*.

        Empty dict when unavailable (no XBRL, 404, throttled). Never raises.
        """
        ...
```

- [x] **Step 4: Add the backend to `src/data/edgar_backend.py`**

```python
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class EdgarFilingsProvider:
    """XBRL company facts. One document per filer, sometimes tens of megabytes."""

    def __init__(self, client: EdgarClient | None = None) -> None:
        self._client = client or EdgarClient()

    def get_company_facts(self, cik: str) -> dict:
        cik = (cik or "").strip()
        if not cik:
            return {}
        payload, _ = self._client.get_json(COMPANYFACTS_URL.format(cik=cik.zfill(10)))
        return payload or {}
```

- [x] **Step 5: Add the factory getter to `src/data/factory.py`**

```python
def _make_filings_provider(name: str) -> FilingsProvider:
    if name == "edgar":
        from src.data.edgar_backend import EdgarFilingsProvider

        return EdgarFilingsProvider()
    raise ValueError(f"Unknown data.filings_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_filings_provider() -> FilingsProvider:
    """Return the active :class:`FilingsProvider` (cached process-wide)."""
    return _make_filings_provider(get_config().data.filings_provider)
```

- [x] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_edgar_companyfacts.py -v && ruff check . && mypy src`
Expected: 5 passed.

- [x] **Step 7: Commit**

```bash
git add src/data tests/test_edgar_companyfacts.py
git commit -m "feat(data): add EDGAR company-facts provider"
```

---

## Task 3.2 — Concept map and resolution `[SONNET]`

Sonnet: this is the single highest-value correctness surface in P1. Filers disagree about which
us-gaap concept means "revenue", and picking the wrong one produces a number that looks fine and
is wrong.

**Files:**
- Create: `config/research_concepts.yaml`, `src/research/schemas.py`,
  `src/research/ingest/concepts.py`
- Test: `tests/test_research_concepts.py`, `tests/fixtures/edgar/`

**Interfaces:**
- Produces:
  - `Fact` (dataclass): `value: float`, `unit: str`, `start: date | None`, `end: date`,
    `accn: str`, `fy: int | None`, `fp: str | None`, `form: str`, `filed: date`
  - `LineItemSpec` (Pydantic): `statement: str`, `kind: str` (`duration`|`instant`),
    `units: list[str]`, `concepts: list[str]`
  - `load_concept_map() -> dict[str, LineItemSpec]` (cached)
  - `parse_facts(payload: dict, concept: str, units: list[str]) -> list[Fact]`
  - `resolve_line_item(payload: dict, spec: LineItemSpec) -> tuple[str, list[Fact]] | None`

- [x] **Step 1: Write the failing test**

Create `tests/test_research_concepts.py`:

```python
"""Concept resolution: the ordered-candidate map, and honest failure when nothing matches."""

from __future__ import annotations

from datetime import date

from src.research.ingest.concepts import (
    LineItemSpec,
    load_concept_map,
    parse_facts,
    resolve_line_item,
)


def _payload(concepts: dict) -> dict:
    return {"cik": 1, "entityName": "Test", "facts": {"us-gaap": concepts}}


_REVENUE_SPEC = LineItemSpec(
    statement="income",
    kind="duration",
    units=["USD"],
    concepts=[
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
)


def test_parse_facts_reads_duration_facts() -> None:
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 1000.0,
                            "accn": "acc-1",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            }
        }
    )
    facts = parse_facts(payload, "Revenues", ["USD"])
    assert len(facts) == 1
    assert facts[0].value == 1000.0
    assert facts[0].start == date(2023, 1, 1)
    assert facts[0].end == date(2023, 12, 31)
    assert facts[0].filed == date(2024, 2, 1)


def test_parse_facts_reads_instant_facts_with_no_start() -> None:
    payload = _payload(
        {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "end": "2023-12-31",
                            "val": 5000.0,
                            "accn": "acc-1",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            }
        }
    )
    facts = parse_facts(payload, "Assets", ["USD"])
    assert facts[0].start is None
    assert facts[0].end == date(2023, 12, 31)


def test_parse_facts_ignores_unrequested_units() -> None:
    """A share count reported in USD, or a value in EUR, is not what we asked for."""
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "EUR": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 900.0,
                         "accn": "a", "form": "10-K", "filed": "2024-02-01"}
                    ]
                }
            }
        }
    )
    assert parse_facts(payload, "Revenues", ["USD"]) == []


def test_parse_facts_skips_malformed_entries_without_failing_the_rest() -> None:
    payload = _payload(
        {
            "Revenues": {
                "units": {
                    "USD": [
                        {"start": "2023-01-01", "end": "bogus-date", "val": 1.0,
                         "accn": "a", "form": "10-K", "filed": "2024-02-01"},
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 2.0,
                         "accn": "b", "form": "10-K", "filed": "2024-02-01"},
                        {"start": "2023-01-01", "end": "2023-12-31", "val": None,
                         "accn": "c", "form": "10-K", "filed": "2024-02-01"},
                    ]
                }
            }
        }
    )
    facts = parse_facts(payload, "Revenues", ["USD"])
    assert [f.value for f in facts] == [2.0]


def test_resolve_takes_the_first_candidate_that_has_facts() -> None:
    payload = _payload(
        {
            "Revenues": {
                "units": {"USD": [
                    {"start": "2023-01-01", "end": "2023-12-31", "val": 10.0,
                     "accn": "a", "form": "10-K", "filed": "2024-02-01"}
                ]}
            },
            "SalesRevenueNet": {
                "units": {"USD": [
                    {"start": "2023-01-01", "end": "2023-12-31", "val": 20.0,
                     "accn": "a", "form": "10-K", "filed": "2024-02-01"}
                ]}
            },
        }
    )
    resolved = resolve_line_item(payload, _REVENUE_SPEC)
    assert resolved is not None
    concept, facts = resolved
    # RevenueFromContractWithCustomer... is absent, so Revenues wins over SalesRevenueNet.
    assert concept == "Revenues"
    assert facts[0].value == 10.0


def test_resolve_prefers_the_earliest_listed_candidate() -> None:
    payload = _payload(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [
                    {"start": "2023-01-01", "end": "2023-12-31", "val": 99.0,
                     "accn": "a", "form": "10-K", "filed": "2024-02-01"}
                ]}
            },
            "Revenues": {
                "units": {"USD": [
                    {"start": "2023-01-01", "end": "2023-12-31", "val": 10.0,
                     "accn": "a", "form": "10-K", "filed": "2024-02-01"}
                ]}
            },
        }
    )
    concept, facts = resolve_line_item(payload, _REVENUE_SPEC)  # type: ignore[misc]
    assert concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert facts[0].value == 99.0


def test_resolve_returns_none_when_no_candidate_matches() -> None:
    """Honest absence. The caller renders UNKNOWN rather than a zero."""
    assert resolve_line_item(_payload({"SomethingElse": {"units": {}}}), _REVENUE_SPEC) is None


def test_resolve_handles_a_payload_with_no_us_gaap_taxonomy() -> None:
    """Many ETFs and foreign filers have no us-gaap facts at all."""
    assert resolve_line_item({"facts": {"dei": {}}}, _REVENUE_SPEC) is None
    assert resolve_line_item({}, _REVENUE_SPEC) is None


def test_shipped_concept_map_covers_the_core_line_items() -> None:
    m = load_concept_map()
    required = {
        "revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
        "total_assets", "total_liabilities", "stockholders_equity",
        "current_assets", "current_liabilities", "long_term_debt", "cash_and_equivalents",
        "operating_cash_flow", "capital_expenditure", "shares_diluted",
    }
    assert required <= set(m)
    for name, spec in m.items():
        assert spec.kind in {"duration", "instant"}, name
        assert spec.concepts, name
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_concepts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research.ingest.concepts'`

- [x] **Step 3: Create `config/research_concepts.yaml`**

```yaml
# Canonical line item -> ordered us-gaap concept candidates. First candidate with facts wins.
#
# Filers disagree about which concept means the same thing. Adding a mapping here is a config
# change, not a code change, which matters because the long tail of filers is where this breaks.
#
# kind:
#   duration - the fact carries start AND end (income statement, cash flow)
#   instant  - the fact carries only end (balance sheet)
# Getting kind wrong produces plausible nonsense, so it is required on every entry.

line_items:
  revenue:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - RevenueFromContractWithCustomerExcludingAssessedTax
      - Revenues
      - SalesRevenueNet
      - RevenueFromContractWithCustomerIncludingAssessedTax

  cost_of_revenue:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - CostOfRevenue
      - CostOfGoodsAndServicesSold
      - CostOfGoodsSold

  gross_profit:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - GrossProfit

  operating_income:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - OperatingIncomeLoss

  net_income:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - NetIncomeLoss
      - ProfitLoss
      - NetIncomeLossAvailableToCommonStockholdersBasic

  eps_diluted:
    statement: income
    kind: duration
    units: ["USD/shares"]
    concepts:
      - EarningsPerShareDiluted
      - EarningsPerShareBasicAndDiluted

  shares_diluted:
    statement: income
    kind: duration
    units: [shares]
    concepts:
      - WeightedAverageNumberOfDilutedSharesOutstanding
      - WeightedAverageNumberOfSharesOutstandingBasic

  total_assets:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - Assets

  total_liabilities:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - Liabilities

  stockholders_equity:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - StockholdersEquity
      - StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest

  current_assets:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - AssetsCurrent

  current_liabilities:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - LiabilitiesCurrent

  long_term_debt:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - LongTermDebtNoncurrent
      - LongTermDebt

  cash_and_equivalents:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - CashAndCashEquivalentsAtCarryingValue
      - CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents

  operating_cash_flow:
    statement: cash_flow
    kind: duration
    units: [USD]
    concepts:
      - NetCashProvidedByUsedInOperatingActivities
      - NetCashProvidedByUsedInOperatingActivitiesContinuingOperations

  capital_expenditure:
    statement: cash_flow
    kind: duration
    units: [USD]
    concepts:
      - PaymentsToAcquirePropertyPlantAndEquipment
      - PaymentsToAcquireProductiveAssets

  dividends_paid:
    statement: cash_flow
    kind: duration
    units: [USD]
    concepts:
      - PaymentsOfDividendsCommonStock
      - PaymentsOfDividends
```

- [x] **Step 4: Create `src/research/schemas.py`**

```python
"""Shapes the research layer passes between its own modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Fact:
    """One XBRL fact. `start` is None for instant (balance-sheet) facts."""

    value: float
    unit: str
    start: date | None
    end: date
    accn: str
    fy: int | None
    fp: str | None
    form: str
    filed: date


class LineItemValue(BaseModel):
    """One normalised line item for one period, traceable to its filing."""

    line_item: str
    value: float | None
    concept: str | None = None
    accn: str | None = None
    filed: date | None = None
    form: str | None = None


class PeriodStatement(BaseModel):
    """Every line item for one reporting period."""

    period_end: date
    period_type: str  # "annual" | "quarterly"
    items: dict[str, LineItemValue]


class NormalizedFinancials(BaseModel):
    symbol: str
    cik: str
    entity_name: str = ""
    annual: list[PeriodStatement] = []
    quarterly: list[PeriodStatement] = []
```

- [x] **Step 5: Implement `src/research/ingest/concepts.py` (parsing and resolution only)**

```python
"""XBRL fact parsing and concept resolution.

EDGAR returns facts tagged with us-gaap concepts, and filers disagree about which concept
means the same thing. Without normalisation a comparison between two companies is
meaningless. The map is config (config/research_concepts.yaml), so a missing mapping is a
config fix rather than a code change.
"""

from __future__ import annotations

import functools
import logging
from datetime import date, datetime

import yaml
from pydantic import BaseModel, field_validator

from src.common.config import CONFIG_DIR
from src.research.schemas import Fact

log = logging.getLogger(__name__)


class LineItemSpec(BaseModel):
    statement: str            # income | balance | cash_flow
    kind: str                 # duration | instant
    units: list[str]
    concepts: list[str]

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in {"duration", "instant"}:
            raise ValueError(f"kind must be 'duration' or 'instant', got {v!r}")
        return v


@functools.lru_cache(maxsize=1)
def load_concept_map() -> dict[str, LineItemSpec]:
    """Load and cache the canonical line item map."""
    path = CONFIG_DIR / "research_concepts.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {name: LineItemSpec(**spec) for name, spec in (raw.get("line_items") or {}).items()}


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_facts(payload: dict, concept: str, units: list[str]) -> list[Fact]:
    """Every well-formed fact for `concept` in one of `units`.

    Malformed entries are skipped individually. One bad date in a filer's history must not
    cost us the other forty facts.
    """
    try:
        unit_map = payload["facts"]["us-gaap"][concept]["units"]
    except (KeyError, TypeError):
        return []

    facts: list[Fact] = []
    for unit in units:
        for entry in unit_map.get(unit, []) or []:
            end = _parse_date(entry.get("end"))
            filed = _parse_date(entry.get("filed"))
            value = entry.get("val")
            if end is None or filed is None or not isinstance(value, int | float):
                continue
            facts.append(
                Fact(
                    value=float(value),
                    unit=unit,
                    start=_parse_date(entry.get("start")),
                    end=end,
                    accn=str(entry.get("accn") or ""),
                    fy=entry.get("fy") if isinstance(entry.get("fy"), int) else None,
                    fp=str(entry["fp"]) if entry.get("fp") else None,
                    form=str(entry.get("form") or ""),
                    filed=filed,
                )
            )
    return facts


def resolve_line_item(payload: dict, spec: LineItemSpec) -> tuple[str, list[Fact]] | None:
    """First candidate concept that actually has facts. None when none do.

    None is the honest answer for a filer that reports nothing we recognise, and the caller
    renders UNKNOWN rather than a zero.
    """
    for concept in spec.concepts:
        facts = parse_facts(payload, concept, spec.units)
        if facts:
            return concept, facts
    return None
```

- [x] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_concepts.py -v && ruff check . && mypy src`
Expected: 9 passed.

- [x] **Step 7: Update the docs**

`ARCHITECTURE.md` config section gains `config/research_concepts.yaml` with a note that adding
a mapping is a config change.

- [x] **Step 8: Commit**

```bash
git add config/research_concepts.yaml src/research tests/test_research_concepts.py ARCHITECTURE.md
git commit -m "feat(research): add XBRL concept map and fact resolution"
```

---

## Task 3.3 — Period selection and restatements `[SONNET]`

Sonnet: the subtlest correctness surface in the milestone. A restated figure that silently
reverts to the original looks completely normal.

**Files:**
- Modify: `src/research/ingest/concepts.py` (append the selectors)
- Test: `tests/test_research_periods.py`

**Interfaces:**
- Produces:
  - `select_periods(facts: list[Fact], *, kind: str, period_type: str, limit: int) -> list[Fact]`
  - Annual duration facts: 300 to 400 days long. Quarterly: 60 to 120 days.
  - Instant facts: annual takes 10-K filings, quarterly takes any form.
  - Ties on `end` are broken by the **latest `filed`**, which is how restatements win.

- [x] **Step 1: Write the failing test**

Create `tests/test_research_periods.py`:

```python
"""Period selection: duration windows, instant handling, and restatement precedence."""

from __future__ import annotations

from datetime import date

from src.research.ingest.concepts import select_periods
from src.research.schemas import Fact


def _fact(
    *, start: date | None, end: date, val: float, filed: date, form: str = "10-K", accn: str = "a"
) -> Fact:
    return Fact(
        value=val, unit="USD", start=start, end=end, accn=accn,
        fy=end.year, fp="FY", form=form, filed=filed,
    )


def test_annual_duration_keeps_only_year_length_windows() -> None:
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1)),
        # a quarter, which must not be mistaken for a year
        _fact(start=date(2023, 10, 1), end=date(2023, 12, 31), val=25, filed=date(2024, 2, 1)),
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert [f.value for f in out] == [100]


def test_quarterly_duration_keeps_only_quarter_length_windows() -> None:
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1)),
        _fact(start=date(2023, 10, 1), end=date(2023, 12, 31), val=25, filed=date(2024, 2, 1),
              form="10-Q"),
    ]
    out = select_periods(facts, kind="duration", period_type="quarterly", limit=8)
    assert [f.value for f in out] == [25]


def test_a_restated_value_wins_over_the_original() -> None:
    """Same period, two filings. The later filing is the correct current answer."""
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100,
              filed=date(2024, 2, 1), accn="original"),
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=94,
              filed=date(2025, 2, 1), accn="restated"),
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert len(out) == 1
    assert out[0].value == 94
    assert out[0].accn == "restated"


def test_periods_are_returned_newest_first() -> None:
    facts = [
        _fact(start=date(2022, 1, 1), end=date(2022, 12, 31), val=1, filed=date(2023, 2, 1)),
        _fact(start=date(2024, 1, 1), end=date(2024, 12, 31), val=3, filed=date(2025, 2, 1)),
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=2, filed=date(2024, 2, 1)),
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert [f.value for f in out] == [3, 2, 1]


def test_limit_truncates_to_the_most_recent_periods() -> None:
    facts = [
        _fact(start=date(y, 1, 1), end=date(y, 12, 31), val=y, filed=date(y + 1, 2, 1))
        for y in (2019, 2020, 2021, 2022, 2023, 2024)
    ]
    out = select_periods(facts, kind="duration", period_type="annual", limit=5)
    assert [f.value for f in out] == [2024, 2023, 2022, 2021, 2020]


def test_instant_annual_takes_only_annual_report_forms() -> None:
    facts = [
        _fact(start=None, end=date(2023, 12, 31), val=500, filed=date(2024, 2, 1), form="10-K"),
        _fact(start=None, end=date(2023, 9, 30), val=480, filed=date(2023, 11, 1), form="10-Q"),
    ]
    out = select_periods(facts, kind="instant", period_type="annual", limit=5)
    assert [f.value for f in out] == [500]


def test_instant_quarterly_accepts_any_form() -> None:
    facts = [
        _fact(start=None, end=date(2023, 12, 31), val=500, filed=date(2024, 2, 1), form="10-K"),
        _fact(start=None, end=date(2023, 9, 30), val=480, filed=date(2023, 11, 1), form="10-Q"),
    ]
    out = select_periods(facts, kind="instant", period_type="quarterly", limit=8)
    assert [f.value for f in out] == [500, 480]


def test_duration_facts_are_rejected_when_instant_was_asked_for() -> None:
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1))
    ]
    assert select_periods(facts, kind="instant", period_type="annual", limit=5) == []


def test_instant_facts_are_rejected_when_duration_was_asked_for() -> None:
    facts = [_fact(start=None, end=date(2023, 12, 31), val=100, filed=date(2024, 2, 1))]
    assert select_periods(facts, kind="duration", period_type="annual", limit=5) == []


def test_empty_input_is_empty_output() -> None:
    assert select_periods([], kind="duration", period_type="annual", limit=5) == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_periods.py -v`
Expected: FAIL with `ImportError: cannot import name 'select_periods'`

- [x] **Step 3: Append to `src/research/ingest/concepts.py`**

```python
# Duration windows, in days. Filers' fiscal years and quarters are not exactly 365/91 days,
# so these are ranges rather than equalities.
_ANNUAL_DAYS = (300, 400)
_QUARTER_DAYS = (60, 120)

# Forms that carry annual balance-sheet positions.
_ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F"}


def select_periods(
    facts: list[Fact],
    *,
    kind: str,
    period_type: str,
    limit: int,
) -> list[Fact]:
    """Pick one fact per reporting period, newest first.

    Two rules carry the correctness of this function:

    1. `kind` is enforced. A duration fact can never satisfy an instant line item and vice
       versa. Summing four quarterly durations into "total assets", or reading an instant as
       a year of revenue, produces plausible nonsense.
    2. When two filings report the same period, the one filed LATER wins. That is how a
       restatement becomes the current answer instead of silently reverting.
    """
    if kind == "duration":
        lo, hi = _ANNUAL_DAYS if period_type == "annual" else _QUARTER_DAYS
        candidates = [
            f for f in facts if f.start is not None and lo <= (f.end - f.start).days <= hi
        ]
    elif kind == "instant":
        candidates = [f for f in facts if f.start is None]
        if period_type == "annual":
            candidates = [f for f in candidates if f.form in _ANNUAL_FORMS]
    else:
        raise ValueError(f"kind must be 'duration' or 'instant', got {kind!r}")

    # One fact per period_end; the latest filing wins.
    by_period: dict[date, Fact] = {}
    for fact in candidates:
        current = by_period.get(fact.end)
        if current is None or fact.filed > current.filed:
            by_period[fact.end] = fact

    return sorted(by_period.values(), key=lambda f: f.end, reverse=True)[:limit]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_periods.py -v && ruff check . && mypy src`
Expected: 10 passed.

- [x] **Step 5: Commit**

```bash
git add src/research/ingest/concepts.py tests/test_research_periods.py
git commit -m "feat(research): period selection with restatement precedence"
```

---

## Task 3.4 — Unit enforcement `[GLM]`

**Files:**
- Modify: `src/research/ingest/concepts.py` (add `assert_units_supported`)
- Test: `tests/test_research_units.py`

**Interfaces:**
- Produces: `assert_units_supported(spec: LineItemSpec) -> None`, raising `ValueError` for any
  unit outside `{"USD", "USD/shares", "shares", "pure"}`.

- [x] **Step 1: Write the failing test**

Create `tests/test_research_units.py`:

```python
"""Units are enforced, never coerced. A unit we do not understand is a config error."""

from __future__ import annotations

import pytest

from src.research.ingest.concepts import LineItemSpec, assert_units_supported, load_concept_map


def test_supported_units_pass() -> None:
    for unit in ("USD", "USD/shares", "shares", "pure"):
        assert_units_supported(
            LineItemSpec(statement="income", kind="duration", units=[unit], concepts=["X"])
        )


def test_an_unsupported_unit_raises() -> None:
    spec = LineItemSpec(statement="income", kind="duration", units=["EUR"], concepts=["X"])
    with pytest.raises(ValueError, match="Unsupported unit"):
        assert_units_supported(spec)


def test_every_shipped_line_item_uses_a_supported_unit() -> None:
    for spec in load_concept_map().values():
        assert_units_supported(spec)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_units.py -v`
Expected: FAIL with `ImportError: cannot import name 'assert_units_supported'`

- [x] **Step 3: Append to `src/research/ingest/concepts.py`**

```python
SUPPORTED_UNITS = frozenset({"USD", "USD/shares", "shares", "pure"})


def assert_units_supported(spec: LineItemSpec) -> None:
    """Reject units we cannot interpret rather than coercing them.

    A EUR-denominated revenue silently treated as USD is worse than no number at all.
    """
    for unit in spec.units:
        if unit not in SUPPORTED_UNITS:
            raise ValueError(
                f"Unsupported unit {unit!r}; supported: {sorted(SUPPORTED_UNITS)}"
            )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_units.py -v && ruff check . && mypy src`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add src/research/ingest/concepts.py tests/test_research_units.py
git commit -m "feat(research): reject unsupported XBRL units instead of coercing"
```

---

## Task 3.5 — Normalisation and persistence `[GLM]`

**Files:**
- Create: `src/research/ingest/fundamentals.py`
- Test: `tests/test_ingest_fundamentals.py`

**Interfaces:**
- Consumes: `get_filings_provider()` (3.1), `load_concept_map`, `resolve_line_item`,
  `select_periods`, `assert_units_supported` (3.2 to 3.4), research store (1.2).
- Produces:
  - `normalize(payload: dict, symbol: str, *, annual_limit: int = 5, quarterly_limit: int = 8) -> NormalizedFinancials`
  - `ingest_fundamentals(symbol: str, cik: str) -> NormalizedFinancials | None` (fetches,
    caches raw, normalises, persists `FinancialRow`s)

- [x] **Step 1: Write the failing test**

Create `tests/test_ingest_fundamentals.py`:

```python
"""Normalisation assembles periods, and persistence is idempotent."""

from __future__ import annotations

from datetime import date

import pytest

from src.research.ingest.fundamentals import ingest_fundamentals, normalize
from src.research.store.models import CompanyFactsRawRow, FinancialRow
from src.research.store.session import init_research_db, research_session


def _payload() -> dict:
    def dur(y: int, val: float) -> dict:
        return {
            "start": f"{y}-01-01", "end": f"{y}-12-31", "val": val,
            "accn": f"acc-{y}", "fy": y, "fp": "FY", "form": "10-K", "filed": f"{y + 1}-02-01",
        }

    def inst(y: int, val: float) -> dict:
        return {
            "end": f"{y}-12-31", "val": val, "accn": f"acc-{y}", "fy": y, "fp": "FY",
            "form": "10-K", "filed": f"{y + 1}-02-01",
        }

    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [dur(2022, 100.0), dur(2023, 120.0)]}},
                "NetIncomeLoss": {"units": {"USD": [dur(2022, 10.0), dur(2023, 15.0)]}},
                "Assets": {"units": {"USD": [inst(2022, 500.0), inst(2023, 550.0)]}},
            }
        },
    }


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_normalize_builds_annual_periods_newest_first() -> None:
    fin = normalize(_payload(), "AAPL")
    assert fin.symbol == "AAPL"
    assert fin.entity_name == "Apple Inc."
    assert [p.period_end for p in fin.annual] == [date(2023, 12, 31), date(2022, 12, 31)]


def test_normalize_carries_filing_traceability() -> None:
    fin = normalize(_payload(), "AAPL")
    rev = fin.annual[0].items["revenue"]
    assert rev.value == 120.0
    assert rev.concept == "Revenues"
    assert rev.accn == "acc-2023"
    assert rev.filed == date(2024, 2, 1)


def test_normalize_mixes_duration_and_instant_into_one_period() -> None:
    fin = normalize(_payload(), "AAPL")
    period = fin.annual[0]
    assert period.items["revenue"].value == 120.0        # duration
    assert period.items["total_assets"].value == 550.0   # instant


def test_unmapped_line_items_are_absent_not_zero() -> None:
    """A line item the filer does not report must not appear as 0.0."""
    fin = normalize(_payload(), "AAPL")
    assert "dividends_paid" not in fin.annual[0].items


def test_normalize_on_an_empty_payload_yields_no_periods() -> None:
    fin = normalize({}, "XYZ")
    assert fin.annual == []
    assert fin.quarterly == []


def test_ingest_persists_rows_and_caches_the_raw_payload(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.fundamentals.get_filings_provider",
        lambda: type("P", (), {"get_company_facts": staticmethod(lambda cik: _payload())})(),
    )
    fin = ingest_fundamentals("AAPL", "0000320193")
    assert fin is not None

    with research_session() as s:
        assert s.get(CompanyFactsRawRow, "0000320193") is not None
        rows = s.query(FinancialRow).filter_by(symbol="AAPL", line_item="revenue").all()
        assert {r.value for r in rows} == {100.0, 120.0}


def test_ingest_is_idempotent(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.fundamentals.get_filings_provider",
        lambda: type("P", (), {"get_company_facts": staticmethod(lambda cik: _payload())})(),
    )
    ingest_fundamentals("AAPL", "0000320193")
    ingest_fundamentals("AAPL", "0000320193")

    with research_session() as s:
        rows = s.query(FinancialRow).filter_by(symbol="AAPL", line_item="revenue").all()
        assert len(rows) == 2  # two periods, not four


def test_ingest_returns_none_when_the_filer_has_no_facts(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.fundamentals.get_filings_provider",
        lambda: type("P", (), {"get_company_facts": staticmethod(lambda cik: {})})(),
    )
    assert ingest_fundamentals("XYZ", "0000000001") is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingest_fundamentals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research.ingest.fundamentals'`

- [x] **Step 3: Implement `src/research/ingest/fundamentals.py`**

```python
"""Fetch, normalise, and persist a filer's financial statements.

Every ratio the checks engine later computes is derived from THESE numbers, never taken from
a vendor's precomputed field. That is the discipline src/analytics/fundamentals.py already
follows, and it is why the concept map and period selection matter so much.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from src.data.factory import get_filings_provider
from src.research.ingest.concepts import (
    assert_units_supported,
    load_concept_map,
    resolve_line_item,
    select_periods,
)
from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement
from src.research.store.models import CompanyFactsRawRow, FinancialRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

ANNUAL_LIMIT = 5
QUARTERLY_LIMIT = 8


def normalize(
    payload: dict,
    symbol: str,
    *,
    annual_limit: int = ANNUAL_LIMIT,
    quarterly_limit: int = QUARTERLY_LIMIT,
) -> NormalizedFinancials:
    """Turn a companyfacts document into periods of canonical line items."""
    concept_map = load_concept_map()

    # period_type -> period_end -> line_item -> value
    buckets: dict[str, dict[date, dict[str, LineItemValue]]] = {
        "annual": defaultdict(dict),
        "quarterly": defaultdict(dict),
    }

    for name, spec in concept_map.items():
        assert_units_supported(spec)
        resolved = resolve_line_item(payload, spec)
        if resolved is None:
            continue  # the filer reports nothing we recognise; absent, never zero
        concept, facts = resolved

        for period_type, limit in (("annual", annual_limit), ("quarterly", quarterly_limit)):
            for fact in select_periods(
                facts, kind=spec.kind, period_type=period_type, limit=limit
            ):
                buckets[period_type][fact.end][name] = LineItemValue(
                    line_item=name,
                    value=fact.value,
                    concept=concept,
                    accn=fact.accn,
                    filed=fact.filed,
                    form=fact.form,
                )

    def statements(period_type: str, limit: int) -> list[PeriodStatement]:
        ends = sorted(buckets[period_type], reverse=True)[:limit]
        return [
            PeriodStatement(
                period_end=end, period_type=period_type, items=buckets[period_type][end]
            )
            for end in ends
        ]

    return NormalizedFinancials(
        symbol=symbol,
        cik=str(payload.get("cik", "")).zfill(10) if payload.get("cik") else "",
        entity_name=str(payload.get("entityName", "")),
        annual=statements("annual", annual_limit),
        quarterly=statements("quarterly", quarterly_limit),
    )


def ingest_fundamentals(symbol: str, cik: str) -> NormalizedFinancials | None:
    """Fetch, cache the raw payload, normalise, and persist. None when there are no facts."""
    payload = get_filings_provider().get_company_facts(cik)
    if not payload:
        log.info("No XBRL facts for %s (CIK %s)", symbol, cik)
        return None

    financials = normalize(payload, symbol)
    now = datetime.now(UTC)

    with research_session() as session:
        raw = session.get(CompanyFactsRawRow, cik)
        blob = json.dumps(payload, separators=(",", ":"))
        if raw is None:
            session.add(CompanyFactsRawRow(cik=cik, payload_json=blob, fetched_at=now))
        else:
            raw.payload_json = blob
            raw.fetched_at = now

        # Replace this symbol's rows wholesale: normalisation is deterministic, so a
        # re-ingest should leave exactly one row per (period, line item).
        session.query(FinancialRow).filter_by(symbol=symbol).delete()
        for statement in [*financials.annual, *financials.quarterly]:
            for item in statement.items.values():
                session.add(
                    FinancialRow(
                        symbol=symbol,
                        period_end=statement.period_end,
                        period_type=statement.period_type,
                        line_item=item.line_item,
                        value=item.value,
                        concept=item.concept,
                        accn=item.accn,
                        filed=item.filed,
                    )
                )

    return financials
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ingest_fundamentals.py -v && ruff check . && mypy src`
Expected: 8 passed.

- [x] **Step 5: Commit**

```bash
git add src/research/ingest/fundamentals.py tests/test_ingest_fundamentals.py
git commit -m "feat(research): normalise and persist EDGAR financial statements"
```

---

## Task 3.6 — Bounded materialisation `[SONNET]`

Sonnet: this is a judgment call about degradation. The contract between "slow" and "partial"
is what keeps a cold-tier first view from feeling broken.

**Files:**
- Create: `src/research/ingest/materialize.py`
- Modify: `src/research/ingest/jobs.py` (register the drain)
- Test: `tests/test_research_materialize.py`

**Interfaces:**
- Produces:
  - `SectionState` (StrEnum): `READY`, `PENDING`, `UNAVAILABLE`
  - `materialize(symbol: str, *, budget_seconds: float | None = None) -> MaterializeResult`
    where `MaterializeResult{symbol, fundamentals: NormalizedFinancials | None,
    fundamentals_state: SectionState, reason: str | None}`
  - `enqueue(symbol: str, kind: str) -> None` (deduplicated on pending)
  - `drain_ingest_jobs(max_jobs: int = 20) -> int`

- [x] **Step 1: Write the failing test**

Create `tests/test_research_materialize.py`:

```python
"""Cold-tier materialisation: full when it fits the budget, partial and queued when not."""

from __future__ import annotations

import pytest

from src.research.ingest.materialize import (
    SectionState,
    drain_ingest_jobs,
    enqueue,
    materialize,
)
from src.research.store.models import IngestJobRow, SymbolRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))


def test_unknown_symbol_is_unavailable_not_pending(db) -> None:
    """A ticker with no directory row will never resolve, so queueing it is a lie."""
    result = materialize("NOPE")
    assert result.fundamentals_state is SectionState.UNAVAILABLE
    assert result.reason


def test_successful_ingest_is_ready(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals",
        lambda symbol, cik: object(),
    )
    result = materialize("AAPL")
    assert result.fundamentals_state is SectionState.READY


def test_exceeding_the_budget_returns_pending_and_queues_a_job(db, monkeypatch) -> None:
    import time

    def slow(symbol: str, cik: str):
        time.sleep(0.05)
        return object()

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", slow)
    result = materialize("AAPL", budget_seconds=0.01)
    assert result.fundamentals_state is SectionState.PENDING

    with research_session() as s:
        jobs = s.query(IngestJobRow).filter_by(symbol="AAPL", status="pending").all()
        assert len(jobs) == 1


def test_a_failing_ingest_is_unavailable_with_a_reason(db, monkeypatch) -> None:
    def boom(symbol: str, cik: str):
        raise RuntimeError("SEC throttled")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)
    result = materialize("AAPL")
    assert result.fundamentals_state is SectionState.UNAVAILABLE
    assert "SEC throttled" in (result.reason or "")


def test_enqueue_deduplicates_pending_jobs(db) -> None:
    enqueue("AAPL", "fundamentals")
    enqueue("AAPL", "fundamentals")
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(symbol="AAPL", status="pending").count() == 1


def test_drain_marks_jobs_done(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals",
        lambda symbol, cik: object(),
    )
    enqueue("AAPL", "fundamentals")
    assert drain_ingest_jobs() == 1
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(status="done").count() == 1


def test_drain_records_the_error_and_increments_attempts(db, monkeypatch) -> None:
    def boom(symbol: str, cik: str):
        raise RuntimeError("nope")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)
    enqueue("AAPL", "fundamentals")
    drain_ingest_jobs()
    with research_session() as s:
        job = s.query(IngestJobRow).filter_by(symbol="AAPL").one()
        assert job.attempts == 1
        assert "nope" in (job.last_error or "")
        assert job.status == "pending"  # retried next drain


def test_drain_gives_up_after_repeated_failures(db, monkeypatch) -> None:
    def boom(symbol: str, cik: str):
        raise RuntimeError("nope")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)
    enqueue("AAPL", "fundamentals")
    for _ in range(4):
        drain_ingest_jobs()
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(symbol="AAPL").one().status == "failed"
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_materialize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research.ingest.materialize'`

- [x] **Step 3: Implement `src/research/ingest/materialize.py`**

```python
"""Cold-tier materialisation with a wall-clock budget.

A symbol nobody has viewed before has no cached analysis. We try to build one synchronously
inside a budget; if that overruns, the caller gets a partial payload with the slow sections
marked PENDING and a background job queued. The client polls. There is never a spinner over
a blank screen. See design §5.5.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from src.common.config import get_config
from src.research.ingest.fundamentals import ingest_fundamentals
from src.research.schemas import NormalizedFinancials
from src.research.store.models import IngestJobRow, SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


class SectionState(StrEnum):
    READY = "ready"              # data is present
    PENDING = "pending"          # queued; poll again
    UNAVAILABLE = "unavailable"  # will not resolve; reason explains why


class MaterializeResult(BaseModel):
    symbol: str
    fundamentals: NormalizedFinancials | None = None
    fundamentals_state: SectionState = SectionState.UNAVAILABLE
    reason: str | None = None


def enqueue(symbol: str, kind: str) -> None:
    """Queue a background ingest. Deduplicated on (symbol, kind, pending)."""
    with research_session() as session:
        exists = (
            session.query(IngestJobRow)
            .filter_by(symbol=symbol, kind=kind, status="pending")
            .first()
        )
        if exists is None:
            session.add(
                IngestJobRow(
                    symbol=symbol, kind=kind, status="pending",
                    attempts=0, enqueued_at=datetime.now(UTC),
                )
            )


def materialize(symbol: str, *, budget_seconds: float | None = None) -> MaterializeResult:
    """Build a symbol's analysis inputs, bounded by a wall-clock budget."""
    budget = (
        budget_seconds
        if budget_seconds is not None
        else get_config().research.tiers.materialization_budget_seconds
    )

    with research_session() as session:
        row = session.get(SymbolRow, symbol.upper())
        cik = row.cik if row else None

    if not cik:
        # No directory row means no CIK, and a queued job would never resolve. Saying
        # "pending" here would be a lie the client renders as a spinner forever.
        return MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason="No SEC filer record for this symbol",
        )

    started = time.monotonic()
    try:
        financials = ingest_fundamentals(symbol, cik)
    except Exception as exc:
        log.warning("Fundamentals ingest failed for %s: %s", symbol, exc)
        return MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason=str(exc),
        )

    if time.monotonic() - started > budget:
        # It DID finish, but too slowly to keep the request open next time. Queue a warm
        # refresh so the next view is instant, and tell the client this view is partial.
        enqueue(symbol, "fundamentals")
        return MaterializeResult(
            symbol=symbol,
            fundamentals=financials,
            fundamentals_state=SectionState.PENDING,
            reason="Still building; refresh shortly",
        )

    if financials is None:
        return MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason="No XBRL financial statements filed for this symbol",
        )

    return MaterializeResult(
        symbol=symbol, fundamentals=financials, fundamentals_state=SectionState.READY
    )


def drain_ingest_jobs(max_jobs: int = 20) -> int:
    """Run queued jobs. Returns how many succeeded."""
    with research_session() as session:
        jobs = (
            session.query(IngestJobRow)
            .filter_by(status="pending")
            .order_by(IngestJobRow.enqueued_at)
            .limit(max_jobs)
            .all()
        )
        pending = [(j.id, j.symbol, j.kind) for j in jobs]

    done = 0
    for job_id, symbol, kind in pending:
        with research_session() as session:
            row = session.get(SymbolRow, symbol)
            cik = row.cik if row else None

        error: str | None = None
        if kind == "fundamentals" and cik:
            try:
                ingest_fundamentals(symbol, cik)
            except Exception as exc:
                error = str(exc)
        else:
            error = f"Cannot run job kind {kind!r} for {symbol}"

        with research_session() as session:
            job = session.get(IngestJobRow, job_id)
            if job is None:
                continue
            job.attempts += 1
            if error is None:
                job.status = "done"
                job.last_error = None
                done += 1
            else:
                job.last_error = error
                job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"

    return done
```

- [x] **Step 4: Register the drain in the scheduler**

In `src/research/ingest/jobs.py`'s `build_scheduler()`:

```python
    from apscheduler.triggers.interval import IntervalTrigger

    from src.research.ingest.materialize import drain_ingest_jobs

    sched.add_job(
        lambda: run_job("drain", drain_ingest_jobs),
        IntervalTrigger(seconds=30),
        id="drain_ingest_jobs",
        replace_existing=True,
    )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_materialize.py -v && ruff check . && mypy src`
Expected: 8 passed.

- [x] **Step 6: Commit**

```bash
git add src/research tests/test_research_materialize.py
git commit -m "feat(research): bounded materialisation with a background ingest queue"
```

---

## Task 3.7 — `GET /research/{symbol}` `[SONNET]`

Sonnet: this defines the partial-payload contract every later section plugs into.

**Files:**
- Create: `src/api/models/research.py`
- Modify: `src/api/routers/research.py`, `docs/web/api.md`
- Test: `tests/test_api_analysis.py`

**Interfaces:**
- Produces:
  - `Section[T]{state: SectionState, data: T | None, reason: str | None}`
  - `AnalysisResponse{as_of, symbol, name, exchange, is_etf, fundamentals: Section[FinancialsPayload]}`
  - `GET /research/{symbol}` returning 404 only when the symbol is not in the directory

- [x] **Step 1: Write the failing test**

Create `tests/test_api_analysis.py`:

```python
"""The analysis payload: per-section state, and honest 404s."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.ingest.materialize import MaterializeResult, SectionState
from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session

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
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq"))
    return TestClient(create_app())


def _financials() -> NormalizedFinancials:
    from datetime import date

    return NormalizedFinancials(
        symbol="AAPL",
        cik="0000320193",
        entity_name="Apple Inc.",
        annual=[
            PeriodStatement(
                period_end=date(2024, 9, 28),
                period_type="annual",
                items={
                    "revenue": LineItemValue(
                        line_item="revenue", value=391035000000.0, concept="Revenues",
                        accn="acc-1", filed=date(2024, 11, 1), form="10-K",
                    )
                },
            )
        ],
    )


def test_requires_auth(client) -> None:
    assert client.get("/research/AAPL").status_code == 401


def test_unknown_symbol_is_404(client) -> None:
    assert client.get("/research/ZZZZ", headers=AUTH).status_code == 404


def test_ready_section_carries_data(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals=_financials(),
            fundamentals_state=SectionState.READY,
        ),
    )
    body = client.get("/research/AAPL", headers=AUTH).json()
    assert body["symbol"] == "AAPL"
    assert body["fundamentals"]["state"] == "ready"
    assert body["fundamentals"]["data"]["annual"][0]["items"]["revenue"]["value"] > 0


def test_pending_section_is_200_with_a_reason_not_an_error(client, monkeypatch) -> None:
    """A slow section must not fail the page. The client polls."""
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals_state=SectionState.PENDING,
            reason="Still building; refresh shortly",
        ),
    )
    r = client.get("/research/AAPL", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["fundamentals"]["state"] == "pending"
    assert r.json()["fundamentals"]["reason"]


def test_unavailable_section_still_returns_the_symbol_header(client, monkeypatch) -> None:
    """An ETF with no XBRL still renders a page. The section explains itself."""
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals_state=SectionState.UNAVAILABLE,
            reason="No XBRL financial statements filed for this symbol",
        ),
    )
    body = client.get("/research/AAPL", headers=AUTH).json()
    assert body["name"] == "Apple Inc."
    assert body["fundamentals"]["state"] == "unavailable"
    assert body["fundamentals"]["data"] is None


def test_symbol_lookup_is_case_insensitive(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals_state=SectionState.UNAVAILABLE, reason="x"
        ),
    )
    assert client.get("/research/aapl", headers=AUTH).status_code == 200
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_analysis.py -v`
Expected: FAIL with 404 on every case.

- [x] **Step 3: Implement `src/api/models/research.py`**

```python
"""Response shapes for the research routes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from src.api.models.common import Envelope
from src.research.ingest.materialize import SectionState
from src.research.schemas import NormalizedFinancials

T = TypeVar("T")


class Section(BaseModel, Generic[T]):
    """One region of the page, with its own state.

    A slow or missing section never fails the whole page. `reason` is rendered to the user
    verbatim, so it must read as an explanation rather than an exception string.
    """

    state: SectionState
    data: T | None = None
    reason: str | None = None


class AnalysisResponse(Envelope):
    symbol: str
    name: str
    exchange: str | None = None
    is_etf: bool = False
    fundamentals: Section[NormalizedFinancials]
```

- [x] **Step 4: Add the route to `src/api/routers/research.py`**

```python
@router.get("/{symbol}", response_model=AnalysisResponse)
def analysis(symbol: str, user: CurrentUser, db: ResearchDb) -> AnalysisResponse:
    """Full analysis for one symbol.

    404 only when the symbol is not a known filer. Everything else degrades per section.
    """
    now = datetime.now(UTC)
    upper = symbol.upper()

    row = db.get(SymbolRow, upper)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")

    result = materialize(upper)

    return AnalysisResponse(
        as_of=now,
        symbol=upper,
        name=row.name,
        exchange=row.exchange,
        is_etf=row.is_etf,
        fundamentals=Section[NormalizedFinancials](
            state=result.fundamentals_state,
            data=result.fundamentals,
            reason=result.reason,
        ),
    )
```

Add the imports: `from fastapi import HTTPException`,
`from src.api.models.research import AnalysisResponse, Section`,
`from src.research.ingest.materialize import materialize`,
`from src.research.schemas import NormalizedFinancials`.

**Route ordering matters:** `/search` must be registered **before** `/{symbol}`, or FastAPI
matches `/research/search` as a symbol named "search". Keep the `search` function above
`analysis` in the file.

- [x] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_analysis.py tests/test_api_search.py -v && ruff check . && mypy src`
Expected: all passed. The search tests passing confirms the route ordering is right.

- [x] **Step 6: Update `docs/web/api.md`**

Document `GET /research/{symbol}`, the `Section` shape, all three `SectionState` values, and
the rule that 404 means "unknown symbol" while a missing section is a 200 with a reason.

- [x] **Step 7: Commit**

```bash
git add src/api docs/web/api.md tests/test_api_analysis.py
git commit -m "feat(api): add per-symbol analysis endpoint with per-section state"
```

---

## Task 3.8 — Ticker page and statements table `[GLM]`

**Files:**
- Modify: `web/app/stock/[symbol]/page.tsx`
- Create: `web/components/stock/SectionShell.tsx`,
  `web/components/stock/StatementsTable.tsx`, `web/lib/format.ts`
- Test: `web/components/stock/StatementsTable.test.tsx`, `web/lib/format.test.ts`

**Interfaces:**
- Consumes: `GET /research/{symbol}` (3.7), `apiFetch` (2.6).
- Produces:
  - `formatMoney(v: number | null): string` (compact: `$391.0B`, `$1.2M`; `"—"` never used,
    the unknown marker is the string `"n/a"`)
  - `<SectionShell state reason>` rendering pending and unavailable states
  - `<StatementsTable financials />` with filing traceability in a `title` attribute

- [x] **Step 1: Write the failing tests**

`web/lib/format.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { formatMoney, formatPeriod } from "./format";

describe("formatMoney", () => {
  it("compacts billions", () => expect(formatMoney(391035000000)).toBe("$391.0B"));
  it("compacts millions", () => expect(formatMoney(1250000)).toBe("$1.3M"));
  it("handles negatives", () => expect(formatMoney(-4500000000)).toBe("-$4.5B"));
  it("renders an unknown as n/a, never as zero", () => expect(formatMoney(null)).toBe("n/a"));
  it("renders a real zero as a zero", () => expect(formatMoney(0)).toBe("$0"));
});

describe("formatPeriod", () => {
  it("renders an ISO date as a short period label", () =>
    expect(formatPeriod("2024-09-28")).toBe("Sep 2024"));
});
```

`web/components/stock/StatementsTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatementsTable } from "./StatementsTable";

const financials = {
  symbol: "AAPL",
  cik: "0000320193",
  entity_name: "Apple Inc.",
  annual: [
    {
      period_end: "2024-09-28",
      period_type: "annual",
      items: {
        revenue: {
          line_item: "revenue",
          value: 391035000000,
          concept: "Revenues",
          accn: "0000320193-24-000123",
          filed: "2024-11-01",
          form: "10-K",
        },
      },
    },
  ],
  quarterly: [],
};

describe("StatementsTable", () => {
  it("renders the period column header", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getByText("Sep 2024")).toBeDefined();
  });

  it("formats the value", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getByText("$391.0B")).toBeDefined();
  });

  it("exposes filing traceability on the cell", () => {
    render(<StatementsTable financials={financials} />);
    const cell = screen.getByText("$391.0B");
    expect(cell.getAttribute("title")).toContain("0000320193-24-000123");
    expect(cell.getAttribute("title")).toContain("Revenues");
  });

  it("renders a missing line item as n/a rather than zero", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run`
Expected: FAIL, modules not found.

- [x] **Step 3: Implement `web/lib/format.ts`**

```ts
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** A value we do not have. Never a zero, never a dash that reads as a minus sign. */
export const UNKNOWN = "n/a";

export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return UNKNOWN;
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function formatPeriod(iso: string): string {
  const [y, m] = iso.split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`;
}
```

- [x] **Step 4: Implement `web/components/stock/SectionShell.tsx`**

```tsx
export function SectionShell({
  title,
  state,
  reason,
  children,
}: {
  title: string;
  state: "ready" | "pending" | "unavailable";
  reason?: string | null;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">{title}</h2>
      {state === "ready" && children}
      {state === "pending" && (
        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
          {reason ?? "Building this section. It will appear shortly."}
        </p>
      )}
      {state === "unavailable" && (
        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
          {reason ?? "Not available for this symbol."}
        </p>
      )}
    </section>
  );
}
```

- [x] **Step 5: Implement `web/components/stock/StatementsTable.tsx`**

```tsx
import { UNKNOWN, formatMoney, formatPeriod } from "@/lib/format";

type Item = {
  line_item: string;
  value: number | null;
  concept: string | null;
  accn: string | null;
  filed: string | null;
  form: string | null;
};

type Period = { period_end: string; period_type: string; items: Record<string, Item> };
type Financials = { annual: Period[]; quarterly: Period[] };

// Fixed row order so the table reads like a statement, not a hash dump.
const ROWS: [string, string][] = [
  ["revenue", "Revenue"],
  ["cost_of_revenue", "Cost of revenue"],
  ["gross_profit", "Gross profit"],
  ["operating_income", "Operating income"],
  ["net_income", "Net income"],
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["stockholders_equity", "Shareholders equity"],
  ["operating_cash_flow", "Operating cash flow"],
  ["capital_expenditure", "Capital expenditure"],
];

export function StatementsTable({ financials }: { financials: Financials }) {
  const periods = financials.annual;

  return (
    <div className="overflow-x-auto rounded-md bg-surface">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-3 text-left font-medium text-muted">Line item</th>
            {periods.map((p) => (
              <th
                key={p.period_end}
                className="tabular px-4 py-3 text-right font-mono font-medium text-muted"
              >
                {formatPeriod(p.period_end)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([key, label]) => (
            <tr key={key} className="border-b border-border last:border-0">
              <td className="px-4 py-2 text-content">{label}</td>
              {periods.map((p) => {
                const item = p.items[key];
                const title = item
                  ? `${item.concept ?? ""} · ${item.form ?? ""} ${item.accn ?? ""} filed ${item.filed ?? ""}`
                  : "Not reported";
                return (
                  <td
                    key={p.period_end}
                    title={title}
                    className={`tabular px-4 py-2 text-right font-mono ${
                      item?.value == null ? "text-unknown" : "text-content"
                    }`}
                  >
                    {item ? formatMoney(item.value) : UNKNOWN}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [x] **Step 6: Rewrite the ticker page**

`web/app/stock/[symbol]/page.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import { apiFetch } from "@/lib/api";
import { SectionShell } from "@/components/stock/SectionShell";
import { StatementsTable } from "@/components/stock/StatementsTable";

export default function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  const upper = symbol.toUpperCase();

  const { data, isLoading } = useQuery({
    queryKey: ["analysis", upper],
    queryFn: () => apiFetch<any>(`/research/${upper}`),
    // Poll while any section is still building.
    refetchInterval: (q) =>
      q.state.data?.fundamentals?.state === "pending" ? 5000 : false,
  });

  return (
    <div className="px-8 py-6">
      <header className="mb-8">
        <h1 className="font-mono text-2xl text-content">{upper}</h1>
        <p className="mt-1 text-sm text-muted">
          {data?.name ?? (isLoading ? "Loading" : "")}
          {data?.exchange ? ` · ${data.exchange}` : ""}
          {data?.is_etf ? " · ETF" : ""}
        </p>
      </header>

      <SectionShell
        title="Financial statements"
        state={data?.fundamentals?.state ?? "pending"}
        reason={data?.fundamentals?.reason}
      >
        {data?.fundamentals?.data && (
          <StatementsTable financials={data.fundamentals.data} />
        )}
      </SectionShell>
    </div>
  );
}
```

Replace the `any` types with the generated types from `npm run gen:api` once the API is
running; `AnalysisResponse` is exported by `lib/api-types.ts`.

- [x] **Step 7: Run tests to verify they pass**

Run: `cd web && npx vitest run && npm run build && npm run lint`
Expected: 9 passed, clean build.

- [x] **Step 8: Verify end to end**

Start the API and worker, `npm run dev`, then visit `/stock/AAPL`. Expected: real Apple
financials from SEC, five annual columns, and hovering a cell shows its accession number.
Then visit `/stock/SPY`. Expected: the page renders with the fundamentals section explaining
that no XBRL statements were filed.

- [x] **Step 9: Commit**

```bash
git add web
git commit -m "feat(web): ticker page with normalised statements and filing traceability"
```

---

## Milestone 3 exit criteria

- [x] `python -m pytest -q`, `ruff check .`, `mypy src` all green
- [x] `cd web && npx vitest run && npm run build && npm run lint` all green
- [x] `/stock/AAPL` shows five years of real SEC financials
- [x] `/stock/SPY` renders cleanly with an explained empty fundamentals section
- [x] A missing line item renders `n/a`, never `$0`
- [x] Hovering any cell reveals its concept, form, accession number and filing date
- [x] `docs/web/api.md` and `ARCHITECTURE.md` updated
