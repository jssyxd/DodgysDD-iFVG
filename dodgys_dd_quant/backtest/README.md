# `dodgys_dd_quant.backtest` — the end-to-end rolling backtest

This package decides **how trades are accounted for**, never *what* to trade.
The rule engine lives in `dodgys_dd_quant.strategy`.

```
dodgys_dd_quant/backtest/
├── cost_model.py   fees and slippage, isolated (D9)
├── walk_forward.py the rolling harness: folds, the forward-only check, the portfolio, the DSR
└── runner.py       the command-line entry point
```

---

## 1. Run it

```bash
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11

# the headline: the full governed BTCUSDT 1-minute sample
$PY -m dodgys_dd_quant.backtest.runner \
    --symbol BTCUSDT --timeframe 1m \
    --from 2023-01-01 --to 2026-11-21 \
    --cost-profile binance --slippage-ticks 1 \
    --preset honest --regime vxn --reference-symbol ETHUSDT \
    --candidates-out data/candidates/BTCUSDT_1m.parquet

# the D4-equivalent arm: the experiment harness's accounting
$PY -m dodgys_dd_quant.backtest.runner \
    --symbol BTCUSDT --preset e1 --portfolio defer --cost-profile binance

# the doc's rules (ATR floor + sweep precondition + killzone)
$PY -m dodgys_dd_quant.backtest.runner --symbol BTCUSDT --preset doc

# the reference's leg tracker + BE-intact gate
$PY -m dodgys_dd_quant.backtest.runner --symbol BTCUSDT --preset pine
```

The data is resolved from the **NFS lake** (`~/iflow_lake/...`, authoritative) and
falls back to the local checkout (`/home/da/桌面/database/...`).  The lake is
**read-only** for this package (D10).

Useful flags: `--preset {e1,honest,pine,doc}`, `--portfolio {drop,defer}`,
`--inversion-window {code,doc}`, `--regime {none,vxn,dvol}`,
`--reference-symbol`, `--threshold`, `--trials`, `--limit`.

---

## 2. The three rules the harness never breaks

### 2.1 One position at a time (D4)

The experiment harness's **census** arm opens one position per candidate: on
2 046 240 BTCUSDT 1-minute bars that is **423 759 simultaneously-open,
correlated positions**, and its `t = 15.28` is an artefact, not a result.

Every number printed here comes from a portfolio that holds **at most one
position at a time**.  Two accountings are implemented and both are reported:

| mode | behaviour of a signal that arrives while a position is open |
|---|---|
| `drop` (default) | the signal is **discarded** — what a real portfolio does (L2 §A.4) |
| `defer` | the signal stays **pending** and may trigger later, at a different price — the experiment harness's queue (D-17) |

The `defer` arm is the only one comparable to the published D4 baseline, and it
reproduces it **exactly** (see §5).

### 2.2 Forward only (D3)

A model with `asof = T` may only decide trades with `ts_event > T`.  The rule is
a **hard check that raises** (`ForwardOnlyViolation`), not a warning.  It fires
inside the walk-forward loop for every candidate a fold scores, and the unit
tests prove it fires.

### 2.3 Costs live here, not in the strategy (D9)

Fees and slippage are in `cost_model.py` only.  The round-trip cost is charged
**inside** the trade, and every report prints the **break-even round-trip cost
in R** next to the expectancy.

| profile | tick | multiplier | fee | 0 / 1 / 2 ticks |
|---|---|---|---|---|
| `nq` | 0.25 pt = $5.00 | $20 | $4.50 | $9.50 / $14.50 / $19.50 |
| `mes` | 0.25 pt = $1.25 | $5 | $2.25 | $3.50 / $4.75 / $6.00 |
| `es` | 0.25 pt = $12.50 | $50 | $4.50 | $17.00 / $29.50 / $42.00 |
| `binance` | 0.10 | 1 | 0.04 %/side | 0.08 % + 0 / 0.10 / 0.20 |

The D9 ladder ($9.50 / $14.50 / $19.50) only reproduces with **one tick of
crossing cost already inside the baseline** ($4.50 + 1 × $5.00 = $9.50), which
is what a market order at the open actually pays.  The percentage profile
already contains the exchange's own crossing in the taker fee, so its baseline
is zero.

**The cost in R is the number that matters.**  The risk unit is the stop
distance; on 1-minute crypto that is a few tenths of a percent of the price,
while the Binance taker fee is 0.08 % of the notional.  The measured mean
round-trip cost on BTCUSDT 1-minute is therefore **0.41 – 1.54 R per trade**,
i.e. several times the entire gross edge.

---

## 3. The walk-forward

* The folds come from the ML leaf's `artifacts/models/{symbol}/walk_forward_index.json`
  (D3).  The reader is deliberately tolerant: a bare list or `{"folds": [...]}`
  is accepted, and the fold entries may carry `asof` / `dir` / `test_start` …
  keys.  The index format is **not** frozen beyond "the ordered list of fold
  directories", so this is an assumption, not a contract.
* Each fold's model decides **only the candidates of its own test window**, and
  only the ones with `P(Win) >= 0.58` are traded.
* **No model ⇒ rule-only baseline**, and the period is labelled `rule_only` in
  the report.  Nothing is silently pretended.
* Per fold the report gives: n candidates, n approved, n trades, win rate,
  expectancy **gross and net of costs**, PF, a 95 % CI, the model window and
  the **prediction-drift** metric.

### Prediction drift

The D3 artefact stores counts, not the training prediction distribution, so the
drift is measured against the **training base rate**
`positives_train / n_train`:

| metric | meaning |
|---|---|
| `train_base_rate` | the training win rate |
| `live_mean_p` | the mean `P(Win)` the model produced out of sample |
| `live_realised_win_rate` | the realised win rate of the approved trades |
| `mean_p_minus_base` | the model's own drift |
| `realised_minus_base` | the drift that actually costs money |

**Gap:** the artefact does not carry the training *prediction* distribution, so
the drift can only be measured against a base rate.  A KS distance would need
the training scores to be stored in `meta_label_meta.json`.

### Stitching and the multiple-testing correction

The folds' equity curves are concatenated into one series.  The **deflated
Sharpe** (Bailey & López de Prado) is reported next to the raw Sharpe:

```
SR0   = sqrt(V) * ((1-g) Z^-1(1 - 1/N) + g Z^-1(1 - 1/(N e)))
DSR   = Phi( (SR - SR0) sqrt(T-1) / sqrt(1 - g3*SR + (g4-1)/4*SR^2) )
```

`N` is the number of independent trials — **32** by default, because 32 arms
have already been tried (D4).  The DSR p-value is the probability that the
observed Sharpe is a multiple-testing artefact.

---

## 4. The candidate log (D2)

The candidate log is written to the **frozen D2 schema**, column for column:

```
ts_event symbol side entry_price stop_price target_price risk fvg_low fvg_high
fvg_bar1 fvg_bar3 confirm_bar bars_to_inversion minutes_from_us_open
checklist_score smt_divergence sweep_detected vxn_known vxn_regime
vision_iou vision_confidence label r_multiple
```

* **Every candidate is kept**, including the losers and the ones that never
  resolved (`label = -1`).  Nothing is erased (INV4); the upstream indicator's
  `hideLosing` behaviour is banned.
* `label` / `r_multiple` are the **outcome join**: the trade each candidate
  *would* have produced on its own.  The portfolio then **selects** a subset of
  those rows; the outcome of a selected row does not change.
* `vision_iou` / `vision_confidence` are always `NaN`: the vision layer does not
  exist (D12) and its metric was replaced (D6).
* `checklist_score` is the sum of the doc's **five named conditions** (D8).  It
  is **reported, never used as a filter**; the distribution is printed in every
  report.
* `smt_divergence` is `-1` when no reference instrument is available — never a
  guess.

**Path.**  D2 names `research/candidates/{symbol}_{timeframe}.parquet`, but
`research/**` is read-only for this leaf, so the default output is
`data/candidates/{symbol}_{timeframe}.parquet` (gitignored).  The file can be
moved to the D2 path by whoever owns `research/`.

---

## 5. Measured results (BTCUSDT 1-minute, 2 046 240 bars, 2023-01-01 → 2026-11-21)

Cost profile `binance`, 1 tick of slippage.  "Gross" is before any cost.

| arm | candidates | trades | win % | E[R] gross | PF gross | **PF net** | t | 95 % CI | mean cost | E[R] net | break-even cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `e1` (defer, **D4 accounting**) | 423 770 | 15 929 | 32.7 % | **−0.0197** | **0.971** | **0.548** | −1.76 | [−0.042, +0.002] | 0.413 R | −0.433 | −0.020 R |
| `honest` (drop) | 423 770 | 42 093 | 33.6 % | **+0.0087** | **1.013** | **0.340** | +1.26 | [−0.005, +0.022] | 0.830 R | −0.821 | +0.009 R |
| `pine` (leg tracker, drop) | 5 029 | 4 951 | 19.8 % | **−0.4062** | **0.494** | **0.075** | −23.91 | [−0.439, −0.373] | 1.542 R | −1.948 | −0.406 R |
| `doc` (ATR+sweep+killzone, drop) | 14 743 | 6 804 | 33.8 % | **+0.0147** | **1.022** | **0.350** | +0.85 | [−0.019, +0.048] | 0.805 R | −0.791 | +0.015 R |

`PF net` is the profit factor with the round-trip cost charged **inside** every
trade (D9); `PF gross` is the cost-free figure the experiment harness reports.

### 5.1 The engine reproduces the D4 baseline exactly

The `e1`/`defer` arm is **bit-identical** to
`research/experiments/e1_rule_falsification.py` on the same data:

```
mine : n=15 928  win=32.7%  E[R]=-0.0197  PF=0.971  t=-1.76  CI95=[-0.042,+0.002]  maxL=22
E-1  : n=15 928  win=32.7%  E[R]=-0.020   PF=0.971  t=-1.76  CI95=[-0.042,+0.002]  maxL=22
```

The trade-by-trade sequence (entry bar, entry, stop, target, outcome) was
compared and is **identical** over a 120 000-bar sample.  The census agrees
too: 423 759 closed concurrent trades, exactly E-1's number.

### 5.2 Nothing beats the baseline

* The `honest` arm's **gross** E[R] of +0.0087 is nominally above the baseline's
  −0.0197, but the 95 % CI is [−0.005, +0.022] — it **includes zero**, it is a
  *different* trade population (drop vs defer ⇒ 42 093 vs 15 929 trades), and it
  is **deeply negative after costs** (−0.82 R per trade).
* The `doc` arm (ATR floor + sweep precondition + killzone) has the best
  *gross* expectancy of the four (+0.0147 R) and the tightest population
  (14 743 candidates), but its CI [−0.019, +0.048] includes zero and its PF
  (1.022) is far below the design doc's **> 1.25** gate.
* The `pine` arm (the reference's leg tracker + BE-intact gate) is
  **catastrophically negative**: E[R] = −0.406, PF = 0.494, t = −23.9.  It also
  produces **84× fewer candidates** (5 029 vs 423 770).  The reference's
  leg machinery does not merely re-select a subset — it produces a different
  and much worse population.
* No arm has a gross PF above 1.03, and **no arm has a net PF above 0.55**.
  The doc's phase-1 gate is PF > 1.25 *after* costs; the gross edge is
  ≤ 0.015 R while the break-even cost is 0.41–1.54 R.  **The edge is 20–100×
  smaller than the cost of trading it.**

### 5.3 The cost dominates, and it is structural

On 1-minute crypto the stop distance is a few tenths of a percent of the
price, so a 0.08 % round-trip taker fee is **0.4–1.5 R**.  The gross edge is
≤ 0.015 R.  No filter can fix that: the doc's own filters reduce the
population by 30× and move the gross expectancy by +0.006 R.

This is the same conclusion D4 reached from the other direction, now measured
with an engine that reproduces the baseline exactly and with the cost model
wired inside the trade.

---

## 6. Known gaps and open questions

1. **The `walk_forward_index.json` format is assumed, not contracted.**  D3
   freezes the artefact, not the index schema.  The reader accepts a bare list
   or `{"folds": [...]}` with `asof`/`dir`/`test_start`/`test_end` keys.  If
   the ML leaf writes a different shape, the reader must be adjusted (or the
   index schema frozen in D3).
2. **The training prediction distribution is not in the artefact**, so the
   prediction-drift metric can only use the training base rate (§3).
3. **`lightgbm` is not installed** for the 3.11 interpreter, so the model
   scoring path could not be executed end-to-end against a real artefact.  The
   scorer degrades explicitly (`available = False` ⇒ the fold runs rule-only
   and says so); it never pretends a model ran.  The ML leaf owns the model.
4. **`SERIES` mode of the reference's candidate arbitration is not implemented**
   (only `Single`).
5. **The `pine` arm's origin semantics are one of two readings** (L2 §E-1):
   the origin is the swing extreme itself.  The reference's own code takes the
   bar *before* the extreme; the two readings give different break-even levels.
6. **The reference's pivot predicate may be inert in Pine v6.**
   `ta.lowestbars(3) == -1` (`pine:L350`) is the v4 idiom for "a new 3-bar
   low"; in v5/v6 `ta.lowestbars` returns the in-window offset, so the test is
   false for any non-`na` series.  If that is right, the published replica
   creates **no candidates at all**, and the `pine` arm above is the author's
   *intent*, not the replica's behaviour.  This is a research question for the
   captain, not something this leaf can settle; the `pine` arm is labelled
   accordingly.
7. **PDH/PDL uses the calendar day in `America/New_York`**, not the CME Globex
   day (18:00 ET → 17:00 ET).  The doc never defines "previous day" (L2 §C.3).
8. **VIX and GVZ are not ingested** (D5).  MES's regime layer needs VIX and
   GC's needs GVZ before the regime column can be used on those markets.  The
   index is pluggable (`RegimeIndex`), and `DvolRegimeIndex` exists for crypto,
   but its bands are **not specified by the doc** and must be calibrated.
9. **The candidate log's `label` is the standalone outcome**, not the outcome
   inside the portfolio.  The two coincide for every selected row (the
   portfolio only selects), but a reader that joins the portfolio trades back
   to the log must not assume the log contains only traded setups.
