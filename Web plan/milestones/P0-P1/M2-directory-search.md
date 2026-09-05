# Milestone 2 — Symbol Directory, Search, and the Shell

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Search works across every SEC filer, and the dark shell with its left rail is on
screen.

**Spec:** `Web plan/P0-P1-design.md` §5.1, §5.2, §5.5, §8, §9. **Index:**
`Web plan/P0-P1-IMPLEMENTATION-PLAN.md`.

**Depends on:** Milestone 1 complete.

**Ends with:** `⌘K` opens a palette that fuzzy-searches ~10,000 tickers and navigates to a stub
ticker page; the research worker refreshes the directory weekly.

---

## File structure

| File | Responsibility |
|---|---|
| `src/data/protocols.py` | `SymbolDirectoryProvider` Protocol added |
| `src/data/edgar_backend.py` | EDGAR HTTP client, rate limiter, directory fetch |
| `src/data/factory.py` | `get_symbol_directory_provider()` |
| `src/research/ingest/symbols.py` | Directory fetch to `symbols` table |
| `src/api/routers/research.py` | `GET /research/search` |
| `scripts/run_research_worker.py` | APScheduler worker process |
| `web/` | Next.js app: tokens, fonts, rail, command palette |

---

## Task 2.1 — `SymbolDirectoryProvider` protocol and factory `[GLM]`

**Files:**
- Modify: `src/data/protocols.py` (append a new Protocol, matching the three already there)
- Modify: `src/data/factory.py` (append a getter, matching the three already there)
- Test: `tests/test_data_symbol_directory.py`

**Interfaces:**
- Produces:
  - `SymbolRecord` (Pydantic): `symbol: str`, `cik: str`, `name: str`, `exchange: str | None`
  - `SymbolDirectoryProvider` Protocol with `list_symbols() -> list[SymbolRecord]`
  - `get_symbol_directory_provider() -> SymbolDirectoryProvider`
  - New config key `data.symbol_directory_provider` (default `"edgar"`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_symbol_directory.py`:

```python
"""The symbol-directory provider follows the existing src/data Protocol pattern."""

from __future__ import annotations

from src.data.protocols import SymbolDirectoryProvider, SymbolRecord


def test_symbol_record_shape() -> None:
    r = SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq")
    assert r.symbol == "AAPL"
    assert r.cik == "0000320193"


def test_a_stub_satisfies_the_protocol_structurally() -> None:
    class Stub:
        def list_symbols(self) -> list[SymbolRecord]:
            return [SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.")]

    assert isinstance(Stub(), SymbolDirectoryProvider)


def test_factory_rejects_an_unknown_backend(monkeypatch) -> None:
    import pytest

    from src.data.factory import _make_symbol_directory_provider

    with pytest.raises(ValueError, match="Unknown data.symbol_directory_provider"):
        _make_symbol_directory_provider("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_symbol_directory.py -v`
Expected: FAIL with `ImportError: cannot import name 'SymbolDirectoryProvider'`

- [ ] **Step 3: Append to `src/data/protocols.py`**

```python
class SymbolRecord(BaseModel):
    """One row of the symbol directory. `cik` is zero-padded to 10 digits."""

    symbol: str
    cik: str
    name: str = ""
    exchange: str | None = None


@runtime_checkable
class SymbolDirectoryProvider(Protocol):
    """The full list of listed US filers: ticker, CIK, name, exchange."""

    def list_symbols(self) -> list[SymbolRecord]:
        """Return every symbol the backend knows about.

        Empty list when unavailable. Never raises.
        """
        ...
```

Add `from pydantic import BaseModel` to the imports at the top of the file.

- [ ] **Step 4: Append to `src/data/factory.py`**

```python
def _make_symbol_directory_provider(name: str) -> SymbolDirectoryProvider:
    if name == "edgar":
        from src.data.edgar_backend import EdgarSymbolDirectoryProvider

        return EdgarSymbolDirectoryProvider()
    raise ValueError(f"Unknown data.symbol_directory_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_symbol_directory_provider() -> SymbolDirectoryProvider:
    """Return the active :class:`SymbolDirectoryProvider` (cached process-wide)."""
    return _make_symbol_directory_provider(get_config().data.symbol_directory_provider)
```

Add `SymbolDirectoryProvider` to the `from src.data.protocols import ...` line.

- [ ] **Step 5: Add the config key**

In `src/common/config.py`, `class DataCfg` (line 286) gains:

```python
    symbol_directory_provider: str = "edgar"
    filings_provider: str = "edgar"
    bulk_price_provider: str = "stooq"
```

In `config/settings.yaml` under `data:`:

```yaml
  symbol_directory_provider: edgar
  filings_provider: edgar
  bulk_price_provider: stooq
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_data_symbol_directory.py -v && ruff check . && mypy src`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/data tests/test_data_symbol_directory.py src/common/config.py config/settings.yaml
git commit -m "feat(data): add SymbolDirectoryProvider protocol and factory"
```

---

## Task 2.2 — EDGAR client and directory backend `[SONNET]`

Sonnet because this is the first EDGAR client. It sets the rate limiter, the User-Agent policy
and the ETag caching that every later EDGAR call reuses, and SEC blocks callers that get it
wrong.

**Files:**
- Create: `src/data/edgar_backend.py`
- Test: `tests/test_edgar_backend.py`

**Interfaces:**
- Consumes: `cfg.research.providers.edgar.*` (1.1), `cfg.secrets.sec_contact_email` (1.1),
  `SymbolRecord` (2.1).
- Produces:
  - `RateLimiter(rate_per_second: float)` with `.acquire() -> None`
  - `EdgarClient.get_json(url: str, *, etag: str | None = None) -> tuple[dict | None, str | None]`
    returning `(payload, etag)`; `(None, etag)` on HTTP 304
  - `EdgarSymbolDirectoryProvider.list_symbols() -> list[SymbolRecord]`
  - `user_agent() -> str`

**Reference:** `https://www.sec.gov/files/company_tickers_exchange.json` returns
`{"fields": ["cik","name","ticker","exchange"], "data": [[320193,"Apple Inc.","AAPL","Nasdaq"], ...]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_edgar_backend.py`:

```python
"""EDGAR client: User-Agent policy, rate limiting, ETag handling, directory parsing."""

from __future__ import annotations

import time

import httpx
import pytest

from src.data.edgar_backend import (
    EdgarClient,
    EdgarSymbolDirectoryProvider,
    RateLimiter,
    user_agent,
)

_DIRECTORY = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
        [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
    ],
}


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr(
        "src.data.edgar_backend._contact_email", lambda: "trader@example.com"
    )


def test_user_agent_carries_a_contact_address() -> None:
    """SEC requires a contact address in the User-Agent or it blocks the caller."""
    ua = user_agent()
    assert "trader@example.com" in ua
    assert "IBKR-Income-System" in ua


def test_user_agent_raises_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr("src.data.edgar_backend._contact_email", lambda: "")
    with pytest.raises(ValueError, match="SEC_CONTACT_EMAIL"):
        user_agent()


def test_rate_limiter_spaces_requests() -> None:
    limiter = RateLimiter(rate_per_second=20.0)  # 50ms apart
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    assert time.monotonic() - start >= 0.09  # two gaps of 50ms


def test_client_sends_the_user_agent_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True}, headers={"ETag": "abc"})

    client = EdgarClient(transport=httpx.MockTransport(handler))
    payload, etag = client.get_json("https://data.sec.gov/x.json")
    assert payload == {"ok": True}
    assert etag == "abc"
    assert "trader@example.com" in seen["user-agent"]


def test_client_returns_none_on_304_not_modified() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(304, headers={"ETag": "abc"})

    client = EdgarClient(transport=httpx.MockTransport(handler))
    payload, etag = client.get_json("https://data.sec.gov/x.json", etag="abc")
    assert payload is None
    assert etag == "abc"


def test_client_returns_none_on_429_rather_than_raising() -> None:
    """A throttled SEC must degrade the page, not crash the request."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = EdgarClient(transport=httpx.MockTransport(handler), max_retries=0)
    payload, _ = client.get_json("https://data.sec.gov/x.json")
    assert payload is None


def test_directory_parses_and_zero_pads_cik() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_DIRECTORY)

    provider = EdgarSymbolDirectoryProvider(
        client=EdgarClient(transport=httpx.MockTransport(handler))
    )
    rows = provider.list_symbols()
    assert len(rows) == 3
    apple = next(r for r in rows if r.symbol == "AAPL")
    assert apple.cik == "0000320193"  # zero-padded to 10
    assert apple.name == "Apple Inc."
    assert apple.exchange == "Nasdaq"


def test_directory_returns_empty_list_on_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = EdgarSymbolDirectoryProvider(
        client=EdgarClient(transport=httpx.MockTransport(handler), max_retries=0)
    )
    assert provider.list_symbols() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_edgar_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.data.edgar_backend'`

- [ ] **Step 3: Implement `src/data/edgar_backend.py`**

```python
"""SEC EDGAR backend: the symbol directory and (from Milestone 3) XBRL company facts.

EDGAR is free and keyless, but it has rules, and breaking them gets an IP blocked:
  - Declare a User-Agent carrying a real contact address.
  - Stay under 10 requests/second.
  - Zero-pad CIKs to 10 digits in API paths.
Honour ETags so a repeat fetch of an unchanged document costs a 304.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from src.common.config import get_config
from src.data.protocols import SymbolRecord

log = logging.getLogger(__name__)

DIRECTORY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


def _contact_email() -> str:
    """Indirection so tests can supply a contact address without touching .env."""
    return get_config().secrets.sec_contact_email


def user_agent() -> str:
    """SEC-compliant User-Agent. Raises rather than sending an anonymous request."""
    email = _contact_email()
    if not email:
        raise ValueError(
            "SEC_CONTACT_EMAIL is not set. SEC EDGAR requires a contact address in the "
            "User-Agent header and blocks callers that omit it."
        )
    product = get_config().research.providers.edgar.user_agent_product
    return f"{product} {email}"


class RateLimiter:
    """Thread-safe minimum-interval limiter. Simpler than a bucket and enough here."""

    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._interval


class EdgarClient:
    """Rate-limited, ETag-aware JSON client. Never raises on an HTTP failure."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 2,
    ) -> None:
        cfg = get_config().research.providers.edgar
        self._limiter = RateLimiter(cfg.max_requests_per_second)
        self._client = httpx.Client(
            timeout=cfg.timeout_seconds,
            transport=transport,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        self._max_retries = max_retries

    def get_json(
        self, url: str, *, etag: str | None = None
    ) -> tuple[dict | None, str | None]:
        """Fetch JSON. Returns (payload, etag); (None, etag) on 304 or on failure."""
        headers = {"User-Agent": user_agent()}
        if etag:
            headers["If-None-Match"] = etag

        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                log.warning("EDGAR request failed for %s: %s", url, exc)
                return None, etag

            if resp.status_code == 304:
                return None, etag
            if resp.status_code == 200:
                return resp.json(), resp.headers.get("ETag", etag)
            if resp.status_code in (403, 429) and attempt < self._max_retries:
                time.sleep(2.0 * (attempt + 1))
                continue
            log.warning("EDGAR returned %s for %s", resp.status_code, url)
            return None, etag
        return None, etag


class EdgarSymbolDirectoryProvider:
    """Every listed US filer, from company_tickers_exchange.json."""

    def __init__(self, client: EdgarClient | None = None) -> None:
        self._client = client or EdgarClient()

    def list_symbols(self) -> list[SymbolRecord]:
        payload, _ = self._client.get_json(DIRECTORY_URL)
        if not payload:
            return []
        try:
            fields = payload["fields"]
            idx = {name: i for i, name in enumerate(fields)}
            rows: list[SymbolRecord] = []
            for row in payload["data"]:
                ticker = str(row[idx["ticker"]] or "").strip().upper()
                if not ticker:
                    continue
                rows.append(
                    SymbolRecord(
                        symbol=ticker,
                        cik=str(row[idx["cik"]]).zfill(10),
                        name=str(row[idx["name"]] or ""),
                        exchange=(str(row[idx["exchange"]]) if row[idx["exchange"]] else None),
                    )
                )
            return rows
        except (KeyError, IndexError, TypeError) as exc:
            log.warning("EDGAR directory payload had an unexpected shape: %s", exc)
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_edgar_backend.py -v && ruff check . && mypy src`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data/edgar_backend.py tests/test_edgar_backend.py
git commit -m "feat(data): add rate-limited EDGAR client and symbol directory backend"
```

---

## Task 2.3 — Symbol directory ingest `[GLM]`

**Files:**
- Create: `src/research/ingest/__init__.py`, `src/research/ingest/symbols.py`
- Test: `tests/test_ingest_symbols.py`

**Interfaces:**
- Consumes: `get_symbol_directory_provider()` (2.1), `research_session` (1.2), `SymbolRow` (1.2).
- Produces: `refresh_symbol_directory() -> int` returning the number of rows written.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_symbols.py`:

```python
"""Directory ingest upserts, preserves enrichment, and never truncates on a failed fetch."""

from __future__ import annotations

import pytest

from src.data.protocols import SymbolRecord
from src.research.ingest.symbols import refresh_symbol_directory
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


class _Stub:
    def __init__(self, rows: list[SymbolRecord]) -> None:
        self._rows = rows

    def list_symbols(self) -> list[SymbolRecord]:
        return self._rows


def test_writes_every_symbol(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider",
        lambda: _Stub(
            [
                SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq"),
                SymbolRecord(symbol="MSFT", cik="0000789019", name="MICROSOFT CORP"),
            ]
        ),
    )
    assert refresh_symbol_directory() == 2
    with research_session() as s:
        assert s.get(SymbolRow, "AAPL").name == "Apple Inc."


def test_upsert_preserves_locally_enriched_columns(db, monkeypatch) -> None:
    """sector/industry/is_etf are filled in later by other jobs; a refresh must not wipe them."""
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="old", sector="tech", is_etf=False))

    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider",
        lambda: _Stub([SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.")]),
    )
    refresh_symbol_directory()

    with research_session() as s:
        row = s.get(SymbolRow, "AAPL")
        assert row.name == "Apple Inc."   # refreshed
        assert row.sector == "tech"       # preserved


def test_empty_fetch_leaves_existing_rows_alone(db, monkeypatch) -> None:
    """A failed SEC fetch must never empty the directory that search depends on."""
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))

    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider", lambda: _Stub([])
    )
    assert refresh_symbol_directory() == 0

    with research_session() as s:
        assert s.get(SymbolRow, "AAPL") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingest_symbols.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research.ingest'`

- [ ] **Step 3: Implement**

`src/research/ingest/__init__.py` is empty.

`src/research/ingest/symbols.py`:

```python
"""Refresh the symbol directory from the configured provider.

Search reads `symbols` directly, so this table must never be empty. An upsert (rather than a
truncate-and-reload) keeps locally enriched columns and survives a failed fetch.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.data.factory import get_symbol_directory_provider
from src.research.store.models import SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def refresh_symbol_directory() -> int:
    """Upsert every symbol the provider returns. Returns the row count written."""
    rows = get_symbol_directory_provider().list_symbols()
    if not rows:
        log.warning("Symbol directory fetch returned nothing; leaving existing rows intact")
        return 0

    now = datetime.now(UTC)
    with research_session() as session:
        existing = {r.symbol: r for r in session.query(SymbolRow).all()}
        for rec in rows:
            row = existing.get(rec.symbol)
            if row is None:
                session.add(
                    SymbolRow(
                        symbol=rec.symbol,
                        cik=rec.cik,
                        name=rec.name,
                        exchange=rec.exchange,
                        updated_at=now,
                    )
                )
            else:
                # Only the provider-owned columns. sector/industry/is_etf are enriched
                # by other jobs and must survive a directory refresh.
                row.cik = rec.cik
                row.name = rec.name
                row.exchange = rec.exchange
                row.updated_at = now

    log.info("Symbol directory refreshed: %d symbols", len(rows))
    return len(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ingest_symbols.py -v && ruff check . && mypy src`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/research/ingest tests/test_ingest_symbols.py
git commit -m "feat(research): upsert the SEC symbol directory"
```

---

## Task 2.4 — `GET /research/search` `[GLM]`

**Files:**
- Create: `src/api/routers/research.py`
- Modify: `src/api/main.py` (include the router)
- Create: `docs/web/api.md`
- Test: `tests/test_api_search.py`

**Interfaces:**
- Consumes: `CurrentUser`, `ResearchDb` (1.4), `Envelope` (1.3), `SymbolRow` (1.2).
- Produces:
  - `GET /research/search?q=<str>&limit=<int, default 20, max 50>`
  - `SearchResponse{as_of, query, results: list[SearchHit]}` where
    `SearchHit{symbol, name, exchange, is_etf}`
  - Ranking: exact ticker match first, then ticker prefix, then name substring, each
    alphabetical within its band.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_search.py`:

```python
"""Symbol search: ranking, limits, and input handling."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
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
        s.add_all(
            [
                SymbolRow(symbol="AA", cik="1", name="Alcoa Corp"),
                SymbolRow(symbol="AAPL", cik="2", name="Apple Inc."),
                SymbolRow(symbol="AAP", cik="3", name="Advance Auto Parts"),
                SymbolRow(symbol="MSFT", cik="4", name="Microsoft Corp"),
                SymbolRow(symbol="SPY", cik="5", name="SPDR S&P 500 ETF", is_etf=True),
            ]
        )
    return TestClient(create_app())


def test_search_requires_auth(client) -> None:
    assert client.get("/research/search?q=AAPL").status_code == 401


def test_exact_ticker_match_ranks_first(client) -> None:
    r = client.get("/research/search?q=AAP", headers=AUTH)
    assert r.status_code == 200
    symbols = [h["symbol"] for h in r.json()["results"]]
    assert symbols[0] == "AAP"        # exact
    assert "AAPL" in symbols          # prefix


def test_name_substring_matches(client) -> None:
    r = client.get("/research/search?q=microsoft", headers=AUTH)
    symbols = [h["symbol"] for h in r.json()["results"]]
    assert symbols == ["MSFT"]


def test_search_is_case_insensitive(client) -> None:
    r = client.get("/research/search?q=aapl", headers=AUTH)
    assert r.json()["results"][0]["symbol"] == "AAPL"


def test_etf_flag_is_returned(client) -> None:
    r = client.get("/research/search?q=SPY", headers=AUTH)
    assert r.json()["results"][0]["is_etf"] is True


def test_blank_query_returns_no_results_not_the_whole_table(client) -> None:
    r = client.get("/research/search?q=", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_limit_is_capped(client) -> None:
    r = client.get("/research/search?q=A&limit=999", headers=AUTH)
    assert r.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_search.py -v`
Expected: FAIL with `404` on `/research/search`

- [ ] **Step 3: Implement `src/api/routers/research.py`**

```python
"""Research routes: search today, the analysis payload from Milestone 3."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from src.api.deps import CurrentUser, ResearchDb
from src.api.models.common import Envelope
from src.research.store.models import SymbolRow

router = APIRouter(prefix="/research", tags=["research"])


class SearchHit(Envelope):
    symbol: str
    name: str
    exchange: str | None = None
    is_etf: bool = False


class SearchResponse(Envelope):
    query: str
    results: list[SearchHit]


@router.get("/search", response_model=SearchResponse)
def search(
    user: CurrentUser,
    db: ResearchDb,
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> SearchResponse:
    """Rank: exact ticker, then ticker prefix, then name substring."""
    now = datetime.now(UTC)
    term = q.strip()
    if not term:
        return SearchResponse(as_of=now, query=q, results=[])

    upper = term.upper()
    like_prefix = f"{upper}%"
    like_name = f"%{term.lower()}%"

    # Ranking bands: 0 exact ticker, 1 ticker prefix, 2 name substring.
    band = func.iif(
        SymbolRow.symbol == upper,
        0,
        func.iif(SymbolRow.symbol.like(like_prefix), 1, 2),
    ).label("band")

    stmt = (
        select(SymbolRow, band)
        .where(
            or_(
                SymbolRow.symbol.like(like_prefix),
                func.lower(SymbolRow.name).like(like_name),
            )
        )
        .order_by(band, SymbolRow.symbol)
        .limit(limit)
    )

    rows = db.execute(stmt).all()
    return SearchResponse(
        as_of=now,
        query=q,
        results=[
            SearchHit(
                as_of=now,
                symbol=r[0].symbol,
                name=r[0].name,
                exchange=r[0].exchange,
                is_etf=r[0].is_etf,
            )
            for r in rows
        ],
    )
```

`func.iif` is SQLite's conditional. If the research database ever moves to Postgres, replace
it with `sqlalchemy.case`; the rest of the query is portable.

- [ ] **Step 4: Register the router**

In `src/api/main.py`, add `from src.api.routers import meta, research` and
`app.include_router(research.router)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_search.py -v && ruff check . && mypy src`
Expected: 7 passed.

- [ ] **Step 6: Create `docs/web/api.md`**

Document every endpoint that exists so far: method, path, auth requirement, query parameters,
response shape, and an example response body for `/health`, `/me`, `/nav` and
`/research/search`. This file is updated by every later router task.

- [ ] **Step 7: Commit**

```bash
git add src/api/routers/research.py src/api/main.py docs/web/api.md tests/test_api_search.py
git commit -m "feat(api): add symbol search endpoint"
```

---

## Task 2.5 — Research worker process `[SONNET]`

Sonnet because this defines the process model and its failure behaviour: a job that throws must
not kill the scheduler, and a heartbeat that lies is worse than none.

**Files:**
- Create: `src/research/ingest/jobs.py`, `scripts/run_research_worker.py`
- Modify: `src/research/store/models.py` (add `WorkerHeartbeatRow`)
- Modify: `src/api/routers/meta.py` (populate `worker_heartbeat`)
- Modify: `SETUP.md`, `README.md`, `ARCHITECTURE.md`
- Test: `tests/test_research_worker.py`

**Interfaces:**
- Produces:
  - `WorkerHeartbeatRow(id: int, beat_at: datetime, last_job: str | None)`
  - `record_heartbeat(last_job: str | None) -> None`
  - `read_heartbeat() -> datetime | None`
  - `run_job(name: str, fn: Callable[[], object]) -> bool` — logs and swallows exceptions,
    returns success
  - `build_scheduler() -> BackgroundScheduler`

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_worker.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research.ingest.jobs'`

- [ ] **Step 3: Add the heartbeat model**

Append to `src/research/store/models.py`:

```python
class WorkerHeartbeatRow(Base):
    """Single-row table. Written only after a job SUCCEEDS, so /health cannot lie."""

    __tablename__ = "worker_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    beat_at: Mapped[datetime] = mapped_column(DateTime)
    last_job: Mapped[str | None] = mapped_column(String(64))
```

- [ ] **Step 4: Implement `src/research/ingest/jobs.py`**

```python
"""Job runner and scheduler for the research worker process.

Holds no IBKR connection. A job that raises is logged and swallowed: one failing source
must not take down the scheduler and every other job with it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.common.config import get_config
from src.research.ingest.symbols import refresh_symbol_directory
from src.research.store.models import WorkerHeartbeatRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def record_heartbeat(last_job: str | None) -> None:
    with research_session() as session:
        row = session.get(WorkerHeartbeatRow, 1)
        now = datetime.now(UTC)
        if row is None:
            session.add(WorkerHeartbeatRow(id=1, beat_at=now, last_job=last_job))
        else:
            row.beat_at = now
            row.last_job = last_job


def read_heartbeat() -> datetime | None:
    with research_session() as session:
        row = session.get(WorkerHeartbeatRow, 1)
        return row.beat_at if row else None


def run_job(name: str, fn: Callable[[], object]) -> bool:
    """Run a job, swallowing failures. Heartbeats only on success."""
    try:
        fn()
    except Exception:
        log.exception("Research job %r failed", name)
        return False
    record_heartbeat(name)
    return True


def build_scheduler() -> BackgroundScheduler:
    cfg = get_config().research.tiers
    sched = BackgroundScheduler(timezone=get_config().scheduler.timezone)

    sched.add_job(
        lambda: run_job("symbols", refresh_symbol_directory),
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="symbol_directory",
        replace_existing=True,
    )
    # Warm-tier refresh and the ingest_jobs drain are registered in Milestones 3 and 4.
    del cfg
    return sched
```

- [ ] **Step 5: Implement `scripts/run_research_worker.py`**

```python
"""Run the research ingestion worker.

    python -m scripts.run_research_worker

Holds no IBKR connection and no clientId. Writes only to data/research.db.
"""

from __future__ import annotations

import signal
import threading

from src.common.logging import setup_logging
from src.research.ingest.jobs import build_scheduler
from src.research.ingest.symbols import refresh_symbol_directory
from src.research.ingest.jobs import run_job
from src.research.store.session import init_research_db


def main() -> None:
    setup_logging()
    init_research_db()

    # Populate the directory on first start so search works immediately.
    run_job("symbols", refresh_symbol_directory)

    sched = build_scheduler()
    sched.start()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    sched.shutdown(wait=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Wire the heartbeat into `/health`**

In `src/api/routers/meta.py`, replace `worker_heartbeat=None` with:

```python
        worker_heartbeat=read_heartbeat(),
```
and add `from src.research.ingest.jobs import read_heartbeat`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_worker.py tests/test_api_meta.py -v && ruff check . && mypy src`
Expected: all passed.

- [ ] **Step 8: Verify end to end**

```bash
python -m scripts.run_research_worker &
sleep 30
curl -s -H "Authorization: Bearer $WEB_API_TOKEN" "http://127.0.0.1:8787/research/search?q=AAPL"
kill %1
```
Expected: a hit for AAPL with CIK-backed name, proving the real SEC fetch worked.

- [ ] **Step 9: Update the docs**

`SETUP.md` scripts table gains `python -m scripts.run_research_worker`. `README.md` layout
table gains the script. `ARCHITECTURE.md` gains the worker in its process model, stating that
neither new process holds a clientId.

- [ ] **Step 10: Commit**

```bash
git add src/research scripts/run_research_worker.py src/api/routers/meta.py SETUP.md README.md ARCHITECTURE.md tests/test_research_worker.py
git commit -m "feat(research): add ingestion worker process with honest heartbeat"
```

---

## Task 2.6 — Next.js scaffold, design tokens, fonts `[SONNET]`

Sonnet because this fixes every frontend convention. A raw `bg-gray-800` or a missing tabular
figure setting here is copied into thirty later components.

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/next.config.ts`,
  `web/tailwind.config.ts`, `web/postcss.config.mjs`, `web/app/globals.css`,
  `web/app/layout.tsx`, `web/app/page.tsx`, `web/lib/api.ts`, `web/CLAUDE.md`,
  `web/.env.local.example`
- Modify: `.gitignore` (add `web/node_modules`, `web/.next`, `web/.env.local`)

**Interfaces:**
- Produces:
  - `apiFetch<T>(path: string, init?: RequestInit): Promise<T>` reading
    `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_API_TOKEN`
  - CSS custom properties and Tailwind semantic aliases: `bg-background`, `bg-surface`,
    `bg-elevated`, `text-content`, `text-muted`, `border-border`, `text-gain`, `text-loss`,
    `text-unknown`, `ring-focus`
  - `npm run gen:api` regenerating `web/lib/api-types.ts` from the live `/openapi.json`

- [ ] **Step 1: Scaffold**

```bash
cd web
npx create-next-app@latest . --typescript --tailwind --app --eslint --src-dir=false --import-alias "@/*" --no-turbopack
npm install @tanstack/react-query lightweight-charts recharts cmdk clsx
npm install -D openapi-typescript vitest @testing-library/react @testing-library/jest-dom jsdom @vitejs/plugin-react
```

- [ ] **Step 2: Write `web/app/globals.css` with the token system**

```css
@import "tailwindcss";

/*
  Dark only in P1, deliberately. Every colour is consumed through a semantic token so a
  light theme later is a token file rather than a refactor. NEVER use a raw palette class
  (bg-white, bg-gray-800) or a hex literal in a component.
  Values from Web plan/P0-P1-design.md §8.3.
*/
:root {
  --bg-background: #121212;
  --bg-surface: #181818;
  --bg-elevated: #282828;

  --text-content: #f5f5f5;
  --text-muted: #a7a7a7;

  --border-border: #2c2c2c;

  /* Semantic only. Chrome is achromatic so these always mean something. */
  --color-gain: #4ade80;
  --color-loss: #f87171;
  --color-unknown: #6b6b6b;
  /* Focus and selection: deliberately neither cyan nor the gain green, so "selected"
     can never read as "up". */
  --color-focus: #7f9cf5;
}

@theme inline {
  --color-background: var(--bg-background);
  --color-surface: var(--bg-surface);
  --color-elevated: var(--bg-elevated);
  --color-content: var(--text-content);
  --color-muted: var(--text-muted);
  --color-border: var(--border-border);
  --color-gain: var(--color-gain);
  --color-loss: var(--color-loss);
  --color-unknown: var(--color-unknown);
  --color-focus: var(--color-focus);
}

html,
body {
  background: var(--bg-background);
  color: var(--text-content);
}

/* Numbers align in columns like a ledger. */
.tabular {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

/* The unknown state carries texture as well as colour, so it never reads as a zero
   and never depends on colour alone. */
.hatch {
  background-image: repeating-linear-gradient(
    45deg,
    var(--color-unknown) 0 2px,
    transparent 2px 5px
  );
}

::selection {
  background: var(--color-focus);
  color: var(--bg-background);
}

:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track {
  background: var(--bg-background);
}
::-webkit-scrollbar-thumb {
  background: var(--bg-elevated);
  border-radius: 6px;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 3: Write `web/app/layout.tsx` with the fonts**

```tsx
import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { Rail } from "@/components/shell/Rail";
import { Providers } from "@/app/providers";

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Research",
  description: "Stock research and options income console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="bg-background text-content font-sans antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Rail />
            <main className="flex-1 overflow-x-hidden">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
```

Add to `tailwind.config.ts`'s theme:
```ts
fontFamily: {
  sans: ["var(--font-sans)", "system-ui", "sans-serif"],
  mono: ["var(--font-mono)", "ui-monospace", "monospace"],
},
```

- [ ] **Step 4: Write `web/lib/api.ts`**

```ts
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8787";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}
```

`web/.env.local.example`:
```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8787
NEXT_PUBLIC_API_TOKEN=
```

- [ ] **Step 5: Add the type-generation script**

In `web/package.json` `"scripts"`:
```json
"gen:api": "openapi-typescript http://127.0.0.1:8787/openapi.json -o lib/api-types.ts"
```

Run it with the API up: `npm run gen:api`. Commit `lib/api-types.ts`.

- [ ] **Step 6: Write `web/CLAUDE.md`**

Record, as house law for this subtree: dark only; semantic tokens only, never a raw palette
class or hex literal; IBM Plex Sans and Mono with `.tabular` on every numeric column;
elevation by lightness, never border plus shadow stacked; state never encoded by colour
alone; zero em dashes in UI copy; banned words "seamless", "robust", "unlock", "elevate";
`prefers-reduced-motion` respected; charts never animate their data in.

- [ ] **Step 7: Verify**

```bash
cd web && npm run build && npm run lint
```
Expected: a clean production build.

- [ ] **Step 8: Commit**

```bash
git add web .gitignore
git commit -m "feat(web): scaffold Next.js app with the dark token system and Plex fonts"
```

---

## Task 2.7 — Left rail and shell `[GLM]`

**Files:**
- Create: `web/app/providers.tsx`, `web/components/shell/Rail.tsx`,
  `web/components/shell/RailSection.tsx`
- Test: `web/components/shell/Rail.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (2.6), `GET /nav` (1.6).
- Produces: `<Rail />` rendering five sections; unavailable sections render disabled with
  their `note` as the reason and are not links.

- [ ] **Step 1: Write the failing test**

`web/components/shell/Rail.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RailSection } from "./RailSection";

describe("RailSection", () => {
  it("renders an available section as a link", () => {
    render(<RailSection sectionKey="research" label="Research" available note={null} />);
    expect(screen.getByRole("link", { name: /research/i })).toBeDefined();
  });

  it("renders an unavailable section as disabled with its reason", () => {
    render(<RailSection sectionKey="options" label="Options" available={false} note="Arrives in P2" />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Arrives in P2")).toBeDefined();
  });

  it("marks an unavailable section aria-disabled rather than hiding it", () => {
    render(<RailSection sectionKey="pnl" label="P&L" available={false} note="Arrives in P4" />);
    expect(screen.getByRole("listitem").getAttribute("aria-disabled")).toBe("true");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/shell/Rail.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement `web/components/shell/RailSection.tsx`**

```tsx
import Link from "next/link";
import clsx from "clsx";

const HREF: Record<string, string> = {
  research: "/",
  options: "/options",
  portfolio: "/portfolio",
  pnl: "/pnl",
  universe: "/universe",
};

export function RailSection({
  sectionKey,
  label,
  available,
  note,
}: {
  sectionKey: string;
  label: string;
  available: boolean;
  note: string | null;
}) {
  const base = "block rounded-md px-3 py-2 text-sm transition-colors";

  if (!available) {
    return (
      <li aria-disabled="true" className={clsx(base, "text-muted cursor-default")}>
        <span className="flex items-center justify-between gap-2">
          <span>{label}</span>
          <span className="text-[11px] text-unknown">{note}</span>
        </span>
      </li>
    );
  }

  return (
    <li>
      <Link
        href={HREF[sectionKey] ?? "/"}
        className={clsx(base, "text-content hover:bg-surface focus-visible:bg-surface")}
      >
        {label}
      </Link>
    </li>
  );
}
```

- [ ] **Step 4: Implement `web/components/shell/Rail.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { RailSection } from "./RailSection";

type NavSection = {
  key: string;
  label: string;
  available: boolean;
  note: string | null;
};

type NavResponse = { as_of: string; sections: NavSection[] };

export function Rail() {
  const { data } = useQuery({
    queryKey: ["nav"],
    queryFn: () => apiFetch<NavResponse>("/nav"),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <nav className="w-[260px] shrink-0 border-r border-border bg-surface px-3 py-4">
      <div className="px-3 pb-6 font-mono text-sm text-muted">Research</div>
      <ul className="space-y-1">
        {(data?.sections ?? []).map((s) => (
          <RailSection
            key={s.key}
            sectionKey={s.key}
            label={s.label}
            available={s.available}
            note={s.note}
          />
        ))}
      </ul>
    </nav>
  );
}
```

Note the elevation rule: the rail uses `bg-surface` **plus** a border, and the page uses
`bg-background`. That is a border on a lightness change, not a border stacked on a shadow,
which is what the rule forbids.

- [ ] **Step 5: Implement `web/app/providers.tsx`**

```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            // Offline-first: keep showing the last good response rather than a spinner.
            placeholderData: (prev: unknown) => prev,
            retry: 1,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npx vitest run && npm run build`
Expected: 3 passed, clean build.

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat(web): add left rail driven by the nav manifest"
```

---

## Task 2.8 — Command-palette search `[GLM]`

**Files:**
- Create: `web/components/search/CommandPalette.tsx`, `web/app/stock/[symbol]/page.tsx`
- Modify: `web/app/page.tsx` (mount the palette and a visible search entry point)
- Test: `web/components/search/CommandPalette.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (2.6), `GET /research/search` (2.4).
- Produces: `<CommandPalette />` opening on `⌘K` / `Ctrl+K`, debounced at 200ms, navigating to
  `/stock/{symbol}` on select.

- [ ] **Step 1: Write the failing test**

`web/components/search/CommandPalette.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { CommandPalette } from "./CommandPalette";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async () => ({
    as_of: "2026-09-02T00:00:00Z",
    query: "AAP",
    results: [
      { symbol: "AAP", name: "Advance Auto Parts", exchange: "NYSE", is_etf: false },
      { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
    ],
  })),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

describe("CommandPalette", () => {
  beforeEach(() => push.mockClear());

  it("is closed until the shortcut fires", () => {
    render(<CommandPalette />);
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it("opens on meta+k", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
  });

  it("shows results and navigates on select", async () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "AAP" } });
    await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());
    fireEvent.click(screen.getByText("Apple Inc."));
    expect(push).toHaveBeenCalledWith("/stock/AAPL");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/search/CommandPalette.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement `web/components/search/CommandPalette.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
type SearchResponse = { as_of: string; query: string; results: Hit[] };

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!term.trim()) {
      setHits([]);
      return;
    }
    const id = setTimeout(async () => {
      try {
        const data = await apiFetch<SearchResponse>(
          `/research/search?q=${encodeURIComponent(term)}`,
        );
        setHits(data.results);
      } catch {
        setHits([]);
      }
    }, 200);
    return () => clearTimeout(id);
  }, [term]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[15vh]">
      <div className="w-full max-w-xl rounded-lg bg-elevated p-2">
        <input
          autoFocus
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Search a ticker or company"
          className="w-full bg-transparent px-3 py-2 font-mono text-sm text-content outline-none placeholder:text-muted"
        />
        <ul className="max-h-80 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  router.push(`/stock/${h.symbol}`);
                }}
                className="flex w-full items-baseline gap-3 rounded px-3 py-2 text-left hover:bg-surface focus-visible:bg-surface"
              >
                <span className="tabular font-mono text-sm text-content">{h.symbol}</span>
                <span className="truncate text-sm text-muted">{h.name}</span>
                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
              </button>
            </li>
          ))}
          {term.trim() && hits.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted">No match</li>
          )}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create the stub ticker page**

`web/app/stock/[symbol]/page.tsx`:

```tsx
export default async function StockPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  return (
    <div className="px-8 py-6">
      <h1 className="font-mono text-2xl text-content">{symbol.toUpperCase()}</h1>
      <p className="mt-2 text-sm text-muted">Analysis arrives in Milestone 3.</p>
    </div>
  );
}
```

- [ ] **Step 5: Mount the palette on the landing page**

In `web/app/page.tsx`, render `<CommandPalette />` and a visible button reading
`Search a ticker` with the hint `⌘K`, so the shortcut is discoverable rather than hidden.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npx vitest run && npm run build && npm run lint`
Expected: all passed, clean build.

- [ ] **Step 7: Verify end to end**

Start the API and the worker, then `cd web && npm run dev`. Press `⌘K`, type `NVDA`, press
Enter. Expected: navigation to `/stock/NVDA`.

- [ ] **Step 8: Commit**

```bash
git add web
git commit -m "feat(web): add command-palette search over the symbol directory"
```

---

## Milestone 2 exit criteria

- [ ] `python -m pytest -q`, `ruff check .`, `mypy src` all green
- [ ] `cd web && npm run build && npm run lint && npx vitest run` all green
- [ ] The worker populates `symbols` from a real SEC fetch
- [ ] `⌘K` searches the full directory and navigates to a ticker page
- [ ] No raw palette class or hex literal in any component (grep `bg-gray-`, `bg-white`, `#` in
      `web/components/`)
- [ ] `docs/web/api.md`, `SETUP.md`, `README.md`, `ARCHITECTURE.md` updated
