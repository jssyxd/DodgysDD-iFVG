# Leaf R1 — Review the merged tree (read-only, different kind from the authors)

## Context
Project: `/home/da/桌面/DodgysDD_ifvg`. Two implementation leaves (M1 = rolling ML, M2 = rule engine +
E2E backtest) have been merged into `main` by the captain. You are the **reviewer**. Your kind differs
from the authors' (they were `pi`/MiniMax-M3; you are a different model), so bring a fresh eye.

**You are a worker, not an orchestrator.** Do not dispatch agents, do not run `herdr`/`herd-dispatch`, do
not edit `.herd-swarm/decisions.md`.

## What you review
The merged tree at `/home/da/桌面/DodgysDD_ifvg`:
```
dodgys_dd_quant/ml_pipeline/{features,labels,splits,train_meta_labeler,kaggle_export}.py
dodgys_dd_quant/strategy/{constants,structure,state_machine,regime}.py
dodgys_dd_quant/backtest/{cost_model,walk_forward,runner}.py
tests/unit/{test_splits,test_labels,test_state_machine,test_cost_model,test_walk_forward}.py
```
plus the audit reports `research/audit/L{1,2,3,4,5}_*.md` and the design record
`.herd-swarm/decisions.md`.

## Required reading
- `.herd-swarm/decisions.md` — the **frozen contracts** (D2 candidate-log schema, D3 model artefact,
  D4 the one-position-at-a-time rule, D9 costs) and the captain's decisions D12/D13.
- `research/audit/L2_RULES.md` — the rule-fidelity matrix the engine was supposed to satisfy.

## Your task → `research/audit/R1_REVIEW.md`

### A. Contract conformance — the highest-value check
Verify, by reading the code (not by trusting the docstrings), that:
1. The candidate log the state machine emits matches the **D2 schema exactly** — column names, dtypes and
   semantics, one by one. Report any deviation.
2. The model artefact the trainer writes matches **D3** — the directory layout, `meta_label_lgbm.txt`,
   `meta_label_meta.json` with its exact keys, and `walk_forward_index.json`.
3. The backtest's **forward-only assertion** is actually enforced: a model with `asof = T` must not be
   able to decide a trade with `ts_event <= T`. Read the code and say whether the check can be bypassed.
4. The **one-position-at-a-time** rule is enforced in the backtest and not merely documented.

### B. Look-ahead hunt — treat this as adversarial
The single most important property of this codebase is that it does not peek. Hunt for it:
- the state machine: does any predicate use a bar that has not closed? Check the FVG detection, the
  inversion trigger (`close[k-1]` semantics), the ATR anchoring, the swing detection, the session/killzone
  evaluation, and the regime lookup.
- the regime module: can a bar on day D see day D's VXN close? (It must not — only D−1.)
- the features module: can any feature use a value dated after `ts_event`? Check each one.
- the labels module: does the label use the future *correctly* (it must) without leaking into the features?
- the splits module: is the embargo real, and can a training sample overlap a validation/test sample?
For each finding: file, line, the exact mechanism, and a **failing test case** you can write to prove it.
If you find no look-ahead, say so explicitly and state which properties you actually exercised.

### C. Test quality
Do the tests **test behaviour**, or do they merely assert that the code runs? Specifically:
- is there a test that would **fail** if the look-ahead were reintroduced?
- is there a test that pins the **one-position-at-a-time** behaviour?
- is there a test that pins the **purge/embargo** invariants with a case where a naive split would leak?
- are the tests deterministic and offline (no network, no lake dependency)?
List any test that is tautological, over-mocked, or testing a private helper instead of the contract.

### D. Does it actually run end-to-end?
Run it. Then report:
- `pytest tests/unit -q` — the pass/fail count.
- the **E2E backtest on the real data**: BTCUSDT 1-minute from the NFS lake
  (`~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet`,
  2,046,240 bars). Use the runner's own CLI. Report the **actual numbers**: n candidates, n trades,
  expectancy in R **gross and net of costs**, profit factor, the 95% CI, and — the thing that matters —
  **whether it beats the D4 baseline** (one-position-at-a-time E[R] ∈ [−0.024, +0.014], PF ≤ 1.051).
- If it cannot run, say exactly why and what is missing.

### E. Honesty audit
The project's whole credibility rests on not over-claiming. Check the code and its docstrings for:
- claims that the strategy has an edge;
- a "significant" t-statistic quoted from the concurrent/census arm (D4 forbids it);
- results computed with the wrong accounting (multiple simultaneous positions);
- any place a losing setup is dropped rather than persisted;
- a grade filter applied despite D8;
- a threshold asserted but not implemented.

### F. Verdict
```
CONTRACT CONFORMANCE:   pass / minor issues / broken
LOOK-AHEAD:             none found / N findings (highest severity: ...)
TESTS:                  adequate / inadequate (what is missing)
E2E ON REAL DATA:       ran / could not run  ->  the numbers
BEATS THE D4 BASELINE:  yes / no / not measurable
HONESTY:                clean / N over-claims
RECOMMENDATION:         merge / merge after fixes (list the fixes) / do not merge
```

## Constraints
- Write **only** `research/audit/R1_REVIEW.md`. You may create scratch files under `/tmp`.
- You may **run** the code and the tests. You may **not** modify any file other than your own.
- If you find a look-ahead, you may add a **failing test** as evidence in your report (describe it; do
  not commit it to the repo).
- Be adversarial but fair. If the code is good, say so; if it is broken, say exactly where.
- Do not re-litigate D1–D13; they are decided.

## Deliverable
`research/audit/R1_REVIEW.md`. Final reply: the verdict block, the highest-severity finding, and the
E2E numbers if you got them.
