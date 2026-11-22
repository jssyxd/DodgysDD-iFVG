# Leaf L4 — Data sufficiency and the rolling ML / RL / e2e design

## Context
Project: `/home/da/桌面/DodgysDD_ifvg`. The user's question 5: *is the existing data sufficient, and how
should rolling ML training, rolling RL, an end-to-end model and dynamic backtesting be organised?*

**Read-only audit leaf.** Own exactly one file: `research/audit/L4_ROLLING.md`.

## Required reading
- `.herd-swarm/decisions.md` — **D2** (frozen candidate-log schema), **D3** (frozen model-artefact
  contract), **D4** (the honest baseline: the rule engine has **no edge**), **D5** (data reality),
  **D8** ("A/A+" unimplementable), **D9** (cost model).
- `research/analysis/DATA_ACQUISITION.md` — the measured data state and the acquisition history.
- `research/analysis/DATA_FEASIBILITY.md` — the earlier feasibility assessment.
- `research/experiments/E1_RESULTS.md` — rev. 2, the falsification result.
- `research/docs/RULE_SPEC.md` §on the ML feature list and the ambiguity register.

## Your task → `research/audit/L4_ROLLING.md`

### A. Data sufficiency — a requirement-by-requirement matrix
Build the table the user asked for. For each thing the system needs, state **AVAILABLE / PARTIAL /
MISSING**, the evidence path, and the consequence.

Rows (at minimum):
1. NQ 1-minute OHLCV, ≥3 years, with a documented **roll rule**.
2. ES 1-minute OHLCV (the SMT reference), time-aligned to NQ.
3. Tick data (needed for the RL's order-book-imbalance state, and for accurate slippage).
4. A **tradeable** instrument definition (tick size, multiplier, fees) — and the Nautilus
   `FuturesContract` for NQ/ES.
5. VXN (daily) and the intraday volatility proxy the doc actually needs.
6. The **session/killzone calendar** with DST handling.
7. Funding rates (crypto) / DVOL.
8. The candidate log itself (the output of the rule engine — the input to ML).
9. The **labels** (outcome join) and the cost model.
10. Out-of-sample capacity: can a 6/1/1 rolling split get enough trades per fold?

For row 1 and 2, be precise about **what exists and where**: the NFS lake path
`~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/1m/` holds
**7,490 / 7,489 rows for one week only** — verify this yourself. Then state the **real** gap: what is
missing is not "1-minute NQ" but "**multi-year** 1-minute NQ **with a roll rule**", and explain why the
roll rule is not optional (a roll gap prints like a liquidity sweep).

### B. Sufficiency of the *current* crypto data — and be honest about the transfer
BTCUSDT/ETHUSDT have 2,046,240 gap-free 1-minute bars (2023-01-01 → 2026-11-21). Answer:
- Does that data **support** the doc's walk-forward (6 months train / 1 month validate / 1 month test,
  rolling monthly)? How many folds, how many trades per fold, and does each fold have enough positives
  for a binary classifier? Compute the **label base rate** if you can (the rule engine's candidate
  statistics are in `research/experiments/E1_RAW_OUTPUT_btcusdt1m_full.txt`).
- **Critical**: does a result on BTCUSDT transfer to NQ? The doc's target is NQ. Argue the transfer
  question properly — what would have to be true, and what is the cheapest test of it?
- State the **minimum additional data** that makes phase 1 meaningful, with a cost.

### C. Rolling ML training — the concrete design
Specify the pipeline in full detail, against the **frozen** contracts in D2/D3:
- **Feature table**: the exact feature list. It must be computable **at decision time** from what exists.
  The doc's list (L146) is: checklist score, SMT flag, vision confidence, VXN level + 1-hour change,
  bars-to-inversion, minutes-from-US-open. State for each: available? computable? and what replaces the
  dropped 1-hour VXN change.
  Note the doc's **"视觉检测置信度"** is a vision feature — and the vision layer does not exist (L1's
  subject). Say how the design degrades gracefully without it, and what the ML feature set is until it
  does.
- **Label construction**: binary 1 = reached the 2R target, 0 = stopped out; the outcome join; the
  handling of still-open trades; the **base rate**; and the class-imbalance treatment.
- **Split**: purged walk-forward with an **embargo**. Give the exact embargo rule (in *minutes* and in
  *bars*), why it must exceed the maximum holding period, and how to prove no overlap
  (the audit's QA requirement).
- **Model**: LightGBM binary; hyper-parameters; the class-weight / scale-pos-weight handling; the
  early-stopping protocol on the validation fold; and the **decision rule** (P(Win) ≥ 0.58).
- **The artefact**: exactly the D3 layout.
- **The honest acceptance test**: a meta-labeler can only help if the base signal has *some* edge to
  filter. Given D4, state the **necessary condition** for the ML layer to add value, the metric that
  tests it (conditional expectancy of the kept subset vs the base, with a CI), and what result would
  mean "stop, the idea is dead".

### D. Rolling RL
- The doc's RL is **position management only** — it must never open a position. Specify how that is
  *enforced in code* (not by convention): the action space, the state (PnL in R, VXN regime, holding
  time, order-book imbalance), the reward (Sortino-like with the 1.5R penalty), and the invariant test.
- Where does the RL's order-book-imbalance state come from for **NQ**? (For crypto the lake has `bar_ofi`
  on 1-minute bars — for NQ we have nothing.) State the gap.
- The RL's **training data**: what episodes, on what series, and why a policy trained on BTCUSDT 1m bars
  cannot simply be applied to NQ.
- Why RL is *last* in the sequence and what must be true before it is worth building.

### E. End-to-end model
Define the end-to-end system as a **pipeline of stages with gates**, each stage's input/output
artefact, and the gate that must pass. Include the paper-trading stage and the slippage-parity check the
doc demands. Give the **full sequence** from raw data to a live order, naming the artefact at each hand-off.

### F. Dynamic backtesting
Answer the user's "如何根据动态的训练情况动态的回测" precisely:
- Define it as a **walk-forward simulation with per-fold model selection**: for each month, the model
  trained on data before that month decides that month's trades; the equity curve is the concatenation.
- Specify what must be reported per fold (n candidates, n trades, win rate, expectancy in R **net of
  costs**, PF, CI, the model's train/valid/test windows, the feature importances, and the **prediction
  drift**: the model's live P(Win) distribution vs its training distribution — this is the "dynamic
  training" signal).
- Specify the **degradation monitoring**: how a human notices the model decaying and what the
  kill-switch is (the doc requires a paper-trading stage; state the abort criteria).
- Specify the **multiple-testing correction**: we have already run 32 arms plus a concurrency artefact.
  Name the method (deflated Sharpe ratio / PBO) and say what it requires.
- Be explicit that dynamic backtesting does **not** manufacture an edge; it measures how fast an edge
  decays once it exists.

### G. Verdict
```
DATA SUFFICIENT FOR PHASE 1 (NQ):   yes / no / conditional
DATA SUFFICIENT FOR PHASE 1 (crypto): yes / no / conditional
MISSING DATA, PRIORITISED:          <ordered list with cost>
ROLLING ML DESIGN:                  <one paragraph>
ROLLING RL FEASIBLE TODAY:          yes / no / conditional
E2E PIPELINE:                       <one paragraph>
```

## Constraints
- Write **only** `research/audit/L4_ROLLING.md` (create `research/audit/` if needed).
- Read-only elsewhere; scratch in `/tmp` only. Do not write to the NFS lake.
- You MAY compute exploratory statistics on the lake data (read-only).
- Do not implement. Specify.
- `[FACT]` / `[INFERENCE]` / `[PROPOSAL]`, with file+line citations and commands for every number.

## Deliverable
`research/audit/L4_ROLLING.md`. Final reply: the seven-line verdict block plus the top-3 missing data items.
