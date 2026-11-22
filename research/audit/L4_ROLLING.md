# L4 — Data sufficiency, rolling ML / RL, end-to-end model, dynamic backtesting

**Leaf:** L4 (analyst) · **Date:** 2026-11-22 · **Mode:** read-only audit + specification
**Scope:** user question 5 — *is the existing data sufficient, and how should rolling ML training,
rolling RL, an end-to-end model and dynamic backtesting be organised?*

**Frozen contracts this leaf codes against:** D2 (candidate log), D3 (model artefact), D4 (honest
baseline: no edge), D5 (data reality), D8 (A/A+ unimplementable), D9 (cost model).
**Nothing in this document is implemented.** Every number is either quoted with a file+line citation or
reproduced by a command in Appendix R.

**Tag legend:** `[FACT]` = measured on this host; `[INFERENCE]` = a deduction from measured facts;
`[PROPOSAL]` = a design choice this leaf recommends.

---

## 0. Headline findings (read this first)

| # | Finding | Tag | Evidence |
|---|---|---|---|
| **F1** | The lake's NQ/ES 1-minute partitions exist but hold **one week**: NQ **7,490** rows, ES **7,489** rows, 2026-09-24 → 2026-10-01. Verified on the **NFS** mount. | `[FACT]` | §A.1–A.2, R1 |
| **F2** | The real gap is **not** "1-minute NQ" but "**multi-year 1-minute NQ with a roll rule**". A roll gap prints as a liquidity sweep and manufactures a setup with a stop and a 2R target. | `[FACT]`+`[INFERENCE]` | §A.3 |
| **F3** | **The stored NQ/ES 1m price basis is the *index level*, not the tradable futures price** (NQ 30,372–31,148; ES 7,685–7,814; 0.25 granularity). A `FuturesContract(price_increment=0.25, multiplier=20)` applied to these prices yields a **50× wrong P&L**. | `[FACT]`+`[INFERENCE]` | §A.4, R8 |
| **F4** | **NQ 1-minute is cost-viable; crypto 1-minute is not.** NQ ATR(14) on 1m = **10.66 index pts = $213**, so the D9 round trip ($9.50/$14.50/$19.50) = **0.045 / 0.068 / 0.091 R**. BTCUSDT 1m mean measured round-trip cost = **1.08 R** (census) / **0.41 R** (portfolio) at Binance's 0.08 %. | `[FACT]` | §B.4, R9, R10 |
| **F5** | **The rule engine's gross win rate is ≈ 1/3 on every market tested** — BTC 34.45 % (census) / 32.68 % (portfolio); ETH 34.3 % / 33.9 %. For a 1:2 bracket `E[R]_gross = 3p − 1` exactly, so p = 1/3 is cost-free break-even. | `[FACT]` | §B.2, R2 |
| **F6** | **The phase-1 gate has a precise numeric form.** `PF = 2p/(1−p)`, so `PF > 1.25` ⇔ **p > 38.46 %** cost-free; net of NQ costs (0–2 ticks) it is **p > 38.5 % / 40.9 % / 41.7 %**. Crypto delivers 32.7–34.5 %. **The transfer gap is +4 to +9 percentage points of win rate.** | `[INFERENCE]` | §B.3, §C.6 |
| **F7** | **There *is* exploitable conditional structure, and it is not the FVG.** The stop distance in ATR units predicts the win rate monotonically with **split-half Spearman ρ = +0.93** (p = 0.534 in H1 → 0.549 in H2 for `risk/ATR < 0.5`). It survives controlling for the immediate momentum (`runup_atr`) and for time-of-day. | `[FACT]` | §B.5, R11, R12 |
| **F8** | **But a `P(Win)`-gated filter makes things strictly worse.** Because `cost_R` is *inversely* proportional to the stop distance, every threshold on `risk/ATR` **lowers** net expectancy. On BTCUSDT 1m the one-position-at-a-time portfolio goes from **−0.41 R / −0.45 R** (no filter) to **−3.92 R / −4.46 R** (risk/ATR < 0.75). ETH: −0.32/−0.27 → −2.87/−2.17. | `[FACT]` | §B.6, R13, R14 |
| **F9** | **Therefore the decision rule must be `P(Win) > (1 + cost_R)/3`, not `P(Win) ≥ 0.58`.** The doc's 0.58 implies a required gross E[R] of +0.74 R — it selects exactly the tight-stop trades whose cost is 4–5 R. | `[INFERENCE]` | §C.5 |
| **F10** | **The crypto data supports the doc's 6/1/1 walk-forward arithmetically** (40 monthly folds, ~9,016 candidates and ~339 portfolio trades per test month) but **not statistically**: one test fold has se(p) = 2.55 pp, so only the **concatenated 40-fold OOS** (n ≈ 15,928, se(p) = 0.37 pp) has any power. | `[FACT]`+`[INFERENCE]` | §B.7, §C.4 |
| **F11** | **The measured label horizon is long and unbounded**: median 32 bars, p90 236, p95 428, p99 1,473, p99.9 5,726, **max 35,745** bars (24.8 days). A17's "1 trading day" embargo is only defensible **if** the label horizon is capped; capping it at H makes `embargo = H` by construction. | `[FACT]`+`[INFERENCE]` | §C.3 |
| **F12** | **The RL's order-book-imbalance state does not exist for NQ**, and the only file that has it (`bar_ofi`, 1,636,229 BTC 1m bars) is **not in the canonical lake** — it lives under the non-canonical `iflow/backtestTools/data/...` root. | `[FACT]` | §A.3 row 3, §D.3 |

---

## A. Data sufficiency — a requirement-by-requirement matrix

Status vocabulary: **AVAILABLE** = present, governed, and sufficient for the stated use ·
**PARTIAL** = present but insufficient in *length*, *provenance*, or *basis* ·
**MISSING** = absent.

| # | Requirement | Status | Evidence (path / command) | Consequence |
|---|---|---|---|---|
| **1** | **NQ 1-minute OHLCV, ≥3 y, with a documented roll rule** | **MISSING** (length + roll rule) | `~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/us_futures/NQ/1m/NQ_1m.parquet` → **7,490 rows**, `2026-09-24 04:09` → `2026-10-01 14:48` (R1). Multi-year NQ exists only at 1h (**13,764** rows, 2024-05-23→2026-10-01) and 1d (**1,258** rows, 2021-10-01→2026-10-01) (R2). No roll rule in any artefact (`AUDIT.md` §C.4; `DATA_ACQUISITION.md` §7). | **Phase 1 cannot start.** See §A.1–A.3 for what exactly is missing and why the roll rule is not optional. |
| **2** | **ES 1-minute OHLCV (SMT reference), time-aligned to NQ** | **MISSING** (length) / **AVAILABLE** (alignment) | `.../us_futures/ES/1m/ES_1m.parquet` → **7,489 rows**, same week. **Alignment is good**: 7,488 of 7,489 timestamps intersect (2 NQ-only, 1 ES-only) (R3). | Alignment machinery is proven; only length is missing. |
| **3** | **Tick data** (RL order-book-imbalance state; slippage calibration) | **MISSING for NQ** · **PARTIAL for crypto** | NQ: nothing anywhere. Crypto: `crypto/high_frequency_lob/BTCUSDT/BTCUSDT_1m_3years_governed.parquet` → **1,636,229** 1m bars 2023-01-01→2026-02-14 with `bar_ofi`, `atr14`, `parkinson_vol`, `garman_klass_vol`; `..._depth20_20260326...` (322,674 rows, **one day**); `..._lob_depth_microstructure...` (100,000 µs updates, `wap_diff`/`depth_skew`/`spread`); `..._trades_20260418...` (1,941,077 rows, **one day**) (R4). **All of these sit under `~/iflow_lake/iflow/backtestTools/data/03_governed_lake/...`, not under the canonical `iflow/database/03_governed_lake/...` — the canonical lake has no `crypto/high_frequency_lob` tree at all** (R4). | The RL's fourth state variable is unavailable for the target market, and the substitute is not in the governed lake. See §D.3. |
| **4** | **Tradeable instrument definition** (tick size, multiplier, fees) + Nautilus `FuturesContract` for NQ/ES | **PARTIAL** | Specs pinned: NQ tick 0.25 / mult $20 / precision 2; ES tick 0.25 / mult $50 (`NAUTILUS_API.md` §3, lines 154–165). `FuturesContract` verified to exist; **there is no `Future` class**; `activation_ns`/`expiration_ns` are mandatory uint64 (`.field-guide/env.md`; `NAUTILUS_API.md` §3, lines 120–153). The fee schedule is a **doc number with no named broker** (`DATA_FEASIBILITY.md` A5). **The stored price basis is wrong** (F3). | The instrument definition exists as a *sketch* but is **not executable as written** on the stored data. §A.4 specifies the fix. |
| **5** | **VXN (daily) and the intraday volatility proxy the doc needs** | **AVAILABLE** (daily) / **MISSING** (intraday VXN) | `macro/vxn/VXN_1d_consolidated.parquet` → **4,327** daily bars, 2009-09-14 → 2026-11-20 (R5). **No intraday VXN anywhere**; `RULE_SPEC` A18 forbids fabricating it; `DATA_ACQUISITION.md` §6 confirms the 1-hour VXN change-rate feature was dropped. | The doc's "VXN 1-hour change rate" feature must be **dropped** and **replaced**, not approximated. §C.1 specifies the replacement. |
| **6** | **Session / killzone calendar with DST handling** | **MISSING** (code, not data) | No calendar file in the repo. `RULE_SPEC` A21 pins `America/New_York` with DST, endpoint-inclusive; `DATA_FEASIBILITY.md` §E3 lists the four assertions required. The 1-week NQ/ES files contain the breaks that make this necessary: 4 × 61-min gaps, 4 × 11-min gaps, 1 × 49.2-h gap, 1 × 2-min gap per series (R3). | A pure code task (~1 day), but **it must exist before any backtest**, because a sweep across a 61-minute hole is an artefact (§A.3). |
| **7** | **Funding rates (crypto) / DVOL** | **AVAILABLE** (crypto) / **N/A** (NQ) | `crypto/funding_rate/{BTCUSDT,ETHUSDT}/*.parquet` → **4,200** prints each, 2023-01-01 → 2026-10-31 (R6). `macro/dvol/BTCDVOL_1h_consolidated.parquet` → **26,665** hourly bars, 2023-10-01 → 2026-10-16 (R6). | Available as crypto-lane features; **not applicable to NQ**. NQ's regime index is VXN. |
| **8** | **The candidate log** (rule engine output → ML input) | **MISSING** (does not exist yet) | The rule engine is unimplemented (D1). The **schema is frozen** (D2) and the **expected volumes are now measured** (§B.7). | Implement the rule engine to the D2 schema first; nothing else can start. |
| **9** | **The labels** (outcome join) and the **cost model** | **PARTIAL** — cost model **frozen but inconsistent** | D9 freezes NQ $9.50/$14.50/$19.50 (0/1/2 ticks) and Binance 0.08 %/side→0.08 % round trip. **Conflict:** `E1_RESULTS.md` §3.3 quotes "$14.50–$24.50" for NQ, which is $5 higher than D9 at every tick count. **Also:** E-1's flat "0.05 R" crypto assumption is ~8× below the measured mean (F4). | Adopt D9 as the single source; reconcile `E1_RESULTS.md` §3.3; replace the flat crypto cost with the measured per-trade `cost_R` (§C.2). |
| **10** | **Out-of-sample capacity** for a 6/1/1 rolling split | **AVAILABLE for crypto** / **MISSING for NQ** | Measured: 47 months → **40 folds**; ~9,016 candidates and ~339 portfolio trades per test month (§B.7, R7). NQ: 7,490 bars → **1,735** FVG candidates, 1,016 closed, p = 0.324, CI [0.295, 0.353] (R6b). | Crypto has the *volume*; NQ has none. Statistical power, not volume, is the binding constraint on crypto (§C.4). |

### A.1 / A.2 — What exists and where (rows 1–2, verified)

The authoritative lake is the **NFS** mount (`nfs://fnos2.local/fs/1000/nfs/iflow/database`), not the
SMB share and not the local checkout (`DATA_ACQUISITION.md` §1; `.field-guide/env.md` "the canonical
lake is NFS, not SMB, and it is mountable").

```
~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/
├── us_futures/
│   ├── NQ/  1m/NQ_1m.parquet          7,490 rows  2026-09-24 04:09 → 2026-10-01 14:48
│   │        5m/NQ_5m_consolidated.parquet   1,512 rows  2026-08-06 → 2026-10-01
│   │        15m/NQ_15m.parquet              4,537 rows  2026-08-06 → 2026-10-01
│   │        1h/NQ_1h.parquet              13,764 rows  2024-05-23 → 2026-10-01
│   │        2h/NQ_2h_consolidated.parquet   7,151 rows  2024-05-23 → 2026-10-01
│   │        4h/NQ_4h.parquet               3,707 rows  2024-05-09 → 2026-10-01
│   │        1d/NQ_1d.parquet               1,258 rows  2021-10-01 → 2026-10-01
│   ├── ES/  (same tree; 1m = 7,489 rows → 2026-10-01 14:47)
│   └── MBT/, MET/   (8–77 rows; placeholders)
├── us_equities/QQQ/ 15m/QQQ_15m_consolidated.parquet   73,325 rows  2022-10-14 → 2026-10-14
│                     30m/QQQ_30m_consolidated.parquet   36,695 rows  2022-10-14 → 2026-10-14
│                     1m/QQQ_1m.parquet                    2,428 rows  2026-09-23 → 2026-10-01
├── crypto/futures_um/{BTCUSDT,ETHUSDT}/1m/*_1m_consolidated.parquet
│                                                     2,046,240 rows  2023-01-01 → 2026-11-21
├── crypto/funding_rate/{BTCUSDT,ETHUSDT}/            4,200 prints  2023-01-01 → 2026-10-31
├── macro/vxn/VXN_1d_consolidated.parquet              4,327 rows  2009-09-14 → 2026-11-20
├── macro/dvol/BTCDVOL_1h_consolidated.parquet        26,665 rows  2023-10-01 → 2026-10-16
└── (NO crypto/high_frequency_lob  ← the RL's OBI state)
```

`[FACT]` **The manifest is aspirational.** `v2_parquet_lake/manifest/manifest.json` advertises
`1m,5m,15m,1h,2h,4h,1d` for NQ/ES; only `1m` (one week), `5m`/`15m` (two months) and `1h`/`2h`/`4h`/`1d`
(multi-year) have bytes behind them (R2). `sync_manifest_truth.py` now rewrites the manifest from disk,
so this drift is being closed.

`[FACT]` **The NQ/ES 1m files violate the lake's own flat-bar corollary**: NQ has **7** zero-volume
non-flat bars, ES has **6** (R3). The lake's own auditor cannot see this — `incremental_update.py::
verify_mathematical_invariants` only tests `volume < 0` (`DATA_ACQUISITION.md` §2).

### A.3 — The *real* gap: "multi-year 1-minute NQ **with a roll rule**"

`[INFERENCE]` The phrase "we need 1-minute NQ" understates the problem by two orders of magnitude. What
is missing is a **multi-year** series that is **continuous-contract** and therefore **contains roll
gaps**, and no artefact states how those gaps are handled.

Why the roll rule is **not optional** — the mechanism, end to end:

1. A continuous NQ series is spliced at each H→M roll. The splice is a price discontinuity of roughly
   50–150 index points (`DATA_FEASIBILITY.md` §E1).
2. The rule engine's **first** precondition is *"price pierces a prior swing high/low"* (`RULE_SPEC.md`
   §1.4 Step 2, lines 145–146). A roll gap that gaps **down** through a prior swing **low** is a
   *bullish sweep* and fires the entire chain (`AUDIT.md` §C.4, "the roll filter is not a nice-to-have").
3. The gap also manufactures a 3-candle FVG around it, so ATR(14), the gap floor, the swing levels and
   therefore **the stop distance and the R unit** are all computed on a price series that never existed.
4. The backtest then scores the synthetic setup with a synthetic stop and a synthetic 2R target.

`[PROPOSAL]` The minimum viable roll rule, exactly as `AUDIT.md` §C.4 already specifies, is:

* a per-bar `contract_id` where the source provides one (Databento does);
* otherwise a **statistical roll detector** `|open[t] − close[t−1]| > k·ATR(14)` with `k ≈ 3`;
* flagged bars **and the `k` bars either side** are excluded from rule evaluation and recorded as
  `roll_boundary` — **never as trades**;
* **one** executable `roll_boundary(ts, contract_id) -> bool` shared by the bar filter and the test;
* ATR, gap size, swing levels and the R-multiple computed in **one** price basis (never mixing
  adjusted and raw);
* assert no candidate's FVG window `[c[i], c[i]+15]` crosses a flagged boundary.

### A.4 — Row 4's hidden defect: the price basis is the index, not the futures price

`[FACT]` The stored NQ 1m closes run **30,372.25 → 31,148.25** and ES **7,685.00 → 7,813.75**, both on a
**0.25** grid, with a minimum non-zero close-to-close change of exactly 0.25 (R8).

`[INFERENCE]` The E-mini NQ is quoted at **index ÷ 50** with a 0.005 price increment (= 0.25 index
points = $5); the E-mini ES at **index ÷ 50** with a 0.25 index-point tick (= $12.50). A Nasdaq-100 of
30,372 and an S&P 500 of 7,700 in late 2026 are *index levels*; the corresponding futures quotes would
be ~607 and ~154. **The stored series is therefore the index level (equivalently: a continuous futures
series scaled by 50, as TradingView's `NQ1!` is).**

Consequences, all of which are blocking:

* Applying `FuturesContract(price_increment=Decimal("0.25"), multiplier=Quantity(20))` **as written** to
  these prices gives a notional of 30,372 × $20 = **$607,440** instead of $155,000 — a **50× P&L
  error**. The same class of defect as `RULE_SPEC.md` B6 (mixing price bases) but 50× larger.
* The **tick size in dollars** differs by instrument under the same 0.25 grid: NQ $5/tick, ES $12.50/tick.
* "10 points of stop" in the stored series is **10 index points** = $200 for NQ and $500 for ES.

`[PROPOSAL]` Before any backtest, the data pipeline must (i) declare the price basis explicitly
(`price_basis: index_points | futures_quoted | back_adjusted`) in the governed schema, (ii) map to the
quoted futures price **or** keep index points and define the instrument's tick as `0.25 index points =
$5` (NQ) / `$12.50` (ES), and (iii) assert in a test that `price_increment × multiplier` equals the
**documented dollar tick** for the chosen basis.

### A.5 — Row 9's cost model: adopt D9, reconcile E-1

`[PROPOSAL]` D9 is the frozen cost model and wins. Two reconciliations are owed:

1. `E1_RESULTS.md` §3.3 uses "$14.50–$24.50" for NQ; D9 says **$9.50 / $14.50 / $19.50** at 0/1/2 ticks.
   D9 is the decision; §3.3's table must be corrected.
2. E-1's crypto cost model is a **flat 0.05 R**. The measured mean round-trip cost in R on BTCUSDT 1m
   is **1.08 R** (census) / **0.41 R** (portfolio) at Binance's 0.08 % round trip. The qualitative
   verdict is unchanged and in fact **stronger**, but the magnitude in E-1 is understated by ~8×.

---

## B. Sufficiency of the *current* crypto data — and the transfer question

### B.1 — What the crypto lane actually is

`[FACT]` BTCUSDT and ETHUSDT 1-minute: **2,046,240 bars each**, 2023-01-01 00:00 → 2026-11-21 23:59,
**0 gaps** (expected bars in span == actual rows), invariants 100 % compliant, 244/149 genuine
zero-volume bars all of them flat (`DATA_ACQUISITION.md` §6; verified R2). 24/7, no session breaks,
no roll gaps, no holiday gaps.

`[INFERENCE]` This is a *better* specimen of a rule-engine test than anything available for NQ: complete,
gap-free, multi-year, and 47 months long. It is the right place to settle the question *"does this
rule engine have an edge at all?"* — and it is the wrong place to settle *"is this rule engine
profitable on NQ?"* because the cost structure differs by a factor of 5–20 (§B.4).

### B.2 — Measured candidate statistics and the label base rate

All figures from **E-1's own engine** (`research/experiments/e1_rule_falsification.py`) re-run on the
lake's consolidated parquet, code arm (`window=[0,15]`, no ATR floor, `honest:open(k+1)` fill, sweep
gate off) — i.e. the reference implementation's own semantics (R2):

| Quantity | BTCUSDT 1m | ETHUSDT 1m |
|---|---|---|
| Bars | 2,046,240 | 2,046,240 |
| 3-candle FVG candidates formed | **677,155** | **605,235** |
| Candidates that triggered into a trade | 423,772 | ≥ 376,137 |
| Closed trades — **census** (all candidates) | **423,759** | **376,137** |
| Census win rate (hit 2R) | **34.45 %** (145,980) | 34.30 % |
| Census `E[R]_gross` | **+0.0335** | +0.0290 |
| Closed trades — **one position at a time** | **15,928** | **16,773** |
| Portfolio win rate | **32.68 %** | 33.90 % |
| Portfolio `E[R]_gross` | **−0.0197**, CI [−0.042, +0.002] | **+0.0180**, CI [−0.004, +0.039] |

`[FACT]` **The label base rate is p ≈ 0.3445 (census) / 0.3268 (portfolio) on BTC and 0.343 / 0.339 on ETH.**

`[INFERENCE]` **The arithmetic is exact and it is the whole story.** For a fixed 1:2 bracket with
E-1's payoff convention (`r = +2` on target, `r = −1` on stop):

```
E[R]_gross = 2p − (1−p) = 3p − 1          PF = 2p/(1−p)
```

Check: BTC census p = 0.3445 → E[R] = +0.0335 ✓, PF = 1.051 ✓ (matches `E1_RESULTS.md` §3.0).
BTC portfolio p = 0.3268 → E[R] = −0.0196 ✓, PF = 0.971 ✓ (matches).

`[FACT]` **The census's t-statistic is *not* purely a concurrency artefact — but it is still not a
result.** A moving-block bootstrap (1,000 resamples, blocks of 300 / 1,440 / 4,320 trades ≈ 1 day / 5
days / 1 month) gives:

| Arm | n | E[R] | iid t | block-1d t | block-1mo t | design effect (1d → 1mo) |
|---|---|---|---|---|---|---|
| census | 423,759 | +0.0335 | 15.28 | 11.33 | 8.11 | 1.8× → 3.6× |
| one-at-a-time | 15,928 | −0.0197 | −1.76 | −1.81 | −2.39 | 1.0× → 0.5× |

`[INFERENCE]` Serial correlation inflates the census t by only √1.8–√3.6 ≈ 1.3–1.9×. The census
arm's defect is **not** statistical — it is that **it is not a portfolio**: it asserts you can hold
423,759 simultaneous 1-R positions. Its +0.0335 R is a true *per-candidate* expectancy, and the
portfolio constraint turns it into −0.0197 R because *"take the first signal while flat"* is an
**adverse-selection rule**. Clustering is mild at the bar level (423,759 trades over **345,831 distinct
entry bars** = 1.23 trades/bar, R6c) — it is the **overlapping holding periods**, not same-bar
clustering, that bind. **This is a materially more precise statement than D4's**, and it does not
weaken D4: the *portfolio* arm is the one that matters and it is negative.

### B.3 — The phase-1 gate, stated numerically

`[INFERENCE]` With `PF = 2p/(1−p)`:

| Gate | Required win rate `p` (gross) |
|---|---|
| `PF > 1.25`, cost-free | **p > 38.46 %** |
| `PF_net > 1.25` at 0 ticks (c = 0.045 R) | **p > 40.1 %** |
| `PF_net > 1.25` at 1 tick (c = 0.068 R) | **p > 40.9 %** |
| `PF_net > 1.25` at 2 ticks (c = 0.091 R) | **p > 41.7 %** |

`[FACT]` Crypto delivers p = 32.68 % (BTC portfolio), 33.90 % (ETH portfolio), 34.45 % (BTC census).

`[INFERENCE]` **The transfer gap is +4 to +9 percentage points of win rate.** NQ must produce a rule
engine that is *materially* better than the same rule engine on two large, liquid, 24/7 crypto
markets. That is the single number the whole project turns on, and it is **not currently supported by
any evidence**.

### B.4 — The cost side: NQ 1m is tradable, crypto 1m is not

`[FACT]` Measured ATR(14) on 1-minute bars and the implied round-trip cost in R:

| Series | ATR(14, 1m) | in $ at the D2/D9 multiplier | D9 round trip (0/1/2 ticks) | cost in R |
|---|---|---|---|---|
| **NQ 1m** | **10.66 index pts** | $213 (×$20/pt) | $9.50 / $14.50 / $19.50 | **0.045 / 0.068 / 0.091 R** |
| **ES 1m** | **1.73 index pts** | $87 (×$50/pt) | $9.50 / $22.00 / $34.50 | 0.110 / 0.254 / 0.398 R |
| **BTCUSDT 1m** | — | measured mean | 0.08 % of notional | **1.08 R** (census) / **0.41 R** (portfolio) |
| **ETHUSDT 1m** | — | measured mean | 0.08 % of notional | 0.34 R / 0.28 R (portfolio) |

`[INFERENCE]` **This is the decisive asymmetry.** The crypto negative result has **two** components:
(a) a *signal* component — p ≈ 1/3, which is market-agnostic and does transfer; and (b) a *cost*
component — 0.28–1.08 R per trade, which is **venue-specific and does not transfer**. On NQ the same
bracket costs 0.045–0.091 R, i.e. **5–20× cheaper in R terms**.

`[INFERENCE]` Therefore: **a negative crypto result falsifies the signal, but the crypto *losses* are
mostly a cost artefact; NQ's cost is low enough that even a p of 35 % would be net-positive.** The
question NQ must answer is narrow and sharp: *is p on NQ above (1 + c)/3 ≈ 0.345–0.364?* Crypto says
p ≈ 0.327–0.345. It is a coin-flip's worth of separation.

### B.5 — Does *any* conditional structure exist? (the ML premise, tested)

`[FACT]` Split-half stability of the conditional win rate. H1 = 2023-01…2024-12, H2 = 2025-01…2026-11,
census population, bins chosen a priori (R11):

| Feature (all computable at decision time) | Split-half Spearman ρ (bin win rates) | Reading |
|---|---|---|
| **`risk/ATR`** (stop distance ÷ ATR(14) at the FVG bar) | **+0.929** | **strong, monotone, replicable** |
| `penetration/ATR` (how far past the far edge the close went) | +0.881 | strong |
| `gap/ATR` (FVG size ÷ ATR) | +0.643 | moderate, noisy |
| `hour(UTC)` | +0.024 | none |
| `bars_to_inversion` (age) | **−0.429** | **sign-flips between halves** — unstable |

`[FACT]` The `risk/ATR` effect, per bin:

| `risk/ATR` | H1 n | H1 p | H2 n | H2 p | `E[R]_gross` | mean `cost_R` | `E[R]_net` |
|---|---|---|---|---|---|---|---|
| < 0.5 | 771 | **0.5344** | 759 | **0.5494** | +0.60 | 9.10 | −8.50 |
| 0.5 – 1.0 | 12,045 | 0.4051 | 11,515 | 0.4191 | +0.22 | 2.88 | −2.64 |
| 1.0 – 1.5 | 35,248 | 0.3537 | 33,022 | 0.3525 | +0.06 | 1.77 | −1.66 |
| 1.5 – 2.0 | 43,691 | 0.3431 | 41,438 | 0.3383 | +0.03 | 1.42 | −1.37 |
| 2.0 – 3.0 | 63,589 | 0.3452 | 63,048 | 0.3349 | +0.04 | 1.07 | −1.05 |
| 3.0 – 5.0 | 44,851 | 0.3346 | 46,249 | 0.3307 | −0.01 | 0.77 | −0.77 |
| > 5.0 | 13,424 | 0.3377 | 13,911 | 0.3132 | −0.06 | 0.69 | −0.73 |

`[FACT]` **It is not a momentum artefact.** The signed move from the confirmation close to the next
bar's open (`runup_atr`) has essentially no effect on p (0.3406 for runup < 0 vs 0.3456 for ≥ 0), and
stratifying by it leaves the `risk/ATR` effect intact: `risk<0.75 ATR` → p = 0.456 (runup < 0) and
0.474 (runup ≥ 0); `risk 1.5–3 ATR` → 0.334 / 0.342 (R12).

`[INFERENCE]` **What the effect actually is.** With a *fixed* 1:2 bracket, the stop distance controls
the distance to the target. A tight stop ⇒ a tight target ⇒ the target is reached more often. So
`risk/ATR` is a **mechanical consequence of the bracket**, not evidence that the FVG carries
information. It is nonetheless real, causal, replicable and tradable *in principle* — and it is the
only thing the ML layer has to work with.

`[PROPOSAL]` **Mandatory benchmark.** Any ML result must be compared against a **no-FVG baseline**
that uses the same features minus the FVG geometry (e.g. a pure "stop distance in ATR" momentum rule
on the same bars). If the meta-labeler cannot beat that baseline OOS, the FVG adds nothing and the
project's premise is dead even if the P&L looks good.

### B.6 — …and the filter makes it worse: the decisive OOS test

`[FACT]` One position at a time, a `risk/ATR` threshold used as a stand-in for the ML filter, chosen
on H1 and applied to H2, net of the measured 0.08 % round trip (R13, R14):

**BTCUSDT 1m**

| Filter | H1 n | H1 p | H1 gross | H1 cost_R | H1 net | H2 n | H2 p | H2 gross | H2 cost_R | H2 net |
|---|---|---|---|---|---|---|---|---|---|---|
| **none (baseline)** | 8,043 | 0.3209 | −0.037 | 0.374 | **−0.4115** | 7,883 | 0.3329 | −0.001 | 0.450 | **−0.4518** |
| risk/ATR < 5.0 | 18,108 | 0.3329 | −0.001 | 0.692 | −0.6928 | 18,620 | 0.3340 | +0.002 | 0.811 | −0.8092 |
| risk/ATR < 3.0 | 34,347 | 0.3412 | +0.024 | 1.069 | −1.0458 | 35,634 | 0.3436 | +0.031 | 1.204 | −1.1736 |
| risk/ATR < 1.5 | 40,016 | 0.3691 | +0.107 | 1.767 | −1.6599 | 39,253 | 0.3701 | +0.110 | 1.929 | −1.8183 |
| risk/ATR < 0.75 | 6,380 | 0.4605 | +0.382 | 4.298 | **−3.9160** | 6,132 | 0.4623 | +0.387 | 4.852 | **−4.4647** |

**ETHUSDT 1m**: baseline −0.3199 (H1) / −0.2660 (H2); `risk/ATR<0.75` −2.8718 / −2.1667;
`risk/ATR<5.0` −0.5307 / −0.4013. **Every threshold is worse than no threshold, on both markets, in
both halves.**

`[INFERENCE]` **This is the single most important result in this leaf.** Because `cost_R` is
*inversely* proportional to the stop distance, **any filter that selects high-P(Win) candidates is a
filter that selects the most expensive candidates.** A meta-labeler gated on `P(Win)` alone is
*guaranteed* to make the book worse. This is not a hyperparameter problem; it is a formulation error.

### B.7 — Does the crypto data support the doc's 6/1/1 walk-forward?

`[FACT]` 47 months (2023-01 … 2026-11). Fold `f` has train = 6 months, valid = 1 month, test = 1 month,
rolled monthly ⇒ **40 folds** (test months 2023-08 … 2026-11) (R7).

`[FACT]` Per-month volumes (R7):

| | per month | min | max | mean |
|---|---|---|---|---|
| Census candidates (closed) | | 6,130 (2026-11, partial) | 10,742 (2025-08) | **9,016** |
| Census positives @ p = 0.3445 | | ~2,110 | ~3,701 | **3,106** |
| Portfolio trades | | 79 (2025-04) | 543 (2024-11) | **339** |
| Portfolio positives @ p ≈ 0.327 | | ~26 | ~177 | **111** |
| Distinct entry bars (census) | | 5,045 | 8,416 | **7,358** |

`[INFERENCE]` **Per fold:** train ≈ 54,100 candidates (18,640 positives) / 2,034 portfolio trades (665
positives); valid ≈ 9,016 / 339; test ≈ 9,016 / 339.

**Is that enough for a binary classifier?** Yes, comfortably, on rows. **Is it enough to detect an
edge?** No — and this is the part the doc's design misses:

`[INFERENCE]` Statistical power of one test fold on the *portfolio* population (n = 339):
`se(p) = sqrt(0.327 × 0.673 / 339) = 2.55 pp`. To detect a +2 pp lift at 80 % power you need
`n ≈ 7,849` trades ≈ **23 months** of portfolio data. One month of test data is **~1/23** of what a
2 pp effect needs. Concatenating all 40 folds (n = 15,928) gives `se(p) = 0.37 pp`, i.e. `se(E[R]) =
0.011 R` — enough to resolve a 0.022 R net edge, and nothing smaller.

`[PROPOSAL]` **The walk-forward's power comes from the concatenation, never from a single fold.**
Per-fold P&L is a *diagnostic*, not evidence. The acceptance test (§C.6) is evaluated on the
concatenated OOS equity curve only, with per-fold numbers reported for drift detection (§F.3).

### B.8 — The transfer question, argued properly

**What would have to be true for the crypto result to transfer to NQ?** Three things, and they are
independent:

* **T1 — Signal transfer.** The win rate `p` of the rule engine on NQ 1-minute must exceed the crypto
  value by enough to clear costs: `p_NQ > (1 + c_NQ)/3 = 0.345–0.364` vs crypto's 0.327–0.345.
  Requires: NQ's *intrabar* microstructure (tick size $5 vs a 0.25 grid, spread, session gaps) to
  produce a materially different FVG-inversion success rate. **No reason to expect it; the mechanism
  is scale-free.**
* **T2 — Cost transfer.** `c_NQ` must be small relative to the stop distance. **Measured true**: 0.045–0.091 R
  on NQ vs 0.28–1.08 R on crypto. This is the one thing that *does* transfer in NQ's favour.
* **T3 — Regime/feature transfer.** The features that carry the conditional structure
  (`risk/ATR`, `penetration/ATR`) must behave similarly on NQ. They are ATR-normalised, so they
  *should*; but the ATR itself is a different process on a 23-hour, index-arbitraged instrument.

**The cheapest test of T1** — and this is the question the user asked, so it gets a real answer:

1. **`[FACT]` FREE, ALREADY DONE — the ETH-vs-BTC test.** Two very different markets, same rule
   engine, 3.9 years each: p = 32.68 % (BTC portfolio) and 33.90 % (ETH portfolio); census 34.45 % /
   34.30 %. **The rule engine's win rate is ≈ 1/3 on both.** The *only* thing that differs between the
   two markets is the **cost**, and cost is what killed both. **Conclusion: what transfers is the
   absence of signal, not the presence of it.**
2. **`[PROPOSAL]` FREE, 1 hour — the NQ 1-week probe.** Run the same engine on
   `us_futures/NQ/1m/NQ_1m.parquet` (7,490 bars): **1,735** FVG candidates, **1,016** closed,
   **p = 0.324**, CI ≈ [0.295, 0.353] (R6b). This is *not* decisive (se(p) = 1.47 pp) but it is free
   and it does three jobs: it proves the engine runs on NQ's price scale, it gives a first NQ p
   estimate, and it validates the price-basis mapping (§A.4). **Do this before spending anything.**
3. **`[PROPOSAL]` FREE, half a day — the NQ 1h/15m cross-timeframe probe.** NQ 1h has **13,764** bars
   (2024-05-23 → 2026-10-01) and 15m has 4,537. Running the same engine at a coarser timeframe
   separates *"NQ vs crypto"* from *"1-minute vs 1-hour"*. A positive p at 1h would say the mechanism
   is real but the timeframe is wrong; a p ≈ 1/3 at 1h would say the mechanism is nowhere.
4. **`[PROPOSAL]` THE DECISIVE TEST — multi-year NQ 1m.** ≥600 trades per arm (AUDIT §D.3's sample-size
   requirement) at 1-minute. Cost: Databento CME Globex, **plausibly $100–$300**
   (`DATA_FEASIBILITY.md` §D Option 3; the doc's "$10–30" is flagged **UNVERIFIED** there).
   *Interim, free, provenance-poor:* the community HF datasets in `DATA_FEASIBILITY.md` §D Option 1 —
   `mdelcristo/NQ-F_1min_OHLCV_Parquet` (2015–2025, 50 MB) and `Khanhpham1992/es-futures-1m`
   (2020-11 → 2024-07, 141 MB) — ~0.2 GB total, ~50 minutes at the host's measured 69 KB/s, but with
   **no roll metadata on the NQ side** and unclear licensing.

**Minimum additional data that makes phase 1 meaningful** `[PROPOSAL]`:

| Item | Why | Cost | Effort |
|---|---|---|---|
| NQ **and** ES 1-minute, ≥3 y, **per-contract** (Databento) | the gate cannot be run without it | **$100–$300** (budget approval) | 1–2 days |
| A **roll rule** + `roll_boundary()` detector | a roll manufactures scored setups (§A.3) | included | 0.5 day |
| **Price-basis declaration** in the governed schema | 50× P&L error otherwise (§A.4) | included | 0.5 day |
| **Session calendar + DST** | a 61-min hole can fake a sweep | included | 1 day |
| **Fee schedule** from a named broker (Rithmic / AMP / Tradovate / IB) | D9's $4.50 has no owner | free | hours |
| **Intrabar/tick data for the one-week + one-month sample** | slippage calibration; the RL's OBI | Databento MBP or the broker | separate |

**Everything else the pipeline needs — VXN, DVOL, funding, the crypto OBI, the calendar — is already
free and present.** The single blocking purchase is multi-year NQ+ES 1-minute.

---

## C. Rolling ML training — the concrete design

### C.1 — The feature table (computable at decision time, nothing else)

`[PROPOSAL]` The doc's list is `iFVG几个模型的讨论.txt` L146: *checklist score, SMT flag, vision
confidence, VXN level + 1-hour change, bars from FVG formation to inversion, minutes from US open*.
Against D2's frozen candidate log and what actually exists:

| Doc feature | Available? | Computable at decision time? | **Replacement / treatment** |
|---|---|---|---|
| **Checklist score** (`checklist_score`, D2) | **PARTIAL** | **YES** | D8: implement the five named checklist conditions as **booleans**, expose the sum, **report the distribution, do not filter**. The "uncleared opposing OB" clause has **no detector in any artefact** (`AUDIT.md` §C.5) → drop it and record `checklist_ob_not_implemented`. The "+2 SMT" term is only computable on a market with a reference instrument. |
| **SMT flag** (`smt_divergence`, D2) | **YES on NQ** (ES), **−1 = unknown** on crypto | **YES** | Keep as `int8` with the −1 sentinel (D2 already defines it). **Crypto has no reference instrument → the feature is missing, not zero.** LightGBM handles NaN natively: pass `NaN` and let the model learn "no reference instrument" as its own state. |
| **Vision confidence** (`vision_confidence`, `vision_iou`, D2) | **NO** — the vision layer does not exist (D1); and its gate is unreachable by construction (D6: body-IoU, ≈0.5, white 640×640) | **NO** | **Degrade gracefully**: keep both D2 columns, always `NaN`. LightGBM's default `use_missing=true` + `zero_as_missing=false` means the model simply does not split on them; the feature-importance report will show 0 gain, which is the honest signal. **The feature set until the vision layer exists is the six below, minus vision.** |
| **VXN level** (`vxn_known`, `vxn_regime`, D2) | **YES** — daily, 4,327 bars | **YES** | Use `vxn_known` = the **previous** close (D2 says "lagged VXN (previous close)"), regime = the D-rule bins (−∞,18)→0, [18,28)→1, [28,∞)→2 (`RULE_SPEC.md` §1.9). |
| **VXN 1-hour change rate** | **NO** | **NO** | **Dropped** (A18, `DATA_ACQUISITION.md` §6). **Replacement** `[PROPOSAL]`: an **instrument-native realised-volatility change**, computable from the 1m bars the engine already has — e.g. `rv_1h = std(log returns, 60 bars)`, `rv_24h = std(log returns, 1440 bars)`, feature = `rv_1h/rv_24h − 1`, plus `atr14_ratio = ATR(14)/ATR(100)`. This is free, causal, available on every market (including crypto, where the doc's DVOL is the analogue), and is a *better* regime proxy than a daily VXN change because it is contemporaneous. |
| **Bars from FVG formation to inversion** (`bars_to_inversion`, D2) | **YES** | **YES** | Keep. **Note the measured instability**: split-half ρ = **−0.429**, sign-flipping between halves (§B.5). It is a legitimate feature but it is *not* a stable one — do not build the model around it. |
| **Minutes from US open** (`minutes_from_us_open`, D2) | **YES** (needs the calendar, §A row 6) | **YES** | Keep, as minutes since 09:30 ET on the trade date, plus a `killzone_id` categorical (0 = outside, 1 = NY AM, 2 = NY PM). |

**The feature set the ML layer actually gets today** `[PROPOSAL]` — ten features, all in D2 or derivable
from D2 + the 1m bars:

```
checklist_score          f64   (D2; 0–5, no filter applied)
smt_divergence           int8   (D2; -1 = unknown on crypto)
sweep_detected           int8   (D2)
vxn_known                f64   (D2; lagged)          [crypto: DVOL_known instead]
vxn_regime               int8   (D2; 0/1/2)           [crypto: dv ol_regime]
rv_ratio_1h_24h          f64   (NEW, replaces the dropped 1h-VXN change)
atr14_ratio              f64   (NEW)
bars_to_inversion        int32  (D2)
minutes_from_us_open     int32  (D2)
killzone_id              int8   (NEW, from the calendar)
side                     int8   (D2)
--- and, computed from D2's price columns, which is where the measured signal is ---
risk_in_atr              f64   (NEW = risk / atr14[fvg_bar3])
penetration_in_atr       f64   (NEW)
gap_in_atr               f64   (NEW)
```

`[PROPOSAL]` The last four are the ones the measurements say matter (§B.5). They are derivable from
D2's `risk`, `fvg_low`, `fvg_high`, `fvg_bar1..3`, `confirm_bar` and the ATR series — **no schema
change to D2 is required**, so the frozen contract is preserved.

`[INFERENCE]` **The mandatory no-FVG baseline** (§B.5) is: the same model trained on the same rows but
with the FVG-geometry features (`risk_in_atr` is geometry-derived too) — the honest baseline is a
momentum rule on ATR-normalised stop distance with no reference to the FVG. Report both side by side.

### C.2 — Label construction

`[PROPOSAL]` Follow D2 exactly: `label ∈ {1 = reached the 2R target, 0 = hit the stop, −1 = still open /
unlabelled}` and `r_multiple` (realised R, NaN while open).

* **Outcome join.** For each candidate row, resolve the bracket **forward from the confirmation bar**:
  walk bars from the fill bar; the first bar that touches the stop **or** the target resolves the
  trade. **If a bar touches both, the stop wins** (E-1's conservative convention; `E1_RESULTS.md` §1
  "Intrabar convention").
* **Horizon cap — this is the key design decision.** `[FACT]` The measured resolution horizon
  (portfolio arm, fill → resolution, in 1m bars) is: **median 32, p90 236, p95 428, p99 1,473,
  p99.9 5,726, max 35,745**; mean 125; **34.2 %** of trades resolve in more than 60 bars and **9.79 %**
  in more than 240 (R7b). `A27` sets **no** time stop, so the horizon is unbounded in principle.
  → **Define `LABEL_HORIZON_BARS = 480`** (8 h at 1m, ≈ p96 of the measured horizon). A candidate not
  resolved within 480 bars gets `label = −1` (**censored**), `r_multiple = NaN`, and is **excluded from
  both training and scoring**. ~4 % of trades are censored; that is the honest price of a bounded
  horizon and it makes the embargo well-defined.
* **Cost.** `r_multiple` stays **gross** (pure price outcome); the **cost enters as a per-row feature**
  `cost_R` (see below) and in the *scoring* of the portfolio, never inside the label. Rationale: the
  classifier's job is "will this reach 2R", which is a price question; the cost is a separate,
  deterministic quantity.
* **`cost_R` — a new per-row quantity** `[PROPOSAL]`:
  `cost_R = (round_trip_fee_usd + slippage_ticks × tick_usd) / (risk × multiplier)`, with
  `tick_usd = price_increment × multiplier`, `risk = |entry − stop|` in the instrument's price basis.
  For NQ at a $213 ATR-sized stop: 0.045 / 0.068 / 0.091 R. For crypto 1m it is 0.28–1.08 R.
  This column is **derived**, not part of D2 — it goes in the *feature table*, not the candidate log,
  so D2 is untouched.
* **Base rate** `[FACT]`: p = **0.3445** (census) / **0.3268** (portfolio) on BTCUSDT 1m; 0.343 / 0.339 on
  ETHUSDT 1m; **0.324** (CI [0.295, 0.353]) on the one-week NQ sample.
* **Class imbalance** `[PROPOSAL]`: the imbalance is **mild** (p ≈ 0.34, so the majority class is the
  *negative* class at 66 %). Do **not** use `class_weight='balanced'` blindly — it destroys the
  calibration the decision rule needs. Use `scale_pos_weight = n_neg/n_pos ≈ 1.90` **and then
  recalibrate the output** on the validation fold (isotonic, or Platt) so that `P̂` is again a
  probability of the 2R event under the *original* prior. **A threshold on an uncalibrated
  `scale_pos_weight`-trained score is not a threshold on P(Win).**

### C.3 — The split: purged walk-forward with an embargo

`[PROPOSAL]` The doc's windows (L145): **train 6 months / validate 1 month / test 1 month, rolled
monthly**. Measured on crypto this yields **40 folds** (§B.7).

**The exact embargo rule** — two halves, both mandatory:

> **Purge.** Drop every training row whose *label horizon* would extend past `train_end`, i.e. any row
> with `ts_event + LABEL_HORIZON_BARS > train_end`, and every row whose label is `−1` (censored).
> This is exact, not a heuristic.
>
> **Embargo.** Insert a gap of `embargo_bars` bars between the end of the training window and the start
> of the validation window, and between the end of the validation window and the start of the test
> window.
>
> `embargo_bars = max(LABEL_HORIZON_BARS, 1 trading day of bars) = max(480, 1,440) = 1,440 bars`
> at 1-minute frequency, i.e. **`embargo_minutes = 1,440`**.

**Why the embargo must exceed the maximum holding period.** `[INFERENCE]` The label of a training row
is *not knowable* until its trade resolves. If a training row's resolution falls inside the evaluation
window, the model has been fitted on a fact that only became observable after the evaluation window
opened — this is textbook look-ahead (Lopez de Prado's purged CV). With the horizon capped at
`LABEL_HORIZON_BARS = 480` and the purge rule above, **every retained training row's label was knowable
before `train_end` by construction**; the embargo then adds a further 1-day buffer so that no training
row's *feature window* or *near-duplicate candidate* straddles the boundary. A17's "1 trading day"
is therefore **correct and slightly conservative** — but it is only sufficient *because* the horizon is
capped. Without the cap (raw A27: no time stop, measured max horizon 35,745 bars = 24.8 days) no finite
embargo is sufficient, and the purge rule alone would remove a large and time-varying fraction of the
training set.

**How to prove no overlap** — three assertions, all in `tests/unit/test_walkforward.py` and all
re-runnable on any fold:

```python
# (1) no training label leaks into validation or test
assert max(train.ts_event) + LABEL_HORIZON_BARS + EMBARGO_BARS <= min(valid.ts_event)
assert max(valid.ts_event) + LABEL_HORIZON_BARS + EMBARGO_BARS <= min(test.ts_event)
# (2) every retained training row's label was knowable at train_end
assert (train.ts_event + train.label_horizon_bars <= train_end).all()
# (3) D3's forward-only rule: the model may only decide strictly after its asof
assert min(test.ts_event) > model.asof          # asof = test_start - 1 bar
# (4) no row is in two windows
assert set(train.ts_event) & set(valid.ts_event) == set()
assert set(valid.ts_event) & set(test.ts_event) == set()
```

`[PROPOSAL]` **Additionally**: purge on the *portfolio* clock as well. Because the portfolio takes
the first signal while flat, the *effective* decision points are the portfolio trades; a training
period whose last portfolio trade is still open at `train_end` must have that trade dropped. This is
implied by the per-row horizon purge (the row's horizon is its own), but it should be asserted
explicitly on the portfolio stream.

### C.4 — The model

`[PROPOSAL]` LightGBM binary classifier (`lightgbm` is not yet installed for the 3.11 interpreter —
`.field-guide/env.md`; `pip install --break-system-packages lightgbm scikit-learn pytest`).

| Setting | Value | Why |
|---|---|---|
| `objective` | `binary` | the label is binary (D2) |
| `metric` | `binary_logloss` (+ `auc` for reporting) | calibrated probabilities matter (§C.5) |
| `n_estimators` | 2,000 with early stopping | — |
| `learning_rate` | 0.03 | with 15 leaves, conservative |
| `num_leaves` | 15 | ≈ 2^4; the train fold has ~54k rows × ~13 features |
| `max_depth` | 5 | hard cap against interaction explosion |
| `min_data_in_leaf` | 200 | the fold's positives are ~18,600, so 200 is a ~1 % floor — prevents the model from learning leaf-level noise |
| `feature_fraction` | 0.8 | — |
| `bagging_fraction` / `bagging_freq` | 0.8 / 1 | decorrelate the 1.23-trades-per-bar clusters |
| `lambda_l1` / `lambda_l2` | 0.0 / 1.0 | L2 only, modest |
| `scale_pos_weight` | `n_neg/n_pos` ≈ **1.90** | mild imbalance (p ≈ 0.3445); **then recalibrate** |
| `early_stopping_rounds` | 50 | **on the validation fold only** |
| `random_state` | fixed | determinism is a QA requirement |

**Early-stopping protocol** `[PROPOSAL]`:
1. Fit on **train only**, monitoring `binary_logloss` on **valid**. Record `best_iteration`.
2. **Do not touch the test fold** for any fitting decision.
3. `meta_label_meta.json` records `n_train`, `n_valid`, `n_test`, `positives_train`, `positives_test`,
   `auc_test`, `accuracy_test` (D3's schema is already fixed for this).
4. For the **live** model (after the last fold), refit on train+valid with `n_estimators =
   best_iteration × 1.1` and set `asof` = the refit's cut-off. The *reported* test metrics always come
   from the non-refit model.
5. **Calibration**: fit an isotonic (or Platt) calibration map on the **validation fold** predictions
   and apply it to the test/paper predictions. Store the map inside the artefact directory as
   `meta_label_calibrator.json` (an addition to D3's file list — flag to the captain).

**Hyper-parameters are pre-registered, not tuned on the test fold.** `[PROPOSAL]` If they are tuned at
all, they are tuned on the **validation** fold of fold 1 only, and the choice is then frozen for all
40 folds. This is a hard requirement of the multiple-testing discipline in §F.5.

### C.5 — The decision rule — **not** `P(Win) ≥ 0.58`

`[INFERENCE]` This is the leaf's most important design correction, and it is forced by measurement
(§B.6). The correct rule is:

```
accept  ⇔  E[R]_net > 0
        ⇔  3 · P̂(Win) − 1 − cost_R > 0
        ⇔  P̂(Win) > (1 + cost_R) / 3
```

with `cost_R` the **per-candidate** cost in R (§C.2). For NQ: the threshold ranges from **0.348**
(0 ticks) to **0.364** (2 ticks) — a *conditional* threshold, not a constant.

`[INFERENCE]` **Why the doc's 0.58 is wrong as specified.** `P ≥ 0.58` ⇔ gross `E[R] ≥ +0.74 R`. On
NQ that requires a **58 % win rate** (gross `E[R] = +0.74 R`) — above the maximum the measured
conditional structure reaches (~0.55), and 15–25 percentage points above the population's 0.33–0.34.
Worse, the 0.58 gate selects *tight-stop* candidates, and §B.6 measured exactly what that does:
on BTCUSDT 1m it takes the portfolio from **−0.41 R** to **−4.46 R** (H2). **The doc's threshold, taken
literally, is the single most expensive mistake available in this system.**

`[PROPOSAL]` **Report both, act on one.** The system computes `P̂`, `cost_R` and the derived
`E[R]_net_estimate = 3·P̂ − 1 − cost_R`. The **gate is `E[R]_net_estimate > 0`**, i.e.
`P̂ > (1+cost_R)/3`. The doc's 0.58 is retained in the report as a **secondary, stricter** filter whose
traded population is published, so the design doc's intent remains auditable — but it is not the
production gate. **This changes a number in the design doc and must be raised with the captain.**

### C.6 — The honest acceptance test

**The necessary condition.** `[INFERENCE]` A meta-labeler adds value **only if** the base signal has
some edge *to filter*, and the kept subset's edge must exceed the cost of the subset it replaces. Two
necessary conditions, both measurable:

* **NC1 — gross conditional structure must survive OOS.** `E[R]_gross[kept] > 0` on the concatenated
  OOS folds. `[FACT]` On BTC this is **met** in the tight-stop bins (+0.39 R gross at risk/ATR<0.75) —
  but only in bins whose `cost_R` is 4.3–4.9 R.
* **NC2 — the kept subset's cost must be affordable**: `E[R]_gross[kept] > cost_R[kept]`. `[FACT]` On
  BTCUSDT 1m **no bin satisfies this** — the best net across all bins is −0.69 R. On NQ this is not
  known, because NQ's `cost_R` is 0.045–0.091 R and the gross conditional edge reaches +0.39 R.

**The metric.** `[PROPOSAL]` Let `S` = the set of OOS portfolio trades the model accepted, and `All` =
all OOS portfolio trades. Report, on the **concatenated 40-fold OOS equity curve**:

```
E_net[All] = mean over All of (3·y − 1 − cost_R)          with a 95 % CI (block bootstrap by month)
E_net[S]   = mean over S   of (3·y − 1 − cost_R)          with a 95 % CI
Δ          = E_net[S] − E_net[All]                        with a 95 % CI
kept_fraction = |S| / |All|
break_even_cost_R[S] = E[R]_gross[S]                      (the cost in R at which S goes to zero)
```

`[FACT]` Why the block bootstrap and not the iid t: the portfolio arm's design effect measured at
1.0× (1-day blocks) to 0.5× (1-month blocks) — the portfolio trades are essentially independent —
but the **census** population has a 1.8–3.6× design effect, so any statistic computed on the census
must use block bootstrapping. The portfolio is the honest population for P&L.

**Acceptance criteria (all must hold):**
1. `E_net[S] > 0` with a 95 % CI **excluding 0**;
2. `Δ` with a 95 % CI **excluding 0**;
3. `E_net[S] ≥ E_net[All] + 0.02 R` (a margin at least twice the OOS standard error of 0.011 R);
4. the result **survives the §F.5 multiple-testing correction** for the number of configurations tried;
5. the result **beats the no-FVG momentum baseline** (§B.5);
6. the kept subset's `break_even_cost_R[S]` is **> 2×** the assumed round-trip cost (so the result is
   not one tick of slippage away from dying).

**"Stop, the idea is dead" — the abort criteria.** `[PROPOSAL]` Any one of these ends the project:

* **A1.** `E_net[S] ≤ 0` on the concatenated OOS with the CI including 0 → the meta-labeler adds
  nothing. **Do not** proceed to the RL; do not "tune harder"; report the negative.
* **A2.** The only subsets with positive `E[R]_gross` are those with `cost_R > 0.3 R` → the edge is
  structurally untradable at the assumed fees (this is *exactly* the BTC 1m situation, F8).
* **A3.** A high-AUC model with **no** `E_net` lift → the model is learning the *cost* (i.e. `cost_R`
  and `risk_in_atr`) rather than the edge. Diagnostic: check whether `cost_R` or `risk_in_atr` is the
  top-2 feature; if so, the model has rediscovered F8 and the result is not an edge.
* **A4.** The result does not beat the no-FVG momentum baseline → the FVG contributes nothing; the
  project should pivot to a plain ATR-normalised momentum system or stop.
* **A5.** `E_net[S] > 0` but the CI includes 0 and the point estimate is < 0.05 R → **inconclusive**;
  report as inconclusive, do not start paper trading, do not raise the threshold and re-test.

`[INFERENCE]` **The prior from D4 and §B is that A1/A2 is the likely outcome on any market at 1-minute
frequency unless NQ's price process is materially different.** The design must therefore be built so
that A1 is *cheap to observe* — which is precisely what the walk-forward + concatenation discipline
delivers.

---

## D. Rolling RL

### D.1 — Position management only, **enforced in code**

`[INFERENCE]` "The RL must never open a position" (INV1, `RULE_SPEC.md` §2.2; doc L150) cannot be a
convention. `[PROPOSAL]` **four independent mechanisms**, each independently sufficient, each with a
test:

1. **Type separation.** The RL's action is a frozen dataclass with exactly three fields:
   `PositionAction(position_multiplier: float, be_trigger_r: float, partial_tp_ratio: float)`. There is
   **no** field that can open, close-to-zero, or reverse a position. `assert not any(
   hasattr(a, f) for f in ("side","quantity","direction","open","entry"))` over the action space.
2. **Capability restriction.** The RL agent receives a `PositionManager` capability object exposing
   only `set_stop(price)`, `set_take_profit(price)`, `reduce_size(fraction)`,
   `scale_in(factor, cap)`. It has **no** `submit_order`, no `submit_market_order`, no access to the
   `OrderFactory`. The strategy's entry path and the RL's management path are separate objects with
   separate capabilities; the entry path is reachable **only** from the rule engine's signal handler.
3. **Runtime invariant (the "malicious policy" test).** `[PROPOSAL]` A test runs a full backtest with a
   policy that always emits the maximum scale-in action and asserts:
   `position.size ≤ base_size × 1.5` (the SVG-A multiplier set) **and**
   `count(PositionOpened) == count(rule_engine_candidates_taken)` **and**
   `count(PositionClosed) ≤ count(PositionOpened)`.
   A policy that tried to open would fail the second assertion immediately.
4. **Action-space grid assertion.** The BE-trigger grid is `{0.0, 0.5, 1.0, 1.5}` R, the partial-TP
   ratio grid is `{0, 0.25, 0.5, 0.75, 1.0}`, the multiplier set is `{0.5, 1.0, 1.5}` (A29 +
   SVG-A). `assert all(a.be_trigger_r >= 0 for a in ACTION_SPACE)` and
   `assert all(a.partial_tp_ratio <= 1 for a in ACTION_SPACE)` — a negative BE trigger would be a
   stop *above* entry on a short and is therefore a de-facto open.

`[PROPOSAL]` File paths (A28 fixes the missing directory): `dodgys_dd_quant/rl/ppo_agent.py`,
`reward.py`, `state_builder.py`, `action_space.py`, `position_manager.py` (the capability object).
The `rl/` directory is the one addition to the SVG-B package tree.

### D.2 — State, action, reward

| Element | Definition | Availability for NQ |
|---|---|---|
| **State** | `open_pnl_r` (unrealised, in R) · `peak_pnl_r` · `vxn_regime` (0/1/2) · `holding_time_bars` (normalised) · `order_book_imbalance` (normalised) | 4 of 5 available; **OBI missing** |
| **Action** | `position_multiplier ∈ {0.5, 1.0, 1.5}` × `be_trigger_r ∈ {0.0, 0.5, 1.0, 1.5}` × `partial_tp_ratio ∈ {0, 0.25, 0.5, 0.75, 1.0}` = **60 discrete actions** | — |
| **Reward** | Sortino-like: `r_t = ΔE[R]_t / max(σ_downside, ε)`, terminal `= realised R`; **plus** the 1.5R penalty `−λ · 1{peak_R ≥ 1.5 ∧ final_R < 0}` with `λ` a named constant (default `λ = 0.5`), per doc L152 | — |

`[INFERENCE]` The reward must be **per-trade terminal-dominant**: a Sortino-style per-step reward
computed on 1-minute deltas will reward noise. The episode reward should be the realised R of the
position under the policy, adjusted downward by the 1.5R failure penalty and by the realised cost in R,
with an optional small per-step shaping term. `λ` must live in the constants module with the other
thresholds.

`[PROPOSAL]` **All state features must be market-agnostic and lagged.** `open_pnl_r` and `peak_pnl_r`
are R-normalised (scale-free). `vxn_regime` is an index regime. `holding_time_bars` is dimensionless.
**`order_book_imbalance` must either be dropped or defined identically on every market** — see §D.3.

### D.3 — Where the RL's order-book-imbalance state comes from for NQ

`[FACT]` **It does not.** The lake's `bar_ofi` (1,636,229 BTCUSDT 1m bars, 2023-01-01 → 2026-02-14)
is the **only** multi-year order-flow-imbalance series that exists, it is **BTC-only**, and it is
**not in the canonical lake** — it sits under `~/iflow_lake/iflow/backtestTools/data/03_governed_lake/
v2_parquet_lake/crypto/high_frequency_lob/`, while the canonical
`~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/crypto/` contains only `funding_rate`,
`futures_swap` and `futures_um` (R4). The L2 files (`depth20`, `lob_depth_microstructure`,
`snapshots`, `trades`) cover **2026-03-26 / 2026-04-18 only** — one or two days.

`[PROPOSAL]` Three options, in order of preference:

* **O1 — Drop OBI from the state.** Replace it with a **price-derived, market-agnostic** imbalance
  proxy computable from the 1m bars every market has: e.g. the **close-location value**
  `(close−low)/(high−low)` of the current bar, or the signed body fraction, or the bar's
  tick-rule imbalance `(2·close − high − low)/(high − low)`. This keeps the state dimension fixed,
  keeps it computable on NQ at zero cost, and **makes the state vector identical on every market**,
  which is a precondition for any transfer (§D.4).
* **O2 — Buy NQ MBP/MBO** from Databento for the same period as the bars. Cost: MBP for NQ 1m over
  3 years is materially more expensive than the bars alone; and the OBI would then be a *different
  variable* from the crypto `bar_ofi`, so a BTC-trained policy still could not transfer.
* **O3 — Train on crypto, abstract the state.** Train the PPO policy on BTCUSDT 1m episodes *with*
  the real `bar_ofi`, then **drop the OBI input** and re-train (or re-learn) the final layer without
  it before applying it to NQ. This discards the OBI's information but preserves the transfer
  possibility. **Only O1 or O3 make the state vector market-agnostic, which is the precondition for
  D.4.**

### D.4 — The RL's training data, and why a BTC policy cannot be applied to NQ

`[PROPOSAL]` **Episodes.** One episode per position: from the rule engine's fill to the bracket
resolution (or a hard `max_episode_bars` cap). The environment's *default* action is the unmodified
rule bracket; the policy learns a **deviation** from it. This is the only sensible formulation when
the base rule is (possibly) profitable and the RL's job is to *manage* — doc L150/152.

**Training series.** The candidates that pass the ML gate, with their brackets and their realised
paths, on the **same 1-minute series** the policy will trade. `[INFERENCE]` For crypto that is
BTCUSDT 1m (2.05 M bars) with `bar_ofi` for 2023-01 → 2026-02; for NQ it is whatever multi-year 1m
arrives.

**Why a BTC-trained policy cannot be applied to NQ** — four independent reasons, any one of which is
sufficient:

1. **The state vector differs.** If OBI is in the BTC policy's state and NQ has no OBI, the input
   dimension differs and the weights are simply not applicable. This is an engineering fact, not a
   modelling subtlety.
2. **The path statistics differ.** The reward is a function of the *path* of returns in R units.
   Crypto trades 24/7 with no session gaps; CME has a 17:00–18:00 ET maintenance break, an RTH/Globex
   break, daily cash settlement, and index arbitrage. The distribution of "what happens to a position
   after 30 minutes" is not the same.
3. **The volatility–liquidity coupling differs.** Crypto 1m ATR is 0.28–1.08 R of round-trip cost;
   NQ 1m ATR is 0.045–0.091 R of cost. A policy tuned in a regime where costs are 5–20× larger will
   systematically prefer wide stops and late break-even moves — exactly the opposite of what NQ's cost
   structure rewards.
4. **The microstructure differs.** Crypto's 1m bars aggregate a continuously liquid order book; NQ's
   1m bars are a thin, tick-and-spread-dominated book with a 5-dollar tick on a $213 ATR. The
   *realised* intrabar path that the RL sees is far coarser on NQ — the RL literally cannot observe
   the intra-1m path it would need to time a break-even move.

`[INFERENCE]` **Conclusion:** the RL policy must be **retrained per market**, and the only transferable
artefact is the *design* (state normalisation, action grid, reward shape), not the weights. A policy
trained on BTCUSDT 1m must never be applied to NQ.

### D.5 — Why the RL is last, and what must be true before it is worth building

`[INFERENCE]` Five preconditions, in order:

1. **The base must have edge.** The RL manages positions; it cannot create them. If the rule+ML stack
   has net-negative expectancy, the RL is optimising a loss and will convert it into a *different*
   loss. **Measured today: the base is negative on both crypto markets (§B.6) and the ML layer's
   best case makes it worse (F8).**
2. **The candidate log must be trustworthy** (D2, INV4). Today it does not exist (D1).
3. **The action space must be defined** — A29 fixes the grids but they have never been executed.
4. **The state must be computable** — the OBI does not exist for NQ (§D.3).
5. **The evaluation must be honest.** The RL's natural evaluation is a *paired* comparison on the same
   episodes (same entries, different exit policy), which is a clean A/B — but it is still an
   in-sample comparison unless the episodes are split by time, and the comparison has a multiple-testing
   problem of its own (every policy variant is a trial).

`[PROPOSAL]` **The RL is the last thing to build, and only after the ML layer's acceptance test has
passed criterion §C.6.1–6.** Concretely: the RL earns its existence only if (a) the ML-gated book has
`E_net > 0` OOS, and (b) the RL can demonstrate on held-out episodes that its policy improves the
*realised* R of those positions by more than the cost of the deviation it introduces. A useful
sanity bound: **the RL can only add value if the base bracket's exit is materially suboptimal.** On the
measured data the base bracket is a fixed 1:2 with a window-extreme stop — and the *entire* measured
conditional structure (§B.5) lives in **where the stop is placed**, not in the exit. That is a hint
that the stop-placement rule, not an RL, is where the value is. **This should be tested before any RL
code is written.**

---

## E. End-to-end model — the pipeline of stages with gates

`[PROPOSAL]` Each stage has one input artefact, one output artefact, and one gate. A stage may not
start until the previous gate passes (`RULE_SPEC.md` §2.5 "Gate ordering rule").

| # | Stage | Input artefact | Output artefact | **Gate (must pass)** |
|---|---|---|---|---|
| **0** | **Data ingest & governance** | Databento DBN (NQ+ES per-contract 1m), CBOE VXN, (crypto: Binance Vision) | `03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/1m/*.parquet` + `macro/vxn/VXN_1d_consolidated.parquet`, with **`price_basis` declared** (§A.4) | the lake's 5 invariants + the flat-bar corollary pass (`incremental_update.py --audit`); `price_basis` present in the schema; **the 7/6 zero-volume non-flat bars are quarantined, not kept** |
| **1** | **Roll rule + session calendar** | the 1m parquets | `roll_boundary` table (ts, contract_id, kind) + `sessions.parquet` (session_id, open/close UTC, is_rth) | `roll_boundary()` is a single executable function used by both the filter and the test; no candidate's FVG window crosses a flagged boundary; DST switch-day assertions pass (`DATA_FEASIBILITY.md` §E3) |
| **2** | **Nautilus catalog + instrument definitions** | the parquets + the roll rule | `ParquetDataCatalog` (int64 **ns**, right-close) + `FuturesContract` for NQ (tick $5, mult $20) and ES (tick $12.50, mult $50) | the 20-bar smoke backtest runs and a 1-tick adverse fill is produced on a market order (`NAUTILUS_API.md` §3); `price_increment × multiplier` equals the documented dollar tick |
| **3** | **Rule engine (layer 1)** | the catalog | **`research/candidates/{symbol}_{timeframe}.parquet`** — the D2 schema, **every candidate including losers** (INV4) | the D2 schema validates; the candidate count on the NQ 1-week sample is 1,735 ± tolerance (a regression fixture, R6b); the E-1 reproduction on the NQ sample reproduces |
| **4** | **Vision cross-validation (layer 2)** — *optional, parallel* | the candidate log + a white 640×640 render of the last 60 bars | `vision_iou`, `vision_confidence` written **back into the candidate log** (D2 columns) | the **body-IoU** metric, calibrated threshold ≈ 0.5 (D6) — **`VISION_IOU_THRESHOLD = 0.75` is deleted**; the layer is a **feature generator**, not a gate, until it is calibrated |
| **5** | **Meta-labeling (layer 3)** | the candidate log + features + labels | **`artifacts/models/{symbol}/{asof_YYYYMMDD}/`** — `meta_label_lgbm.txt`, `meta_label_meta.json`, `meta_label_calibrator.json`, `walk_forward_index.json` (D3) | the §C.6 acceptance test passes on the concatenated OOS: `E_net[S] > 0` (CI excludes 0), `Δ` CI excludes 0, beats the no-FVG baseline, survives §F.5 |
| **6** | **Dynamic walk-forward backtest (layer 3→4 seam)** | the model artefacts + the candidate log | the **concatenated OOS equity curve** + the per-fold report (§F.2) | the forward-only assertion (D3) holds for every fold; no fold's model saw its own test month |
| **7** | **RL position management (layer 4)** | the OOS-validated candidate log + the OBI/proxy | `dodgys_dd_quant/rl/ppo_agent.py` + a policy artefact per market | the §D.1 "malicious policy" invariant test passes; the policy improves realised R on **held-out** episodes by more than the deviation cost |
| **8** | **Paper trading (forward test)** | the frozen artefact set + a `LiveNode` against IB / Tradovate / Rithmic **simulation** | a live candidate log + a paper P&L series | **4 weeks** of forward testing (doc L175) with **live slippage == backtest slippage**; the slippage-parity check below |
| **9** | **Live** | the same, with real money | — | not in scope |

**The slippage-parity check (stage 8)** `[PROPOSAL]` — the doc demands "验证实盘滑点与回测一致性"
(L175). It must be a *quantitative* assertion, not a vibe:

1. For every paper fill, record `fill_price − decision_price` in **ticks**.
2. Compare the paper distribution against the backtest fill model's distribution (0/1/2 ticks, D9):
   assert `median(paper_slippage_ticks) ≤ backtest_slippage_ticks + 1` and
   `P(paper_slippage_ticks > backtest_slippage_ticks + 2) < 0.05`.
3. Compare the paper **fill rate** against the backtest's (a backtest fills every market order;
   a live book does not). Any paper/backtest fill-rate gap > 10 % invalidates the P&L comparison.
4. Re-run the §C.6 acceptance test **on the paper series** with the same criteria. The paper result is
   the gate for live, not the backtest.

**Full sequence, naming the artefact at every hand-off** `[PROPOSAL]`:

```
Databento DBN  ──govern──►  governed 1m parquet (price_basis declared)
                                │
VXN daily ──govern──► VXN_1d.parquet ─┐
                                      ├──►  features + labels  ──►  candidates/{sym}_{tf}.parquet (D2)
1m bars ──rule engine──► ──────────────┘                                    │
                                                                           ├─► features.parquet
                                                                           └─► labels.parquet
                                                                                   │
                                          purged walk-forward (6/1/1, embargo 1440 bars)
                                                                                   ▼
                                              artifacts/models/{sym}/{asof}/  (D3: lgbm.txt + meta.json
                                                                              + calibrator.json)
                                                                                   │
                                        walk_forward_index.json  ──►  dynamic OOS equity curve
                                                                                   │
                                              (stage 8)  LiveNode paper  ──►  paper candidate log
                                                                                   │
                                                                                   ▼
                                                                          slippage-parity report
```

---

## F. Dynamic backtesting — "如何根据动态的训练情况动态的回测"

### F.1 — The definition, precisely

`[PROPOSAL]` **Dynamic backtesting = walk-forward simulation with per-fold model selection.** It is a
*simulation of the operational loop*, not a second training procedure:

> For each test month `t` in the 40-fold schedule, the model trained on data **strictly before** `t`
> (train = `t−7..t−2`, valid = `t−1`, embargoed, D3's `asof < ts_event` asserted) **decides the
> trades of month `t`**. The fold's trades are executed under the frozen cost model with the
> one-position-at-a-time constraint. The fold's P&L is appended to the equity curve. The final equity
> curve is the **concatenation** of the 40 folds, in time order, with **no re-fitting and no peeking**.

`[INFERENCE]` Three properties that must hold, and which distinguish it from "train once, backtest once":

* **The model in force on date d is the one whose `asof < d`** — pinned by `walk_forward_index.json` (D3).
  The backtest **must assert** this, not assume it.
* **The equity curve is a concatenation, not an average.** Each fold contributes its own realised
  trades; nothing is re-weighted.
* **The model is re-selected monthly**, so the curve embeds the *operational* cost of retraining and
  the *operational* risk of a model that has decayed.

`[INFERENCE]` **What dynamic backtesting does and does not do.** It **does not manufacture an edge**:
it is still the same rule engine and the same features, evaluated out-of-sample. What it *does* is
**measure how fast an edge decays once it exists**, and — critically for this project — **it is the
instrument that reveals the decay before the money is at risk**. In this project it is *also* the
instrument that would reveal that there was never an edge (§C.6's abort criteria).

### F.2 — What must be reported per fold

`[PROPOSAL]` Every fold writes one row to `artifacts/reports/walk_forward/{symbol}_{tf}/folds.csv`
with **at least** these fields:

| Field | Why |
|---|---|
| `fold`, `train_start`, `train_end`, `valid_start`, `valid_end`, `test_start`, `test_end` | the windows, so the embargo is auditable |
| `asof` (D3) | the forward-only assertion |
| `n_candidates` | the population; the label base rate |
| `n_candidates_labeled`, `n_censored` | the censoring rate (≈4 % by construction) |
| `base_rate` (`p`) in the fold | the label base rate must be reported per fold, not assumed constant |
| `n_trades` (portfolio), `n_trades_kept` (ML-accepted), `kept_fraction` | the funnel |
| `win_rate` (portfolio and kept) | |
| `expectancy_R_gross`, `expectancy_R_net` for portfolio / kept / base | **net of cost** (§D.9) |
| `PF`, `PF_net` | the phase-1 gate metric |
| `CI95` on expectancy (block bootstrap by month) | |
| `max_drawdown_R`, `max_consecutive_losses` | |
| `auc_test`, `accuracy_test`, `brier_score` | the model's own quality on this fold |
| `feature_importances` (top 10, gain) | per fold — **the drift signal** |
| **`p_pred_distribution`**: mean, sd, and the 5/25/50/75/95 percentiles of `P̂(Win)` on the fold's candidates | **the prediction-drift signal** (§F.3) |
| `p_pred_distribution_train` (the same percentiles on the fold's *training* set) | the reference for drift |
| `cost_R` mean/median on the kept subset | the fee/slippage sensitivity |
| `n_roll_boundary_bars_excluded` | the roll filter's activity |

### F.3 — Degradation monitoring and the kill-switch

`[INFERENCE]` **The "dynamic training" signal the user asked about is prediction drift.** A model does
not announce its decay; it drifts. The three observable signals, in order of usefulness:

1. **Prediction-distribution drift.** Compare the live fold's `P̂(Win)` percentiles against the model's
   own training distribution (both stored in the artefact). A monotone shift of the median `P̂` by more
   than **0.05** absolute, or a collapse of the `P̂` spread (σ < 50 % of its training value), means the
   input distribution has moved. `[PROPOSAL]` **flag**, not auto-kill, on drift; a distribution shift
   with unchanged *realised* p is benign.
2. **Realised-vs-predicted calibration.** On each fold, bin the candidates by `P̂` and compare the
   realised win rate per bin against the prediction (a reliability curve). `[PROPOSAL]` **kill-switch
   trigger**: the realised win rate in the top decile of `P̂` falls below **0.45** (the threshold implied
   by the D9 cost model: `p > (1+0.091)/3 = 0.364` for the *whole* book, so the top decile must be far
   above it) for **two consecutive folds**. Two folds, not one, because a single fold has se(p) =
   2.55 pp (§B.7).
3. **Feature-importance churn.** If the top-2 features change between consecutive folds by more than
   half their gain, the model is refitting to noise.

**The kill-switch** `[PROPOSAL]` — three levels, all in the backtest/paper config, not in strategy logic:

| Level | Trigger | Action |
|---|---|---|
| **K1 — degrade** | any one of the three drift signals above | **stop trading the affected fold**; retrain with a longer window (12 months) and re-validate; log everything |
| **K2 — halt** | K1 twice within 6 months, **or** the realised top-decile win rate below 0.45 for 3 consecutive folds, **or** the paper/book slippage-parity check (§E) fails | **stop trading entirely**; the model is retired; a new `asof` is required before trading resumes |
| **K3 — kill the project** | the §C.6 abort criteria (A1–A5) trigger on the concatenated OOS | the strategy is abandoned; publish the negative result |

`[INFERENCE]` The doc's phase-3 requirement of **4 weeks of forward paper trading** (L175) is the
*minimum* observation window for K1/K2, but it is **not sufficient** to detect a 2 pp expectancy
degradation (se(p) = 2.55 pp per fold → 4 weeks ≈ 1 fold ≈ 2.6 pp of noise). `[PROPOSAL]` **The paper
window must be ≥ 3 months (12 folds) before the paper result is treated as evidence about the edge**,
and even then only as evidence about *stability*, not about the existence of an edge.

### F.4 — What the paper stage must prove

See §E, stage 8. The paper stage proves **slippage parity** and **operational stability** (no
crashes, no missing candidates, the model in force is the right one). It does **not** prove an edge;
that is what the concatenated OOS is for. `[INFERENCE]` Reporting the paper P&L as "validation" of the
strategy would repeat the phase-1 mistake in a new place. On NQ the *portfolio* rate is bounded by the
holding time, not by the candidate rate: the measured NQ 1-week file yields **1,735 FVG candidates and
1,016 triggered trades in 5 trading days** (≈ 69 candidates/day, ≈ 40 triggered/day — far above
`AUDIT.md` §D.3's pre-data estimate of 2–7/day), but the crypto-measured holding-time distribution
(median 32 bars, mean 125 bars) caps a one-position-at-a-time book at roughly **5–12 trades/day** on a
1-minute series. Four weeks of paper trading is therefore **≈ 100–330 trades**, giving
`se(p) = sqrt(0.33 × 0.673 / n) ≈ 2.6–4.7 pp` and a **95 % CI of ±5.1 to ±9.3 pp on the win rate** —
wide enough to contain both "profitable" and "hopeless". The paper stage's job is parity, not validation.

### F.5 — Multiple-testing correction

`[FACT]` The project has **already** run **32 pre-registered arms** (E-1) plus a **concurrency
artefact** (a 33rd and 34th "arm" that were reported and then retracted), plus, with this leaf, a
**32-arm ETH replication** and a **6-threshold × 2-market × 2-half filter grid** (24 more), plus the
split-half binning studies (5 features × 2 halves × 2 markets). That is already **~90 distinct
configurations** whose results have been looked at.

`[PROPOSAL]` The method is the **Deflated Sharpe Ratio** (Bailey & López de Prado) for the headline
statistic, plus the **Probability of Backtest Overfitting (PBO)** via Combinatorially Symmetric
Cross-Validation (CSCV) for the selection procedure. **What DSR requires that we do not yet have:**

1. **A complete, immutable trial registry.** Every backtest configuration ever run, with its full
   OOS return series, appended to a write-once ledger (`artifacts/trials/registry.parquet`). E-1's 32
   arms, this leaf's ~90 configurations, and every future run must be registered **before** the result
   is inspected. Without the registry, DSR is not computable and the number of trials is unknowable —
   which is exactly how the census arm got reported.
2. **The number of trials `N`** — from the registry.
3. **The skewness and kurtosis** of the trial return series — computable from the registry.
4. **The variance of the trial Sharpe ratios** — the registry's `Sharpe` column.
5. **Non-overlapping OOS segments for CSCV** — the 40 monthly folds provide them.

`[PROPOSAL]` **The practical form.** For the headline claim ("the ML filter creates positive net
expectancy"), report the **DSR of the OOS Sharpe** of the concatenated equity curve, using `N` = the
number of registered trials, and report the **PBO** from CSCV over the 40 folds. **Acceptance requires
`DSR > 0.95`** (i.e. the probability that the observed Sharpe exceeds the best of `N` trials by chance
is < 5 %).

`[INFERENCE]` **What the bar is in R.** With `N ≈ 90` trials, the expected best-of-90 Sharpe sits near
**2.6σ**, so the observed statistic must clear roughly **t ≈ 3** on the per-trade R series (measured
per-trade σ ≈ 1.407 R). That converts to a net expectancy of `3 × 1.407 / √n`:

| Population | n | se(E[R]) | net expectancy for t ≈ 3 |
|---|---|---|---|
| crypto OOS (all 40 folds) | 15,928 | 0.011 R | **+0.033 R** |
| NQ, 3 y, 5 trades/day | ~5,500 | 0.019 R | **+0.057 R** |
| NQ, 3 y, 12 trades/day | ~13,000 | 0.012 R | **+0.037 R** |

`[INFERENCE]` **And the D9 NQ round-trip cost is 0.045–0.091 R.** So on NQ the *entire* statistical
detection threshold of the ML layer is of the same order as the trading cost it must exceed. **The
project does not have enough statistical power to detect an edge smaller than its own round-trip
cost** — which argues for (a) more NQ history than 3 years, (b) accepting a longer paper/live
validation horizon, or (c) a rule engine with a *higher* candidate density than NQ's ~40/day.
**This should be settled before the ML pipeline is built, because it determines whether the experiment
is worth running at all.**

`[INFERENCE]` **A second, cheaper discipline that must also be applied: report the *worst* arm, not
the best.** E-1's "best arm" framing is what produced the retracted census result. The report format
should be: **the pre-registered primary arm's result, with the full arm table beside it**, and the
acceptance decision is taken on the **primary** arm only. Selecting the best arm post hoc is exactly
the multiple-testing failure the DSR is there to catch.

### F.6 — The honest summary of dynamic backtesting

`[INFERENCE]` Dynamic backtesting **cannot manufacture an edge**. It is a *measurement instrument for
the decay rate of an edge that already exists*, plus a *discipline* that forces every claim through a
forward-only, embargoed, per-fold selection. On the evidence in this leaf, its most likely immediate
output is **the negative**: the walk-forward will confirm (F5, F6, F8) that the rule engine's win rate
is ≈ 1/3 on any instrument we can test, that the ML layer's best case is bounded by a cost it cannot
control, and that the doc's `P ≥ 0.58` gate is actively harmful. **That is a legitimate and valuable
result** — and it is the result the project's own upstream author reached
(`research/github/IFVG-Ultimate-Dodgy/README.md`: *"So does the strategy have any value? NO"*).

---

## G. Verdict

```
DATA SUFFICIENT FOR PHASE 1 (NQ):     no
   — the blocking gap is multi-year NQ+ES 1-minute WITH a roll rule and a declared
     price basis (the lake holds one week: NQ 7,490 / ES 7,489 rows). Cost ~$100–300
     (Databento) or ~50 min of free-but-provenance-poor community data. Everything
     else (VXN, calendar, fees, roll detector, price-basis mapping) is free code work.

DATA SUFFICIENT FOR PHASE 1 (crypto):  conditional
   — BTCUSDT/ETHUSDT 1m (2,046,240 bars, gap-free, 47 months) DO support the doc's
     6/1/1 walk-forward arithmetically (40 folds, ~9,016 candidates and ~339 portfolio
     trades per test month) and are the correct instrument for settling "does the rule
     engine have an edge?". They do NOT support a profitability claim: the measured
     round-trip cost is 0.28–1.08 R per trade, so every bin of every conditional
     structure is net-negative. Crypto 1-minute is a cost-arithmetic dead end.

MISSING DATA, PRIORITISED:
   1. Multi-year NQ + ES 1-minute, PER-CONTRACT, ≥3 y  (Databento, ~$100–300,
      1–2 days)                          — without it nothing about NQ can be settled.
   2. The roll rule + roll_boundary() detector (included above, 0.5 day)
      — without it a roll gap manufactures scored setups.
   3. A declared price_basis for the stored series + a tradable FuturesContract
      (included above, 0.5 day) — the stored NQ/ES 1m is the INDEX level; applying
      multiplier 20 to it is a 50× P&L error.
   (then, cheap and free: the session/DST calendar 1 d; the broker fee schedule hours;
    tick/MBP data for slippage parity and the RL's OBI state; an intraday volatility
    proxy to replace the dropped 1-hour VXN change — an ATR-ratio from the 1m bars
    is free and better than VXN.)

ROLLING ML DESIGN:  Train a LightGBM binary meta-labeler on the D2 candidate log
   (every candidate, losers included), on 6/1/1 monthly purged walk-forward folds with
   an exact horizon purge plus a 1,440-bar embargo, `LABEL_HORIZON_BARS = 480` capping
   the label, `scale_pos_weight ≈ 1.90` plus isotonic recalibration on the validation
   fold, early stopping on the validation fold only, and the D3 artefact layout with
   `walk_forward_index.json` pinning the forward-only rule. The feature set is the
   doc's six (minus the dropped 1-hour VXN change, replaced by an ATR-ratio; minus
   vision, which degrades to NaN) PLUS the four ATR-normalised geometry features the
   measurements identify — `risk_in_atr` is the single strongest (split-half ρ = +0.93).
   The gate is NOT `P(Win) ≥ 0.58` (which implies a 58 % win rate and, by
   measurement, costs −4.46 R per trade on crypto) but `3·P̂ − 1 − cost_R > 0`, i.e.
   `P̂ > (1 + cost_R)/3` — a per-candidate threshold of 0.348–0.364 on NQ.

ROLLING RL FEASIBLE TODAY:  no
   — the state, action and reward can be specified and the "never open a position"
   invariant can be enforced in code (four independent mechanisms + the malicious-policy
   test), but the RL's fourth state variable (order-book imbalance) does not exist for
   NQ, the candidate log it would manage does not exist, the base book it would manage
   has no measured positive expectancy, and a BTC-trained policy is provably not
   transferable (§D.4). RL is last, and only after §C.6 passes.

E2E PIPELINE:  Ten gated stages with one named artefact per hand-off: governed
   per-contract 1m parquet (price_basis declared) → roll_boundary + session calendar →
   Nautilus catalog + FuturesContract (tick $5 NQ / $12.50 ES) → rule engine →
   research/candidates/{symbol}_{timeframe}.parquet (D2, every candidate) → features +
   labels → artifacts/models/{symbol}/{asof}/ (D3) → concatenated walk-forward OOS
   equity curve → RL policy (optional) → 4 weeks of LiveNode paper trading (the doc's
   parity gate; ≥3 months to be evidence about the *edge*) with a quantitative
   slippage-parity assertion (median ≤ backtest + 1 tick, P(>backtest+2) < 0.05,
   fill-rate gap < 10 %) → live. Every gate is a pre-registered numeric test;
   a negative phase-1 result is a rule-reproduction defect to be reported, never masked.
```

### Top-3 missing data items (ranked)

1. **Multi-year NQ + ES 1-minute, per-contract, ≥3 years** — the only purchase that unblocks the
   project's own target market. Databento CME Globex, **≈ $100–$300** (the doc's "$10–30" is flagged
   unverified in `DATA_FEASIBILITY.md` §D Option 3), 1–2 days. Interim, free, provenance-poor
   substitute: the two community HF 1-minute datasets (~0.2 GB, ~50 min at the host's 69 KB/s) —
   but the NQ side has no roll metadata, so the roll detector becomes mandatory rather than optional.
2. **The roll rule and the price-basis declaration** (both free, both blocking, 1 day total) —
   without the roll rule a single roll gap manufactures a scored setup with a stop and a 2R target;
   without the price-basis declaration the stored index-level series produces a 50× P&L error when
   fed to `FuturesContract(price_increment=0.25, multiplier=20)`.
3. **A named broker's fee schedule + intrabar/tick data for the sample** — D9's "$4.50" has no
   owner, and 1–2 ticks of NQ slippage ($5–$10/side) is the difference between PF 1.30 and PF 1.22.
   Databento MBP for the same period as the bars, or a broker's own historical depth.

---

## Appendix R — Reproduction commands

All run on the uv-managed 3.11 interpreter:
`PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`

| ID | Command | Result |
|---|---|---|
| **R1** | `ls ~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/1m/` then `pq.read_table(...).num_rows` | NQ **7,490**, ES **7,489**; `2026-09-24 04:09` → `2026-10-01 14:48/14:47` |
| **R2** | `pq.read_table` over the whole `us_futures`, `crypto/futures_um`, `macro`, `us_equities/QQQ` trees | the full tree in §A.1; BTC/ETH 1m = **2,046,240** rows each (2023-01-01 → 2026-11-21); VXN **4,327**; DVOL **26,665**; QQQ 15m **73,325** |
| **R3** | timestamp-set intersection of NQ_1m / ES_1m; gap histograms; zero-volume non-flat scan | intersection **7,488**/7,489; gaps {60 s: 7,479, 61 min: 4, 11 min: 4, 49.2 h: 1, 2 min: 1}; **NQ 7 / ES 6** zero-volume non-flat bars |
| **R4** | `find ~/iflow_lake -name "*high_frequency_lob*"`; `os.path.exists(.../iflow/database/.../crypto/high_frequency_lob)` | present **only** under `iflow/backtestTools/data/...`; **absent** from the canonical lake |
| **R5** | `pq.read_table(macro/vxn/VXN_1d_consolidated.parquet)` | 4,327 rows, 2009-09-14 → 2026-11-20 |
| **R6** | `pq.read_table` on the funding-rate and DVOL partitions | funding 4,200 prints each (2023-01-01 → 2026-10-31); DVOL 26,665 hourly bars (2023-10-01 → 2026-10-16) |
| **R6b** | E-1 engine on `us_futures/NQ/1m/NQ_1m.parquet` and `ES/1m/ES_1m.parquet` | NQ **1,735** FVG candidates, **1,016** closed, p = **0.324**, E[R] = −0.029, CI [−0.115, +0.058]; ES 1,563 candidates |
| **R6c** | distinct entry-bar count over the BTC census | 423,759 trades over **345,831** distinct entry bars = **1.23** trades/bar |
| **R7** | E-1 engine + monthly aggregation (47 months) | the monthly table in §B.7; 40 folds |
| **R7b** | re-scan forward from each portfolio entry bar to its resolution | horizon: median 32, p90 236, p95 428, p99 1,473, p99.9 5,726, max 35,745 bars; mean 125; 34.2 % > 60 bars; 9.79 % > 240 bars |
| **R8** | close-range and min non-zero close-to-close change on NQ_1m / ES_1m | NQ 30,372.25–31,148.25, ES 7,685.00–7,813.75; min Δ = **0.25** on both |
| **R9** | ATR(14) of NQ_1m / ES_1m (median, bars 50+) | NQ **10.66** index pts ($213); ES **1.73** index pts ($87) |
| **R10** | per-trade `cost_R = 0.0008 · price / risk` over the census and portfolio | BTC census mean **1.08 R**, portfolio **0.41 R**; ETH portfolio 0.28 R |
| **R11** | split-half (2023-24 / 2025-26) conditional win rate by bin + Spearman ρ between halves | the table in §B.5 |
| **R12** | the same, stratified by `runup_atr` | the `risk/ATR` effect survives; `runup` alone has no effect (p = 0.3406 vs 0.3456) |
| **R13** | BTC: filtered one-position-at-a-time portfolio at 6 `risk/ATR` thresholds | the table in §B.6 |
| **R14** | ETH: same | the ETH table in §B.6 |
| **R15** | moving-block bootstrap (1,000 resamples; blocks 300/1,440/4,320) on the census and portfolio R series | the table in §B.2 |

Scratch scripts used for R1–R15 live in `/tmp/l4_*.py` and are **not** part of the repository.
**No file was written to the NFS lake**; every lake read was `pq.read_table` on an existing governed
partition.

---

*End of L4.*
