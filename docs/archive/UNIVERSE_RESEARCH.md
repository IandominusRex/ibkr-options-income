# Universe Research — Options Income Strategy Reference

Deep-research findings (June 2026) on every ticker in `config/universe.yaml`.
Used by Claude Code when analysing the codebase and injected (in compact form) into the
trade-review prompt in `src/claude/prompts/strategist.py`.

**Last updated:** 2026-10-10 (operator-confirmed) — AVGO, VST and BE added to `watchlist:` +
`would_own` + `actively_wheeling`; CRWD promoted from dip-watch to `actively_wheeling`;
JPM/WMT/UBER/TSLA/IWM (all dip-watch) archived to `config/universe_archive.yaml` — see
"Additions — 2026-10-10" and "Archived — 2026-10-10" below. Prior update, 2026-09-29 — AMD un-archived back into `watchlist:` as
**CC-only** against the held 300-share position (not added to `would_own`); BAC added to
`watchlist:` + `would_own` + `actively_wheeling` (held 1000 sh, CC + CSP); DPST moved from the
CC-only leveraged set into the deliberate `would_own` exception, joining TQQQ/UPRO/SOXL — see the
"Additions — 2026-09-29" section below. Prior update, 2026-08-28 — second archive pass:
GLD/XLF/XLK/XLE/XLU/XLI/SLV/MA/HD/AMD/NET/SNOW/TTD/DDOG archived to `config/universe_archive.yaml`
(realistically won't-trade ETFs, one payments-network name kept, AMD too expensive vs. SMH/SOXL,
unfamiliar software names). Prior update, 2026-08-27 — tiers renamed Tier 1/2/3 → safe bets/moderate/risky (organizational
only, no change to the underlying research); `would_own` split into `actively_wheeling` (the core
rotation, scanned every intraday cycle) and dip-watch (would_own-eligible, but only scanned on a
≥3% drop — see `config/universe.yaml`); ARKK/LLY/COST/CRM/COIN/MSTR/BITO/CRCL archived to
`config/universe_archive.yaml`; MAGS/TQQQ/UPRO added, SOXL moved into `would_own` as a deliberate
leveraged-decay exception.  
**Originally published:** 2026-06-02  
**Source methodology:** 104 adversarial search agents; claims requiring ApexVol data were
rejected (ApexVol explicitly labels its IV rank / CSP yield tiles as "simulated — values are
deterministic per ticker and do not reflect today's market"). All prices and IV ranks below
are from independent sources (Unusual Whales, Barchart, FlashAlpha, Volradar, Market Chameleon,
projectoption.com) as of early June 2026.

---

## IV Rank methodology note

TastyTrade — the most authoritative practitioner source for premium-selling — targets
**IVR ≥ 50** before entering a new premium position. The system's `min_iv_rank: 30` in
`risk_limits.yaml` is a softer floor that lets candidates surface; Claude's review should
flag candidates with IVR 30–49 as "thin premium environment — consider waiting for higher IVR."

Typical monthly premium yields at the 0.30 delta:
- Mega-cap stable tech (AAPL, MSFT, GOOGL): **0.7–1.2% per cycle** in normal markets
- Elevated-IV names (NVDA, AMD, META, PLTR): **1.5–3.0% per cycle**
- High-IV speculative (MARA, RGTI, SOFI, HOOD): **3–8%+ per cycle**
- Leveraged ETFs (SOXL, LABU, TSLL): **5–15%+ per weekly cycle** (extreme)

---

## Safe bets — core income (fund-manager grade)

_Renamed from "Tier 1" 2026-08-27 — same names, same research, organizational label only. See
`config/universe.yaml` for exactly which of these are `actively_wheeling` (core rotation, scanned
every intraday cycle) vs dip-watch (would_own-eligible, scanned only on a ≥3% drop) — that split
does not track this tier grouping 1:1, e.g. GOOGL/NVDA/AMZN are actively_wheeling but AAPL/MSFT/JPM
are dip-watch._

### SPY — S&P 500 ETF
- **Price (June 2026):** ~$540  
- **IV rank typical range:** 15–35  
- **Monthly premium at 0.30Δ:** 0.8–2.5% (varies heavily with VIX; ~1.2% at VIX 18)  
- **CC:** ✅ — most liquid option chain in existence  
- **CSP:** ✅ — $54K collateral per contract; size accordingly  
- **Assignment:** Comfortable — you own a diversified index  
- **Notes:** The benchmark. ETFs don't have earnings events. Biggest single-day moves ~3–5%.

### QQQ — Nasdaq-100 ETF
- **Price (June 2026):** ~$470  
- **IV rank typical range:** 18–40  
- **Monthly premium at 0.30Δ:** ~1–2.5%  
- **CC:** ✅ | **CSP:** ✅  
- **Assignment:** Comfortable — tech-heavy index, no single-company earnings risk  
- **Notes:** Higher IV than SPY due to tech concentration; premium is notably better.

### IWM — Russell 2000 ETF — ARCHIVED 2026-10-10

Removed from `config/universe.yaml` 2026-10-10 (was dip-watch). See `config/universe_archive.yaml`
and the "Archived — 2026-10-10" section below. Research retained here for reference only:

- **Price (June 2026):** ~$200  
- **IV rank typical range:** 20–45  
- **Monthly premium at 0.30Δ:** ~1.5–3%  
- **CC:** ✅ | **CSP:** ✅  
- **Assignment:** Acceptable — small-cap ETF, more volatile than SPY/QQQ  
- **Notes:** Better premiums than SPY; more sensitive to rate environment.

### SMH — VanEck Semiconductor ETF
- **Price (June 2026):** ~$220  
- **IV rank typical range:** 28–55  
- **Monthly premium at 0.30Δ:** ~2–4%  
- **CC:** ✅ | **CSP:** ✅  
- **Assignment:** Acceptable — diversified semi exposure, no single-stock binary events  
- **Notes:** Good substitute for individual semi exposure (NVDA/AMD) with lower assignment risk.

### GLD — SPDR Gold Shares ETF — ARCHIVED 2026-08-28

Removed from `config/universe.yaml` (user says realistically won't trade it much). See
`config/universe_archive.yaml` for the archive entry and the "Archived — 2026-08-28" section
below. Research retained here for reference only:

- **Price (June 2026):** ~$250  
- **IV rank typical range:** 14–28  
- **Monthly premium at 0.30Δ:** ~0.8–1.5%  
- **CC:** was ✅ | **CSP:** was ✅  
- **Assignment:** gold as a store of value; decorrelates from equity drawdowns  
- **Notes:** Lower IV than equity ETFs, but excellent diversification. Useful when equity IV is depressed.

### AAPL — Apple
- **Price (June 2026):** ~$211  
- **IV rank typical range:** 18–40  
- **Monthly premium at 0.30Δ:** **0.8–1.2%** (verified; claims of 2–3% are inaccurate for normal environments)  
- **CC:** ✅ | **CSP:** ✅ (~$21,100 collateral)  
- **Assignment:** Comfortable — world's most profitable company, strong buybacks  
- **Notes:** Most liquid single-stock options. IV stays structurally lower than NVDA/AMD. Don't expect fat premiums.

### MSFT — Microsoft
- **Price (June 2026):** ~$413  
- **IV rank typical range:** 15–35  
- **Monthly premium at 0.30Δ:** **0.7–1.0%** (verified; average IV ~7–8% makes high premiums impossible)  
- **CC:** ✅ | **CSP:** ✅ (~$41,300 collateral)  
- **Assignment:** Comfortable — cloud/AI leader, strong cash flow, dividend  
- **Notes:** Lowest-IV large-cap. Great for stable CC income but don't expect significant yield.

### GOOGL — Alphabet
- **Price (June 2026):** ~$165  
- **IV rank typical range:** 22–45  
- **Monthly premium at 0.30Δ:** ~1–2%  
- **CC:** ✅ | **CSP:** ✅ (~$16,500 collateral)  
- **Assignment:** Comfortable — diversified revenue, search + cloud + AI  
- **Notes:** Better premium-per-dollar than MSFT. IV rank ~39 in recent data.

### JPM — JPMorgan Chase — ARCHIVED 2026-10-10

Removed from `config/universe.yaml` 2026-10-10 (was dip-watch). See `config/universe_archive.yaml`
and the "Archived — 2026-10-10" section below. Research retained here for reference only:

- **Price (June 2026):** ~$280  
- **IV rank typical range:** 20–40  
- **Monthly premium at 0.30Δ:** ~1–2%  
- **CC:** ✅ | **CSP:** ✅ (~$28,000 collateral)  
- **Assignment:** Comfortable — best-in-class bank, dividend payer, fortress balance sheet  
- **Notes:** Provides financials sector diversification. Good for CCs when IV spikes on rate/macro news.

### BAC — Bank of America

Added 2026-09-29 (operator-confirmed) — **held (1000 sh) — CC + CSP, actively wheeling.**
`watchlist:` + `would_own` + `actively_wheeling`.

- **IV rank typical range:** 20–40  
- **Monthly premium at 0.30Δ:** ~0.8–1.5%  
- **CC:** ✅ | **CSP:** ✅  
- **Assignment:** Comfortable — money-centre bank, held — CC + CSP, actively wheeling  
- **Notes:** Second financials name alongside JPM. Put in `actively_wheeling` (not dip-watch)
  deliberately — a low-vol bank would rarely trip the 3% dip-watch trigger on its own, so it's
  scanned every cycle instead of waiting for a drop.

---

## Moderate — active income (elevated IV, real fundamentals)

_Renamed from "Tier 2" 2026-08-27 — same names, same research, organizational label only._

### NVDA — NVIDIA
- **Price (June 2026):** **~$224** (not ~$130–$135; that was 2024/early-2025 data)  
- **IV rank (verified):** **32–64%** range depending on source; Barchart: 32, projectoption: 42, Volradar: 64  
- **Monthly premium at 0.30Δ:** ~2–4% in normal conditions  
- **CC:** ✅ | **CSP:** ✅ (~$22,400 collateral)  
- **Assignment:** Acceptable if bullish on AI infrastructure long-term  
- **Notes:** Highest-premium safe-bet-adjacent name. IV compressed from 50%+ cycle highs into 30–40% range as AI narrative matured. Still the best premium/quality tradeoff in mega-cap tech.

### AMZN — Amazon
- **Price (June 2026):** ~$205  
- **IV rank typical range:** 25–45  
- **Monthly premium at 0.30Δ:** ~1.5–3%  
- **CC:** ✅ | **CSP:** ✅ (~$20,500 collateral)  
- **Assignment:** Comfortable — AWS + retail + ads = diversified cash flows  
- **Notes:** Better premium than MSFT/AAPL with similar assignment safety.

### AMD — Advanced Micro Devices

Un-archived 2026-09-29 (operator-confirmed) — **held (300 sh) — CC only.** Archived 2026-08-28
(too expensive for this account's sizing vs. SMH/SOXL); back in `watchlist:` for CC income
against the held shares — deliberately **not** added to `would_own` (no CSPs). See
`config/universe_archive.yaml`'s header for the restore process and the "Additions — 2026-09-29"
section below.

- **Price (June 2026):** ~$130 (stale anchor — use the scan-time spot price)  
- **IV rank typical range:** 30–55  
- **Monthly premium at 0.30Δ:** ~1.5–3%  
- **CC:** ✅ (held — CC only) | **CSP:** ❌ — not in `would_own`  
- **Assignment:** N/A — CSPs are not offered on this name  
- **Notes:** Popular wheel stock. More accessible price than NVDA. IV stays elevated due to NVDA competition narrative. Stays out of `would_own` on purpose — CC income on the existing position only.

### META — Meta Platforms
- **Price (June 2026):** ~$640  
- **IV rank typical range:** 28–55  
- **Monthly premium at 0.30Δ:** ~2–4%  
- **CC:** ✅ | **CSP:** ✅ (~$64,000 collateral — large!)  
- **Assignment:** Comfortable — strong fundamentals since 2023 turnaround, FCF machine  
- **Notes:** One of the best premium/fundamentals combinations in the universe. High share price limits CSP sizing.

### PLTR — Palantir Technologies
- **Price (June 2026):** ~$158  
- **IV rank (verified June 2026):** **46.73**; IV 68.79%; implied weekly move ±4.9%  
- **Monthly premium at 0.30Δ:** ~3–5%  
- **CC:** ✅ | **CSP:** ✅ (~$15,800 collateral)  
- **Assignment:** Acceptable — AI/defence analytics with real government/commercial revenue  
- **Notes:** AI narrative keeps IV persistently elevated. IV rank 46.73 is in the "active selling" zone. Frequently appears in options activity reports alongside NVDA/META.

### SOFI — SoFi Technologies
- **Price (June 2026):** ~$18–19 (up 32% YTD in 2026)  
- **IV rank (verified June 2026):** **26.64** (Unusual Whales) — currently BELOW the `min_iv_rank: 30` filter  
- **ATM IV:** ~57.9%; HV20: ~46.8%; implied weekly move ±1.5%  
- **CC:** ✅ | **CSP:** ✅ (~$1,800–1,900 collateral — most accessible in the universe)  
- **Assignment:** Acceptable — fintech turnaround story, growing revenue, improving fundamentals  
- **Notes:** IV rank currently below 30 — the risk engine will correctly filter CSP candidates until IVR recovers. ATM IV of 57.9% is healthy but has been higher. Best accessible-account wheel name.

### HOOD — Robinhood Markets
- **Price (June 2026):** ~$90  
- **IV rank typical range:** 45–80  
- **Monthly premium at 0.30Δ:** ~3–6%  
- **CC:** ✅ | **CSP:** ✅ (~$9,000 collateral)  
- **Assignment:** Acceptable — retail brokerage in secular growth phase; crypto/retail activity drives revenue  
- **Notes:** Elevated IV from crypto correlation and retail trading volume cycles. Appears in active-options lists alongside PLTR and META.

### HIMS — Hims & Hers Health
- **Price (June 2026):** ~$35  
- **IV rank typical range:** 55–90  
- **Implied earnings move:** ±15.99% (verified)  
- **Monthly premium at 0.30Δ:** ~4–8%  
- **CC:** ✅ | **CSP:** ✅ (~$3,500 collateral)  
- **Assignment:** Acceptable with awareness — GLP-1/telehealth growth story; regulatory risk from FDA on compounded drugs  
- **Notes:** High IV driven by binary regulatory events around GLP-1 drug approvals. Earnings moves are large. Good premiums but require watching FDA calendar.

### BABA — Alibaba Group (ADR)
- **Price (June 2026):** ~$133 (+6% on June 2 on AI/UEFA news)  
- **IV rank typical range:** 35–55; 52-week range 31–55 (verified)  
- **Monthly premium at 0.30Δ:** ~2–4%  
- **CC:** ✅ | **CSP:** ⚠️ with caution (~$13,300 collateral)  
- **Assignment:** **Conditional** — ADR delisting/geopolitical risk means assignment could leave you holding a difficult-to-exit position if US-China tensions escalate. Keep per-ticker allocation small.  
- **Notes:** Strong analyst consensus (38 Buy, 1 Sell). IV elevated by China regulatory and geopolitical overhang. Reasonable premiums. Treat as moderate for CCs, extra caution for CSPs.

---

## Risky — speculative / high-IV

_Renamed from "Tier 3" 2026-08-27 — same names, same research, organizational label only._

### SOXL — Direxion 3× Semiconductor Bull ETF
- **Price (June 2026):** ~$25  
- **IV typical range:** 80–140%  
- **CC expected returns (verified):** 1.75–13.13% per trade; **182–534% annualized**  
- **CC:** ✅ — exceptional income if you own shares  
- **CSP:** ✅ — **as of 2026-08-27, a deliberate `would_own` exception** (confirmed: this account
  accepts daily-reset decay risk on assignment for SOXL specifically, alongside TQQQ/UPRO). The
  NAV-decay reasoning below still applies in full — this is an accepted risk, not a retraction of
  it — but SOXL is no longer blanket CSP-excluded the way LABU/TSLL are (DPST joined this
  exception set too, 2026-09-29).  
- **Historical range:** -85% (2022) to +227% (2023)  
- **Notes:** Sell short-dated (weekly/biweekly) OTM calls for CC income as before. If selling a
  CSP, size small — assignment through a sharp drawdown compounds leverage decay with the
  underlying's own move.

### LABU — Direxion 3× Biotech Bull ETF
- **Price (June 2026):** ~$20  
- **IV typical range:** 90–160%  
- **CC:** ✅ — very high premiums  
- **CSP:** ❌ — **NEVER**. Same leverage decay risk as SOXL, PLUS binary FDA event risk that can gap -40% in a session.  
- **Notes:** Even more dangerous than SOXL due to single-drug binary events. Use exclusively as CC income when you already hold shares.

### TSLL — Direxion 2× Tesla Bull ETF
- **Price (June 2026):** ~$15  
- **IV typical range:** 90–130%  
- **CC:** ✅ — low share price means low cost to own 100 shares; high premium  
- **CSP:** ❌ — leverage decay and TSLA correlation mean assignment is a trap  
- **Notes:** Low price (~$1,500 to own 100 shares) makes CC entry accessible. Sell short-dated OTM calls only.

### DPST — Direxion 3× Regional Banks Bull ETF
- **Price (June 2026):** ~$120  
- **IV typical range:** 70–110%  
- **CC:** ✅ — interest-rate sensitive; good premiums on rate announcement weeks  
- **CSP:** ✅ — **deliberate `would_own` exception (2026-09-29):** 3× regional banks, so
  assignment means holding a daily-reset product (SVB-style risk amplified 3×); size small and
  prefer short DTE, alongside TQQQ/UPRO/SOXL. No longer blanket CSP-excluded.  
- **Notes:** Options liquidity thinner than SOXL/TSLL. Verify OI > 100 before trading.

### MARA — MARA Holdings (Bitcoin miner)
- **Price (June 2026):** ~$15  
- **IV typical range:** 90–130%  
- **Monthly premium at 0.30Δ:** ~6–12%  
- **CC:** ✅ — bitcoin proxy with exceptional premiums  
- **CSP:** ⚠️ — in `would_own` (and `actively_wheeling` as of 2026-08-27) but treat as high-risk; BTC can halve in days, taking MARA with it  
- **Assignment caution:** If assigned, you own a Bitcoin miner that can lose 70%+ in a bear cycle  
- **Notes:** Premium income is real but so is the risk. The risk engine's `max_pct_per_ticker: 5%` cap limits exposure naturally. Best run as CC-only unless explicitly bullish on BTC.

### RGTI — Rigetti Computing (quantum computing)
- **Price (June 2026):** ~$8–12  
- **IV rank (verified):** IV mean ~86%; IV rank 9.52% (currently VERY LOW vs. history — current IV is cheaper than usual)  
- **Implied earnings move:** ±13.67%  
- **CC:** ✅ — speculative quantum play; premiums can be very high around catalysts  
- **CSP:** ⚠️ — in `would_own` (and `actively_wheeling` as of 2026-08-27) with small sizing; very early stage company  
- **Assignment caution:** Quantum computing is a decade-long bet; assignment means owning a pre-revenue (or very early revenue) company through multi-year development  
- **Notes:** IV rank at 9.52% means current options are cheap relative to history — not the best time to sell premium. Wait for IV rank > 40 before selling.

### CRCL — Circle Internet Group (stablecoin/crypto) — ARCHIVED 2026-08-27

Removed from `config/universe.yaml` (thin option liquidity, 57% off ATH, most speculative name
in the prior list). See `config/universe_archive.yaml` for the archive entry and the "Archived —
2026-08-27" section below. Research retained here for reference only:

- **Price (June 2026):** ~$113 (down from ATH $263 in June 2025 — off 57%)  
- **IV (verified):** ~173%; IV rank 28.04  
- **CC:** was ✅ — exceptional IV if you own shares; weekly options can yield 5–15%  
- **CSP:** was ❌ — **NOT in `would_own`**. Recent IPO (2025), 57% off ATH, thin option liquidity, crypto infrastructure regulatory risk  
- **Notes:** IV 173% is extraordinary but options liquidity is thin — verify bid/ask spreads and OI before entering. Not suitable for CSPs.

---

## TSLA — Tesla (moderate, added 2026-06-12) — ARCHIVED 2026-10-10

Removed from `config/universe.yaml` 2026-10-10 (was dip-watch). See `config/universe_archive.yaml`
and the "Archived — 2026-10-10" section below. Research retained here for reference only:


- **Price (June 2026):** ~$395–436  
- **IV:** structurally high absolute IV (40–70%), but IV *rank* was compressed (~22) in mid-2026 — high premium in dollar terms, low relative to TSLA's own history.  
- **CC:** ✅ — deepest single-stock options liquidity after AAPL; rich premium.  
- **CSP:** ✅ — in `would_own`; high beta, size with the per-ticker cap.  
- **Notes:** A core income staple (the glaring prior omission — TSLL the 2× ETF was listed but not the underlying). When IV rank is compressed the `min_iv_rank: 30` gate filters it automatically, so no manual gating needed. Watch the earnings/delivery-number calendar.

---

## Additions — 2026-06-12 (diversification batch)

Concise entries for names added to broaden the book away from its tech/crypto tilt. Prices are
spot-checked June 2026; IV descriptors are qualitative (verify IV **rank** on Barchart before
selling — see Data quality warning).

**Diversifier sector ETFs (all in `would_own`; liquid; defensives are LOW-IV → few signals). As
of 2026-08-27 all are dip-watch, not `actively_wheeling` — pulled into a scan only on a ≥3%
drop, never scanned every cycle. XLV/XLP/TLT are the thinnest on premium of the three, which is
part of why dip-watch treatment fits them (see `config/universe.yaml`). XLF/XLK/XLE/XLU/XLI/SLV
were archived 2026-08-28 — see the "Archived — 2026-08-28" section below:**

| Ticker | Price | Sector | IV character | CC | CSP | Notes |
|---|---|---|---|---|---|---|
| XLV | ~$154 | healthcare | low | ✅ | ✅ | defensive; thin premium |
| XLP | ~$85 | consumer | very low | ✅ | ✅ | staples; often below `min_iv_rank` |
| TLT | ~$86 | bonds | very low | ✅ | ✅ | rates hedge sleeve; rarely signals |

**Quality stocks added to `would_own`:**

- **V (~$324)** — payments-network moat; LOW IV (~12–28), large collateral; CC+CSP but expect modest yield. Dip-watch as of 2026-08-27. (MA was also added here but archived 2026-08-28 — user only wants one payments-network name.)
- ~~**WMT (~$120)**~~ — **archived 2026-10-10**, see below. Was: defensive consumer; liquid chain; moderate IV. Dip-watch as of 2026-08-27. (HD was also added here but archived 2026-08-28 — user will not trade it.)
- ~~**COIN (~$162)**~~ — **archived 2026-08-27**, see below. Was: liquid crypto-equity; high IV (60–100%); the cleanest crypto expression (far better liquidity than small miners). Crypto-correlated gap risk.

**Watchlist-only (CC-focused or CC-only):**

- **NBIS, CRWD, TEM, ASTS, IONQ** — high-IV software/AI/space/quantum names for CC (and CSP where in `would_own`). Note overlaps: CRWD/HACK (cybersecurity), IONQ/RGTI (quantum) are correlated theses. NBIS and ASTS moved into `actively_wheeling` 2026-08-27 (see below), CRWD on 2026-10-10; CRM was archived the same day. NET/SNOW/TTD/DDOG were also here but archived 2026-08-28 — user isn't familiar enough with those names to trade them.

**Removed 2026-06-12:**

- **BRK.B** — class-share symbol does not resolve on both data sources (yfinance `BRK-B` vs IBKR `BRK B`); empirically returned zero yfinance rows. Low-IV, illiquid options anyway. Dropped.
- **HUT, CLSK** — pure BTC miners, redundant with MARA + BITO; dropped to avoid quadrupling one correlated bet.
- **DIA** — low-IV "SPY-lite"; redundant with SPY and rarely clears the IV gate.

---

## Archived — 2026-08-27

Names the user has decided they'll clearly never trade, moved to `config/universe_archive.yaml`
(reference-only — nothing in the application loads that file). Full reasoning lives there; a
short pointer per ticker:

- **ARKK** — innovation-basket ETF; user will not trade it.
- **LLY (~$1,150)** — was watchlist-only/CC-focused above (~$115k CSP collateral, pharma trial
  risk); now fully archived, not just CC-focused.
- **COST (~$975)** — was watchlist-only/CC-focused above (~$97k CSP collateral); now fully
  archived, not just CC-focused.
- **CRM** — was in the high-IV software group above; user will not trade it.
- **COIN (~$162)** — was a `would_own` quality stock above; crypto-equity exposure user will not trade.
- **MSTR (~$125)** — was CC-only/leveraged-BTC-proxy above; user will not trade it.
- **BITO** — bitcoin futures ETF; futures-roll decay, redundant crypto exposure once COIN/MSTR
  are also archived.
- **CRCL** — see the dedicated (now-archived) section above; thin liquidity, most speculative
  name in the prior list.

To bring one back: reverse the process in `config/universe_archive.yaml`'s header comment, and
update this file plus `src/claude/prompts/strategist.py`'s `_UNIVERSE_CONTEXT` per CLAUDE.md's
doc-update table.

---

## Archived — 2026-08-28

A second trim, same reference-only treatment as above — moved to `config/universe_archive.yaml`:

- **GLD** — see the dedicated (now-archived) section above; user says realistically won't trade it much.
- **AMD** — too expensive for this account's sizing, user prefers SMH or SOXL for semiconductor exposure instead. **Un-archived 2026-09-29** as CC-only against the held 300-share position — see the AMD section above and "Additions — 2026-09-29" below; no longer in `config/universe_archive.yaml`.
- **XLF, XLK, XLE, XLU, XLI, SLV** — were in the diversifier-ETF table above; user says realistically won't trade them much.
- **MA (~$488)** — was a `would_own` quality stock above; user only wants one payments-network name, kept V instead.
- **HD (~$327)** — was a `would_own` quality stock above; user will not trade it.
- **NET, SNOW, TTD, DDOG** — were in the watchlist-only group above; user isn't familiar enough with these names to trade them.

To bring one back: reverse the process in `config/universe_archive.yaml`'s header comment, and
update this file plus `src/claude/prompts/strategist.py`'s `_UNIVERSE_CONTEXT` per CLAUDE.md's
doc-update table.

---

## Additions — 2026-09-29 (operator-confirmed)

- **AMD** — un-archived from `config/universe_archive.yaml` back into `watchlist:` (sector
  `semis`). **Held — CC only** against the existing 300-share position; deliberately not added
  to `would_own` — no CSPs. See the dedicated AMD section above.
- **BAC** — new to `watchlist:` (sector `financials`), and also to `would_own` +
  `actively_wheeling`. **Held — CC + CSP, actively wheeling**: a low-vol money-centre bank would
  rarely trip the 3% dip-watch trigger on its own, so it's placed in the core rotation instead of
  dip-watch. See the dedicated BAC section above.
- **DPST** — reclassified from the CC-only leveraged set into the deliberate `would_own`
  exception, joining TQQQ/UPRO/SOXL (also added to `actively_wheeling`). See the updated DPST
  section above and Key trading rule 3 below.

---

## Additions — 2026-10-10 (operator-confirmed)

All four go straight into `actively_wheeling` (and therefore `would_own`): CSP-eligible, on the
±0.5% materiality gate and the 120-min staleness net. Prices are **not** researched here —
the IV ranges are qualitative anchors only; verify IV **rank** on Barchart before relying on
them (see Data quality warning).

- **AVGO — Broadcom** (`watchlist:`, sector `semis`, safe bets). AI networking and custom
  accelerator silicon plus VMware software; deep, liquid chains. IV typically ~30–50%. CC ✅ |
  CSP ✅. **Large per-share price → large CSP collateral** — check it against
  `max_pct_per_ticker`. Overlaps the existing semis bucket (NVDA, AMD, SMH, SOXL), which will
  hit the 25% sector cap sooner.
- **CRWD — CrowdStrike** (already in `watchlist:`/`would_own`, sector `tech`; moderate).
  **Promoted from dip-watch to `actively_wheeling`.** Cybersecurity leader; IV typically
  ~35–55%, earnings moves are large. CC ✅ | CSP ✅. Large CSP collateral. Correlated with HACK.
- **VST — Vistra** (`watchlist:`, sector `utilities`; moderate). Merchant power generator
  (gas + nuclear) trading as an AI-datacenter power-demand name rather than a sleepy utility;
  IV typically ~45–65%. CC ✅ | CSP ✅. Reintroduces the `utilities` sector, archived 2026-08-28
  with XLU.
- **BE — Bloom Energy** (`watchlist:`, sector `energy`; risky). Solid-oxide fuel cells sold as
  on-site datacenter power; violent momentum swings, IV typically ~70–110%. CC ✅ | CSP ✅*
  (*speculative — cap sizing). Gets a `strike_bands: 0.45` override, like ASTS/RGTI, so the
  ~0.25Δ strike is in scope before its IV history is backfilled. Reintroduces the `energy`
  sector.

**VST + BE are one thesis** (AI power demand) in two different sector tags, so the
concentration cap will *not* catch them together — flag the correlation when both are open.

---

## Archived — 2026-10-10

Dip-watch trim, same reference-only treatment as above — moved to
`config/universe_archive.yaml`. None were held at the time.

- **JPM, IWM, TSLA** — see their dedicated (now-archived) sections above.
- **WMT** — was a `would_own` quality stock in the 2026-06-12 batch above.
- **UBER** — was a dip-watch mobility/delivery name in `watchlist:`.

To bring one back: reverse the process in `config/universe_archive.yaml`'s header comment, and
update this file plus `src/claude/prompts/strategist.py`'s `_UNIVERSE_CONTEXT` per CLAUDE.md's
doc-update table.

---

## Key trading rules derived from research

1. **Do not sell premium when IVR < 30.** The risk engine enforces this, but Claude should flag candidates near the floor as marginal.
2. **TastyTrade standard: wait for IVR ≥ 50** before entering new premium positions in ideal conditions. IVR 30–49 = acceptable but not ideal.
3. **Leveraged ETFs (LABU, TSLL):** CC-only. Assignment = NAV decay trap. Never sell CSPs.
   **TQQQ, UPRO, SOXL, and (since 2026-09-29) DPST are a deliberate exception** (TQQQ/UPRO/SOXL
   confirmed 2026-08-27; DPST confirmed 2026-09-29): this account accepts daily-reset decay risk
   on assignment for these four specifically — they're in `would_own` and `actively_wheeling`.
   The NAV-decay reasoning is unchanged; the risk is accepted, not absent.
4. **BABA:** Size conservatively (< `max_pct_per_ticker`). Flag ADR risk in every review.
5. **MARA, RGTI, BE:** The `max_pct_per_ticker: 5%` cap limits damage. Flag as speculative in every review.
6. **Earnings blackout:** The system enforces a 14-day blackout. Claude should call out if the DTE window is close to an expected earnings date that yfinance missed.
7. **Monthly premium reality check:** AAPL/MSFT rarely exceed 1.2%/month. Claims of 2–3%/month across all large-caps are marketing. Flag yield claims that seem too high.

---

## Data quality warning

Several popular wheel-strategy blogs (notably **ApexVol**) display IV rank and CSP yield
figures that are explicitly labelled "simulated — values are deterministic per ticker and do
not reflect today's market." Do not rely on these sites for live IV rank data. Use:

- **Barchart.com** — IV rank and percentile (reliable, near-real-time)
- **Unusual Whales** — IV rank, flow data
- **Market Chameleon** — IV rank history, skew
- **FlashAlpha** — ATM IV, GEX, HV
- **Volradar / projectoption.com** — IV rank cross-check

**Symbol format:** one ticker string feeds BOTH yfinance and IBKR. Class shares whose two data
sources disagree on the separator (e.g. Berkshire-B: yfinance `BRK-B` vs IBKR `BRK B`) do not
resolve on both and must NOT be added — they silently return no data and never produce candidates.

---

## Sector concentration reference

The risk engine caps sector exposure at 25% of net liquidation. Sector assignments in
`universe.yaml`:

| Sector | Tickers |
|---|---|
| `index` | QQQ, TQQQ, UPRO |
| `semis` | NVDA, AMD, AVGO, SMH, SOXL |
| `tech` | AAPL, MSFT, GOOGL, AMZN, MAGS, META, PLTR, RGTI, BABA, NBIS, CRWD, IONQ, HACK, IGV |
| `financials` | BAC, SOFI, HOOD, DPST, V |
| `consumer` | TSLL, XLP |
| `healthcare` | HIMS, TEM, XLV |
| `crypto` | MARA |
| `bonds` | TLT |
| `biotech` | LABU |
| `aerospace` | RKLB |
| `telecom` | ASTS |
| `utilities` | VST |
| `energy` | BE |

**Watch:** `tech` is still the largest bucket (~14 tickers, including MAGS) and will hit the
25% cap first on a strong tech morning — correct behaviour, and MAGS specifically double-counts
exposure already held via GOOGL/NVDA/AMZN, so watch it compound faster than the other names in
this bucket. The 2026-06-12 diversification batch deliberately grew the non-tech buckets
(consumer, financials, healthcare, plus bonds) so the engine has genuinely decorrelated names to
fall back on once the tech cap binds; the 2026-08-27 archive pass shrank `crypto` down to just
MARA (CRCL/COIN/MSTR/BITO archived), and the 2026-08-28 trim removed the `commodities`,
`energy`, `utilities`, and `industrials` sectors entirely (GLD/SLV, XLE, XLU, XLI archived) —
one fewer decorrelation lever if the tech cap ever binds hard. The 2026-10-10 change brought
`utilities` (VST) and `energy` (BE) back, but as a single correlated AI-power bet, not a
defensive one; it also thinned `consumer` to TSLL/XLP (TSLA/WMT/UBER archived) and grew `semis`
with AVGO.
