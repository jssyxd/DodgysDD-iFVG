# Job: Extract the canonical DodgysDD iFVG rule specification from the design discussion

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. The single source of truth for the intended system is the file
`iFVG几个模型的讨论.txt` (283 lines, Chinese). It contains: the iFVG concept, a survey of community
implementations, the user's stated requirements, and a full proposed architecture (NautilusTrader core,
four-layer EV system, cross-market migration table, three-phase roadmap).

Sibling agents are concurrently downloading the referenced artifacts (GitHub / HF / Kaggle). **You do not
need them** — your job is to turn the discussion into an unambiguous, implementation-ready spec that later
workers and reviewers can check code against.

Also read `AGENTS.md` at the project root (written by the captain) — it summarizes the current understanding.
Where you disagree with it, say so explicitly.

## Your task
Produce `research/docs/RULE_SPEC.md`: a precise, testable specification of the strategy and target system.

It MUST contain, at minimum:

### A. Strategy semantics (the deterministic core)
- The exact iFVG definition: the 3-candle FVG geometry for bullish and bearish cases, using the doc's own
  notation (`Candle[i-2].high < Candle[i].low` bullish, inverse bearish) — restate it as an unambiguous
  inequality with inclusive/exclusive bounds decided and stated.
- The 5-step state machine from the doc, each step broken into: precondition, exact numeric predicate,
  and what state is carried forward.
- Every numeric threshold with its source line in the doc: `0.25 * ATR(14)`, the 7–15 bar inversion window,
  the killzone windows `09:30–11:30` and `13:30–15:30` ET, the VXN regime bins `[0, 18, 28, 200]` -> labels
  `0/1/2`, the `0.58` P(Win) threshold, the `0.75` visual IoU threshold, the 60-bar chart window, the
  224x224 render size, the `> 55%` win-rate goal, the `Profit Factor > 1.25` phase-1 gate, `Sharpe > 1.8`,
  `max drawdown < 10%`, `$4.5` round-trip fees, `1–2 ticks` slippage, RR targets `1:1.5–1:2` / `1:2.5–1:3` /
  `1:2`, the `>= 2R` liquidity target rule, `+2` SMT score weight, the A+/A/B/C grades.
- For each threshold, mark it as either **[DOC]** (stated in the discussion), **[DERIVED]** (logically implied
  by the doc but not stated), or **[UNSPECIFIED]** (the doc needs it but does not give it). Every
  **[UNSPECIFIED]** item must get a proposed default with a one-line rationale — these are the open decisions
  the fleet must settle.
- The **ambiguity register**: a numbered list of every place the doc underdetermines behaviour. Examples to
  check for and include: what "body close thoroughly penetrates the far edge" means exactly (close beyond the
  far edge? equal to it?); which bar's ATR(14) is used and its period/warmup; whether the 7–15 bar window
  counts from FVG formation or from the sweep; what constitutes "the last impulse leg"; how EQH/EQL are
  detected (exact touches vs proximity); whether the checklist score thresholds per grade are defined
  anywhere; how A+ vs A is distinguished; whether the sweep must precede the FVG or may be simultaneous;
  which direction the FVG must oppose the sweep; what the "visual clarity score" formula is; how the
  "1-hour VXN change rate" is obtained from a daily VXN series.

### B. System semantics
- The four-layer architecture, the data flow between layers, and the **hard invariants** (RL must never open
  a position; the rule engine decides direction; ML only filters; no signal may be erased after the fact).
- The four-layer diagram `diagram-四层正 EV 量化系统完整架构.svg` and the module list in
  `diagram-目录结构规划.svg` — read both (extract SVG text with a small python/regex command; `read` renders
  SVGs as images) and reconcile them against the prose. Report any disagreement between the diagrams and
  the prose.
- The phase gates and what each phase must prove before the next may start.
- The cross-market migration table, verbatim, with the micro-tweaks per market.
- The explicit architectural argument against using AlphaGPT/Qlib as the signal source (the doc argues
  cross-sectional ranking is architecturally mismatched to a single-contract event state machine) and the
  limited role the doc DOES assign them.

### C. Traceability appendix
A table mapping each spec item to the doc line number(s) it came from, so a reviewer can verify each claim
independently.

## Constraints
- Write ONLY `research/docs/RULE_SPEC.md`.
- Do NOT download anything, do NOT clone anything, do NOT modify the discussion file.
- Cite line numbers for every spec item — the reviewer agent will check them.
- Where the doc is wrong or internally inconsistent (e.g. it calls the 15-bar confirmation and the 7–15
  window in different places), report the inconsistency rather than silently picking one.
- The doc ends with a caution "请谨慎使用此类代码" attached to the sample code — note that the sample
  `prepare_parquet.py` was written against an older NautilusTrader API and must be ported, not pasted.

## Surprises
Deliverable: `research/docs/RULE_SPEC.md`. Your final message should summarize the count of
[UNSPECIFIED] items and list the top 5 that most affect correctness. That list feeds the captain's field guide.

## Field guide (read before you start)
Read `.field-guide/env.md` and `.field-guide/sources.md` in the project root for environment quirks and
the exact re-fetch procedure for external artifacts. Do not edit the guide.
