# Baseline matrix, 2026-11-24 — 5 symbols x 7 timeframes x 2 presets

The first complete baseline sweep on the new higher-timeframe lanes
(`research/analysis/DATA_LANES_2026-11.md`).  **Rule layer only** — no model is
loaded, so every `p_win` is NaN and `gate_approved` is False by construction;
that is what makes the numbers below attributable to the rules and the costs
rather than to a classifier.

## Configuration

* symbols BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT;
* timeframes 5m, 15m, 30m, 1h, 2h, 4h, 1d (the resampled lanes, 2023-01 →
  2026-10/11);
* presets `honest` (code-derived core, reference look-ahead removed) and `doc`
  (ATR gap floor + the doc's filters);
* regime DVOL (lagged), SMT reference BTCUSDT (ETHUSDT for the BTC cell);
* cost: Binance 0.08 % round trip + **1 tick of each symbol's own tick**
  (BTC 0.1, ETH/SOL/BNB 0.01, XRP 0.0001);
* horizon: 60 hours, but never fewer than **20 bars** (otherwise 4h/1d cells
  cannot resolve a 2R target and report NaN);
* accounting: one position at a time, drop (D4).

Reproduce with::

    python -m dodgys_dd_quant.backtest.matrix \
        --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT \
        --timeframes 5m 15m 30m 1h 2h 4h 1d \
        --presets honest doc --horizon-minutes 3600 \
        --out artifacts/matrix_2026-11-24

## The archive (gitignored, on disk)

| file | rows | contents |
|---|---|---|
| `artifacts/matrix_2026-11-24/runs.parquet` | 70 | one row per cell: config, sample, TradeStats, Sharpe/DSR, kill-switch level, abort criteria fired/evaluated |
| `artifacts/matrix_2026-11-24/candidates.parquet` | 211195 | **every candidate iFVG, taken or not** | 
| `artifacts/matrix_2026-11-24/folds.parquet` | 0 | empty: a rule-only cell has no folds |
| `artifacts/matrix_2026-11-24/manifest.json` | — | command, commit, lake root, counts |

`candidates.parquet` has **57 columns**: the 35 `Candidate` fields (geometry,
bar indices, outcome, `r_multiple`, `p_win`), the run identity, `ts_utc` and an
exact `ts_event_ms`, the engine's label `y` (1 target / 0 stop / −1 not
resolved), `selected` (the one-position portfolio's decision), `gate_approved`
and `fold_asof` (both inert in this baseline), and **all features** —
`checklist_score`, `smt_divergence`, `vxn_level`, `vxn_regime`,
`bars_to_inversion`, `minutes_from_us_open`, `vision_*`, plus the causal
extras `atr14`, `risk_atr`, `gap_atr`, `volume_zscore_60`.

Population: **211195 candidates, 60945 selected by the one-position portfolio**
(so 71 % of the signals exist only because they were recorded, not traded —
exactly the population `hideLosing` deletes upstream).

Label balance: 70,471 targets / 134,515 stops / 6,209 unresolved
(``y = -1``: censored or break-even) over the cells that produced signals.

## Aggregate

**15 of 70 cells are net-positive**, and the median cell is negative in every
timeframe except 30m (doc: +0.0089).  Median E_net by timeframe:

| preset | 5m | 15m | 30m | 1h | 2h | 4h | 1d |
|---|---|---|---|---|---|---|---|
| `honest` | -0.1903 | -0.0767 | -0.0966 | -0.0906 | -0.1768 | -0.1142 | -0.1498 |
| `doc` | -0.1753 | -0.0700 | +0.0089 | -0.1871 | +0.1365 | -0.0588 | n/a |

**Multiple testing.** 70 cells were evaluated; the best gross t-statistic in
the matrix is XRPUSDT 30m `honest` (+0.1198 R, n=1116, t = +2.66), which
corresponds to a one-sided p ≈ 0.004 — with 70 trials the expected number of
cells that extreme is ≈ 0.26, so it is **not** evidence after the trial count.
The 30m cells as a group (4 of the top 5) are the only pattern worth a
pre-registered follow-up, not a result.

## Full matrix

### preset `honest`

| symbol | tf | n | win % | E[R] | E_net | PF | t (gross) | kill | abort |
|---|---|---|---|---|---|---|---|---|---|
| BNBUSDT | 15m | 2363 | 34.8 | +0.0046 | -0.1353 | 1.007 | +0.16 | K3 | A1 |
| BTCUSDT | 15m | 2124 | 36.2 | +0.0439 | -0.1073 | 1.069 | +1.42 | K3 | A1 |
| ETHUSDT | 15m | 2101 | 36.5 | +0.0591 | -0.0555 | 1.093 | +1.88 | K3 | A1 |
| SOLUSDT | 15m | 2183 | 34.9 | +0.0129 | -0.0767 | 1.020 | +0.43 | K3 | A1,A4 |
| XRPUSDT | 15m | 2008 | 35.9 | +0.0402 | -0.0656 | 1.063 | +1.25 | K3 | A1 |
| BNBUSDT | 1d | 39 | 26.3 | -0.2895 | -0.3036 | 0.607 | -1.03 | K3 | A1,A4 |
| BTCUSDT | 1d | 39 | 35.7 | +0.0179 | +0.0039 | 1.028 | +0.07 | K3 | A4,A5 |
| ETHUSDT | 1d | 36 | 8.3 | -0.7708 | -0.7790 | 0.159 | -4.84 | K3 | A4 |
| SOLUSDT | 1d | 1 | nan | +nan | +nan | nan | +nan | none | - |
| XRPUSDT | 1d | 35 | 38.1 | +0.0476 | +0.0355 | 1.077 | +0.16 | K3 | A5 |
| BNBUSDT | 1h | 728 | 30.7 | -0.1173 | -0.1895 | 0.831 | -2.13 | K3 | A4 |
| BTCUSDT | 1h | 650 | 34.3 | -0.0112 | -0.0906 | 0.983 | -0.19 | K3 | A1,A2,A4 |
| ETHUSDT | 1h | 655 | 30.7 | -0.1035 | -0.1631 | 0.851 | -1.77 | K3 | A1,A4 |
| SOLUSDT | 1h | 13 | 45.5 | +0.2727 | +0.2488 | 1.500 | +0.61 | none | - |
| XRPUSDT | 1h | 636 | 35.3 | +0.0239 | -0.0355 | 1.037 | +0.38 | K3 | A1 |
| BNBUSDT | 2h | 442 | 33.3 | -0.0408 | -0.0940 | 0.939 | -0.51 | K3 | A1,A4 |
| BTCUSDT | 2h | 389 | 30.1 | -0.1545 | -0.2137 | 0.779 | -1.86 | K3 | A1,A4 |
| ETHUSDT | 2h | 418 | 29.8 | -0.1543 | -0.2034 | 0.780 | -1.97 | K3 | A4 |
| SOLUSDT | 2h | 411 | 30.5 | -0.1382 | -0.1768 | 0.801 | -1.74 | K3 | A1,A2,A4 |
| XRPUSDT | 2h | 367 | 36.7 | +0.0362 | -0.0061 | 1.057 | +0.39 | K3 | A1 |
| BNBUSDT | 30m | 1234 | 33.5 | -0.0330 | -0.1313 | 0.950 | -0.80 | K3 | A1,A4 |
| BTCUSDT | 30m | 1137 | 35.0 | -0.0068 | -0.1084 | 0.990 | -0.16 | K3 | A1,A4 |
| ETHUSDT | 30m | 1129 | 37.3 | +0.0854 | -0.0002 | 1.136 | +1.91 | K3 | A1 |
| SOLUSDT | 30m | 1230 | 33.5 | -0.0297 | -0.0966 | 0.955 | -0.73 | K3 | A1,A4 |
| XRPUSDT | 30m | 1116 | 38.6 | +0.1198 | +0.0453 | 1.195 | +2.66 | none | - |
| BNBUSDT | 4h | 239 | 26.9 | -0.2462 | -0.2854 | 0.663 | -2.23 | K3 | A4 |
| BTCUSDT | 4h | 219 | 34.9 | -0.0138 | -0.0523 | 0.979 | -0.10 | K3 | A1,A4 |
| ETHUSDT | 4h | 224 | 29.9 | -0.1453 | -0.1761 | 0.793 | -1.18 | K3 | A1,A4 |
| SOLUSDT | 4h | 1 | nan | +nan | +nan | nan | +nan | none | - |
| XRPUSDT | 4h | 211 | 35.8 | +0.0229 | -0.0083 | 1.036 | +0.17 | K3 | A1 |
| BNBUSDT | 5m | 6638 | 35.0 | +0.0013 | -0.2465 | 1.002 | +0.08 | K3 | A1 |
| BTCUSDT | 5m | 5848 | 36.0 | +0.0199 | -0.2530 | 1.031 | +1.10 | K3 | A1 |
| ETHUSDT | 5m | 5762 | 35.4 | +0.0121 | -0.1855 | 1.019 | +0.66 | K3 | A1 |
| SOLUSDT | 5m | 6222 | 35.5 | +0.0178 | -0.1356 | 1.028 | +1.01 | K3 | A1 |
| XRPUSDT | 5m | 5715 | 34.7 | -0.0070 | -0.1903 | 0.989 | -0.38 | K3 | A1 |

### preset `doc`

| symbol | tf | n | win % | E[R] | E_net | PF | t (gross) | kill | abort |
|---|---|---|---|---|---|---|---|---|---|
| BNBUSDT | 15m | 343 | 35.8 | +0.0452 | -0.0660 | 1.070 | +0.58 | K3 | A1 |
| BTCUSDT | 15m | 411 | 34.4 | -0.0051 | -0.1143 | 0.992 | -0.07 | K3 | A1,A2,A4 |
| ETHUSDT | 15m | 368 | 35.5 | +0.0465 | -0.0331 | 1.072 | +0.61 | K3 | A1 |
| SOLUSDT | 15m | 358 | 32.3 | -0.0645 | -0.1326 | 0.905 | -0.87 | K3 | A1,A4 |
| XRPUSDT | 15m | 338 | 34.7 | +0.0172 | -0.0700 | 1.026 | +0.22 | K3 | A1 |
| BNBUSDT | 1d | 0 | nan | +nan | +nan | nan | +nan | none | - |
| BTCUSDT | 1d | 0 | nan | +nan | +nan | nan | +nan | none | - |
| ETHUSDT | 1d | 0 | nan | +nan | +nan | nan | +nan | none | - |
| SOLUSDT | 1d | 0 | nan | +nan | +nan | nan | +nan | none | - |
| XRPUSDT | 1d | 0 | nan | +nan | +nan | nan | +nan | none | - |
| BNBUSDT | 1h | 94 | 26.0 | -0.2123 | -0.2688 | 0.713 | -1.34 | K3 | A1,A4 |
| BTCUSDT | 1h | 112 | 31.8 | -0.1176 | -0.1871 | 0.828 | -0.82 | K3 | A1,A2,A4 |
| ETHUSDT | 1h | 116 | 36.3 | +0.0549 | +0.0029 | 1.086 | +0.37 | K3 | A5 |
| SOLUSDT | 1h | 4 | 100.0 | +1.7500 | +1.7328 | inf | +7.00 | none | - |
| XRPUSDT | 1h | 84 | 31.1 | -0.1393 | -0.1882 | 0.798 | -0.83 | K3 | A1,A4 |
| BNBUSDT | 2h | 37 | 40.0 | +0.1200 | +0.0755 | 1.200 | +0.42 | none | - |
| BTCUSDT | 2h | 71 | 45.0 | +0.2625 | +0.2151 | 1.477 | +1.16 | none | - |
| ETHUSDT | 2h | 45 | 42.3 | +0.2308 | +0.1948 | 1.400 | +0.79 | none | - |
| SOLUSDT | 2h | 40 | 41.7 | +0.1667 | +0.1365 | 1.286 | +0.57 | none | - |
| XRPUSDT | 2h | 42 | 33.3 | -0.1296 | -0.1699 | 0.806 | -0.53 | K3 | A1,A4 |
| BNBUSDT | 30m | 207 | 34.4 | -0.0027 | -0.0764 | 0.996 | -0.03 | K3 | A1,A2,A4 |
| BTCUSDT | 30m | 246 | 34.9 | +0.0093 | -0.0719 | 1.014 | +0.10 | K3 | A1,A4 |
| ETHUSDT | 30m | 222 | 38.6 | +0.1361 | +0.0760 | 1.222 | +1.33 | none | - |
| SOLUSDT | 30m | 218 | 36.1 | +0.0576 | +0.0089 | 1.090 | +0.56 | K3 | A5 |
| XRPUSDT | 30m | 213 | 36.8 | +0.0865 | +0.0207 | 1.137 | +0.81 | K3 | A5 |
| BNBUSDT | 4h | 14 | 50.0 | +0.3750 | +0.3539 | 1.750 | +0.47 | none | - |
| BTCUSDT | 4h | 23 | 40.0 | +0.1000 | +0.0715 | 1.167 | +0.15 | none | - |
| ETHUSDT | 4h | 15 | 16.7 | -0.5000 | -0.5192 | 0.400 | -1.00 | K3 | A1,A4 |
| SOLUSDT | 4h | 0 | nan | +nan | +nan | nan | +nan | none | - |
| XRPUSDT | 4h | 15 | 33.3 | -0.1667 | -0.1890 | 0.750 | -0.32 | K3 | A1,A4 |
| BNBUSDT | 5m | 998 | 33.8 | -0.0242 | -0.2406 | 0.963 | -0.55 | K3 | A1,A2,A4 |
| BTCUSDT | 5m | 1047 | 35.7 | +0.0358 | -0.1834 | 1.056 | +0.82 | K3 | A1 |
| ETHUSDT | 5m | 917 | 35.1 | +0.0273 | -0.1321 | 1.042 | +0.58 | K3 | A1 |
| SOLUSDT | 5m | 898 | 35.2 | +0.0140 | -0.1109 | 1.022 | +0.30 | K3 | A1 |
| XRPUSDT | 5m | 886 | 34.0 | -0.0097 | -0.1753 | 0.985 | -0.21 | K3 | A1,A2 |

## NautilusTrader status

The repository has **no Nautilus `Strategy` class** yet (`dodgys_dd_quant/strategy/`
holds the engine, not the module-#5 strategy).  The Nautilus-facing code that
does run is the data lane: the `FuturesContract` definitions, the catalog
round-trip and a bare `python -m nautilus_trader.backtest --raw <json>`
execution (bench probes `data.backtest_config_decodes_with_nautilus`,
`data.nautilus_backtest_runs_the_catalog`).  Because there is no strategy, the
Nautilus run produces **no candidates and no trades**; the candidate population
recorded here is precisely what such a strategy would consume once it exists.
No Nautilus backtest result is claimed in this document.
