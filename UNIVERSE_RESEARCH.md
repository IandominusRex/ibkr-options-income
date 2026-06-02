# Universe Research — Options Income Strategy Reference

Deep-research findings (June 2026) on every ticker in `config/universe.yaml`.
Used by Claude Code when analysing the codebase and injected (in compact form) into the
trade-review prompt in `src/claude/prompts/strategist.py`.

**Last updated:** 2026-06-02  
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

## Tier 1 — Core income (fund-manager grade)

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

### IWM — Russell 2000 ETF
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

### GLD — SPDR Gold Shares ETF
- **Price (June 2026):** ~$250  
- **IV rank typical range:** 14–28  
- **Monthly premium at 0.30Δ:** ~0.8–1.5%  
- **CC:** ✅ | **CSP:** ✅  
- **Assignment:** Comfortable — gold as a store of value; decorrelates from equity drawdowns  
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

### JPM — JPMorgan Chase
- **Price (June 2026):** ~$280  
- **IV rank typical range:** 20–40  
- **Monthly premium at 0.30Δ:** ~1–2%  
- **CC:** ✅ | **CSP:** ✅ (~$28,000 collateral)  
- **Assignment:** Comfortable — best-in-class bank, dividend payer, fortress balance sheet  
- **Notes:** Provides financials sector diversification. Good for CCs when IV spikes on rate/macro news.

---

## Tier 2 — Active income (elevated IV, real fundamentals)

### NVDA — NVIDIA
- **Price (June 2026):** **~$224** (not ~$130–$135; that was 2024/early-2025 data)  
- **IV rank (verified):** **32–64%** range depending on source; Barchart: 32, projectoption: 42, Volradar: 64  
- **Monthly premium at 0.30Δ:** ~2–4% in normal conditions  
- **CC:** ✅ | **CSP:** ✅ (~$22,400 collateral)  
- **Assignment:** Acceptable if bullish on AI infrastructure long-term  
- **Notes:** Highest-premium Tier 1-adjacent name. IV compressed from 50%+ cycle highs into 30–40% range as AI narrative matured. Still the best premium/quality tradeoff in mega-cap tech.

### AMZN — Amazon
- **Price (June 2026):** ~$205  
- **IV rank typical range:** 25–45  
- **Monthly premium at 0.30Δ:** ~1.5–3%  
- **CC:** ✅ | **CSP:** ✅ (~$20,500 collateral)  
- **Assignment:** Comfortable — AWS + retail + ads = diversified cash flows  
- **Notes:** Better premium than MSFT/AAPL with similar assignment safety.

### AMD — Advanced Micro Devices
- **Price (June 2026):** ~$130  
- **IV rank typical range:** 35–65  
- **Monthly premium at 0.30Δ:** ~2–4%  
- **CC:** ✅ | **CSP:** ✅ (~$13,000 collateral)  
- **Assignment:** Acceptable — real AI/data-centre revenue, though volatile  
- **Notes:** Popular wheel stock. More accessible price than NVDA. IV stays elevated due to NVDA competition narrative.

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
- **Notes:** Strong analyst consensus (38 Buy, 1 Sell). IV elevated by China regulatory and geopolitical overhang. Reasonable premiums. Treat as Tier 2 for CCs, Tier 3 caution for CSPs.

---

## Tier 3 — Speculative / High-IV

### SOXL — Direxion 3× Semiconductor Bull ETF
- **Price (June 2026):** ~$25  
- **IV typical range:** 80–140%  
- **CC expected returns (verified):** 1.75–13.13% per trade; **182–534% annualized**  
- **CC:** ✅ — exceptional income if you own shares  
- **CSP:** ❌ — **NEVER**. Daily leverage reset causes structural NAV decay. Being assigned 100 shares through a -50% drawdown is catastrophic. SOXL lost -85% in 2022.  
- **Historical range:** -85% (2022) to +227% (2023)  
- **Notes:** Sell short-dated (weekly/biweekly) OTM calls. Only viable as CC income tool. Never hold as a long-term position naked.

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
- **CSP:** ❌ — 3× leverage on regional banks (SVB-style risk amplified 3×)  
- **Notes:** Options liquidity thinner than SOXL/TSLL. Verify OI > 100 before trading.

### MARA — MARA Holdings (Bitcoin miner)
- **Price (June 2026):** ~$15  
- **IV typical range:** 90–130%  
- **Monthly premium at 0.30Δ:** ~6–12%  
- **CC:** ✅ — bitcoin proxy with exceptional premiums  
- **CSP:** ⚠️ — technically in `would_own` but treat as high-risk; BTC can halve in days, taking MARA with it  
- **Assignment caution:** If assigned, you own a Bitcoin miner that can lose 70%+ in a bear cycle  
- **Notes:** Premium income is real but so is the risk. The risk engine's `max_pct_per_ticker: 5%` cap limits exposure naturally. Best run as CC-only unless explicitly bullish on BTC.

### RGTI — Rigetti Computing (quantum computing)
- **Price (June 2026):** ~$8–12  
- **IV rank (verified):** IV mean ~86%; IV rank 9.52% (currently VERY LOW vs. history — current IV is cheaper than usual)  
- **Implied earnings move:** ±13.67%  
- **CC:** ✅ — speculative quantum play; premiums can be very high around catalysts  
- **CSP:** ⚠️ — technically in `would_own` with small sizing; very early stage company  
- **Assignment caution:** Quantum computing is a decade-long bet; assignment means owning a pre-revenue (or very early revenue) company through multi-year development  
- **Notes:** IV rank at 9.52% means current options are cheap relative to history — not the best time to sell premium. Wait for IV rank > 40 before selling.

### CRCL — Circle Internet Group (stablecoin/crypto)
- **Price (June 2026):** ~$113 (down from ATH $263 in June 2025 — off 57%)  
- **IV (verified):** ~173%; IV rank 28.04  
- **CC:** ✅ — exceptional IV if you own shares; weekly options can yield 5–15%  
- **CSP:** ❌ — **NOT in `would_own`**. Recent IPO (2025), 57% off ATH, thin option liquidity, crypto infrastructure regulatory risk  
- **Notes:** IV 173% is extraordinary but options liquidity is thin — verify bid/ask spreads and OI before entering. Not suitable for CSPs.

---

## TSLA — Tesla (not in current universe, for reference)

- **Price (June 2026):** ~$415–436  
- **IV rank (verified June 2026):** **~22; IV percentile ~14.68% ("Low")** — TSLA is in a LOW IV environment  
- **Notes:** Frequently cited as a high-IV wheel stock but currently in a compressed-IV regime. Premium selling on TSLA is unattractive right now. The system's `min_iv_rank: 30` would correctly filter it. If TSLA is added to the universe, only trade when IVR > 40.

---

## Key trading rules derived from research

1. **Do not sell premium when IVR < 30.** The risk engine enforces this, but Claude should flag candidates near the floor as marginal.
2. **TastyTrade standard: wait for IVR ≥ 50** before entering new premium positions in ideal conditions. IVR 30–49 = acceptable but not ideal.
3. **Leveraged ETFs (SOXL, LABU, TSLL, DPST):** CC-only. Assignment = NAV decay trap. Never sell CSPs.
4. **BABA:** Size conservatively (< `max_pct_per_ticker`). Flag ADR risk in every review.
5. **MARA, RGTI:** The `max_pct_per_ticker: 5%` cap limits damage. Flag as speculative in every review.
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

---

## Sector concentration reference

The risk engine caps sector exposure at 25% of net liquidation. Sector assignments in
`universe.yaml`:

| Sector | Tickers |
|---|---|
| `index` | SPY, QQQ, IWM |
| `semis` | NVDA, AMD, SMH, SOXL |
| `tech` | AAPL, MSFT, GOOGL, AMZN, META, PLTR, RGTI, BABA, TSLL |
| `financials` | JPM, SOFI, HOOD, DPST |
| `healthcare` | HIMS |
| `commodities` | GLD |
| `crypto` | MARA, CRCL |

**Watch:** The `tech` bucket is large (9 tickers). In a morning where NVDA, AAPL, MSFT, and
GOOGL all score well, the 25% cap will reject the 3rd/4th tech candidate. This is correct
behaviour — the system is working as designed.
