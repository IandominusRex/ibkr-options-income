# Bulk price data source — licence check (Task 4.1)

`BulkPriceProvider` (`src/data/protocols.py`) serves the cold tier: daily OHLCV for any US
ticker a user views for the first time, where a keyed per-symbol API would be too expensive to
call on every cache miss. stooq was the plan's first choice; the licence check below ruled it
out, so only `YFinanceBulkPriceProvider` satisfies the Protocol today — selected by
`config/settings.yaml → data.bulk_price_provider`.

## Verdict: **not permitted** — stooq is not usable for unattended automated access

**Checked:** 2026-09-04
**URLs checked:** `https://stooq.com`, `https://stooq.com/q/d/l/?s=aapl.us&i=d` (the exact CSV
download endpoint `StooqBulkPriceProvider` would call)

**Finding:** As of this check, every request to stooq.com — including the CSV download endpoint
itself, not just the marketing site — returns a 200 response wrapping a client-side
proof-of-work bot-verification challenge (a `crypto.subtle.digest` SHA-256 puzzle solved in the
browser, then POSTed to `/__verify` before the real page or CSV is served), rather than data. A
plain server-side HTTP client (`httpx`, `requests`) receives only the challenge HTML and can
never complete the JS-executed proof-of-work, so `StooqBulkPriceProvider.get_daily_bars` as
specified in this task (a stateless `httpx.Client().get(...)`) would return an empty frame on
every call, in production, forever — not intermittently, structurally.

Independent corroboration ([api-evangelist/stooq](https://github.com/api-evangelist/stooq)):
stooq now requires an API key obtained via an on-site CAPTCHA (a change dated "early 2026"), with
an unpublished daily quota per key, and quota-exceeded responses arrive as HTTP 200 with an error
body rather than a 4xx/5xx — consistent with what the direct check above found.

This is a technical access-control change on stooq's side (bot verification + a manually
provisioned, CAPTCHA-gated API key), not a documented redistribution restriction — but it rules
out the "free, keyless, server-side CSV fetch" design this task and `P0-P1-design.md` §"Data
providers" call for. Standing up a CAPTCHA-solving flow, or a human re-provisioning an API key by
hand on a schedule, conflicts with this system's unattended-operation model (`src/research/` runs
as an unattended background worker — see `ARCHITECTURE.md`) and is out of scope for the cold
tier's job of serving cheap bulk EOD bars.

**Decision:** ship `YFinanceBulkPriceProvider` only. `data.bulk_price_provider: yfinance` in
`config/settings.yaml`. `src/data/stooq_backend.py` is not created. Per this task's design, the
`BulkPriceProvider` Protocol is what the rest of the system depends on (`ingest_daily_bars`,
`get_bulk_price_provider()`), so nothing downstream changes if stooq becomes viable later — only
the config value and a new backend file would need to land.

## Revisiting this later

If stooq ships a documented, keyless (or key-on-request, not CAPTCHA-gated) HTTP API in the
future, re-run this check against the same two URLs, update the verdict above with a new date,
and flip `data.bulk_price_provider` to `stooq` once `StooqBulkPriceProvider` exists and its tests
pass — no other module needs to change.
