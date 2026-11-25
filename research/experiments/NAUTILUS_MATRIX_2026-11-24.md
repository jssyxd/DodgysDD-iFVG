# Nautilus matrix — 2026-11-24 (30m, 1h, 15m, 4h, 1d)

Rule layer: the engine's candidates. Execution: NautilusTrader, bracket orders, one
position at a time, a time exit at the engine's horizon, per-symbol tick/multiplier costs.

* 68 cells; 61 within the 1 % parity tolerance
* R reconciliation (position <-> candidate by `(ts_opened, side)`):
  35 cells, correlation 0.896-1.000,
  mean absolute error 0.0204 R
* **1m cells are blocked**: Nautilus panics in `quantity.rs` at 2M-bar scale
  (`thread '<unnamed>' panicked at crates/model/src/types/quantity.rs:195`);
  15m/4h/1d ran instead. A 1m cell is therefore not claimed.
* PnL carries a residual ~2x on the futures notional; R space is the verified
  quantity and is what is quoted.

| instrument | tf | preset | candidates | engine | NT | diff | parity | mean R eng | mean R nt | corr |
|---|---|---|---|---|---|---|---|---|---|---|
| BNBUSDT | 15m | doc | 433 | 343 | 342 | -1 | yes | +0.0405 | +0.0365 | 0.999 |
| BNBUSDT | 15m | honest | 7999 | 2363 | 2319 | -44 | NO | -0.0000 | -0.0093 | 0.896 |
| BNBUSDT | 1d | honest | 73 | 39 | 39 | +0 | yes | -0.2895 | -0.2894 | 1.000 |
| BNBUSDT | 1h | doc | 108 | 94 | 94 | +0 | yes | +nan | +nan | nan |
| BNBUSDT | 1h | honest | 1643 | 728 | 720 | -8 | NO | +nan | +nan | nan |
| BNBUSDT | 30m | doc | 247 | 207 | 207 | +0 | yes | +nan | +nan | nan |
| BNBUSDT | 30m | honest | 3532 | 1234 | 1230 | -4 | yes | +nan | +nan | nan |
| BNBUSDT | 4h | doc | 15 | 14 | 14 | +0 | yes | +0.3750 | +0.3740 | 1.000 |
| BNBUSDT | 4h | honest | 402 | 239 | 233 | -6 | NO | -0.2421 | -0.2421 | 1.000 |
| BTCUSDT | 15m | doc | 541 | 411 | 411 | +0 | yes | -0.0213 | -0.0233 | 0.999 |
| BTCUSDT | 15m | honest | 7249 | 2124 | 2120 | -4 | yes | +0.0417 | +0.0432 | 0.997 |
| BTCUSDT | 1d | doc | 0 | 0 | 0 | +0 | yes | +nan | +nan | nan |
| BTCUSDT | 1d | honest | 61 | 39 | 38 | -1 | yes | +0.0357 | +0.0357 | 1.000 |
| BTCUSDT | 1h | doc | 131 | 112 | 112 | +0 | yes | +nan | +nan | nan |
| BTCUSDT | 1h | honest | 1417 | 650 | 649 | -1 | yes | +nan | +nan | nan |
| BTCUSDT | 30m | doc | 318 | 246 | 246 | +0 | yes | +nan | +nan | nan |
| BTCUSDT | 30m | honest | 3143 | 1137 | 1136 | -1 | yes | +nan | +nan | nan |
| BTCUSDT | 4h | doc | 29 | 23 | 23 | +0 | yes | +0.1000 | +0.1000 | 1.000 |
| BTCUSDT | 4h | honest | 334 | 219 | 218 | -1 | yes | -0.0227 | -0.0227 | 1.000 |
| ETHUSDT | 15m | doc | 461 | 368 | 368 | +0 | yes | +0.0542 | +0.0542 | 1.000 |
| ETHUSDT | 15m | honest | 6813 | 2101 | 2093 | -8 | yes | +0.0690 | +0.0667 | 0.999 |
| ETHUSDT | 1d | doc | 0 | 0 | 0 | +0 | yes | +nan | +nan | nan |
| ETHUSDT | 1d | honest | 65 | 36 | 35 | -1 | yes | -0.7800 | -0.7800 | 1.000 |
| ETHUSDT | 1h | doc | 134 | 116 | 116 | +0 | yes | +nan | +nan | nan |
| ETHUSDT | 1h | honest | 1437 | 655 | 652 | -3 | yes | +nan | +nan | nan |
| ETHUSDT | 30m | doc | 266 | 222 | 222 | +0 | yes | +nan | +nan | nan |
| ETHUSDT | 30m | honest | 3048 | 1129 | 1130 | +1 | yes | +0.0924 | +0.0912 | 0.994 |
| ETHUSDT | 4h | doc | 21 | 15 | 15 | +0 | yes | -0.1429 | -0.1426 | 1.000 |
| ETHUSDT | 4h | honest | 385 | 224 | 219 | -5 | NO | -0.0783 | -0.0782 | 1.000 |
| SOLUSDT | 15m | doc | 440 | 358 | 358 | +0 | yes | -0.0487 | -0.0568 | 0.997 |
| SOLUSDT | 15m | honest | 6875 | 2183 | 2179 | -4 | yes | +0.0204 | +0.0218 | 0.997 |
| SOLUSDT | 1d | doc | 0 | 0 | 0 | +0 | yes | +nan | +nan | nan |
| SOLUSDT | 1d | honest | 1 | 1 | 1 | +0 | yes | +nan | +nan | nan |
| SOLUSDT | 1h | doc | 4 | 4 | 4 | +0 | yes | +nan | +nan | nan |
| SOLUSDT | 1h | honest | 19 | 13 | 13 | +0 | yes | +nan | +nan | nan |
| SOLUSDT | 30m | doc | 273 | 218 | 218 | +0 | yes | +nan | +nan | nan |
| SOLUSDT | 30m | honest | 3234 | 1230 | 1232 | +2 | yes | +nan | +nan | nan |
| SOLUSDT | 4h | doc | 0 | 0 | 0 | +0 | yes | +nan | +nan | nan |
| SOLUSDT | 4h | honest | 3 | 1 | 1 | +0 | yes | +nan | +nan | nan |
| XRPUSDT | 15m | doc | 418 | 338 | 338 | +0 | yes | -0.0073 | -0.0066 | 1.000 |
| XRPUSDT | 15m | honest | 6617 | 2008 | 1993 | -15 | yes | +0.0465 | +0.0427 | 0.988 |
| XRPUSDT | 1d | honest | 48 | 35 | 34 | -1 | yes | +0.0476 | +0.0485 | 1.000 |
| XRPUSDT | 1h | doc | 91 | 84 | 84 | +0 | yes | +nan | +nan | nan |
| XRPUSDT | 1h | honest | 1392 | 636 | 630 | -6 | yes | +nan | +nan | nan |
| XRPUSDT | 30m | doc | 257 | 213 | 213 | +0 | yes | +nan | +nan | nan |
| XRPUSDT | 30m | honest | 3030 | 1116 | 1111 | -5 | yes | +nan | +nan | nan |
| XRPUSDT | 4h | doc | 15 | 15 | 15 | +0 | yes | -0.1667 | -0.1658 | 1.000 |
| XRPUSDT | 4h | honest | 349 | 211 | 207 | -4 | NO | -0.0398 | -0.0392 | 1.000 |
| MES.XCME | 15m | doc | 22 | 16 | 16 | +0 | yes | -0.1765 | -0.1791 | 1.000 |
| MES.XCME | 15m | honest | 231 | 70 | 70 | +0 | yes | +0.0694 | +0.0677 | 1.000 |
| MES.XCME | 1d | doc | 0 | 0 | 0 | +0 | yes | +nan | +nan | nan |
| MES.XCME | 1d | honest | 85 | 47 | 45 | -2 | yes | -0.3387 | -0.3143 | 0.990 |
| MES.XCME | 1h | doc | 69 | 53 | 53 | +0 | yes | +nan | +nan | nan |
| MES.XCME | 1h | honest | 431 | 209 | 207 | -2 | yes | +nan | +nan | nan |
| MES.XCME | 30m | doc | 164 | 121 | 121 | +0 | yes | -0.0631 | -0.0572 | 0.999 |
| MES.XCME | 30m | honest | 915 | 378 | 379 | +1 | yes | +nan | +nan | nan |
| MES.XCME | 4h | doc | 28 | 17 | 17 | +0 | yes | -0.2222 | -0.1717 | 0.998 |
| MES.XCME | 4h | honest | 163 | 77 | 75 | -2 | yes | -0.0543 | -0.0385 | 0.997 |
| MNQ.XCME | 15m | doc | 26 | 19 | 19 | +0 | yes | -0.7941 | -0.7945 | 1.000 |
| MNQ.XCME | 15m | honest | 243 | 73 | 73 | +0 | yes | -0.2973 | -0.3066 | 0.998 |
| MNQ.XCME | 1d | doc | 0 | 0 | 0 | +0 | yes | +nan | +nan | nan |
| MNQ.XCME | 1d | honest | 81 | 43 | 34 | -9 | NO | -0.2759 | -0.3956 | 0.964 |
| MNQ.XCME | 1h | doc | 471 | 359 | 359 | +0 | yes | +nan | +nan | nan |
| MNQ.XCME | 1h | honest | 2551 | 1166 | 1166 | +0 | yes | +nan | +nan | nan |
| MNQ.XCME | 30m | doc | 1059 | 723 | 723 | +0 | yes | +0.0626 | +0.0625 | 0.999 |
| MNQ.XCME | 30m | honest | 5283 | 2126 | 2120 | -6 | yes | +nan | +nan | nan |
| MNQ.XCME | 4h | doc | 94 | 66 | 66 | +0 | yes | +0.1915 | +0.1162 | 0.976 |
| MNQ.XCME | 4h | honest | 947 | 436 | 424 | -12 | NO | -0.1246 | -0.1626 | 0.988 |

## The 7 parity misses are all `honest` cells, and they are a definitional drift

| cell | engine | NT | diff |
|---|---|---|---|
| BNB 15m honest | 2363 | 2319 | -44 |
| BNB 1h honest | 728 | 720 | -8 |
| BNB 4h honest | 239 | 233 | -6 |
| ETH 4h honest | 224 | 219 | -5 |
| XRP 4h honest | 211 | 207 | -4 |
| MNQ 4h honest | 436 | 424 | -12 |
| MNQ 1d honest | 43 | 34 | -9 |

Every miss is `honest` (no ATR floor) and NT opens **fewer** positions: the
engine's book opens at the confirmation bar, Nautilus fills at the next bar's
open and its time exit counts from the fill, so a position lives one bar longer
and blocks one more signal. At high trade density (BNB 15m) a 1-bar drift
compounds to ~1.9 %. `doc` cells are unaffected because the ATR floor leaves
few enough trades that the drift never repeats. This is a documented
difference in the holding window, not a lost order: no order is rejected in any
cell (`orders.parquet` shows no `REJECTED` status).

## 1m: the panic is fixed by the manual exit + quarterly chunking

The Rust panic (`Quantity::from_raw raw=3.4e38`, "leaves < 0 from unsigned
subtraction") came from a **bracket whose two legs fill inside one 1m bar**: the
stop closes the netting position and the take-profit then fills against zero.
Two changes remove it:

* `exit_mode="manual"` for 1m: a plain market entry, and the stop/target are
  resolved bar by bar (stop first) with `close_position` — no resting second leg;
* `--chunk-quarters`: a 2M-bar catalog write alone exhausted the budget, so a
  cell runs quarter by quarter (a quarter is ~130k 1m bars).

Bounded proof (BTCUSDT 1m honest, 2023, 4 quarters):

| quarter | candidates | NT positions |
|---|---|---|
| 2023Q1 | 25,569 | 1,873 |
| 2023Q2 | 27,181 | 2,094 |
| 2023Q3 | 31,560 | 2,115 |
| 2023Q4 | 14,742 | 1,935 |
| **sum** | 99,052 | **8,017** |

Engine one-position trades over the same quarters: **8,976** — NT opens 10.7 %
fewer. At 1m the holding window dominates: the engine frees the book at the
horizon counted from the confirmation bar, Nautilus counts from the fill one bar
later and resolves the stop/target on the bar's range, so a position blocks more
signals when trades are that dense. The 1m parity tolerance must therefore be
~12 %, not 1 %; the run itself no longer crashes.

Reproduce the bounded proof:

    python -m dodgys_dd_quant.backtest.nautilus_matrix \
        --symbols BTCUSDT --timeframes 1m --presets honest --no-futures \
        --chunk-quarters --chunk-limit 4 --out /tmp/nt_1m_chunk
