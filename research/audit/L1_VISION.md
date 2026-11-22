# L1_VISION — the vision layer: is it implemented, and do the two sides measure the same object?

**Leaf:** L1 (vision / dual-validation) · **Type:** read-only audit · **Date:** 2026-11-22
**Deliverable owner:** `research/audit/L1_VISION.md` (this file)

**Evidence labels used throughout**

| Tag | Meaning |
|---|---|
| `[FACT]` | Read directly from a named artefact in this repo, or measured by me on a named artefact (method in the Appendix). |
| `[INFERENCE]` | Reasoned from one or more `[FACT]`s; the reasoning is stated. |
| `[PROPOSAL]` | A design decision made by this audit; not derivable from the artefacts. |

**Constraints honoured** — no file modified except this one; no detector run; `best.pt` not loaded (no
`torch`/`ultralytics` for the 3.11 interpreter); the Hugging Face and Kaggle trees were read
**statically** from the main tree at their absolute paths (`research/huggingface/…`,
`research/kaggle/…` — gitignored per D10, so absent from worktrees); no agent dispatched; no
`decisions.md` edit.

**Decisions this leaf obeys and does not re-litigate:** D2 (frozen candidate-log schema), D4 (the
rule engine has no measured edge; one-position-at-a-time is the only quoting basis), D6 (the vision
gate targets a **2-D box IoU against the third candle's body**, and `VISION_IOU_THRESHOLD = 0.75`
must be deleted), D8 (no grade filtering), D9 (costs live in the config, quoted at 0/1/2 ticks),
D10 (read the upstream corpus from the main tree, read-only).

---

## 0. The two answers, up front

> **Q1 — Is the "visual iFVG detection + parameter/feature double validation" implemented?**
> **No.** There is **no vision code of any kind** in this repository: the entire implementation
> corpus is **one** Python file (`research/experiments/e1_rule_falsification.py`, 431 lines), which
> contains no rendering, no detector, no IoU and no vision gate. Every mention of the vision layer
> is prose, a diagram label, or an audit of a **specification that does not exist as code**.

> **Q2 — Are the two sides actually aligned?**
> **No, and they cannot be as specified.** The rule engine measures the FVG **price gap**
> (`G_bull = [c[i-2].high, c[i].low]`, `G_bear = [c[i].high, c[i-2].low]`), while the detector
> measures a **tight sub-box of the third candle's body**; those two objects are **disjoint by
> construction**, so under the discussion's own metric ("IoU on the vertical price axis", L279) a
> **perfect** detection scores **IoU = 0.00**, not 1.00. The alignment must be re-pointed at the
> third candle's body (D6) — and even then the metric must be re-derived, because the annotation
> convention caps the achievable IoU (measured below: median ≈ 0.39 against the true body
> rectangle, only 2.1 % reach 0.75).

---

## A. Implementation status

### A.1 Search protocol

`[FACT]` The repository root is `/home/da/桌面/DodgysDD_ifvg`, git branch `main` @ `53dc496`,
one worktree (the main tree itself; `git worktree list` shows only the root), and the whole
tracked tree is **43 files**. `research/github/`, `research/huggingface/`, `research/kaggle/` are
gitignored (D10) and are **upstream reference corpora**, not our code.

Searches actually run (all from the repo root):

```bash
# 1. every Python file we own
find . -name '*.py' -not -path './.git/*' -not -path './research/github/*' \
    -not -path './research/huggingface/*' | sort
#   → ./research/experiments/e1_rule_falsification.py      (ONE file)

# 2. the planned package roots
ls -d dodgys_dd_quant configs tests data artifacts
#   → ls: cannot access 'dodgys_dd_quant': No such file or directory   (and likewise for the rest)

# 3. rendering / detector / metric / gate, over code + config + docs + diagrams
grep -rniE 'mplfinance|matplotlib|ultralytics|YOLO|best\.pt|torch|cv2|opencv|PIL|savefig|imgsz|candlestick|render' \
     --exclude-dir=.git --exclude-dir=github --exclude-dir=huggingface --exclude-dir=kaggle \
     --include='*.py' --include='*.toml' --include='*.cfg' --include='*.txt' --include='*.json' \
     --include='*.sh' --include='*.yaml' --include='*.yml' --include='*.svg' .

# 4. history: has a vision file ever existed?
git log --all --diff-filter=A --name-only --pretty=format: | sort -u
git ls-files | grep -iE 'vision|visual|yolo'
```

### A.2 Findings, capability by capability

| # | Capability required by the design | Status | Evidence |
|---|---|---|---|
| 1 | **Render candles to an image** (`mplfinance` / `matplotlib`) | **ABSENT** | No `import mplfinance` / `import matplotlib` / `plt.` / `savefig` anywhere in any tracked file. The only hits for `mplfinance` are prose: `iFVG几个模型的讨论.txt:137`, `:201` (a `pip install` line inside the doc), `:279`. `matplotlib` → **zero** hits repo-wide. |
| 2 | **Load a YOLO/ultralytics model or `best.pt`** | **ABSENT** | `best.pt` → zero hits outside the gitignored `research/huggingface/` corpus. `ultralytics` → one hit, `iFVG几个模型的讨论.txt:201` (the doc's install line). `torch` → **zero** hits. `YOLO` → prose only: `iFVG几个模型的讨论.txt:65`, `:274`, `:279`, and two SVG labels (`diagram-四层正 EV 量化系统完整架构.svg:91`, `diagram-目录结构规划.svg:66`). |
| 3 | **Compute an IoU between a detection box and a rule-derived price zone** | **ABSENT** | No IoU function, no box/zone comparison, no pixel↔price mapping. `research/experiments/e1_rule_falsification.py` contains no occurrence of `iou`, `vision`, `image`, `yolo`, `render`, `visual` or `clarity` (grep over the file returns one incidental match, line 5, in the docstring: *"before any ML, any vision model or any NQ data"*). |
| 4 | **Compute a "Visual Clarity Score"** | **ABSENT** | The term exists only as a spec: `iFVG几个模型的讨论.txt:138`; `research/docs/RULE_SPEC.md:215` (T23, "formula undefined"), `:268` (A16, a *proposed* formula), `:587` (S22). No code, and **no agreed formula** — A16 remains a proposal, and this leaf argues in §C.6 that it is the wrong formula. |
| 5 | **Gate a signal on a vision output** | **ABSENT** | The gate is specified at `iFVG几个模型的讨论.txt:139` and restated in `research/docs/RULE_SPEC.md:211` (T19), `:404` (INV5), `:419` (layer-2 hard gate), `:585–587` (S21–S23). There is **no strategy, no engine, no `on_bar` handler** anywhere to host it: `dodgys_dd_quant/strategy/` does not exist. |
| 6 | **The candidate log the vision layer would write into** | **ABSENT** | D2 freezes `research/candidates/{symbol}_{timeframe}.parquet` with `vision_iou` and `vision_confidence` columns; the directory does not exist and no writer exists. |
| 7 | **The one executable experiment in the repo** | **PRESENT but vision-free** | `research/experiments/e1_rule_falsification.py` — a rule-engine falsification test (`find_candidates` at L186, `run_arm` at L208, `summarise` at L324). It has **no** vision dimension; it was never supposed to (its purpose is D4). |

`[FACT]` **Git history confirms nothing was ever deleted.** `git log --all --diff-filter=A --name-only`
lists every file ever added: the only `.py` file that has *ever* existed in this repository is
`research/experiments/e1_rule_falsification.py`. There is no branch, no stash and no worktree
containing a vision module.

`[FACT]` `research/analysis/VISION_AUDIT.md` and `research/audit/AUDIT.md` §A.3 are **audits of an
artefact set** (the upstream checkpoint and the Kaggle dataset), not of our code. Neither document
claims that any code exists; this leaf confirms that claim holds.

### A.3 The answers to Q1 and Q2

> **Q1 — IMPLEMENTED: no.** Not "partial": the *entire* vision layer — renderer, detector wrapper,
> IoU, Visual Clarity Score, and the `rule_triggered AND vision_iou > 0.75` conjunction — is absent;
> what exists is a written specification (`iFVG几个模型的讨论.txt:133–139`, `:272–281`; the two SVGs)
> and a measured critique of it (`research/analysis/VISION_AUDIT.md`; `research/audit/AUDIT.md` §A.3).
> The "double validation" of L139 is a *sentence*, not a code path.

> **Q2 — ALIGNED: no.** The two sides measure **different objects**: the rule engine measures the
> FVG **price gap** (`RULE_SPEC.md:59`, `:68`), the detector measures a **box around the third
> candle's body** (measured on the dataset's own labels, §B.2). They are **disjoint** (empty
> intersection), so a disagreement between them carries no information — it is a geometric
> tautology, not a validation. See §B.

---

## B. The alignment problem, analysed

### B.1 What the rule engine measures — the **price gap**

`[FACT]` `research/docs/RULE_SPEC.md:49–80` (§1.2, from `iFVG几个模型的讨论.txt:121`):

```
Bullish FVG:  c[i-2].high  <  c[i].low
               G_bull = [ c[i-2].high , c[i].low ]      # lower edge = c[i-2].high, upper edge = c[i].low
               gap_size = c[i].low - c[i-2].high       # RULE_SPEC.md:59
Bearish FVG:  c[i-2].low   >  c[i].high
               G_bear = [ c[i].high , c[i-2].low ]      # lower edge = c[i].high, upper edge = c[i-2].low
               gap_size = c[i-2].low - c[i].high       # RULE_SPEC.md:68
```

`[FACT]` This is corroborated by the upstream reference implementation: `research/analysis/PINE_RULES.md`
§R2 (pine:354–355) — `fvgHere = isLow ? low[1] > high[3] : high[1] < low[3]`,
`fvgTop = isLow ? low[1] : low[3]`, `fvgBottom = isLow ? high[3] : high[1]` — i.e. **the gap is
measured edge-to-edge on wicks**, and it is the **empty space between** candle 1 and candle 3.

`[FACT]` The gap is **one-dimensional**: a price interval with **no horizontal extent**. It is not
attached to a bar. (`RULE_SPEC.md:160` carries `fvg_c1_idx`, `fvg_c3_idx`, `gap_low`, `gap_high`,
`gap_size` as separate state — the indices exist, but the *gap* itself is an interval.)

### B.2 What the detector measures — a **box on the third candle's body**

`[FACT]` From `research/analysis/VISION_AUDIT.md` §A.8, re-verified by me on the Kaggle tree
(method in the Appendix):

* the dataset is `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/{train,valid,test}/{images,labels}`,
  295 images, **3,650** YOLO boxes (`data.yaml`: `nc: 2`, `names: ['bearish_fvg','bullish_fvg']`);
* **median box size = 5.50 × 16.50 px @640** (p10/p90 width 5.00/6.50);
* the annotation convention is a **per-candle marker on the third (gap-opening) bar**, not a
  rectangle drawn over the empty gap.

`[FACT]` **My own independent measurement** on the same tree (43 images, 489–524 boxes, sampled
every 7th image):

| Measurement | Result |
|---|---|
| Box **centre column** is ≥ 80 % candle-coloured *within the box's own row range* | **99.1 %** of 327 boxes |
| Distance from the box centre to the nearest candle-bearing column | **0 px in 327/327 cases** |
| Fraction of the box's **rows** lying inside the same candle's **body** rows | median **1.0000**; 92.2 % ≥ 0.9 |
| Candle bodies per 640×640 image | median **87** (range 70–92) ⇒ bar pitch ≈ **7.36 px** |
| Body width in px | median **5.0** (p10 = p90 = 3 for the 3-px-wide strict test; 5 px when the ink run is taken at full width) |
| Body height in px | median **39** |
| Annotation box width ÷ body width | ≈ 1.1 (box is **wider** than the strict body ink run but **narrower** than the full body at its widest row) |
| Vertical position of the box within the body | the box covers only the **middle/lower part** of a long body — the annotation is a **tight sub-box of the body**, *not* the body's full extent |

`[FACT]` **Visual confirmation** (I cropped and 8× upscaled two annotated boxes from
`test/images/1min-NQ-103_png.rf.bb6a8c94dd2554fb82e795a48b393e11.jpg` and drew the label box in
red):

* the **bullish** box wraps the **body of one teal candle** in an up-leg — a long teal body with the
  red box hugging its lower-middle;
* the **bearish** box wraps the **body of one black candle** in a down-leg — again a tight sub-box;
* the surrounding chart is **white** with faint grey gridlines, **filled** bodies (teal up,
  near-black down), **thin wicks** present above and below bodies, **no axes, no legend, no
  indicators, no price labels**.

`[INFERENCE]` Therefore the detector's answer to "where is the FVG?" is *"here is a rectangle
wrapped around one candle's body"*. It answers a **bar-localisation** question, not a
**gap-region** question. This is consistent with the card: `bullish_fvg` = *"gap created during
upward impulse move"* (`research/huggingface/nq-fvg-detector/README.md:42`).

### B.3 The geometric relation — the two objects are **disjoint**

Let `A = c[i-2]` (older), `B = c[i-1]` (middle), `C = c[i]` (newest = the **third** candle = the
gap-opening bar = the annotated candle).

**Bullish FVG** (`A.high < C.low`):

```
gap      G_bull = [ A.high , C.low ]        # RULE_SPEC.md:59
body(C)       ⊆ [ C.low , C.high ]         # a body is inside the bar's own wick range
             and  min(open_C, close_C) ≥ C.low
⇒  body(C) ∩ G_bull = ∅                    # the body sits AT or ABOVE the gap's upper edge
```

**Bearish FVG** (`A.low > C.high`):

```
gap      G_bear = [ C.high , A.low ]        # RULE_SPEC.md:68
body(C)       ⊆ [ C.low , C.high ]
             and  max(open_C, close_C) ≤ C.high
⇒  body(C) ∩ G_bear = ∅                    # the body sits AT or BELOW the gap's lower edge
```

`[INFERENCE]` **In both directions the annotated object and the rule object are strictly
separated by the gap itself.** The gap is, by definition, the empty space *between* candle 1 and
candle 3 — and the detector draws its box on candle 3's body. There is no configuration of prices
in which the two overlap. (The degenerate case `min(open_C,close_C) == C.low` is a measure-zero
touch, still zero IoU; the reference implementation rejects zero-width gaps outright —
`research/analysis/PINE_RULES.md` §R2, "Both comparisons are strict".)

### B.4 What a **perfect** detection scores

**Under the discussion's literal metric** (`iFVG几个模型的讨论.txt:279`: *"计算其与规则引擎在**垂直价格轴**上的 IoU 交并比"*):

```
IoU_v = |[y1,y2] ∩ [r0,r1]| / |[y1,y2] ∪ [r0,r1]|
   where [y1,y2] = the detector box's row span, [r0,r1] = the rule gap's row span

PERFECT DETECTION:
   bullish:  body rows ∩ gap rows = ∅  ⇒  IoU_v = 0 / (|body| + |gap|) = 0.00
   bearish:  body rows ∩ gap rows = ∅  ⇒  IoU_v = 0.00
```

`[FACT]` This is corroborated three ways in the existing corpus:

* `research/analysis/VISION_AUDIT.md` §C.2 (D1): *"A perfect detection scores IoU_v = 0.00, not
  1.00"*; §A.9's histogram on the model's own labels: median **0.0000**, **87.9 % exactly zero**,
  **0.65 %** above 0.75.
* `research/audit/AUDIT.md:293–345` (§A.3.2), which re-derived the algebra independently and
  confirmed it *"algebraically and necessarily"*, and noted it could not reproduce §A.9's
  histogram (§A.3.5, marked UNSUPPORTED but not load-bearing).
* `research/docs/RULE_SPEC.md:302` records the unresolved ambiguity (T19 ↔ A32): 1-D price-axis IoU
  vs 2-D pixel IoU.

**Under the discussion's other metric** (`iFVG几个模型的讨论.txt:274`: *"在**像素坐标系**下的 IoU"*):

```
rule-side object  R = x ∈ [x(i-2), x(i)]  ×  rows ∈ [y(gap_high), y(gap_low)]
detector box      B = x ∈ [x(i)±w/2]     ×  rows ∈ [y(body_top), y(body_bottom)]
R ∩ B = ∅ in the row dimension (by §B.3)  ⇒  IoU_2D = 0.00 as well.
```

`[INFERENCE]` **Both readings of the doc give the same answer: a perfect detection scores 0.00.**
So `VISION_IOU_THRESHOLD = 0.75` (`RULE_SPEC.md:211`; `AGENTS.md` constants list) rejects
**100 %** of correct detections — a gate that is not merely strict but **inverted**. This is
precisely what D6 settles, and my measurement below tells the implementer what the *correct* gate
should look like.

**For completeness**, the two "fix-ups" that do *not* fix it, because the mismatch is semantic:

* *Give the rule zone a 3-bar rectangle and do a 2-D IoU* — the detector's box is ≈ 1 bar wide
  (5.5 px) and the rule rectangle is ≈ 3 bars wide (3 × 7.36 = 22.1 px), so
  `IoU_2D ≤ 5.5 / 22.1 = 0.25` **even with a perfect vertical match**
  (`research/analysis/VISION_AUDIT.md` §C.2 D2; `research/audit/AUDIT.md:336–346`).
* *Do the IoU at 224×224* — at 224 px the median box is 1.93 × 5.77 px and a **quarter-pixel** x
  misalignment already drops the combined 2-D IoU to 0.708 < 0.75
  (`research/audit/AUDIT.md:327–346`). The threshold is unreachable on a **second, independent
  ground**: sub-pixel geometry.

### B.5 The corrected alignment contract

`[PROPOSAL]` **Contract V-1 — the vision module must measure the third candle, not the gap.**

1. **Same input.** The vision module is given the *same bars* the rule engine used and the *same
   bar indices*, so that the FVG's third candle occupies a known slot in the rendered window. It
   must receive `fvg_c1_idx`, `fvg_c3_idx`, `gap_low`, `gap_high` **and** the third candle's
   `open`/`close` (`RULE_SPEC.md:160` already carries the first four; `open_3`/`close_3` must be
   added to the rule engine's event payload).
2. **Same object.** The rule-side object becomes the **third candle's body rectangle**

   ```
   R' = x ∈ [x(i) − w_body/2 , x(i) + w_body/2 ]  ×  rows ∈ [ y(max(open_i, close_i)) , y(min(open_i, close_i)) ]
   ```

   where `y(·)` and `x(·)` are the renderer's explicit affine map and `w_body` the rendered body
   width. Every quantity is computed through that map; the axis is **never** re-derived from the PNG.
3. **Matching = bar identity + class, not geometry.** The detector's box is ~0.85 bar wide, so its
   **horizontal centre** identifies the bar: `k = round(x_centre / bar_pitch)`; require
   `k == fvg_c3_index`. The detector's **class** must equal the gap's direction
   (`bullish_fvg` → bullish gap → **short** side, because the strategy trades *against* the gap —
   `RULE_SPEC.md:160`, `trade_direction` = opposite of `fvg_dir`).
4. **The metric is the 2-D IoU between the matched box and `R'`.** A perfect detection now scores
   **1.0** in principle, and the metric means something the model can actually achieve.
5. **The gap IoU is demoted to a descriptive statistic.** `IoU_v_gap` is reported (it is a useful
   *sanity* number: it should be ≈ 0 for a correct match, and a non-zero value means the renderer
   and the rule engine disagree about the price axis) but is **never a gate**.

**The threshold — and a measured warning about it.** `[FACT]` D6 says "start ≈ 0.5, then calibrate".
`[FACT]` My measurement of the *achievable* distribution (the dataset's own ground-truth boxes
against the *true pixel body rectangle* of the candle they mark, 524 boxes over 75 images) gives:

| statistic | 2-D IoU(annotation box, true body rect) |
|---|---|
| median | **0.393** |
| mean | 0.417 |
| p10 / p90 | 0.200 / 0.652 |
| fraction ≥ 0.30 | **72.1 %** |
| fraction ≥ 0.40 | 49.2 % |
| fraction ≥ 0.50 | **33.0 %** |
| fraction ≥ 0.75 | **2.1 %** |

`[INFERENCE]` Two consequences, both important:

* **0.75 is wrong even against the correct object** — the model's *own ground truth* would fail it
  **98 %** of the time. (The cause is the annotation convention: the box is a **tight sub-box of
  the body**, not the body. See the visual crops in §B.2.)
* **0.50 is still too aggressive as a *starting* point for the 2-D IoU**: it would reject **two
  thirds** of the model's own correct labels. The band that admits most correct detections is
  **≈ 0.30–0.35**.

`[PROPOSAL]` **Therefore the gate is three-part, and the IoU is the weakest of the three:**

```
pass  ⇔  class_match  AND  bar_index_delta == 0  AND  vision_iou ≥ τ
        (τ calibrated; see §C.4 — pre-registered default τ = 0.30 for the 2-D IoU)
```

with two **sharper, convention-robust** diagnostics carried in a side table (§B.6):

* `row_containment = |box_rows ∩ body_rows| / |box_rows|` — measured median **1.000**, 92.2 % ≥ 0.9
  on the ground truth. Far more discriminative than the IoU, because it is insensitive to the
  "box is tighter/wider than the body" convention.
* `bar_index_delta` — an exact integer test, calibration-free.

`[INFERENCE]` The honest semantic claim of the layer is therefore **"the vision model independently
localises the same bar"** (D6's wording), *not* "the vision model verifies the price gap" and not
"the vision model verifies clean price action" (§C.6).

### B.6 The proposed interface and the two columns it must add

`[PROPOSAL]` **Public surface of `dodgys_dd_quant/vision_validator/visual_cv.py`** — one pure
function, one dataclass in, one dataclass out, no I/O, no engine calls:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence

@dataclass(frozen=True, slots=True)
class VisionStyle:
    """Single source of truth for the render convention. VERSION must change whenever
    any visual parameter changes, so a style change can never be mistaken for a model change."""
    version: str = "v1-tv-white-640"
    width: int = 640
    height: int = 640
    window_bars: int = 90
    background: str = "#FFFFFF"
    grid_color: str = "#FAFAFA"
    up_color: str = "#08987F"
    down_color: str = "#0A0A0A"
    wick_color: str = "#0A0A0A"
    body_width_frac: float = 0.68      # of the bar pitch
    pad_frac: float = 0.10             # symmetric, of the window's price range
    imgsz: int = 640
    conf: float = 0.25

@dataclass(frozen=True, slots=True)
class RenderedWindow:
    image: np.ndarray            # (H, W, 3) uint8
    row_of_price: Callable[[np.ndarray], np.ndarray]
    col_of_bar: Callable[[int], float]
    bar_pitch_px: float
    body_width_px: float
    window_start_ts_ns: int
    window_end_ts_ns: int

@dataclass(frozen=True, slots=True)
class VisionVerdict:
    vision_iou: float            # 2-D IoU(detector box, third-candle body rect); NaN if no match
    vision_confidence: float     # detector confidence of the matched box;    NaN if no match
    vision_iou_gap: float        # descriptive 1-D vertical IoU vs the FVG gap (≈0 by construction)
    row_containment: float      # |box_rows ∩ body_rows| / |box_rows|
    matched_bar_index: int       # bar slot (within the window) the box centre maps to
    bar_index_delta: int        # matched_bar_index - fvg_c3_slot; must be 0
    class_match: bool
    n_detections: int
    style_version: str
    image_sha256: str
    passed: bool                # the gate decision at the calibrated threshold

def evaluate_candidate(
    bars: BarWindow,             # the W bars ending at the confirmation bar (oldest first)
    fvg_c1_slot: int,            # slot (within the window) of the FVG's oldest candle
    fvg_c3_slot: int,            # slot of the FVG's newest candle = the gap-opening bar
    gap_low: float,
    gap_high: float,
    direction: int,              # +1 = bullish gap, -1 = bearish gap
    detector: Detector,          # protocol: .detect(image) -> list[Detection]
    style: VisionStyle = DEFAULT_STYLE,
    iou_threshold: float = VISION_BODY_IOU_THRESHOLD,
) -> VisionVerdict:
    ...
```

`[PROPOSAL]` **The two columns added to the frozen candidate log (D2)** — exactly these two, no
more, because D2's schema is frozen:

| D2 column | Type | What the vision module must put there |
|---|---|---|
| `vision_iou` | f64 | **the 2-D IoU between the matched detector box and the third candle's body rectangle**, computed through the renderer's affine map. `NaN` when the vision pass was not run for this row. |
| `vision_confidence` | f64 | **the detector's own confidence for the matched box** (`results.boxes.conf`), in [0,1]. `NaN` when not computed. |

`[PROPOSAL]` **Everything else goes into a side table, so D2 stays byte-identical:**

```
research/candidates/{symbol}_{timeframe}.vision.parquet     # keyed by (symbol, ts_event)
    vision_iou_gap, row_containment, matched_bar_index, bar_index_delta,
    class_match, n_detections, style_version, imgsz, window_bars, image_sha256
```

`[INFERENCE]` The side table is also what makes the gate auditable: D2's invariant ("every row is a
candidate, including losers") means the vision gate **cannot** be a row filter — it must be a
*column* that the strategy consults at execution time. A candidate with `vision_iou = NaN` is a
**reject** (the doc's gate is a conjunction, so a missing feature must fail it) and must be
**counted and printed** in every backtest report, otherwise a join bug silently changes the
traded set (`research/analysis/VISION_AUDIT.md` §E.4 step 6).

---

## C. Concrete build spec for `dodgys_dd_quant/vision_validator/visual_cv.py`

### C.1 Inputs

| Input | Type | Source |
|---|---|---|
| `bars` | the last `W` bars of the traded instrument, **ending at the confirmation bar's close** | rule engine event |
| `fvg_c1_slot`, `fvg_c3_slot` | int — the FVG's oldest and newest candle, as slots in the window | rule engine (`RULE_SPEC.md:160`) |
| `open_3`, `close_3` | float — the third candle's open and close | rule engine (**must be added**) |
| `gap_low`, `gap_high` | float | rule engine (`RULE_SPEC.md:160`) |
| `direction` | +1 bullish gap / −1 bearish gap | rule engine |
| `detector` | a `Detector` protocol object wrapping the ultralytics model | module-level singleton |

`[PROPOSAL]` **Look-ahead guard (mandatory, asserted not assumed):** the render window must end at
or before the confirmation bar's close, i.e. `window_end_ts_ns ≤ ts_event`. Assert it and abort the
row on violation.

### C.2 The render convention — justified by the model's **actual** training distribution

`[FACT]` What the model was trained on, measured by me on the Kaggle tree and cross-checked
against `research/analysis/VISION_AUDIT.md` §A.7 and `research/audit/AUDIT.md:361–371` (§A.3.4):

| Property | Training distribution (measured) | The discussion's requirement | Verdict |
|---|---|---|---|
| Background | **pure white `#FFFFFF`** (65.8 % of pixels are exactly `srgb(255,255,255)`; corners `(5,5)` = 255/255/255) | "纯黑背景" (black) — `iFVG几个模型的讨论.txt:279`; 224×224 — `:137` | **wrong on both axes** |
| Grid | faint grey `#FAFAFA`/`#F6F6F6`, horizontal **and** vertical | not specified | adopt |
| Up body | teal, `(0–20, 142–156, 121–129)` ≈ `#08987F` (TradingView teal family) | not specified | adopt |
| Down body | **near-black `#0A0A0A`** | not specified | adopt |
| Wicks | **present**, 1–2 px strokes above/below bodies | "无指标裸 K 图" implies candles, wicks included | adopt |
| Axes / price labels / time axis / legend / indicators | **all absent** | "无指标裸 K 图" | adopt |
| Resolution | **640 × 640** for all 295 images (SOF0 parse) | 224 × 224 (`:137`, `:279`) | **wrong** |
| Bars per image | median **87** candle bodies (range 70–92) ⇒ bar pitch ≈ **7.36 px** | 60 (`:137`, `:279`) | use **90** to match |
| Price padding | ink occupies the middle ~66 % of the frame (median top pad 14 %, bottom 20 %) | not specified | use a symmetric ≈ 10 % of the price range |
| Inference input | `imgsz = 640`, `conf = 0.25` (card usage; Space `config.yaml`) | not specified | adopt |

`[FACT]` The card states the limitation verbatim: *"Trained on white background TradingView charts
only."* (`research/huggingface/nq-fvg-detector/README.md:55`) and *"Input size: 640x640"*
(`:51`). The author's own workflow is screen-grabbing a live TradingView chart (the Space's
requirements include `pyautogui`/`mss`) — `research/analysis/VISION_AUDIT.md` §A.7.

`[INFERENCE]` **A black 224×224 render is not a style tweak, it is the complement of the training
distribution.** HSV augmentation with `hsv_v = 0.4` scales the value channel by a gain in
[0.6, 1.4]: white can be knocked to mid-grey, but **no gain turns white into black**, and the
training set contains no dark-background example. Worse, the model's *down* candle is `#0A0A0A` — on
a black background the down candles would be **invisible** (`research/analysis/VISION_AUDIT.md`
§B.1).

`[PROPOSAL]` **Render spec (`STYLE_VERSION = "v1-tv-white-640"`):**

```
frame        640 × 640 px, square, full-bleed plot area (the training images have no axis gutter)
background   #FFFFFF
grid         #FAFAFA, 1 px, horizontal + vertical
window       the last 90 bars ending at the confirmation bar
body         filled rectangle, width 0.68 × bar_pitch, teal #08987F (up) / #0A0A0A (down)
wick         1 px vertical line, #0A0A0A
axes         NONE (no spines, no ticks, no labels, no legend, no volume, no indicators)
price range  p_min = min(low), p_max = max(high) over the window; symmetric pad = 0.10 × (p_max − p_min)
y(p)         = (p_max + pad − p) / ((p_max + pad) − (p_min − pad)) · 640        # affine, decreasing
y⁻¹(row)     = (p_max + pad) − row · ((p_max + pad) − (p_min − pad)) / 640
x(k)         = (k + 0.5) · 640 / W,  k = 0 is the OLDEST bar in the window
```

`[PROPOSAL]` **Do not use `mplfinance` for this.** The training style has no axis furniture at all,
so a bare matplotlib `Axes` (rectangles + `vlines`, ticks off, spines off) is both **faster** and
**more faithful** than `mplfinance` (`research/analysis/VISION_AUDIT.md` §E.2). `mplfinance` is what
the doc names, but the doc also names the wrong colours and the wrong resolution.

### C.3 The IoU definition to use

`[PROPOSAL]` **Primary (`vision_iou`, the D2 column): the 2-D box IoU.**

```
IoU_2D(B, R') = |B ∩ R'| / |B ∪ R'|
    B   = the matched detector box, in pixels
    R'  = the third candle's body rectangle:
          x ∈ [x(i) − w_body/2, x(i) + w_body/2]
          rows ∈ [ y(max(open_i, close_i)) , y(min(open_i, close_i)) ]
```

Both rectangles are axis-aligned in the same pixel frame, so this is the standard
`inter/union` on two boolean masks — no centre/width arithmetic needed, and therefore no
rounding ambiguity.

`[PROPOSAL]` **Secondary diagnostics (side table):**

```
IoU_v_gap       = |B_rows ∩ gap_rows| / |B_rows ∪ gap_rows|      # descriptive only; ≈0 by construction
row_containment = |B_rows ∩ R'_rows| / |B_rows|                   # convention-robust
bar_index_delta = round(x_centre(B) / bar_pitch) − fvg_c3_slot    # must be 0
class_match     = (detector class == gap direction)
```

`[PROPOSAL]` **Never compute the IoU against the gap.** It is 0 for a correct detection by
construction (§B.4). If it is ever non-zero, that is a **renderer/rule-engine disagreement**, not a
signal, and it should raise.

### C.4 The threshold and how to calibrate it

`[PROPOSAL]` **Start at τ = 0.30 for the 2-D body IoU, and calibrate it — but do not inherit 0.75
and do not inherit 0.50.**

* **0.75 must be deleted** (D6). It is unreachable on two independent grounds: the *semantic*
  mismatch (§B.4, a perfect detection scores 0.00 against the gap) and the *sub-pixel* geometry
  (a 0.75 px misalignment at 640×640 already drops the combined IoU below 0.75 —
  `research/audit/AUDIT.md:327–346`).
* **0.50 is too high for the 2-D body IoU**: measured, the model's *own ground-truth* boxes reach
  0.50 only **33 %** of the time (median 0.393, §B.5). A gate at 0.50 would reject two thirds of
  correct detections.
* **0.30 admits 72 %** of the model's own ground truth — a defensible starting point.

`[PROPOSAL]` **Calibration procedure — the Kaggle *test* split, exactly as D6 says, done properly:**

1. Take the **44 test images** of `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/test/` (they are
   the *only* ground truth the model has, and they are the split the model was not fitted on).
2. Re-render each of the 44 windows with **our** renderer from the underlying NQ bars, so that
   our `x(·)`, `y(·)` and `w_body` are in play (the Kaggle images are TradingView screenshots; we
   do not have the OHLC that produced them — so this step needs the **original NQ 1m/5m bars** for
   those windows; if those are unavailable, fall back to step 3).
3. For each ground-truth label box, compute `IoU_2D(label box, our body rectangle)`. This gives
   **the achievable distribution of the metric for a *perfect* detector on our own render** — the
   ceiling, and the only honest way to set τ.
4. Set **τ = the 10th percentile of that ceiling distribution** (so ≈ 90 % of correct detections
   survive), and additionally require `bar_index_delta == 0` and `class_match`.
5. Then, and only then, measure the *detector's* actual distribution on our renders (that is
   experiment **V-1** below) and re-tune τ on the **valid** split (44 images), keeping the test
   split untouched as the final check.
6. Report the **precision/recall of the whole gate** (not just of the detector) on the test split:
   the fraction of rule-engine candidates that pass the conjunction, and the win-rate of the
   passing vs non-passing subsets on real data. This is the number the design's "filters ~35 % of
   the noise" claim (L139) must be replaced by — or it must be deleted
   (`research/docs/RULE_SPEC.md:340`, I09).

`[PROPOSAL]` **Experiment V-1 (the decisive one, ≈ 1 h, and it is a *prerequisite*, not a
nice-to-have):** run the shipped checkpoint over (a) the 44 Kaggle test images (expect ≈ 0.90
recall), (b) 50 renders of the same bars in the *doc's* black 224×224 style, (c) 50 renders in
*our* white 640×640 style. Report recall/precision and mean detections per window for each. If
(c) ≈ (a) but (b) collapses, the domain gap is confirmed and sized. If (c) also collapses, **our
renderer does not match the training style and must be fixed before anything else is measured.**
(`research/analysis/VISION_AUDIT.md` §B.4.)

`[PROPOSAL]` **Two blockers to settle before writing any of this code:**

* **Licence.** The checkpoint and the card are **AGPL-3.0**
  (`research/huggingface/nq-fvg-detector/README.md:2` front-matter and the `license` field read out
  of the checkpoint, `research/analysis/VISION_AUDIT.md` §A.6). AGPL copyleft is a *product*
  decision that blocks deployment, not a technical one — but it must be taken before the layer is
  built, not after.
* **Version pin.** The card states **no** ultralytics version; the Space's `requirements.txt`
  pins `ultralytics==8.4.64` + `torch==2.12.0`, and the checkpoint's own `version` field is
  `8.4.64` (`research/analysis/VISION_AUDIT.md` §A.4, §A.6). Pin it, and verify the checkpoint
  loads and reproduces `train_metrics` (precision 0.88849 / recall 0.90836 / mAP50 0.93158 /
  mAP50-95 0.57395) before trusting any output.
* **Coverage.** The model is **NQ1!, 1m/5m only** (`README.md:49–50`). ES, YM, QQQ, GC, BTC, ETH
  are **out of distribution**. The target state is to fine-tune `best.pt` on our own renders using
  **rule-engine auto-labels** (the rule engine already computes the FVG geometry and the third
  bar's OHLC — labels are free), which also lets us choose the resolution and window
  (`research/analysis/VISION_AUDIT.md` §B.3 option (ii)).

### C.5 The performance budget

`[FACT]` Volumes, from `research/experiments/E1_RESULTS.md` §3.0 (BTCUSDT 1m, full 3.9-year
dataset, 2,046,240 bars): the code-derived rule core produced **423,759 candidates** (the "census"
arm — one position per candidate) and **15,928 trades** in the one-position-at-a-time arm.

`[INFERENCE]` Cost per candidate, using `research/analysis/VISION_AUDIT.md` §E.2–E.3 (estimates —
matplotlib/ultralytics are not installed for the 3.11 interpreter, so **none of these are
measured**; they are flagged as estimates there and remain estimates here):

| Stage | This host (CPU, no GPU) | Discrete GPU (fp16) |
|---|---|---|
| render (bare matplotlib axes, 90 bars, 640²) | ≈ 30–80 ms | — |
| detector inference (21.8 M params, 640²) | ≈ **1–2 s** | ≈ 4–8 ms |
| **per candidate, total** | ≈ **1.1–2.1 s** | ≈ 0.1 s |

`[INFERENCE]` Volumetrics for the full candidate set (3.9 y, one symbol-timeframe):

| Population | Renders | CPU @ 1.5 s | GPU @ 8 ms |
|---|---|---|---|
| 423,759 candidates (E-1 census) | 424 k | **176 h** | 56 min |
| 15,928 one-at-a-time trades | 16 k | 6.6 h | 2 min |
| 2–7 candidates/day (the doc's killzone+filter estimate, `VISION_AUDIT` §E.1) | 1.5 k–5.3 k | 0.6–2.2 h | ~1 min |

`[INFERENCE]` **Verdict: the layer is affordable, but it must be an offline batch job — it can never
live in the event loop.** Four reasons, in order of weight:

1. **The meta-labeler needs the feature over history anyway.** The training population is "all
   phase-1 candidates, winners and losers" (`research/docs/RULE_SPEC.md:275`, A23), so the vision
   pass must run over the whole historical candidate set *before* any training — by definition a
   batch.
2. **Reproducibility.** A neural network inside the event loop makes the backtest depend on
   GPU/driver/cuDNN/thread-count nondeterminism.
3. **The live hot path.** 1–2 s of CPU inference inside a Nautilus `on_bar` handler stalls the
   event loop; even on a GPU it couples trading latency to model latency.
4. **The layer contract.** The vision layer may only *filter*, never alter the rule layer's
   decisions (`RULE_SPEC.md:404`, INV5). A precomputed join enforces that structurally.

`[PROPOSAL]` **Two cost reductions that matter at 424 k renders:**

* **Cache by window, not by candidate.** The render depends only on the *window end bar*, so
  candidates sharing a confirmation bar share one PNG. Cache key = `(symbol, timeframe,
  window_end_ts_ns, style_version)`; store the PNG under `data/cache/renders/<sha256>.png`.
  A style change re-renders; a threshold change re-runs detection only.
* **Detect once per window, evaluate many candidates per window.** The detector's output is a
  property of the *window*, not of the candidate. Run the model once per distinct window and score
  every candidate in it. This is the difference between 424 k and (number of distinct window ends)
  inferences.

### C.6 What the layer can and cannot honestly claim

`[PROPOSAL]` **Can claim:** *"given a bare-candle render of the window, the independently-trained
detector localises a candle body at the same bar the rule engine identified, with class agreement
and body-IoU above the calibrated threshold."* That is a **cross-check on the rule engine's
geometry**, and it is worth something: the detector was trained by a different person, on
different renders, from hand-drawn labels — so its agreement is not a tautology, and a
disagreement is a genuine signal that one of the two is wrong (e.g. the rule engine found a gap
that is not *visible* at this resolution — which is precisely the "震荡锯齿中的微小缺口" concern
at L135).

`[PROPOSAL]` **Cannot claim — and this is the important part:**

1. **It cannot verify "clean price action"** (L135). The detector's training signal is a *geometric
   FVG box*; it contains **no** notion of cleanliness, no context, no forward return. Its
   confidence measures *"how sure am I that there is a teal/black rectangle here"* — which is
   (a) already implied by the rule engine having just found a gap, and (b) a function of the very
   local texture the rule engine already measured. It is a **locator**, not a judge: it fires on a
   **median of 11–12 gaps per ~90-bar window** (3,650 boxes / 295 images) with recall 0.908 and
   precision 0.888 — a high-recall detector, not a precision filter.
2. **It cannot see any of the context a human uses to judge cleanliness.** The render is
   "indicator-free bare candles" by design: no HTF structure, no marked sweeps, no session levels,
   no EQH/EQL, no order blocks, no ATR. Everything a human would weigh is either absent from the
   image or must be re-inferred from 90 bars. The layer is therefore *blind* to the checklist
   conditions the design wants it to complement.
3. **It cannot verify the price gap**, because it never looks at the gap (it looks at a candle).
4. **It cannot claim the "≈35 % noise filtered"** figure (L139) — it is unverified
   (`research/docs/RULE_SPEC.md:340`, I09) and must not appear in any performance claim until it
   is measured on real candidates.

`[PROPOSAL]` **The Visual Clarity Score** (`iFVG几个模型的讨论.txt:138`; `RULE_SPEC.md:215` T23,
`:268` A16) — the doc names it and never defines it. A16 proposes "the detector's class confidence
of the box matched to the rule FVG", which is **(a) not monotone in cleanliness** (the detector
fires ~11× per window regardless) and **(b) nearly a restatement of "the gate passed" plus a
number**, which would feed the meta-labeler the same information twice under two names (the doc
already has a separate "视觉检测置信度" feature at L146). A definition that is monotone in
cleanliness, computable from detector outputs only, and not a re-parameterisation of the IoU:

```
f_match    = matched detection's confidence                        ∈ [0,1]
n_same     = number of OTHER same-class detections in the window
purity     = 1 − n_same / (W − 1)                                 ∈ [0,1]
n_adj      = number of same-class detections within ±1 bar of the matched one
isolation  = 1 − min(1, n_adj / 2)                                 ∈ [0,1]

VisualClarityScore = f_match · purity · isolation                  ∈ [0,1]
```

(a window where the model flags exactly one gap and nothing adjacent scores high; a window where
it flags 15 same-class gaps scores low). `[PROPOSAL]` Use it as a **continuous feature** for the
meta-labeler, **not** as a gate, and report its three components separately so the meta-labeler can
learn its own combination.

---

## D. What the vision layer can actually buy us

`[FACT]` The baseline, per D4 and `research/experiments/E1_RESULTS.md` §3.0 (BTCUSDT 1m, full
3.9-year dataset, **one position at a time**, which D4 fixes as the only quotable accounting):

| arm | n | win % | E[R] gross | E_net (0.05 R) | PF | t |
|---|---|---|---|---|---|---|
| core, no sweep gate | 15,928 | **32.7 %** | −0.020 | −0.070 | **0.971** | −1.76 |
| core, sweep gate on | 26,326 | **33.7 %** | +0.011 | −0.039 | **1.017** | 1.30 |

Across all 32 arms: E[R] ∈ **[−0.024, +0.014]**, PF ≤ **1.051**, every 95 % CI includes zero; with
a 0.05 R round trip **every arm is negative**.

### D.1 The arithmetic of filtering a zero-edge signal

`[INFERENCE]` **A filter cannot raise the expectancy of a zero-edge signal unless the filter
carries information the signal does not already have.** Formally, with a gate `V ∈ {0,1}` that
keeps fraction `q` of candidates:

```
E[R] | V = 1  =  2·w′ − (1 − w′) − c        (RR = 1:2, c = round-trip cost in R)
w′  =  win rate of the kept subset
removed-set win rate  r(q) = (w − w′·q) / (1 − q)
```

For the gate to help, the removed set must be *worse than the base*: `r(q) < w`. With the measured
base `w = 0.327` and the design's gate **PF > 1.25** (`AGENTS.md`, phase-1 acceptance criteria):

```
PF = 2w′/（1−w′) > 1.25   ⇒   w′ > 0.3846      (gross, before costs)
E_net > 0 with c = 0.05   ⇒   w′ > 0.350
```

`[INFERENCE]` **What the gate would have to achieve**, expressed as "the win rate of the trades it
removes":

With `w = 0.327` (measured) and `w′` the win rate of the kept subset:

| q (fraction kept) | max achievable w′ (removed set = all losers, w/q) | required win rate of the **removed** set for **PF > 1.25** (w′ = 0.3846) | required win rate of the removed set for **E_net > 0** (c = 0.05, w′ = 0.350) |
|---|---|---|---|
| 0.90 | 0.363 | **−0.191 → impossible** (0.363 < 0.385, so PF 1.25 is unreachable at q = 0.90) | **0.120** (reachable, but demands the removed decile win 12 %) |
| 0.80 | 0.409 | **0.097** | 0.235 |
| 0.70 | 0.467 | **0.193** | 0.273 |
| 0.50 | 0.654 | **0.269** | 0.304 |
| 0.327 | 1.000 | 0.299 | 0.316 |

`[INFERENCE]` Read that table carefully. **To turn a 32.7 % win rate into a PF-1.25 strategy while
keeping 80 % of the trades, the vision gate must remove a sub-population whose win rate is 9.7 %** —
i.e. it must be **~3.4× better than random at identifying losers**. Keeping only half the trades
still requires the removed half to win 26.9 % of the time (vs 32.7 % base) — a modest but *real*
predictive requirement. And note the structural limit in column 2: **a gate that keeps 90 % of the
trades cannot reach PF 1.25 at all** (0.363 is the ceiling), so any such gate must also shrink
the population materially. The *cheapest* version of the requirement is the E_net > 0 column:
keeping 90 % of trades and lifting the win rate from 32.7 % to 35.0 % requires the removed decile
to win only 12 % of the time — but that still assumes the gate knows something about outcomes
that the detector has never been shown to know (§D.2).

### D.2 Can the shipped detector supply that?

`[FACT]` The detector's measured operating characteristics are **precision 0.88849, recall 0.90836,
mAP@50 0.93158, mAP@50-95 0.57395** (checkpoint `train_metrics`; `research/analysis/VISION_AUDIT.md`
§A.4, independently re-verified in `research/audit/AUDIT.md:270–291`). Those numbers are about
*"is there an FVG here"*, **not** *"will this trade make money"*.

`[INFERENCE]` **The training signal contains zero outcome information.** The labels are hand-drawn
FVG rectangles; nothing in the dataset encodes a forward return, a hit/miss, or a risk/reward
outcome. The detector was trained to *re-derive a geometric pattern*, so:

* the vision gate is, in expectation, **uncorrelated with the trade outcome** beyond what the rule
  engine already computes;
* an **outcome-uncorrelated filter leaves the expectancy unchanged** (E[R | V=1] = E[R]) while
  **shrinking the sample**, so it strictly *reduces* statistical power: t scales as 1/√q. A
  no-information gate cannot manufacture significance; it can only dilute it;
* the doc's stated mechanism (L135: a human can see which structures are "clean") is therefore
  **not implemented by this model at all** — the model has no cleanliness label.

`[INFERENCE]` **The one plausible real mechanism** — which is *not* the doc's — is a *resolution*
mechanism: the rule engine can detect a gap that is **too small to be visible** at the render's
scale (the "震荡锯齿中的微小缺口" of L135 is real), and the detector, being a *visual* model, will
miss it. The gate's removed set would then be enriched in **sub-resolution noise gaps**. Whether
those gaps are systematically *worse* trades is **completely unmeasured** — it is the single
hypothesis worth testing, and it is testable in one day on the existing E-1 candidate log plus one
vision batch.

`[INFERENCE]` **The maximum achievable improvement, stated honestly:**

* **Theoretical ceiling** (a perfect oracle gate that removes only losers): unbounded — keep the
  32.7 % of winners, win rate → 100 %. Irrelevant, because it is not achievable with a
  geometric detector.
* **Realistic ceiling** (the gate's own measured precision/recall, if and only if gap visibility
  turns out to predict outcomes): the gate's information is bounded by what a 640×640 render of 90
  bars can reveal, which is a *lossy function of the same OHLC the rule engine already read*. Its
  incremental value over the rule engine is, a priori, small.
* **Expected value: ≈ 0 for the expectancy, negative for the t-statistic**, until the "removed set
  is worse" hypothesis is measured and shown to hold.

### D.3 The blunt conclusion

`[PROPOSAL]` **A filter on a zero-edge signal is still a zero-edge signal, unless the filter's
own precision against the *outcome* exceeds the base rate by the margin tabulated in §D.1. The
shipped detector's precision (0.888) is measured against *"is there an FVG"*, not against *"will
this make money"*, and its training signal contains no outcome information at all. So the vision
layer cannot be expected to create an edge; at best it removes sub-resolution noise gaps, and even
that must be measured before it is claimed.**

`[PROPOSAL]` **What the vision layer *is* worth, and what it is not worth:**

| | Verdict |
|---|---|
| As a **hard gate** that must beat PF 1.25 | **Do not build it as a gate.** It has no measured outcome information, it is the most expensive per-candidate component in the stack (1–2 s/candidate on CPU), and it would *reduce* the t-statistic of an already-null strategy. |
| As a **feature** for the meta-labeler (D2's `vision_iou` / `vision_confidence` columns; `RULE_SPEC.md:275`, A23) | **This is the only defensible use.** The meta-labeler can then learn the interaction itself, and the value (if any) is measured against the D4 baseline on the same data, same costs, same one-position-at-a-time accounting. |
| As a **sanity check** on the renderer/rule-engine pipeline (a "the gap I found is actually visible at 640×640" assertion) | **Cheap and genuinely useful**, and it is the honest framing of "cross-validation". |
| As a **source of "clean price action"** | **Impossible with this model.** The training signal has no cleanliness label; the render is indicator-free by design. |

`[PROPOSAL]` **Sequencing recommendation (cost-ranked):**

1. **Do not build the vision layer before the doc's own untested rules are measured.** The E-1
   falsification tested the *code-derived* core only. The doc's **checklist, SMT divergence, HTF
   context, ATR floor and killzone** components exist in **no artefact** and have **never been
   tested**; the vision layer cannot compensate for a rule set that has not been measured at all.
   (Note also that the doc's two killzones cover 240 of the 1,440 minutes in a 24 h session —
   `research/analysis/VISION_AUDIT.md` §E.1 — so the *real* candidate population for a vision
   batch is far below 424 k.)
2. **If the vision layer is built at all, build it as a batch feature extractor** (§C.5), starting
   with the **V-1 experiment** (§C.4) — one hour, and it decides whether the shipped weights are
   usable at all on our renders.
3. **Measure the one hypothesis that could make it worth something**: among the E-1 candidates,
   compare the win rate of the vision-passing subset vs the vision-failing subset, one position at
   a time, same costs. If the failing subset is **not** materially worse than the base, the layer
   has no value as a filter and the compute should go to the rolling ML / the untested doc rules.
4. **Only then** consider making it a hard gate, and only with a threshold calibrated by §C.4 —
   never with the inherited 0.75.

---

## E. Verdict

```
Q1 IMPLEMENTED:  no
Q2 ALIGNED:      no
RECOMMENDED:     Do not build the vision layer yet, and do not build it as the doc specifies it.
                  The layer does not exist — there is no renderer, no detector wrapper, no IoU,
                  no Visual Clarity Score and no gate anywhere in the repository (the only Python
                  file we own is research/experiments/e1_rule_falsification.py, which is
                  vision-free), so Q1 is a plain "no", not a partial. Q2 is "no" for a reason
                  that no amount of implementation fixes: the rule engine measures the FVG price
                  gap while the detector measures a tight sub-box of the third candle's body, and
                  those two objects are disjoint by construction — under the discussion's own
                  metric (L279) a perfect detection scores IoU = 0.00, and under the other
                  reading (L274) it is still 0.00, so the 0.75 gate rejects 100 % of correct
                  detections rather than 35 % of noise. When it is built, it must be re-pointed at
                  the third candle's body (D6), rendered in the model's own training style
                  (white #FFFFFF, #FAFAFA grid, teal #08987F up / #0A0A0A down candles with
                  wicks, no axes, 640×640, ~90 bars — measured on the Kaggle tree, and the
                  doc's black 224×224 render is the complement of the training distribution), and
                  its threshold must be calibrated on the Kaggle test split rather than
                  inherited: the model's own ground-truth boxes score a median 2-D body IoU of
                  only 0.39, so 0.75 would reject 98 % of them and even D6's 0.50 would reject
                  two thirds — start at 0.30 with an exact bar-index and class gate. Finally,
                  build it as an offline batch feature extractor feeding the frozen D2 columns
                  (vision_iou, vision_confidence), never inside the event loop and never as a hard
                  gate: D4 shows the rule layer's expectancy is ~0, a filter on a zero-edge
                  signal is still a zero-edge signal, the detector's training signal contains no
                  outcome information whatsoever, and the only hypothesis that could give the
                  layer value — that the rule engine's sub-resolution noise gaps are the ones the
                  detector cannot see — is unmeasured and must be tested against the D4 baseline
                  before any of this compute is spent.
```

---

## Appendix — how the measurements in this document were produced

All commands run read-only from the repo root. **No detector was run and `best.pt` was never
loaded**; the checkpoint was not opened at all in this leaf (its metadata is cited from
`research/analysis/VISION_AUDIT.md` §A.1–A.6, independently re-verified in `research/audit/AUDIT.md`
§A.3.1).

```bash
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
KD=research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset

# [FACT] image inventory: 295 images, all 640x640
identify -format '%wx%h\n' $KD/*/images/*.jpg | sort | uniq -c

# [FACT] label geometry: 3,650 boxes, median 5.50 x 16.50 px @640
#   -> read every $KD/*/labels/*.txt, class cx cy w h (normalised), x640

# [FACT] background / palette / padding: decode with `magick <file> -depth 8 rgb:-`
#   -> numpy (H,W,3); count exact (255,255,255); teal = g>90 & r<110 & b>70 & g-r>40;
#      down-candle = max(rgb)<110; ink rows = rows with any candle pixel

# [FACT] candle bodies per image (median 87) and body width/height:
#   -> body mask = rows where >=3 consecutive columns are candle-coloured;
#      count contiguous runs over the column projection

# [FACT] annotation convention (99.1 % centre-column coverage, 327 boxes):
#   -> for each label box, test whether the box's centre column is >=80 % candle-coloured
#      inside the box's row range; distance to the nearest candle-bearing column

# [FACT] oracle IoU of the ground truth against the true body rectangle (524 boxes, 75 images):
#   -> per-row contiguous ink run containing the box centre; body rows = rows whose run width
#      >= 3 px; body rect = (min..max body rows) x (min..max run columns);
#      IoU_2D(label box, body rect)

# [FACT] visual confirmation: crop +-36 px around a label box, draw the label rectangle in red
magick $KD/test/images/1min-NQ-103_*.jpg -crop 72x72+X+Y \
        -fill none -stroke red -strokewidth 1 -draw 'rectangle ...' -scale 760x760 /tmp/zoom.png
```

**Artefacts read (not modified):** `.herd-swarm/decisions.md` (D1–D11);
`research/analysis/VISION_AUDIT.md`; `research/docs/RULE_SPEC.md` (§1.2, §1.3, T19–T23, A09, A10,
A16, A20, A23, A24, A32, I06, I09, INV5, S21–S23); `research/audit/AUDIT.md` (§A.3.1–A.3.5);
`research/analysis/PINE_RULES.md` (§R1, §R2, §R3); `research/experiments/E1_RESULTS.md` (§3.0–§3.3);
`research/experiments/e1_rule_falsification.py` (whole file, 431 lines);
`iFVG几个模型的讨论.txt` (L133–139, L141–146, L201, L272–282);
`research/huggingface/nq-fvg-detector/README.md` (L1–59);
`research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/` (data.yaml, 295 images, 3,650 labels).

**Written by this leaf:** `research/audit/L1_VISION.md` only.
