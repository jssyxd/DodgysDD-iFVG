# Repository Guidelines

## Project Overview

Design + (planned) implementation of a **positive-EV quantitative trading system** for DodgysDD's
*Inversion Fair Value Gap* (iFVG) strategy, built on **NautilusTrader** as both backtest and live engine.

The strategy reacts (not predicts): after price sweeps liquidity and fails to hold an FVG, the FVG
inverts into a resistance/support zone; entry is on the failed retest, stop beyond the recent swing,
target the next liquidity pool. The repo today is **specification-only** — four documents, zero code.
Everything below marked *planned* describes the intended build; treat the documents as the source of truth.

Current repo contents:

| Path | Role |
|---|---|
| `iFVG几个模型的讨论.txt` | Master design doc: strategy rules, layer architecture, phased roadmap |
| `diagram-四层正 EV 量化系统完整架构.svg` | Four-layer pipeline diagram |
| `diagram-目录结构规划.svg` | Planned package tree (module numbers 1–6) |
| `一些必备apikey和环境.txt` | Local env notes + **live API tokens** (never commit; see Risks) |

## Architecture & Data Flow

Four layers, strictly one-directional. Each layer may only *filter or manage*, never silently alter the
rule layer's decisions.

```
Data layer: NQ + ES 1m/5m bars/ticks + VXN index
   │
   ├─► 1. Deterministic rule engine  (DodgysDDStateMachine)  ──► candidate setups
   │        │
   │        └─► 2. Vision cross-validation (YOLOv8/v26)  ──► visual confidence + IoU
   │
   └─► 3. Meta-labeling filter (LightGBM, rolling walk-forward)  ──► P(Win)
              │  gate: P(Win) < 0.58 → abandon the trade
              ▼
   4. RL execution/risk agent (PPO/SAC): position multiplier, break-even trigger, partial TP
```

Module → file mapping (from `diagram-目录结构规划.svg`; package root is `dodgys_dd_quant/`):

| # | File | Responsibility |
|---|---|---|
| 1 | `dodgys_dd_quant/data_pipeline/prepare_parquet.py` | Databento DBN → `ParquetDataCatalog` bars; VXN clean + regime alignment |
| 2 | `dodgys_dd_quant/vision_validator/visual_cv.py` | Render 60 indicator-free candles → detector → IoU vs rule FVG box |
| 3 | `dodgys_dd_quant/strategy/custom_data.py` | `VXNRegimeData` and vision-signal `Data` objects on the engine timeline |
| 4 | `dodgys_dd_quant/strategy/state_machine.py` | Faithful DodgysDD rule state machine |
| 5 | `dodgys_dd_quant/strategy/dodgys_strategy.py` | NautilusTrader `Strategy`: multi-instrument subscription, filters, execution, log export |
| 6 | `dodgys_dd_quant/ml_pipeline/meta_labeling_train.py` | Log → features → meta-labels → purged walk-forward LightGBM |

**Rule engine (`state_machine.py`) — the deterministic core.** Five steps, no ML involved:

1. **HTF context & killzones** — NY AM `09:30–11:30 ET`, NY PM `13:30–15:30 ET`; track PDH/PDL, session highs/lows, unreclaimed 15m/1H FVGs.
2. **Liquidity sweep + SMT divergence** — NQ pierces a prior swing high/low (EQH/EQL/PDH/PDL); check ES or YM did *not* make a new extreme on the same leg → SMT divergence, +2 score points.
3. **Initial FVG identification** — 3-candle FVG in the last impulse leg (`c[i-2].high < c[i].low` bullish, inverse bearish); gap must exceed `0.25 * ATR(14)`.
4. **Inversion confirmation** — within **7–15 bars**, a candle whose **body close** fully penetrates the far edge of the FVG. Wick penetration does **not** count.
5. **Checklist scoring** — no uncleared opposing OB/equal-high-low in front; a clear liquidity target ≥ 2R away. Grades **A+ / A / B / C**.

**Meta-labeling (`meta_labeling_train.py`).** The rule engine decides *direction*; the classifier only decides
*"did this specific setup make money?"* — binary label `1 = reached 2R TP`, `0 = stopped out`. Rolling
walk-forward with an **embargo** (purged split): 6 months train / 1 month validate / 1 month test, rolling
forward monthly. Features: checklist score, SMT flag, vision confidence, VXN level and 1-hour change,
bars from FVG formation to inversion, minutes from US open.

**RL layer.** Position management **only** — it must never open a position. State: open PnL in R, VXN
regime, holding time, order-book imbalance. Reward: Sortino-like downside-adjusted, with an extra penalty
for reaching 1.5R and then failing to move the stop.

## Research Base (read before building anything)

`research/` holds the verified evidence base. **Every claim below is reproducible** — re-run the
scripts, do not trust the prose summaries.

| Path | What it establishes |
|---|---|
| `research/docs/RULE_SPEC.md` | The design doc's rules, threshold provenance, and a 30-item ambiguity register (`A01`–`A30`, `I01`–`I11`) |
| `research/analysis/PINE_RULES.md` | The reference iFVG implementation, extracted rule by rule from `ifvgUltimatePlus.pine` |
| `research/analysis/VISION_AUDIT.md` | The detector's real training distribution and why the doc's IoU gate is unreachable |
| `research/analysis/ML_REUSE.md` | Per-artifact use/adapt/discard verdicts for the 5 external projects |
| `research/analysis/DATA_FEASIBILITY.md` | Whether phase 1 can start, and what is missing |
| `research/audit/AUDIT.md` | Independent cross-audit of all of the above against source |
| `research/nautilus/NAUTILUS_API.md` | Verified NautilusTrader 1.221.0 API map with a smoke-test log |
| `research/audit/FINAL_REPORT.md` | **Start here.** The answers to Q1–Q5 and the build status |
| `research/experiments/e1_rule_falsification.py` | The E-1 falsification test — **run it** |
| `research/experiments/E1_RESULTS.md` | E-1's measured outcome |
| `.field-guide/` | Append-only log of environment quirks and non-obvious invariants |

### Findings that change the design

These are measured, not opinions:

1. **The rule engine as documented does not exist in the reference implementation.** No ATR filter,
   no SMT divergence, no A+/A/B/C scoring, no checklist. The doc's `0.25 × ATR(14)` gap floor, the
   SMT leg and the grade system have **no code basis** in any artifact we have.
2. **The inversion window is `[0,15]`, not `[7,15]`.** `graceCandles = allowExtIFVG ? 15 : 6` — an
   upper bound only, with no lower bound. The doc's "7" comes from a UI label, not the code.
3. **The liquidity sweep is OPTIONAL** in the reference script (`onlyShowSweptIFVG` defaults to
   `false`), while the doc treats it as a mandatory precondition.
4. **The doc's session windows gate alerts, not signals.** Setups are computed on every bar.
5. **The vision gate `IoU > 0.75` is unreachable by construction.** The detector's boxes wrap the
   *third candle's body*, which is **disjoint** from the FVG *gap*; a perfect detection scores
   **IoU = 0.00**. Measured: median 0.0000, 87.9 % exactly zero, 0.65 % above 0.75. Use a 2-D box
   IoU against the candle body, threshold ≈ 0.5, calibrated on the Kaggle test split.
6. **The detector needs a white 640×640 render**, not the doc's black 224×224. At 224×224 the median
   FVG box is 1.9 × 5.8 px.
7. **The A+/A/B/C grade exists in no artifact**, so the phase-1 gate "A/A+ only" has no implementable
   definition. Report grades; do not filter on an invented rubric.
8. **The lake's two manifests contradict each other** on whether NQ/ES 1-minute bars exist. Check
   the mounted share before promising phase 1.
9. **E-1 (executed, rev. 2, on the full 3.9-year BTCUSDT 1-minute dataset — 2,046,240 bars):
   no edge.** With **one position at a time**, E[R] spans **−0.024 to +0.014** across all 32 arms,
   every 95% CI includes zero, and **PF never exceeds 1.051** against the design doc's **> 1.25** gate.
   With a 0.05 R round trip every arm is negative. ⚠️ The first version of this result was wrong: it
   counted **423,759 simultaneously-open, correlated positions** as independent bets (t = 15.28).
   **A backtest must hold at most one position at a time, and significance must be quoted from that
   arm.** Phase 2 (ML) must not start.
10. **The upstream author's own replica concludes the strategy has no value** — see the README in
    `research/github/IFVG-Ultimate-Dodgy/`. Treat a negative phase-1 result as a likely outcome to be
    measured, not an impossibility.

## Data Lanes — what actually exists (measured 2026-11-22)

The **authoritative** lake is an **NFS mount**: `nfs://fnos2.local/fs/1000/nfs/iflow/database`
(`fnos2.local` = 192.168.1.6 — the same NAS as the SMB share, but the NFS export is world-accessible
while SMB rejects every credential). Mount it with
`sudo mount -t nfs -o rw,vers=3,proto=tcp fnos2.local:/fs/1000/nfs ~/iflow_lake`.
`/home/da/桌面/database/` is only a **working checkout** — **publish new governed partitions to the NFS
mount**. Full evidence: `research/analysis/DATA_ACQUISITION.md`.

| Asset | 1-minute | Multi-year lane |
|---|---|---|
| NQ | 7,490 bars (2026-09-24 → 10-01) only — **confirmed on the NFS lake** | 1h from 2024-05; 1d from 2021-10 |
| ES | 7,489 bars (same week) | 1h from 2024-05; 1d from 2021-10 |
| GC / XAU | 7,714 bars (same week) | 1h from 2024-05; 1d from 2021-10 |
| QQQ | 2,428 bars (1 week) | **15m from 2022-10** (73,325 bars) |
| BTCUSDT | **being filled → 2023-01 → 2026-11** | 15m from 2024-01; `bar_ofi` 1m from 2023-01 (1.64 M bars) |
| ETHUSDT | **being filled → 2023-01 → 2026-11** | **15m from 2020-01** (239,520 bars) |

**The 1-minute CME ceiling is measured, not assumed.** Yahoo serves only ~1–2 days of 1m
(`range=1mo` → HTTP 422); cryptohftdata has no candle family; OKX needs ~14,000 requests per symbol.
The only free multi-year CME 1m path found is Twelve Data's lake mirror, pulled by **Parquet
columnar pushdown over HTTP Range** (its `bars_1min/train.parquet` is 3.33 GB but NQ/ES live in a
few row groups). Otherwise **Databento (~$10–30)** is the route the design doc already names.

**Already in the lake and directly useful:** `macro/vxn/VXN_1d_consolidated.parquet` (CBOE official,
4,327 bars, 2009→2026 — newly ingested), `macro/dvol/BTCDVOL_1h` (crypto regime index),
`crypto_indices/CMC20/cmc20_15m_signals` (crypto cross-sectional regime),
`crypto/high_frequency_lob/BTCUSDT/BTCUSDT_1m_3years_governed.parquet` (**`bar_ofi`** — the RL's
missing order-book-imbalance state), and `depth20` / `lob_depth_microstructure` L2 files.

**Higher timeframes for the crypto lanes (pulled 2026-11-24).** BTCUSDT, ETHUSDT, SOLUSDT,
BNBUSDT and XRPUSDT now carry 5m/15m/30m/1h/2h/4h/1d partitions covering 2023-01 -> 2026-10/11,
built by `data_pipeline/resample.py` from the 1m lanes (BTC/ETH) or from a Binance Vision 5m pull
(SOL/BNB/XRP), with **complete-bucket-only** aggregation and the lake audit before publication.
Binance funding is present for all five (4,200 rows, 2023-01 -> 2026-10); OKX funding covers only the
venue's ~96-day history window.  The **legacy** 1h/4h/1d lanes are one-month stubs (744/186/31 bars,
2024-01) and the legacy 15m lanes start in 2024-01, so the longer series live in `*_resampled.parquet`
beside them -- pass `--data <path>` until a lane is republished under its canonical name.  Full evidence:
`research/analysis/DATA_LANES_2026-11.md`; the NFS concurrent-write hazard is in `.field-guide/env.md`.

**Consumption path:** `03_governed_lake/v2_parquet_lake/tools/db_loader.py` (`QuantDataLoader`) reads
from the NFS lake and caches under `~/.cache/quant_db/`. Its path convention was **stale** — it looked
for `<db_root>/<asset>/...` while the data lives under `03_governed_lake/v2_parquet_lake/`, so **every**
asset failed to resolve. Fixed and published; `polars` + `duckdb` must be installed for the 3.11
interpreter (PEP 668 → `--break-system-packages`). Verified loading BTCUSDT 1m (2,046,240 rows),
ETHUSDT 1m, QQQ 15m and NQ 1m straight from the NAS.

**Lake governance, briefly** (full contract in the lake's own `AGENTS.md`): five mathematical
invariants — strict monotonic UTC timestamps, no duplicates, `High ≥ max(Open,Close)` and
`Low ≤ min(Open,Close)`, strictly positive prices, `Volume ≥ 0` **plus** the flat-bar corollary
"`volume == 0` implies `O == H == L == C`". Analytical lake = int64 **ms**, **left-open**, Parquet
**Zstd-7**, atomic `.tmp` → rename. **No synthetic forward-fill.** Note: the lake's own auditor only
tests `volume < 0`, so it **cannot** detect a zero-volume non-flat bar — verify that rule yourself.
**Verified** by `dodgys_dd_quant.data_pipeline.audit` (all five invariants plus the flat-bar
corollary): the governed `BTCUSDT_1m_consolidated.parquet` (2,046,240 bars) passes every one.

## What is built (and what it shows)

`dodgys_dd_quant/` now exists and is verified end to end:
- `strategy/` — the rule engine: causal swings, one-shot sweep levels, ATR gap floor, inversion window
  `[1,15]`/`[7,15]`, BE-intact gate, checklist as five booleans (**reported, never filtered on**),
  VXN regime with a one-day lag. Emits the **D2** candidate log verbatim.
  **`dodgys_strategy.py` is the NautilusTrader strategy (doc module #5)**: it consumes the precomputed
  candidate feed (the rules are *not* re-run per bar -- the engine is O(history)) and owns execution --
  bracket orders (market entry, limit TP, stop-market SL), one position at a time, an optional time
  exit, and the export. `backtest/nautilus_runner.py` runs it in `BacktestEngine` and writes
  `fills/positions/account.parquet`; `data_pipeline/catalog_builder.py` builds the
  `ParquetDataCatalog` (`CryptoPerpetual`, ns close timestamps). Parity on a 2,000-bar BTC 30m slice:
  240 candidates -> 52 brackets -> **49 positions, the engine's 49**. The reference's remaining
  machinery is ported as **opt-in switches**: the leg-origin tracker, the break-even level and its
  resolution, the HTF confluence gate, the setup-history cap, the per-direction candidate cap, the
  hand-aggregated HTF view with its three-bar fractal sweep object, and the roll-boundary guard.
- `vision_validator/` — the D6 contract: a white 640×640 render, a 2-D box IoU against the third
  candle's **body**, a calibrated body-IoU threshold, the gap IoU demoted to a descriptive statistic
  and the three-part gate.
- `ml_pipeline/` — binary meta-labels, purged 6/1/1 walk-forward with an embargo tied to the label
  horizon, LightGBM, **D3** artefacts, a Kaggle kernel generator that never sees the test fold.
- `backtest/` — costs isolated in the config, **one position at a time**, per-fold model, the
  forward-only guard that **raises** on a malformed fold, an **independent** rule-only baseline,
  per-fold and deflated-Sharpe statistics, the write-once trial registry and the CSCV/PBO.
  Every run can be **archived** (`--archive <dir>`): `runs.parquet` (one row of statistics and the
  kill-switch verdict) and `candidates.parquet` -- **every** candidate, taken or not, with its
  geometry, all features, the model's `p_win`, the gate's decision, the portfolio's `selected` flag
  and the final label `y`.  The whole `symbol x timeframe x preset` sweep is reproducible with
  `python -m dodgys_dd_quant.backtest.matrix` (see `research/experiments/BASELINE_MATRIX_2026-11-24.md`).
  The holding period is a **time** (`--horizon-minutes`), converted to the scanned series' bar
  count, and the outcome can be resolved on a finer **execution series**
  (`--execution-data`, `backtest/execution.py`): the signal decides *whether* to trade, the
  execution bars decide *which barrier came first*. The meta-label gate can use each fold's
  **validation-fold quantile** on an isotonic-calibrated probability (`--gate quantile`)
  instead of the fixed 0.58, which on uncalibrated scores opened in bursts and closed for
  years at a time.
- `analysis/` — the L3 §C.2 regime-correlation test (per-band E[R], CR1 errors, moving-block
  permutation p-value) and the **no-FVG momentum control** (L4 §C.6's A4): a plain ATR-normalised
  momentum system the FVG has to beat.
- `rl/` — the action space that **cannot open a position**, the downside-adjusted reward with the
  1.5R failure penalty and the scale-free state.
- `data_pipeline/` — the governed-lake **auditor** (the five invariants plus the flat-bar
  corollary the lake's own auditor cannot see), the **roll-boundary** detector (a contract switch
  must not fake a sweep), the **session calendar** (the killzone windows and the Globex open in
  New York time *with DST*, the regular-trading-hours flag), and the Nautilus ingest
  (`prepare_parquet.py`): the CME `FuturesContract` definitions (NQ/MNQ/ES/MES, with the cost
  model's tick and multiplier), the catalog writer and the continuous-series-as-dated-contracts rule.
- `backtest/` — the write-once trial registry, the **CSCV/PBO**, the D4 accounting statement, the
  paper stage's **slippage-parity** check, **L4 §C.6's five abort criteria** — the "kill the
  project" rules, evaluated on the concatenated OOS and wired to the kill-switch's K3 — and the
  **degradation monitor** (L4 §F.3): the fold's training P(Win) distribution and feature
  importances live in the D3 artefact, and the walk-forward feeds the switch's three signals.
- `strategy/custom_data.py` — the regime index and the vision verdict as Nautilus `Data` objects,
  so the two exogenous signals ride the engine's timeline.

**153 unit tests pass** (LightGBM is importable from the 3.11 interpreter, so nothing is
skipped). The
`bench/` capability benchmark runs 167 executable probes over the same code — 5,908 verified
capability points, 0 invariant failures (`bash autoresearch.sh`).

**Measured on 2,046,240 real BTCUSDT 1-minute bars, 366,500 candidates, 39 folds** — re-measured
on 2026-11-23 after the timezone and portfolio-accounting fixes, on the governed lake
(`BTCUSDT_1m_consolidated.parquet`), `preset=honest`, doc window (7, 15), binance cost, 1 tick of
slippage. The run is reproducible: LightGBM's thread count is pinned.

| | n trades | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|
| Rule only | 32,521 | −0.0183 | −0.6328 | 0.973 | −2.34 | [−0.034, −0.003] |
| ML-gated (`P(Win) ≥ 0.58`) | 282 | 0.0000 | −0.6310 | 1.000 | 0.00 | [−0.165, +0.165] |

Both arms use the **drop** accounting (a signal blocked by an open position is discarded). The
D4 baseline in `E1_RESULTS.md` is the **deferred** arm (a blocked signal stays pending and may
trigger later at a different price) — 15,928 trades, E[R] −0.020 R, PF 0.971, t = −1.76 — so the
two tables are *not* the same accounting and must not be compared row for row. The E-1 arms still
reproduce exactly: the census arm 423,759 trades / E[R] +0.033 / PF 1.051 / t = 15.28, and every
one-at-a-time arm's CI includes zero.

****The timeframe, not the rules, decided the published verdict (E3/E4).** On the same instrument,
features and costs, ETHUSDT 1m gives E[R] -0.0003 (n=39,645, mean cost 0.636 R) and ETHUSDT 15m
gives +0.0475 (n=4,221, t=2.17, mean cost 0.111 R) — the first positive gross edge in the
repository, exactly cancelled by the Binance fee (break-even cost 0.0475 R).  The `doc` preset's
ATR floor is the only filter that turns the net expectancy positive (+0.0159 R, n=354, t=1.32 —
underpowered).  The reference-faithful `pine` preset collapses (-0.41 R, 19.3 % win rate) because
its break-even exit is resolved on the same bars that produced the setup.  See
`research/experiments/ETH15_WALKFORWARD.md` and `research/analysis/STRATEGY_VERSIONS.md`.

The no-FVG control (L4 §C.6, A4).** `dodgys_dd_quant.analysis.momentum_baseline` is a plain
ATR-normalised momentum system on the same bars, the same costs and the same one-position-at-a-time
accounting. On the same 2,046,240 bars it closes **444,928 trades at +0.0455 R gross** — against
the rule engine's **−0.0183 R gross**. The FVG therefore *loses* to a plain momentum system before
costs; it wins only **net** (−0.633 R against the control's −2.051 R), and only because its stops
are wider, so the same fee buys a larger cost in R. The honest reading: the rule engine has **no
gross edge at all**, and the cost profile decides which arm looks better. This is why L4 §C.6's A4
compares the two arms **gross against gross** — a net comparison is rigged by the risk definition —
and leaves the "is it tradable" question to A2.

**The repo's own verdict on that run is K3 — kill the project.** The walk-forward evaluates L4
§C.6's abort criteria and prints them:

```
KILL-SWITCH: K3   signals fired: calibration, importance_churn
ABORT CRITERIA (L4 C.6): fired A1, A2, A4
```

All five criteria are evaluated. A1 fires (the meta-labeler adds nothing: the net expectancy is
not positive and the CI includes zero), A2 fires (the gross edge does not survive the costs: only
the cost-heavy bucket is profitable) and A4 fires (the FVG does not beat the no-FVG control); the
degradation monitor's calibration and churn signals fire as well. A3 and A5 are evaluated and do
not fire. The published artefact is
`research/experiments/E2E_MODEL_WALKFORWARD.txt`.

The 1:2 break-even win rate is exactly 33.3 %; the measured win rate is 32.7 % (rule-only) and
33.3 % (gated). `auc_test` is **0.485–0.522** across all folds — the meta-labeler has no predictive
power. The round-trip cost is **0.61–0.63 R** per trade, and the gross expectancy is **−0.018 R**:
the rule-only arm already loses before costs, and the costs bury it. Both t-statistics are quoted
from the **one-position-at-a-time** arm (D4) — the census arm's t = 15.28 is an artefact of
correlated trades and is never quoted. **Phase 2 (ML) must not start.**

## Key Directories

```
dodgys_dd_quant/          # package root (planned; does not exist yet)
├── data_pipeline/        # #1 market data ingest → Nautilus Parquet catalog
├── vision_validator/     # #2 chart rendering + detector IoU
├── strategy/             # #3 custom Data, #4 rule engine, #5 main strategy
└── ml_pipeline/          # #6 feature engineering + rolling training
configs/                  # planned: backtest/, live/, strategy/, symbols/, regimes/
tests/                    # planned: unit/ (rules), integration/ (backtest), vision/
data/                     # gitignored: catalog/, *.parquet, models/
```

Data lake (external, governed): `smb://192.168.1.6/iflow/database`, governed by
`github.com/jssyxd/dataBaseLake`. Incremental pulls must pass that repo's audit/governance standard and be
marked **可用 / 可入湖** before use. Binance/OKX official history and cryptohftdata.com supplement crypto coverage.

## Development Commands

No build system exists yet. The design doc's `conda` recipe does **not** match this machine (no conda
installed) — use the uv-managed 3.11 interpreter, which already has NautilusTrader.

```bash
# interpreter that owns nautilus_trader 1.221.0
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11

$PY -V                                   # 3.11.17 — REQUIRED (NT needs >=3.11,<3.14)
$PY -c "import nautilus_trader; print(nautilus_trader.__version__)"

# deps still missing for the doc's full stack
$PY -m pip install databento yfinance mplfinance ultralytics lightgbm scikit-learn pytest
```

Run the engine. The wheel ships **no `nautilus` console script** — use the module entry
points. The configuration is a **JSON list** and `--raw` takes the **raw JSON string**
(`--fsspec-url` takes a path), so a file is passed with a shell substitution:

```bash
# the phase-1 baseline backtest (NQ + ES, one minute)
$PY -m nautilus_trader.backtest --raw "$(cat configs/backtest/phase1_baseline_nq_es.json)"

# the capability benchmark (83+ executable probes over the real numbers)
bash autoresearch.sh
```

The configuration is **JSON only** — NautilusTrader 1.221's config layer is msgspec and the
package ships no YAML support. `configs/backtest/phase1_baseline_nq_es.json` expects the
Nautilus catalog at `artifacts/catalog/nq_es`, which `dodgys_dd_quant.data_pipeline.prepare_parquet`
writes from the governed lake.

Run the E-1 falsification test (the only executable experiment available today):

```bash
$PY research/experiments/e1_rule_falsification.py     # ~5 s, stdlib only
```

Planned project commands once tooling lands (keep them in a `Makefile`):

```bash
make data      # DBN → ParquetDataCatalog + vxn_aligned.parquet
make backtest  # phase-1 rule-only baseline
make features  # logs → labelled dataset
make train     # purged walk-forward LightGBM
make test      # pytest
make lint      # ruff + mypy
```

## Code Conventions & Common Patterns

- **Style**: PEP 8, 4-space indent, type hints on public functions, `from __future__ import annotations`.
- **Naming**: `snake_case` for modules/functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for
  constants (thresholds such as `MIN_GAP_ATR_MULT = 0.25`, `INVERSION_MIN_BARS = 7`,
  `INVERSION_MAX_BARS = 15`, `VISION_IOU_THRESHOLD = 0.75`, `META_LABEL_THRESHOLD = 0.58`).
  Put all tunable thresholds in **one** constants module — never inline magic numbers in logic.
- **Config format**: NautilusTrader 1.221 has **no YAML support**; its config layer is msgspec JSON
  (`msgspec.json.decode(..., type=list[BacktestRunConfig])`). Use **JSON only** — do not introduce a second
  config convention. File naming: `snake_case.json`, phase-prefixed (`phase1_baseline_nq_es.json`),
  per-market files under `configs/symbols/` (`nq.json`, `mes.json`, `qqq.json`, `gc.json`, `btc.json`, `eth.json`).
- **Engine idiom**: event-driven. All decisions in `on_data`/`on_bar` handlers; the rule engine is a **pure**
  function of the bar history (no I/O, no engine calls) so it is unit-testable without a backtest.
- **Look-ahead prevention**: every exogenous series must be lagged. VXN uses `Close.shift(1).bfill()` and
  regime labels are derived from the lagged value. Never use the current bar's close for a decision that
  fires on that same bar's close.
- **Error handling**: raise on data-integrity violations (missing bars, non-monotonic timestamps, unknown
  instrument); never silently skip. Return `None`/`False` for "no signal" — that is a normal outcome, not an error.
- **Custom data**: VXN regime and vision results must be `nautilus_trader.core.data.Data` subclasses
  (via `@customdataclass`) so they align on the engine timeline with bars.
- **Multi-instrument**: subscribe NQ (traded) and ES/YM (SMT reference) in the same strategy instance;
  align on timestamps, do not resample across instruments.
- **Signal integrity**: the upstream closed-source indicator erases losing setups post-hoc
  ("Hide Losing Setups"). **Never** delete or hide failed signals in logs, charts, or training data —
  every candidate setup must be persisted with its outcome.

## Important Files

| Path | Why it matters |
|---|---|
| `iFVG几个模型的讨论.txt` | Single source of truth for rules, thresholds, roadmap |
| `diagram-四层正 EV 量化系统完整架构.svg` | Layer contracts, the `0.58` gate, RL action space |
| `diagram-目录结构规划.svg` | Canonical package/module layout — follow it |
| `dodgys_dd_quant/strategy/state_machine.py` | The rules; everything else filters its output |
| `dodgys_dd_quant/strategy/dodgys_strategy.py` | Wires filters, sizing, bracket orders, log export |
| `dodgys_dd_quant/data_pipeline/prepare_parquet.py` | Only module with concrete code in the docs — **implemented** against the installed NT 1.221 API: the CME `FuturesContract` definitions, the catalog writer (the instrument's price precision, the ns timestamp discipline) and the continuous-series-as-dated-contracts rule |

## Runtime / Tooling Preferences

- **Python 3.11 only.** `nautilus_trader` 1.221.0 requires `>=3.11,<3.14`. The system `python3` is **3.14**
  and **cannot** import it — always use the uv-managed 3.11 interpreter path shown above.
- **Package manager**: `uv` (`/home/da/.local/bin/uv`) — conda is unavailable on this host despite the doc's
  recipe. Pin `nautilus_trader==1.221.0` and the installed bounds (`pandas>=2.2.3,<3`, `numpy>=1.26.4`,
  `pyarrow>=21`, `msgspec>=0.19,<1`, `fsspec>=2025.2,<2026`, `click>=8,<9`).
- **Installed**: `nautilus_trader 1.221.0`, `pandas 2.3.3`, `numpy 2.4.6`, `pyarrow 26.0.0`, `msgspec 0.22.0`,
  `fsspec 2025.12.0` (python3.11 site-packages). **Missing**: `databento`, `yfinance`, `mplfinance`,
  `ultralytics`, `lightgbm`, `scikit-learn`, `pytest` (for 3.11).
- **GPU**: the vision layer needs CUDA for YOLOv26m; run the detector out-of-band or CPU-fallback explicitly
  rather than silently degrading.
- **Secrets**: `一些必备apikey和环境.txt` holds live GitHub/HF/Kaggle/CryptoHFT tokens. It must be
  gitignored, never copied into code or committed, and replaced by env vars / `.env` (gitignored) with a
  committed `.env.example` listing key **names** only.

## Testing & QA

No test suite exists yet. Planned layout:

```
tests/unit/         # state machine, FVG detection, SMT, regime binning — pure functions, no engine
tests/integration/  # backtest smoke tests, catalog round-trip, feature/label alignment
tests/vision/       # IoU computation, render→detect determinism
```

- **Framework**: `pytest` (install into the 3.11 interpreter; the system 3.14 pytest is unusable).
- **Phase gates — these are acceptance criteria, not aspirations:**
  - *Phase 1 (rule-only, weeks 1–2)*: EV must be **positive** under realistic costs — ~**$4.5 round-turn
    fees**, **1–2 ticks** slippage, fixed 1:2 RR, A/A+ setups only → **Profit Factor > 1.25**. A negative
    pure-rule result means the rule reproduction is wrong; **never** paper over it with ML.
  - *Phase 2 (features + vision, weeks 3–4)*: win rate **> 55%** (from ~45%) and materially lower max drawdown.
  - *Phase 3 (RL + paper trading, weeks 5–6)*: PPO position/BE management, then **4 weeks** forward paper
    trading on IB / Tradovate / Rithmic to confirm backtest↔live slippage parity.
  - Target steady state: sample-out-of-sample **Sharpe > 1.8**, **max drawdown < 10%**.
- **Leakage checks are part of QA**: assert VXN is lagged, assert walk-forward splits have an embargo
  (no train/test overlap), assert the visual IoU threshold is applied, assert RL never emits an open action.
- **Cost model** belongs in the backtest config, not in strategy logic, so backtests and paper runs share it.
- Tests must be deterministic and isolated from the network; data comes from the local catalog / data lake.

## Market Expansion Reference

Migration path — the core state machine is **not** rewritten per market, only parameters change:

| Target | SMT reference | Regime index | Key tuning |
|---|---|---|---|
| NQ / MNQ | ES / YM | VXN | Baseline template, core window 09:30 ET |
| MES | NQ / RTY | VIX | Min-gap ATR coefficient **0.25 → 0.20** |
| QQQ | SPY / IWM | VXN | Add overnight gap as primary liquidity target |
| GC (gold) | SI / DXY | GVZ | Windows shift to London 03:00 ET and COMEX 08:20 ET |
| BTC / ETH | BTC ↔ ETH | DVOL | 24/7; sweeps concentrate at 09:30 ET and UTC 00:00 |

Regime behavior (VXN bands `0 / 18 / 28 / 200` → `0 = low-vol range, 1 = normal trend, 2 = high-vol panic`):
low → tighten to A+ only, RR 1:1.5–1:2; normal → RR 1:2.5–1:3 to the opposite liquidity pool;
high → halve risk per trade, raise the minimum ATR gap threshold.

## Risks & Known Gaps

**Resolved by the research wave — do not re-open:**
- The doc's `prepare_parquet.py` sample is **mostly valid against 1.221** — `BarSpecification(1,
  BarAggregation.MINUTE, PriceType.LAST)`, `BarType(inst_id, spec)`, `Price.from_str` and
  `catalog.write_data(bars)` were all verified working. Its real defects are: no CME instrument
  definition (`TestInstrumentProvider` is imported but unused), hard-coded 2-decimal prices, and no
  `uint64` ns type discipline. See `research/nautilus/NAUTILUS_API.md`.
- CME instrument definitions (tick size, multiplier, precision) are **not** specified anywhere;
  `InstrumentId.from_str("NQ.XCME")` alone is not tradable in Nautilus. Use
  `nautilus_trader.model.instruments.FuturesContract` — there is **no `Future` class**. Its
  `activation_ns`/`expiration_ns` are mandatory, so continuous-contract handling is an open decision.
- The RL layer has **no file path** in any document — decide one (e.g. `rl/`) before implementing.
- Visual model: HF `ibtsam/nq-fvg-detector` (Ultralytics YOLOv26m, AGPL-3.0, 640×640, classes
  `bullish_fvg`/`bearish_fvg`) was trained on **white-background TradingView charts**, contradicting the
  doc's black-background 224×224 requirement. Resolve the rendering convention explicitly — either
  re-render in the model's training style or retrain; do not mix them silently.
- "Visual Clarity Score" is named but never defined — pin its formula before wiring it into features.
- Feature spec requires VXN **1-hour change rate**, but the pipeline builds **daily** VXN — resolve the
  mismatch (daily regime + intraday change from another source, or drop the feature).
- `AlphaGPT` / `Qlib` do not fit a single-contract event-driven state machine — but the doc's stated
  reason is wrong. AlphaGPT has **no IC/RankIC** (its fitness is a dense cross-sectional P&L over a
  hard-wired crypto feature set); Qlib has **no futures support, no shorts and no cross-sectional-free
  strategy**, and its rolling machinery drags in YAML + mlflow/redis/mongo. Take the *concept*
  (expanding monthly folds, purge, concatenated OOS predictions) and reimplement it. See
  `research/analysis/ML_REUSE.md`.

**Still open — these block the build:**
- **The phase-1 gate is unimplementable as written** because "A/A+ only" has no definition. **Closed by
  substitution:** the five named checklist conditions are implemented as booleans and the grades are
  *reported*, never filtered on.
- **No reachable NQ/ES 1-minute pair with a documented roll rule.** The two lake manifests disagree;
  the databank MANIFEST lists NQ/ES as **1-Day only**. The share `smb://192.168.1.6/iflow/database` is
  not mounted on this host. The roll rule matters: a roll gap can fake a liquidity sweep. **The rule
  itself is implemented** (`data_pipeline/roll.py` and the engine's roll guard); what is missing is the
  *per-contract* data, which is a purchase.
- **No intraday VXN.** The pipeline builds daily VXN, but the ML feature list needs a 1-hour change
  rate. **Dropped, not fabricated** (RULE_SPEC A18): the feature list carries the exclusion with its
  reason.
- **No order-book imbalance data**, which the RL state requires (doc L151). The state uses the
  close-location proxy (L4 §D.3) and says so.
- **Continuous-contract handling is undecided.** `FuturesContract` requires mandatory
  `activation_ns`/`expiration_ns`; a continuous NQ contract has no single expiry. **Decided:** a
  continuous series is a **series of dated contracts**, one per roll segment
  (`data_pipeline/prepare_parquet.py`).
