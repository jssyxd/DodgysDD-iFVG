# Swarm Task Tree

Captain: this session (omp). Depth ≤ 2. Workers never dispatch.

## Root goal
Audit the existing data, programs and ML architecture for the DodgysDD iFVG project; answer the user's
five questions; and check whether the environment can support Kaggle model training, Kaggle-style rolling
training and local rolling backtests.

## Leaves

| Leaf | Kind | Ownership | Status | Answers |
|---|---|---|---|---|
| L1 vision-dual-validation | pi/M3 | `research/audit/L1_VISION.md` | **merged** | Q1, Q2 |
| L2 rule-fidelity | pi/M3 | `research/audit/L2_RULES.md` | **merged** | Q3 |
| L3 regime-VXN-VIX | pi/M3 | `research/audit/L3_REGIME.md` | **merged** | Q4 |
| L4 data+rolling-design | pi/M3 | `research/audit/L4_ROLLING.md` | **merged** | Q5 |
| L5 env+kaggle-probe | pi/M3 | `research/audit/L5_ENV.md` | **merged** | Kaggle/env feasibility |
| M1 rolling-ML | pi/M3 (worktree) | `dodgys_dd_quant/ml_pipeline/**` | **merged** | implementation |
| M2 e2e-rolling-backtest | pi/M3 (worktree) | `dodgys_dd_quant/strategy/**`, `dodgys_dd_quant/backtest/**` | **merged** | implementation |
| R1 reviewer | pi/M2.7-highspeed (different model) | `research/audit/R1_REVIEW.md` | **merged — CONDITIONAL FAIL** | merge quality |

## Frozen contracts
See `.herd-swarm/decisions.md` D2 (candidate log schema), D3 (model artefact),
D9 (cost model). **Leaves may not change them.**

## Status log
- 2026-11-22 — repo published to `jssyxd/DodgysDD-iFVG` (private), credentials scrubbed, pre-commit
  guard installed, `scripts/sync_github.sh` added. Git tree initialised to enable `--worktree`.

## Final state (2026-11-23)

All 8 leaves are merged; the fleet is torn down (captain pane only).

- **79 tests pass** (2 skipped: they need LightGBM, which lives in `.venv-ml/`).
- The R1 review's **CONDITIONAL FAIL** was acted on: F1 (vacuous forward-only guard), F2 (D3
  producer/consumer could not interoperate), F3 (the model path could not predict), F4 (the
  "rule-only baseline" was the gated portfolio), F5 (`minutes_from_us_open` was minutes since
  midnight) and F9 (`~` never expanded, so the authoritative NFS lake was unused) are closed.
  F6/F7/F8/F10/F11/F12 remain open and are listed in `research/audit/R1_REVIEW.md`.
- The end-to-end ML path now **executes on real data**: 366,500 candidates -> 39 walk-forward
  folds -> `auc_test` 0.483-0.521 (no predictive power) -> the `P(Win) >= 0.58` gate passes
  652 trades -> E[R] +0.0675 (t 1.20, CI includes zero) vs an independent rule-only baseline
  of 21,539 trades at E[R] -0.0002 -> **E_net -0.5245 R** after costs.
- The repository is published at `jssyxd/DodgysDD-iFVG` (private) and local/remote are at the
  same commit.
