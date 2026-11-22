# External sources

Every artifact below is referenced in `iFVG几个模型的讨论.txt` and is mirrored under `research/`.
This file records **how to re-fetch** each one, so a future agent can rebuild the research base without
rediscovering the URLs.

## GitHub (cloned into `research/github/`)

| Repo | Ref | Notes |
|---|---|---|
| Open-source iFVG Pine Script reimplementation | `cantolab/IFVG-Ultimate-Dodgy` | MIT. Encodes the authoritative rule parameters. **Highest-value artifact.** |
| Symbolic-regression factor mining | `imbue-bit/AlphaGPT` | Reference only; cross-sectional by design. |
| Microsoft AI quant platform | `microsoft/qlib` | Large. Cross-sectional stock ranking; architecture mismatch with a single-contract state machine. |
| Community mirror of AlphaGPT | `Hyde1989/AlphaGPT-By-imbue-bit` | Backup copy. |
| User's data-lake governance repo | `jssyxd/dataBaseLake` | Defines the 可用 / 可入湖 audit standard for downloaded backtest data. |

Auth: `git -c http.extraheader="Authorization: Bearer <GITHUB_TOKEN>" clone --depth 1 <url> <dir>`
(`github.com` token in `一些必备apikey和环境.txt`, repo-read only).

## Hugging Face (downloaded into `research/huggingface/`)

| Ref | Type | Notes |
|---|---|---|
| `ibtsam/nq-fvg-detector` | model | YOLOv26m FVG box detector. Intended vision cross-validation layer. |
| `nerds-gaming/xauusd-ml-trader` | model repo | Python quant framework: liquidity sweeps, FVG imbalance, session filters, risk mgmt. Order-block entry today. |
| `mandiyaaman/ict-6000-mentorship-master` | dataset | Structured ICT rule reasoning data. 401 on the *models* API, 200 on the *datasets* API — not a failure. |

Auth: `HF_TOKEN=<HUGGINGFACE_TOKEN> hf download <repo_id> --local-dir <dir>` (`hf` at `~/.local/bin/hf`).

## Kaggle (downloaded into `research/kaggle/`)

| Ref | Title | Notes |
|---|---|---|
| `ibtsamsadiq/nq-fvg-dataset` | nq-fvg-dataset | ~5.7 MB. FVG-labelled NQ candles. |
| `thinukakusalmith06/gold-xauusd-smc-trading-data` | Gold (XAU/USD) SMC Trading Data | ~88 KB. OHLC + FVG/OB boolean labels. |
| `wangqizhou/fvgnet` | FVgNET | ~45 GB — manifest only, do not download. |

Auth: `KAGGLE_USERNAME=<user> KAGGLE_KEY=<key> kaggle datasets download -d <ref> -p <dir> --unzip`
(`kaggle` at `~/.local/bin/kaggle`).

## TradingView
`iFVG Ultimate+ | DodgysDD` and `iFVG Ultimate+ Deluxe` are **invite-only / closed source** — no source is
obtainable. The upstream indicator also defaults to "Hide Losing Setups", which erases losing trades from the
chart after the fact; the open-source `cantolab` reimplementation can show them. Never reproduce that
erasure behaviour — failed setups must remain in logs and training data.

## Market data lake
`smb://192.168.1.6/iflow/database`. Any incremental download must satisfy the governance standard defined
in `github.com/jssyxd/dataBaseLake` and be marked 可用 / 可入湖 before use.
Binance and OKX official history plus cryptohftdata.com are the supplemental sources for crypto coverage.

## 2026-11-22 — verified local state after the fetch wave
- `research/github/`: `IFVG-Ultimate-Dodgy` (single file `ifvgUltimatePlus.pine`, 31 KB), `AlphaGPT`,
  `AlphaGPT-By-imbue-bit`, `qlib` (blobless clone, 15 MB), `dataBaseLake` (4 stage dirs
  `01_raw_lake`/`02_pipeline_engine`/`03_governed_lake`/`04_strategies` + `bootstrap_lake.py` +
  `incremental_update.py` + `data_sources.json` + `GOVERNANCE_TIMESTAMP_ALIGNMENT.md`).
- `research/huggingface/`: `nq-fvg-detector` (`best.pt` 44 MB, README 1.3 KB), `xauusd-ml-trader`
  (full `xauusd_trader/` package, 15 py files), `ict-6000-mentorship-master`
  (`data/train-00000-of-00001.parquet`, 1.1 MB).
- `research/kaggle/`: `nq-fvg-dataset` (**295 chart JPGs + YOLO labels**, NOT OHLCV), `gold-xauusd-smc-trading-data`
  (`XAUUSD_15M_SMC_Data.csv`, 4502 rows, 2026-07-14 → 2026-09-22), `fvgnet-manifest.txt`.

## 2026-11-22 — the vision-layer contradiction is now a measured fact
`ibtsam/nq-fvg-detector` README states verbatim: *"Trained on white background TradingView charts only."*
Its training set (`nq-fvg-dataset` on Kaggle) is **640×640 white-background TradingView charts with a grid**,
teal/black candles, no axes. The design doc demands a **black-background 224×224** render.
Measured from the Kaggle YOLO labels (3650 boxes): median normalised box is **w 0.0086 × h 0.0258**, i.e.
**5.5 × 16.5 px at 640×640** but only **1.9 × 5.8 px at 224×224**. A 0.75 IoU gate is not achievable at
224×224. Render at 640×640, white background, matching the model's training distribution.

## 2026-11-22 — Kaggle `nq-fvg-dataset` is an image dataset, not a price dataset
`research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/` contains `train|valid|test` dirs of **chart JPGs** plus YOLO
label `.txt` files and `labels.cache`; `data.yaml` declares `nc: 2`, `names: ['bearish_fvg','bullish_fvg']`.
There is **no OHLCV**. It can ground-truth FVG *detection* but cannot drive a profitability backtest.
The only tabular dataset is the XAU/USD 15-minute CSV (4502 rows) with boolean
`Bullish_FVG`/`Bearish_FVG`/`Bullish_OB`/`Strong_Bullish_Move`/`Is_Bearish` columns and a `Body_Size` column —
~2 months of XAUUSD, not NQ.

## 2026-11-22 — the open iFVG replica contradicts the design doc on six points
`research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` (694 lines, Pine v6, `indicator()` not
`strategy()`) is the only executable statement of the rules. Verified by reading the source:
1. **No ATR filter.** `grep -ci atr` = 0. The doc's `0.25 * ATR(14)` minimum-gap rule does not exist here.
2. **No SMT divergence.** `grep -ci smt` = 0. No cross-instrument reference at all.
3. **No scoring / no A+..C grades.** `grep -ci "score\|grade\|A+\|checklist"` = 0. The doc's checklist
   and grading system is **not** in this replica.
4. **The confirmation window is a switch, not a 7–15 range.** `int graceCandles = allowExtIFVG ? 15 : 6`
   (line 658). The tooltip says *"If enabled, IFVGs may form within 15 candles. If disabled, they must form
   within 6 candles."* The doc's "7–15 根 K 线内" is a misreading of the label "Allow 7 - 15 Candle IFVGs".
   The window is measured from `e.fvgBar1` (line 499: `bar_index - e.fvgBar1 > graceCandles`).
5. **The sweep filter is OFF by default.** `onlyShowSweptIFVG = input.bool(false, ...)` (line 11). The doc
   treats the liquidity sweep as a mandatory precondition; the reference script only *optionally* requires it.
6. **Session windows gate ALERTS, not signals.** `inAlertSession` is used only at line 497 to fire
   `alert(...)`. Setups are computed on every bar. Defaults: session1 `"0930-1600"` (enabled),
   session2 `"2000-0000"` (disabled), session3 `"0200-0500"` (disabled) — note these are RTH/overnight, not
   the doc's "NY AM 09:30–11:30 / NY PM 13:30–15:30" killzones.

Other verified mechanics worth porting:
- **FVG geometry** (line 355): `fvgHere = isLow ? low[1] > high[3] : high[1] < low[3]` — 3-candle gap
  using bars 1 and 3, with `fvgBar1 = bar_index-1`, `fvgBar3 = bar_index-3`.
- **Inversion trigger** (line 437): `close[1] > e.fvgTop` (bullish source) / `close[1] < e.fvgBottom`
  (bearish source) — a **body close strictly beyond the far edge**, evaluated on `close[1]` (the previous
  closed bar), so the setup is drawn one bar after confirmation.
- **BE gate** (line 442): `beBreached = requireBEIntact and (ifvgBullish ? lvl >= e.swingPrice : lvl <= e.swingPrice)`
  — setups whose confirmation close already reached the swing level are **silently dropped** (default ON).
- **Stop loss** (line 462): `ict_ScanExtreme` finds the worst wick between `fvgBar1` and now;
  `slPlacement` options `Wick` (default) / `Body` / `IFVG`.
- **Break-even** (line 476): `tr.bePrice := e.swingPrice` — BE is the swing pivot price.
- **RR** (line 313): `riskRange = abs(entryPrice - slPrice)`, targets at `entry ± riskRange * r`,
  default `rrInput = "1,2"`.
- **Signal erasure** (line 519): `if hideLosing` (default **true**) deletes the box/line/label and removes
  the record from `setupRecords` when the stop is hit. This is the "Hide Losing Setups" behaviour the
  design doc warns about — our implementation must keep losers visible and labelled.

## 2026-11-22 — xauusd-ml-trader: what is reusable and what is not
`research/huggingface/xauusd-ml-trader/xauusd_trader/` (15 py files, pandas + XGBoost, no Nautilus).
- **Reusable as-is (copy the functions, keep the semantics):**
  `strategies/smc_strategy.py::detect_liquidity_sweeps` — bullish sweep = `low < last_swing_low and
  close > last_swing_low` (wick pierces, body does not), depth normalised by ATR; `detect_fvg` —
  `low[i] > high[i-2]` / `high[i] < low[i-2]`, i.e. the *same* 3-candle geometry the design doc specifies;
  `data_loader.py::add_atr` (period 14), `add_session_labels` (session filter helper);
  `backtesting/wfo_engine.py::compute_trade_metrics` (PF / win-rate / drawdown aggregation).
- **Must be rewritten:** the entry. `generate_ob_entry_signals` is an order-block-tap limit-order strategy
  (entry at the OB 50% equilibrium, SL behind the OB wick, TP at `tp_rr_ratio`=2.5). The iFVG entry is the
  opposite construct — a **market/stop entry after the FVG is closed through by a body**, then a retest.
- **Do NOT reuse the ML layer:** `ml/ensemble_model.py::create_labels` makes a **3-class directional label**
  (1=Buy / -1=Sell / 0=Hold) from forward returns. That is exactly the overfitting-prone approach the
  design doc rejects; our meta-label must be **binary** (1 = reached 2R TP, 0 = stopped out) with the rule
  engine owning direction. Its `TradingEnsemble` (XGBoost) is also not LightGBM, and it has an online
  retrain path (`_incremental_retrain`) that is unsuitable for a purged walk-forward regime.
- **Framework mismatch:** everything is vectorized pandas with `df.iloc[i]` loops and forward-shifted labels
  — the future-function risk the NautilusTrader decision was meant to eliminate. Useful as a *logic
  reference* for the sweep/FVG predicates; not as an engine.

## 2026-11-22 — the reference replica's author concludes the strategy has NO value
`research/github/IFVG-Ultimate-Dodgy/README.md` is the most decision-relevant document in this repo.
Canto Lab reverse-engineered the closed-source "iFVG Ultimate+ | DodgysDD" from the author's public
videos and states, verbatim:
- *"**So does the strategy have any value?** NO"*
- *"Dodgy is a classic example of a hindsight trader — his own explanations contradict each other depending
  on how the trade played out."*
- *"He hides invalidated IFVGs… it just removes losers after the fact it has happened. You have no way to tell
  that apart from a real loss when you're trading it live."*
- *"He isn't consistent about where his stop actually is… Both explanations get used depending on which one
  makes the trade look better after the fact, not based on a fixed rule stated up front."*
- *"This indicator is constantly scanning for setups, and that's a bad thing. Price is always forming FVGs, if
  there's a swing, there's basically always an FVG in it. And given enough time, that FVG will always become
  an IFVG."*
- *"The only thing his model does to control for this is require the FVG to invert within 7–15 candles, which
  cuts down the number of setups shown, but **doesn't meaningfully increase how often they actually work out**."*
- *"I also built HTF sweep confirmation into IFVG detection (turn on in settings) expecting it to clean things
  up. Setup quality barely changed, if anything it looked slightly worse. So I didn't bother coding HTF FVG
  confluence or SMT on top of it, especially since he takes trades without them as well."*
- *"Setup grade box — left out entirely. Dodgy himself has said the grading is mechanical, meaning there's a
  fixed set of rules generating the grade that doesn't imply actual grade."*

**Consequence for our plan:** the four-layer design doc assumes the rule layer is a high-quality signal
generator that ML merely *filters*. This README says the rule layer is an over-generating scanner whose
only quality lever is the inversion window, and that the author of the original trades it *without* SMT or
HTF-confluence — i.e. without the very filters the design doc makes mandatory. The design doc's own phase-1
gate (pure-rule PF > 1.25) is exactly the test that would settle this, and it must be run **before** any ML
is built. Treat the phase-1 negative result as a likely outcome to be *measured*, not an impossibility.

Note the "7–15 candles" phrase in the README matches the doc, while the code is
`graceCandles = allowExtIFVG ? 15 : 6` — an **upper bound only**, with **no lower bound**. Because the
trigger is evaluated with `close[1]`, the inversion may be confirmed on the FVG's own newest candle
(age 0), so the real window is **[0, 15] bars from `fvgBar1`** (or [0, 6] with the toggle off). The doc's
"7–15" lower bound **does not exist in code**. Full derivation: `research/analysis/PINE_RULES.md` §R13–R15,
§D.1.

## 2026-11-22 — the data lake ALREADY has NQ + ES 1-minute continuous futures
`research/github/dataBaseLake/03_governed_lake/v2_parquet_lake/manifest/manifest.json` (v2.1.0,
`last_updated_utc` 2026-10-20) declares in `catalog.us_futures.symbols`:
- `NQ` — "E-mini Nasdaq 100 Continuous Futures", path `us_futures/NQ/`, timeframes
  **`1m, 5m, 15m, 1h, 2h, 4h, 1d`**
- `ES` — "E-mini S&P 500 Continuous Futures", path `us_futures/ES/`, same timeframes
- also `MBT` (Micro Bitcoin Futures CME) and `MET` (Micro Ether Futures CME) — the crypto leg of the
  migration table, at `5m` and above only
- `us_equities`: `SPY`, `QQQ`, `TQQQ` at 1m — a possible SMT/QQQ substitute
- `global_futures`: `NK225`, `HSI`, `FDAX`, plus commodities/rates incl. gold

**So NQ 1m + ES 1m continuous futures — the exact phase-1 requirement — are already governed and
available.** No Databento purchase is needed. The blocker is *access*, not supply:
- the git clone has `03_governed_lake/v2_parquet_lake/us_futures/` **empty except `.gitkeep`** — the binary
  Parquet is gitignored, so it exists only on the SMB share `smb://192.168.1.6/iflow/database`.
- `192.168.1.6` responds to ICMP (12.6 ms) from this machine, but **no SMB mount is present** (`mount |
  grep cifs` is empty; `/mnt` contains only `t6`). The lake must be mounted or copied before phase 1.

**Governance contract (from `03_governed_lake/v2_parquet_lake/manifest/manifest.json` and the README):**
- time index = **UTC int64 milliseconds, left-aligned bar open time**; `lookahead_bias_guarantee: true`
- storage = Parquet, **Zstd level 7**, row group target 100000, readable by Polars / DuckDB / PyArrow / Pandas
- mandatory columns: `timestamp` (int64 ms), a human-readable ISO UTC datetime, `open`, `high`, `low`,
  `close`, `volume` (+ crypto-only quote volume and taker-buy volume / CVD)
- **five mathematical invariants** every promoted dataset must pass: (1) strictly monotonic UTC timestamps,
  (2) total de-duplication, (3) bar geometry `High >= max(Open,Close)` and `Low <= min(Open,Close)`,
  (4) all prices > 0, (5) volume >= 0 — plus (6) real-break governance: genuine gaps are recorded in
  `defects.json` and **forward-fill synthetic interpolation is forbidden**; stock/futures bars are aligned
  strictly to the exchange calendar.
- audit command: `python incremental_update.py --audit`; incremental pull:
  `python incremental_update.py --symbols BTCUSDT ETHUSDT QQQ SPY CMC20`
- reader: `from database.03_governed_lake.v2_parquet_lake.tools.db_loader import load_data` then
  `load_data("NQ", timeframe="1m", engine="polars")` (~1–2 ms per load).

## 2026-11-22 — xauusd-ml-trader has silent look-ahead; port the logic, not the code
`research/analysis/ML_REUSE.md` §A found two defects that must be fixed during any port:
- the swing-point detector uses a **centered** window, so the swing high/low it returns is not known at
  the bar where it is used;
- order blocks are registered **before** the displacement that creates them.
Either one silently inflates the profit factor — exactly the failure the NautilusTrader decision was
meant to prevent. The port must emit a `known_at` timestamp per signal.
Also: its session helper documents UTC but implements exchange-local time (a 4-hour mislabel of every
session gate) and its headline numbers are **cost-free**, so they are not a baseline.
Correct reuse decision: **ADAPT** (≈2–2.5 engineer-days for a causal, futures-correct
sweep/FVG/session/sizing foundation), not "copy".

## 2026-11-22 — the design doc's stated reasons for rejecting AlphaGPT/Qlib are wrong
The doc rejects both because they are "cross-sectional stock-ranking frameworks" that compute IC/RankIC.
`research/analysis/ML_REUSE.md` §B/§C shows the **real** reasons are stronger:
- **AlphaGPT has no IC/RankIC anywhere.** Its fitness is a dense cross-sectional P&L over a hard-wired
  crypto-meme feature set (`liquidity`, `fdv`); its live layer is a Solana on-chain bot. Pointing it at
  our event timestamps means replacing the feature engineer, the target, the fitness and the sampling.
- **Qlib has no futures support at all**: equity-only `Exchange` (price limits, suspension, round lots,
  T+1 cash settlement), **long-only** `Position` (no shorts), canonical strategy = cross-sectional top-k
  ranking, label = forward return scored by IC/RankIC. Its rolling machinery is inseparable from Qlib's
  calendar + dataset + **YAML** config (against our JSON-only rule) and drags in mlflow/redis/mongo.
- Reimplementing our purged walk-forward costs ≈1 day vs ≈3–6 days to adopt Qlib's — so take the
  *concept* (expanding monthly folds, tail truncation/purge, concatenated OOS predictions) and
  reimplement it with an explicit embargo.

## 2026-11-22 — the ICT reasoning dataset is a synthetic 4-gate checklist, not a detector
`ict-6000-mentorship-master`: the 4,000-row "Audit" subset (2,287 fully parseable) is an arithmetically
exact 4-gate rule corpus — time-window whitelist, liquidity purge asserted, displacement asserted,
equilibrium/premium-discount/FVG position arithmetic — with 756 hard-negative time rows. But gates 2–3
are **asserted, not derived from bars**, prices are fabricated, and **SMT Absent still yields VALID**, so
SMT is *not* mandatory in that corpus — a deviation from our checklist, which must be recorded.
Use it as a **test-vector corpus** (`tests/fixtures/ict_audit_cases.json`), not as training data and not
as a detector.

## 2026-11-22 — the lake's own manifests CONTRADICT each other on NQ/ES 1-minute bars
Two manifests in `research/github/dataBaseLake/` disagree, and the disagreement decides whether phase 1
can start:
- `03_governed_lake/v2_parquet_lake/manifest/manifest.json` (v2.1.0) advertises
  `catalog.us_futures.symbols.NQ/ES` with timeframes `1m, 5m, 15m, 1h, 2h, 4h, 1d`.
- `03_governed_lake/nautilus_databank/MANIFEST.md` is the index of **actually materialised** data —
  63 BarTypes / 42,278,836 bars / 1.02 GB, storage root `…/iflow/数据库5/nautilus_databank`,
  coverage 2020-01-01→2026. Its universe table lists **only**
  `NQ.CME-1-DAY-LAST-EXTERNAL` and `ES.CME-1-DAY-LAST-EXTERNAL` (1,695 daily bars each, 2020→2026).
  The 1-minute bar types it indexes are crypto, FX, metals and **US equities/ETFs**
  (QQQ 1.3 M bars, SPY 1.28 M, IWM 1.12 M) — **no CME 1-minute index futures**.
So the parquet manifest's 1m claim is **aspirational, or the 1m partitions exist only on the share and
were never back-filled into the databank**. A 5-minute check on the mounted share settles it — see
`research/analysis/DATA_FEASIBILITY.md` §B2 step 4. **Do not promise phase 1 until that check passes.**

## 2026-11-22 — Kaggle datasets: both are unusable for a backtest
- `nq-fvg-dataset` = **295 chart JPGs + YOLO labels, no OHLCV**. It can ground-truth FVG *detection*
  and train/validate the vision layer. It cannot drive a profitability backtest.
- `gold-xauusd-smc-trading-data` = **4,502 rows of XAUUSD 15-minute bars, 2026-07-14 → 2026-09-22**
  (~10 weeks) with boolean `Bullish_FVG`/`Bearish_FVG`/`Bullish_OB`/`Strong_Bullish_Move`/`Is_Bearish`
  and a `Body_Size` column. Useful as a **geometry unit-test oracle** for the FVG detector, not as
  backtest data (wrong symbol, ~2 months, no ES counterpart, no session markers).

## 2026-11-22 — the gold Kaggle dataset's FVG labels are NOT reproducible from its own OHLC
Measured directly on `research/kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv`
(4,502 rows, XAUUSD 15m):
- the standard 3-candle **wick** gap (`low[i] > high[i-2]` / `high[i] < low[i-2]`) fires on 977 bars and the
  label columns are True on 977 bars — **the same count** — but only **210 overlap** (21%), and only **115
  agree on direction** while 95 are the *opposite* direction. The offset distribution is flat
  (+2:361, 0:210, −1:158, +1:150, −2:98), so it is not a simple index shift.
- a **body** gap (`close[i] > open[i-2]`) gives **recall 0.996** (973/977 labelled bars) but 4,471 events
  (precision 0.218) — the labels are a ~22% subset of body gaps.
- no size filter reconciles it: sweeping a gap threshold from 0.5 to 10, and ATR-normalised thresholds
  from 0.5×ATR(14) to 3×ATR(14), never exceeds precision 0.24.
- 247 adjacent same-direction label pairs indicate the labels are **forward-filled** (event flags smeared
  forward), which is exactly the pattern that breaks nearest-neighbour label joins.
**Conclusion:** this dataset is **not** a geometry oracle for our FVG detector as-is — the author computed
the labels on a different (likely higher-resolution or un-resampled) series. It remains usable only as a
*statistical smoke test* (does the detector fire at a plausible rate?), not as ground truth.
This **contradicts** `research/analysis/DATA_FEASIBILITY.md` §C2, which called it a "geometry unit-test
oracle"; that claim needs correcting. The label columns are forward-filled booleans, so they must never be
joined to bars by exact timestamp.

## 2026-11-22 — the doc's IoU > 0.75 vision gate is UNREACHABLE BY CONSTRUCTION
Measured by the vision audit against the detector's own ground truth (`research/analysis/VISION_AUDIT.md`
§C):
- The Kaggle annotations are boxes around the **third candle's BODY**, not around the price gap. So for a
  bullish FVG `gap = [high_{i-2}, low_i]`, the third candle's body lies at or above `gap_high` ⇒
  **body ∩ gap = ∅**; symmetrically for the bearish case. The two objects are **disjoint by construction**.
- Under the doc's literal 1-D vertical interval IoU, a **perfect** detection therefore scores **0.00**,
  not 1.00. Measured on the model's own labels: median IoU **0.0000**, **87.9 % exactly zero**, only
  **0.65 % above 0.75**. Any threshold on that metric is noise.
- Under a 2-D box IoU against the FVG's 3-bar x-range, a perfect match is capped at
  `width(B)/width(R) = 1/3` (the detector's box is one bar wide; the rule rectangle is three bars wide) —
  a bound that is independent of resolution and window size.
- **The only self-consistent definition is a 2-D box IoU against the third candle's BODY rectangle**
  (perfect match = 1.0), i.e. the gate becomes *"the vision model independently localises the same bar"*
  — a cross-check on the rule engine's geometry. It cannot verify "clean price action"; that is not
  something a box detector can express.
- Suggested threshold: start at **IoU_box ≥ 0.5** and calibrate on the Kaggle **test** split (44 images).
  Given the model's `mAP@50-95 = 57.4 %`, its box corners are already loose and 0.75 may leave too few
  survivors. Do not inherit 0.75 unexamined.
Also confirmed: the detector wants a **white 640×640** render, not the doc's black 224×224, and at 224×224
the median box is 1.9 × 5.8 px.

## 2026-11-22 — CORRECTION: the lake is LOCAL at `/home/da/桌面/database/`, and NQ/ES 1m DOES exist there
The SMB share was a red herring: the governed lake is a local checkout. Corrected facts (measured):
- `03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/1m/` **contain 1-minute partitions** — but only
  **7,490 / 7,489 rows covering 2026-09-24 -> 2026-10-01** (one week), sourced from Yahoo Finance, whose
  1-minute history window is ~30 days. The lake's `scripts/govern_us_assets_lake.py` supports only
  `1d / 1h / 30m`, so the lake's own tooling cannot extend 1m.
- **CORRECTION to my earlier note**: NQ/ES volume is NOT all zero. Only **7 (NQ) / 6 (ES)** of ~7,490 bars
  have `volume == 0`, and every one of them is **non-flat** (OHLC differ) — which violates the lake's flat-bar
  rule ("volume == 0 implies O=H=L=C"). The lake's `incremental_update.py::verify_mathematical_invariants`
  only checks `volume < 0`, so **it cannot detect this class of violation**. Do not trust a clean audit
  report to mean the flat-bar rule holds.
- The lake's deep multi-year lanes are: `crypto/futures_um/ETHUSDT/15m` (2020-01 -> 2026-10),
  `crypto/futures_um/BTCUSDT/15m` (2024-01 -> 2026-10), `us_equities/QQQ/15m` (2022-10 -> 2026-10),
  and `crypto/high_frequency_lob/BTCUSDT/BTCUSDT_1m_3years_governed.parquet`
  (**1,636,229 1m bars, 2023-01-01 -> 2026-02-14**, with `bar_ofi`, `parkinson_vol`, `garman_klass_vol`,
  `atr14`) — the last is the missing RL order-book-imbalance state, already governed.
- `lake_audit`: `python incremental_update.py --audit` -> **1248/1250 files pass**; the 2 failures are
  pre-existing (a vendored third-party dataset and a 3-row anomaly in `ZN_1d`).

## 2026-11-22 — E-1 REVISED: the "significant" result was a concurrency artefact
The first E-1 implementation opened **one position per candidate** (unlimited concurrency). That is a
signal census, not a portfolio: the trades overlap heavily, so they are strongly correlated and the
iid t-statistic is inflated.
Measured on the **full governed-lake BTCUSDT 1-minute dataset** (2,046,240 bars, 2023-01-01 ->
2026-11-21, gap-free, ingested this session from Binance Vision):
- `concurrent`: n=423,759, E[R]=+0.033, **t=15.28**, CI [+0.029,+0.038]  <- looks significant
- `one-at-a-time`: n=15,928, E[R]=**-0.020**, **t=-1.76**, CI [-0.042,+0.002]  <- no edge
Across all 32 arms the one-at-a-time expectancy spans **-0.024 R to +0.014 R**, every CI includes
zero, **PF never exceeds 1.051** (gate: > 1.25), and with a 0.05 R round-trip cost **every arm is
negative**. The sign flips across the fill arm in every parameter group.
(On the 7-month partial run the same picture held: concurrent t=9.08 vs one-at-a-time t=-0.33.)
Earlier measurement on real BTCUSDT 1-minute bars (305,280 bars, 2023-01->2023-07, from the governed lake):
- `concurrent`: n=63,308, E[R]=+0.052, **t=9.08**, CI [+0.041,+0.063]  <- looks significant
- `one-at-a-time`: n=1,693, E[R]=**-0.011**, **t=-0.33**, CI [-0.078,+0.056]  <- no edge at all
Every one-at-a-time arm has a 95 % CI that includes zero, and with a 0.05 R round-trip cost **every
one-at-a-time arm has net expectancy <= +0.002 R**. The measured gross edge (0.052 R) is **smaller than
a realistic NQ round trip** ($14.50-$24.50 = 0.036-0.245 R depending on stop distance).
**Rule: any backtest of a signal generator must hold at most ONE position at a time, and its
significance must be quoted from that arm.** The census arm is fine for counting how often a pattern
fires and for nothing else.
Corrected write-up: `research/experiments/E1_RESULTS.md` (rev. 2).

## 2026-11-22 — E-1 EXECUTED (SUPERSEDED BY THE ENTRY ABOVE — see rev. 2): the rule engine shows NO edge on the only data in this repo
`research/experiments/e1_rule_falsification.py` (run it; raw output in `E1_RAW_OUTPUT.txt`, write-up in
`E1_RESULTS.md`). Data: the gold Kaggle XAUUSD **15-minute** CSV, 4,502 bars, 2026-07-14→2026-09-22,
**not** using its (forward-filled, irreproducible) FVG label columns. 16 pre-registered arms.
Result:
- **No arm reaches the phase-1 gate.** Best arm **PF = 1.193 cost-free**; the gate demands **> 1.25
  after** ~$4.50 fees and 1–2 ticks of slippage. The gate fails *before* any cost is charged.
- **No arm is statistically distinguishable from zero** — every 95 % CI on E[R] includes zero;
  the largest |t| is 1.22 (p≈0.22).
- **The edge is smaller than the cost of trading NQ.** The best arm absorbs only **0.121 R** of
  round-trip cost. For NQ (tick 0.25 pt = $5.00, multiplier $20) the doc's ~$4.50 fee + 1–2 ticks is
  **$14.50–$24.50**; at a $200 stop that is 0.073–0.123 R, i.e. the edge is **entirely consumed**
  below roughly a **6–10 NQ point** stop.
- **The sign flips** across arms for the code[0,15] window (+0.046 / −0.017 / +0.046 / −0.017);
  only the doc[7,15] window is sign-stable, and one of its four combinations is exactly 0.000.
- 977 raw 3-candle FVG events (490 bull / 487 bear); 554 invert within 15 bars; 568/492/242/216
  closed trades per arm.
**Consequence:** phase 2 (ML) must not start. The blocker is **data**, not models. E-2 (NQ+ES 1-minute,
≥600 trades/arm, PF at 0/1/2 ticks, 95 % CI on expectancy) is the deciding experiment.

## 2026-11-22 — the lake is LOCAL and the SMB share was a red herring
The governed lake is a local checkout at `/home/da/桌面/database/` (same `dataBaseLake` layout:
`01_raw_lake` -> `02_pipeline_engine` -> `03_governed_lake` -> `04_strategies`, plus
`bootstrap_lake.py`, `incremental_update.py`, `data_sources.json`, `catalog/`, its own `AGENTS.md`).
`smb://192.168.1.6/iflow/database` is reachable but rejects every credential tried
(`NT_STATUS_LOGON_FAILURE`) and no CIFS/GVFS mount exists on this host.
**Ask for the local path first**; do not burn time on SMB auth.

## 2026-11-22 — this host's egress is capped at ~69 KB/s and parallelism does NOT scale
Measured: 8 parallel Binance Vision downloads -> 14.18 MB in 200 s (69 KB/s aggregate); a single
connection -> ~56 KB/s. Plan every bulk download against a 69 KB/s budget:
- 3.33 GB (Twelve Data `bars_1min/train.parquet`) = ~13 h -> use HTTP Range + Parquet columnar
  pushdown instead (see `research/analysis/DATA_ACQUISITION.md`).
- 175 MB (Binance Vision monthly 1m klines, 2 symbols x 46 months) = ~42 min -> acceptable.
- 62 GB (cryptohftdata tick archive) = ~10 days -> never.
Transfers are also lossy: `urlopen` frequently raises `IncompleteRead`; always resume with a
`Range` header and verify the byte count.

## 2026-11-22 — the 1-minute CME ceiling is real and now measured
| Source | Result |
|---|---|
| Yahoo `NQ=F` | `range=1mo` -> HTTP 422; `15d` -> 422; `7d` -> truncated body; **`2d` -> 795 bars OK**. The lake's 1m ends 2026-10-01 and the 7-week gap to today is unrecoverable free. |
| cryptohftdata | **no `candles` family** (404 on every date); tick archive starts ~2025-07. |
| OKX `history-candles` | 100 bars/request -> ~14,000 requests per symbol for 3 years (~13 h). |
| Twelve Data `financial-world-model` | **has NQ at 1m**; `bars_1min/train.parquet` = 3.33 GB, 51 row groups, 18.2 M rows. Pull it by **columnar pushdown over HTTP Range**, not by download. |
| HF `mito0o852/OHLCV-1m` | 129 **stock** tickers only. |
So multi-year CME 1m is either Twelve Data (free, awkward) or **Databento (~$10-30, what the design
doc recommends)**. There is no third option.

## 2026-11-22 — Yahoo and Binance Vision both need a specific UA / endpoint shape
Yahoo's chart API needs `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)` and returns
**HTTP 422** when the requested window exceeds the interval's retention; it also intermittently
resets the connection and can return a truncated body that breaks `json.loads`. Binance Vision needs
`.../data/futures/um/monthly/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM>.zip`.

## 2026-11-22 — Binance Vision funding-rate archives use a 3-column layout
`calc_time,funding_interval_hours,last_funding_rate` (a 4-column legacy layout with `mark_price`
also exists). The lake's existing funding partitions (DOGEUSDT/SOLUSDT/SUIUSDT) use columns
`calc_time, funding_interval_hours, last_funding_rate, ts_utc, rate` — match that exactly.
