# DodgysDD iFVG — positive-EV quantitative system

A research-and-build repository for the **DodgysDD "Inversion Fair Value Gap" (iFVG)** trading strategy,
targeting **NautilusTrader** as the single backtest and live engine.

> **Status: phase 1 executed on real NQ 1-minute data (2015–2025).**
> The rule engine, the cost model, the rolling walk-forward and the meta-labeler are implemented and
> have been run against **3,664,241 real NQ 1-minute bars**. The reference-faithful arm has a
> **statistically significant but small** gross edge (+0.0317 R, t = 3.52) that is **three times too
> small to cover the 0.102 R round trip** — see [Phase 1](#phase-1-executed) and
> [research/audit/PHASE1_REPORT.md](research/audit/PHASE1_REPORT.md).

---

## What the strategy is

iFVG is ICT price-action, mechanised: after price sweeps liquidity and *fails* to hold a Fair Value
Gap, the gap **inverts** — a bullish support band broken by a body close becomes bearish resistance.
Entry is on the failure/retest, stop beyond the recent swing, target the next liquidity pool.

The four-layer architecture the design calls for:

```
Data layer        NQ + ES 1-minute bars + VXN
   │
   ├─► 1. Deterministic rule engine (DodgysDD state machine) ──► candidate setups
   │        │
   │        └─► 2. Vision cross-validation (YOLO detector)  ──► confidence + IoU
   │
   └─► 3. Meta-labeling filter (LightGBM, purged walk-forward) ──► P(Win)
            │   gate: P(Win) < 0.58 → abandon the trade
            ▼
   4. RL execution/risk agent (PPO/SAC): position multiplier, break-even, partial TP
```

Each layer may only *filter or manage*. It may never silently change the rule layer's decisions.

---

## Current findings

Read these before writing any code — they are measured, not opinions.

**The rule engine as documented does not exist in the reference implementation.** The open-source
replica of the closed-source TradingView indicator contains **no ATR filter, no SMT divergence, no
A+/A/B/C scoring and no checklist**. The doc's `0.25 × ATR(14)` gap floor, the SMT leg and the grade
system have **no code basis** in any artefact we have.

---

## Phase 1, executed

On **3,664,241 real NQ 1-minute bars** (2015-01-01 → 2025-07-25, with the quarterly splice detected
and masked), one position at a time, NQ costs (~$4.50 round trip + 1 tick):

| arm | what it adds | trades | win% | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|---|---|
| `honest` | the vectorised scanner | 45,734 | 32.9 | −0.0127 | −0.1436 | 0.981 | −1.93 | [−0.026, 0.000] |
| `pine_be` | + the BE-intact gate | 45,269 | 32.9 | −0.0135 | −0.1450 | 0.980 | −2.03 | [−0.026, −0.000] |
| `pine_leg` | + the leg tracker | 25,228 | 34.3 | **+0.0303** | −0.0714 | 1.046 | **+3.38** | **[0.013, 0.048]** |
| `pine` | both (reference-faithful) | 25,083 | 34.4 | **+0.0317** | −0.0700 | 1.048 | **+3.52** | **[0.014, 0.049]** |
| `doc` | the doc's ATR floor + sweep + killzone | 7,399 | 34.1 | +0.0242 | −0.1021 | 1.037 | +1.46 | [−0.008, +0.057] |

**Three findings that change the project.**

1. **The leg tracker is the entire source of the edge.** On its own it moves E[R] from −0.013 to
   +0.030 and t from −1.9 to +3.4; the BE-intact gate does nothing on its own. This was invisible
   before: the tracker's pivots were a 3-bar rolling minimum, which fires on a third of all bars, so
   every live gap was discarded before it could reach the 7-bar minimum inversion age — the arm
   produced **one trade in ten years**.
2. **The edge is in the entry, not the payoff.** The RR sweep (1:1 → 1:4) moves gross E[R] inside a
   band of **0.008 R**; the doc's **NY killzone** moves it by **+0.049 R** and the **checklist** by
   **+0.015 R**; widening the stop *destroys* it (−0.068 R at 3×). The reference's 1:2 target was
   never the problem. The killzone was itself a fourth engine defect — the bar gate was only built
   for the vectorised scanner, so the leg tracker ignored it entirely.
3. **The meta-labeler has no out-of-sample signal.** `auc_test` was 0.47–0.53 across 120 monthly
   folds. It does *raise* the reference arm's gross expectancy (+0.0317 → +0.0511 R) by selecting the
   better setups, but on 705 trades that is no longer significant.

With the killzone and the checklist the arm becomes **net-positive** (E[R] net **+0.047**, PF_net
**1.070**, t = 2.48, four of the five years positive) — but the best deflated-Sharpe p-value over
the ~60 arms tried is **0.067**, so this is a hypothesis, not a result. It needs a pre-registered
forward test.

**The vision layer works, and the project's own audit of it was wrong.** `VISION_AUDIT.md` asserted —
from a *static* reading of the checkpoint, without ever running the model — that the detector's boxes
wrap the third candle's body and that the doc's `IoU > 0.75` gate was unreachable by construction.
Measured: **336/348** boxes land on a rule-engine FVG's middle bar, the class matches the gap's
direction in 96.1 %, and the vertical IoU against the **gap interval** has a median of **0.9518**.
The boxes wrap the *gap*. The **detector's confidence** is then a real filter (win% 35.2 vs 30.7,
E[R] +0.055 vs −0.079, **z = +2.26**) — the first significant discriminator that is neither the
session nor the checklist.

Full report with every figure parsed from the executed output:
[research/audit/PHASE1_REPORT.md](research/audit/PHASE1_REPORT.md).

---

## Earlier findings

**The first falsification test found no edge.** On **2,046,240 real BTCUSDT 1-minute bars**
(2023-01-01 → 2026-11-21, gap-free), with **one position at a time**:

| | n | expectancy | PF | t | 95 % CI |
|---|---|---|---|---|---|
| census (one position per candidate) | 423,759 | +0.033 R | 1.051 | 15.28 | [+0.029, +0.038] |
| **one position at a time** | **15,928** | **−0.020 R** | **0.971** | **−1.76** | [−0.042, +0.002] |

Across 32 pre-registered arms the one-at-a-time expectancy spans **−0.024 R … +0.014 R**, **every CI
includes zero**, and **PF never exceeds 1.051** against the design doc's **> 1.25** gate. With a 0.05 R
round trip, every arm is negative.

> ⚠️ The census row is the trap: counting 423,759 *simultaneously open, mutually correlated* positions as
> independent bets manufactures a t of 15.28. **Always quote significance from the one-position-at-a-time arm.**

**The vision gate as written is unreachable.** The detector's annotations wrap the **candle body**, which
is **disjoint** from the FVG *gap*, so a perfect detection scores **IoU = 0.00** against the doc's
1-D vertical metric (measured: median 0.0000, 87.9 % exactly zero). The layer must be re-specified as a
**body-box IoU**, and the model needs a **white 640×640** render, not the doc's black 224×224.

**The grade system exists nowhere.** "A/A+ only" — the phase-1 population filter — has no implementable
definition, so that gate is currently not a computable test.

---

## Data

The governed data lake lives on **NFS** (the SMB share rejects every credential):

```bash
sudo mount -t nfs -o rw,vers=3,proto=tcp fnos2.local:/fs/1000/nfs ~/iflow_lake
# canonical lake: ~/iflow_lake/iflow/database/
```

| Asset | 1-minute | Multi-year lane |
|---|---|---|
| BTCUSDT | 2,046,240 bars, 2023-01-01 → 2026-11-21, 0 gaps | 15m from 2024-01; `bar_ofi` 1m from 2023-01 |
| ETHUSDT | 2,046,240 bars, 2023-01-01 → 2026-11-21, 0 gaps | 15m from 2020-01 |
| **NQ** | **3,664,241 bars, 2015-01-01 → 2025-07-25** (Hugging Face) | 1h from 2024-05; 1d from 2021-10 |
| **ES** | **646,948 bars, 2020-11-17 → 2024-07-19** (Hugging Face, 55 % weekday coverage) | 1h from 2024-05; 1d from 2021-10 |
| GC | 7,714 bars — **one week only** | 1h from 2024-05; 1d from 2021-10 |
| QQQ | 2,428 bars | **15m from 2022-10** (73,325 bars) |
| VXN (CBOE official) | 4,327 daily bars, 2009 → 2026 | — |
| Funding rate (BTC/ETH) | 4,200 prints each | — |

**Multi-year NQ/ES 1-minute history does *not* require a paid feed.** The earlier claim (that only
Databento has it) was wrong — it was based on Yahoo, Twelve Data and cryptohftdata. Two Hugging Face
datasets carry it: `mdelcristo/NQ-F_1min_OHLCV_Parquet` (NQ, one parquet per year, 2015–2025) and
`Khanhpham1992/es-futures-1m` → `es_continuous_1m.parquet` (ES, with the publisher's `instrument_id`
per bar). `scripts/fetch_hf_futures_1m.sh` pulls them; `scripts/ingest_futures_1m.py` writes them
into the lake.

**The continuous series is rolled, and the roll must be handled.** The NQ publisher splices the
series at the quarterly expiry: at **37 of the 44** expiries in 2015–2025 there is a 1-minute move of
0.15 %–1.76 % against a 1-minute sigma of 0.030 % (5–58 σ). Those moves are synthetic and are the
exact shape of a liquidity sweep, so they must not be traded. `scripts/ingest_futures_1m.py`
**detects** the splice (the largest 1-minute move near each expiry) and flags ±60 minutes around it
as `roll_masked = 1` — the bars are flagged, not deleted: 0.169 % of NQ, 0.300 % of ES.

---

## Repository layout

```
AGENTS.md                  # Repository Guidelines — read this first
.herd-swarm/decisions.md   # the captain's design record: frozen contracts
.field-guide/              # append-only log of environment quirks and hard-won facts
research/
  docs/RULE_SPEC.md        # the strategy's rules, threshold provenance, ambiguity register
  analysis/                # PINE_RULES, VISION_AUDIT, ML_REUSE, DATA_FEASIBILITY, DATA_ACQUISITION
  audit/AUDIT.md           # independent cross-audit of all of the above
  nautilus/NAUTILUS_API.md # verified NautilusTrader 1.221.0 API map
  experiments/             # the falsification test and its results
```

`research/github/`, `research/huggingface/` and `research/kaggle/` hold the fetched upstream artefacts and
are **gitignored** (large binaries). `.field-guide/sources.md` records exactly how to re-fetch each one.

---

## Running the falsification test

```bash
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
$PY research/experiments/e1_rule_falsification.py --cost-r 0.05
$PY research/experiments/e1_rule_falsification.py \
    --data ~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet \
    --cost-r 0.05
```

---

## Running phase 1 on NQ

```bash
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
LAKE=~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake
# the vision layer has its own env: the uv runtime interpreter is externally managed

# 1. fetch + ingest (the roll splice is detected and flagged, not deleted)
bash scripts/fetch_hf_futures_1m.sh
$PY scripts/ingest_futures_1m.py --symbol NQ --root research/hf_futures
$PY scripts/ingest_futures_1m.py --symbol ES --root research/hf_futures

# 2. audit the stored files against the lake's five mathematical invariants
$PY scripts/audit_lake_dataset.py --path $LAKE/us_futures/NQ/1m/NQ_1m.parquet

# 3. the rule engine, rule-only (one position at a time)
$PY -m dodgys_dd_quant.backtest.runner --symbol NQ --timeframe 1m --preset pine \
    --cost-profile nq --slippage-ticks 1 --inversion-window doc --regime vxn \
    --reference-symbol ES --no-write-candidates

# 4. the meta-labeler, then the gated walk-forward
.venv-ml/bin/python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler \
    --candidates data/candidates/NQ_1m_pine.parquet \
    --bars $LAKE/us_futures/NQ/1m/NQ_1m.parquet --run-root artifacts_pine
$PY -m dodgys_dd_quant.backtest.runner --symbol NQ --timeframe 1m --preset pine \
    --cost-profile nq --slippage-ticks 1 --inversion-window doc --regime vxn \
    --reference-symbol ES --models-root artifacts_pine --no-write-candidates

# 5. the vision layer (its own env: torch + ultralytics; no GPU here, 0.45 s/candidate)
.venv-vision/bin/python scripts/vision_signals.py \
    --candidates data/candidates/NQ_1m_pine_kz.parquet \
    --bars $LAKE/us_futures/NQ/1m/NQ_1m.parquet \
    --out data/candidates/NQ_1m_kz_vision.parquet
.venv-vision/bin/python scripts/analyze_vision_signal.py \
    --candidates data/candidates/NQ_1m_pine.parquet \
    --vision data/candidates/NQ_1m_vision.parquet

# 6. re-render the report from the executed output
$PY scripts/render_phase1_report.py
```

The presets are `honest` (the vectorised scanner), `pine` (the reference-faithful leg tracker +
BE-intact gate), `pine_leg` / `pine_be` (its ablations) and `doc` (the design doc's rules).

---

## Ground rules

1. **Rules decide direction; ML filters; RL manages.** The four-layer contract is not negotiable.
2. **Never erase a losing setup.** "Hide Losing Setups" is banned — every candidate is persisted with its
   outcome.
3. **No look-ahead.** Every exogenous series is lagged; a decision may not use the close of the bar it
   fires on.
4. **A backtest holds at most one position at a time**, and significance is quoted from that arm.
5. **Costs live in the config**, never in strategy logic, and are always reported at 0/1/2 ticks with the
   break-even cost in R.
6. **A negative result is a result.** Phase 2 must not start until the pure-rule phase passes.

---

## Licence

Research code and documentation in this repository: MIT. The upstream artefacts under
`research/github/`, `research/huggingface/` and `research/kaggle/` keep their own licences — notably
`cantolab/IFVG-Ultimate-Dodgy` (MIT), `ibtsam/nq-fvg-detector` (AGPL-3.0) and `microsoft/qlib` (MIT).
