# Repository Guidelines

## Project Overview

Implementation of a **positive-EV quantitative trading system** for DodgysDD's
*Inversion Fair Value Gap* (iFVG) strategy, built on **NautilusTrader** as both backtest and live engine.

The strategy reacts (not predicts): after price sweeps liquidity and fails to hold an FVG, the FVG
inverts into a resistance/support zone; entry is on the failed retest, stop beyond the recent swing,
target the next liquidity pool. The **rule engine, the cost model, the rolling walk-forward and the
meta-labeler are implemented and have been run against ten years of real NQ 1-minute data**
(`research/audit/PHASE1_REPORT.md`); the vision layer and the RL layer are not built.

Current repo contents:

| Path | Role |
|---|---|
| `iFVG几个模型的讨论.txt` | Master design doc: strategy rules, layer architecture, phased roadmap |
| `diagram-四层正 EV 量化系统完整架构.svg` | Four-layer pipeline diagram |
| `diagram-目录结构规划.svg` | Planned package tree (module numbers 1–6) |
| `dodgys_dd_quant/` | The implementation: `strategy/`, `backtest/`, `ml_pipeline/` |
| `scripts/` | Data ingest, the roll detector, the lake audit, the report renderer |
| `research/audit/PHASE1_REPORT.md` | **The current result** — every figure parsed from a real run |
| `.field-guide/` | Append-only log of environment quirks and hard-won facts |
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

| # | File | Responsibility | Status |
|---|---|---|---|
| 1 | `dodgys_dd_quant/data_pipeline/prepare_parquet.py` | Databento DBN → `ParquetDataCatalog` bars; VXN clean + regime alignment | not built — the lake path (`scripts/ingest_futures_1m.py`) is used instead |
| 2 | `dodgys_dd_quant/vision_validator/visual_cv.py` | Render 90 indicator-free candles → detector → IoU vs the rule FVG | **built** |
| 3 | `dodgys_dd_quant/strategy/custom_data.py` | `VXNRegimeData` and vision-signal `Data` objects on the engine timeline | not built |
| 4 | `dodgys_dd_quant/strategy/state_machine.py` | Faithful DodgysDD rule state machine | **built** |
| 5 | `dodgys_dd_quant/strategy/dodgys_strategy.py` | NautilusTrader `Strategy`: multi-instrument subscription, filters, execution, log export | not built — the backtest harness (`dodgys_dd_quant/backtest/`) drives the engine instead |
| 6 | `dodgys_dd_quant/ml_pipeline/meta_labeling_train.py` | Log → features → meta-labels → purged walk-forward LightGBM | **built** |

The rule engine is a **pure function of the bar history** (no I/O, no engine calls), so the backtest
harness and the unit tests drive the *same* code the live strategy would.

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
8. **The lake's two manifests contradicted each other** on whether NQ/ES 1-minute bars exist.
   Resolved 2026-11-23: the lake's manifest registers NQ/ES at `us_futures/<sym>/` with a `1m`
   timeframe, and **10 years of NQ 1-minute + 4 years of ES 1-minute are now in the lake**
   (Hugging Face; see Data Lanes below).
9. **E-1 (executed, rev. 2, on the full 3.9-year BTCUSDT 1-minute dataset — 2,046,240 bars):
   no edge.** With **one position at a time**, E[R] spans **−0.024 to +0.014** across all 32 arms,
   every 95% CI includes zero, and **PF never exceeds 1.051** against the design doc's **> 1.25** gate.
   With a 0.05 R round trip every arm is negative. ⚠️ The first version of this result was wrong: it
   counted **423,759 simultaneously-open, correlated positions** as independent bets (t = 15.28).
   **A backtest must hold at most one position at a time, and significance must be quoted from that
   arm.**
10. **Phase 1 on NQ (executed 2026-11-23, 3,664,241 bars): the reference-faithful arm has a real
    but too-small edge.** E[R] = **+0.0317 R**, t = **3.52**, CI **[0.014, 0.049]**, PF 1.048, over
    25,083 trades — significant, and **net-negative (−0.070 R)** against the 0.102 R round trip.
    The **leg tracker is the entire source of the edge** (alone: +0.0303, t = 3.38); the BE-intact
    gate adds +0.0014. Three engine defects were hiding this and are now fixed (the leg tracker's
    pivots were a 3-bar rolling minimum, so the arm produced **one trade in ten years**;
    `require_be_intact` was dead config; SMT recorded "absent" where the reference had no data).
11. **The upstream author's own replica concludes the strategy has no value** — see the README in
    `research/github/IFVG-Ultimate-Dodgy/`. Treat a negative phase-1 result as a likely outcome to be
    measured, not an impossibility.
12. **The edge is in the entry, not the payoff.** The RR sweep (1:1 → 1:4) moves gross E[R] inside a
    band of 0.008 R; the NY killzone moves it by **+0.049 R** and the checklist by **+0.015 R**;
    widening the stop *destroys* it (−0.068 R at 3×). The reference's 1:2 target was never the problem.
13. **The doc's `IoU > 0.75` vision gate IS reachable.** `VISION_AUDIT.md` asserted the opposite from
    a *static* reading of the checkpoint, without ever running the model. Measured: **336/348**
    detector boxes land on a rule-engine FVG's middle bar (96.6 %), the class matches the gap's
    direction in 96.1 %, and the vertical IoU against the **gap interval** has a median of **0.9518**
    with 94.9 % above 0.75. The boxes wrap the **gap**, not the third candle's body. **Never infer
    what a model does — measure it.**
14. **The detector's *confidence* is a real filter** (win% 35.2 vs 30.7, E[R] +0.055 vs −0.079,
    two-proportion z = **+2.26**); the IoU itself is uninformative (corr +0.002 with the outcome).

## Data Lanes — what actually exists (measured 2026-11-23)

The **authoritative** lake is an **NFS mount**: `nfs://fnos2.local/fs/1000/nfs/iflow/database`
(`fnos2.local` = 192.168.1.6 — the same NAS as the SMB share, but the NFS export is world-accessible
while SMB rejects every credential). Mount it with
`sudo mount -t nfs -o rw,vers=3,proto=tcp fnos2.local:/fs/1000/nfs ~/iflow_lake`.
`/home/da/桌面/database/` is only a **working checkout** — **publish new governed partitions to the NFS
mount**. Full evidence: `research/analysis/DATA_ACQUISITION.md`.

| Asset | 1-minute | Multi-year lane |
|---|---|---|
| NQ | **3,664,241 bars, 2015-01-01 → 2025-07-25** (Hugging Face; quarterly splice detected and flagged) | 1h from 2024-05; 1d from 2021-10 |
| ES | **646,948 bars, 2020-11-17 → 2024-07-19** (Hugging Face; 55 % weekday coverage, holes up to 165 days) | 1h from 2024-05; 1d from 2021-10 |
| GC / XAU | 7,714 bars (same week) | 1h from 2024-05; 1d from 2021-10 |
| QQQ | 2,428 bars (1 week) | **15m from 2022-10** (73,325 bars) |
| BTCUSDT | **being filled → 2023-01 → 2026-11** | 15m from 2024-01; `bar_ofi` 1m from 2023-01 (1.64 M bars) |
| ETHUSDT | **being filled → 2023-01 → 2026-11** | **15m from 2020-01** (239,520 bars) |

**The 1-minute CME ceiling was measured — and the measurement was wrong.** Yahoo serves only ~1–2
days of 1m (`range=1mo` → HTTP 422); cryptohftdata has no candle family; OKX needs ~14,000 requests
per symbol; Twelve Data's lake mirror is an *equities* dataset with no NQ/ES at all. The conclusion
drawn from those — "multi-year NQ/ES 1m needs Databento (~$10–30)" — was **false**: two Hugging
Face datasets carry it for free.

- `mdelcristo/NQ-F_1min_OHLCV_Parquet` — NQ 1-minute OHLCV, one parquet per year, **2015–2025**
  (~50 MB). The `timestamp` is tz-**naive UTC**.
- `Khanhpham1992/es-futures-1m` → `es_continuous_1m.parquet` (15 MB) — ES 1-minute with the
  publisher's `instrument_id` per bar, plus `adj_*` columns.
- Hugging Face tolerates **parallel** downloads (4 at once succeeded); api.github.com does not.
  Use `curl -sL --fail --retry 3`.

**The continuous series is rolled, and the roll looks exactly like a liquidity sweep.** At **37 of
the 44** quarterly expiries in the NQ span there is a 1-minute move of **0.15 %–1.76 %** against a
1-minute sigma of **0.030 %** (5–58 σ). These are the publisher splicing two contracts, and they
must not be traded. The splice minute must be **detected** (the largest 1-minute move within ±3 days
of the expiry — the publisher's roll dates ran up to 33 days away from it), not assumed to sit on
the expiry date. `scripts/ingest_futures_1m.py` flags ±60 min around it as `roll_masked = 1`:
**0.169 %** of NQ, **0.300 %** of ES.

**The ES panel's `instrument_id` changes are dataset *segmentation*, not rolls.** The ids are not
contiguous in time — id 95414 ends 2023-05-05 and id 314863 starts 2023-10-18, a **five-month
hole**. The panel covers only **528 of 959 weekdays (55 %)**. Any ES-based SMT comparison across a
hole is meaningless; the code returns `smt_divergence = −1` (unknown) where the reference does not
cover the window.

**Already in the lake and directly useful:** `macro/vxn/VXN_1d_consolidated.parquet` (CBOE official,
4,327 bars, 2009→2026 — newly ingested), `macro/dvol/BTCDVOL_1h` (crypto regime index),
`crypto_indices/CMC20/cmc20_15m_signals` (crypto cross-sectional regime),
`crypto/high_frequency_lob/BTCUSDT/BTCUSDT_1m_3years_governed.parquet` (**`bar_ofi`** — the RL's
missing order-book-imbalance state), and `depth20` / `lob_depth_microstructure` L2 files.

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

## What is built (and what it shows)

`dodgys_dd_quant/` now exists and is verified end to end:
- `strategy/` — the rule engine: causal swings, one-shot sweep levels, ATR gap floor, inversion window
  `[1,15]`/`[7,15]`, BE-intact gate, checklist as five booleans (**reported, never filtered on**),
  VXN regime with a one-day lag. Emits the **D2** candidate log verbatim.
- `ml_pipeline/` — binary meta-labels, purged 6/1/1 walk-forward with an embargo tied to the label
  horizon, LightGBM, **D3** artefacts, a Kaggle kernel generator that never sees the test fold.
- `backtest/` — costs isolated in the config, **one position at a time**, per-fold model, the
  forward-only guard that **raises** on a malformed fold, an **independent** rule-only baseline,
  per-fold and deflated-Sharpe statistics.

**84 tests pass** (2 skipped: they need LightGBM, which lives in `.venv-ml/`).

**Measured on 2,046,240 real BTCUSDT 1-minute bars, 366,500 candidates, 39 folds:**

| | n trades | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|
| Rule only | 21,539 | −0.0002 | −0.4986 | 1.000 | −0.02 | [−0.019, +0.019] |
| ML-gated (`P(Win) ≥ 0.58`) | 652 | +0.0675 | −0.5245 | 1.105 | 1.20 | [−0.043, +0.178] |

The 1:2 break-even win rate is exactly 33.3 %; the measured win rate is 33.3 %. `auc_test` is
**0.483–0.521** across all folds — the meta-labeler has no predictive power. The round-trip cost is
**0.50–0.83 R** per trade while the break-even cost is **0.009 R**.

**Measured on 3,664,241 real NQ 1-minute bars (2015–2025), 120 folds — the current result:**

| arm | n trades | win% | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|---|
| `honest` (the scanner) | 45,734 | 32.9 | −0.0127 | −0.1436 | 0.981 | −1.93 | [−0.026, 0.000] |
| `pine_leg` (leg tracker) | 25,228 | 34.3 | **+0.0303** | −0.0714 | 1.046 | **+3.38** | **[0.013, 0.048]** |
| `pine` (reference-faithful) | 25,083 | 34.4 | **+0.0317** | −0.0700 | 1.048 | **+3.52** | **[0.014, 0.049]** |
| `pine` + ML gate | 705 | 35.0 | **+0.0511** | −0.0772 | 1.079 | +0.95 | [−0.055, +0.157] |

The 1:2 break-even win rate is 33.3 %; the reference arm's measured win rate is 34.4 %. `auc_test` is
**0.47–0.53** — still no predictive power. The round-trip cost is **0.102 R** against a gross edge of
**0.032 R**: the edge is significant but three times too small. **Phase 2 (ML) must not start**, and
the next lever is the payoff (the RR sweep), not the entry.

## Key Directories

```
dodgys_dd_quant/          # package root
├── strategy/             # #4 rule engine, the candidate log, the constants
├── backtest/             # the cost model, the rolling walk-forward, the runner
└── ml_pipeline/          # #6 feature engineering + the rolling meta-labeler
scripts/                  # data ingest, roll detection, the lake audit, the report renderer
tests/unit/               # the rule engine, the labels, the splits, the cost model
research/                 # docs/, analysis/, audit/, experiments/ — every executed output
data/                     # gitignored: candidate logs, models
artifacts/, artifacts_pine/  # gitignored: the trained folds and the walk-forward index
```

Data lake (external, governed): `~/iflow_lake/iflow/database` (NFS; the SMB share rejects every
credential), governed by `github.com/jssyxd/dataBaseLake`. Incremental pulls must pass that repo's
audit/governance standard and be marked **可用 / 可入湖** before use — run
`scripts/audit_lake_dataset.py` and write the declaration into the lake's `reports/` directory.
Binance/OKX official history and cryptohftdata.com supplement crypto coverage.

## Development Commands

No build system exists yet. The design doc's `conda` recipe does **not** match this machine (no conda
installed) — use the uv-managed 3.11 interpreter, which already has NautilusTrader.

```bash
# interpreter that owns nautilus_trader 1.221.0
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11

$PY -V                                   # 3.11.17 — REQUIRED (NT needs >=3.11,<3.14)
$PY -c "import nautilus_trader; print(nautilus_trader.__version__)"

# the ML extras live in their own venv (LightGBM is not in the runtime env)
.venv-ml/bin/python -c "import lightgbm; print(lightgbm.__version__)"
```

The **two interpreters** are a hard split: the 3.11 runtime env runs the rule engine and the
backtest; `.venv-ml` runs the feature builder and the meta-labeler, because LightGBM needs a build
the runtime env does not have. Never install LightGBM into the runtime env. The **vision layer has a
third env**, `.venv-vision/` (torch + ultralytics), because the uv runtime interpreter is
**externally managed** (PEP 668) and must not be modified.

```bash
# the rule engine, rule-only, one position at a time
$PY -m dodgys_dd_quant.backtest.runner --symbol NQ --timeframe 1m --preset pine \
    --cost-profile nq --slippage-ticks 1 --inversion-window doc --regime vxn \
    --reference-symbol ES --no-write-candidates

# the payoff / entry sweeps (the phase-1 report's §3-§5)
$PY -m dodgys_dd_quant.backtest.runner --symbol NQ --timeframe 1m --preset pine \
    --rr 1.0 --killzone --min-checklist 3 --min-checklist-known 4 \
    --cost-profile nq --slippage-ticks 1 --inversion-window doc --regime vxn \
    --reference-symbol ES --no-write-candidates

# the vision layer (its own env; no GPU on this host, 0.45 s per candidate)
.venv-vision/bin/python scripts/vision_signals.py \
    --candidates data/candidates/NQ_1m_pine_kz.parquet \
    --bars ~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/us_futures/NQ/1m/NQ_1m.parquet \
    --out data/candidates/NQ_1m_kz_vision.parquet
.venv-vision/bin/python scripts/analyze_vision_signal.py \
    --candidates data/candidates/NQ_1m_pine.parquet \
    --vision data/candidates/NQ_1m_vision.parquet

# the meta-labeler and then the gated walk-forward
.venv-ml/bin/python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler \
    --candidates data/candidates/NQ_1m_pine.parquet \
    --bars ~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/us_futures/NQ/1m/NQ_1m.parquet \
    --run-root artifacts_pine
$PY -m dodgys_dd_quant.backtest.runner ... --models-root artifacts_pine

# the data pipeline
bash scripts/fetch_hf_futures_1m.sh
$PY scripts/ingest_futures_1m.py --symbol NQ --root research/hf_futures
$PY scripts/audit_lake_dataset.py --path <lake>/us_futures/NQ/1m/NQ_1m.parquet

# the report, re-rendered from the executed output
$PY scripts/render_phase1_report.py

# tests (pytest must be in the 3.11 env; the system 3.14 pytest is unusable)
$PY -m pytest tests/unit -q
```

Run the engine (the wheel ships **no `nautilus` console script** — use module entry points):

```bash
$PY -m nautilus_trader.backtest --raw configs/backtest/phase1_baseline_nq_es.json
$PY -m nautilus_trader.live     --raw configs/live/paper_tradovate.json
```

Run the E-1 falsification test:

```bash
$PY research/experiments/e1_rule_falsification.py     # ~5 s, stdlib only
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
| `research/audit/PHASE1_REPORT.md` | **The current result**, rendered from the executed output |
| `dodgys_dd_quant/strategy/state_machine.py` | The rules; everything else filters its output |
| `dodgys_dd_quant/strategy/constants.py` | Every tunable threshold in one place |
| `dodgys_dd_quant/backtest/runner.py` | The phase-1 CLI: preset, cost profile, slippage, regime |
| `dodgys_dd_quant/backtest/walk_forward.py` | The rolling walk-forward, the forward-only guard, the portfolio accounting |
| `dodgys_dd_quant/ml_pipeline/train_meta_labeler.py` | The purged walk-forward meta-labeler (D3 artefacts) |
| `scripts/ingest_futures_1m.py` | The lake ingest **with the detected roll mask** |
| `scripts/audit_lake_dataset.py` | The five mathematical invariants, re-derived from the stored file |
| `scripts/render_phase1_report.py` | Renders the phase-1 report from the executed output — never hand-edited |

## Runtime / Tooling Preferences

- **Python 3.11 only.** `nautilus_trader` 1.221.0 requires `>=3.11,<3.14`. The system `python3` is **3.14**
  and **cannot** import it — always use the uv-managed 3.11 interpreter path shown above.
- **Package manager**: `uv` (`/home/da/.local/bin/uv`) — conda is unavailable on this host despite the doc's
  recipe. Pin `nautilus_trader==1.221.0` and the installed bounds (`pandas>=2.2.3,<3`, `numpy>=1.26.4`,
  `pyarrow>=21`, `msgspec>=0.19,<1`, `fsspec>=2025.2,<2026`, `click>=8,<9`).
- **Installed**: `nautilus_trader 1.221.0`, `pandas 2.3.3`, `numpy 2.4.6`, `pyarrow 26.0.0`, `msgspec 0.22.0`,
  `fsspec 2025.12.0` (python3.11 site-packages). **Missing**: `databento`, `yfinance`, `mplfinance`,
  `ultralytics`, `lightgbm`, `scikit-learn`, `pytest` (for 3.11).
- **GPU**: there is **none on this host** (`nvidia-smi` is absent), so the detector runs on CPU at
  **0.45 s per candidate** — fine for a filtered subset, hopeless for the full 430 k census. The
  vision layer runs out-of-band in `.venv-vision/` and writes a parquet the strategy joins.
- **Secrets**: `一些必备apikey和环境.txt` holds live GitHub/HF/Kaggle/CryptoHFT tokens. It must be
  gitignored, never copied into code or committed, and replaced by env vars / `.env` (gitignored) with a
  committed `.env.example` listing key **names** only.

## Testing & QA

`tests/unit/` exists and runs (86 tests). Planned additions:

```
tests/unit/         # state machine, FVG detection, SMT, regime binning, cost model, splits — pure, no engine
tests/integration/  # backtest smoke tests, catalog round-trip, feature/label alignment
tests/vision/       # IoU computation, render→detect determinism
```

- **Framework**: `pytest` in the 3.11 interpreter (the system 3.14 pytest is unusable).
  `$PY -m pytest tests/unit -q` → 86 passed in ~3 s.
- **Look-ahead is tested by construction**: `test_truncating_the_future_does_not_change_the_signals`
  re-runs the engine on a truncated series and asserts the earlier signals are byte-identical.
  Every preset is parameterised over it — keep it that way.
- **Phase gates — these are acceptance criteria, not aspirations:**
  - *Phase 1 (rule-only)*: EV must be **positive** under realistic costs — ~**$4.5 round-turn
    fees**, **1–2 ticks** slippage, fixed 1:2 RR, A/A+ setups only → **Profit Factor > 1.25**.
    **Status: executed and FAILED.** The reference-faithful arm reaches PF 1.048 gross
    (E[R] +0.0317, t = 3.52) but −0.070 R net of the 0.102 R round trip
    (`research/audit/PHASE1_REPORT.md`). A negative pure-rule result means the rule reproduction is
    wrong; **never** paper over it with ML.
  - *Phase 2 (features + vision)*: win rate **> 55%** and materially lower max drawdown.
  - *Phase 3 (RL + paper trading)*: PPO position/BE management, then **4 weeks** forward paper
    trading on IB / Tradovate / Rithmic to confirm backtest↔live slippage parity.
  - Target steady state: sample-out-of-sample **Sharpe > 1.8**, **max drawdown < 10%**.
- **Leakage checks are part of QA**: assert VXN is lagged, assert walk-forward splits have an embargo
  (no train/test overlap), assert the visual IoU threshold is applied, assert RL never emits an open action.
- **Cost model** belongs in the backtest config, not in strategy logic, so backtests and paper runs share it.
- Tests must be deterministic and isolated from the network; data comes from the local catalog / data lake.
- **A regression test belongs beside every defect you fix in the rule engine.** Five shipped
  together with the phase-1 fixes: the leg tracker's pivot cadence, the BE-intact gate, the
  unknown-SMT case, the killzone gate reaching the leg tracker, and the stop multiplier.

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
- **The phase-1 gate is unimplementable as written** because "A/A+ only" has no definition. Substitute:
  implement the five named checklist conditions as booleans and *report* the grades rather than
  filtering on them.
- **The edge is real but too small for the costs.** The reference-faithful arm reaches
  E[R] = +0.0317 R (t = 3.52, CI [0.014, 0.049], PF 1.048) over 25,083 trades across ten years of
  NQ — but the round trip costs 0.102 R, so the arm is **net-negative at 1 tick of slippage** and
  the doc's `PF > 1.25` gate is unreachable by tuning. The next lever is the **payoff**, not the
  entry: sweep the RR (the run is a pure re-run with a different target) and the stop geometry,
  since a wider stop lowers the cost-to-risk ratio.
- **The meta-labeler has no out-of-sample signal** (`auc_test` 0.47–0.53 over 120 monthly folds).
  It does lift the reference arm's gross expectancy (+0.0317 → +0.0511 R) by selecting better
  setups, but the features it sees — checklist score, SMT flag, VXN regime, bar geometry — do not
  carry the signal. The **vision layer's IoU is not in the feature frame** and is the obvious
  candidate for an independent signal.
- **No intraday VXN.** The pipeline builds daily VXN, but the ML feature list needs a 1-hour change
  rate. Either source intraday VXN separately or drop the feature.
- **No order-book imbalance data**, which the RL state requires (doc L151). The RL layer also still has
  no file path and no action-space grid.
- **Continuous-contract handling is undecided.** `FuturesContract` requires mandatory
  `activation_ns`/`expiration_ns`; a continuous NQ contract has no single expiry.
- **ES covers only 55 % of the weekdays** in the 1-minute panel, with holes up to 165 days. The SMT
  comparison is therefore unavailable for long stretches of the NQ sample; it must report *unknown*
  (`−1`) rather than *absent* (`0`) there, or the ML features are poisoned.
