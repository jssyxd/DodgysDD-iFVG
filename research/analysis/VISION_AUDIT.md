# VISION_AUDIT — the vision cross-validation layer vs. the real detector

**Scope** — audit of the four-layer design's *vision cross-validation* layer (module 1 in
`iFVG几个模型的讨论.txt`, layer 2 in `diagram-四层正 EV 量化系统完整架构.svg`) against the actual
artefacts of `ibtsam/nq-fvg-detector` and its training dataset.

**Verdict in one line** — the layer as specified **cannot work**: it has **two independent fatal
defects** (a colour/resolution domain mismatch that the design doc already suspects, and a
**geometric mismatch** that makes the `IoU > 0.75` gate mathematically unreachable), and it must be
**re-specified as a localisation cross-check on the gap-opening candle**, not as a gap-region IoU.

**Evidence labels used throughout**

| Tag | Meaning |
|---|---|
| `[FACT]` | Read directly from a named artefact in this repo or from the upstream Hugging Face / Kaggle pages (URL given). |
| `[INFERENCE]` | Reasoned from one or more `[FACT]`s; the reasoning is stated. |
| `[PROPOSAL]` | A design decision made by this audit; not derivable from the artefacts. |

**Constraints honoured** — no `pip install`, no `torch`/`ultralytics` load, no inference executed. The
checkpoint was inspected **statically** (see §A.0).

---

## 0. Artefacts read

| Path / URL | What it gave |
|---|---|
| `research/huggingface/nq-fvg-detector/README.md` | model card: architecture name, classes, input size, metrics, the "white background" limitation |
| `research/huggingface/nq-fvg-detector/best.pt` | 44,028,313 B torch zip; `best/data.pkl` → full training metadata, architecture YAML, state-dict shapes |
| `research/huggingface/nq-fvg-detector/.cache/huggingface/trees/45d52629e6260f40b4161292307b721ff5dc5586.json` | authoritative file list of the model repo (3 files) |
| `research/huggingface/nq-fvg-detector/.cache/huggingface/download/best.pt.metadata` | LFS sha256 `8691c95f…09af19` |
| `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/data.yaml` | class names, split dirs |
| `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/{train,valid,test}/{images,labels}/` | 295 chart JPEGs + 3,650 YOLO labels — the *only* ground truth for the model's behaviour |
| `research/docs/RULE_SPEC.md` | sibling spec: T19/T21/T22/T23, A16, A20, A32, I06, I07, I09 |
| `iFVG几个模型的讨论.txt` L137–L139, L274, L279 | the normative spec under audit |
| `https://huggingface.co/spaces/ibtsam/nq-fvg-detector/resolve/main/{app.py,requirements.txt,config.yaml}` | the author's own inference code + **pinned ultralytics version** (fetched 2026-11-22, read-only) |
| `https://www.kaggle.com/api/v1/datasets/view/ibtsamsadiq/nq-fvg-dataset` | dataset card (fetched 2026-11-22) |
| `https://pypi.org/pypi/ultralytics/json` | published ultralytics versions (fetched 2026-11-22) |

---

## A. Model forensics

### A.0 Method (how the checkpoint was read without torch)

`best.pt` is a torch ZIP archive. `pickle.Unpickler` was subclassed so that `find_class()` returns a
**stub class** for every `torch.*` / `ultralytics.*` symbol and `persistent_load()` returns a
placeholder carrying the storage dtype and element count. The pickle therefore deserialises into
plain Python containers; the module tree, the embedded `model.yaml`, the `train_args` dict, the
`train_metrics` dict and every tensor **shape** (recovered from the `_rebuild_parameter` →
`_rebuild_tensor_v2` size argument) are readable, while no torch tensor is ever materialised.

### A.1 Artefact inventory

`[FACT]` The model repo contains **exactly three files** (HF API `siblings` and the cached trees
JSON agree): `.gitattributes` (1,519 B), `README.md` (1,307 B), `best.pt` (44,028,313 B,
sha256 `8691c95f6c47ece382637691b42f0c007f39b03d15dee8fde5ce16fa2109af19`).
**There is no `config.yaml`, no `requirements.txt`, no sample image and no evaluation script in the
model repo.** `[INFERENCE]` Loading therefore works without a side-car config: ultralytics'
`attempt_load_one_weight` rebuilds the network from the pickled `DetectionModel` (which carries its
own `yaml`, `names` and `stride`). The absence of a `requirements.txt` is what creates the version
risk in §A.6.

### A.2 Checkpoint format

`[FACT]`

* `file best.pt` → `Zip archive data`. Contents: `best/data.pkl` (203,530 B) + `best/data/0…N`
  storage blobs + `best/.format_version`, `best/.storage_alignment`, `best/byteorder`.
* Standard **ultralytics trainer checkpoint**. Top-level keys:
  `date, version, license, docs, epoch, best_fitness, model, ema, updates, optimizer, scaler,
  train_args, train_metrics, train_results, git`.
* `epoch = -1`, `best_fitness = None`, `optimizer = None`, `scaler = None`, `ema = None`,
  `updates = None` → this is the **stripped final model** (post `strip_optimizer`), not a
  resumable checkpoint.
* **Weights are fp16.** Every parameter and every floating buffer unpickles as `HalfStorage`.
  `[INFERENCE]` This is `save_model()`'s `deepcopy(model).half()`; ultralytics re-casts to fp32 on
  load, so this is harmless, but it means the file carries ~44 MB for a 21.8 M-parameter model
  (21.8 M × 2 B = 43.6 MB of weights + buffers).

### A.3 Architecture, version and parameter count

`[FACT]` The embedded `model.yaml` (read out of the pickle):

```
yaml_file: yolo26m.yaml     scale: m      nc: 2      channels: 3
end2end: True              reg_max: 1
scales: {n:[0.5,0.25,1024], s:[0.5,0.5,1024], m:[0.5,1.0,512], l:[1.0,1.0,512], x:[1.0,1.5,512]}
backbone: Conv×5 · C3k2×6 · SPPF · C2PSA
head:     Upsample/Concat/C3k2×4 · Conv · Detect
```

* Class paths present in the pickle: `ultralytics.nn.modules.block.C2PSA`,
  `…block.C3k2`, `…block.SPPF`, `…conv.Concat`, `…conv.Conv`, `…head.Detect`.
* `Detect` head attributes: `nl = 3`, `no = 6`, `stride` shape `(3,)`, `anchors` shape `(2, 9261)`,
  `max_det = 300`, `reg_max = 1`, and the state dict contains `model.23.one2one_cv2.*` and
  `model.23.one2one_cv3.*`.
* **Total parameters: 21,776,096 (21.78 M)** across 520 parameter tensors — computed by summing
  the recovered tensor shapes.

`[INFERENCE]` `end2end: True` + `reg_max: 1` + the `one2one_*` branch is the signature of
**YOLOv26's NMS-free end-to-end head** (no DFL, one-to-one prediction branch). This is consistent
with the card's "Ultralytics YOLOv26m" tag and with `train_args['model'] = 'yolo26m.pt'`.

### A.4 Training run metadata (all from `train_args` / `train_metrics`)

`[FACT]`

| Field | Value |
|---|---|
| `model` | `yolo26m.pt` |
| `data` | `E:\ml projects\trading-cv-fvg\data\dataset\My-First-Project.v4i.yolov11\data.yaml` (Roboflow "v4i" export) |
| `epochs` / `patience` | 100 / 20 — **stopped at epoch 80** (`train_results['epoch']` ends at 80) |
| `imgsz` | **640** |
| `batch`, `rect` | 16, **False** (square training, letterbox) |
| `device`, `workers`, `cache` | **`cpu`**, 0, False |
| `amp`, `seed`, `deterministic` | True, 0, True |
| `mosaic` / `mixup` / `cutmix` | **1.0** / 0.0 / 0.0 |
| `hsv_h` / `hsv_s` / `hsv_v` | 0.015 / 0.7 / **0.4** |
| `degrees` / `translate` / `scale` / `shear` / `perspective` | 0.0 / 0.1 / **0.5** / 0.0 / 0.0 |
| `flipud` / `fliplr` | 0.0 / **0.5** |
| `close_mosaic` | 10 |
| `iou` (NMS) / `max_det` / `conf` | 0.7 / 300 / None |
| `project` / `name` | `E:\ml projects\trading-cv-fvg\models` / `fvg_detector-4` |
| `git` | origin `https://github.com/ibi111/market-structure-cv.git`, commit `e891843b495a6f020997892b34a5d0de599a880f`, message **"First commit"** |
| `date` / `version` / `license` | `2026-06-16T21:25:09` / **`8.4.64`** / AGPL-3.0 |
| wall-clock | `train_results['time'][-1] = 29,311.5 s` ≈ **8.1 h, on CPU** |

`[FACT]` **Measured metrics** (`train_metrics`): precision **0.88849**, recall **0.90836**,
mAP@50 **0.93158**, mAP@50-95 **0.57395**, fitness 0.57395.

`[FACT]` **The model card's numbers disagree with the checkpoint's**:

| Metric | Card | Checkpoint |
|---|---|---|
| mAP@50 | 92.3 % | **93.16 %** |
| mAP@50-95 | 58.2 % | **57.40 %** |
| Precision | 83.9 % | **88.85 %** |
| Recall | 89.4 % | **90.84 %** |
| F1 | 86.6 % | **89.61 %** |

`[INFERENCE]` The card was likely written from an earlier run or a differently-weighted evaluation.
**Use the checkpoint's numbers**; they are the ones attached to the shipped weights.

`[FACT]` The card's `mAP@50-95 = 58.2 %` with `mAP@50 = 92.3 %` is a **very wide spread**: the model
is good at detecting *that* a gap is present but poor at *localising its extent* (average IoU
0.574 at the 0.5–0.95 sweep). This matters directly for §C.

### A.5 Classes, resolution, confidence

`[FACT]`

* `names = {0: 'bearish_fvg', 1: 'bullish_fvg'}` — **note the index order: bearish is class 0.**
* Card: "**Input size:** 640x640"; "**Instrument:** NQ1! Futures"; "**Timeframes:** 1m, 5m";
  "**Framework:** Ultralytics YOLOv26m".
* Card usage: `results = model("chart.png", conf=0.25)`.
* Space `config.yaml`: `conf_threshold: 0.25`; the Gradio slider runs 0.1–0.9, step 0.05.

`[INFERENCE]` `conf = 0.25` is the operating point to reproduce. Note the trained checkpoint's own
`conf` is `None` (i.e. 0.001) and its NMS `iou` is 0.7 — but for an **end2end** model the NMS
threshold is largely inert; `conf` is the knob that matters.

### A.6 Can current `ultralytics` load these weights?

`[FACT]` The **model card states no version requirement at all** — a genuine documentation gap.
The *Space*'s `requirements.txt` does pin it:

```
ultralytics==8.4.64
torch==2.12.0
torchvision==0.27.0
python_version: '3.13'      # (Space README front-matter)
```

`[FACT]` PyPI (fetched 2026-11-22): latest published `ultralytics` is **8.4.216**; **8.4.64 exists**.

`[INFERENCE]` Because the pickled `Detect` carries the YOLOv26 end-to-end head
(`one2one_cv2` / `one2one_cv3`, `end2end: True`, `reg_max: 1`), the checkpoint can only be
reconstructed by an ultralytics whose `Detect` implements that head — i.e. the 8.4.x line.
An 8.3.x install (the last pre-YOLOv26 series) will raise on missing/unexpected `one2one_*`
state-dict keys. **Pin `ultralytics==8.4.64`** (identical to the checkpoint's own `version` field)
for the first run, then move to a current 8.4.x and re-validate the metrics.

`[FACT]` Licence: **AGPL-3.0** (checkpoint `license` field, model card front-matter, and the
`license` tag). `[INFERENCE]` AGPL-3.0 is a copyleft licence — a *service* built on these weights
must offer source. Combined with the AGPL-3.0 dataset-adjacent tooling this is a
product/licensing decision, not a technical one, but it must be taken before the layer is built.

### A.7 The training chart style — measured, not assumed

`[FACT]` All **295** dataset images are **exactly 640×640** JPEG (SOF0 header parse over every
file). All 295 training/val/test images are the same size — the model has seen no other resolution.

`[FACT]` Pixel measurements (`magick` colour histogram + point sampling on
`train/images/1min-NQ-100_png.rf.affc899fb7cf38521471ca79f28a20b4.jpg`):

| Element | Measured value |
|---|---|
| Background | **`srgb(255,255,255)` — pure white** (corners at (5,5), (320,20) all 255/255/255) |
| Gridlines | `#FAFAFA` and `#F6F6F6` — very light grey, both horizontal and vertical |
| Up candle body | `#159379` / `#42A391` / `#498A7C` (TradingView teal family, `#26A69A`) |
| Down candle body | `#0A0A0A` — near-black |
| Wicks | **Present** — 1–2 px vertical strokes above and below the bodies |
| Price axis / tick labels | **Absent** |
| Time axis / session markers | **Absent** |
| Legend, watermark, indicators | **Absent** |
| Aspect | Square 640×640; the price series occupies ≈ **382 px** of the 640 px vertical span (median) with white padding above and below |
| Bars per image | ≈ **90** candles (median 90, min 83, max 94 over 40 sampled training images) |

`[FACT]` The card says, verbatim:

> **Limitations**
> Trained on white background TradingView charts only. Not financial advice.

`[FACT]` The author's own Space UI says *"Upload a TradingView screenshot and detect Bullish /
Bearish FVGs."*, and the Space's `requirements.txt` includes `pyautogui`, `mss` and `keyboard` —
i.e. the author's workflow is **screen-grabbing a live TradingView chart** (white theme) and
feeding it to the detector.

`[INFERENCE]` The training distribution is therefore: *square 640×640, pure-white background, faint
light-grey grid, teal/black candles with wicks, no axes, no indicators, ~90 bars.* It is a clean
"bare candle" chart — the same *content* the doc asks for ("无指标裸 K 图"), but the **opposite
colour scheme** and at **1/2.86 the linear resolution**.

### A.8 Dataset composition and annotation convention

`[FACT]` `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/data.yaml`:

```yaml
train: ../train/images
val:   ../valid/images
test:  ../test/images
nc: 2
names: ['bearish_fvg', 'bullish_fvg']
```

`[FACT]` Composition:

| Split | images | labels | 1min-NQ | 5min-NQ |
|---|---|---|---|---|
| train | 207 | 207 | 110 | 97 |
| valid | 44 | 44 | 23 | 21 |
| test | 44 | 44 | 22 | 22 |
| **total** | **295** | **295** | **155** | **140** |

* **3,650 boxes** total — 2,000 `bullish_fvg` (class 1) and 1,650 `bearish_fvg` (class 0).
  Boxes per image: median 11, range 0–24.
  *Discrepancy:* the Kaggle dataset card advertises "**~2,400+** annotated FVG instances"; the
  measured value is **3,650**. Use 3,650.
* Symbol: **NQ1! (Micro E-mini Nasdaq-100) only.** Timeframes: **1m and 5m only.**
* Annotation tool: **Roboflow**; export format: YOLOv11 (`class cx cy w h`, normalised).
* Box geometry: width median **0.00859** normalised = **5.5 px** @640 (p10 0.0078, p90 0.0109);
  height median **0.02578** = **16.5 px** @640 (min 1.5 px, max 252 px).

`[FACT]` **The annotation convention — measured over all 3,650 boxes:**

1. **The boxes are NOT rectangles drawn over empty gap space.** Computing, for every box, the
   fraction of its interior pixels that are candle-coloured: **98.7 % of boxes have >50 % candle
   interior** (median interior coverage 80–83 %); only **0.1 %** are >80 % empty.
2. **The boxes hug a single candle's body.** For every box, the box's vertical extent is measured
   against the body of the candle it sits on: **90.8 % of boxes lie entirely inside that candle's
   body** (median "fraction of box inside body" = **1.000**); only 13.6 % are within 8 px of the
   body's own extent (i.e. the box is systematically *tighter* than the body).
3. **Visual confirmation** (6× nearest-neighbour zoom of `1min-NQ-100`): the blue (`bullish_fvg`)
   rectangle wraps exactly one teal candle's body, wicks excluded; the red (`bearish_fvg`) rectangle
   wraps exactly one black candle's body.
4. **The annotated candle is the third (gap-opening) bar of the FVG pattern.** Testing pixel
   geometry against the ICT definition directly — bullish: c3's low above c1's high; bearish: c3's
   high below c1's low — gives **48.9 % (bullish)** and **50.0 % (bearish)** confirmation. The
   *symmetry across the two classes* is the signature of a **consistent convention** (the residual
   50 % is measurement noise in the neighbour-candle assignment, not a second convention).
   Measured FVG gap height @640: median **28 px** (p25 12, p75 55).

`[INFERENCE]` **The dataset marks ONE candle per FVG — the third bar — with a ~1-bar-wide box.** It
does **not** draw the geometric gap rectangle (the space between candle 1's wick and candle 3's
wick). The Kaggle prose ("A gap exists between the wick of candle 1 and the wick of candle 3")
describes what an FVG *is*; the annotation is a **per-candle marker**.

### A.9 The consequence, measured on the model's own ground truth

`[FACT]` Taking the training images as ground truth — the rule engine's FVG price gap reconstructed
in pixels, the detector's own annotation box taken as "the detector's output", and the doc's
metric applied:

```
IoU( detector BOX , FVG gap interval )      n = 2,443
  median = 0.0000    mean = 0.0407    max = 0.9462
  fraction with IoU > 0.10 :   9.82 %
  fraction with IoU > 0.25 :   6.71 %
  fraction with IoU > 0.50 :   3.27 %
  fraction with IoU > 0.75 :   0.65 %      <-- the doc's gate
vertical overlap of the box with the gap, as a fraction of the box height:
  median = 0.0000;  fraction with EXACTLY ZERO overlap = 87.9 %
```

`[INFERENCE]` **Even if the detector is perfect, the doc's gate rejects ~99.4 % of true positives.**

---

## B. The white/black contradiction — and a second, deeper one

### B.1 What the model actually expects

`[FACT]` White. Pure `#FFFFFF` background (§A.7), verified on the actual training images; the card
states it explicitly; the author's own workflow screen-grabs TradingView.

`[INFERENCE]` **The HSV augmentation does not rescue a black render.** `hsv_v = 0.4` scales the
value channel by a gain in `[0.6, 1.4]`: a white background can be knocked down to mid-grey, but
**value gain can never turn white into black**, and a black background stays black under any gain.
The training set contains **no example of a dark background** — so a black render is not a "slight
style mismatch", it is the **complement** of the training distribution.

`[INFERENCE]` A second, easily-missed trap: the model's down-candle colour is `#0A0A0A`
(near-black). If we render a black background with the model's candle palette, **the down candles
become invisible**. Any "black background" render must also invert the candle palette, which moves
it *twice* away from the training distribution (background polarity **and** candle polarity).

### B.2 The resolution mismatch, quantified

`[FACT]` Model input 640×640; doc requires 224×224 (`iFVG几个模型的讨论.txt` L137, L279;
`RULE_SPEC.md` T21/T22). Training charts show ≈90 bars in 640 px.

`[INFERENCE]` Assume the doc's render keeps the training charts' **aspect** (same padding fraction,
60 bars covering ≈ ⅔ of the 90-bar price range). Then the 224×224 / 60-bar chart is a **uniform
0.525× downscale** of the training geometry (horizontally: (224/60) ÷ (640/90) = 0.525; vertically:
(224 × 382/640) ÷ (⅔ × 382) = 0.526). Every pixel measurement therefore scales by 0.525:

| Quantity | @640 (training) | @224 / 60 bars (doc) |
|---|---|---|
| bar pitch | 7.1 px | **3.7 px** |
| detector box width | 6 px | **3.1 px** |
| detector box height | 17 px | **8.9 px** |
| FVG gap height (median) | 28 px | **14.7 px** |
| candle body width | ≈6 px | ≈3.1 px |

`[INFERENCE]` **Is 0.75 IoU achievable at 224×224? No — and not for a geometric reason, but for a
detector-resolution reason.** The detector's finest feature level is stride 8 (the `Detect` head has
`nl = 3`, strides 8/16/32; `anchors` 9,261 = 3 scales × 80×80 + 40×40 + 20×20 at 640). At 224 the P3
grid is 28×28 and the target is 3.1 px wide = **0.39 of one stride-8 cell**. Even at the training
resolution the target is only 0.75 of a stride-8 cell — the model already works near its detection
floor at 640 (`mAP@50-95 = 57.4 %` says exactly this: it finds gaps but localises them poorly).
Shrinking the input by 0.35× in each axis pushes the objects **below** that floor.

`[INFERENCE]` Note the likely origin of the 224 figure: 224×224 is the classic CNN input size
(AlexNet/ImageNet). Ultralytics YOLO is a fully-convolutional detector and accepts any multiple of
32; the shipped checkpoint is 640. **The 224 requirement is a cargo-cult number and should be
dropped.**

### B.3 Which option is right

| Option | Verdict | Reasoning |
|---|---|---|
| **(i) Render white, TradingView-style, at 640×640** | **ADOPT as the interim** | The only option that uses the shipped weights as intended. Cost: re-implement the render to match the training style (white bg, #FAFAFA grid, teal/#0A0A0A candles, wicks, no axes, square, ~90 bars) and pin `ultralytics==8.4.64`. Gets the layer working in **days**, not weeks. |
| **(ii) Retrain / fine-tune on our own renders** | **ADOPT as the target state** | The only option that gives a domain-matched model for NQ **and** ES/YM/QQQ/GC/BTC, for 1m **and** 5m, at a resolution we choose. Cost: we already need a labelled FVG dataset for meta-labeling, and the rule engine can **auto-label FVGs on real bars** (FVG detection is deterministic and cheap) → labels are free. Realistic cost: 1–2 days to build the renderer + auto-labeller, 1–2 days to render and label 10–20 k windows, then a few GPU-hours to fine-tune from `best.pt`. |
| **(iii) Neutral style + normalisation** | **REJECT** | A "neutral" style is by definition *not* the training distribution, and normalising (grayscale, edge maps, histogram equalisation) destroys exactly the texture/colour cues the CNN was trained on. It is strictly worse than (i) and cheaper than (ii) but buys nothing. |

`[PROPOSAL]` **Recommended path: (i) now, (ii) later, (iii) never.**

1. **Phase-1a (do first, ~2 days).** Replace the render with a *style-faithful* one:
   640×640, `#FFFFFF` background, `#FAFAFA` grid, teal up / `#0A0A0A` down candles with wicks, no
   axes/labels/legend, ~90-bar window (match the training window, not the doc's 60 — see §B.5),
   and `imgsz=640`, `conf=0.25`. Pin `ultralytics==8.4.64`.
2. **Phase-1b (parallel, ~1 week).** Build the auto-labeller (the rule engine already computes FVG
   geometry and the third bar's OHLC) and fine-tune `best.pt` on **our** renders — which lets us
   choose the resolution (recommend 640×640), the bar window, and the colour scheme, and adds
   ES/YM/5m coverage. This is the model we actually want in production.
3. **Never silently mix.** Whatever we ship, the render style, resolution and window must be
   recorded next to every cached feature (`render_style_version`, `imgsz`, `window_bars`) so a
   later style change cannot be mistaken for a model change.

### B.4 Cost and expected accuracy impact

`[FACT]` What *can* be said from the artefacts: the model's own measured recall on white 640×640
TradingView charts is **0.908** and precision **0.888** (`train_metrics`).

`[INFERENCE]` The accuracy drop from a black 224×224 render is **not measurable here** (no torch, no
ultralytics, and the task forbids inference). It should be measured, and it is cheap to measure:

> **Experiment V-1 (decisive, ~1 hour).** Run the shipped checkpoint over (a) the 44-image Kaggle
> *test* split (white, 640×640 — expect ≈0.90 recall), and (b) 50 black 224×224 renders of the same
> bars, and (c) 50 white 640×640 renders of the same bars. Report recall/precision and the *mean
> number of detections per window*. If (c) ≈ (a) but (b) collapses, the domain gap is confirmed and
> its size is known. If (c) also collapses, our renderer does not match the training style and must
> be fixed before anything else is measured.

`[INFERENCE]` Expected ordering of damage: (1) background polarity — large, because it changes the
global image statistics the first conv layer keys on; (2) 224 vs 640 — large, because it pushes the
target below the stride-8 floor; (3) 60-bar vs 90-bar window — small, but it changes the bar
pitch and therefore the *aspect* of the learned "one bar" prior (the detector's box width is
~0.85 bar, so the box-to-pitch ratio survives a window change; only the absolute pixel size
changes).

### B.5 A note on the 60-bar window

`[FACT]` Doc: "最近 60 根 K 线" (L137, L279). Training images: ≈**90** bars.

`[INFERENCE]` A 60-bar window is *not* wrong per se (a detector can be applied to any window), but
it is another unjustified departure from the training configuration, and it interacts badly with
resolution: 60 bars in 224 px gives 3.7 px/bar, whereas the model learned ~7.1 px/bar. **Recommend
matching the training window (90 bars) at 640×640** until we have fine-tuned our own model. If the
doc's 60-bar window is kept, the render must still be 640×640 (60 bars → 10.7 px/bar) — the
resolution is what the model cares about, not the bar count.

---

## C. The IoU contract

This is where the layer actually dies. The doc says two different things:

* L274: "计算其与规则引擎所识别 FVG 价格区间在**像素坐标系**下的 IoU（交并比）" — pixel-space IoU.
* L279: "计算其与规则引擎在**垂直价格轴**上的 IoU" — vertical-price-axis IoU.

`RULE_SPEC.md` I06 already flags this ambiguity; A32 resolves it as "2-D pixel-space IoU". **Both
resolutions fail**, for different reasons, and the reason is *semantic*, not incidental.

### C.0 The render's price → pixel transform (must be specified, not implied)

`[PROPOSAL]` The renderer must expose an explicit, testable transform. Recommended contract:

```
Frame        : 640 × 640 px, square, no axes, no labels, no legend  (matches training style)
Plot area    : the full 640 × 640 (the training images have no axis gutter)
Window       : the last W bars of the traded instrument, W = 90 by default  (§B.5)
Price range  : p_min = min(low_i), p_max = max(high_i) over the window
Padding      : pad = 0.05 · (p_max − p_min), symmetric
y(p)         = (p_max + pad − p) / ((p_max + pad) − (p_min − pad)) · 640      # affine, decreasing
y⁻¹(row)     = (p_max + pad) − row · ((p_max + pad) − (p_min − pad)) / 640
x(k)         = (k + 0.5) · 640 / W            # k = 0 is the OLDEST bar in the window
candle body width w_body = 0.6 · (640/W)      # the training boxes are ~0.85 bar wide
```

Every downstream quantity must be computed through `y(·)` and `x(·)` — never by re-deriving the
axis from the PNG.

### C.1 Mapping the rule engine's zone to pixels

`[FACT]` `RULE_SPEC.md` §1.2: bullish `gap_low = c[i-2].high`, `gap_high = c[i].low`;
bearish `gap_low = c[i].high`, `gap_high = c[i-2].low`; `gap_size = gap_high − gap_low`.

`[PROPOSAL]` In pixels, the rule zone is the **row interval**

```
rows = [ y(gap_high), y(gap_low) ]            # r0 ≤ r1, because y is decreasing
```

It has **no horizontal extent** — a price interval is not attached to a bar. This is the crux: the
detector's box is a 2-D rectangle with a horizontal extent (≈1 bar), and the rule zone is a 1-D
interval. Any 2-D IoU requires *inventing* a horizontal extent for the rule zone, and any 1-D IoU
requires the detector's box to be the same *kind* of object as the rule zone. It is not.

### C.2 Candidate definitions, and what a PERFECT match scores under each

#### (D1) 1-D vertical interval IoU — the doc's literal reading (L279)

```
IoU_v = |[y1,y2] ∩ [r0,r1]| / |[y1,y2] ∪ [r0,r1]|
```

*If* the detector drew the gap region, a perfect match = **1.0** → the 0.75 gate is reachable.

**But the detector does not draw the gap region.** `[FACT]` §A.8/§A.9: the annotation is a box
around the **third candle's body**. Now the arithmetic:

* bullish FVG: `gap = [high_{i-2}, low_i]`; c3's body satisfies `body_low ≥ low_i = gap_high`
  (c3's *low* is the gap's upper bound, and the body sits at or above it) ⇒
  **body ∩ gap = ∅**.
* bearish FVG: `gap = [high_i, low_{i-2}]`; c3's body satisfies `body_high ≤ high_i = gap_low`
  ⇒ **body ∩ gap = ∅**.

**⇒ A perfect detection scores IoU_v = 0.00, not 1.00.** The measured value on the model's own
ground truth is median **0.0000** with **87.9 % exactly zero** and only **0.65 % above 0.75**.

> **The doc's literal metric is unreachable by construction. Any threshold on it is noise.**

#### (D2) 2-D box IoU with the rule zone expanded to the FVG's 3-bar x-range

The natural way to make "pixel-space IoU" (L274) well-posed: give the rule zone a rectangle,
`R = x ∈ [x(i-2), x(i)] × rows ∈ [r0, r1]`, and compare to the detector box `B`.

* Width of `R` ≈ 3 bars = 3 · (640/W) px. With W = 90 → 21.3 px; with W = 60 → 32 px.
* Width of `B` ≈ 1 bar = 640/W px (measured 6 px at 640/90 bars, 5.5 px median over the dataset).
* **Even with a perfect vertical match**, `IoU_2D ≤ width(B)/width(R) = 1/3` — and that bound is
  **resolution-independent and window-independent**: it follows only from "the detector's box is
  one bar wide" and "the rule rectangle is three bars wide".

**⇒ A perfect match scores ≈ 0.19–0.28 (empirically), against a gate of 0.75. Unreachable.**

#### (D3) 2-D box IoU against the **third candle's body rectangle**

Align the rule engine with what the model was actually trained to detect:

```
R' = x ∈ [x(i) − w_body/2, x(i) + w_body/2]  ×  rows ∈ [ y(max(open_i,close_i)), y(min(open_i,close_i)) ]
```

A perfect match scores **1.0** → the gate is reachable, and the metric means something the model can
actually achieve. `[PROPOSAL]` This is the only self-consistent definition of "IoU between the
detector's box and the rule engine's FVG" for this checkpoint.

*Cost:* the rule engine must additionally expose c3's `open`/`close` and the renderer must expose
`w_body` and `y(·)`. Both are cheap — the state machine already holds the bars.

*Semantic change (must be stated in the code and in the docs):* the gate changes from
*"the vision model confirms the price gap"* to *"the vision model independently localises the same
bar"*. It becomes a **cross-check on the rule engine's geometry**, which is what a vision layer can
honestly be. It does **not** and cannot verify "clean price action" — see §D.

`[PROPOSAL]` Threshold: start at **IoU_box ≥ 0.5**, then calibrate on the Kaggle *test* split (44
images where we know both the annotation and the rendered pixel geometry). Do **not** keep 0.75
unexamined: given the model's `mAP@50-95 = 57.4 %`, its box corners are already loose, and 0.75
may leave too few survivors. `0.75` is defensible for the *1-D vertical* IoU against the body
(where a perfect match is 1.0 and the failure mode is a small vertical offset) but should be
calibrated, not inherited.

#### (D4) Hybrid — the recommendation

`[PROPOSAL]`

1. **x = bar selection.** Compute the detector box's horizontal centre, map it to a bar index
   `k = floor(x_centre / (640/W))`, and require `k ∈ {i-2, i-1, i}`; strongly prefer `k = i` (the
   gap-opening bar), which is exactly what the model was trained to mark. The detector's box is
   ~1 bar wide, so its **centre** — not its extent — is the bar identifier.
2. **y = vertical agreement.** 1-D vertical IoU between the selected box's rows and the **third
   candle's body** rows: `IoU_v_body ≥ τ_v`, with `τ_v = 0.5` proposed.
3. **class = direction.** The box's class must equal the FVG's direction (`bearish_fvg` for a
   bearish gap, `bullish_fvg` for a bullish gap), after mapping our direction convention
   (the doc trades *against* the gap; the model labels the gap's own direction).
4. **Report the gap IoU as a descriptive statistic only** — `IoU_v_gap` — never as a gate.

This decouples "is it the right bar?" (x, categorical) from "is it the right vertical extent?"
(y, continuous) and does not require the detector's 1-bar box to have the same width as anything
the rule engine produces.

### C.3 Summary — perfect-match score per definition

| # | Definition | Perfect-match IoU | `> 0.75` gate |
|---|---|---|---|
| D1 | 1-D vertical IoU vs the **gap interval** (doc literal) | **0.00** (boxes are candle bodies) — empirical median 0.0000, 87.9 % exact zeros | **UNREACHABLE** — rejects ~99.4 % of true positives |
| D2 | 2-D IoU vs the **gap rectangle over 3 bars** | **≈ 1/3 × (box width / rect width) ≈ 0.19–0.28**, resolution-independent | **UNREACHABLE** |
| D3 | 2-D IoU vs the **c3 body rectangle** | **1.00** | reachable (calibrate τ) |
| D4 | x-bar selector + 1-D vertical IoU vs c3 body | **1.00** | reachable (calibrate τ) |

### C.4 The x-axis, answered

* The detector's horizontal extent **must** be used, but as a **bar selector**, never as an IoU term
  (the widths are incomparable by construction — §C.2 D2).
* Alignment is deterministic and needs no calibration: the rule engine knows the FVG's bar index
  `i` (it already carries `fvg_c1_idx`, `fvg_c3_idx` — `RULE_SPEC.md` §1.3), and the renderer knows
  `x(·)`. Map the detector box's centre to a bar index and compare indices.
* The model's box is ~0.85 bar wide, so "the box overlaps bar i" is a ±0.5-bar tolerance; using the
  **centre** and requiring `k == i` is the sharpest available test and should be primary, with
  `k ∈ {i-2,i-1,i}` as the fallback for images where the detector's box is wider than a bar.
* Do **not** try to match "the FVG formed around bar k" to "the detector's box" by price — the
  detector's box carries no price information; only its position in the rendered frame does.

### C.5 The "35 % noise filtered" claim

`[FACT]` The doc (L139) claims the gate "能过滤掉约 35% 的假突破噪音". `RULE_SPEC.md` I09 already
records this as an unverified assertion. `[FACT]` The model's own operating characteristics
contradict the framing: it detects **11 FVGs per ~90-bar window** (median over the dataset) with
recall 0.908 and precision 0.888 — it is a **locator**, not a precision filter. `[INFERENCE]` The
vision layer should be treated as a *feature generator* and a *sanity check*, and the "35 %" figure
must not appear in any performance claim.

---

## D. The "Visual Clarity Score"

`[FACT]` The doc names it — "输出视觉形态置信度（Visual Clarity Score）" (L138) — and never defines
it. `RULE_SPEC.md` A16 proposes "the detector's class confidence of the box matched to the rule
FVG", marked `[M]`.

`[INFERENCE]` A16's proposal is *not* monotone in "clean price action": the detector is
high-recall and fires on ~11 gaps per window, and its confidence is only weakly related to how clean
the price action is. It is also nearly a restatement of "the gate passed" plus a confidence number.
A better definition must be monotone in cleanliness, computable from detector outputs only, and
must not be a re-parameterisation of IoU.

### `[PROPOSAL]` Definition

For the matched detection `d` (class `c`, confidence `f`, box `b`) inside a window of `W` bars:

```
f_match   = d.conf                                                    ∈ [0,1]
n_same    = number of OTHER detections of class c in the same window
purity    = 1 − n_same / (W − 1)                                       ∈ [0,1]
n_adj     = number of same-class detections whose bar index is within ±1 of d's bar index
isolation = 1 − min(1, n_adj / 2)                                     ∈ [0,1]

VisualClarityScore = f_match · purity · isolation                     ∈ [0,1]
```

* **Derived only from detector outputs** — class, confidence, count and position of detections.
  No price data, no rule-engine score.
* **Monotone in clean price action** — a window in which the model flags exactly one gap, and
  nothing adjacent to it, scores high; a window in which the model flags 15 gaps of the same class
  (chop) scores low, because `purity` collapses and `isolation` collapses. Note the `purity`
  denominator `W − 1` makes the score comparable across windows.
* **Not a restatement of IoU** — IoU enters only as a *binary precondition* (which detection is
  "the" one). The score itself is a function of confidence and detection **density**, quantities
  IoU does not encode.
* **Range** `[0, 1]`, higher = cleaner. Use it as a **continuous feature** for the meta-labeler,
  not as a gate (the gate's job is the IoU/class match).

`[PROPOSAL]` Two refinements worth considering, to be decided after seeing the feature's
distribution on real data:
* Replace `purity`'s denominator with the number of *FVG candidates the rule engine found in the
  window* rather than `W − 1`, so the score measures "of the gaps that are really there, how many
  did the vision layer also see" — this is a **recall-flavored** quantity and is more meaningful
  than a raw count, but it couples the vision layer to the rule layer (the design says the layers
  must not influence each other, so keep it as a *feature*, computed offline, not a gate).
* Report the three components separately (`f_match`, `purity`, `isolation`) in the cached feature
  table so the meta-labeler can learn its own combination instead of inheriting ours.

`[FACT]` The doc also calls the visual output "视觉检测置信度" (L146, the meta-labeler feature list).
That is `f_match` — a different thing from the "Visual Clarity Score". **The two must be kept as
separate columns** in the feature table, or the meta-labeler will be fed the same number twice
under two names.

---

## E. Performance budget

### E.1 Candidate rate

`[FACT]` From the dataset: 3,650 FVG instances over 295 images × ≈90 bars ≈ 26,550 bar-windows
⇒ **0.1375 raw FVGs per bar**.

`[INFERENCE]` Over the doc's NY killzones (`RULE_SPEC.md` §1.5: 09:30–11:30 and 13:30–15:30 ET =
240 one-minute bars per RTH day) ⇒ **≈ 33 raw FVGs/day** before any rule filter.

`[INFERENCE]` The rule engine's filters (sweep prerequisite, `gap > 0.25·ATR(14)`, inversion within
7–15 bars, checklist A/A+ only, SMT, killzone) reduce this, but **the exact rate is not yet
measurable** — it must be measured from the phase-1 rule engine on real NQ 1m bars. Until then,
budget for **2–7 candidates/day** (a 5–15× reduction is typical for this rule set) and keep the
table below as the planning envelope.

| Candidates / day | 3 years × 252 days | renders | detections |
|---|---|---|---|
| 2 | 1,512 | 1.5 k | 1.5 k |
| 7 | 5,292 | 5.3 k | 5.3 k |
| 33 (no rule filter) | 24,948 | 25 k | 25 k |

`[INFERENCE]` Also plan to run the detector over **every** FVG the rule engine sees, not only the
A/A+ ones — the meta-labeler must be trained on the full candidate set (`RULE_SPEC.md` A23/A24), and
the model's detection count is itself an informative feature.

### E.2 Rendering cost

`[INFERENCE / estimate — matplotlib/mplfinance are not installed here, so this is not measured]`
The cost is dominated by **figure construction**, not by pixel pushing. A `mplfinance` render of a
60–90-bar chart is ≈ **50–120 ms at 224×224** and ≈ **80–200 ms at 640×640** (axes creation, tick
layout, text metrics). At 25 k renders that is **0.5–1.4 hours** of pure rendering.

`[PROPOSAL]` Two mitigations: (i) render once and cache the PNG **and** its `sha256` next to the
extracted features, so a threshold change never re-renders; (ii) for the offline batch, replace
mplfinance with a direct renderer (matplotlib `Rectangle`/`vlines` on a bare `Axes`, no ticks, no
spines) — the training style needs *no* axis furniture, so this is both faster and more faithful
than `mplfinance`.

### E.3 Inference cost

`[FACT]` Model: 21.78 M parameters, 640×640 input, stride 8/16/32, end2end head.
`[FACT]` **This host has no GPU** (`nvidia-smi` absent); CPU is an **AMD Ryzen 5 5500U, 6C/12T,
AVX2** (max 4.07 GHz). Measured fp32 SGEMM ceiling with numpy 2.4.6 on this box:
**186.5 GFLOP/s** (1024³ matmul in 11.5 ms).

`[INFERENCE]` Convolutions on CPU typically realise 15–35 % of the SGEMM ceiling ⇒ ≈ 30–65 GFLOP/s
effective. A detector of this class at 640² is of the order 40–60 GFLOPs per image (not measured
here — flag as an estimate) ⇒

| Target | This host (CPU) | Discrete GPU (RTX 3060/4060, fp16) |
|---|---|---|
| 640×640 | **≈ 1–2 s / image** | ≈ 4–8 ms / image |
| 224×224 (12.3 % of the pixels) | ≈ 0.12–0.25 s / image | ≈ 1–2 ms / image |

3-year totals at 640×640 on this host: 1.5 k candidates ≈ 25–50 min; 25 k candidates ≈ **7–14 h**.
At 224×224: 3–10 min and 50 min–2 h respectively. On a GPU: seconds to a couple of minutes.

`[INFERENCE]` The *author's* training run cost 8.1 h for 80 epochs on CPU — a useful sanity check
that CPU-only training of this model is slow but not impossible, and that **inference (1 image) is
~10,000× cheaper than one training epoch**.

### E.4 Verdict and the offline batch design

`[INFERENCE]` **The layer is affordable — at any of these volumes — but it must not live in the
event loop.** Four reasons, in order of weight:

1. **The meta-labeler needs the feature over history anyway.** The training set is "all phase-1
   candidates, successful and failed" (`RULE_SPEC.md` A23). So the vision pass must be run
   over the whole historical candidate set *before* any training — which is by definition a batch
   job, not a per-event online call.
2. **Reproducibility.** A backtest must be bit-reproducible. A neural network inside the event loop
   makes the run depend on GPU/driver/cuDNN/thread-count nondeterminism. An offline join does not.
3. **The live engine cannot depend on a GPU in the hot path.** A 1–2 s CPU inference inside a
   Nautilus `on_bar` handler would stall the event loop; even on a GPU it couples trading latency
   to model latency.
4. **The layer contract.** The design says the vision layer may only *filter*, never alter the rule
   layer's decisions (`RULE_SPEC.md` INV5). A precomputed join enforces that structurally: the
   rule engine's output is fixed before the vision feature is ever attached.

`[PROPOSAL]` **Batch design**

```
dodgys_dd_quant/vision_validator/
    style.py       STYLE_VERSION, colors, grid, candle geometry  (single source of truth)
    render.py      render_window(bars, style) -> RenderedWindow(image, y_of_price, x_of_bar, w_body)
    detect.py      load_detector(path, ultralytics_version) -> wrapper; .predict(img, imgsz=640, conf=0.25)
    features.py    compute_vision_features(rule_event, rendered, detections) -> VisionFeature
    io.py          parquet read/write for the feature table

scripts/build_vision_features.py     # offline batch driver
```

1. **Input**: the phase-1 rule engine's event log — one row per candidate iFVG, carrying
   `instrument_id`, `fvg_ts_ns`, `fvg_c1_idx/c2_idx/c3_idx`, `gap_low`, `gap_high`, `fvg_dir`,
   `open3`, `close3`, `atr14`, `grade`, `outcome`.
2. **Render**: for each event, slice the last `W` bars, render with `style.py`, and **assert**
   `window_end_ts ≤ event_ts` (cheap look-ahead insurance; the window is backward-looking so this
   should never fire, but it must be checked, not assumed).
3. **Detect**: one `YOLO` instance, batched, `imgsz=640`, `conf=0.25`, `verbose=False`.
4. **Feature**: for each event, select the matching detection (D4), compute
   `vision_conf`, `vision_iou_body`, `vision_iou_gap` (descriptive), `vision_bar_index_delta`,
   `vision_class_match`, `vision_n_detections`, `vision_n_same_class`, `vcs`,
   `vcs_f_match`, `vcs_purity`, `vcs_isolation`, plus `render_style_version`, `imgsz`, `window_bars`,
   `image_sha256`.
5. **Output**: `data/features/vision_features.parquet`, keyed by
   `(instrument_id, fvg_ts_ns, rule_event_id)`.
6. **Strategy integration**: `on_data` looks up the row by `(instrument_id, ts_event)`.
   **A missing row must be an explicit, logged decision, not a silent pass** — the doc's gate is
   `rules_triggered AND IoU > 0.75`, so a missing feature must mean *reject* (and be counted in a
   "vision feature missing" counter that the backtest report prints). Otherwise a join bug becomes
   an invisible change in the traded set.
7. **Cache discipline**: store the rendered PNG under `data/cache/renders/<sha256>.png` so a
   threshold change re-runs detection only, and a style change re-renders only.

`[INFERENCE]` **One more design point:** because the vision feature is computed *offline* and
*joined*, it can be attached to **every** candidate in the training set including the ones the gate
rejects. That is what makes it usable as a meta-labeling **feature** (as the doc intends at L146)
rather than only as a hard filter. It also means the "35 % noise filtered" claim can finally be
*measured* — count how many phase-1 losers pass and fail the gate.

---

## F. Consolidated recommendations

| # | Recommendation | Cost | Priority |
|---|---|---|---|
| R1 | **Drop the `IoU > 0.75` gate as specified.** It is unreachable (§C.2 D1/D2: perfect match scores 0.00 / ≈0.25). Replace with the D4 contract: x-bar selector + 1-D vertical IoU against the **third candle's body** + class match, τ ≈ 0.5 calibrated. | ~0.5 day | **P0** |
| R2 | **Render in the model's training style**: white `#FFFFFF` background, `#FAFAFA` grid, teal/`#0A0A0A` candles with wicks, no axes/legend, **640×640**, `conf=0.25`, `imgsz=640`. Delete the "224×224" and "纯黑背景" requirements from the doc (they are the source of the mismatch, not a constraint). | ~1–2 days | **P0** |
| R3 | **Pin `ultralytics==8.4.64`** (and `torch==2.12.0`) — the model card does not state it; only the Space's `requirements.txt` does. Verify that the checkpoint loads and reproduces `train_metrics` before trusting any output. | ~1 hour | **P0** |
| R4 | **Decide the licence.** AGPL-3.0 on the weights; MIT on the dataset. | legal review | **P0** (blocks deployment) |
| R5 | **Build the offline batch pipeline** (`scripts/build_vision_features.py`) and the feature parquet; the vision layer joins, it does not run in the loop. | ~2–3 days | **P1** |
| R6 | **Define the Visual Clarity Score** as `f_match · purity · isolation` (§D), keep it distinct from the raw detector confidence, and expose the three components separately. | ~0.5 day | **P1** |
| R7 | **Start the fine-tune** (option ii) on our own renders with rule-engine auto-labels — this is what makes ES/YM/QQQ/GC/BTC, 1m/5m and a chosen resolution possible. | ~1 week | **P1** (parallel with R5) |
| R8 | **Run experiment V-1** (§B.4) to quantify the domain gap before and after R2. | ~1 hour | **P1** |
| R9 | **Delete the "≈35 % noise filtered" claim** from the docs until it is measured (it is already flagged in `RULE_SPEC.md` I09). | 5 min | **P1** |
| R10 | **Fix the metric discrepancies** in the model card (precision 83.9 % vs 88.85 %, mAP@50 92.3 % vs 93.16 %) and the Kaggle card ("~2,400+" vs 3,650 instances) in our internal notes, so nobody quotes the wrong numbers. | 10 min | **P2** |

---

## G. What could **not** be established from the artefacts

* **No inference was run** (no `torch`, no `ultralytics`; explicitly out of scope). Therefore:
  the model's recall/precision on *our* renders, and whether it fires at all at 224×224, are
  **unmeasured**. Experiment V-1 (§B.4) closes this in ~1 hour.
* **Training-time latency on this host** is an estimate from the measured SGEMM ceiling
  (186.5 GFLOP/s); the per-image FLOPs of YOLOv26m were not computed (the FLOP counter needs
  torch).
* **The annotator's exact bar choice** could not be resolved for ~50 % of the boxes by pixel
  geometry alone (the measurement is noisy where neighbouring candles merge); the *symmetric*
  bullish/bearish confirmation rates (48.9 % / 50.0 %) support a single convention (third bar),
  but a human review of ~20 boxes would settle it definitively. **Experiment V-2: overlay 20
  annotated boxes and count.**
* **Whether the model repo's author ever rendered at 224×224** — the repo contains no rendering
  code and no sample images; only the Space's screenshot workflow is visible.
* **The dataset's "≈90 bars per image"** is a measured median over 40 sampled training images
  (column-clustering count), not an exact figure for all 295.
* **The 60-bar → 90-bar window change** (§B.5) has no measured accuracy impact; that is part of
  experiment V-1.

---

## Appendix — reproducibility of the measurements in this document

* **Checkpoint metadata / architecture / parameter count** — `pickle.Unpickler` subclass with a
  stubbed `find_class` and a stubbed `persistent_load`, run over `best/data.pkl` extracted from
  `research/huggingface/nq-fvg-detector/best.pt`. Parameter count = Σ over all 520 recovered tensor
  shapes = 21,776,096.
* **Image geometry / colour / annotation statistics** — `magick` (ImageMagick 7) to decode to raw
  `rgb:-` and to render box overlays; all arithmetic in pure Python over the raw byte buffer.
  Scripts were run from `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/`.
* **CPU ceiling** — numpy 2.4.6 SGEMM benchmark on the uv-managed CPython 3.11.17 interpreter.
* **Upstream metadata** — HF model API, HF Space file resolve, Kaggle dataset API, PyPI JSON;
  all fetched read-only on 2026-11-22.
