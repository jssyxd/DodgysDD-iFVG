# The capability benchmark

`bash autoresearch.sh` runs this benchmark and prints one `METRIC` line per
measurement.  It is the canonical entrypoint for the optimisation loop.

```
METRIC capability_score=1.0           # weighted coverage of the specification
METRIC capability_points=1903         # the primary metric: verified capabilities
METRIC capability_points_total=1903
METRIC points_vision=114              # per-question breakdown
METRIC points_vision_total=114
METRIC points_rules=720
METRIC points_rules_total=720
METRIC points_regime=300
METRIC points_regime_total=300
METRIC points_rolling=769
METRIC points_rolling_total=769
METRIC probes_passed=83
METRIC probes_total=83
METRIC invariant_failures=0
METRIC runtime_s=70.88
```

**The primary metric is `capability_points`, the absolute count of verified
capabilities.**  The *fraction* (`capability_score`) saturates at 1.0 as soon
as every specified behaviour is implemented -- it was 1.0 from round 8 on --
so it can no longer discriminate.  Growing the specification (new probes for
gaps the audits still name) and implementing them raises the point count
instead, and the fraction stays at 1.0 as the statement that nothing was
bought by breaking the system.

Exit codes: `0` the benchmark ran and every invariant held; `1` an
**invariant** was violated (a regression -- the system is broken); `2` the
benchmark could not run at all (missing dependency, missing fixture).

## Why the metric is coverage and not profit

The audits have already settled the profit question: over 2,046,240 real
BTCUSDT 1-minute bars the rule engine's expectancy is **-0.0002 R**, every
95 % CI includes zero, the profit factor never exceeds **1.051** against the
design doc's `> 1.25` gate, and the meta-labeler's `auc_test` is
**0.483-0.521** across 39 folds (D4).  The edge is zero to within the
measurement error, and the round-trip cost is 0.50-0.83 R per trade against
a break-even of 0.009 R.

Optimising a profit number on that sample would optimise noise, and the
repository's own rules forbid it (D4: *"never quote the concurrent arm's
t-statistic"*; D8: *"report the distribution, do not filter"*).  So the
primary metric measures what is actually being asked for -- **how much of the
specified system is implemented and verified** -- and the trading statistics
are reported as secondary metrics so that a change which silently damages the
strategy is visible.

The secondary EV metrics are for **regression detection**, not as an
optimisation target.

## The two kinds of probe

| kind | failing means | effect on the run |
|---|---|---|
| **capability** | a specified behaviour is not implemented yet | the score drops; the run still succeeds |
| **invariant** | a property that must hold at all times was broken | the score drops **and the run exits non-zero** |

The invariants are: the inversion window's arithmetic, no look-ahead, no
signal erasure, the frozen D2 schema, the checklist is never used as a
filter, one position at a time, the regime's strict lag, and the cost ladder.
**Optimisation may add capabilities; it may never buy them by breaking the
system.**

## The probe set

Every probe asserts on **behaviour** -- it calls the code and checks the
output.  A flag nobody reads, or a value that never reaches a decision,
earns nothing.

### `vision` -- Q1 (visual detection) + Q2 (are the two sides aligned?)

The audit's finding is that the two sides measure **different objects**:
the rule engine measures the FVG *price gap*, the detector annotates the
*third candle's body*, and those are disjoint by construction -- so the
discussion's own metric gives a **perfect** detection **IoU = 0.00**
(measured: median 0.0000, 87.9 % exactly zero, 0.65 % above 0.75).

D6 fixes the contract; these probes encode it.

| probe | requires |
|---|---|
| `vision.module_exists` | `dodgys_dd_quant/vision_validator/visual_cv.py` exposing `VisionStyle`, `VisionVerdict`, `evaluate_candidate` |
| `vision.style_is_640_white` | `DEFAULT_STYLE`: 640x640, **white** background, >= 60-bar window (the detector was trained on white TradingView charts, not black 224x224) |
| `vision.body_iou_not_gap_iou` | a box-IoU function where `IoU(body, body) == 1.0` and `IoU(body, gap) == 0.0` |
| `vision.gap_iou_is_descriptive` | `gap_interval_iou` exists and returns 0.0 for a body-vs-gap pair -- reported, never gated on |
| `vision.threshold_is_calibrated` | `constants.VISION_BODY_IOU_THRESHOLD` in [0.20, 0.50]; the inherited 0.75 gate is gone |
| `vision.verdict_has_diagnostics` | `VisionVerdict` carries `vision_iou`, `vision_confidence`, `row_containment`, `bar_index_delta`, `class_match`, `n_detections`, `passed` |
| `vision.gate_is_three_part` | `gate_passes(class_match, bar_index_delta, vision_iou, tau)`: rejects on a class mismatch, on a bar-index mismatch and on a low IoU, accepts when all three hold |
| `vision.evaluates_candidate` | `evaluate_candidate(window, c1_slot, c3_slot, gap_low, gap_high, direction, detector)` returns a verdict; a **stub** detector is injected, so no GPU and no 43 MB weight file are needed |
| `vision.degrades_gracefully` | the ML pipeline still excludes the vision feature when the column is absent (D12) |
| `vision.verdict_reaches_the_d2_log` | the offline batch writes the verdict into the D2 log's two columns |
| `vision.feature_reaches_the_model` | the ML pipeline picks the vision feature up once the columns are filled (D12) |
| `vision.batch_is_causal` | the batch is causal: truncating the future changes no verdict |
| `vision.calibration_recovers_the_pre_registered_threshold` | the IoU threshold comes from a calibration procedure (D6) |
| `vision.side_table_is_exportable` | the audit's side table -- the sharper diagnostics -- can be exported (L1 §B.6) |
| `vision.verdict_never_filters_a_candidate` | the verdict is a feature, never a gate: no decision may depend on it |

### `rules` -- Q3 (are DodgysDD's rules faithfully reproduced?)

| probe | requires |
|---|---|
| `rules.inversion_window_is_1_15` | **invariant** -- ages span (1, 15); age 0 is arithmetically impossible |
| `rules.doc_window_is_7_to_15` | the doc's (7, 15) window is a separate, A/B-able arm |
| `rules.atr_floor_enforced` | with the floor on, every gap exceeds 0.25 x ATR(14) |
| `rules.sweep_level_consumed_once` | a swept level cannot be swept again |
| `rules.killzone_gate_exists` | the killzone gate removes the out-of-session candidates |
| `rules.be_intact_gate_exists` | `require_be_intact=True` changes the population (today the flag is **declared but never applied**) |
| `rules.smt_uses_reference_instrument` | against a reference series, `smt_divergence` takes {-1, 0, 1} and reaches 1 |
| `rules.smt_unknown_without_reference` | without a reference it is -1 (unknown), never 0 |
| `rules.checklist_is_five_booleans` | exactly the five named booleans; `checklist_score` is their sum |
| `rules.checklist_never_filters` | **invariant** -- low-scoring candidates are kept |
| `rules.grade_is_reported` | the rubric discriminates once the regime and the reference are attached |
| `rules.grade_matches_rubric` | the label equals the weighted rubric's label (F11) |
| `rules.no_signal_erased` | **invariant** -- losers are persisted (INV4) |
| `rules.d2_schema_frozen` | **invariant** -- the 23-column D2 schema and its dtypes |
| `rules.no_lookahead_truncation` | **invariant** -- truncating the future changes nothing already emitted |
| `rules.session_extremes_causal` | the PDH never exceeds the running high |
| `rules.regime_lag_is_strict` | **invariant** -- a bar never sees its own day's index close |
| `rules.one_position_at_a_time` | **invariant** -- no two trades overlap in time |
| `rules.leg_tracker_limits_candidates` | the leg tracker keeps no same-direction overlap |

The matrix rows the audits still call *absent* have their own probes:

| probe | requires |
|---|---|
| `rules.stop_placement_body_and_ifvg` | the reference's three stop placements exist and differ (L2 row 18) |
| `rules.break_even_level_is_the_swing_origin` | the break-even level is the leg's swing origin and resolves the trade (rows 19-20) |
| `rules.target_from_the_liquidity_universe` | the >=2R target is named from the liquidity-level universe (row 23) |
| `rules.equal_high_low_levels` | equal-high/low clusters are a level source, consumed once (row 5) |
| `rules.sweep_is_leg_scoped` | the sweep flag counts a sweep **since the origin pivot** (row 30) |
| `rules.unreclaimed_htf_fvg` | unreclaimed HTF FVG zones are tracked causally (row 3) |
| `rules.candidate_array_cap` | the 50-per-direction candidate cap is explicit and its drops are recorded (row 29) |
| `rules.htf_confluence_gate` | the HTF-FVG confluence gate reads the unreclaimed zones (row 8 / D-08) |
| `rules.setup_history_cap` | the setup-history cap stops managing an evicted setup (row 28 / D-11) |
| `rules.origin_bar_variants` | both readings of the origin bar are ported and reconciled (row 15) |
| `rules.bias_filter_partitions` | the direction filter partitions the neutral population (row 26) |
| `rules.sweep_object_is_htf_fractal` | the reference's sweep object is the HTF fractal with a strict pierce (D-06) |
| `rules.engine_is_deterministic` | the engine is a pure function of the bar history: two runs agree exactly |
| `rules.d2_log_parquet_matches_the_lake_contract` | the D2 log's Parquet artefact round-trips with the frozen schema |

### `regime` -- Q4 (is VXN/VIX correlated and wired in?)

The audit's answer was *no on all five paths*.

| probe | requires |
|---|---|
| `regime.correlation_test_runs` | a correlation module returning per-band `E[R]` and a **permutation p-value** (L3 §C.2) -- the deliverable the audit says was never run |
| `regime.reaches_order_decision` | the low-vol and high-vol regimes produce different target distances, matching `REGIME_PARAMETERS` |
| `regime.parameters_are_used` | `regime_parameters()` is **called** somewhere (F10: the table is inert) |
| `regime.in_ml_features` | `vxn_level` and `vxn_regime` reach the feature table |
| `regime.index_is_pluggable` | the index is an interface with a pluggable implementation |
| `regime.no_future_backfill` | the head of the index is dropped, not back-filled from the future (L3 trap 2) |
| `regime.stale_days_is_visible` | a `RegimeState` carries `stale_days`, `percentile`, `known_at_ns` |
| `regime.bands_are_per_market` | the absolute VXN bands do not transfer: the mapping is per index (A34) |
| `regime.percentile_mapping_is_causal` | the percentile mapping uses only the history published before the observation |
| `regime.market_row_names_the_index_and_the_mapping` | each market's row names its regime index and its band mapping |
| `regime.percentile_bands_reach_the_order` | a percentile-banded index still changes the order's target distance |
| `regime.state_is_decision_time` | the regime state carries only what was knowable at the decision (L3 trap 2) |
| `regime.cr1_errors_are_invariant_to_cluster_replication` | the cluster-robust standard error does not shrink when a cluster is replicated (CR1) |
| `regime.correlation_test_reports_cr1_contrasts` | the correlation test reports the band contrasts with their CR1 intervals |
| `regime.permutation_is_blocked_and_seeded` | the permutation test moves the labels in blocks and is reproducible from its seed |
| `regime.pre_registered_family_runs` | the pre-registered family runs on a sample, with every member reported |
| `regime.family_correction_is_joint` | the multiple-testing correction is applied jointly across the family |

### `rolling` -- Q5 (data sufficiency and the rolling ML/RL/e2e stack)

These encode the open R1 findings.

| probe | requires |
|---|---|
| `rolling.forward_only_is_not_vacuous` | the guard consults the **model artefact's** own asof, so a model stamped 2024 cannot decide a 2023 trade (F1) |
| `rolling.d3_producer_consumer_interop` | the trainer writes the index where the backtest's default `--models-root` looks for it (F2) |
| `rolling.model_path_predicts` | the scorer takes a feature dict and returns a probability (F3) |
| `rolling.feature_frame_is_unambiguous` | the feature key is finer than `ts_event`: `(ts_event, side, fvg_bar3)` identifies a candidate uniquely (F3) |
| `rolling.baseline_is_independent` | the rule-only baseline is an independent population, not the gated one (F4) |
| `rolling.single_label_definition` | the engine's label and the ML label agree (F6) |
| `rolling.embargo_follows_the_horizon` | `make_folds` takes `horizon_bars`, so the embargo follows the horizon in use (F7) |
| `rolling.census_is_caveated` | the trainer's census expectancies carry the D4 caveat (F8) |
| `rolling.lake_roots_expand_home` | the lake roots expand `~` (F9) |
| `rolling.rl_cannot_open_a_position` | the RL action space carries no field that could open a position (INV1) |
| `rolling.dynamic_backtest_reports_each_fold` | a per-fold report is written (L4 §F.2) |
| `rolling.kaggle_kernel_never_sees_test` | the kernel generator carries the test-window assertions |
| `rolling.cost_ladder_is_reported` | the 0/1/2-tick ladder in R increases with slippage (D9) |
| `rolling.dsr_accounts_for_trials` | the deflated Sharpe falls as the trial count rises (D4) |
| `rolling.one_position_accounting_is_drop` | blocked signals are dropped, not deferred |
| `rolling.expectancy_is_reported_with_cost` | the runner reports `E[R] net` and the break-even cost in R |
| `rolling.math_is_finite` | no NaN leaks into the headline statistics |
| `rolling.report_is_json_serialisable` | the report serialises, so it can be archived and compared |
| `rolling.pbo_via_cscv` | the PBO via CSCV exists and detects a selection that does not generalise (L4 §F.5) |
| `rolling.dsr_trial_count_comes_from_the_registry` | the DSR's trial count comes from the write-once ledger (L4 §F.5) |
| `rolling.artefact_layout_is_documented` | the README, the producer and the consumer agree on the artefact layout (F12) |
| `rolling.rl_reward_penalises_stalled_profits` | the reward is downside-adjusted and carries the 1.5R failure penalty (doc L152) |
| `rolling.rl_state_carries_regime_and_flow` | the state carries the P&L in R, the regime, the holding time and the imbalance (doc L152) |
| `rolling.roll_gap_does_not_fake_a_sweep` | a contract roll's price gap is excluded from the signal population (Q5) |
| `rolling.accounting_statement_is_on_every_report` | every report carries D4's accounting statement |
| `rolling.cli_prints_the_accounting_statement` | the runner's terminal output prints the statement with the headline |
| `rolling.report_carries_the_baseline_next_to_the_gated_arm` | the gated arm is always reported next to the rule-only baseline |
| `rolling.accounting_statement_names_the_census_trap` | the statement says which arm the t-statistic may be quoted from |
| `rl.policy_loop_applies_the_action` | the policy's action is applied, and the position arms the break-even |
| `rl.management_never_exceeds_the_cap` | a policy cannot push the position past the action space's cap |
| `rl.managed_trade_reports_its_realised_r` | the managed position reports the realised multiple the reward consumes |
| `rl.policy_loop_is_auditable` | every management operation is recorded |
| `rl.action_space_is_the_documented_grid` | the action space is the documented 3 x 4 x 5 grid |
| `rolling.kill_switch_levels_are_implemented` | the kill-switch's three levels and their triggers (L4 §F.3) |
| `rolling.fold_assertions_abort_the_run` | each of the five per-fold assertions aborts the run (L5 §D.5) |
| `rolling.degradation_signals_are_computed` | the three degradation signals are computed per fold |
| `rolling.pipeline_is_causal_end_to_end` | truncating the future changes nothing the pipeline emitted |
| `rolling.trial_registry_is_append_only` | the ledger refuses a duplicate name |
| `rolling.fold_report_has_every_audited_field` | the per-fold report carries every field L4 §F.2 names |
| `rolling.model_metadata_carries_the_d3_keys` | the artefact's metadata carries every D3 key the README documents |
| `rolling.feature_builder_asserts_no_lookahead` | the feature builder's look-ahead assertion holds and fires |
| `rolling.candidate_consistency_report_detects_a_drift` | the D2 log's derived columns are checked against the recomputed ones (F5) |
| `rolling.label_summary_counts_the_census` | the label summary counts the census and reports the base rate |
| `rolling.kaggle_dataset_export_is_written` | the Kaggle dataset export writes the splits, the metadata and the kernels |
| `rolling.pbo_from_the_trial_registry` | the PBO can be computed from the registered trials |
| `rolling.registry_statistics_feed_the_dsr` | the registry publishes the DSR's other inputs |
| `rolling.deferred_accounting_is_reachable` | the deferred accounting arm (D-17) exists beside the drop arm |
| `rolling.portfolio_survives_a_censored_candidate` | a censored candidate holds the book for the horizon, not for ever |
| `rolling.break_even_exit_carries_its_price` | a break-even exit carries the bar it closed on and its multiple |
| `rolling.e1_census_matches_the_standalone_experiment` | the engine's census is the standalone E-1 experiment's census (F11) |
| `rolling.e1_expectancy_matches_the_standalone_experiment` | the engine's one-position-at-a-time expectancy is the standalone experiment's |
| `rolling.e1_rules_are_the_documented_arm` | the engine's e1 preset is the arm the standalone experiment documents |
| `rolling.e1_other_arms_match_the_standalone_experiment` | the other arms (doc window, ATR floor, close fill) reproduce the standalone experiment |
| `rolling.paper_stage_slippage_parity_is_checked` | the paper stage's slippage parity is a quantitative assertion (L4 §E stage 8) |
| `rolling.trainer_dry_run_plans_the_folds` | the trainer's dry run plans the folds without training anything |
| `data.cme_instruments_are_defined` | the CME contracts are defined as tradable instruments with the right tick and multiplier |
| `data.catalog_round_trips_the_bars` | the bars survive the Nautilus catalog round trip |
| `data.prices_use_the_instrument_precision` | the written prices carry the instrument's precision, not a hard-coded one |
| `data.continuous_series_is_dated_contracts` | a continuous series is a series of dated contracts, one per roll segment |
| `data.lake_audit_catches_every_invariant` | the lake's five invariants are audited, and each violation is reported |
| `data.lake_audit_catches_the_flat_bar_corollary` | a zero-volume bar that moved is caught (the lake's own auditor cannot see it) |
| `data.dst_switch_days_shift_the_window` | the switch days move the window by exactly one hour (DATA_FEASIBILITY §E.3) |
| `data.globex_open_moves_with_dst` | the Globex open is 23:00 UTC under EST and 22:00 UTC under EDT |
| `data.rth_flag_marks_the_cash_session` | the session calendar marks the regular trading hours |
| `data.killzone_is_endpoint_inclusive` | the killzone windows are endpoint-inclusive and hold the same bars across DST |
| `data.custom_data_rides_the_nautilus_timeline` | the regime and the vision verdict are Nautilus `Data` objects |
| `data.regime_signal_carries_the_lagged_values` | the regime signal carries the engine's own lagged values |
| `rules.local_minutes_follow_dst` | the local minutes follow the tz database across the DST switch days |
| `regime.binning_matches_the_corrected_semantics` | the regime bins use the corrected semantics, not the discussion's `pd.cut` |
| `rl.manager_refuses_to_open_or_submit` | the position manager has no way to open or submit anything (INV1) |
| `rolling.d9_dollar_ladder_is_exact` | the cost model reproduces D9's dollar ladder exactly |
| `rolling.label_horizon_has_one_representation` | the label horizon has one representation in bars and in minutes |
| `data.credential_guard_catches_a_leaked_token` | the pre-commit credential guard blocks a staged token |
| `data.backtest_config_decodes_with_nautilus` | the backtest configuration decodes with Nautilus's own decoder |
| `data.nautilus_backtest_runs_the_catalog` | the Nautilus backtest actually runs over the catalog the ingest writes |
| `data.backtest_config_is_reproducible` | the same configuration bytes twice: the instance id is derived, not random |
| `rolling.census_arm_is_not_a_result` | the census arm's significance is an artefact of overlapping trades (D4) |
| `rolling.abort_criteria_are_evaluated` | L4 §C.6's five abort criteria fire on the data they describe |
| `rolling.abort_criteria_report_what_they_could_not_check` | a criterion whose inputs are missing is reported as not evaluated |
| `rolling.abort_criteria_reach_the_kill_switch` | the abort criteria are the kill-switch's K3 trigger, not a manual flag |
| `rolling.degradation_monitor_inputs_are_recorded` | the fold's artefact records the training distribution and the feature importances (L4 §F.3) |
| `rolling.degradation_monitor_feeds_the_kill_switch` | the walk-forward feeds the kill-switch's three signals from the fold's own numbers |
| `rolling.momentum_baseline_is_an_independent_control` | the no-FVG momentum control trades, with its own one-position accounting |
| `rolling.abort_criteria_a4_compares_the_control` | A4 fires when the FVG does not beat the no-FVG control |
| `rolling.abort_criteria_a2_finds_the_cost_heavy_arms` | A2 fires when the only profitable arms are the expensive ones |
| `rolling.abort_criteria_a4_is_evaluated_in_a_walk_forward` | a walk-forward that is given the bars evaluates A4 against the control |
| `rolling.kill_switch_verdict_is_visible_in_the_run_output` | the runner prints the kill-switch's level and the abort criteria behind it |
| `rolling.abort_criteria_a2_splits_the_population_by_cost` | A2 splits the population at 0.3 R of cost and compares the two buckets |
| `rolling.abort_criteria_a3_reads_the_models_own_numbers` | A3 reads the model's AUC, its net lift and the features it learned |
| `rolling.all_five_criteria_are_evaluated_in_a_walk_forward` | a walk-forward with a model evaluates all five abort criteria |

## The fixtures

`bench/fixtures/` holds gzip-compressed CSV slices of the governed lake --
see `bench/fixtures/MANIFEST.md` for the provenance of each file.  The
benchmark therefore needs **no network and no lake mount**, and every run is
byte-for-byte reproducible.

## Adding a probe

Register it in the matching module under `bench/probes/`:

```python
@register("rules.some_new_rule", "rules", 8, "what it requires")
def _some_new_rule() -> tuple[bool, str]:
    ...
    return True, "what the probe observed"
```

Keep it **behavioural**: call the code, assert on the output.  Mark it
`invariant=True` only if a violation means the system is broken rather than
merely unfinished.
