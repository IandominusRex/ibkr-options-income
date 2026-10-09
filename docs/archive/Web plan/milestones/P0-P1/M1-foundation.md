# Milestone 1 — Web Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stand up the API process, its auth boundary, the research database, and the two
structural fences, with nothing user-visible yet.

**Spec:** `Web plan/P0-P1-design.md` §4. **Index:** `Web plan/P0-P1-IMPLEMENTATION-PLAN.md` (read
Global Constraints first).

**Ends with:** `python -m scripts.run_api` serves `/health`, `/me` and `/nav` behind a bearer
token; `data/research.db` is created with its full schema; the trading database is provably
read-only from the API; the import fence test is green.

**Dependencies to add** to `pyproject.toml` `[project.optional-dependencies]`:
```toml
web = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "apscheduler>=3.10"]
```
(`httpx` is already a top-level dependency and doubles as the FastAPI `TestClient` transport.)

---

## File structure

| File | Responsibility |
|---|---|
| `config/research.yaml` | All research/API tunables |
| `src/common/config.py` | `ResearchCfg` models, wired into `Config` |
| `src/research/store/models.py` | Research `Base` and every research table |
| `src/research/store/session.py` | Research engine, session factory, `init_research_db()` |
| `src/api/models/common.py` | `Source`, `Sourced[T]`, `Envelope` |
| `src/api/auth.py` | `Role`, `User`, constant-time token check |
| `src/api/deps.py` | `current_user`, `require_owner`, DB session dependencies |
| `src/api/trading_db.py` | Read-only engine for `income_system.db` |
| `src/api/routers/meta.py` | `/health`, `/me`, `/nav` |
| `src/api/main.py` | App factory, middleware, exception handlers |
| `scripts/run_api.py` | uvicorn entrypoint |
| `tests/test_research_config.py` | Task 1.1 |
| `tests/test_research_store.py` | Task 1.2 |
| `tests/test_api_provenance.py` | Task 1.3 |
| `tests/test_api_auth.py` | Task 1.4 |
| `tests/test_api_trading_db_readonly.py` | Task 1.5 |
| `tests/test_api_meta.py` | Task 1.6 |
| `tests/test_web_fence.py` | Task 1.7 |

---

## Task 1.1 — Research configuration `[GLM]`

**Files:**
- Create: `config/research.yaml`
- Modify: `src/common/config.py` (add `ResearchCfg` and friends near `DataCfg` at line 286;
  add `research=` to the `Config` model and to `get_config()`'s constructor call)
- Modify: `.env.example` (add `WEB_API_TOKEN` and `SEC_CONTACT_EMAIL`)
- Test: `tests/test_research_config.py`

**Interfaces:**
- Consumes: `get_config()`, `ROOT`, `_load_yaml` from `src/common/config.py`.
- Produces:
  - `cfg.research.database.url: str`
  - `cfg.research.api.host: str`, `.port: int`, `.cors_origins: list[str]`
  - `cfg.research.tiers.materialization_budget_seconds: float`,
    `.warm_refresh_hour_et: int`, `.directory_refresh_days: int`
  - `cfg.research.providers.edgar.max_requests_per_second: float`, `.timeout_seconds: float`,
    `.user_agent_product: str`
  - `cfg.research.summary.backend: str`, `.model: str`, `.timeout_seconds: int`,
    `.cache_ttl_hours: int`
  - `cfg.research_db_url_abs() -> str`
  - `cfg.secrets.web_api_token: str`, `cfg.secrets.sec_contact_email: str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_config.py`:

```python
"""Research/API configuration loads with the documented defaults."""

from __future__ import annotations

from src.common.config import ROOT, get_config


def test_research_config_loads() -> None:
    cfg = get_config()
    assert cfg.research.database.url == "sqlite:///data/research.db"
    assert cfg.research.api.port == 8787
    assert cfg.research.tiers.materialization_budget_seconds == 8.0
    assert cfg.research.providers.edgar.max_requests_per_second == 10.0
    assert cfg.research.summary.backend == "claude_cli"


def test_research_db_url_resolves_against_project_root() -> None:
    cfg = get_config()
    resolved = cfg.research_db_url_abs()
    assert resolved.startswith("sqlite:///")
    assert resolved.endswith("/data/research.db")
    assert (ROOT / "data").as_posix() in resolved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_config.py -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'research'`

- [ ] **Step 3: Create `config/research.yaml`**

```yaml
# Research layer + web API settings. Secrets live in .env, NOT here.
# See Web plan/P0-P1-design.md for the design these keys implement.

database:
  # Second database, separate from storage.db_url on purpose: SQLite permits one
  # writer per database, and a nightly research ingest must never serialise against
  # approval_service's writes. See design §4.3.
  url: "sqlite:///data/research.db"

api:
  host: "127.0.0.1"       # loopback only; Tailscale interface when it goes remote
  port: 8787
  cors_origins:
    - "http://localhost:3000"

tiers:
  # Wall-clock budget for synchronous materialisation of a cold-tier symbol on first
  # view. Exceeding it returns a partial payload with pending sections plus an
  # ingest_job, never a blank screen. See design §5.5.
  materialization_budget_seconds: 8.0
  warm_refresh_hour_et: 4      # nightly warm-tier refresh, 04:00 ET
  directory_refresh_days: 7    # symbol directory refresh cadence

providers:
  edgar:
    # SEC requires a declared User-Agent carrying a contact address. The address comes
    # from .env (SEC_CONTACT_EMAIL); this is the product half of the string.
    user_agent_product: "IBKR-Income-System/1.0"
    max_requests_per_second: 10.0
    timeout_seconds: 20.0

summary:
  # claude_cli | anthropic | openai | ollama
  backend: "claude_cli"
  model: "claude-sonnet-4-6"
  timeout_seconds: 120
  cache_ttl_hours: 24
```

- [ ] **Step 4: Add the config models**

In `src/common/config.py`, after `class DataCfg` (line 286), add:

```python
class ResearchDatabaseCfg(BaseModel):
    url: str = "sqlite:///data/research.db"


class ResearchApiCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class ResearchTiersCfg(BaseModel):
    materialization_budget_seconds: float = 8.0
    warm_refresh_hour_et: int = 4
    directory_refresh_days: int = 7


class EdgarProviderCfg(BaseModel):
    user_agent_product: str = "IBKR-Income-System/1.0"
    max_requests_per_second: float = 10.0
    timeout_seconds: float = 20.0


class ResearchProvidersCfg(BaseModel):
    edgar: EdgarProviderCfg = Field(default_factory=EdgarProviderCfg)


class ResearchSummaryCfg(BaseModel):
    backend: str = "claude_cli"
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = 120
    cache_ttl_hours: int = 24

    @field_validator("backend")
    @classmethod
    def _known_backend(cls, v: str) -> str:
        allowed = {"claude_cli", "anthropic", "openai", "ollama"}
        if v not in allowed:
            raise ValueError(f"research.summary.backend must be one of {sorted(allowed)}, got {v!r}")
        return v


class ResearchCfg(BaseModel):
    database: ResearchDatabaseCfg = Field(default_factory=ResearchDatabaseCfg)
    api: ResearchApiCfg = Field(default_factory=ResearchApiCfg)
    tiers: ResearchTiersCfg = Field(default_factory=ResearchTiersCfg)
    providers: ResearchProvidersCfg = Field(default_factory=ResearchProvidersCfg)
    summary: ResearchSummaryCfg = Field(default_factory=ResearchSummaryCfg)
```

- [ ] **Step 5: Wire it into `Config` and `get_config()`**

Add to `class Config` (line 383), next to `data: DataCfg`:

```python
    research: ResearchCfg
```

Add the resolver method next to the existing `db_url_abs`:

```python
    def research_db_url_abs(self) -> str:
        """Resolve the relative research sqlite path against the project root."""
        url = self.research.database.url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url
```

In `get_config()`, add to the `Config(...)` call:

```python
        research=ResearchCfg(**_load_yaml("research.yaml")),
```

Add to `class Secrets`:

```python
    web_api_token: str = Field(default="", alias="WEB_API_TOKEN")
    sec_contact_email: str = Field(default="", alias="SEC_CONTACT_EMAIL")
```

- [ ] **Step 6: Update `.env.example`**

```bash
# Web API bearer token. Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
WEB_API_TOKEN=
# Contact address SEC EDGAR requires in the User-Agent header for its free APIs.
SEC_CONTACT_EMAIL=
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_config.py -v && ruff check . && mypy src`
Expected: 2 passed, no lint or type errors.

- [ ] **Step 8: Commit**

```bash
git add config/research.yaml src/common/config.py .env.example tests/test_research_config.py
git commit -m "feat(research): add research.yaml config and ResearchCfg models"
```

---

## Task 1.2 — Research database models and session `[GLM]`

**Files:**
- Create: `src/research/__init__.py`, `src/research/store/__init__.py`,
  `src/research/store/models.py`, `src/research/store/session.py`
- Test: `tests/test_research_store.py`

**Interfaces:**
- Consumes: `get_config()`, `cfg.research_db_url_abs()` from Task 1.1.
- Produces:
  - `src.research.store.models.Base` (a `DeclarativeBase` distinct from `src.storage.models.Base`)
  - ORM classes: `SymbolRow`, `CompanyFactsRawRow`, `FinancialRow`, `DailyBarRow`, `QuoteRow`,
    `NewsItemRow`, `AnalysisCacheRow`, `CheckResultRow`, `SummaryRow`, `WatchlistRow`,
    `WatchlistItemRow`, `RecentlyViewedRow`, `IngestJobRow`
  - `src.research.store.session.get_research_engine() -> Engine`
  - `src.research.store.session.research_session() -> Iterator[Session]` (context manager)
  - `src.research.store.session.init_research_db() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_store.py`:

```python
"""The research database is a separate schema with its own Base."""

from __future__ import annotations

import sqlalchemy as sa

from src.research.store import models as research_models
from src.research.store.session import init_research_db, research_session
from src.storage import models as trading_models


def test_research_base_is_not_the_trading_base() -> None:
    """A shared Base would let create_all() build either schema against either engine."""
    assert research_models.Base is not trading_models.Base


def test_init_creates_every_table(tmp_path, monkeypatch) -> None:
    db = tmp_path / "research.db"
    monkeypatch.setattr(
        "src.research.store.session._resolve_url", lambda: f"sqlite:///{db.as_posix()}"
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    names = set(sa.inspect(engine).get_table_names())
    assert {
        "symbols",
        "company_facts_raw",
        "financials",
        "daily_bars",
        "quotes",
        "news_items",
        "analysis_cache",
        "check_results",
        "summaries",
        "watchlists",
        "watchlist_items",
        "recently_viewed",
        "ingest_jobs",
    } <= names


def test_symbol_roundtrip(tmp_path, monkeypatch) -> None:
    db = tmp_path / "research.db"
    monkeypatch.setattr(
        "src.research.store.session._resolve_url", lambda: f"sqlite:///{db.as_posix()}"
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    with research_session() as s:
        s.add(research_models.SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))
    with research_session() as s:
        row = s.get(research_models.SymbolRow, "AAPL")
        assert row is not None
        assert row.cik == "0000320193"
        assert row.is_etf is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_research_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research'`

- [ ] **Step 3: Create the package and models**

`src/research/__init__.py` and `src/research/store/__init__.py` are empty files.

`src/research/store/models.py`:

```python
"""Research-database ORM models.

A SEPARATE SQLAlchemy Base from `src/storage/models.py`, deliberately. SQLite permits one
writer per database; a nightly research ingest writing into the trading database would
serialise against approval_service's writes, and the failure mode is a delayed trade
approval. Keeping the metadata separate also means `create_all()` can never build the wrong
schema against the wrong engine. See Web plan/P0-P1-design.md §4.3.

NEVER import `src.storage.models.Base` here.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Research schema root. Distinct from the trading schema's Base."""


class SymbolRow(Base):
    """The symbol directory: every SEC filer, refreshed weekly. Search reads this."""

    __tablename__ = "symbols"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    exchange: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))
    is_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class CompanyFactsRawRow(Base):
    """Raw EDGAR companyfacts payload, kept so normalisation is replayable.

    When the concept map gains a mapping, every affected symbol can be re-normalised
    without re-fetching from SEC.
    """

    __tablename__ = "company_facts_raw"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(String(128))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class FinancialRow(Base):
    """One normalised line item for one period, traceable to its filing."""

    __tablename__ = "financials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(8))  # "annual" | "quarterly"
    line_item: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    concept: Mapped[str | None] = mapped_column(String(128))
    accn: Mapped[str | None] = mapped_column(String(32))
    filed: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        Index("ix_financials_lookup", "symbol", "period_type", "line_item", "period_end"),
    )


class DailyBarRow(Base):
    __tablename__ = "daily_bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="stooq")


class QuoteRow(Base):
    """Delayed intraday quote for a warm-tier symbol. One row per symbol."""

    __tablename__ = "quotes"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    price: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(16), default="yfinance")


class NewsItemRow(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(64))
    sentiment: Mapped[float | None] = mapped_column(Float)


class AnalysisCacheRow(Base):
    """The assembled ticker-page payload. One row per symbol."""

    __tablename__ = "analysis_cache"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime)
    tier: Mapped[str] = mapped_column(String(8), default="cold")  # hot | warm | cold


class CheckResultRow(Base):
    __tablename__ = "check_results"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))  # PASS | FAIL | UNKNOWN | NOT_APPLICABLE
    actual: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class SummaryRow(Base):
    __tablename__ = "summaries"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_as_of: Mapped[datetime] = mapped_column(DateTime)
    payload_json: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime)


class WatchlistRow(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="owner")
    name: Mapped[str] = mapped_column(String(64), default="Default")


class WatchlistItemRow(Base):
    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime)


class RecentlyViewedRow(Base):
    __tablename__ = "recently_viewed"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="owner")
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime)


class IngestJobRow(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # fundamentals | prices | news | quote
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime)
```

- [ ] **Step 4: Create the session module**

`src/research/store/session.py`:

```python
"""Engine and session factory for `data/research.db`.

WAL mode, matching the trading database, so the API can read while the worker writes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.research.store.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for the research database. Patched in tests."""
    return get_config().research_db_url_abs()


def get_research_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = _resolve_url()
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True)

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def init_research_db() -> None:
    """Create every research table. Idempotent."""
    Base.metadata.create_all(get_research_engine())


@contextmanager
def research_session() -> Iterator[Session]:
    """Transactional scope around a research-database session."""
    get_research_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_store.py -v && ruff check . && mypy src`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/research tests/test_research_store.py
git commit -m "feat(research): add research.db schema and session factory"
```

---

## Task 1.3 — Provenance envelope `[SONNET]`

Sonnet because this sets the shape every later payload copies. Getting the generic wrong, or
letting `stale` be caller-supplied rather than derived, propagates into every endpoint.

**Files:**
- Create: `src/api/__init__.py`, `src/api/models/__init__.py`, `src/api/models/common.py`
- Test: `tests/test_api_provenance.py`

**Interfaces:**
- Produces:
  - `Source` (StrEnum): `EDGAR`, `YFINANCE`, `STOOQ`, `IBKR`, `COMPUTED`
  - `Sourced[T]` with fields `value: T | None`, `source: Source`, `as_of: datetime`,
    `stale: bool`
  - `Sourced.of(value, source, as_of, *, fresh_for: timedelta) -> Sourced[T]` classmethod that
    **derives** `stale`
  - `Envelope` base model with `as_of: datetime`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_provenance.py`:

```python
"""Every headline number carries its source and its age, and staleness is derived."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.api.models.common import Envelope, Source, Sourced


def test_sourced_is_generic_over_value_type() -> None:
    price: Sourced[float] = Sourced[float](
        value=191.24, source=Source.YFINANCE, as_of=datetime.now(UTC), stale=False
    )
    assert price.value == 191.24
    assert price.source == Source.YFINANCE


def test_of_marks_fresh_data_not_stale() -> None:
    s = Sourced.of(
        191.24, Source.YFINANCE, datetime.now(UTC) - timedelta(minutes=5),
        fresh_for=timedelta(minutes=30),
    )
    assert s.stale is False


def test_of_marks_old_data_stale() -> None:
    s = Sourced.of(
        191.24, Source.YFINANCE, datetime.now(UTC) - timedelta(hours=3),
        fresh_for=timedelta(minutes=30),
    )
    assert s.stale is True


def test_missing_value_is_representable_and_still_carries_provenance() -> None:
    """A number we could not get is None with a source, never a silent zero."""
    s = Sourced.of(None, Source.EDGAR, datetime.now(UTC), fresh_for=timedelta(days=1))
    assert s.value is None
    assert s.source == Source.EDGAR


def test_naive_as_of_is_treated_as_utc() -> None:
    """SQLite hands back naive datetimes; comparing them to an aware now() would raise."""
    s = Sourced.of(
        1.0, Source.EDGAR, datetime.utcnow() - timedelta(days=2),
        fresh_for=timedelta(days=1),
    )
    assert s.stale is True


def test_envelope_carries_top_level_as_of() -> None:
    class Payload(Envelope):
        symbol: str

    p = Payload(symbol="AAPL", as_of=datetime.now(UTC))
    assert p.symbol == "AAPL"
    assert p.as_of is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_provenance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api'`

- [ ] **Step 3: Implement**

`src/api/__init__.py` and `src/api/models/__init__.py` are empty.

`src/api/models/common.py`:

```python
"""Shared response primitives: provenance envelope and the response base.

Design §4.5: every headline number ships as {value, source, as_of, stale}, and every
response carries a top-level as_of. `stale` is DERIVED from as_of, never passed in by a
caller who might guess wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Source(StrEnum):
    """Where a number came from. A Black-Scholes delta must not look like an IBKR one."""

    EDGAR = "edgar"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    IBKR = "ibkr"
    COMPUTED = "computed"


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes. Treat naive as UTC rather than raising."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class Sourced(BaseModel, Generic[T]):
    """One value with its provenance. `value` is None when the data was unavailable."""

    value: T | None = None
    source: Source
    as_of: datetime
    stale: bool = False

    @classmethod
    def of(
        cls,
        value: T | None,
        source: Source,
        as_of: datetime,
        *,
        fresh_for: timedelta,
    ) -> Sourced[T]:
        """Build a Sourced, deriving `stale` from how old `as_of` is."""
        age = datetime.now(UTC) - _as_utc(as_of)
        return cls(value=value, source=source, as_of=as_of, stale=age > fresh_for)


class Envelope(BaseModel):
    """Base for every response body. Carries the payload-level freshness stamp."""

    as_of: datetime
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_provenance.py -v && ruff check . && mypy src`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api tests/test_api_provenance.py
git commit -m "feat(api): add Sourced provenance envelope and response base"
```

---

## Task 1.4 — Auth boundary `[SONNET]`

Sonnet because this is a security boundary. A timing-unsafe comparison or a route that forgets
`require_owner` is exactly the class of bug that only matters once the site is reachable.

**Files:**
- Create: `src/api/auth.py`, `src/api/deps.py`
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `get_config().secrets.web_api_token` from Task 1.1.
- Produces:
  - `Role` (StrEnum): `OWNER = "owner"`, `VIEWER = "viewer"`
  - `User` (BaseModel): `id: str`, `role: Role`
  - `authenticate(token: str | None) -> User | None`
  - `current_user` FastAPI dependency raising 401
  - `require_owner` FastAPI dependency raising 403
  - `research_db` FastAPI dependency yielding a `Session`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_auth.py`:

```python
"""The auth boundary: bearer token in, User out, owner-only routes gated."""

from __future__ import annotations

import pytest

from src.api.auth import Role, authenticate


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: "correct-horse-battery")


def test_no_token_is_rejected() -> None:
    assert authenticate(None) is None


def test_empty_token_is_rejected() -> None:
    assert authenticate("") is None


def test_wrong_token_is_rejected() -> None:
    assert authenticate("wrong") is None


def test_correct_token_yields_the_owner() -> None:
    user = authenticate("correct-horse-battery")
    assert user is not None
    assert user.id == "owner"
    assert user.role is Role.OWNER


def test_unconfigured_token_rejects_everything(monkeypatch) -> None:
    """An empty WEB_API_TOKEN must fail closed, never open."""
    monkeypatch.setattr("src.api.auth._configured_token", lambda: "")
    assert authenticate("") is None
    assert authenticate("anything") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.auth'`

- [ ] **Step 3: Implement `src/api/auth.py`**

```python
"""Authentication and the role model.

Today this returns a single owner for a valid bearer token. The seam is deliberate: when
the site goes multi-user, `authenticate` is what changes, and every route that already
depends on `current_user` keeps working unchanged. See design §4.4.
"""

from __future__ import annotations

import secrets
from enum import StrEnum

from pydantic import BaseModel

from src.common.config import get_config


class Role(StrEnum):
    OWNER = "owner"   # sees the book: positions, account, fills, campaigns
    VIEWER = "viewer" # research only


class User(BaseModel):
    id: str
    role: Role


def _configured_token() -> str:
    """Indirection so tests can patch the configured token without touching .env."""
    return get_config().secrets.web_api_token


def authenticate(token: str | None) -> User | None:
    """Return the user for a valid bearer token, or None.

    Fails closed when WEB_API_TOKEN is unset: an unconfigured deployment must reject
    everything rather than accept anything.
    """
    configured = _configured_token()
    if not configured or not token:
        return None
    if not secrets.compare_digest(token, configured):
        return None
    return User(id="owner", role=Role.OWNER)
```

- [ ] **Step 4: Implement `src/api/deps.py`**

```python
"""FastAPI dependencies: auth, and database sessions."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.api.auth import Role, User, authenticate
from src.research.store.session import research_session

_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    user = authenticate(creds.credentials if creds else None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_owner(user: CurrentUser) -> User:
    """Gate for anything exposing the book. Applied to P3/P4 routes when they land."""
    if user.role is not Role.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required"
        )
    return user


OwnerUser = Annotated[User, Depends(require_owner)]


def research_db() -> Iterator[Session]:
    with research_session() as session:
        yield session


ResearchDb = Annotated[Session, Depends(research_db)]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_auth.py -v && ruff check . && mypy src`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/api/auth.py src/api/deps.py tests/test_api_auth.py
git commit -m "feat(api): add bearer auth, role model, and owner gate"
```

---

## Task 1.5 — Read-only trading database access `[SONNET]`

Sonnet because "read-only" must be structurally true, not a convention. The test proves the
database itself rejects a write.

**Files:**
- Create: `src/api/trading_db.py`
- Test: `tests/test_api_trading_db_readonly.py`

**Interfaces:**
- Produces:
  - `read_only_url(db_path: str) -> str`
  - `get_trading_engine() -> Engine`
  - `trading_session() -> Iterator[Session]` (context manager, read-only)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_trading_db_readonly.py`:

```python
"""The API's handle on the trading database rejects writes at the SQLite layer."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from src.api.trading_db import read_only_url


def test_read_only_url_shape() -> None:
    url = read_only_url("/tmp/income_system.db")
    assert url == "sqlite:///file:/tmp/income_system.db?mode=ro&uri=true"


def test_reads_succeed_and_writes_are_refused(tmp_path) -> None:
    db = tmp_path / "income_system.db"

    # Build a database with a row, using a normal read-write engine.
    rw = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with rw.begin() as conn:
        conn.execute(sa.text("CREATE TABLE positions (symbol TEXT, qty INTEGER)"))
        conn.execute(sa.text("INSERT INTO positions VALUES ('AAPL', 100)"))
    rw.dispose()

    ro = sa.create_engine(read_only_url(db.as_posix()))

    with ro.connect() as conn:
        assert conn.execute(sa.text("SELECT qty FROM positions")).scalar_one() == 100

    with pytest.raises(OperationalError, match="readonly database"):
        with ro.connect() as conn:
            conn.execute(sa.text("INSERT INTO positions VALUES ('MSFT', 50)"))
            conn.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_trading_db_readonly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.trading_db'`

- [ ] **Step 3: Implement `src/api/trading_db.py`**

```python
"""Read-only access to the trading database.

The API reads positions, candidates and recommendations from `income_system.db` and writes
to it NEVER. That is enforced by SQLite itself through the `mode=ro` URI, not by convention:
an accidental INSERT raises OperationalError rather than corrupting operational state.
See design §4.3.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def read_only_url(db_path: str) -> str:
    """SQLAlchemy URL that opens `db_path` read-only via SQLite's URI filename syntax."""
    return f"sqlite:///file:{db_path}?mode=ro&uri=true"


def _resolve_path() -> str:
    url = get_config().db_url_abs()
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"Trading DB must be sqlite for read-only access, got {url!r}")
    return url[len(prefix) :]


def get_trading_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(read_only_url(_resolve_path()), future=True)
        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


@contextmanager
def trading_session() -> Iterator[Session]:
    """Read-only session against the trading database. Never commits."""
    get_trading_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_trading_db_readonly.py -v && ruff check . && mypy src`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/trading_db.py tests/test_api_trading_db_readonly.py
git commit -m "feat(api): open the trading database read-only, enforced by SQLite"
```

---

## Task 1.6 — App factory and meta routes `[SONNET]`

Sonnet because this is the first router and sets the pattern every later one copies: how
dependencies are declared, how errors are shaped, how `as_of` is stamped.

**Files:**
- Create: `src/api/routers/__init__.py`, `src/api/routers/meta.py`, `src/api/main.py`
- Modify: `README.md` (layout table), `ARCHITECTURE.md` (folder guide)
- Test: `tests/test_api_meta.py`

**Interfaces:**
- Consumes: `CurrentUser`, `ResearchDb` (1.4); `Envelope` (1.3); `get_trading_engine` (1.5).
- Produces:
  - `create_app() -> FastAPI`
  - `GET /health` → `HealthResponse{as_of, status, research_db, trading_db, worker_heartbeat}`
  - `GET /me` → `MeResponse{as_of, id, role}`
  - `GET /nav` → `NavResponse{as_of, sections: list[NavSection]}` where
    `NavSection{key, label, available, note}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_meta.py`:

```python
"""Health, identity, and the nav manifest that drives the left rail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app

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
    from src.research.store.session import init_research_db

    init_research_db()
    return TestClient(create_app())


def test_health_needs_no_auth(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degraded"}
    assert "as_of" in r.json()


def test_me_requires_auth(client) -> None:
    assert client.get("/me").status_code == 401


def test_me_returns_the_owner(client) -> None:
    r = client.get("/me", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["id"] == "owner"
    assert r.json()["role"] == "owner"


def test_nav_lists_every_section_with_availability(client) -> None:
    r = client.get("/nav", headers=AUTH)
    assert r.status_code == 200
    sections = {s["key"]: s for s in r.json()["sections"]}
    assert set(sections) == {"research", "options", "portfolio", "pnl", "universe"}
    assert sections["research"]["available"] is True
    # P2-P4 render a placeholder rather than being hidden, so the shape is visible.
    assert sections["options"]["available"] is False
    assert sections["options"]["note"]


def test_unknown_route_returns_json_not_html(client) -> None:
    r = client.get("/nope", headers=AUTH)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_meta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.main'`

- [ ] **Step 3: Implement `src/api/routers/meta.py`**

```python
"""Liveness, identity, and the navigation manifest."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter

from src.api.deps import CurrentUser, ResearchDb
from src.api.models.common import Envelope
from src.api.trading_db import get_trading_engine

router = APIRouter()


class HealthResponse(Envelope):
    status: str
    research_db: bool
    trading_db: bool
    worker_heartbeat: datetime | None = None


class MeResponse(Envelope):
    id: str
    role: str


class NavSection(Envelope):
    key: str
    label: str
    available: bool
    note: str | None = None


class NavResponse(Envelope):
    sections: list[NavSection]


# P2-P4 sections render an explicit placeholder rather than being hidden, so the finished
# shape of the product is legible from milestone 1. See design §9.
_SECTIONS: list[tuple[str, str, bool, str | None]] = [
    ("research", "Research", True, None),
    ("options", "Options", False, "Arrives in P2"),
    ("portfolio", "Portfolio", False, "Arrives in P3"),
    ("pnl", "P&L", False, "Arrives in P4"),
    ("universe", "Universe", True, None),
]


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health(db: ResearchDb) -> HealthResponse:
    now = datetime.now(UTC)

    research_ok = True
    try:
        db.execute(sa.text("SELECT 1"))
    except Exception:
        research_ok = False

    trading_ok = True
    try:
        with get_trading_engine().connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception:
        trading_ok = False

    return HealthResponse(
        as_of=now,
        status="ok" if research_ok and trading_ok else "degraded",
        research_db=research_ok,
        trading_db=trading_ok,
        worker_heartbeat=None,  # populated by the worker in Task 2.5
    )


@router.get("/me", response_model=MeResponse, tags=["meta"])
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(as_of=datetime.now(UTC), id=user.id, role=str(user.role))


@router.get("/nav", response_model=NavResponse, tags=["meta"])
def nav(user: CurrentUser) -> NavResponse:
    now = datetime.now(UTC)
    return NavResponse(
        as_of=now,
        sections=[
            NavSection(as_of=now, key=k, label=lbl, available=avail, note=note)
            for k, lbl, avail, note in _SECTIONS
        ],
    )
```

- [ ] **Step 4: Implement `src/api/main.py`**

```python
"""FastAPI application factory.

This process holds NO ib_async connection and therefore no clientId. It cannot reach the
broker, by construction. See design §4.2.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers import meta
from src.common.config import get_config

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(
        title="IBKR Income System — Web API",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.research.api.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(404)
    async def _not_found(_request: Request, _exc: Exception) -> JSONResponse:
        """JSON, never HTML: the client parses every response as JSON."""
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    app.include_router(meta.router)
    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_meta.py -v && ruff check . && mypy src`
Expected: 5 passed.

- [ ] **Step 6: Update the docs (mandatory, per `CLAUDE.md`)**

In `README.md`'s layout table add rows for `src/api/` ("FastAPI JSON API. No IBKR connection.")
and `src/research/` ("Research data layer: ingestion, normalisation, checks, summaries").

In `ARCHITECTURE.md`'s folder guide add the same two sections, and state the two-database rule
and the one-way import fence from design §4.3 and §4.7.

- [ ] **Step 7: Commit**

```bash
git add src/api README.md ARCHITECTURE.md tests/test_api_meta.py
git commit -m "feat(api): app factory with health, me, and nav routes"
```

---

## Task 1.7 — The import fence `[SONNET]`

Sonnet because this enforces a `CLAUDE.md` invariant, and a fence test that passes vacuously is
worse than none.

**Files:**
- Create: `tests/test_web_fence.py`
- Create: `src/research/checks/__init__.py`, `src/research/summary/__init__.py` (empty, so the
  fence is real from day one rather than vacuous)

**Interfaces:**
- Consumes: nothing. Reads source text.

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_fence.py`:

```python
"""The one-way import fence between the trading system and the web layer.

The web layer knows about the trading system. The trading system does not know the web layer
exists. See Web plan/P0-P1-design.md §4.7.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modules_under(*dirs: str) -> list[str]:
    """Every non-init module under the given src/ subdirectories, globbed not listed.

    Globbed for the same reason tests/test_eval_skills.py globs: a hand-maintained list goes
    stale the moment the path grows a module, and a fence test that silently stops covering
    new code is worse than no fence test.
    """
    return [
        str(p.relative_to(ROOT))
        for d in dirs
        for p in sorted((ROOT / "src" / d).glob("*.py"))
        if p.name != "__init__.py"
    ]


def test_trading_path_never_imports_the_web_layer() -> None:
    offenders = [
        rel
        for rel in _modules_under("engine", "execution", "strategies")
        if any(
            token in (ROOT / rel).read_text(encoding="utf-8")
            for token in ("src.api", "src.research")
        )
    ]
    assert not offenders, f"fence violated — web layer reachable from: {offenders}"


def test_checks_engine_never_imports_the_summary_layer() -> None:
    """The AI summary is enrichment. It must not reach the deterministic checks engine."""
    checks_dir = ROOT / "src" / "research" / "checks"
    assert checks_dir.is_dir(), "checks package must exist for this fence to be meaningful"
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted(checks_dir.glob("*.py"))
        if "src.research.summary" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"fence violated — summary reachable from checks: {offenders}"


def test_research_schema_does_not_share_the_trading_base() -> None:
    """A shared Base would let create_all() build either schema against either engine."""
    text = (ROOT / "src" / "research" / "store" / "models.py").read_text(encoding="utf-8")
    assert "src.storage.models" not in text


def test_the_api_never_constructs_a_broker_connection() -> None:
    """No ib_async anywhere under src/api/ or src/research/: no clientId, no placeOrder path."""
    offenders = [
        str(p.relative_to(ROOT))
        for d in ("api", "research")
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if "ib_async" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"web layer must hold no broker connection: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_fence.py -v`
Expected: FAIL on `test_checks_engine_never_imports_the_summary_layer` with
`AssertionError: checks package must exist for this fence to be meaningful`

- [ ] **Step 3: Create the empty packages**

```bash
mkdir -p src/research/checks src/research/summary
printf '"""Deterministic checks engine. Must never import src.research.summary."""\n' > src/research/checks/__init__.py
printf '"""Pluggable AI summary backends. Enrichment only; influences nothing."""\n' > src/research/summary/__init__.py
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_fence.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green, including the pre-existing 581-plus tests.

- [ ] **Step 6: Commit**

```bash
git add tests/test_web_fence.py src/research/checks src/research/summary
git commit -m "test(fence): enforce the one-way web/trading import boundary"
```

---

## Task 1.8 — Entrypoint and documentation `[GLM]`

**Files:**
- Create: `scripts/run_api.py`
- Modify: `pyproject.toml` (add the `web` optional dependency group)
- Modify: `SETUP.md` (scripts table), `README.md` (layout table), `STATUS.md`

**Interfaces:**
- Consumes: `create_app()` (1.6), `cfg.research.api.host/port` (1.1),
  `init_research_db()` (1.2).

- [ ] **Step 1: Add the dependency group**

In `pyproject.toml` under `[project.optional-dependencies]`:

```toml
web = ["fastapi>=0.115", "uvicorn[standard]>=0.30"]
```

Then: `pip install -e ".[web,dev]"`

- [ ] **Step 2: Create `scripts/run_api.py`**

```python
"""Run the web API.

    python -m scripts.run_api

Holds no IBKR connection and no clientId. Bound to config/research.yaml -> api.host,
which is loopback by default.
"""

from __future__ import annotations

import uvicorn

from src.common.config import get_config
from src.common.logging import setup_logging
from src.research.store.session import init_research_db


def main() -> None:
    setup_logging()
    init_research_db()
    cfg = get_config()
    uvicorn.run(
        "src.api.main:create_app",
        factory=True,
        host=cfg.research.api.host,
        port=cfg.research.api.port,
        log_level=cfg.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
```

`setup_logging()` is defined at `src/common/logging.py:119` and takes no arguments.

- [ ] **Step 3: Verify it starts and serves**

```bash
python -m scripts.run_api &
sleep 3
curl -s http://127.0.0.1:8787/health
curl -s -H "Authorization: Bearer $WEB_API_TOKEN" http://127.0.0.1:8787/nav
kill %1
```
Expected: `/health` returns `{"status":"ok",...}`; `/nav` returns five sections.

- [ ] **Step 4: Update the docs**

`SETUP.md` scripts table gains:

| `python -m scripts.run_api` | Web API (port 8787). Requires `WEB_API_TOKEN` in `.env`. No IBKR connection. |

`README.md` layout table gains `scripts/run_api.py`.

`STATUS.md` gains a "Web platform" section recording: P0 built; P1 in progress; P2 (options
console), P3 (portfolio), P4 (profitability tracker) and P5 (mobile) deliberately not built,
with `Web plan/OVERVIEW.md` named as the roadmap.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_api.py pyproject.toml SETUP.md README.md STATUS.md
git commit -m "feat(api): add run_api entrypoint and document the web layer"
```

---

## Milestone 1 exit criteria

- [ ] `python -m pytest -q` fully green
- [ ] `ruff check .` clean
- [ ] `mypy src` clean
- [ ] `python -m scripts.run_api` serves `/health`, `/me`, `/nav`
- [ ] `data/research.db` exists with all 13 tables
- [ ] `tests/test_web_fence.py` green with four real assertions
- [ ] `README.md`, `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md` updated
