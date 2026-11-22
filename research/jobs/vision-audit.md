# Job: Audit the vision cross-validation layer against the real detector model

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. The four-layer design (`iFVG几个模型的讨论.txt`, module 1) puts a
**vision cross-validation** layer between the deterministic rule engine and the ML meta-labeling filter:

- when the rule engine fires a candidate iFVG, render the last **60** indicator-free candles to a
  **224×224** image,
- run a detector (`ibtsam/nq-fvg-detector`, described in the doc as YOLOv26m-based) to get FVG bounding boxes,
- compute the **IoU** between the detected box and the rule engine's FVG price zone **in pixel space**,
- gate: proceed only if `rules_triggered == True AND iou > 0.75`, claiming this filters ~35% of noise,
- feed the confidence / IoU downstream as the "视觉检测置信度" feature and as a custom `Data` event.

The model is downloaded at `research/huggingface/nq-fvg-detector/` by a sibling worker (see
`research/huggingface/DL_REPORT.md`). Another sibling produced `research/docs/RULE_SPEC.md` from the prose.

Your job is to determine whether this layer, as specified, can actually work — and to specify it correctly.

## Your task
Produce `research/analysis/VISION_AUDIT.md`.

### A. Model forensics
From the downloaded artifacts (config, weights, card, any sample images):
- exact architecture family and version, the checkpoint file(s) and format, total parameters, and whether the
  weights can even be loaded by current `ultralytics` (note: YOLOv26 may be very new — check the README
  requirements and flag if a specific ultralytics version/git commit is required)
- the class names, the input resolution, and the confidence/NMS defaults the card recommends
- **the training chart style**: background colour, whether candles are drawn with wicks, whether any
  indicator/grid/axis is present, aspect ratio, chart type. Quote the card/README text supporting your answer,
  and list the sample images if any were included.
- the training dataset composition (which symbols, timeframes, how many images) and the annotation convention
  (box around the gap region? around the candles?)

### B. The white/black contradiction — resolve it
The doc requires a **black-background 224×224** render; the model's card (per earlier reading) claims training on
**white-background TradingView charts**. This is a hard contradiction: a detector trained on white charts will
mis- or under-fire on black renders. Investigate and decide, with evidence:
- what the model actually expects (inspect any inference example, training config, or augmentation settings)
- which of the three options is right, and why: (i) render white to match the model, (ii) retrain/fine-tune on
  our own black 224×224 renders, (iii) render in a neutral style and normalise
- state the concrete recommendation and its cost (effort, data needed, expected accuracy impact)
- quantify the resolution mismatch: the model wants 640×640 (or whatever it wants) while the doc wants 224×224
  — what happens to small FVG boxes at 224×224 given a 60-bar window? Compute the pixel height of a typical
  NQ 1-minute FVG in the doc's own coordinate system and say whether 0.75 IoU is even achievable.

### C. The IoU contract
The doc says IoU is computed between the detector's box and the rule engine's FVG price zone, "on the vertical
price axis". Define this precisely, because the naive reading is wrong:
- a detector box is a 2D rectangle in image pixels; the rule zone is a 1D price interval. Specify exactly how
  the rule's [gap_low, gap_high] price interval maps to pixel rows (the chart's price→pixel transform, its
  axis padding, and the bar-window offset)
- then state the exact IoU formula the implementation must use (e.g. 1-D interval IoU over the vertical axis,
  or 2-D box IoU after expanding the rule zone to the bar range) — and compute what value a *perfect* match
  would yield under each candidate definition. A definition under which a perfect match scores < 0.75 makes the
  gate unreachable; if that is the case, say so and give the corrected threshold.
- address the x-axis: does the detector's horizontal extent get used at all, and how do you align "the FVG
  formed around bar k" with the detector's box?

### D. Visual Clarity Score
The doc names a "Visual Clarity Score" but never defines it. Propose a concrete, computable definition that is
(a) derived only from what the detector gives us, (b) monotone in "clean price action", and (c) not a restatement
of IoU. Give the formula and its range, and mark it clearly as a proposal.

### E. Performance budget
The vision layer runs inside a backtest loop. Quantify: rendering cost, inference cost (GPU vs CPU) per
candidate, and the number of candidates per trading day at the doc's stated frequency. State whether the layer
is viable for a multi-year backtest and propose an offline batch design (render once, cache features, join by
timestamp) if it is not.

## Constraints
- Write ONLY `research/analysis/VISION_AUDIT.md`.
- Do NOT pip install. Do NOT load the weights or run inference (torch/ultralytics are not installed for the
  3.11 interpreter). Inspect files statically.
- Ground every claim in a specific file you read. Distinguish clearly: **[FACT]** (read from an artifact),
  **[INFERENCE]** (reasoned from a fact), **[PROPOSAL]** (your design decision).
- If a fact could not be established (e.g. the card is silent), say so rather than guessing.

## Surprises
Deliverable: `research/analysis/VISION_AUDIT.md`. Final message: the single most important finding (I expect
the colour/resolution contradiction) and your recommended fix. The captain transcribes it into `.field-guide/`.
