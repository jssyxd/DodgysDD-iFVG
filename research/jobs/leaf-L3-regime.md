# Leaf L3 — Regime: is VXN / VIX correlated, and does it reach the decision?

## Context
Project: `/home/da/桌面/DodgysDD_ifvg`. The design discussion (L103–109) makes the Nasdaq-100 volatility
index the **market-regime** driver, and the migration table (L159–163) assigns a regime index per market.

**Read-only audit leaf.** Own exactly one file: `research/audit/L3_REGIME.md`.

## Required reading
- `.herd-swarm/decisions.md` — **D5** (data reality: VXN exists, **VIX does not**), **D9** (costs),
  **D4** (the honest baseline).
- `research/analysis/DATA_ACQUISITION.md` — the lake state and what was ingested.
- `research/docs/RULE_SPEC.md` — the feature list and the ambiguity register.
- `research/audit/AUDIT.md`.
- The discussion L103–109 (regime design) and L144–146 (the ML feature list) and L151 (RL state) and
  L159–163 (migration table).
- The VXN series: `~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/macro/vxn/VXN_1d_consolidated.parquet`
  (read-only; NFS lake, canonical) — 4,327 daily bars, 2009-09-14 → 2026-11-20.

## The question
**Q4 — Is VXN / VIX (and related regime variables) (a) subjected to a correlation check, and (b) actually
wired into the strategy and the order decision?**

## Your task → `research/audit/L3_REGIME.md`

### A. Implementation status
Search the repo for any use of VXN, VIX, DVOL, GVZ, "regime", "volatility index", and for any
correlation analysis or feature-importance report. For each hit: file+line and what it does.
State plainly whether a **correlation check** and a **regime → order-decision path** exist, or are absent.

### B. Data availability, measured
Inventory every regime-capable series actually present, with its coverage and granularity:
- VXN (daily, CBOE) — confirm on disk.
- VIX — **is it present anywhere?** (lake `macro/`, `equities_indices/`, the databank, the HF
  `twelvedata/financial-world-model` dataset which has a `vix_level` column, yfinance `^VXN`/`^VIX`).
  Check the lake's own directories and the databank MANIFEST.
- DVOL (Deribit) — `macro/dvol/BTCDVOL_1h_consolidated.parquet`.
- GVZ (gold), and the FTX/CME indices the migration table names (GSPC/VIX/VXN/DXY).
- Crypto equivalents: `crypto_indices/CMC20/cmc20_15m_signals.parquet`, funding rate, `bar_ofi`.
For each: coverage, granularity, and whether it is **lagged** correctly (the regime variable must be
knowable at decision time).

### C. The correlation check that has NOT been done — and how to do it
Design it concretely. This is the deliverable the user explicitly asked about ("VXN、VIX等是否纳入相关性校验").
- What is the hypothesis? (e.g. does the iFVG signal's expectancy depend on the VXN regime?)
- What is the **test**? Specify: the unit of analysis (a candidate setup), the outcome (R multiple),
  the grouping variable (VXN regime band 0/1/2), the estimator (conditional expectancy with a CI,
  plus a permutation/bootstrap test that respects time ordering), and the **multiple-testing**
  correction given we will test several market/volatility variables (state the method and the number of
  comparisons).
- The **look-ahead** traps: VXN is a *daily* index, so intraday alignment must use the **previous
  close**; the `shift(1).bfill()` pattern in the doc; and the fact that a daily index cannot produce
  the doc's "1-hour VXN change rate" (already dropped per the user's decision) — state the consequence
  for what can be tested.
- A **power** calculation: with the candidate counts actually available (e.g. 423,759 candidates /
  15,928 one-at-a-time trades on BTCUSDT 1m), what effect size is detectable at 80 % power? Give the
  minimum detectable difference in R.
- Specify the **exact code-level interface** the regime layer must expose so that the rule engine can
  consume it, and the two candidate-log columns it fills (`vxn_known`, `vxn_regime` — frozen in D2).

### D. Is a regime-conditioned strategy even the right hypothesis here?
Given D4 (the rule engine's expectancy is ~0 and no arm's CI excludes zero), argue honestly:
- if the unconditional edge is zero, is a regime-conditioned edge plausible? What would have to be true?
- what is the **cost** of regime conditioning: fewer trades per fold, wider CIs, more overfitting risk
  (a regime × window × ATR × sweep grid is already 32 arms — how many more would the regime add)?
- state the **minimum experiment** that would settle it, and its expected duration.

### E. Where the regime variable must enter (and where it must NOT)
The discussion has the regime in three places: the rule engine's filter (low-vol → A+ only), the ML
feature set, and the RL state. For each, say:
- whether it is currently implemented;
- what the **correct** entry point is;
- the **concrete gate/parameter** it should drive (the doc: low-vol → A+ only and RR 1:1.5–1:2;
  normal → RR 1:2.5–1:3; high-vol → halve risk and raise the ATR gap floor);
- and the leakage risk if it is wired in wrongly (e.g. using the *same day's* VXN close for a trade that
  happened at 09:30 ET — is that look-ahead? argue precisely, because the VXN close is published after
  the cash close).

### F. Verdict
```
CORRELATION CHECK IMPLEMENTED:  yes / no
REGIME IN STRATEGY:             yes / no / partial
REGIME IN ORDER DECISION:       yes / no / partial
REGIME IN ML FEATURES:          yes / no / partial
REGIME IN RL STATE:             yes / no / partial
```

## Constraints
- Write **only** `research/audit/L3_REGIME.md` (create `research/audit/` if needed).
- Read-only elsewhere. The NFS lake is shared — do not write to it.
- You MAY run read-only analysis (pandas/polars) on the lake data to compute descriptive statistics
  and a preliminary conditional-expectancy table. If you do, label it clearly as **exploratory** and
  say exactly what it does and does not establish.
- `[FACT]` / `[INFERENCE]` / `[PROPOSAL]`, with file+line citations.

## Deliverable
`research/audit/L3_REGIME.md`. Final reply: the five-line verdict block, plus the minimum experiment
that would settle whether the regime matters.
