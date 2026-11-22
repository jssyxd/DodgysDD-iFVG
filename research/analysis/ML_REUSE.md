# ML & Framework Reuse Assessment

**Scope.** Five external artifacts were downloaded and read at source (no execution, no installs):
`research/huggingface/xauusd-ml-trader/`, `research/github/AlphaGPT/`,
`research/github/AlphaGPT-By-imbue-bit/`, `research/github/qlib/`,
`research/huggingface/ict-6000-mentorship-master/`.
Binding constraints come from `AGENTS.md`: NautilusTrader is the **sole** backtest/live engine;
ML is a *filter*; RL is a *position manager*; thresholds live in one constants module; the rule
engine is a pure function of bar history; exogenous series must be lagged; every candidate setup
must be persisted with its outcome (no "Hide Losing Setups"); cost model lives in the backtest
config; **JSON-only config** (msgspec), no second config convention.

**Headline:** exactly one artifact is worth porting code from (`xauusd-ml-trader`, and only ~4 of
its 12 modules). Two are stale/duplicative. One is a checklist spec, not a detector. One is an
architectural dead end for our pipeline.

---

## A. `xauusd-ml-trader` — the primary reuse candidate

**Verdict: ADAPT.** Port 4 modules with edits into `dodgys_dd_quant/strategy/`, rewrite the entry
generator from scratch, discard the ML layer and the orchestrator.

### A.1 File tree and per-file responsibility

```
research/huggingface/xauusd-ml-trader/
├── requirements.txt                 # numpy>=1.24, pandas>=2.0, scikit-learn>=1.3, xgboost>=2.0,
│                                    # scipy>=1.11, yfinance>=0.2.30, river>=0.21, joblib>=1.3
├── README.md                        # claims "MIT License - See LICENSE file" — NO LICENSE FILE EXISTS
└── xauusd_trader/
    ├── __init__.py                  (17)
    ├── data_loader.py               (210)  yfinance loader, synthetic generator, ATR, session labels
    ├── main.py                      (718)  XAUUSDTradingSystem orchestrator + trade simulators
    ├── strategies/
    │   ├── smc_strategy.py          (439)  swing points, BOS, sweeps, order blocks, FVG, OB entry
    │   ├── ict_power_of_3.py        (273)  accumulation / manipulation / distribution (AMD)
    │   ├── momentum_strategy.py     (315)  RSI, Stochastics, MACD, Bollinger, EMA crossovers
    │   ├── sentiment_strategy.py    (206)  VIX/DXY/SPY/TLT risk-on score
    │   └── risk_management.py       (421)  RiskConfig, TradePosition, RiskManager, vol features
    ├── ml/
    │   └── ensemble_model.py        (491)  XGBoost 3-model ensemble, Hedge weights, ADWIN, labels
    └── backtesting/
        ├── wfo_engine.py            (313)  rolling walk-forward folds + trade metrics
        └── probability_best_fit.py  (307)  BIC distribution fit, Monte Carlo, hedge ensemble
```
Total ≈ 3,713 lines. `scipy`, `river`, `xgboost` and `yfinance` are used **only** by the ML/data
layers; a port that keeps only the SMC + risk core needs **pandas + numpy only**.

### A.2 The framework (what it actually is)

* **pandas + numpy**, not vectorbt, not backtrader, not an event loop. One `DataFrame`, one row per
  bar, feature columns computed in-place.
* The "backtest" is a **hand-rolled bar loop**: `RiskManager.update_positions()` walks the frame
  bar by bar, checking `current_low <= stop_loss` before `current_high >= take_profit` (pessimistic
  when both are hit in the same bar), and `main._simulate_strategy_trades()` /
  `main._generate_trades_from_predictions()` drive entries off signal columns.
* No fill model, no order book, no tick data, no partial fills, no contract specification.
* **Cost model is declared but not applied.** `BacktestConfig` defines `spread_pips=3.0`,
  `pip_value=0.01`, `commission_per_lot=0.0`, `slippage_pips=1.0`, but in the two trade-generation
  paths I read (`_simulate_strategy_trades`, `_generate_trades_from_predictions`) no fee or slippage
  is deducted, and `RiskManager.update_positions` exits at the exact SL/TP price. Their headline
  numbers (PF 2.09, Sharpe 5.34) are therefore **cost-free** and must not be quoted as a baseline.
  *(Confirm with a one-line grep before citing externally.)*

### A.3 Entry / exit logic as implemented

`generate_ob_entry_signals()` (in `strategies/smc_strategy.py`):

1. Maintain `active_bull_obs` / `active_bear_obs` (OB zones with `high`, `low`, `mid` = 50 % level).
2. **Bullish trigger:** `low <= ob['mid'] and close > ob['low']` **and** `market_structure == 'bullish'`.
   → `signal = +1`, `entry = ob['mid']`, `sl = ob['low'] - 0.5*ATR`, `risk = entry - sl`,
   `tp = entry + risk * 2.5`.
3. **Bearish trigger:** mirrored (`high >= mid and close < ob['high']` and bearish structure).
4. The OB is consumed on trigger and expires after 100 bars.
5. `confidence = min(1, 0.3*ob_strength + 0.2*liq_bonus + 0.3)` — an ad-hoc heuristic, not a
   probability.

Entry is therefore **"limit order at the OB midpoint, filled at the midpoint on the tap bar"** —
no fill realism, no partial fill, no rejection if price gaps through.

### A.4 Order-block entry

`detect_order_blocks()`: a bullish OB is the **last bearish candle before a bullish BOS** whose
body displacement ≥ `min_displacement_atr` (1.5) × ATR; `ob_50pct = (ob_high + ob_low) / 2`;
strength = `(displacement/ATR) × (ob_volume / mean_volume)`.

**Two defects that must not be copied:**
* *Look-ahead.* The OB flags are written at `idx_pos` — the **OB candle's own index**, i.e. *before*
  the displacement that creates it. `generate_ob_entry_signals()` then registers the OB when the
  loop reaches that index, so the strategy "knows" the order block several bars before it exists.
* *Volume semantics.* `ob['volume'] / df['volume'].mean()` is a spot/CFD concept; for NQ/ES it
  grades a tick-volume average, not liquidity.

**Verdict on order blocks: discard.** Our entry object is an inverted FVG, not an order block.

### A.5 Liquidity sweep and FVG imbalance — the two genuinely useful detectors

**`detect_liquidity_sweeps()`** — matches our Rule step 2 definition almost exactly:
* bullish sweep: `low < last_swing_low and close > last_swing_low` (wick pierces, body holds back);
* bearish sweep: `high > last_swing_high and close < last_swing_high`;
* `sweep_strength = (swept_depth / ATR)`.

**`detect_fvg()`** — the 3-candle imbalance, verified:
* bullish: `low[i] > high[i-2]` → gap `[high[i-2], low[i]]`;
* bearish: `high[i] < low[i-2]` → gap `[low[i-2], high[i]]`;
* `fvg_size` = gap width in price.

This is the *same* pattern our rule uses; what is missing is everything our rule adds on top:
**the ATR gap filter (`gap > 0.25 × ATR(14)`), the zone bookkeeping, the inversion state machine
(body close through the far edge within 7–15 bars), the retest entry, the checklist grading.**

**One look-ahead to fix in both.** `detect_swing_points()` uses a **centered** window: a swing high
at bar *i* is only confirmed *lookback* bars later (it needs `high[i+1..i+lookback]` to be lower).
`last_swing_low` is a forward-fill of that column, so at bar *i* the sweep detector may be testing
against a swing that only became knowable at bar *i+5*. **Every ported detector must be rewritten
as right-edge-free**: a swing is only visible `lookback` bars after it forms.

### A.6 Session filters

Two independent mechanisms, both wrong for our use:

1. `data_loader.add_session_labels()` — hard-codes `asian 00–08`, `london 08–13`, `ny 13–22`,
   `off_hours 22–24` from `df.index.hour`, and the docstring claims the hours are **UTC**. For the
   default ticker `GC=F` yfinance returns a **New York-localised** index, so the labels are actually
   New York hours wearing a UTC label. No DST handling, no zoneinfo, no instrument calendar.
2. `strategies/ict_power_of_3.py` — `detect_accumulation_range()` (Asian-session tight range
   < 0.8 × ATR), `detect_manipulation()` (false breakout of that range, wick out / body back in),
   `detect_distribution()` (displacement ≥ 1.0 × ATR in the opposite direction within 10 bars),
   `generate_amd_signals()` (entry on the distribution bar, SL 0.75 × ATR, TP 2.5 R).

Our killzones are **ET** (NY AM 09:30–11:30, NY PM 13:30–15:30) with US DST, and CME session
breaks. Neither mechanism is usable as written. The *concept* (session as a hard gate, manipulation
as a failed breakout) maps onto our Rule step 2 and can be re-derived from our own spec.

### A.7 Risk-management block

`strategies/risk_management.py` is the **most portable file in the whole corpus**:

* `RiskConfig` — capital, `max_risk_per_trade`, `max_position_pct`, `max_open_positions`,
  `max_daily_loss_pct`, `max_total_drawdown_pct`, `min/max_sl_atr_mult`,
  `guaranteed_stop_buffer`, `vol_scale_lookback/thresholds`, `session_risk_mult`, `dd_scale_levels`
  ladder (1 %→0.8, 2 %→0.6, 3 %→0.4, 5 %→0.2).
* `RiskManager.compute_position_size()` — fixed-fractional risk, multiplied by session multiplier,
  volatility-ratio multiplier (`high/ratio`, and up to 1.5× when vol is *below* threshold),
  confidence multiplier `0.5 + confidence`, and the first matching DD rung; then
  `size = risk_amount / stop_distance`, capped at `max_position_pct`.
* `RiskManager.validate_stop_loss()` — clamps the stop into `[0.5, 3.0] × ATR` around the entry.
* `RiskManager.update_positions()` — bar-by-bar bracket management, SL checked before TP.
* `RiskManager.get_risk_features()` — 8 risk-state features (drawdown, open positions, daily PnL %,
  halted flag, 50-trade win rate, avg R, consecutive losses) — directly usable as meta-label
  features.
* `compute_volatility_features()` — HV, Parkinson, Yang–Zhang, vol ratio, percentile regime,
  gap detection, range expansion/contraction.

It is pure Python + pandas, **no I/O, no engine calls, deterministic** → unit-testable exactly the
way `AGENTS.md` wants the rule engine to be.

**What must change:** it models a spot/CFD (per-unit size, no contract multiplier, no tick size,
no margin, no fee). For NQ we need `qty = risk_$ / (stop_distance_in_ticks × tick_value)` and the
cost model must move to the backtest config (AGENTS.md), not into the sizing code. Its
`open_position()` daily-loss check also compares `timestamp.date()` against `last_trade_date`
(which is set to the *entry* timestamp, not the last close) — a latent off-by-one-day bug.

### A.8 The ML layer — must NOT be reused

`ml/ensemble_model.py`:

* `create_labels()` builds a **3-class directional label** (`+1` buy / `0` hold / `-1` sell) from
  `close.shift(-forward_bars)` versus an ATR threshold. Our meta-label is **binary** and
  event-conditioned: the rule engine decides the direction, the classifier only answers "did this
  specific setup reach 2R before the stop" (`1` / `0`). A 3-class directional label is a *different
  product*: it would re-decide direction and re-introduce the "ML overrides the rule layer"
  violation of the four-layer contract.
* `prepare_features()` does `X.fillna(0)` globally — silent NaN scrubbing, forbidden by our
  "raise on data-integrity violations" convention.
* The ensemble is XGBoost (not LightGBM) with Hedge weighting and ADWIN drift detection;
  `river` is a hard dependency. We already have `lightgbm` planned.

**Verdict: discard the ML layer.**

### A.9 Conversion plan: OB-entry → DodgysDD iFVG entry

**Do not "port" the entry generator — replace it.** The OB entry and the iFVG entry are different
objects. What we port is the *pattern detectors*; the decision function is new.

**State machine (new, in `dodgys_dd_quant/strategy/state_machine.py`):**

```
IDLE
 └─ FVG forms at bar i:  bullish  → low[i]  > high[i-2] and (low[i]-high[i-2]) > 0.25*ATR(14)
                           bearish → high[i] < low[i-2]  and (low[i-2]-high[i]) > 0.25*ATR(14)
        zone_bull = (high[i-2], low[i])        zone_bear = (low[i-2], high[i])
        → FVG_ARMED(direction, zone, formed_idx=i)

FVG_ARMED
 └─ for j in (formed_idx+1 .. formed_idx+15):
      if j - formed_idx < 7: continue            # INVERSION_MIN_BARS = 7
      bullish FVG inverts when a candle's BODY CLOSE <= zone_bull.lower_edge (gap fully consumed)
      bearish FVG inverts when a candle's BODY CLOSE >= zone_bear.upper_edge
      wick penetration does NOT invert            (hard rule, per design doc)
      → INVERTED(direction, zone, inverted_idx=j)

INVERTED
 └─ entry on RETEST: the first later bar whose price trades back INTO the zone
      bullish FVG → now resistance → SELL at zone_bull.upper_edge (entry = zone top)
      bearish FVG → now support   → BUY  at zone_bear.lower_edge (entry = zone bottom)
      stop  = beyond the swing extreme that produced the inversion (inversion bar extreme ± buffer)
      target = next opposing liquidity pool; require >= 2R of room, else reject the setup
      if no retest within MAX_RETEST_BARS → setup expires (log it as an outcome)
```

**New decision function** (replaces `generate_ob_entry_signals`):

```python
def generate_ifvg_entry_signals(
    df: pd.DataFrame,
    atr_col: str = "atr_14",
    min_gap_atr_mult: float = MIN_GAP_ATR_MULT,     # 0.25  (constants module, not literal)
    inversion_min_bars: int = INVERSION_MIN_BARS,   # 7
    inversion_max_bars: int = INVERSION_MAX_BARS,   # 15
    rr: float = FIXED_RR,                           # 2.0
    max_retest_bars: int = MAX_RETEST_BARS,
    sweep_lookback: int = SWEEP_LOOKBACK,
) -> pd.DataFrame:
    """Adds: ifvg_direction, ifvg_zone_low, ifvg_zone_high, ifvg_formed_idx,
    ifvg_inverted_idx, ifvg_bars_to_inversion, ifvg_smt, ifvg_known_at_idx,
    ifvg_entry, ifvg_sl, ifvg_tp, ifvg_signal, ifvg_confidence.

    HARD RULE: every column written at row i must be derivable from bars[0..i] only.
    `ifvg_known_at_idx` is the bar on which the setup became tradable; the Nautilus
    strategy may only act on a setup at or after that bar.
    """
```

**The xauusd → our-code mapping:**

| xauusd artifact | our destination | action |
|---|---|---|
| `data_loader.add_atr` | `dodgys_dd_quant/strategy/indicators.py::add_atr` | port with edits — Wilder smoothing (theirs is `rolling(14).mean()`), and **session-aware previous close** so the overnight gap does not inflate ATR on 1-min NQ |
| `smc_strategy.detect_swing_points` | `strategy/structure.py::detect_swings` | **rewrite right-edge-free**: a swing is published `lookback` bars after it forms; add a max age so stale levels stop being swept |
| `smc_strategy.detect_bos` | `strategy/structure.py::detect_bos` | port with edits — BOS is not in our rule set (we use sweeps), but the "last confirmed swing" bookkeeping is reusable |
| `smc_strategy.detect_liquidity_sweeps` | `strategy/structure.py::detect_liquidity_sweeps` | **port with edits** — closest match to our Rule step 2; extend the swept level set to EQH/EQL/PDH/PDL and require ATR-depth ≥ threshold |
| `smc_strategy.detect_fvg` | `state_machine.py` (FVG formation step) | **port with edits** — add the 0.25 × ATR gap filter and the zone/inversion bookkeeping |
| `smc_strategy.detect_order_blocks` | — | **discard** (wrong entry object + look-ahead + volume semantics) |
| `smc_strategy.generate_ob_entry_signals` | — | **discard**, superseded by `generate_ifvg_entry_signals` |
| `smc_strategy.compute_smc_features` | `strategy/features.py` | rewrite — keep only the feature columns we actually declare |
| `data_loader.add_session_labels` | `strategy/sessions.py::add_session_labels` | **rewrite** — `zoneinfo` America/New_York, DST-correct, killzone whitelist/blacklist per the design doc (not 4 fixed buckets) |
| `ict_power_of_3.*` | — | **reference only** — the "manipulation = false breakout" idea is already in our spec; the session model is wrong |
| `momentum_strategy`, `sentiment_strategy` | — | **discard** (RSI/Stoch/MACD; VIX/DXY sentiment — we use VXN) |
| `risk_management.RiskManager/RiskConfig` | `dodgys_dd_quant/strategy/risk.py` | **port with edits** (see A.7) — keep sizing math, DD ladder, ATR stop clamp, risk features; add contract multiplier/tick size; move costs to config |
| `ml/ensemble_model.py` | — | **discard** (3-class directional label) |
| `backtesting/wfo_engine.py` | `ml_pipeline/` (our own) | **reference only** — our spec already mandates purged 6/1/1-month rolling with embargo; their folds recompute features per fold (history loss at fold edges) and have no embargo |
| `backtesting/probability_best_fit.py` | — | **reference only** — nice BIC/Monte-Carlo reporting, not required |
| `main.py` | — | **discard** (yfinance + XGBoost orchestrator) |

### A.10 Data-format assumptions vs our Nautilus Parquet catalog

| Assumption in xauusd | Actual | Consequence for us |
|---|---|---|
| Columns | `open, high, low, close, volume` (lower-case), plus derived `returns, log_returns, range, body, upper_wick, lower_wick, is_bullish` | Trivial adapter: `catalog.query()` → rename `ts_event`→index, `bar_type` filter. Lower-case names are a non-issue. |
| Index | `DatetimeIndex` named `datetime`; **no tz normalisation anywhere** | Nautilus `ts_event` is UTC epoch ns → we must build a tz-aware index ourselves. Everything session-related must go through `zoneinfo`. |
| Timezone | **Broken.** `add_session_labels` documents UTC but reads the local exchange tz of `GC=F` | Must rewrite; this is the single most dangerous silent bug in the corpus (a 4-hour mislabel of every session gate). |
| Instrument | **Absent.** One frame = one instrument; there is no `symbol` column and no second series | Our design needs **NQ (traded) + ES/YM (SMT reference) aligned on timestamp**. The xauusd pipeline is structurally single-instrument → SMT requires a second frame and a merge-on-timestamp step that the corpus does not contain. `AGENTS.md` forbids resampling across instruments: align on timestamps only. |
| Timeframe | None hard-coded (default `1h`) | Our target is **1-minute** bars + 5 m/1 H context. `ATR(14)` on 1-min NQ is ~0.25–0.5 pt, so every ATR-multiple threshold must be re-derived, not copied. The `MIN_GAP_ATR_MULT = 0.25` constant is the one that transfers. |
| Volume | Required, non-null (yfinance) | NQ/ES have tick volume → the column exists, but **volume is not liquidity**; do not port the OB strength formula. |
| Prices | float64, no tick snapping | Fine for indicators; **order prices must be snapped to tick size** — Nautilus handles this from the `FuturesContract` definition. |
| Session gaps | Not handled: `add_atr` uses `abs(high - close.shift(1))`, so the overnight gap enters TR | For 1-min NQ the CME break would inflate ATR and corrupt the 0.25 × ATR gap filter. Need a session-aware previous close. |
| Look-ahead posture | Two confirmed violations (centered swing window; OB registered pre-displacement) | Any ported detector must be re-derived as causal. This is the main risk in section A. |

**Net:** the data contract is *compatible* (one OHLCV frame, one row per bar) but the **index/tz
handling and the single-instrument assumption are not**. The adapter is ~40 lines; the causal
rewrite is the real work.

---

## B. `AlphaGPT` — can it mine factors for us?

**Verdict: BORROW-IDEAS-ONLY** (usable as a bounded interpretability research toy, at low
priority; **not** part of the production pipeline). Use **upstream only** — the community mirror is
stale (see B.5).

### B.1 What the core abstractions actually are

AlphaGPT is **not** symbolic regression in the classical (genetic-programming / gplearn) sense and
**not** a transformer language model over text. It is:

> a **Transformer sequence generator trained with REINFORCE (policy gradient) that emits a
> postfix token sequence ("formula") over a fixed DSL**, which is then **evaluated by a stack VM
> over dense torch tensors** and scored by a hand-written fitness function.

Concretely (`model_core/`):

* `alphagpt.py` — `AlphaGPT`: d_model 64, 2 LoopedTransformer layers (3 inner loops each), 4 heads,
  RMSNorm, SwiGLU, QK-Norm, `MTPHead` (multi-task pooling over 3 vocab-sized heads) + a scalar
  critic head. The policy is **autoregressive over 12 formula tokens**; the critic value is
  computed but **never used** in `engine.py` (only `logits` are consumed) → it is a pure REINFORCE
> policy, not PPO.
* `vocab.py` — `FORMULA_VOCAB`: `feature_names = (RET, LIQ_SCORE, PRESSURE, FOMO, DEV, LOG_VOL)`
  plus 13 operator names → **19-token vocabulary**. This indirection is the one genuinely useful
  extension point (see B.4).
* `ops.py` — `OPS_CONFIG`: `ADD, SUB, MUL, DIV, NEG, ABS, SIGN, GATE, JUMP, DECAY, DELAY1, MAX3`
  (+`NOT`-style `GATE`). All are **pointwise-in-time or 1-bar-lagged**; there are **no
  cross-sectional operators** and **no windowed operators** (no rolling mean/rank).
* `vm.py` — `StackVM.execute()`: postfix evaluation over a `[n_series, n_time]` tensor; returns
  `None` for malformed formulas.
* `factors.py` — the base features. `FeatureEngineer.compute_features` **requires**
  `raw_dict['liquidity']` and `raw_dict['fdv']` (crypto token metadata) — there is **no way to feed
  OHLCV-only bars** without writing a new feature engineer. `AdvancedFactorEngineer` adds 12
  features (Parkinson-ish vol, momentum reversal, relative strength, close-position-in-range) but
  **still requires `liquidity` and `fdv`**.
* `engine.py` — the search loop: sample 8192 formulas per step × 1000 steps, execute each on the
  full panel, reward = fitness, advantage = standardised reward, loss = Σ −logπ·A. A new best
  formula is printed and saved to `best_meme_strategy.json`.
* `backtest.py` — `MemeBacktest.evaluate()`: `signal = sigmoid(factor)`, `position = (signal > 0.85)
  & liquidity > 500k`, crypto-AMM costs (`0.6 %` fee + price impact `trade_size/liquidity`
  clamped to 5 %), P&L against a 2-bar forward open-to-open log return, `score = cum_ret − 2 ×
  #(bars with pnl < −5 %)`, **fitness = `torch.median(score)` across the asset universe**.
* `lord/experiment.py` — **not a finance experiment at all**: it is a research script on
  **modular addition arithmetic** (`ModularAdditionDataset(p=113)`) used to characterise the
  LoRD regulariser. The paper's experiment folder is a toy-arithmetic study; the finance code is
  entirely in `model_core/`.

### B.2 The data adapters

* `model_core/data_loader.py` — `CryptoDataLoader` reads a **PostgreSQL** table
  (`SELECT time, address, open, high, low, close, volume, liquidity, fdv FROM ohlcv`), pivots to
  `[n_tokens, n_time]` tensors, `ffill` then `fillna(0)`. Hard-coded `DB_URL` from env vars.
* `data_pipeline/` — `fetcher.py` / `providers/{birdeye,dexscreener}.py` pull trending tokens and
  OHLCV from **crypto APIs** into Postgres; `processor.py` does cleaning + basic factors;
  `db_manager.py` / `data_manager.py` manage the store.
* **There is no file / parquet / catalog adapter anywhere.** Feeding it requires writing a new
  loader.
* The live side (`execution/`, `strategy_manager/`) is a **Solana on-chain bot** (Jupiter aggregator,
  honeypot checks via sell quotes, SOL accounting) — irrelevant to a futures pipeline.

### B.3 What a "factor" means in its schema

A factor is a **token sequence**; its *evaluation* is a per-asset time series of values; a trade is
taken where `sigmoid(factor) > 0.85` and the asset is liquid; P&L is booked bar-by-bar against the
2-bar forward return; the fitness of a formula is the **median score across the asset universe**.

**This corrects the design doc.** `iFVG几个模型的讨论.txt` characterises AlphaGPT as aiming at
"cross-sectional stock ranking (IC/RankIC)". That is **Qlib**, not AlphaGPT: `grep -rniE
"rankic|information coefficient"` over the whole AlphaGPT tree returns **zero hits**. AlphaGPT has
no IC, no RankIC, no universe-selection step, and no ranking of assets. Its cross-sectional-ness is
one line: `torch.median(score)` over the token panel.

That matters because the doc's rejection reason is **partly wrong**, and the *real* rejection reason
is stronger (B.4).

### B.4 The decisive question: can the search be pointed at our event timestamps?

**Yes in principle — the search machinery is instrument-agnostic; the data, features, target and
fitness are not.** Four concrete changes:

1. **Data adapter (new, ~80 lines).** Replace `CryptoDataLoader` with a reader over our Nautilus
   Parquet catalog → tensors `[n_series, n_time]` for NQ / ES / YM.
2. **Feature engineer (new).** `FeatureEngineer` is hard-wired to meme-coin columns
   (`liquidity`, `fdv`). We must write our own `compute_features` producing our declared block:
   checklist score, SMT flag, vision confidence, VXN level + 1-hour change, bars from FVG
   formation to inversion, minutes from US open — plus optionally the FVG geometry
   (gap/ATR, zone position in the dealing range). **Good news:** upstream's `vocab.py` makes the
   feature vocabulary pluggable (`FORMULA_VOCAB(feature_names=..., operator_names=...)`), and the
   stack VM indexes features by position — so a new feature block drops in cleanly. *This is the one
   thing in AlphaGPT that ports.*
3. **Target definition.** `target_ret` is a dense 2-bar forward open-to-open log return. Ours is
   event-conditioned: after the retest entry, did price reach +2R before −1R? The current
   evaluation is **dense per bar**, so an event mask has to be introduced: either (a) a boolean
   event mask applied inside the fitness (the VM cannot express it, but the fitness can), or
   (b) build a panel whose rows are event windows (±N bars around each setup).
4. **Evaluation metric.** `MemeBacktest.evaluate` must be replaced by an event-conditioned
   fitness: take the factor value at each event bar, threshold it, simulate the barrier outcome,
   score in **R after costs** ($4.5 round-turn + 1–2 ticks slippage), and require a minimum trade
   count. The "median over the universe" trick maps naturally to **median expectancy across the 12
   monthly walk-forward folds** — a cheap and genuinely useful drift-robustness objective.
5. **Sampling / compute.** With `BATCH_SIZE = 8192`, `MAX_FORMULA_LEN = 12`, and a panel of
   3 instruments × 1 year of 1-minute bars (~1.5 M bars), each step evaluates
   8192 × 12 × 1.5 M element-ops ≈ 1.5e11 → not feasible per step × 1000 steps. The panel must be
   **restricted to event windows** (e.g. 5,000 events × 61 bars × 3 instruments ≈ 0.9 M values),
   and the batch/steps reduced (≈1024 × 300). This is the "point it at our event timestamps"
   answer, and it is also the reason the whole thing is expensive.
6. **Walk-forward.** The current loop optimises the formula on the **whole panel** — the mined
   expression is in-sample unless we re-implement the fold loop (which is exactly the part we
   would have to build anyway).

**What would it buy us that LightGBM does not?** A **closed-form, human-readable expression** over
our features. Not accuracy: with 10–20 features and tree models, LightGBM already models the
interactions. The value is interpretability and cheap inference, and the risk is that we spend GPU
hours rediscovering `sigmoid`-of-a-threshold.

**Also note the "no information creation" property**: the searched formulas are functions of
features *we* supply. The search can compress and re-weight, never create information. A LightGBM
meta-labeler over the same features already captures nearly all of it.

### B.5 Licence and the community mirror

* **Upstream `imbue-bit/AlphaGPT`: Apache-2.0** (a full `LICENSE` file is present). Compatible with
  reuse provided we keep the notice. The upstream README is largely an appeal for donations
  ("人身安全威胁", donation links) — that is presentation, not licence.
* **Mirror `AlphaGPT-By-imbue-bit`: STALE and materially different.**
  * Mirror HEAD `5d38411` dated **2026-01-11**; upstream HEAD `d851f22` dated **2026-06-12** —
    a **5-month lag**.
  * `diff -rq` shows **`model_core/{alphagpt,factors,vm,engine,config,data_loader}.py` all
    differ**, plus `strategy_manager/runner.py` and the whole `data_pipeline/` + `execution/`.
  * The mirror **lacks** the `vocab.py` refactor → there the feature count is hard-coded
    (`ModelConfig.INPUT_DIM = 6`, `AlphaGPT(vocab_size=30)`) and `StackVM` derives its offset from
    `FeatureEngineer.INPUT_DIM`. **The pluggable-vocabulary extension point we would need does not
    exist in the mirror.**
  * The mirror also lacks `lord/`, `times.py`, `requirements.txt`, `requirements-optional.txt`,
    `.gitignore`; it adds `README_EN.md` and loose PNGs.
* **Action: use upstream only. Delete/ignore the mirror.** A stale copy of a research repo in
  `research/` is a trap: it looks like a backup and is actually an older API.

### B.6 Pilot plan (only because the answer is "usable as a research toy", at low priority)

**Pilot: "does a mined expression add anything over LightGBM on iFVG events?"**

*Scope (2 engineer-days, GPU optional):*
1. From the Phase-1 rule engine, export **every** candidate setup (never delete losing ones) with
   the declared feature block + the binary 2R-vs-stop label + the FVG geometry.
2. Write our `FeatureEngineer` + a `StackVM`/`ops` pair **copied verbatim from upstream**
   (Apache-2.0, ~76 lines) + an event-conditioned fitness (median across the 12 monthly
   walk-forward folds of expectancy-in-R after costs; penalty for folds with < 5 trades).
3. Train with a reduced budget (batch ≈ 1024, ≈300 steps) over an event-window panel.
4. Compare the mined expression against (i) "always take the trade", (ii) the LightGBM meta-labeler
   at the same 0.58 gate.

*What the pilot measures:* OOS expectancy in R (median fold), % positive folds, expression token
count, and whether the expression survives costs.

*What would disqualify it (any one is sufficient):*
* median-fold expectancy does not beat the "always trade" baseline by ≥ **0.15 R**;
* the mined expression does not match LightGBM's OOS expectancy within **±0.10 R** (i.e. no
  information gain — LightGBM is then strictly better and the expression is a report artifact only);
* the run needs > **3 GPU-hours** or > **2 engineer-days** per expression;
* the advantage disappears after subtracting $4.5 round-turn fees + 2-tick slippage;
* the expression is not stable across ≥ 70 % of the monthly folds.

*If disqualified:* stop; the production path stays LightGBM. If qualified: keep the expression
**only** as an interpretability artifact attached to the meta-label report — never as a gate, never
in the live path.

---

## C. `Qlib` — architecture, futures support, and the rolling-retrain question

**Verdict: BORROW-IDEAS-ONLY** (take the rolling-split *concept*, not the code; discard the data
layer, the backtest engine, the workflow/MLflow stack and the model zoo).

Snapshot: upstream `microsoft/qlib` HEAD `5435523` (2026-10-08). Licence: **MIT**.

### C.1 Core abstractions

| Layer | Location | What it is |
|---|---|---|
| Data store | `qlib/data/storage/file_storage.py` | Per-**market** × per-**instrument** × per-**field** binary files + a shared calendar file + a per-market instrument list. Keys are `(market, symbol)`; the calendar defines the time axis. |
| Expression engine | `qlib/data/ops.py`, `base.py`, `expression_parser.py` | Per-instrument series computation: `Ref`, `Rolling`/`Mean`/`Std`/`Corr`/`Rsquare`/`Quantile`, `ChangeInstrument` (cross-instrument reference), `TResample`, point-in-time `P`/`PRef` (`qlib/data/pit.py`). |
| Client / panel | `qlib/data/client.py`, `qlib/data/data.py` | `D.features()` assembles the **panel**: a DataFrame indexed by `(datetime, instrument)` — a cross-sectional date panel by construction. |
| Dataset | `qlib/data/dataset/` | `DataHandler`/`DataHandlerLP` (fit/process pipelines), `DatasetH` (train/valid/**test segments** over the panel), `TSDataSampler` (samples `(instrument, datetime)` rows), `TSDatasetH` (per-instrument time series). |
| Model zoo | `qlib/contrib/model/` | `gbdt.py` (LGBModel), `xgboost.py`, `catboost_model.py`, `linear.py`, `double_ensemble.py`, + ~20 PyTorch variants; `qlib/model/ens/`, `qlib/model/riskmodel/`. |
| Workflow / experiment | `qlib/workflow/` | `R` / `Recorder` on **MLflow** (`recorder.py`), `exp.py`/`expm.py`, `record_temp.py` (signal + portfolio analysis records), `task/` (TaskManager, **task generators**), `online/`. |
| Rolling orchestration | `qlib/contrib/rolling/base.py`, `qlib/workflow/task/gen.py` | `Rolling` driver + `RollingGen` (expanding vs sliding segment shifting on qlib's calendar, `trunc_days` tail-truncation to avoid future leakage); `qlib/contrib/rolling/ddgda.py` is a rolling variant with dynamic labels. |
| Backtest | `qlib/backtest/` | `Exchange` (fills, **price limits**, **suspension**, volume caps, trade unit, open/close cost), `Account`, `Position`, `executor.py` (incl. a nested executor used as an RL simulator), `decision.py` (`Order`, `TradeDecision`), `report.py`. |
| Strategies | `qlib/contrib/strategy/` | `TopkDropoutStrategy` (buy top-k / sell bottom-n by score), `EnhancedIndexingStrategy`, rule strategies. |
| Evaluation | `qlib/contrib/evaluate.py`, `eva/alpha.py` | IC / RankIC analysis of predictions vs labels. |
| RL | `qlib/rl/` | A `Simulator`/`State`/`Reward` framework (gym-style) with a single-asset **order-execution** task (PPO) and `qlib/rl/data/` intraday backtest data. |

### C.2 The critical question: futures and single-instrument event-driven strategies?

**No. Qlib is equity-candle + cross-sectional only.** Evidence from the source:

1. **No futures anywhere.** `grep -rniE "future" qlib/` returns only "future information",
   `get_next_trading_date(..., future=True)` and `__future__` imports. There is **no futures
   instrument type**, no contract multiplier, no expiry/roll logic, no continuous-contract
   handling, no margin.
2. **The instrument model is static equity.** `InstKT = (market, symbol)` with a static start/end
   time per instrument; the store is a per-symbol price panel.
3. **The `Exchange` is an equity exchange**: `limit_threshold` (**涨跌停** price limits),
   `check_stock_suspended()` (a NaN `$close` = suspended), `trade_unit` (round lots, e.g. 100
   shares), `volume_threshold`, `open_cost`/`close_cost`/`min_cost`, and `Order.SELL` / `Order.BUY`
   **only**.
4. **No short positions.** `qlib/backtest/position.py` `Position` holds a *stock count* per code;
   there is no `PositionDirection.SHORT`, no margin, no leverage, no multi-leg or bracket orders.
   (`qlib/contrib/strategy/rule_strategy.py` has a `TREND_SHORT` constant, but it maps to "sell the
   holding", not to opening a short.)
5. **The canonical strategy is a long-only cross-sectional ranking.**
   `TopkDropoutStrategy.generate_trade_decision()` takes `pred_score` (a Series indexed by
   instrument for one decision date), sorts it descending, buys the top-k not already held and
   sells the bottom-n of the current holdings. `EnhancedIndexingStrategy` produces
   benchmark-relative weights. Both **require a cross-section at every decision date**.
6. **T+1-style cash settlement** (`settle_type = "cash" | None`) and per-day bars semantics.
7. **The label model is cross-sectional/time-based**: the canonical label is
   `Ref($close,-2)/Ref($close,-1)-1` (a forward return), and `qlib/contrib/evaluate.py` scores
   models with **IC / RankIC** — i.e. exactly the cross-sectional ranking paradigm.

**The one thing that looks tempting and is real:** minute-frequency *is* supported
(`qlib/contrib/ops/high_freq.py` builds 1-minute calendars; `qlib/contrib/model/highfreq_gdbt_model.py`
exists). But intraday support does not change the equity/cross-sectional shape.

**Net for us:** a single NQ contract with event-conditioned entries, a 2R bracket, a stop beyond a
swing, and MTF context is **not expressible** in Qlib's backtest: no shorts, no futures contract
spec, no intrabar bracket, no per-event entry, no event-conditioned label.

### C.3 Could Qlib's rolling-retrain machinery drive our monthly LightGBM refit *without* adopting its data layer?

**Technically yes, practically no.** What would be reused:

* `qlib/workflow/task/gen.py::RollingGen` — generates the sequence of rolling tasks by shifting
  `train`/`valid`/`test` segments (`ROLL_EX` expanding for train, `ROLL_SD` sliding for
  valid/test) and truncating the tail of train/valid (`trunc_days`) to prevent future leakage.
* `qlib/contrib/rolling/base.py::Rolling` — drives the fold graph and **concatenates the OOS
  predictions of all folds into one rolling record**.
* `qlib/workflow/task/utils.py` — the `train → predict → record` task loop.
* `qlib/workflow/recorder.py` — MLflow-backed experiment tracking (`R.start`, params, metrics,
  artifacts).
* `qlib/contrib/model/gbdt.py::LGBModel` — a thin LightGBM wrapper.

**The blockers, in order of severity:**

1. **Hard coupling to Qlib's calendar and dataset.** `RollingGen` shifts segments using
   `qlib.data.pit.TimeAdjuster` against **Qlib's trading calendar**, and feeds a `DatasetH` whose
   handler pulls from the **Qlib data provider**. The rolling machinery is not a standalone
   orchestrator; it is a scheduler *for Qlib's own data path*.
   *Escape route:* implement a custom `DataHandler` (Qlib ships `DataHandlerLP.from_df(df)`) whose
   `fetch` returns our event table. But our label is **event-conditioned and irregular**
   (one row per setup), whereas `DatasetH`/`TSDataSampler` expect a **regular** `(datetime,
   instrument)` panel; event timestamps get snapped to the calendar, and "bars since FVG formation"
   semantics must therefore be pre-computed as columns. Doable — contorted.
2. **YAML config, against an explicit repo rule.** `Rolling` takes `conf_path` pointing to a
   **YAML** file (`ruamel.yaml`, a hard dependency); `qlib/config.py` is YAML end-to-end. `AGENTS.md`
   mandates **JSON-only** ("do not introduce a second config convention"). Adopting Qlib's rolling
   machinery means adopting its YAML conventions.
3. **Dependency weight.** `pyproject.toml` pulls `mlflow<3.13`, `redis`, `pymongo`, `filelock`,
   `python-redis-lock`, `cvxpy`, `gym`, `lightgbm`, `dill`, `ruamel.yaml`, `matplotlib`,
   `jupyter`, `nbconvert` into an environment that currently has NautilusTrader + pandas + numpy.
   `mlflow` + `redis` + `pymongo` for a **monthly** refit of one model is disproportionate.
4. **The purge is not an embargo.** `trunc_days` truncates the tail of the training segment
   (one-sided). Our spec requires an explicit **embargo gap** between train end and test start;
   expressible via `trunc_days` in days, but only as a truncation, not as a symmetric gap.
5. **MLflow record shape** (one experiment per rolling, artifacts per fold) does not match our
   "persist every candidate setup with its outcome" requirement, and our `AGENTS.md` already
   specifies a log-export format.

**Integration cost:** properly (with Qlib's data layer: export NQ/ES/YM 1-min bars into Qlib's
CSV/`bin` layout, custom handler, custom label, monthly segment config, YAML, MLflow) ≈
**3–6 engineer-days of plumbing plus a permanent second config/runtime convention**.
Reimplementing the split ourselves: **≈ 1 day** for the 6-month train / 1-month validate /
1-month test rolling scheme with a purge+embargo, in JSON, driven by our own Parquet catalogue.

### C.4 Verdict per component

| Component | Verdict | Reason |
|---|---|---|
| Data layer (`qlib/data/*`, storage, expression engine) | **discard** | Equity panel + calendar + per-symbol bin store; no futures; our data is event-shaped |
| Expression engine ideas (`ChangeInstrument`, `TResample`, `Ref`, `Corr`) | **borrow-ideas-only** | `ChangeInstrument` is exactly the "reference instrument" concept our SMT needs (ES/YM as reference) — implement it on the Nautilus timeline instead |
| Dataset layer (`DataHandler`, `DatasetH`, `TSDataSampler`) | **discard** | Regular cross-sectional panel assumption; our rows are irregular events |
| Model zoo (`contrib/model/*`) | **discard** (reference only) | Our LightGBM call is ~20 lines; the wrappers add no value |
| Workflow / MLflow recording (`qlib/workflow/*`) | **discard** | mlflow/redis/mongo + YAML; our log-export requirement is already specified |
| Rolling orchestration (`RollingGen`, `contrib/rolling/*`) | **borrow-ideas-only** | Take the *concept* (expanding-window monthly folds, tail truncation, concatenated OOS predictions) and reimplement in JSON; do **not** import the code — it is inseparable from Qlib's calendar + dataset + YAML |
| Backtest / `Exchange` / `Account` / `Position` | **discard** | Long-only equity; no shorts, no futures, price limits, T+1 settlement, no bracket orders. NautilusTrader already owns this role |
| `contrib/evaluate.py` (IC/RankIC) | **discard** | Cross-sectional ranking metrics; meaningless for a single-contract event-conditioned evaluation |
| `qlib/rl/` (simulator abstraction, SAOE task, PPO) | **reference only** | A second simulator for a *different* task (order execution). Our RL layer must run inside Nautilus or we get state divergence between backtest and live. Revisit only for reward-shaping design ideas |

---

## D. The ICT reasoning dataset (`ict-6000-mentorship-master`)

**Verdict: ADAPT — but only the 4,000-row "Audit" subset, and only as a checklist spec + synthetic
test-vector corpus.** It is not a detector and not training data.

### D.1 Schema, row structure, size

* One Parquet file, `data/train-00000-of-00001.parquet`, **1.05 MB**, **6,000 rows**, **2 string
  columns**: `instruction`, `output`. No metadata, no splits beyond `train`, no provenance beyond the
  README. Mean lengths: instruction ≈ 418 chars, output ≈ 1,111 chars (max 1,808).
* Every output carries a `<think>…</think>` chain followed by a formatted verdict block — i.e. it is
  **already instruction-tuned SFT data**, not raw prose.

**Composition (measured):**

| Subset | Rows | Structure |
|---|---|---|
| `Audit this {Bullish,Bearish} ICT setup on {NQ,ES,YM,XAUUSD}` | **4,000** | 4-line structured input (Time / Dealing Range / Liquidity Context / Structure & PD Array) → 4-gate `<think>` audit → verdict + entry/SL/TP |
| `2022 ICT Mentorship Episode N …` | ~1,000 | Templated episode summary with a repeated live-market paragraph |
| `Write an ICT PineScript v5 indicator …` | ~500 | Code-generation requests |
| `Walk through the step-by-step IPDA checklist …` | ~250 | Prose checklist walk-throughs |

### D.2 How a rule is expressed

The Audit rows are parameterised like this:

```
- Time: 03:15 AM EST (London Open Silver Bullet Window)
- Dealing Range: Swing Low = 20343.64, Swing High = 20428.38 (50% Equilibrium = 20386.01)
- Liquidity Context: Swept Previous Day Low (PDL) / High (PDH) | Correlated ES (S&P 500) SMT Divergence: Confirmed
- Structure & PD Array: Energetic displacement MSS forming a 3-Candle Fair Value Gap (BISI / SIBI)
  between 20360.59 and 20367.37 (CE/50% = 20363.98, located at 24% of the dealing range).
```
→
```
1. Gate 1 (Time & Macro Audit)     → time ∈ killzone?
2. Gate 2 (Liquidity Purge & SMT)   → sweep stated | SMT Confirmed/Absent
3. Gate 3 (Displacement & MSS)      → "Confirmed energetic displacement"
4. Gate 4 (Dealing Range Math)      → equilibrium, FVG position %, Discount/Premium
5. Final IPDA Verdict               → VALID / INVALID
```
with **Entry Trigger / Stop Loss / Draw on Liquidity (Target)** in the output.

### D.3 Anti-hallucination check (measured, not impressionistic)

I parsed the Audit rows and tested the arithmetic. **2,287 of the 4,000** Audit rows parse under a
strict numeric regex; on those:

| Property | Result |
|---|---|
| `50% Equilibrium == (range_low + range_high) / 2` | **2,287 / 2,287 (100 %)** |
| `CE/50% == (fvg_low + fvg_high) / 2` | **2,287 / 2,287 (100 %)** |
| `"located at X%" == (CE − range_low) / (range_high − range_low)` | **2,287 / 2,287 (100 %)** |
| FVG lies inside the dealing range | **2,287 / 2,287 (100 %)** |
| Discount/Premium word agrees with X < 50 / X > 50 | **2,287 / 2,287 (100 %)** |
| Entry price == the **FVG edge** (never the CE, though the text offers the CE) | **966 / 966** |
| Stop = swing extreme ± a **fixed per-instrument buffer** (NQ 1.0 pt, ES 1.0, YM 4.0, XAUUSD 0.4) | **966 / 966** |
| Target = the opposite swing extreme, exactly | **966 / 966** |
| Time windows NY-Lunch 12:00–13:00 / 08:28 pre-08:30-news / 18:15 dead-Asian-transition → **INVALID** | **756 rows, 100 % INVALID** (252 each) |
| Killzone windows (6 of them) → mix of VALID / INVALID | 148–176 VALID, 80–109 INVALID per window |
| **`SMT: Not Present` still yields `VALID`** | confirmed on the YM example — **SMT is not a mandatory gate in this corpus** |

**Interpretation.** The Audit subset is **not generic ICT prose**: its numbers are internally
consistent and fully deterministic. It is a **synthetic 4-gate rule-audit corpus** — a parameterised
checklist, with the parameters drawn from a random generator, not from any real bar.

Two consequences that decide the verdict:

* **The reasoning is *not* derived from price structure.** Gates 2 and 3 are **asserted inputs**:
  the instruction *states* "Swept PDL/PDH | SMT Confirmed" and "Energetic displacement MSS", and the
  output merely echoes them. Only Gate 4 (arithmetic) and Gate 1 (time table) are *derived*.
  The corpus therefore contains **no detector logic**: it cannot teach or validate how to find a
  sweep, an MSS or a displacement.
* **The prices are fabricated.** A 20,343 NQ dealing range and a 5,850 ES dealing range belong to
  the same session; they are mutually impossible. The corpus is a rule *language*, not market data.

**Deterministic-test verdict:** *partially yes*. The 2,287 clean Audit rows + the 756 hard-negative
time rows **can** be converted into a deterministic test corpus for a *checklist decision function*
(gate table, time whitelist/blacklist, premium/discount convention, entry-at-FVG-edge, stop-beyond-
swing buffer, target at the opposite extreme). They **cannot** validate our FVG / sweep / MSS
*detectors*, and they contain no information that could.

### D.4 Assessment of the three proposed uses

| Use | Verdict | Why |
|---|---|---|
| (i) Feature-engineering reference | **No — discard** | Every "feature" is a template slot; nothing is derived from bars. Our feature list is already fixed by the design doc. The only transferable content is the *name* of four gates. |
| (ii) Rule-audit checklist for validating the state machine | **Yes — this is the one real use** | It is a machine-checkable spec of what a *complete* ICT setup gate list looks like. Concretely: (1) diff its 4 gates against `research/docs/RULE_SPEC.md` and close any gap in our checklist (e.g. it forbids NY-Lunch initiations and pre-08:30-news entries — do we?); (2) convert the Audit subset into a JSON fixture and assert our checklist engine reproduces the corpus verdicts, including the 756 time-violation rows; (3) **note the deliberate divergence**: the corpus treats SMT as *optional* (Absent → still VALID), whereas our DodgysDD checklist makes SMT a **+2 score point** in the A+/A/B/C grading. Our rule is stricter — keep ours, and record the divergence so nobody "fixes" it later. |
| (iii) LLM fine-tuning data | **No — discard** | 6,000 rows but only 5,419 distinct instruction templates, with the "Live Market Application" paragraph repeated verbatim **5,000×** and the "Anti-Retail" paragraph **4,500×**. The prices are synthetic and mutually inconsistent across instruments. Fine-tuning on this teaches a model to emit ICT boilerplate **with fabricated price levels** — precisely the failure mode our `AGENTS.md` warns about in a different costume ("Hide Losing Setups": inventing a plausible-looking signal). |

---

## E. Recommended reuse plan

### E.1 Decision table

| # | Artifact | Decision | Deciding reason | Concrete next action |
|---|---|---|---|---|
| 1 | `research/huggingface/xauusd-ml-trader/` | **ADAPT** | Only artifact containing runnable SMC primitives (swing / sweep / FVG / ATR / session / sizing) in pandas, futures-capable, minute-capable. But: two look-ahead defects (centered swing window; OB registered pre-displacement), broken timezone handling, no futures contract model, no costs applied, and a **3-class directional ML label** that contradicts our binary meta-label spec. | Port 4 modules into `dodgys_dd_quant/strategy/` with the fixes named in A.9; rewrite the entry generator as `generate_ifvg_entry_signals`; drop `ensemble_model.py`, `main.py`, order blocks, momentum & sentiment strategies. Add a golden-fixture test for the causalised sweep detector. |
| 2 | `research/github/AlphaGPT/` (upstream) | **BORROW-IDEAS-ONLY** | A REINFORCE formula generator over a **hard-wired crypto-meme feature set** (`liquidity`, `fdv`) with a **dense cross-sectional P&L fitness**. Pointing it at our event timestamps means replacing the feature engineer, the target, the fitness and the sampling, then re-tuning a GPU training loop — to compress 10–20 features that LightGBM already models. Also: **no IC/RankIC anywhere** (the design doc's rejection reason is inaccurate; the real one is stronger), and the paper's `lord/` experiments are a modular-arithmetic toy study. | Do not port into `dodgys_dd_quant/`. If the team wants the interpretability artifact, run the bounded pilot in B.6 (2 days, explicit disqualifiers) using **upstream only**. |
| 3 | `research/github/AlphaGPT-By-imbue-bit/` (community mirror) | **DISCARD** | **Stale by 5 months** (2026-01-11 vs upstream 2026-06-12) and materially different: all of `model_core/{alphagpt,factors,vm,engine,config,data_loader}.py` differ, and the mirror **lacks the `vocab.py` refactor** — i.e. it lacks the one extension point (pluggable feature vocabulary) we would have used. It also lacks `lord/`, `times.py` and `requirements.txt`. | Remove the clone from `research/` to avoid accidental use; cite upstream only. Keep upstream under Apache-2.0 with the notice preserved. |
| 4 | `research/github/qlib/` | **BORROW-IDEAS-ONLY** | No futures support anywhere; equity-only `Exchange` (price limits, suspension, round lots, T+1 cash settlement); **long-only** `Position` (no shorts); the canonical strategy is a cross-sectional top-k ranking; the label model is a forward return scored with IC/RankIC. Its rolling machinery is inseparable from Qlib's calendar + dataset + **YAML** config (against our JSON-only rule) and drags in mlflow/redis/mongo. Reimplementing our split costs ≈ 1 day vs ≈ 3–6 days to adopt. | Take the *concept* only — expanding-window monthly folds, tail truncation (purge), concatenated OOS predictions — and reimplement in `dodgys_dd_quant/ml_pipeline/` with a JSON config and an explicit **embargo**. Do not import qlib. |
| 5 | `research/huggingface/ict-6000-mentorship-master/` | **ADAPT** (test-vector corpus only) | The 4,000-row Audit subset is a **synthetic but arithmetically exact** 4-gate checklist: 100 % consistent equilibrium/CE/position math, deterministic per-instrument stop buffer, exact opposite-extreme targets, 756 hard-negative time rows. That is genuinely checkable. But gates 2–3 are *asserted*, not derived, prices are fabricated, and SMT is optional there while our checklist makes it a score point. | Extract the Audit subset to `tests/fixtures/ict_audit_cases.json`; add `tests/unit/test_checklist_agreement.py` asserting our gate table reproduces the corpus verdicts; record the SMT divergence as an intentional deviation in `RULE_SPEC.md`. Do **not** use as ML training data. |

### E.2 Ordered port list — highest-value code to bring into `dodgys_dd_quant/`

| # | What | From | Destination | Effort | Risk it removes |
|---|---|---|---|---|---|
| 1 | **Risk-sizing core**: `compute_position_size`, `validate_stop_loss`, the DD ladder, `get_risk_features` | `xauusd-ml-trader/strategies/risk_management.py` | `dodgys_dd_quant/strategy/risk.py` | **0.5–1 day** incl. tests | Uncontrolled position sizing / drawdown blow-up. Our design doc specifies *no* sizing rule; this fills the gap with a fixed-fractional, ATR-clamped, DD-scaled, session-aware model that is pure and unit-testable. Must add: NQ contract multiplier + tick value; costs moved to the backtest config. |
| 2 | **Causalised swing + liquidity-sweep detector** (`detect_swing_points` + `detect_liquidity_sweeps`) | `xauusd-ml-trader/strategies/smc_strategy.py` | `dodgys_dd_quant/strategy/structure.py` | **0.5 day** | A silent look-ahead that would inflate PF. It is the part of Rule step 2 (EQH/EQL/PDH/PDL sweep) that is easiest to get wrong; the xauusd version is a *starting point whose confirmation lag we must add*, not a copy. |
| 3 | **FVG pattern detector** + ATR gap filter (`detect_fvg`, `add_atr` → Wilder, session-aware prev close) | `xauusd-ml-trader/strategies/smc_strategy.py` / `data_loader.py` | `dodgys_dd_quant/strategy/state_machine.py` (formation step) | **0.25 day** | Getting the imbalance definition wrong (and the overnight gap inflating ATR so the 0.25×ATR filter misfires). |
| 4 | **Session/killzone classifier** — rewrite of `add_session_labels` with `zoneinfo` America/New_York + DST | `xauusd-ml-trader/data_loader.py` | `dodgys_dd_quant/strategy/sessions.py` | **0.25 day** | The worst silent bug in the corpus: a 4-hour mislabel of every session gate (documented UTC, implemented exchange-local). |
| 5 | *Not ported*: `ensemble_model.py`, `main.py`, `detect_order_blocks`, `generate_ob_entry_signals`, `momentum_strategy.py`, `sentiment_strategy.py`, `probability_best_fit.py`, `wfo_engine.py` | — | — | 0 | — (the ML layer's 3-class directional label would re-decide direction and break the four-layer contract) |

**Net effect:** ≈ **2–2.5 engineer-days** to obtain a causal, futures-correct, unit-testable
sweep/FVG/session/sizing foundation — versus writing it from scratch, and versus the 3–6 days
plus a permanent YAML+MLflow dependency that adopting Qlib's rolling machinery would cost.

### E.3 What this assessment does *not* change

* **NautilusTrader remains the only backtest/live engine.** Nothing in any of the five artifacts
  justifies a second engine: `xauusd` has no engine at all, Qlib's backtest cannot express our
  trades, and AlphaGPT's live layer is a Solana on-chain bot.
* **The four-layer contract stands.** The rule engine still decides direction; the meta-labeler
  (LightGBM, binary 2R-vs-stop label, purged walk-forward) still filters; the RL layer still only
  manages positions.
* **The Phase-1 acceptance gate is untouched.** Any reuse must still show **Profit Factor > 1.25**
  under ~$4.5 round-turn fees and 1–2 ticks of slippage with fixed 1:2 RR on A/A+ setups only.
  Note that the xauusd corpus's own headline numbers are cost-free, so they are not a baseline.
* **Signal integrity is a hard constraint on every port.** Ported detectors must emit a
  `known_at` timestamp, and every candidate setup — including the ones that expire without a
  retest, and the ones the vision layer rejects — must be persisted with its outcome.
