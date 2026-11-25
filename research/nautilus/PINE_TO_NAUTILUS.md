# Pine replica -> NautilusTrader: the mapping

Source of truth: `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine`
(Pine v6, MIT) and `research/analysis/PINE_RULES.md`. Every row cites the line
range in the replica. The scope is fixed by `.herd-swarm/decisions.md` D2: the
**execution-relevant** switches are ported; `hideLosing` is forbidden (INV4).

## 1. Inputs -> config field

| Pine input (`pine:L…`) | carries | where it lives now |
|---|---|---|
| `ifvgMode` (Single/Series) | one live candidate per leg vs every gap | `RuleConfig.leg_tracker` (off = every gap) |
| `biasMode` (Neutral/Bullish/Bearish) | direction filter | `RuleConfig.bias` |
| `hideLosing` (default **true**) | deletes invalidated setups from the chart | **not ported**: erasing a signal is forbidden (INV4); the archive keeps it |
| `allowExtIFVG` (7-15 vs 6 candles) | inversion window | `RuleConfig.inversion_min_bars/max_bars` (`(7,15)` = doc, `(1,15)` = code) |
| `requireBEIntact` | hide setups whose confirmation candle already reached B.E. | `RuleConfig.require_be_intact` |
| `onlyShowSweptIFVG` (default false) | require an HTF sweep | `RuleConfig.require_sweep`, `sweep_source` |
| `onlyShowHtfAlignedIFVG` (default false) | require overlap with an HTF FVG | `RuleConfig.require_htf_alignment` |
| `setupHistory` (default 2) | keep only N setups, evict the rest | `RuleConfig.setup_history_cap` (0 = keep all) |
| `htfMode` / `customHTF` | HTF timeframe for the sweep/zone detector | `RuleConfig.htf_timeframe_minutes` |
| `session1..3Enable/Time` (`pine:L58-64`) | **alert** windows, not signal gates | `RuleConfig.killzones` + `killzone_gate=False` |
| `max_bars_back=5000` (`pine:L2`) | history needed for a setup | the engine needs ≥ 5,000 bars of warm-up; the matrix cells have 1.4k-409k |

## 2. Behaviours

| Pine behaviour | line range | port |
|---|---|---|
| 3-candle gap on **wicks**, strict inequality | `pine:L354-356` | `state_machine` FVG detection, `FVG_GEOMETRY_STRICT` |
| inversion: body close beyond the far edge | `pine:L431-500` | `_inversion` + `far_edge` |
| sweep detector on the hand-aggregated HTF, three-bar fractal, one-shot consumption | `pine:L544-630` | `sweep_source="htf_fractal"`, `HTFZones` aggregation |
| `request.security(..., lookahead_off)` with the 1→15/3→30/5→60/15→240/60→1D map | `pine:L635`, `pine:L544` | hand aggregation of the same-TF bars (never a forward-filled synthetic) |
| break-even level = swing origin of the leg; the trade closes there | `pine:L476-491` | `RuleConfig.resolve_break_even`, `_break_even_hit` |
| candidate cap per direction | `pine:L431+` | `RuleConfig` cap switches |
| RR target | `pine:L…` (inputs) | `DEFAULT_RR`, `rule.target_price` |
| `alertcondition` only in the session windows | `pine:L123-125` | killzones gate alerts, never signals |
| `max_bars_back` | `pine:L2` | warm-up requirement documented on the engine |

## 3. Execution gaps (the indicator does not specify these; the strategy must)

| gap | decision |
|---|---|
| when to act | at the confirmation bar's **close** (the `ts_event` the engine writes) |
| order type | market entry at that instant; bracket = market entry + limit TP + stop-market SL |
| size | `equity * risk_per_trade / (risk_points * multiplier)`; 1R = `equity * risk_per_trade` |
| one position? | yes -- a blocked signal is **dropped** (D4), never deferred |
| time exit | the engine censors at its horizon; the strategy closes at the same bar count |
| fees | the instrument carries them (Binance 0.04%/side; MNQ/MES commission in the cost profile) |
| partials / break-even trailing | **not implemented**; the reference's BE is a price level, and `resolve_break_even` is a rule switch, not a trailing stop |

## 4. Test hooks (what a parity test can assert)

| behaviour | observable |
|---|---|
| FVG detection + inversion | the candidate count of a cell (`runs.parquet.candidates`) |
| entry/stop/target geometry | the candidate's `entry_price/stop_price/target_price` |
| one position at a time | `positions == engine_trades` within 1 % (`NAUTILUS_MATRIX_2026-11-24.md`) |
| the realised R | `r_nt` from the position vs the candidate's `r_multiple` (corr ≥ 0.99) |
| no signal erased | `candidates.parquet` holds the blocked and censored rows (`selected=False`, `y=-1`) |
| killzone-as-alert | a setup outside 09:30-11:30 ET still appears in the log |

## 5. What is *not* in the replica and therefore not ported

* the A+/A/B/C grade box (`pine:L…`, removed upstream) -- the checklist is five
  reported booleans (D8), never a filter;
* the "Visual Clarity Score" -- undefined anywhere; the vision layer uses a
  calibrated body IoU instead;
* nearest-liquidity TP -- the replica uses RR targets (its own README says so).
