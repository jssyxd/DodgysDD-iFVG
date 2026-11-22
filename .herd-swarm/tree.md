# Swarm Task Tree

Captain: this session (omp). Depth ≤ 2. Workers never dispatch.

## Root goal
Audit the existing data, programs and ML architecture for the DodgysDD iFVG project; answer the user's
five questions; and check whether the environment can support Kaggle model training, Kaggle-style rolling
training and local rolling backtests.

## Leaves

| Leaf | Kind | Ownership | Status | Answers |
|---|---|---|---|---|
| L1 vision-dual-validation | pi | `research/audit/L1_VISION.md` (read-only elsewhere) | planned | Q1, Q2 |
| L2 rule-fidelity | pi | `research/audit/L2_RULES.md` | planned | Q3 |
| L3 regime-VXN-VIX | pi | `research/audit/L3_REGIME.md` | planned | Q4 |
| L4 data+rolling-design | pi | `research/audit/L4_ROLLING.md` | planned | Q5 |
| L5 env+kaggle-probe | pi | `research/audit/L5_ENV.md` | planned | Kaggle/env feasibility |
| M1 rolling-ML | pi (worktree) | `dodgys_dd_quant/ml_pipeline/**` | planned | implementation |
| M2 e2e-rolling-backtest | pi (worktree) | `dodgys_dd_quant/strategy/**`, `dodgys_dd_quant/backtest/**` | planned | implementation |
| R1 reviewer | pi (handoff, different model) | review only | planned | merge quality |

## Frozen contracts
See `.herd-swarm/decisions.md` D2 (candidate log schema), D3 (model artefact),
D9 (cost model). **Leaves may not change them.**

## Status log
- 2026-11-22 — repo published to `jssyxd/DodgysDD-iFVG` (private), credentials scrubbed, pre-commit
  guard installed, `scripts/sync_github.sh` added. Git tree initialised to enable `--worktree`.
