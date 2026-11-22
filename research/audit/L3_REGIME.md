# L3_REGIME — the regime layer: is VXN / VIX correlated with the iFVG signal, and does it reach the order decision?

**Leaf:** L3 (regime) · **Type:** read-only audit · **Date:** 2026-11-22
**Deliverable owner:** `research/audit/L3_REGIME.md` (this file)

**Evidence labels used throughout**

| Tag | Meaning |
|---|---|
| `[FACT]` | Read directly from a named artefact in this repo or in the data lake, or measured by me on a named artefact (method in Appendix A). |
| `[INFERENCE]` | Reasoned from one or more `[FACT]`s; the reasoning is stated. |
| `[PROPOSAL]` | A design decision made by this audit; not derivable from the artefacts. |

**Constraints honoured** — no file modified except this one; the NFS lake was read, never written;
the exploratory analysis in §C.4 / Appendix A ran from throwaway scripts in `/tmp`; no agent
dispatched; no `decisions.md` edit.

**Decisions this leaf obeys and does not re-litigate:** D1 (the four-layer system is *not*
implemented), D2 (the frozen candidate-log schema), D4 (the rule engine has no measured edge;
one-position-at-a-time is the only quoting basis; the census arm's t = 15.28 is an artefact),
D5 (data reality), D6 (vision gate re-spec), D8 (no grade filtering), D9 (costs live in the
config), D10 (read the upstream corpus read-only).

---

## 0. The answer, up front

> **Q4a — Is VXN / VIX (or any other regime variable) subjected to a correlation check?**
> **No.** There is **no correlation test, no conditional-expectancy test, and no
> feature-importance report anywhere in this repository.** Every quantitative statement about the
> regime in the design discussion is an *un-cited assertion* ("实证研究表明…", `iFVG几个模型的讨论.txt`
> L106). The one executable piece of regime code in the whole repo is a 10-line snippet embedded
> in the discussion itself (L259–269), it is not part of any package, and it crashes on modern
> `yfinance` (`RULE_SPEC.md` B4).

> **Q4b — Is the regime actually wired into the strategy and the order decision?**
> **No.** The package `dodgys_dd_quant/` **does not exist** (`ls` → *No such file or directory*).
> There is no rule engine, no `Strategy`, no meta-labeling pipeline, no RL agent. The regime is a
> *diagram label* and a *prose paragraph*. Nothing consumes it.

> **The data half of the question is in better shape than the code half — but not as good as D5
> states.** VXN exists exactly as D5 says (4,327 daily bars). **VIX also exists**, in two places
> D5 does not mention (§B). But **the NQ 1-minute sample the whole strategy is built on contains
> exactly one regime value**, and **the doc's VXN bands do not transfer to VIX** — the same
> thresholds put 60 % of all VIX days into "low-vol range". The regime layer is therefore, today,
> a **reporting stratifier**, not a decision input, and even as a stratifier it is currently
> **underpowered by roughly a factor of two** relative to the effect it would need to detect.

**The headline exploratory result (§C.4):** on the one market where a regime-conditioned test can
be run today with real data (BTCUSDT 1-minute, 3.9 years, 15,928 one-position-at-a-time trades),
the doc's literal VXN bands produce a *nominally* significant band contrast in one of four
pre-registered rule arms — but the same variable expressed scale-free (trailing-1-year tertiles)
gives **p = 0.85**, a self-referential **realised-volatility control** gives a *smaller* effect,
and the contrast **collapses to p = 0.85 when the inversion window changes from `[0,15]` to
`[7,15]`**. After Holm correction over 16 comparisons nothing survives. This is the exact
signature D4 describes for the unconditional edge: *a result that does not survive a defensible
re-parameterisation.*

---

## A. Implementation status — every hit, file and line

### A.1 What actually exists as code

`[FACT]` The repository's entire executable corpus is **one** Python file,
`research/experiments/e1_rule_falsification.py` (431 lines, stdlib + pyarrow). It contains
**no** regime code: no VXN, no volatility index, no regime band, no regime feature, no
correlation, no permutation test. Its 32-arm grid is
`WINDOWS × ATR_FLOORS × FILLS × SWEEP_GATES × CONCURRENCY` (lines 71–77) — **the word "regime"
does not appear in it.**

`[FACT]` `dodgys_dd_quant/` does not exist. The four planned modules
(`data_pipeline/prepare_parquet.py`, `vision_validator/visual_cv.py`, `strategy/custom_data.py`,
`strategy/state_machine.py`, `strategy/dodgys_strategy.py`, `ml_pipeline/meta_labeling_train.py`)
are described only in `AGENTS.md` (lines 44–47) and `diagram-目录结构规划.svg`. `configs/`,
`tests/`, `data/` do not exist either.

### A.2 Every regime mention in the repo, classified

**The design discussion (`iFVG几个模型的讨论.txt`) — the origin of every claim**

| Line | What it says | Status |
|---|---|---|
| L76 | The user's own question: *"是否要根据市场情况市场regime应变学习（例如恐慌NQ指数？**是否有相关性**）"* — the question this leaf answers. | `[FACT]` question, unanswered |
| L93 | Proposes `VXNRegimeData` as a `nautilus_trader.core.data.Data` subclass pushed onto the engine timeline. | `[FACT]` design intent only |
| L103–L105 | "CBOE VXN tracks NDX implied vol; **strong correlation verification**: VXN is a better fit for NQ than VIX, usually 2–5 points higher." | `[FACT]` the "strong correlation" claim has **no** computation attached; the *level* part of it is **measured and confirmed** in §B.4 — but "correlation" here is claimed between *the index and the market*, never between *the regime and the signal* |
| L106–L109 | The three-band policy: low (< 18) → A+ only, RR 1:1.5–1:2; normal (18–28) → RR 1:2.5–1:3; high (> 28) → halve risk, raise ATR gap floor. Preceded by *"实证研究表明"* ("empirical research shows") with **no source, no sample, no statistic**. | `[FACT]` un-cited assertion |
| L146 | ML feature list: *"当前 VXN 绝对值及 **1 小时变化率**"* — VXN level and 1-hour change rate. | `[FACT]` the 1-hour change rate is **unsatisfiable** from a daily series (`RULE_SPEC.md` A18; dropped per `DATA_ACQUISITION.md` §6) |
| L151 | RL state: *"VXN 波动率状态"* alongside PnL-in-R, holding time, order-book imbalance. | `[FACT]` design intent only |
| L158–L163 | Migration table: NQ→VXN, MES→VIX, QQQ→VXN, GC→GVZ, BTC/ETH→DVOL. | `[FACT]` **only VXN and DVOL have data** (§B) |
| L207 | VXN retrieval: CBOE / Databento / `yfinance ^VXN`, daily **or intraday**, forward-fill + 1-bar lag. | `[FACT]` as written, the `bfill` leaks (§E.5) |
| L259–L269 | The **only** executable regime code in the repo: `yf.download("^VXN", …, interval="1d")` → `vxn_known = Close.shift(1).bfill()` → `pd.cut(bins=[0,18,28,200], labels=[0,1,2])` → `vxn_aligned.parquet`. | `[FACT]` not in any package; `pd.cut` right-closes so it disagrees with the prose at exactly 18 and 28 and **raises** on out-of-range values (`RULE_SPEC.md` I05, §1.9); `bfill()` back-fills from the future at the head of the series |
| L172, L177–183 | Phase-1 deliverable: export all phase-1 signals and *"接入 VXN 历史序列"* (attach the VXN history). | `[FACT]` never done — no phase-1 export exists |

**The diagrams**

| File:line | What it says |
|---|---|
| `diagram-四层正 EV 量化系统完整架构.svg:15` | Data layer: *"数据层 : NQ + ES 1m/5m Tick/Bar + VXN 指数"* |
| `diagram-四层正 EV 量化系统完整架构.svg:136` | ML input: *"规则评分 + 视觉置信度 + **VXN Regime** + 时间衰减特征"* |
| `diagram-目录结构规划.svg:54` | Module #1: *"Databento/Tick数据与 **VXN清洗**并写入 Nautilus ParquetCatalog"* |
| `diagram-目录结构规划.svg:75` | Module #3: *"**VXN指数**与视觉验证信号的自定义 Data对象"* |

`[FACT]` The SVG ML-input list (L136) **disagrees** with the prose feature list (L146) — already
logged as `RULE_SPEC.md` I04. The prose list is normative.

**The research corpus (specification, not implementation)**

| File:line | What it does |
|---|---|
| `research/docs/RULE_SPEC.md:199–205` | T07–T13: the VXN bins and the three per-band policies, each tagged `[DOC]` (source = the discussion, not code) |
| `research/docs/RULE_SPEC.md:218, 220` | T26 (feature list), T28 (RL state) |
| `research/docs/RULE_SPEC.md:238–242` | T46 (0.5 % risk in high vol), T47 (data layer), T49/T50 (the lag and the retrieval) |
| `research/docs/RULE_SPEC.md:261, 270, 271, 282, 621` | A09 (grade thresholds), **A18** (the 1-hour change rate — *"Do not fabricate … drop the feature"*), A19 (how much larger the ATR gap in high vol), A30 (what "1 % risk" means), **A34** (bins for VIX/GVZ/DVOL — *"use the **percentile** mapping instead of absolute points"*) |
| `research/docs/RULE_SPEC.md:336` | I05: the `pd.cut` binning conflict |
| `research/docs/RULE_SPEC.md:344–352` | §1.9: the **corrected** binning `(-∞,18) → 0 | [18,28] → 1 | (28,∞) → 2` |
| `research/docs/RULE_SPEC.md:405` | INV6: *"No look-ahead: every exogenous series is lagged … the regime label is derived from the lagged value"* |
| `research/docs/RULE_SPEC.md:524–525` | The migration table with the note that *"the bins `[0,18,28,200]` are stated for **VXN only**"* |
| `research/audit/AUDIT.md:774–800` | §C.3: daily VXN is reachable, the 1-hour feature is unsatisfiable, `bfill` leaks, and — importantly — *"the regime is used as a **gate**, not only a feature … the regime is a **daily** series while the gate is applied **intraday**"* |
| `research/audit/AUDIT.md:796–800` | The already-recommended reconciliation: *"Apply the regime as a **reporting stratifier**, not a gate, in phase 1"* |
| `research/analysis/DATA_FEASIBILITY.md:553–601` | §E4 (the `bfill` leaks) and §E5 (the VXN-look-ahead checks, incl. *"the previous trading day's close **is** known at 09:30 ET the next day"*) |
| `research/analysis/DATA_ACQUISITION.md` §6 | VXN ingested: *"4,327 daily bars, 2009-09-14 → 2026-11-20 … regime occupancy (bands [0,18,28,200]): low=1541 normal=2099 high=687"*, and *"The **1-hour VXN change-rate feature is dropped**"* |
| `research/analysis/ML_REUSE.md:250` | `sentiment_strategy` (the only third-party artefact that uses VIX/DXY) → **discard**: *"VIX/DXY sentiment — we use VXN"* |

**Third-party code (not ours, and discarded per D7)**

| File:line | What it does |
|---|---|
| `research/huggingface/xauusd-ml-trader/xauusd_trader/strategies/sentiment_strategy.py:36, 65–78` | Downloads `^VIX` via yfinance, builds a `vix_level = (vix − 20)/20` risk-off score. **Discarded** (D7 / `ML_REUSE.md:250`). |
| `research/huggingface/xauusd-ml-trader/xauusd_trader/ml/ensemble_model.py:268–280` | The only feature-importance code in the repo — in a **discarded** third-party module, and it is a *directional* 3-class ensemble, not our meta-label. |
| `research/github/dataBaseLake/01_raw_lake/github/cenkcorapci_download-lots-of-financial-data/scripts/downloaders/stocks.py:101,105` | An upstream **downloader** for `^VIX, ^VXN, ^RVX`. Part of the vendored lake corpus, not our code, and not wired to anything. |

### A.3 The two questions, answered plainly

`[FACT]` **A correlation check does not exist.** A repo-wide search for
`correlat|feature_importance|importance|permutation|shap` across `research/` returns only (i)
third-party code in the discarded `xauusd-ml-trader`, and (ii) prose. There is no correlation
matrix, no conditional-expectancy table, no permutation test, no importance report, and no
p-value attached to any regime claim.

`[FACT]` **A regime → order-decision path does not exist.** No package, no `Strategy`, no
`StateMachine`, no `MetaLabelingTrainer`, no RL environment. The only place a regime value could
enter the order decision is the discussion's snippet, which is not executed by anything.

`[FACT]` **One correlation between two regime variables *has* now been measured for the first time
in this project** (§B.4): corr(VXN, VIX) = **0.7495** on 391 overlapping daily observations
(2024-09-23 → 2026-09-22), and the doc's claim that "VXN is usually 2–5 points above VIX" is
confirmed (mean +4.27, median +3.75, VXN > VIX on 97.2 % of days). But this is a correlation
*between two indices* — not the correlation the user asked about, which is **between the regime and
the signal's expectancy**.

---

## B. Data availability, measured

All rows below were verified by reading the files on the **canonical NFS mount**
(`~/iflow_lake/iflow/database/`, `nfs://fnos2.local/fs/1000/nfs/iflow/database`).

### B.1 The volatility indices

| Series | Where it actually is | Coverage | Granularity | Governed / registered? | Knowable at decision time? |
|---|---|---|---|---|---|
| **VXN** | `03_governed_lake/v2_parquet_lake/macro/vxn/VXN_1d_consolidated.parquet` | **4,327** bars, 2009-09-14 → 2026-11-20; weekday-only (**0** weekend rows; Fri 811, Mon 890, Tue 887, Wed 871, Thu 868) | daily | ✅ governed, ✅ registered — `manifest/manifest.json:556–566` (`macro_indices` → `VXN`, path `macro/vxn/`, timeframes `["1d"]`) | ❌ **the timestamp is wrong for a lagged join** — see B.3 |
| **VIX (a)** | `02_pipeline_engine/nautilus_crypto_pipeline/catalog/data/bar/VIX-INDEX.CBOE-1-DAY-LAST-EXTERNAL/VIX-INDEX.CBOE/{2024,2025,2026}/*_bars.parquet` | **503** bars, 2024-09-23 → 2026-09-22; close 12.77 … 52.33; weekday-only (Mon 105, Tue 102, Wed 98, Thu 99, Fri 99) | daily | ❌ **not** in the governed parquet lake, ❌ **not** in `manifest.json`, ❌ **not** in `nautilus_databank/MANIFEST.md` (which lists 63 bar types and includes `SPX.CBOE` and `NDX.NASDAQ` but **no** VIX) | ⚠️ `ts_event` = **07:00 UTC** on the trade date, `ts_init` = 23:59:59.999 the *same* UTC day → the bar spans [07:00, 24:00) UTC, i.e. it is **not** stamped at the 16:15 ET close. A join must be done on the trade date, not on the timestamp. |
| **VIX (b)** | HF `twelvedata/financial-world-model` → `01_raw_lake/huggingface/twelvedata_financial-world-model/bars_1day/{train,val,test}.parquet`, column **`vix_level`** | `train` 481,635 rows / 51 symbols, 1970-01-02 → 2023-12-29, **`vix_level` only 34.4 % non-null and dirty (max 975 600.0)**; `val` 12,852 rows, 2024, 100 % non-null, 40.16 … 88.52; `test` 21,930 rows, 2025-01-02 → 2026-09-21, 100 % non-null, 16.94 … 82.83. **Total 516,417 rows.** Also carries `dxy_logret_1`, `tlt_logret_1`, `spy_logret_1` | daily, one row **per symbol** (an equities world-model feature, not a standalone index) | ❌ raw lake, ❌ not governed, ❌ not registered | ⚠️ `timestamp[us, tz=America/New_York]` — a **third** timestamp convention |
| **DVOL** | `03_governed_lake/v2_parquet_lake/macro/dvol/BTCDVOL_1h_consolidated.parquet` | **26,665** bars, 2023-10-01 → 2026-10-16 | 1 h | ✅ governed, ❌ **not registered** — `manifest.json` `macro_indices` lists **only** VXN | ⚠️ `timestamp` is int64 **nanoseconds** while VXN's is int64 **milliseconds** — same column name, same directory, two units. See B.3 |
| **GVZ** (gold, GC row of the migration table) | — | **absent everywhere** | — | — | — |
| **DXY, GSPC, RVX, OVX, VVIX** | — | **absent** (`find` over the whole lake returns nothing) | — | — | — |
| **SPX / NDX** (index *levels*, not volatility) | `nautilus_databank/equities_indices/{SPX,NDX}/1d` + `catalog/data/bar/{SPX.CBOE,NDX.NASDAQ}-1-DAY-LAST-EXTERNAL` | 1,692 / 1,695 daily bars, 2020-01-02 → 2026-09-25 | daily | ✅ governed area (`nautilus_databank`) | n/a — a *direction* variable, not a volatility one |

`[FACT]` **Correction to D5.** D5 says *"VIX is NOT ingested."* That is true of the **governed
parquet lake** (`macro/` contains only `vxn/` and `dvol/`). It is **not** true of the lake as a
whole: a VIX daily series exists in the Nautilus catalog (503 bars, 2024-09-23 → 2026-09-22), and
a `vix_level` column exists inside the vendored Twelve Data world-model dataset. Neither is
governed, neither is registered in the manifest, and the latter is dirty before 2024. **D5 should
be amended**, not silently contradicted: VIX is *available*, not *ingested*.

### B.2 The crypto equivalents

| Series | Where | Coverage | Granularity | Governed? | Knowable at decision time? |
|---|---|---|---|---|---|
| **CMC20** | `crypto_indices/CMC20/cmc20_15m_signals.parquet` (plus `_1h/_2h/_4h/_30m/_1d`) | **97,594** rows, 2024-01-01 → 2026-10-13 15:00 UTC | 15 m | ✅ governed | ⚠️ `timestamp` is **`datetime64[us, UTC]`**, not int64 ms; and it is a **cross-sectional index level + breadth + EMA/MACD signals**, i.e. a *direction/breadth* factor, not a volatility regime |
| **Funding rate** | `crypto/funding_rate/{BTCUSDT,ETHUSDT}/*_funding_rate.parquet` | **4,200** prints each, 2023-01-01 → 2026-10-31 | 8 h | ✅ governed, int64 ms | ✅ `calc_time` **is** the publication time — `merge_asof` on it is safe |
| **`bar_ofi`** (the RL's order-book-imbalance state) | `crypto/high_frequency_lob/BTCUSDT/BTCUSDT_1m_3years_governed.parquet` — **local checkout only** (`/home/da/桌面/database/…`); **the NFS mount does not contain `crypto/high_frequency_lob/` at all** | 1,636,229 rows, 2023-01-01 → 2026-02-14; columns `bar_ofi`, `parkinson_vol`, `garman_klass_vol`, `atr14` | 1 m | ⚠️ governed **in the checkout**, absent from the canonical NFS lake | ⚠️ `datetime64[us]` only — no int64 timestamp column |

### B.3 Two concrete alignment hazards in the regime data

`[FACT]` **Hazard 1 — the VXN daily bar is stamped *before* the session it describes.**
`VXN_1d_consolidated.parquet` stamps every row at `datetime = 00:00:00 UTC` **of the CBOE trade
date** (row 0: `timestamp=1252886400000, datetime=2009-09-14 00:00:00`; last row:
`2026-11-20 00:00:00`). But CBOE's daily close for session *D* is published at ~16:15 ET on *D*
= ~20:15/21:15 UTC on *D*. So **00:00 UTC on D is ~20 hours before D's close exists.**
`[INFERENCE]` An `asof` join on the raw `timestamp` — the obvious implementation — hands a trade
at 09:30 ET on D the value of **D's own close**: a silent look-ahead. The discussion's
`shift(1)` on the *row index* protects against this only by accident of indexing, not by
construction. **The fix is structural, not index-based: re-stamp the daily bar at its true
publication time (16:15 America/New_York on the trade date) and then `merge_asof` backwards.**

`[FACT]` **Hazard 2 — three different timestamp units under the same column name.**
`macro/vxn/VXN_1d_consolidated.parquet.timestamp` is int64 **ms**;
`macro/dvol/BTCDVOL_1h_consolidated.parquet.timestamp` is int64 **ns**;
`crypto_indices/CMC20/cmc20_15m_signals.parquet.timestamp` is `datetime64[us, UTC]`;
the VIX catalog uses `ts_event` in ns; the Twelve Data bars use `timestamp[us, tz=America/New_York]`.
`[FACT]` The lake's own governance contract states the analytical lake is **int64 milliseconds**
(`AGENTS.md` "Lake governance, briefly"). **DVOL deviates from that contract inside the same
`macro/` directory as VXN.** `[INFERENCE]` A regime loader that assumes "int64 = ms" will read
DVOL as year 55 717 (measured: `pd.to_datetime(1696118400000000000, unit="ms")` → *OutOfBounds*;
`unit="ns"` → 2023-10-01, correct) and will silently join VXN and DVOL to different dates.

### B.4 The one correlation that has now been measured: VXN vs VIX

`[FACT]` Over the **391** trading days on which both series exist (2024-09-23 → 2026-09-22),
joining the governed VXN parquet to the VIX catalog bars on the New York trade date:

```
Pearson  corr(VXN, VIX) levels   = 0.7495
Spearman corr(VXN, VIX) ranks    = 0.7174
mean(VXN − VIX) = +4.27   median = +3.75   VXN > VIX on 97.2 % of days
corr(ΔVXN, ΔVIX)              = 0.0540
corr(VXN_t, ΔVIX_t)            = 0.1309
```

`[FACT]` The discussion's claim at L105 — *"比 VIX 更贴合 NQ，通常比 VIX 高 2–5 点"* — is
**confirmed** (median +3.75, mean +4.27, 97.2 % of days).

`[FACT]` **But the same absolute bins do not transfer.** Applying the doc's `[0, 18, 28, 200]`
thresholds to each index's *own* distribution over the same 391 days:

| Index | P(X < 18) | P(X < 28) | band agreement with the other index |
|---|---|---|---|
| VXN | **6.6 %** | 89.0 % | — |
| VIX | **59.6 %** | 96.9 % | **40.4 %** |

Crosstab (rows = VXN band, cols = VIX band): VXN-normal/VIX-low = **202 of 391 days**.

`[INFERENCE]` The migration table's "MES → VIX" row, if implemented with VXN's thresholds, would
classify **60 % of all MES days** as "low-vol range" and would put essentially **never** (3.1 %)
MES days into the high-vol band. This is exactly what `RULE_SPEC.md` A34 already says
(*"use the percentile mapping instead of absolute points"*) — and it is now quantified rather
than merely advised.

`[INFERENCE]` `corr(ΔVXN, ΔVIX) = 0.054` says something the level correlation hides: the two
indices agree about the *level* of equity-market fear but say almost nothing about its
*change*. A regime feature built on a change rate (the doc's dropped "1-hour change rate") would
therefore have been nearly orthogonal to VXN's own change — i.e. it would have been a **different
feature wearing VXN's name**.

### B.5 The regime variation that actually exists in the usable samples

`[FACT]` **VXN band occupancy (measured, governed series):**

| Window | low (0) | normal (1) | high (2) | trading days |
|---|---|---|---|---|
| Full VXN history 2009-09-14 → 2026-11-20 | 1,541 (35.6 %) | 2,099 (48.5 %) | 687 (15.9 %) | 4,327 |
| BTCUSDT 1 m sample 2023-01-01 → 2026-11-21 | 158 (16.2 %) | 738 (75.6 %) | 80 (8.2 %) | 976 |
| QQQ 15 m sample 2022-10-14 → 2026-10-14 | 158 (15.8 %) | 749 (74.7 %) | 96 (9.6 %) | 1,003 |
| VIX-catalog window 2024-09-23 → 2026-09-22 | 35 (7.0 %) | 413 (82.4 %) | 53 (10.6 %) | 501 |

`[FACT]` **The NQ 1-minute sample — the strategy's primary market — has ZERO regime variation.**
The lake's entire NQ 1-minute partition is 7,490 bars, 2026-09-24 → 2026-10-01. VXN closes on
those dates were **21.24, 20.87, 22.13, 22.07, 22.46, 22.51** — **every one of them in band 1
("normal trend")**. `[INFERENCE]` Any regime-conditioned NQ backtest run on the data that exists is
a **no-op**: the regime filter selects 100 % or 0 % of the sample depending on the threshold, and
can never be compared across bands. The phase-1 "regime" claim is therefore **untestable on the
target market with the data in the lake**, regardless of how the analysis is written.

### B.6 A prior, independent regime experiment that already exists in the lake

`[FACT]` `04_strategies/btc_15m_moneyflow_dvol/` implements a **DVOL-percentile regime gate**
(`dvol_cap_pct = 75`: "DVOL Overheating suppresses new position entries") on BTCUSDT 15 m, and
records its own iteration results:

```
24h Ch + 5d Trend + CVD (No DVOL),        CAGR -9.95, Sharpe -0.54, 760 trades
24h Ch + 5d Trend + CVD (DVOL < 75%),      CAGR -7.84, Sharpe -0.41, 686 trades
48h Ch +10d Trend + CVD (No DVOL),         CAGR -0.63, Sharpe  0.04, 432 trades
48h Ch +10d Trend + CVD (DVOL < 75%),       CAGR  0.55, Sharpe  0.12, 382 trades
```

`[INFERENCE]` A volatility-regime gate moved two of six variants from negative to ~zero and
changed Sharpe by ≤ 0.14, while cutting the trade count by 10–13 %. This is a **third-party
strategy in the same lake** and it is not ours, so it is not a result about the iFVG pattern — but
it is the closest thing to prior evidence available on "does a DVOL regime gate help?", and its
answer is "marginally, on a strategy that is losing money anyway".

---

## C. The correlation check that has **not** been done — and how to do it

This is the deliverable the user asked for. It is specified against the **frozen D2 candidate
log** so it can be implemented without waiting for the rest of the system.

### C.1 The hypothesis

`[PROPOSAL]` **H1 (primary).** *The expectancy of the iFVG rule engine is a function of the
market's volatility regime.* Formally, for a candidate setup *i* with realised multiple *R*ᵢ and
regime label *G*ᵢ ∈ {0,1,2}: `E[R | G] ≠ const`.

`[PROPOSAL]` **H0.** `E[R | G] = E[R]` for every regime variable *G* — the regime carries no
information about the setup's outcome.

`[INFERENCE]` Note what H1 does **not** say. It is *not* "VXN predicts the market", and it is
*not* "VXN is a good index for NQ" (that part is established, §B.4). It is the only form of the
claim that a trading system can act on: **does the *conditional* expectancy differ?** The
discussion's L106 claim ("NQ's intraday range and mean-reversion/breakout efficiency show
significant non-linearity across VXN bands") is a claim about the *market*, and it is the
proximate cause of the strategy claim; it must be re-derived on *our* signal before it can be
used to filter *our* signal.

### C.2 The test, specified

`[PROPOSAL]` **Unit of analysis.** One **candidate setup** (one row of the D2 candidate log),
not one trade and not one bar. The outcome variable is `r_multiple` (D2). The D2 log carries
every candidate, winners and losers, so the estimator is not survivorship-biased.

`[PROPOSAL]` **Grouping variable.** The regime band, 3 levels, computed from the **lagged** index
level. Two variants must be reported side by side, because they answer different questions:

- **absolute bands** (the doc's `[0,18,28,200]`, corrected per `RULE_SPEC.md` §1.9) — *what the
  doc actually claims*;
- **trailing-percentile tertiles** (the doc's own per-market generalisation, `RULE_SPEC.md` A34) —
  *whether the claim survives being made scale-free*.

`[PROPOSAL]` **Estimator.** A regression of `r_multiple` on regime dummies,
`r_i = α + β₁·1[G=1] + β₂·1[G=2] + ε_i`, with **cluster-robust (CR1) standard errors clustered on
the regime variable's own publication period** — for VXN, the **US trading session whose close was
used**; for hourly variables, the UTC day. Report `E[R | G]` per band with a 95 % CI, the
pairwise contrasts `β₁, β₂` with CR1 CIs, and the **break-even round-trip cost in R** per band
(D9 requires it alongside every expectancy).

`[PROPOSAL]` **The permutation test (this is the one that respects time ordering).** A parametric
t-test on overlapping, autocorrelated trades is not enough. Use a **moving-block permutation
test on the cluster labels**:

1. order the clusters by time;
2. cut the label sequence into contiguous blocks of **20 clusters** (≈ 1 trading month) — long
   enough to preserve the regime's own autocorrelation (volatility clusters last weeks);
3. randomly re-order the blocks (2,000 replications);
4. recompute the band contrast under each re-assignment;
5. report `p = (#{replicates with |stat| ≥ |observed|} + 1) / (2000 + 1)`.

This preserves: the trade→cluster mapping, the trade weights, the within-cluster correlation, and
the regime's serial structure. A naive shuffle of the labels would destroy the regime's
autocorrelation and make the test anti-conservative; a bootstrap over trades would destroy the
within-day correlation that D4 warns about.

`[PROPOSAL]` **Multiple-testing correction.** The family is **every regime variable tested on
the same sample**. Pre-register the family explicitly:

| # | Variable | Rationale |
|---|---|---|
| 1 | VXN, doc absolute bands `[0,18,28,200]` | the doc's primary claim |
| 2 | VXN, trailing-1y tertiles | the scale-free form of #1 (A34) |
| 3 | DVOL, trailing-1y tertiles | the doc's crypto regime index (L163) |
| 4 | realised-volatility (30 d) tertiles | **self-referential control** |
| 5 | funding-rate sign | crypto positioning/crowding |

`[PROPOSAL]` Apply **Holm–Bonferroni at family-wise α = 0.05** across these 5 omnibus tests
(equivalently, 5 comparisons per arm; if the arm grid is also searched, the family becomes
5 × |arms| and must be corrected jointly — see §D.3). Report **Benjamini–Hochberg FDR ≤ 0.10** as
the secondary, discovery-oriented criterion. **Variable 4 is not optional**: a regime effect that
a self-referential volatility measure cannot reproduce is not evidence for a *market* regime.

### C.3 The look-ahead traps, stated precisely

`[FACT]` **Trap 1 — the same-day VXN close.** CBOE's VXN official close for session *D* is the
16:15 ET value of session *D*. A trade taken at **09:30 ET on D** therefore happens **~6 h 45 min
before D's close is published**. Using D's close for that trade is a **look-ahead** — not a
borderline one; the value did not exist yet at the decision time. The **previous** trading day's
close (D−1, published ~16:15 ET on D−1) *is* known at 09:30 ET on D. `DATA_FEASIBILITY.md` §E5
reaches the same conclusion.

`[FACT]` **Trap 2 — `shift(1).bfill()`.** The discussion's snippet (L262) back-fills the head of
the series **from the future** (row 0 receives row 1's value) and silently carries a stale regime
across weekends and holidays with **no marker** (`DATA_FEASIBILITY.md` §E4; `AUDIT.md` §C.3).
`[PROPOSAL]` Use `shift(1)` **without** `bfill`, and add a `regime_stale_days` column so a
4-day-old regime is visibly 4 days old.

`[FACT]` **Trap 3 — the lake's VXN timestamp.** Because the parquet stamps 00:00 UTC of the CBOE
date (§B.3), a naive `merge_asof` on `timestamp` reproduces Trap 1 exactly. `[PROPOSAL]` Re-stamp
the daily bar at `16:15 America/New_York` on its trade date and make the lag *structural*.

`[FACT]` **Trap 4 — a daily index cannot produce the doc's "1-hour VXN change rate".** The feature
was dropped (`DATA_ACQUISITION.md` §6; `RULE_SPEC.md` A18). `[INFERENCE]` **Consequence for what
can be tested:** (a) the regime becomes a **pure level**, i.e. a *step function that is constant
within a session* — it can condition *across* sessions but has **zero within-session variance**,
so it can never condition an intraday decision *within* a session; (b) the effective sample size
of any regime hypothesis is bounded by the **number of sessions** (≈ 850–1,000 in the BTC sample),
not by the number of trades (15,928) — which is why the cluster in C.2 must be the session; (c)
the only "change" information left in the regime family is **overnight** (today's close vs
yesterday's), which is exactly the "gap risk" channel, and it must be reconstructed explicitly
rather than smuggled in as an hourly series.

`[FACT]` **Trap 5 — the regime's own publication timestamp vs the bar's decision timestamp.** The
decision timestamp is the **confirmation bar's close** (`ts_event` in D2), and the regime value
must be known at that instant, not at the session's end.

### C.4 What a first, exploratory run says (EXPLORATORY — not a result)

`[FACT]` **Method.** The D2 candidate log does not exist yet, so the exploratory run regenerated
it from the existing E-1 machinery, unchanged:
`research/experiments/e1_rule_falsification.py` was imported as a module and re-run on
**BTCUSDT 1-minute**, 2,046,240 governed bars (2023-01-01 → 2026-11-21), in four pre-registered
arms. **The reproduction is exact**: the baseline arm returned **n = 15,928, E[R] = −0.0197**
against E-1's published **n = 15,928, E[R] = −0.020** (`E1_RESULTS.md` §3.0), and the
`doc[7,15]` arm returned **n = 13,204, E[R] = −0.0173** against **13,204 / −0.017**. The trade
lists are therefore the same trades E-1 measured. Regime variables were joined with
`merge_asof(direction="backward")` on each variable's **known-at** time (VXN: 16:15 ET on the CBOE
date; DVOL: the end of the hourly bar; RV30: the end of the UTC day) — no forward fill, no
back-fill.

`[FACT]` **Regime-availability at trade time** (all four arms pooled, 64,396 trades):
VXN **100.0 %**, funding **100.0 %**, RV30 **98.6 %**, DVOL **86.5 %** (DVOL starts 2023-10-01).

`[FACT]` **Baseline arm `code[0,15] | none | open | off`** (n = 15,928 one-position-at-a-time
trades, 851 sessions with trades, E[R] = −0.0197):

| Variable | band 0 | band 1 | band 2 | band spread | moving-block permutation **p** |
|---|---|---|---|---|---|
| **VXN, doc absolute bands** | n 2 895 / 145 sess, win 30.64 %, **E[R] −0.0808** | n 11 772 / 643 sess, win 33.05 %, E[R] −0.0084 | n 1 261 / 63 sess, win 33.86 %, E[R] +0.0159 | **+0.0967 R** | **0.0385** |
| VXN, trailing-1y tertiles | n 6 059, E[R] −0.0271 | n 4 320, E[R] −0.0132 | n 5 549, E[R] −0.0166 | +0.0142 R | 0.8496 |
| DVOL, trailing-1y tertiles | n 5 923, E[R] −0.0209 | n 3 946, E[R] −0.0193 | n 6 059, E[R] −0.0186 | +0.0070 R | 0.9670 |
| **RV30 tertiles (control)** | n 6 236, E[R] −0.0109 | n 3 762, E[R] −0.0486 | n 5 930, E[R] −0.0105 | +0.0382 R | 0.3288 |

`[FACT]` **Cluster-robust (CR1, session-clustered) contrasts, same arm:**

| Variable | band 1 − band 0 | 95 % CI | band 2 − band 0 | 95 % CI |
|---|---|---|---|---|
| VXN, doc bands | **+0.0724 R** (t = 2.51) | [+0.0159, +0.1289] | **+0.0967 R** (t = 2.13) | [+0.0078, +0.1856] |
| VXN, tertiles | +0.0139 (t = 0.50) | [−0.0404, +0.0681] | +0.0105 (t = 0.39) | [−0.0418, +0.0628] |
| DVOL, tertiles | +0.0017 (t = 0.06) | [−0.0505, +0.0539] | +0.0023 (t = 0.09) | [−0.0450, +0.0495] |
| RV30 tertiles (control) | −0.0377 (t = −1.33) | [−0.0933, +0.0178] | +0.0004 (t = 0.02) | [−0.0487, +0.0495] |

`[FACT]` **Holm–Bonferroni over the 4 variables, per arm** (16 comparisons in total):

```
arm code[0,15]|none|open|off        VXN_band(doc)  p=0.0385  Holm=0.1539  keep
arm code[0,15]|none|open|off        RV30_tertile   p=0.3288  Holm=0.9865  keep
arm code[0,15]|none|open|off        VXN_tertile    p=0.8496  Holm=1.0000  keep
arm code[0,15]|none|open|off        DVOL_tertile   p=0.9670  Holm=1.0000  keep
arm code[0,15]|0.25atr|open|off     RV30_tertile   p=0.0125  Holm=0.0500  REJECT  <-- the CONTROL
arm code[0,15]|0.25atr|open|off     DVOL_tertile   p=0.0385  Holm=0.1154  keep
arm code[0,15]|0.25atr|open|off     VXN_tertile    p=0.1429  Holm=0.2859  keep
arm code[0,15]|0.25atr|open|off     VXN_band(doc)  p=0.2914  Holm=0.2914  keep
arm code[0,15]|none|confirm|off     VXN_band(doc)  p=0.0260  Holm=0.1039  keep
arm code[0,15]|none|confirm|off     RV30_tertile   p=0.3008  Holm=0.9025  keep
arm code[0,15]|none|confirm|off     VXN_tertile    p=0.9415  Holm=1.0000  keep
arm code[0,15]|none|confirm|off     DVOL_tertile   p=0.9760  Holm=1.0000  keep
arm doc[7,15]|none|open|off         RV30_tertile   p=0.0340  Holm=0.1359  keep
arm doc[7,15]|none|open|off         DVOL_tertile   p=0.3998  Holm=1.0000  keep
arm doc[7,15]|none|open|off         VXN_tertile    p=0.4998  Holm=1.0000  keep
arm doc[7,15]|none|open|off         VXN_band(doc)  p=0.8541  Holm=1.0000  keep
```

`[FACT]` **What this establishes (exploratory only):**
1. The **only** Holm-rejected result in the whole family is the **self-referential realised-volatility
   control** — not VXN.
2. The doc's **absolute VXN bands** produce the largest raw effect (spread 0.0967 R) but the
   **scale-free tertiles of the same index produce essentially nothing** (spread 0.0142 R,
   p = 0.85). `[INFERENCE]` The effect is therefore a property of the **18/28 thresholds**, not of
   VXN.
3. The effect **collapses from p = 0.0385 to p = 0.8541** when the inversion window changes from
   the code's `[0,15]` to the doc's `[7,15]` — the same "sign/strength flips across a defensible
   re-parameterisation" pattern D4 documents for the unconditional edge.
4. `corr(trades-per-session, mean R per session) = −0.15` (baseline arm; −0.16 … −0.19 in the
   others). `[INFERENCE]` **Signal density is negatively related to signal quality** — days with
   more iFVG candidates have worse per-candidate outcomes. This has a direct consequence for the
   design of the test (§D.2) and for any per-day equity curve: a regime band that happens to
   contain more candidates will look worse on a trade-weighted estimator and better on an
   equal-weight-per-session estimator. **The unit of analysis must be declared before the test
   is run, not chosen after seeing the result.**

`[INFERENCE]` **What this does NOT establish:** it does not establish that the regime is
irrelevant. It establishes that (a) the specific claim the discussion makes has **not** been
shown to survive a scale-free re-specification, a parameter change, or a multiple-testing
correction; and (b) the sample is too small to *rule the effect out* (§C.5). It is a
**demotion of the regime from "proven gate" to "unproven hypothesis"**, not a refutation.

### C.5 Power — what effect size is actually detectable

`[FACT]` Baseline arm: n = 15,928 trades, win rate 32.68 %, E[R] = −0.0197, **sd(R) = 1.4071 R**
(derived from the two-point outcome distribution: `Var = p(2−μ)² + (1−p)(−1−μ)²`).
Sessions with trades: **851**; trades per session: mean 18.7, median 17, min 1, max 72;
**within-session variance 1.9798, between-session variance 0.0089, ICC = 0.0045**, design effect
**1.08**, effective n **14,761**. `[INFERENCE]` The one-position-at-a-time constraint already
removes nearly all of the within-session dependence — the D4 trap does not recur here.

`[FACT]` **Minimum detectable difference in E[R]** (two-sided α = 0.05, 80 % power,
`MDD = (1.960 + 0.842)·σ·√(1/n₁ + 1/n₂)`):

| Contrast | iid MDD | session-clustered MDD |
|---|---|---|
| two groups of 5,309 (three equal bands) | **0.0765 R** | 0.0795 R |
| band 0 (n 2 895) vs band 1 (n 11 772) — the observed sizes | **0.0818 R** | 0.0850 R |
| one band of 5,309 vs zero | **0.0541 R** | 0.0562 R |
| all 15,928 vs zero | 0.0312 R | 0.0324 R |

`[FACT]` **Context that makes those numbers bite:** E-1 measured the expectancy of **all 32 arms**
in the range **[−0.024 R, +0.014 R]** (`E1_RESULTS.md` §3.0) — a **total envelope of 0.038 R**.
`[INFERENCE]` **The MDD for a band contrast (0.077–0.085 R) is ≈ 2× the entire
arm-to-arm expectancy envelope of the strategy.** A regime effect worth acting on would have to be
*twice as large as every defensible change of window, ATR floor, fill rule and sweep gate
combined*. That is the single most important number in this section: **the regime hypothesis is
not merely unproven — it is not economically distinguishable from parameter noise at this sample
size.**

`[FACT]` **QQQ 15-minute (the only long US-equity intraday sample in the lake):** 73,325 bars,
2022-10-14 → 2026-10-14, 1,003 VXN trading days (bands 158 / 749 / 96). The same E-1 engine on
it produces: baseline arm **n = 970 trades over 219 sessions, E[R] = −0.0289**, sd(R) = 1.4037,
band 0 (VXN < 18) **n = 189, E[R] = −0.1746** [−0.3661, +0.0169]; band 1 (18–28) **n = 674,
E[R] = +0.0282** [−0.0794, +0.1358]; band 2 (> 28) **n = 107, E[R] = −0.1308** [−0.3899, +0.1282];
band spread +0.2028 R, **moving-block permutation p = 0.2654**. With the ATR floor: spread
+0.0151 R, p = 0.9950. With `doc[7,15]`: spread +0.1063 R, p = 0.4513.
`[FACT]` **QQQ MDD:** band 0 vs band 1 → **0.324 R**; one band vs zero → 0.152 R.
`[INFERENCE]` The only *equity* sample available can only detect a band difference of
**0.32 R — 8× the entire unconditional expectancy envelope.** It cannot answer the question.

### C.6 The exact code-level interface the regime layer must expose

`[PROPOSAL]` One module, one pure function, no engine calls (the `AGENTS.md` "rule engine is a
pure function of the bar history" idiom), so it is unit-testable without a backtest:

```
dodgys_dd_quant/strategy/regime.py
─────────────────────────────────
REGIME_LOW, REGIME_NORMAL, REGIME_HIGH = 0, 1, 2
VXN_ABS_BINS   = (18.0, 28.0)      # doc bands; RULE_SPEC §1.9 corrected semantics
REGIME_INDEX: dict[str, str] = {   # migration table, L158–L163
    "NQ": "VXN", "MNQ": "VXN", "QQQ": "VXN",
    "MES": "VIX", "GC": "GVZ", "BTCUSDT": "DVOL", "ETHUSDT": "DVOL",
}

@dataclass(frozen=True)
class RegimeState:
    known_at_ns: int      # when this value became knowable (publication time)
    level: float          # the lagged index level
    regime: int           # 0 / 1 / 2
    percentile: float     # trailing-window percentile of `level` (scale-free)
    stale_days: int       # how many days old `level` is (0 = fresh)
    index_name: str       # "VXN" | "VIX" | "DVOL" | "GVZ"

def regime_state(index_name: str, asof_ns: int, series: RegimeSeries) -> RegimeState | None
    """Return the regime KNOWABLE at `asof_ns`, or None if the series has not
       started.  MUST NOT return a value whose publication time is > asof_ns."""
```

`[PROPOSAL]` **The two D2 columns it fills** (the log is frozen in D2 — the regime module writes
these two and nothing else):

| D2 column | Type | Meaning | Contract |
|---|---|---|---|
| `vxn_known` | f64 | the **lagged** index level (previous close for a daily index) | `NaN` if no regime series covers the timestamp; never a forward-filled value without a `stale_days` marker |
| `vxn_regime` | int8 | 0 low / 1 normal / 2 high | derived **only** from `vxn_known`; `−1` if `vxn_known` is NaN |

`[INFERENCE]` Because the D2 schema names the columns `vxn_*`, but the migration table assigns a
*different index per market* (VIX for MES, DVOL for BTC/ETH), the columns must be read as
*"the market's own regime index"*, with `index_name` recorded as a side-car
(`research/candidates/{symbol}_{timeframe}.meta.json`) — **not** by adding columns to the frozen
log. `[PROPOSAL]` If the captain prefers literal names, the honest alternative is to keep
`vxn_known`/`vxn_regime` as the *VXN* columns and add a **separate** regime-log side-car file
`research/candidates/{symbol}_{timeframe}.regime.parquet` keyed by `ts_event`, so the D2 schema is
not edited. This needs a decision from the captain.

`[PROPOSAL]` **Mandatory invariants (each is a unit test):**
1. **Look-ahead test (the direct one):** perturb the *current* period's index value and assert
   that **no** regime label at any timestamp changes (`DATA_FEASIBILITY.md` §E5 check 1).
2. `known_at_ns <= asof_ns` for every emitted state, asserted on every row.
3. The regime label is **constant within a session** for a daily index.
4. No back-fill: the first observation is dropped, not filled.
5. Every forward-filled carry is counted and logged; assert `stale_days <= 4`.
6. The unit of every regime series is **asserted** at load time (ms vs ns vs µs — §B.3 hazard 2),
   not assumed.

### C.7 The minimum experiment that would settle it

`[PROPOSAL]` **M-E1 — the one experiment, on data that already exists.** *Does the iFVG rule
engine's expectancy depend on the volatility regime, on an equity instrument, with a
pre-registered test and an honest power calculation?*

- **Data:** QQQ 15-minute (the lake's only long US-equity intraday sample, 73,325 bars,
  2022-10-14 → 2026-10-14) joined to the governed VXN daily series, lagged.
- **Engine:** the existing `research/experiments/e1_rule_falsification.py`, unmodified, in the
  pre-registered arms; **one position at a time** (D4).
- **Pre-registration:** the 5-variable family of §C.2, both band specifications, Holm correction,
  moving-block permutation on session clusters, CR1 cluster-robust contrasts, break-even cost in R
  per band (D9), and the realised-volatility control.
- **Decision rule:** a regime effect is accepted only if (i) it survives Holm across the family,
  (ii) it survives **all** pre-registered arms without a sign flip, (iii) it survives the
  scale-free re-specification, **and** (iv) its per-band expectancy **exceeds the round-trip
  break-even cost** in R.
- **Duration:** **≈ 2 hours of compute** (the QQQ run above took ≈ 90 s including the 2,000
  permutations) and **≈ 1 day of analyst time**. `[FACT]` It has already been run once, in
  exploratory form, in §C.4/§C.5 — **the answer was p = 0.265 on the equity sample and no
  surviving effect after Holm on the crypto sample.**

`[PROPOSAL]` **M-E2 — the decisive version, blocked on data.** The same test on **NQ 1-minute**,
which is the actual target market and the only market where the doc's VXN bands were designed.
`[FACT]` **Blocked:** the lake has **7,490 NQ 1-minute bars (one week)**, entirely inside VXN
band 1 (§B.5) — zero regime variation. This requires a multi-year NQ 1-minute feed (Databento,
~$10–30; `DATA_ACQUISITION.md` §8.1), and **even then** the test needs **≥ 3 years** to reach a
usable number of high-vol sessions (the high band is only 8–16 % of days). `[INFERENCE]`
**Expected duration: ≈ 4–8 weeks** (purchase + ingest + governance + run), and it is the *only*
experiment that can actually settle the doc's claim on its own market.

---

## D. Is a regime-conditioned strategy even the right hypothesis here?

### D.1 If the unconditional edge is zero, is a conditional edge plausible?

`[FACT]` D4 / `E1_RESULTS.md` §3.0: across **32 arms** on 2,046,240 BTCUSDT 1-minute bars, with
one position at a time, E[R] spans **[−0.024, +0.014]**, **every 95 % CI includes zero**, PF never
exceeds **1.051** against the doc's **> 1.25** gate, and **the sign flips across the fill arm in
every parameter group**. With a 0.05 R round trip, **every** arm is net-negative.

`[INFERENCE]` A regime-conditioned edge is **not logically impossible** — but it imposes a much
stronger requirement than an unconditional one. For a conditional edge to exist, the *band means*
must differ by more than the *unconditional noise*, which means:

1. the rule engine's edge must be **non-zero but masked** by averaging over regimes — i.e. some
   regime must carry a positive expectancy large enough to overcome the aggregate;
2. the regimes must be **both observable in advance and not already priced into the rule
   parameters** — VXN's level is observable, but the rule's own ATR-based gap floor and
   window-based stop already adapt to volatility, so part of any "regime effect" may be
   **already captured**;
3. the conditional effect must be **large enough to matter economically** — i.e. the per-band
   expectancy must exceed the round-trip cost in R. `E1_RESULTS.md` §3.3 already shows the
   *gross* edge is ≤ 0.052 R while the round trip is 0.073–0.245 R for NQ — so **the whole
   business is currently cost-negative**, and a regime filter must first *create* a gross edge
   of > 0.05–0.10 R, not merely redistribute one.

`[INFERENCE]` **The honest prior:** a strategy whose unconditional expectancy is indistinguishable
from zero across 32 defensible parameterisations is, by Occam, a strategy with **no edge to
condition**. Conditioning on a variable can *reveal* a hidden edge (that is the legitimate hope),
but it can also manufacture a false one, and §C.4 shows what the false version looks like: a
threshold-specific effect that dies under re-specification, disappears under a parameter change,
and is beaten by a self-referential control. **The regime hypothesis should be treated as a
falsifiable candidate with a pre-registered test (M-E1/M-E2), not as a design premise.**

### D.2 The cost of regime conditioning

`[INFERENCE]` **Fewer trades per fold.** Splitting the sample by regime band splits the trades:
in the BTC sample the bands are 2,895 / 11,772 / 1,261 trades and 145 / 643 / **63 sessions**.
The **high-vol band** — the one the doc's most aggressive policy (halve risk, raise the ATR gap
floor) is aimed at — rests on **63 sessions**. Its minimum detectable difference against the
normal band is **0.117 R** (vs 0.082 R for low-vs-normal), and its CR1 cluster-robust standard
error is **0.0453 R** (vs 0.0288 R for low-vs-normal): the policy that is supposed to matter most
is the one that can be measured least, and it is the one whose *own* CI is widest
([+0.0078, +0.1856] for the high band).

`[INFERENCE]` **Wider CIs — and the cost is already quantified.** §C.5: MDD 0.077–0.085 R for a
band contrast vs a total unconditional expectancy envelope of 0.038 R. On the QQQ sample the MDD
is **0.32 R**. Conditioning does not merely widen the CI — it makes the CI wider than the entire
effect the strategy is trying to detect.

`[INFERENCE]` **The unit-of-analysis trap.** §C.4 found `corr(trades-per-session, mean R per
session) = −0.15`: days with more candidates have worse candidates. A trade-weighted estimator
and an equal-weight-per-session estimator therefore give **different signs** on the same data
(baseline arm: trade-weighted band 1 = −0.008 R; session-weighted band 1 = **+0.041 R**). Any
regime result must declare its estimator in advance, because the choice can flip the sign.

`[INFERENCE]` **The overfitting arithmetic.** The current grid is
2 windows × 2 ATR floors × 2 fills × 2 sweep gates × 2 concurrencies = **32 arms**. Adding the
regime:
- regime **on/off** as a filter → ×2 = 64;
- regime × **3 bands** as separate populations → ×3 = 192;
- regime × **absolute vs percentile** band specs → ×2 = 384;
- regime × **per-band parameter overrides** (the doc's actual policy: A+ only / RR 1:1.5–1:2 /
  RR 1:2.5–1:3 / halved risk / raised ATR floor — **five** independent knobs) → ×(2^5) = 12 288.

`[FACT]` **And the current 32 arms already fail:** every one-at-a-time arm's CI includes zero, and
the sign flips across the fill arm in every parameter group. `[INFERENCE]` **Multiplying a grid
whose every member is indistinguishable from zero by a 32–384× regime factor produces 1,024–12,288
numbers that are all indistinguishable from zero — with 384× more opportunities for one of them to
look significant by chance.** At α = 0.05, a 384-arm search returns a "significant" arm with
probability ≈ 1 − 0.95^384 ≈ **100 %**. This is the classic multiple-comparisons trap, and it is
the reason §C.2's pre-registered family and Holm correction are not optional.

### D.3 The minimum experiment and its duration

Restated: **M-E1** (§C.7) — QQQ 15 m + lagged VXN, pre-registered, **≈ 2 h compute / 1 day
analyst** — plus **M-E2** (§C.7) — NQ 1 m, **≈ 4–8 weeks**, blocked on a paid 1-minute feed.
`[FACT]` M-E1 has already been executed in exploratory form and the answer was **p = 0.265**
(QQQ) and **nothing surviving Holm** (BTCUSDT).

---

## E. Where the regime variable must enter — and where it must not

### E.1 The three places the discussion puts it

| # | Place | Implemented? | Correct entry point | Concrete gate/parameter | Leakage risk if wired wrongly |
|---|---|---|---|---|---|
| 1 | **Rule-engine filter** — L107 "low-vol → A+ only with SMT, RR 1:1.5–1:2" | **No** | **Not the rule engine.** The rule engine must stay a *pure function of the bar history* (`AGENTS.md`). The regime belongs in the **strategy layer** (`dodgys_strategy.py`), as a **post-rule, pre-order** filter that can only *reject* or *resize* a candidate the rule engine already produced — never alter its decision (the four-layer contract in `AGENTS.md`: *"Each layer may only filter or manage, never silently alter the rule layer's decisions"*) | L107: low → "A+ only **with** SMT" + RR 1:1.5–1:2. **This gate is unimplementable today** — "A+" has no definition (D8: implement the five checklist booleans as `checklist_score`, **report** the distribution, **do not filter**). L108: normal → RR 1:2.5–1:3 (also unimplementable: the engine fixes RR = 2.0, and changing it per band multiplies the grid). L109: high → halve risk (1 % → 0.5 %, `RULE_SPEC.md` A30) + raise the ATR gap floor 0.25 → 0.35 (`RULE_SPEC.md` A19) | **The regime must be resolved at the moment of the candidate's confirmation-bar close**, from the *previous* session's close (§C.3 Trap 1). Using the same day's VXN close for a 09:30 ET trade is a **hard look-ahead**: the value did not exist at the decision time. A second, subtler leak: applying the regime as a *filter on the population* (not as a *label on the log*) makes the traded population regime-dependent, so the "phase-1 population" is no longer comparable across arms — D8 requires the population to be **stated explicitly in every backtest report**. |
| 2 | **ML feature set** — L146 "VXN 绝对值及 1 小时变化率" | **No** (no ML pipeline exists) | The **feature builder** (`ml_pipeline/meta_labeling_train.py`), reading `vxn_known` / `vxn_regime` from the D2 candidate log (not from a separate join), so that the feature and the log column can never disagree | **Feature set = `vxn_known` (level) + `vxn_regime` (band).** The **1-hour change rate is dropped** (A18; unsatisfiable from a daily series). Optionally add the **overnight change** `vxn_known_t − vxn_known_{t−1}`, which is the only "change" the daily series supports and is knowable at the open (§C.3 Trap 4) | Leakage through the usual ML channels: (i) computing the feature on the **full** series before the walk-forward split — the feature must be computed from *lagged* values only, which it is if it comes from `vxn_known`; (ii) **train/serve skew** — the model must see the *same* `vxn_known` semantics at inference time as in training (`RULE_SPEC.md` A23/A31); (iii) the "1-hour change rate" would have to be **fabricated** from a daily series, and A18's instruction is explicit: *"Do not fabricate."* |
| 3 | **RL state** — L151 "VXN 波动率状态" | **No** (no RL exists) | The **observation vector** of the RL environment, fed from the same regime provider. Per `AGENTS.md` and D-rules, the RL **may never open a position** — it manages an open one | The RL state should carry the **regime band** (0/1/2) and the **regime's distance from its band boundary** (a continuous, more informative encoding than a 3-way label), both as *known-at-decision-time* values. The RL's **action space** should carry the regime-conditioned risk multiplier that L109 describes (halve risk in high vol) and the break-even trigger | The RL acts **inside** a trade, i.e. at times *after* the entry. Using the regime's **current** value during the trade is legitimate **only if** the regime can be observed at that instant — for a daily index it cannot (it is a daily step function), so the RL's regime input is effectively **constant for the life of the trade**, which is fine but must be stated. The dangerous version is an RL that re-reads a *forward-filled* regime and thereby learns a policy conditioned on a value that will only be known later. Also: **the RL must not be given the ability to emit an "open" action** (`AGENTS.md` "Leakage checks are part of QA … assert RL never emits an open action"). |

### E.2 Where the regime must **NOT** enter

`[PROPOSAL]` **Do not put the regime in the rule engine** (`state_machine.py`). The rule engine
must remain a pure function of the bar history; a regime-dependent rule engine destroys the
ability to state "the phase-1 population" and multiplies the grid before any data exists.

`[PROPOSAL]` **Do not use the regime to *define* the traded population in phase 1.** `AUDIT.md`
§C.3 already recommends this: *"Apply the regime as a **reporting stratifier**, not a gate, in
phase 1 — because its doc-stated policy depends on the undefined grade."* The regime's first job
is to **stratify the report** (`E[R | band]`, break-even cost per band, MDD per band), so that
the phase-1 gate can be decided from data rather than from an assertion.

`[PROPOSAL]` **Do not use an absolute band on a non-VXN index.** §B.4: the doc's thresholds put
60 % of VIX days into "low-vol range". If MES is ever built, its regime must be the **trailing
percentile** (A34).

`[PROPOSAL]` **Do not fabricate an intraday VXN.** A daily index cannot produce the doc's
1-hour change rate (A18). If an intraday VXN is ever obtained, the change must be
`close[t−1h]`, never `close[t]` (`DATA_FEASIBILITY.md` §E5 check 4).

### E.3 One more leakage trap specific to the doc's own numbers

`[FACT]` The doc's "1-hour VXN change rate" is not merely hard to source — it is **definitionally
ambiguous**: an index has no intraday print in the CBOE free file, and the 15-minute data the
lake *does* have for the target market spans **exactly one VXN band** (§B.5). `[INFERENCE]` Any
implementation that "gets" an hourly VXN change for NQ would have had to **synthesise** it
(e.g. from VXN futures or from a VIX proxy), and a synthesised regime would carry the
synthesis's own assumptions into every decision that depends on it. The honest position is the
one already taken: **drop the feature**.

---

## F. Verdict

```
CORRELATION CHECK IMPLEMENTED:  no
REGIME IN STRATEGY:             no
REGIME IN ORDER DECISION:       no
REGIME IN ML FEATURES:          no
REGIME IN RL STATE:             no
```

**With these qualifications, which do not change the yes/no answers but change what to do next:**

- `[FACT]` A **partial** correlation check now exists in this audit: corr(VXN, VIX) = 0.7495 over
  391 daily observations; the doc's "VXN is 2–5 points above VIX" claim is **confirmed**; and
  the doc's **absolute bands are shown not to transfer** to VIX (60 % of VIX days would be "low
  vol"). This is a correlation *between indices*, not the correlation *between the regime and the
  signal* that the user asked about.
- `[FACT]` An **exploratory** conditional-expectancy test was run on BTCUSDT 1 m (15,928
  one-position-at-a-time trades, 4 arms, 4 regime variables, session-clustered CR1 + moving-block
  permutation + Holm). Result: the doc's absolute VXN bands reach p = 0.039 in one arm and
  p = 0.85 in another; the scale-free version of the same index gives p = 0.85 everywhere; the
  **realised-volatility control** is the only variable that survives Holm; **nothing survives**
  across all 16 comparisons.
- `[FACT]` **D5 should be amended**: VIX *is* present in the lake (503 daily bars in the Nautilus
  catalog; a `vix_level` column in the vendored Twelve Data dataset) — but **not** in the governed
  parquet lake, **not** in the manifest, and dirty before 2024.
- `[FACT]` The **highest-value, zero-cost** deliverable in this leaf's scope is the **regime
  stratifier in the phase-1 report** — it costs one column pair in the D2 log and one
  `groupby`, and it converts an un-cited assertion into a measured, pre-registered number.

---

## Appendix A — Exploratory analysis: method, reproduction, and limits

**What was run (read-only; scripts lived in `/tmp` and are not part of the repo).**

1. **Trade regeneration.** `research/experiments/e1_rule_falsification.py` was imported as a
   module (no edits) and re-executed on the governed
   `crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet` (2,046,240 bars) for four
   pre-registered arms, `max_concurrent=1` (one position at a time, per D4).
   **Reproduction check:** baseline arm n = 15,928, E[R] = −0.0197 vs E-1's published
   n = 15,928, E[R] = −0.020; `doc[7,15]` arm n = 13,204, E[R] = −0.0173 vs published
   13,204 / −0.017. **Exact.**
2. **Regime joins.** `merge_asof(direction="backward")` on each variable's *known-at* time:
   VXN → 16:15 America/New_York on the CBOE trade date; DVOL → the end of the hourly bar
   (`timestamp + 1h`, with `timestamp` in ns); RV30 → the end of the UTC day. **No forward fill,
   no back-fill.**
3. **Bands.** VXN: doc absolute bands with the `RULE_SPEC.md` §1.9 semantics
   (`<18 → 0`, `18–28 → 1`, `>28 → 2`). VXN / DVOL / RV30 tertiles: trailing-365-day quantiles
   (1/3, 2/3) computed on the **daily** series with `.shift(1)` so the thresholds use only
   strictly prior days, then joined backwards.
4. **Estimators.** (a) trade-weighted band means with iid CIs; (b) **CR1 cluster-robust** OLS of
   `r` on band dummies, clustered on the **US trading session** for VXN and the **UTC day** for
   DVOL/RV30; (c) equal-weight-per-cluster means; (d) **moving-block permutation** (20 clusters
   per block, 2,000 replications, blocks randomly re-ordered along the time axis, labels
   reassigned to clusters, trade weights preserved); (e) Holm–Bonferroni over the 4-variable
   family per arm.
5. **QQQ 15 m run.** The same engine and the same joins on
   `us_equities/QQQ/15m/QQQ_15m_consolidated.parquet` (73,325 bars, 2022-10-14 → 2026-10-14).
6. **VXN/VIX correlation.** Governed VXN parquet joined to the VIX catalog bars on the New York
   trade date; Pearson, Spearman (rank) and first-difference correlations; band-agreement
   crosstab; the percentile position of the 18/28 thresholds inside each index's own
   distribution.

**Limits of the exploratory work — stated explicitly.**

- It uses **BTCUSDT** (the only market with a long 1-minute sample) and **QQQ 15 m** (the only
  long US-equity intraday sample). **It says nothing about NQ**, the doc's primary market,
  because that data does not exist beyond one week in one regime band.
- The rule engine is the **code-derived** one (FVG geometry, inversion trigger, expiry, stop,
  fixed 1:2 RR), **not** the doc's rules: no ATR floor in the baseline arm, no sweep gate, no
  SMT, no checklist, no grade, no vision. The regime question is therefore asked of the
  *code-derived* rule, which is the only rule that exists.
- **No costs** are applied to the band means (the 0.05 R round trip of D9 must be subtracted
  before any band can be called profitable; at 0.05 R **every** band mean measured here is net
  negative).
- The exploratory run **searched 16 combinations** (4 variables × 4 arms) on one dataset. That
  is a *discovery* exercise, and it is exactly why the report's p-values are reported with their
  Holm correction and with the scale-free and control variables shown side by side. It is
  **not** a hypothesis test and must not be quoted as one.
- The regime variables were joined to trades that were **generated by the same engine** that
  produced the D4 baseline. There is no train/test separation here; the point of the exercise is
  to measure the *magnitude* of any regime dependence, not to validate a trading rule.

**Artefacts read (not modified):** `.herd-swarm/decisions.md` (D1–D11);
`iFVG几个模型的讨论.txt` (L76, L93, L95, L103–L109, L146, L151, L158–L163, L172, L177–L183,
L207, L259–L269, L280); `diagram-四层正 EV 量化系统完整架构.svg`; `diagram-目录结构规划.svg`;
`AGENTS.md`; `research/docs/RULE_SPEC.md` (§1.9, T07–T13, T26, T28, T46–T50, A09, A18, A19,
A30, A34, B4, B8, I04, I05, INV6, §2.4, Appendix B, migration table);
`research/audit/AUDIT.md` (§A.2.2, T07–T10, T49/T50, B4, B5, B8, §C.1, §C.3);
`research/analysis/DATA_ACQUISITION.md` (§1–§8); `research/analysis/DATA_FEASIBILITY.md`
(A8, §E4, §E5); `research/analysis/ML_REUSE.md` (§A.7 table, A.23/A.31);
`research/analysis/PINE_RULES.md`; `research/experiments/E1_RESULTS.md` (§3.0–§3.3);
`research/experiments/E1_RAW_OUTPUT_btcusdt1m_full.txt`;
`research/experiments/e1_rule_falsification.py` (whole file, 431 lines);
`research/huggingface/xauusd-ml-trader/xauusd_trader/strategies/sentiment_strategy.py`;
`research/huggingface/xauusd-ml-trader/xauusd_trader/ml/ensemble_model.py`;
`research/jobs/leaf-L3-regime.md`.

**Lake paths read (canonical NFS mount, read-only):**
`03_governed_lake/v2_parquet_lake/macro/vxn/VXN_1d_consolidated.parquet`;
`03_governed_lake/v2_parquet_lake/macro/dvol/BTCDVOL_1h_consolidated.parquet`;
`03_governed_lake/v2_parquet_lake/crypto_indices/CMC20/cmc20_15m_signals.parquet`;
`03_governed_lake/v2_parquet_lake/crypto/funding_rate/{BTCUSDT,ETHUSDT}/*.parquet`;
`03_governed_lake/v2_parquet_lake/crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet`;
`03_governed_lake/v2_parquet_lake/us_equities/QQQ/15m/QQQ_15m_consolidated.parquet`;
`03_governed_lake/v2_parquet_lake/manifest/manifest.json`;
`03_governed_lake/nautilus_databank/MANIFEST.md`;
`03_governed_lake/nautilus_databank/equities_indices/{SPX,NDX}/1d`;
`02_pipeline_engine/nautilus_crypto_pipeline/catalog/data/bar/VIX-INDEX.CBOE-1-DAY-LAST-EXTERNAL/`;
`01_raw_lake/huggingface/twelvedata_financial-world-model/bars_1day/{train,val,test}.parquet`;
`01_raw_lake/cboe/VXN_History.csv`; `04_strategies/btc_15m_moneyflow_dvol/`;
and, for the `bar_ofi` columns only, the **local working checkout**
`/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/high_frequency_lob/BTCUSDT/`
(not present on the NFS mount).

**Written by this leaf:** `research/audit/L3_REGIME.md` only.
