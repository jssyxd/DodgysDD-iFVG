# Leaf M2 — The rule engine, the regime layer, and the E2E rolling backtest (implementation)

## Context
Project: `/home/da/桌面/DodgysDD_ifvg` — the DodgysDD iFVG quant system on NautilusTrader.
This is an **implementation leaf**. You own exactly the paths listed below; you may not touch anything else.

**You are a worker, not an orchestrator.** Do not spawn other agents, do not run `herdr`/`herd-dispatch`,
do not edit `.herd-swarm/decisions.md`. If you need a decision that is not recorded there, **stop short of
guessing**: state the question in your deliverable and continue with everything else.

## Required reading (before you write a line)
- `.herd-swarm/decisions.md` — **D2** (the candidate-log schema you must **produce**), **D3** (the model
  artefact you must **consume**), **D4** (the honest baseline and the **one-position-at-a-time** accounting
  rule — this is the single most important thing you must not get wrong), **D5** (data reality),
  **D6** (the vision layer is a **body-IoU** cross-check and does not exist — the strategy must degrade
  gracefully without it), **D8** (no grade filtering), **D9** (cost model), **D10** (untracked corpus).
- `research/audit/L2_RULES.md` — **the conformance matrix you are implementing against.** It lists, for
  each rule, whether it is faithful / partial / absent and what is needed. Your job is to close the gaps.
- `research/analysis/PINE_RULES.md` — the rule-by-rule extraction from the reference Pine source, with the
  exact line numbers and Pine semantics (bar indexing, `close[1]` lag, the expiry rule, stop placement).
- `research/experiments/e1_rule_falsification.py` — the **existing** code-derived core. You will port and
  **extend** it; do not start from a blank page.
- `research/docs/RULE_SPEC.md` — the rule spec and its `[UNSPECIFIED]` register.
- `research/audit/L3_REGIME.md` / `L4_ROLLING.md` — if they exist when you start, read them (they are the
  specification for the regime layer and the backtest).
- `.field-guide/env.md`, `.field-guide/sources.md` — environment and data facts.

## Ownership (you may create/modify ONLY these)
```
dodgys_dd_quant/__init__.py            # shared with M1 — create it ONLY if absent; keep it empty of logic
dodgys_dd_quant/strategy/__init__.py
dodgys_dd_quant/strategy/constants.py
dodgys_dd_quant/strategy/structure.py
dodgys_dd_quant/strategy/state_machine.py
dodgys_dd_quant/strategy/regime.py
dodgys_dd_quant/backtest/__init__.py
dodgys_dd_quant/backtest/cost_model.py
dodgys_dd_quant/backtest/runner.py
dodgys_dd_quant/backtest/walk_forward.py
dodgys_dd_quant/backtest/README.md
tests/unit/test_state_machine.py
tests/unit/test_cost_model.py
tests/unit/test_walk_forward.py
```
Do **not** create `dodgys_dd_quant/ml_pipeline/**` — another leaf owns that. Do not modify `research/**`,
`AGENTS.md`, `README.md`, `.herd-swarm/**`, `.field-guide/**`.

## What to build

### 1. `constants.py` — one home for every threshold
Per `AGENTS.md`: all tunables in one module. Include at least
`MIN_GAP_ATR_MULT = 0.25`, `INVERSION_WINDOW = (1, 15)` (see the note below), `INVERSION_MIN_BARS`,
`INVERSION_MAX_BARS`, `DECISION_THRESHOLD = 0.58`, `KILLZONE_NY_AM`, `KILLZONE_NY_PM`,
`VXN_REGIME_BINS = (0.0, 18.0, 28.0, 200.0)`, `DEFAULT_RR = 2.0`, `MAX_SESSIONS`,
and the per-market parameter table from the doc's migration table (NQ/MNQ→ES, MES→NQ/RTY, QQQ→SPY/IWM,
GC→SI/DXY, BTC/ETH→each other), each with its own ATR coefficient, regime index and session windows.

> **Note on the inversion window.** Leaf L2 proved the lower bound of the code's window is **1, not 0**:
> age 0 is arithmetically impossible (a bullish FVG needs `low[c] > high[c-2]`, the age-0 trigger needs
> `close[c] < high[c-2]`, and `close[c] >= low[c]`). So the code-derived window is **(1, 15)** and the
> doc-derived one is **(7, 15)**. Expose both and A/B them; never hard-code 7.

### 2. `structure.py` — causal market structure
- Swing-point detection that is **causal**: a pivot at bar `p` may only be *used* from bar `p + right`.
  (The `xauusd-ml-trader` version uses a **centred** window — that is look-ahead; fix it, and say so.)
- `detect_liquidity_sweeps` with the doc's semantics: a **wick** pierces the level and the **body** closes
  back inside.
- **Consume sweep levels once**: the Pine removes a swept level from its set (pine:L560–575). Levels must
  not be re-swept.
- `detect_fvg` with the exact 3-candle geometry (strict, wick-based).
- `atr_wilder(period=14)` with an explicit warm-up (no signal before the series is warm).

### 3. `state_machine.py` — the rule engine
A **pure** function of the bar history (no I/O, no engine calls) that emits the **D2 candidate log**.
Close the gaps L2 identified: killzone gating (DST-aware, `America/New_York`), session high/low and
PDH/PDL tracking, the sweep gate (configurable — the reference has it OFF by default, the doc has it ON),
the ATR gap floor, the inversion window, the BE-intact gate, the stop placement (wick/body/IFVG), the
break-even level, the RR projection, and the checklist as **five named boolean checks** whose sum is
`checklist_score` — **reported, never used as a filter** (D8).
Where a rule needs the reference instrument (SMT), read it from a second, time-aligned series and record
`smt_divergence = -1` when it is unavailable — never guess.
**Write the candidate log to exactly the D2 schema.**

### 4. `regime.py` — the VXN/regime layer
- Load the governed VXN series (`~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/macro/vxn/VXN_1d_consolidated.parquet`)
  and produce `vxn_known` = the **previous** close (strictly lagged) and `vxn_regime` from
  `VXN_REGIME_BINS`.
- **The regime index must be knowable at decision time.** A daily VXN close is published after the cash
  close, so for an intraday trade on day D the only safe value is **day D−1's close**. Implement that and
  *test* it: no bar on day D may see day D's VXN close.
- Provide the regime-driven parameters the doc specifies (low vol → tighter filter + RR 1:1.5–1:2;
  normal → RR 1:2.5–1:3; high vol → halve risk, raise the ATR floor) as **configurable functions**, and
  state that the "tighten to A+ only" rule is **not implementable** (D8) and is therefore replaced by
  "tighten the ATR floor and the RR".
- **VIX is not ingested.** Make the regime index **pluggable** and document that MES's VIX and GC's GVZ
  still need sourcing.

### 5. `cost_model.py` — costs, isolated
Per D9: fees and slippage live here, never in strategy logic. Provide NQ/ES (tick 0.25 = $5, multiplier $20,
fee ≈ $4.50) and Binance USDT-M (0.04 %/side) profiles, a 0/1/2-tick slippage switch, and a function that
returns the round-trip cost **in R** given the trade's risk. The backtest must always report the
**break-even cost in R** next to the expectancy.

### 6. `walk_forward.py` — the E2E rolling backtest
- Walk forward over the folds the ML leaf produces (D3's `walk_forward_index.json`), and for each fold use
  **that fold's** model to decide that fold's trades.
- **The forward-only assertion:** a model with `asof = T` may only decide trades with `ts_event > T`.
  Implement it as a hard check that raises, and test it.
- **One position at a time** (D4). This is not optional: the census arm manufactures a t of 15.28.
- If no model exists for a period, run the **rule-only baseline** and label those periods as such.
- Per fold report: n candidates, n trades, win rate, expectancy in R **gross and net of costs**, PF,
  a 95 % CI, the model window, and the **prediction-drift** metric (the live P(Win) distribution vs the
  training distribution).
- Stitch the fold equity curves into one series and report the **deflated Sharpe** or equivalent
  multiple-testing correction (we have already tried 32 arms plus the concurrency artefact).

### 7. `runner.py` — the entry point
`python -m dodgys_dd_quant.backtest.runner --symbol BTCUSDT --timeframe 1m --from ... --to ... --cost-profile nq --slippage-ticks 1`
It must load the governed parquet from the NFS lake, build the candidates, run the walk-forward, and print
the report. It must work **end-to-end on the real data that exists** (BTCUSDT 1m, 2,046,240 bars).

## Tests (`tests/unit/`)
- `test_state_machine.py`: the FVG geometry, the inversion trigger on **closed** bars only, the expiry
  rule, the stop placement, and the one-position-at-a-time rule. Include a case that would fail if any
  look-ahead crept in.
- `test_cost_model.py`: the NQ and Binance profiles, and the break-even-cost-in-R computation.
- `test_walk_forward.py`: the forward-only assertion raises when violated, and the fold stitching is
  contiguous.
- Tests must not need the network. Where they need market data, generate it synthetically.

## Constraints
- Python **3.11**; the interpreter path is in `.field-guide/env.md`. Follow `AGENTS.md` conventions.
- **No look-ahead.** Prove it with tests. A rule engine that peeks is worse than no engine.
- Do not modify the frozen contracts (D2/D3). If you think one is wrong, say so and implement it anyway.
- **Do not fabricate results.** If the walk-forward on real data shows no edge, report that. Do not tune
  until the numbers look good, and do not filter on the checklist score to manufacture a population.
- The NFS lake is **shared** — read from it; write only to paths you own.

## Deliverable
Your final reply must state: what you built, the exact commands to run it, the test results, and **the
measured result of running the E2E backtest on the real BTCUSDT 1-minute data** — including the
expectancy net of costs, the PF, and whether it beats the D4 baseline. If you could not run it, say
exactly why. Name the files you created.
