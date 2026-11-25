Strategy versions: what can be obtained, and what data each one needs
=====================================================================

Scope
-----
This note inventories the DodgysDD iFVG implementations named in the brief,
records what could actually be obtained (verified, not assumed), and answers
the operational question: **what data level does each version need for a
backtest and for training**?  It then tests the executable versions on the
same data and the same costs.

1. Acquisition status
---------------------
| version | source | status | what exists locally |
|---|---|---|---|
| **iFVG Ultimate+ / Deluxe** (TakingProphets × DodgysDD) | TradingView, invite-only | **not obtainable** (closed source, no backtest engine) | nothing; the behaviour is known only through videos and the replica |
| **cantolab / IFVG-Ultimate-Dodgy** | GitHub, MIT | **obtained** | `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` (31 KB, Pine v6) + README |
| **FVG / IFVG ATR RR Strategy - Fixed** (yoanybx / Joan Barrios) | TradingView | **not obtainable**: the page says `PROTECTED SOURCE SCRIPT` (verified 2026-11-23 at `tradingview.com/script/EK7GJg11-...`) — the brief's "open-source strategy()" is wrong | only the published feature list |
| **this repository's engine** | local | 4 executable presets: `e1`, `honest`, `pine`, `doc` | `dodgys_dd_quant/strategy/state_machine.py` |

The two obtainable artefacts are therefore the **replica** (rules) and the
**presets** (our own executable versions).  The ATR-RR script can only be
analysed from its description.

2. What each version actually computes (from its own code/description)
---------------------------------------------------------------------
**Replica (`ifvgUltimatePlus.pine`, Pine v6, `indicator()`):**
* single/continuous iFVG detection on the **chart timeframe**, three-candle gap,
  wick geometry, strict inequality;
* inversion window `graceCandles = allowExtIFVG ? 15 : 6` (upper bound only);
* break-even level = swing origin of the leg that produced the gap; the
  reference closes the trade there, and `requireBEIntact` *hides* setups whose
  confirmation candle already reached BE;
* HTF: `request.security(tickerid, htfFvgTF, [high[1], low[1], high[3],
  low[3], time[2]], lookahead = barmerge.lookahead_off)` with the auto map
  `1→15, 3→30, 5→60, 15→240, 60→1D, 240→1W, 1D→1M`;
* sessions are **alert-only** (`time(timeframe.period, session, NY_TZ)` gates
  the alert, not the setup);
* `max_bars_back = 5000`;
* `hideLosing = true` by default: invalidated setups are **deleted from the
  chart after the fact** — the indicator's visible history is not a sample.

**ATR-RR strategy (description only):** 3-candle FVG; IFVG when price closes
beyond the opposite side; optional retest entry; minimum FVG size; ATR-based
or fixed RR take-profit; contracts; direction filter; inverse-position mode;
session filter; daily zone lifecycle.  Structurally this is our `doc` preset
(ATR floor + session + fixed RR), not the replica.

3. The data level each version needs
------------------------------------
| requirement | why | consequence |
|---|---|---|
| **signal bars at the trading timeframe** | every rule reads OHLC at bar close; the replica is timeframe-agnostic, the doc says 1–15 minutes | at 1m the fee is 1.5 × a 1-ATR stop on Binance; at 15m it is 0.29 × (measured) — the timeframe, not the rules, decides the sign |
| **intrabar path for the outcome** | "did the stop or the break-even level come first inside the bar" is undecidable from OHLC | 15m resolution on 15m bars collapses the `pine` preset (measured below); 1m execution changes the result by ~0.01 R; ticks are the only complete answer |
| **HTF bars built by time aggregation** | `request.security(..., lookahead_off)` consumes 15/60/240-minute bars | must be aggregated, not approximated by a rolling window; our `HTFZones` does exactly this |
| **session-aware timestamps** | `time(..., NY_TZ)` and the doc's killzones need DST-correct wall clock | a naive UTC boundary shifts by one hour twice a year (the repo's timezone bug was five hours) |
| **enough history for the fold geometry** | 6/1/1 monthly folds + a 60-hour label horizon need ~8 months minimum, 3+ years for regime coverage | ETH 15m 2020-2026 (239,520 bars) suffices; NQ/ES 15m does **not** exist in the lake (one week) |
| **per-contract futures data + a roll rule** | a roll leaves a price gap that the rule engine reads as a liquidity sweep | without per-contract data the NQ test needs a roll mask, or the "sweep" is an artefact |
| **cost model at the instrument's scale** | the verdict is cost-dominated | Binance 0.08 % → 0.111 R at 15m; CME $4.50 → 0.016 R at 15m |

**Answer to "what level of data is required":** signal OHLC at **5–15
minutes**, an **HTF series** aggregated from it, **1-minute or tick** bars for
the outcome, DST-correct session metadata, three or more years for training,
and per-contract futures data with a roll mask.  1-minute bars are an
*execution* series, not a decision series.

4. Version tests on the same data (ETHUSDT 15m, 2023-01 → 2026-10)
-----------------------------------------------------------------
DVOL regime, Binance cost, 1 tick, one position at a time, 60-hour horizon,
6,570 candidates.  Command shape::

  python -m dodgys_dd_quant.backtest.runner --symbol ETHUSDT --timeframe 15m \
      --regime dvol --reference-symbol BTCUSDT --cost-profile binance \
      --slippage-ticks 1 --horizon-minutes 3600 --from 2023-01-01 \
      --preset <preset> --no-write-candidates

| preset | what it is | n | win% | E[R] gross | E_net | PF | t |
|---|---|---|---|---|---|---|---|
| `e1` | the E-1 code-derived core (no ATR floor, no sweep gate) | 1,975 | 35.6 | +0.0392 | -0.0823 | 1.061 | 1.23 |
| `honest` | same signals, the reference's look-ahead removed | 1,975 | 35.6 | +0.0392 | -0.0837 | 1.061 | 1.23 |
| `pine` | the reference's machinery (BE exit, leg tracker, BE-intact gate) | 114 | 19.3 | **-0.4123** | -0.7083 | 0.489 | -3.63 |
| `doc` | ATR gap floor + the doc's filters | 354 | 37.3 | +0.1017 | **+0.0159** | 1.162 | 1.32 |

Reading:

* The **doc's ATR floor** is the only filter that turns the net expectancy
  positive on this sample — but n = 354 and t = 1.32: the confidence interval
  [-0.050, +0.253] contains zero.  It is a lead, not a result.
* The **reference-faithful** arm collapses (19.3 % win rate).  Its break-even
  exit is resolved on the same bar series that produced the setup, so the
  "BE was hit first" decision is a tie-break artefact — precisely the class of
  error the execution-series resolver (section 5) exists to remove.  Do not
  quote `pine` as "the strategy's" performance until it is re-run on 1m/tick
  execution.
* `e1` and `honest` are identical here because the two differences (entry fill,
  portfolio accounting) do not bite on this sample.

5. What changed in the engine for this (implemented, tested)
------------------------------------------------------------
* `--horizon-minutes`: the holding period is now a **time**, converted to the
  scanned series' bar count (the 240-bar constant meant 4 h at 1m and 60 h at
  15m; that silent drift is gone).
* `--execution-data` + `backtest/execution.py`: the outcome (stop vs target vs
  censored) is resolved on a finer series, with the exit bar mapped back to
  signal-bar space.  The signal series is clipped to the execution window so
  no candidate can be resolved against a different era (the first version
  did, and manufactured t = 35).
* `--gate quantile`: the meta-label gate takes each fold's **validation-fold
  quantile** instead of a fixed 0.58, and the trainer now stores an isotonic
  calibration fitted on the validation fold.

Measured effect of the three fixes (same ETH 15m window):

| config | n | win% | E[R] | t | E_net |
|---|---|---|---|---|---|
| 60 h horizon, 15m resolution (rule-only) | 1,975 | 35.6 | +0.0392 | 1.23 | -0.0837 |
| 8 h horizon, 15m resolution | 2,245 | 32.8 | -0.0445 | -1.53 | -0.2093 |
| 60 h horizon, 1m execution | 2,048 | 35.3 | +0.0295 | 0.95 | -0.0948 |
| 8 h horizon, 1m execution | 2,308 | 31.8 | -0.0711 | -2.48 | -0.2379 |
| **ML gate, absolute 0.58** (60 h) | 196 | 35.2 | -0.0077 | -0.08 | -0.0939 |
| **ML gate, calibrated quantile** (60 h) | 435 | 35.2 | +0.0126 | 0.19 | -0.0908 |

* **Horizon dominates**: shortening the hold from 60 h to 8 h flips a +0.04 R
  edge to -0.07 R.  A 2R target with a 2.6-ATR stop on 15m needs days, which
  contradicts the doc's intraday premise — that contradiction is a design
  decision, not a bug.
* **Execution granularity is second order** (~0.01 R), because 15m bars rarely
  contain both barriers; the reference's break-even exit is the exception,
  where it is first order.
* **The calibrated gate no longer destroys the arm** (it admits ~5 % per fold
  instead of opening in bursts), but it still adds nothing: the model's AUC is
  0.50 and the gated expectancy is below the rule-only arm.

6. What the versions cannot tell us, and what data would
--------------------------------------------------------
Every obtainable version is a **crypto** test, and on crypto the fee is 0.11 R
at 15m while the best gross edge measured is 0.10 R.  The doc's own phase-1
gate is NQ/ES at $4.50, i.e. 0.016 R.  Until a multi-year NQ/ES 15m (or
1m/tick) lane exists — Databento, ~$10–30 — the question "does this strategy
have an edge" is **decidable only on the instrument whose costs do not decide
it**, and that instrument's data is the one thing missing.
