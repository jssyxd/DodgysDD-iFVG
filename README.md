# DodgysDD iFVG — positive-EV quantitative system

A research-and-build repository for the **DodgysDD "Inversion Fair Value Gap" (iFVG)** trading strategy,
targeting **NautilusTrader** as the single backtest and live engine.

> **Status: research complete, the four layers are built and verified — and they still show no edge.**
> The strategy's rules are specified and independently audited; the implementation
> (`dodgys_dd_quant/`) exists and is covered by **139 executable probes** over the real numbers
> (`bash autoresearch.sh`). The falsification test on real 1-minute data found **no edge**, and the
> re-measured one-position-at-a-time arm still shows none: the rule-only arm is **32,521 trades,
> E[R] −0.0183 R gross, PF 0.973, t = −2.34** — it loses before costs. See
> [Current findings](#current-findings) and `AGENTS.md`.

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
| NQ / ES / GC | 7,490 / 7,489 / 7,714 bars — **one week only** | 1h from 2024-05; 1d from 2021-10 |
| QQQ | 2,428 bars | **15m from 2022-10** (73,325 bars) |
| VXN (CBOE official) | 4,327 daily bars, 2009 → 2026 | — |
| Funding rate (BTC/ETH) | 4,200 prints each | — |

**The binding constraint on this project is data, not models.** Multi-year NQ/ES 1-minute history
requires a paid feed (**Databento**, ~$10–30) — Yahoo serves ~1–2 days of 1-minute from this host,
cryptohftdata has no candle family, OKX needs ~14,000 requests per symbol, and Twelve Data's lake
mirror is an *equities* dataset with no NQ/ES at all.

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
