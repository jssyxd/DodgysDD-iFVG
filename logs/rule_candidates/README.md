# Rule-only candidate log

Every iFVG candidate produced by the **rule layer** (no model), across the
baseline matrix: **5 crypto perps + MNQ/MES** x 7 timeframes x 2 presets
(honest, doc).  Crypto: 2023-01 -> 2026-10/11, DVOL regime, Binance costs with
each symbol's own tick.  Micros: the NQ/ES price series (same underlying, lanes
resampled from the multi-year 1m lane), VXN regime, the micros' own tick value
and commission.  A `kind` column (`crypto` / `futures`) separates the two.

| file | rows | contents |
|---|---|---|
| `candidates.parquet` | 284,083 | one row per candidate, **taken or not** |
| `runs.parquet` | 98 | one row per cell with its statistics and verdict |

## `candidates.parquet` columns (57)

* identity: `run_id`, `symbol`, `timeframe`, `preset`, `ts_event` (int64 **ns**),
  `ts_event_ms`, `ts_utc`;
* the 35 `Candidate` fields: geometry (`entry_price`, `stop_price`,
  `target_price`, `risk`, `fvg_low`, `fvg_high`, `far_edge`), bar indices
  (`fvg_oldest`, `fvg_newest`, `confirm_bar`, `entry_bar`, `exit_bar`),
  `bars_to_inversion`, `minutes_from_us_open`, `checklist_score`,
  `checklist_flags_json`, `smt_divergence`, `sweep_detected`, `vxn_known`,
  `vxn_regime`, `origin_bar`, `origin_price`, `be_price`, `be_hit_bar`,
  `liquidity_target_price`, `vision_iou`, `vision_confidence`,
  `sweep_since_origin`, `dropped_by_cap`, `never_tradable`, `risk_multiplier`,
  `outcome`, `r_multiple`, `p_win` (NaN here), `gate_approved` (False here);
* **decisions**: `selected` -- the one-position portfolio took it (87,997 of
  284,083 are selected; the rest exist only because the log is not allowed to
  erase a signal);
* **features**: the frozen core set (`checklist_score`, `smt_divergence`,
  `vxn_level`, `vxn_regime`, `bars_to_inversion`, `minutes_from_us_open`,
  `vision_*`, `feature_cutoff_ns`) plus the causal extras (`atr14`,
  `risk_atr`, `gap_atr`, `volume_zscore_60`);
* **the label** `y`: 1 = target reached, 0 = stop hit, -1 = not resolved inside
  the horizon (censored or break-even) -- never coerced to 0.

## Why it exists

`AGENTS.md` and INV4 forbid deleting a signal after the fact (the upstream
indicator's "hide losing setups"). This log is the evidence: it keeps the
candidates that were blocked by an open position, the ones that never resolved
and the losers, with the features that were known at decision time
(`feature_cutoff_ns <= ts_event`).

## Population and label balance

* 98 cells (70 crypto + 28 futures), 284,083 candidates;
* `y`: 93,386 targets / 181,271 stops / 9,426 unresolved (-1);
* every feature column is complete (0 nulls in `atr14`, `risk_atr`,
  `gap_atr`; 7 nulls in `volume_zscore_60`, the warm-up window).

Nothing here is filtered on: the ATR floor lives in the `doc` preset (a
different set of *candidates*, not a filter on this one), and the checklist is
reported, never used to drop a row.

## How it is produced

    python -m dodgys_dd_quant.backtest.matrix \
        --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT \
        --timeframes 5m 15m 30m 1h 2h 4h 1d --presets honest doc \
        --horizon-minutes 3600 --out artifacts/matrix_2026-11-24

    # the micros (MNQ/MES), same engine over the NQ/ES lanes
    python -m dodgys_dd_quant.backtest.matrix --only-futures \
        --timeframes 5m 15m 30m 1h 2h 4h 1d --presets honest doc \
        --out artifacts/matrix_futures

The futures (MNQ/MES) candidates are produced by the same engine over the
NQ/ES lanes; they are not in this file yet.
