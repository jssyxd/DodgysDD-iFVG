# Job: Assess reuse viability of the community ML quant frameworks and factor-mining tools

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. The four-layer design uses **NautilusTrader** as the sole
backtest/live engine, with ML as a *filter* (meta-labeling) and RL as a *position manager*. The design
discussion (`iFVG几个模型的讨论.txt`) surveyed three external projects and two factor-mining frameworks, and
argues that AlphaGPT/Qlib are architecturally mismatched. Our job is to turn that argument into a verified,
actionable reuse plan — and to see whether any of these projects contains code worth porting.

Artifacts already downloaded by sibling workers (see `research/github/CLONE_REPORT.md`,
`research/huggingface/DL_REPORT.md`):
- `research/github/AlphaGPT/` (imbue-bit) and `research/github/AlphaGPT-By-imbue-bit/` (community mirror)
- `research/github/qlib/` (microsoft)
- `research/huggingface/xauusd-ml-trader/` (nerds-gaming) — a Python quant framework with liquidity-sweep
  detection, FVG imbalance detection, Asian/London/US session filters and risk management; order-block entry
- `research/huggingface/ict-6000-mentorship-master/` (dataset) — structured ICT rule-reasoning data

## Your task
Produce `research/analysis/ML_REUSE.md`.

### A. xauusd-ml-trader — the primary reuse candidate
- Module/file tree with per-file responsibility; the framework (pandas? vectorbt? custom event loop?),
  the entry/exit logic, the order-block entry, how liquidity sweeps and FVG imbalance are implemented, the
  session filters, and the risk-management block
- **The conversion plan**: precisely how to rewrite its OB-entry into the DodgysDD iFVG entry
  ("FVG broken by a body close -> zone inverts -> enter on retest"), naming the functions to change and what
  the new decision function looks like
- What is directly reusable (sweep detection, session filters, ATR gap filter, sizing) and what must be
  rewritten. Give a per-module verdict: **port as-is / port with edits / reference only / discard**
- The data-format assumptions (OHLCV columns, index dtype, timezone, instrument symbol, timeframe) — this
  decides whether it can consume our Nautilus Parquet catalog

### B. AlphaGPT — can it mine factors for us?
- What its core abstractions actually are (symbolic regression? Transformer sequence generation? which
  search/validation loop?), what its data adapters look like, and what a "factor" means in its schema
- The decisive question: its factor pipeline is aimed at **cross-sectional** stock ranking (IC/RankIC) while we
  need **single-contract, event-conditioned** features on NQ 1-minute bars. Assess concretely: could its
  expression search be pointed at our event timestamps instead? What would have to change (target definition,
  evaluation metric, sampling)?
- Verdict: usable as a research tool for auxiliary microstructure features at event time, or architectural
  dead end? Give a concrete pilot plan **only if** the answer is "usable", with an explicit statement of what
  the pilot would measure and what result would disqualify it
- Note the licence and the community mirror's staleness (does the mirror differ from upstream? does it lag?)

### C. Qlib — same questions, plus an integration question
- Core abstractions: data layer, workflow/experiment orchestration, model zoo, the backtest/record framework
- **Critical**: does Qlib support futures and single-instrument event-driven strategies, or is it equity-candle
  + cross-sectional only? Check the actual data layer and the backtest executor for assumptions about
  cross-sectional date panels, universe selection, and long-only ranking
- If someone wanted to use Qlib only for its **rolling-training / concept-drift** machinery (the doc's stated
  legitimate use), what exactly would be reused, and what is the integration cost against a NautilusTrader
  pipeline? Concretely: could Qlib's rolling retrain orchestration drive our monthly LightGBM refit without
  adopting Qlib's data layer?
- Verdict per component

### D. The ICT reasoning dataset
- Schema, row structure, how a rule is expressed, size
- Is it usable as (i) a feature-engineering reference, (ii) a rule-audit checklist for validating our state
  machine, (iii) LLM fine-tuning data? Assess each honestly
- **Anti-hallucination check**: sample several rows and judge whether the "reasoning" is actually derived from
  price structure or is generic ICT prose that would not survive contact with real bars. Give a concrete
  verdict on whether any of it can be converted into a deterministic test.

### E. Recommended reuse plan
A single decision table: for each of the 5 external artifacts — **use / adapt / borrow-ideas-only / discard**,
with the deciding reason and the concrete next action. Then a short ordered list of the highest-value
code to port into `dodgys_dd_quant/`, with estimated effort and the risk it removes.

## Constraints
- Write ONLY `research/analysis/ML_REUSE.md`.
- Read the actual source. Do not describe these projects from memory.
- Do NOT pip install, do NOT run their training pipelines, do NOT execute their code on our data.
- Be blunt when something is a dead end — a clear "discard" is a valuable result here.

## Surprises
Deliverable: `research/analysis/ML_REUSE.md`. Final message: the reuse table in one line each, plus the
single highest-value piece of external code to port. Captain transcribes into `.field-guide/`.
