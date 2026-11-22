# Leaf L1 — Vision iFVG detection and the dual-validation + alignment questions

## Context
Project: `/home/da/桌面/DodgysDD_ifvg` — a research-and-build repo for the DodgysDD iFVG strategy.
The captain is auditing whether the design discussion's requirements are actually implemented.

**This is a read-only audit leaf.** Do not modify any file except the one you own (below). Do not
dispatch other agents. Do not edit `.herd-swarm/decisions.md`.

## Required reading (read these FIRST)
- `.herd-swarm/decisions.md` — especially **D6** (the vision gate must be re-specified) and **D4**
  (the concurrency trap). These are decided; do not re-litigate them.
- `research/analysis/VISION_AUDIT.md` — the prior vision audit (measured).
- `research/docs/RULE_SPEC.md` — §on the vision layer and the ambiguity register.
- `research/audit/AUDIT.md` — the prior cross-audit, §A.3.
- The discussion `iFVG几个模型的讨论.txt` lines 133–139 and 272–281 (the vision module as specified).
- The upstream model card: `/home/da/桌面/DodgysDD_ifvg/research/huggingface/nq-fvg-detector/README.md`
  (**read-only**; that tree is gitignored and not present in worktrees).
- The training-set images: `/home/da/桌面/DodgysDD_ifvg/research/kaggle/nq-fvg-dataset/` (**read-only**).

## The two questions you must answer, definitively

**Q1 — Is the "visual iFVG detection + parameter-feature double validation" implemented?**
The discussion requires (L139): *only when `rule_engine_triggered == True` **and** `vision_iou > 0.75` may
the setup pass to the next layer* — a conjunction of a **parameter/rule** check and a **vision** check.

**Q2 — Are the two sides actually *aligned*?** i.e. does the vision module measure the **same object**
the rule engine measured, so that a disagreement is meaningful rather than an artefact of comparing
different things?

## Your task
Produce `research/audit/L1_VISION.md` (you own this file exclusively).

### A. Implementation status — the honest answer
Search the whole repository (including `research/`, `dodgys_dd_quant/` if it exists, and
`research/experiments/`) for any code that:
- renders candles to an image, or calls `mplfinance` / `matplotlib` to draw a chart;
- loads a YOLO/ultralytics model or the `best.pt` checkpoint;
- computes an IoU between a detection box and a rule-derived price zone;
- computes a "visual clarity score";
- gates a signal on a vision output.
State for each: **present / absent**, with the file and line, or an explicit statement that it is
absent and what you searched for (grep patterns, file globs).

Then state the answer to Q1 in one sentence, and to Q2 in one sentence.

### B. The alignment problem, analysed
Even though nothing is implemented, the *design* has an alignment defect that must be documented,
because it decides what to build:
- What does the rule engine measure? (per `research/analysis/PINE_RULES.md`: the FVG **price gap**,
  `fvgTop`/`fvgBottom`)
- What does the detector measure? (per the Kaggle labels: a box around the **third candle's body**)
- Are these the same object? Compute the geometric relation for a bullish FVG
  (`gap = [high_{i-2}, low_i]`, body of candle `i` sits at or above `low_i`) and for the bearish case.
- Therefore, what does a **perfect** detection score under the discussion's metric
  ("IoU on the vertical price axis", L279)? Show the arithmetic.
- Give the **corrected** alignment contract: what exactly must the vision module return so that it
  measures the same object as the rule engine, and what threshold is then meaningful.
- Propose the concrete function signature the vision module should expose, and the two columns it must
  add to the candidate log (the schema is frozen in `decisions.md` D2 — `vision_iou`, `vision_confidence`).

### C. Concrete build spec (the thing to implement later)
A precise, implementable spec for `dodgys_dd_quant/vision_validator/visual_cv.py`:
- inputs, outputs, the render convention (background colour, resolution, bar count, padding) **justified
  by the model's actual training distribution** — read the card and the training images and say what
  they show;
- the IoU definition to use, with the formula;
- the threshold to start from and how it should be calibrated (name the split and the procedure);
- the performance budget: cost per candidate, and whether it is viable inside a multi-year backtest
  loop or must be an offline batch job;
- what the layer can and **cannot** honestly claim (it cannot verify "clean price action" — say why).

### D. What the vision layer can actually buy us
Given D4 (the rule engine shows no edge), state whether a vision gate could plausibly create one:
if the rule layer's expectancy is ~0 and the vision layer only *filters* it, what is the maximum
achievable improvement, and under what conditions? Be quantitative, and be blunt if the honest answer is
"a filter on a zero-edge signal is still a zero-edge signal, and the vision layer's own measured
precision would have to exceed the base rate to help".

### E. Verdict
A short, explicit verdict block:
```
Q1 IMPLEMENTED:  yes / no / partial
Q2 ALIGNED:      yes / no / partial
RECOMMENDED:    <one paragraph>
```

## Constraints
- Write **only** `research/audit/L1_VISION.md`. You may create `research/audit/` if it does not exist.
- Read-only elsewhere. Do not run the detector or load `best.pt` (no torch/ultralytics for the 3.11
  interpreter). Inspect artefacts statically.
- Distinguish **[FACT]** (you read it), **[INFERENCE]** (you reasoned it), **[PROPOSAL]** (your design).
- Cite file paths and line numbers for every claim.
- Do not implement anything. Specify it.

## Deliverable
`research/audit/L1_VISION.md`. In your final reply, give the two one-sentence answers (Q1, Q2) and the
recommended action.
