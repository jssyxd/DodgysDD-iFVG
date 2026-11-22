# AUDIT.md — cross-audit of the six analysis reports against their source evidence

**Auditor role.** This file verifies; it does not add new findings about the strategy, and it does not
rewrite any report. Every verdict below is **VERIFIED** (I reproduced it), **WRONG** (I refuted it —
evidence given) or **UNSUPPORTED** (the report asserts it, but the cited source does not establish it).

**Scope and caveats.**

* Six reports were audited: `research/docs/RULE_SPEC.md`, `research/analysis/PINE_RULES.md`,
  `research/analysis/VISION_AUDIT.md`, `research/analysis/ML_REUSE.md`,
  `research/analysis/DATA_FEASIBILITY.md`, `research/nautilus/NAUTILUS_API.md`.
* `research/analysis/VISION_AUDIT.md` **did not exist when this audit began** (it was written at
  15:52 by a sibling worker while I was mid-verification). I audited it as delivered. That is a
  process finding, not a defect in the file.
* The six reports are *not* equal in quality. `PINE_RULES.md` and `VISION_AUDIT.md` are, as far as
  I could check, almost entirely accurate. `DATA_FEASIBILITY.md` contains one load-bearing
  measurement that is flatly wrong, and `ML_REUSE.md`'s ICT-corpus section contains six wrong
  counts. `RULE_SPEC.md` is accurate on essentially every line citation I tested, with two
  diagnosis errors.
* **No artifact in this repo was modified.** No report was edited. Only this file was written.
* The design doc is `iFVG几个模型的讨论.txt` (283 lines, UTF-8/CRLF). The reference implementation
  is `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` (694 lines, Pine v6).

---

## 0. Verdict summary

| Report | Load-bearing claims checked | VERIFIED | WRONG | UNSUPPORTED |
|---|---|---|---|---|
| `PINE_RULES.md` | 6 groups | 6 | 0 | 0 (1 open question, E-1, correctly self-flagged) |
| `RULE_SPEC.md` | 8 thresholds + 11 inconsistencies | 17 | 2 (I05 second boundary; B3 line range/consequence) | 1 (A32 now refuted by `VISION_AUDIT.md`) |
| `VISION_AUDIT.md` | 5 groups | 5 | 0 | 2 (§A.8 third-bar rates; §A.9 IoU histogram) |
| `ML_REUSE.md` | 5 groups | 5 | 2 (Qlib `future` grep evidence; ICT corpus counts ×6) | 0 |
| `DATA_FEASIBILITY.md` | 6 groups | 6 | 1 (**§C2 "agreement = 1.000"**) + 3 minor | 1 (F7 — actually refuted) |
| `NAUTILUS_API.md` | 7 smoke tests + 4 assertions | 11 | 1 (T7 output is not the real output) | 0 |

**The three findings that most change the plan** are in §D.2.

---

# A. Claim verification

## A.1 `research/analysis/PINE_RULES.md` → `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine`

### A.1.1 FVG geometry — **VERIFIED**

`PINE_RULES.md` §B.1 R2 quotes `pine:L354`:

```pine
354	    bool  fvgHere     = isLow ? low[1] > high[3] : high[1] < low[3]
355	    float fvgTop      = isLow ? low[1] : low[3]
356	    float fvgBottom   = isLow ? high[3] : high[1]
```

Reproduced verbatim at `ifvgUltimatePlus.pine:354-356`. The report's restatement (`C.low > A.high`
with `A = bar_index-3`, `C = bar_index-1`; gap zone `[A.high, C.low]` for bullish) is correct, and
its strictness claim (`==` is rejected) follows from the code. The report's cross-check against the
doc (`iFVG几个模型的讨论.txt:121`, `Candle[i-2].high < Candle[i].low`) is also correct: `low[1]`
is `c[i].low` and `high[3]` is `c[i-2].high`.

### A.1.2 Inversion trigger predicate — **VERIFIED**

`pine:L437` reproduced verbatim:

```pine
437	                bool trigger = sourceBearish ? close[1] > e.fvgTop : close[1] < e.fvgBottom
```

with `lvl = close[1]` at `pine:L441`. The report's four claims all hold: body close (not wick),
**strict** `>`/`<`, evaluated on the *previous* bar's close, and direction inverted relative to the
FVG type. `RULE_SPEC.md` §1.3 reaches the same predicate independently (`close[k] < c[i-2].high` for
a bullish gap) — the two reports **agree** here.

### A.1.3 `graceCandles` and the [0,15] vs [7,15] conclusion — **VERIFIED**

`pine:L658` reproduced verbatim: `int graceCandles = allowExtIFVG ? 15 : 6;`, and the expiry at
`pine:L499-500`:

```pine
499	                if not trigger and bar_index - e.fvgBar1 > graceCandles
500	                    arr.remove(i)
```

I re-derived the window from the control flow rather than trusting the report:

* the candidate is created on bar `X0` with `fvgBar1 = X0 - 1` (`pine:L380`);
* the trigger is tested on the **same** bar `X0` (`pine:L437`, `close[1] = close(X0-1) = close(fvgBar1)`),
  so the confirmation candle may be the FVG's own newest candle → **age 0**;
* on evaluation bar `Y`, the expiry is tested **after** the trigger (`pine:L499`), so a candidate that
  has not yet triggered is removed at the first `Y` with `Y - fvgBar1 > 15`;
* therefore the trigger can still fire on evaluation bar `fvgBar1 + 16`, whose `close[1]` is
  `close(fvgBar1 + 15)`.

**The confirmation candle's age therefore ranges 0 … 15 inclusive.** The report's headline "the
window is [0, 15], not [7, 15]" is **correct**, and the "there is no lower bound" claim is correct
(grep finds no minimum-age test anywhere in the file).

### A.1.4 "No ATR / no SMT / no scoring / no checklist" — **VERIFIED**

Case-insensitive greps over the whole file: `atr` → **0**, `smt` → **0**, `score` → **0**,
`grade` → **0**, `checklist` → **0**, `a+` → **0**. The only `ta.*` calls are `ta.sma` (`pine:L85`),
`ta.lowestbars` (`pine:L350-351`) and `ta.highestbars` (`pine:L350-351`). `strategy.*` calls: **0**.
`request.security` calls: **1** (`pine:L635`, same-symbol HTF FVG only — no cross-instrument call).
`input.*` declarations: **50** (matches the report's parameter table).

The report's §0.1 framing — that the replica's omissions are the *replica author's* choices, not
evidence about the closed-source original — is the correct epistemics and is supported by
`research/github/IFVG-Ultimate-Dodgy/README.md:17-18`.

### A.1.5 `hideLosing` erasure block — **VERIFIED**

`pine:L519-525` reproduced verbatim:

```pine
519	                    if hideLosing
520	                        box.delete(tr.fvgBox)
521	                        line.delete(tr.entryLine)
522	                        label.delete(tr.entryLabel)
523	                        int recIdx = setupRecords.indexof(tr)
524	                        if recIdx >= 0
525	                            setupRecords.remove(recIdx)
```

Default `true` at `pine:L8`. The report's reading — pure post-hoc erasure of losers, and the
doc's warned-about "Hide Losing Setups" behaviour confirmed at code level — is correct.

### A.1.6 Session windows gate alerts only — **VERIFIED**

`pine:L123-126` defines `inSession1..3` / `inAlertSession`; `pine:L497-498` is the **only** consumer:

```pine
497	                        if enableAlerts and inAlertSession
498	                            alert((ifvgBullish ? "Bullish" : "Bearish") + " IFVG confirmed on " + syminfo.ticker, alert.freq_once_per_bar_close)
```

Defaults confirmed at `pine:L60` (`"0930-1600"`, enabled), `L62` (`"2000-0000"`, disabled),
`L64` (`"0200-0500"`, disabled); timezone hard-coded `"America/New_York"` at `pine:L79`. The report's
§C-13 conclusion — the doc's 09:30–11:30 / 13:30–15:30 killzones have no counterpart in code and the
code's windows are *wider* and *alert-only* — is correct.

### A.1.7 One open item, correctly self-flagged — **UNSUPPORTED but honestly marked**

`PINE_RULES.md` §E-1 asks what `ta.lowestbars(3) == -1` means and states in §B.1 R1 that "the actual
extreme sits at `bar_index` while the recorded origin is `bar_index - 1`" (i.e. the origin is one
bar *inside* the swing).

I could not settle this from this host: `https://www.tradingview.com/pine-script-reference/v5/...`
and `raw.githubusercontent.com` are both refused by the fetch proxy, and no Pine interpreter exists
here. **However, the code's own internal consistency points the other way**: `pine:L352` sets
`originSrc = isLow ? low[1] : high[1]` and `pine:L360` sets `originBar = bar_index - 1` — the
recorded origin bar and the recorded origin price are **the same bar**. Under the report's reading
the author would be recording a swing origin one bar inside the swing, which no implementation of a
swing tracker does. The most likely truth is that `ta.lowestbars(3) == -1` means "the lowest of the
last 3 was 1 bar ago", making the origin the swing bar itself.

**Consequence if the report is wrong:** the break-even level (`pine:L476`, `tr.bePrice := e.swingPrice`)
and the FVG search window (`pine:L377`) both shift by one bar, and the `requireBEIntact` gate
(`pine:L442`) drops or admits a different set of setups. The report's §D.0 advice — "treat offset
`0` (current) as the 'pivot' case" — is inverted under the reading I favour. **Treat E-1 as an
unresolved one-bar ambiguity to be settled by porting both variants**, exactly as the report itself
recommends. Do not treat R1's assertion as established.

---

## A.2 `research/docs/RULE_SPEC.md` → `iFVG几个模型的讨论.txt`

I spot-checked **8 thresholds** and **11 internal inconsistencies** against actual line numbers.

### A.2.1 Threshold spot-checks (8) — all line citations **VERIFIED**

| ID | Claim | Cited line | What the line actually says | Verdict |
|---|---|---|---|---|
| T02 | min gap `> 0.25 * ATR(14)` | L121, L280 | L121: `…且缺口大小必须大于 0.25 * ATR(14)。` L280: `…0.25 ATR 间距判定…` | **VERIFIED** |
| T04 | inversion window `7 … 15` | L123 | L123: `…在 7 至 15 根 K 线内，出现一根实体收盘价（Body Close）彻底穿透该 FVG 远端边界的 K 线…` | **VERIFIED** (and the doc is self-contradictory — see I01) |
| T07 | VXN bins `[0,18,28,200]` → labels `0/1/2` | L265-266 | L265 `bins=[0, 18.0, 28.0, 200.0],` L266 `labels=[0, 1, 2]` | **VERIFIED** |
| T14 | SMT weight `+2` | L119 | L119: `…若出现 SMT 背离，信号基础权重 +2 分。` | **VERIFIED** |
| T16 | liquidity target `≥ 2R` | L126 | L126: `…距离入场位至少 2R 处存在明确的 EQH/EQL、未触及的时段高低点或单边流动性（LRLR）。` | **VERIFIED** |
| T19/T20 | IoU gate `> 0.75` + "≈35% noise" | L139 | L139: `…只有当 规则引擎触发 == True 且 视觉模型 IoU > 0.75 时，才放行进入下一层。这能过滤掉约 35% 的假突破噪音。` | **VERIFIED** (both the gate and the unevidenced 35% figure) |
| T32/T33/T34 | PF > 1.25, ~$4.5, 1-2 ticks, 1:2 RR, A/A+ only | L170 | L170 contains all five verbatim, incl. `如果纯规则阶段为负，说明规则细节还原有误，绝不能直接上 ML 掩盖问题。` | **VERIFIED** |
| T49/T50 | VXN lag `shift(1).bfill()`, daily-or-intraday | L207, L261-262 | L207: `…获取日线/分钟线，并在导入引擎前进行前向填充（Forward-Fill）与严格 1 根 K 线滞后（Shift(1)）对齐…`; L262: `vxn_df["vxn_known"] = vxn_df["Close"].shift(1).bfill()` | **VERIFIED** |

Spot-checks that also came out clean: T05/T06 (L115), T08-T13 (L107-109), T15 (L45/L107/L170),
T17 (L143), T21 (L137/L274/L279), T22 (L137), T23 (L138), T24/T25 (L145/L282), T26 (L146),
T27-T29 (L150-152), T31 (L156), T35 (L173), T36 (L175), T37-T41 (L160-163, L116),
T44 (L92/L119/L169), T46 (L109), T50 (L260), T51 (L86/L101/L143/L150).

**Tag spot-check on the three `[DERIVED]`/`[DOC-SVG]` calls that matter:**

* **T45 `1%` baseline risk tagged `[DERIVED]` — correct.** L109 reads `…（如从 1% 降至 0.5%）`; the
  `1%` appears only as the pre-halving reference, never as a standalone rule.
* **T18 `0.58` tagged `[DOC-SVG]` — correct.** `grep -n "0\.58" iFVG几个模型的讨论.txt` → **no match**.
  The value exists only in `diagram-四层正 EV 量化系统完整架构.svg` (`若 P(Win) < 阈值 (如 0.58)，直接拦截放弃交易`).
* **T30 RL multipliers tagged `[DOC-SVG]` — correct.** `0.5x, 1.0x, 1.5x` appear only in SVG-A.
* **T47 data layer tagged `[DOC-SVG]` — correct.** `数据层 : NQ + ES 1m/5m Tick/Bar + VXN 指数` is SVG-A only.

**Consistency of the SVG citations** — I extracted every text node from both SVGs. All of
`RULE_SPEC.md` §2.3's SVG-A/SVG-B rows match the source strings exactly, including
`输入 : 规则评分 + 视觉置信度 + VXN Regime + 时间衰减特征` (which is the basis of I04) and
SVG-B's `# 4. 忠实还原 DodgysDD的 iFVG状态机（流动性扫荡 +SMT+7-15根反转）` (which is the basis of I01).
**There is no `rl/` directory in SVG-B** — A28 is correct.

### A.2.2 Inconsistency register — 9 of 11 **VERIFIED**, 2 **WRONG**

* **I01** (L123 "7 至 15 根 K 线内" vs L73 "15根K线内反转确认") — **VERIFIED**, both lines say exactly that.
* **I02** (L121 "扫荡发生**前**" vs L11 "在扫荡发生**前后的**波动中") — **VERIFIED**.
* **I03** (three numbering schemes) — **VERIFIED**: L133 `模块 1：视觉检测模型…`, L141 `模块 2：ML 滚动训练…`,
  L148 `模块 3：强化学习…` vs SVG-A's `1./2./3./4.` vs SVG-B's `# 1`–`# 6`.
* **I04** (SVG ML inputs ≠ L146 prose list) — **VERIFIED**.
* **I05** (VXN binning) — **PARTLY WRONG**. See below.
* **I06** (L274 "像素坐标系下的 IoU" vs L279 "垂直价格轴上的 IoU") — **VERIFIED**, both phrases present.
* **I07** (L137/L279 black 224×224 vs `hf:51` 640×640 / `hf:55` white) — **VERIFIED**;
  `research/huggingface/nq-fvg-detector/README.md:51` = `**Input size:** 640x640`,
  `:55` = `Trained on white background TradingView charts only.`
* **I08** (ET vs EST) — **VERIFIED**: L115 `美东时间`, L159/L162/L163 `EST`.
* **I09** ("≈35% noise filtered" unevidenced) — **VERIFIED**.
* **I10** (third meta-label outcome) — **VERIFIED**; L143 defines only `1=达到2R止盈，0=触发止损`.
* **I11** (`请谨慎使用此类代码` at L202 and L270) — **VERIFIED**, both lines exact.

**I05 — the diagnosis is half wrong.** `RULE_SPEC.md` §1.8 says:

> "So VXN == 18 → code says *low* (prose says normal) and VXN == 28 → code says *high* (prose says normal)."

Measured on the 3.11 interpreter with `pandas 2.3.3`:

```
VXN=17.9 -> 0     VXN=18.0 -> 0     VXN=18.1 -> 1
VXN=28.0 -> 1     VXN=28.1 -> 2     VXN=200.0 -> 2
VXN=250.0 -> RAISES ValueError      VXN=-1.0 -> RAISES ValueError
```

**`VXN == 28` maps to `1` (normal), which agrees with the prose** (`18 ≤ VXN ≤ 28` → normal). The
report's claim that the code classifies 28 as *high* is **WRONG** — the right-closed interval
`(18,28]` includes 28. Only the **18** boundary conflicts, and the NaN/`.astype(int)` raise claim is
correct. **The fix in §1.9 is nevertheless right** (and strictly better than the doc's code), so no
downstream harm — but the stated reason was partly invented, and an implementer who trusted the
"28 is a bug" diagnosis would have written the wrong test.

### A.2.3 `prepare_parquet.py` sample defects B1–B8

* **B1** (no instrument defined; `TestInstrumentProvider` imported at L220 but unused) — **VERIFIED**;
  L220 is exactly the import, L226-227 the two `InstrumentId.from_str` calls.
* **B2** (`groupby(level=0)`) — **VERIFIED**, `iFVG几个模型的讨论.txt:234`.
* **B3** (`Price.from_str(f"{…:.2f}")`) — **line range wrong, consequence overstated.**
  The f-strings are at **L244–L247** (open/high/low/close), not "L245–L248" (L248 is `volume=`).
  More importantly, the claim that 2 decimals is "wrong for GC (0.1)" is **wrong**: `f"{2034.5:.2f}"`
  → `"2034.50"` → `Price.from_str` gives precision 2, which is exactly what a 0.1-tick GC instrument
  needs (`price_precision=2`). The genuine defect is that the precision is *hard-coded* rather than
  taken from the instrument — which is what the report says in its first clause.
* **B4** (`yf.download` + `vxn_df["Close"]` MultiIndex) — **VERIFIED**, L260-262.
* **B5** (`pd.cut(...).astype(int)`) — **VERIFIED**, L263-267.
* **B6** (no back-adjustment) — **VERIFIED**, L234.
* **B7** (no conda on this host) — **VERIFIED** (`.field-guide/env.md`).
* **B8** (daily VXN vs 1-hour feature) — **VERIFIED**, L146 vs L260.

### A.2.4 One claim now refuted by a sibling report — **UNSUPPORTED**

`RULE_SPEC.md` A32 resolves the I06 ambiguity as "**2-D pixel-space IoU**". `VISION_AUDIT.md` §C.2 D2
shows that the 2-D form is *also* unreachable when the rule zone is the FVG rectangle: the detector's
box is ~1 bar wide while the rule rectangle spans 3 bars, so `IoU ≤ 1/3` regardless of resolution.
**A32 picks one of the two failing options.** It should be superseded by `VISION_AUDIT.md`'s D3/D4
contract. See §B row *Vision IoU definition*.

---

## A.3 `research/analysis/VISION_AUDIT.md` → `research/huggingface/nq-fvg-detector/` + `research/kaggle/nq-fvg-dataset/`

*(This file was written at 15:52 by a sibling worker, after this audit started. I audited it as
delivered, with the same rigour as the others.)*

### A.3.1 Checkpoint forensics — **VERIFIED, exactly**

I re-ran the report's own technique (stubbed `find_class` / `persistent_load` over
`best/data.pkl` extracted from `best.pt`) and got **field-for-field identical** results:

| Field | Report | My measurement |
|---|---|---|
| `train_args['model']` | `yolo26m.pt` | `yolo26m.pt` ✓ |
| `train_args['imgsz']` | 640 | `640` ✓ |
| `epochs` / `patience` | 100 / 20 | `100` / `20` ✓ |
| `batch`, `rect` | 16, False | `16`, `False` ✓ |
| `device`, `workers`, `cache` | `cpu`, 0, False | `cpu`, `0`, `False` ✓ |
| `mosaic`/`mixup`/`cutmix` | 1.0 / 0.0 / 0.0 | ✓ |
| `hsv_h`/`hsv_s`/`hsv_v` | 0.015 / 0.7 / 0.4 | ✓ |
| `translate`/`scale`/`fliplr`/`close_mosaic` | 0.1 / 0.5 / 0.5 / 10 | ✓ |
| `iou` (NMS) / `max_det` / `conf` | 0.7 / 300 / None | ✓ |
| `train_metrics` precision / recall / mAP50 / mAP50-95 | 0.88849 / 0.90836 / 0.93158 / 0.57395 | **identical to 5 dp** ✓ |
| `epoch` / `optimizer` / `ema` | -1 / None / None | ✓ (stripped final model) |
| `best/data.pkl` size | 203,530 B | `203530` ✓ |

The report's "the model card's numbers disagree with the checkpoint's" table is also correct
(card: 92.3 / 58.2 / 83.9 / 89.4 / 86.6 vs checkpoint: 93.16 / 57.40 / 88.85 / 90.84 / 89.61).

### A.3.2 The IoU definition and what a perfect match scores — **VERIFIED (and stronger than reported)**

This is the report's central claim, so I tested it directly rather than reading it.

**Step 1 — do the boxes wrap the geometric gap, or a candle?** I decoded 40 training images to raw
RGB with `magick` and analysed all **589** labelled boxes in them, classifying each interior pixel
as candle-coloured (TradingView teal `g-r>25`, or near-black `max<110`) vs background (`min>232`):

```
interior candle-colour fraction: median 1.000   mean 0.949
  >50% candle interior: 100.0%
  >80% candle interior:  93.2%
  >80% EMPTY interior:     0.0%
```

The report claims "98.7 % of boxes have >50 % candle interior (median interior coverage 80–83 %);
only 0.1 % are >80 % empty". **Confirmed** — my median is 1.000 (their 80–83 % is evidently a
stricter colour classifier; the conclusion is identical and stronger).

**Step 2 — is a perfect detection's box disjoint from the rule engine's gap interval?** Yes,
algebraically and necessarily:

* bullish FVG: gap = `[high_{i-2}, low_i]`; the annotated candle's body lies in `[low_i, high_i]`,
  so `body ∩ gap = ∅`;
* bearish FVG: gap = `[high_i, low_{i-2}]`; the body lies in `[low_i, high_i]`, so `body ∩ gap = ∅`.

**⇒ Under the doc's literal definition (`RULE_SPEC.md` L274/L279) a *perfect* detection scores
IoU_v = 0.00, not 1.00, and the `IoU > 0.75` gate rejects essentially every true positive.**
This is the single most important technical finding in the whole report set, and it is correct.

**Step 3 — the D2 bound.** The detector's box is ~1 bar wide (median normalised width 0.00859 ×
640 = **5.5 px**) and the rule rectangle spans 3 bars, so `IoU_2D ≤ 5.5 / (3 × 7.1) ≈ 0.26`. The
report's "≈0.19–0.28, resolution-independent" is right.

**One addition of my own (quantitative, and it independently closes the question):** even against the
*correct* object, the 0.75 gate has almost no tolerance margin. For a box of `w × h` px shifted by
`d` px on one axis, `IoU_axis = (w-d)/(2w-d)`:

| box @640 (5.5 × 16.5 px) | IoU_x | IoU_y |
|---|---|---|
| d = 0.50 px | 0.833 | 0.941 |
| d = 0.75 px | **0.760** | 0.913 |
| d = 1.00 px | 0.692 | 0.886 |

| box @224 (1.93 × 5.77 px) | IoU_x | IoU_y |
|---|---|---|
| d = 0.25 px | **0.771** | 0.917 |
| d = 0.50 px | 0.588 | 0.841 |
| d = 1.00 px | 0.317 | 0.705 |

At 224×224 a **quarter-pixel** misalignment on x already drops the 2-D IoU below 0.75
(0.771 × 0.917 → 0.708 combined). At 640×640 the gate tolerates ≈0.75 px. So the threshold is
unreachable on **two independent grounds** — semantic (D1) and geometric (sub-pixel).

### A.3.3 The resolution arithmetic — **VERIFIED**

* Median normalised box **w 0.00859 / h 0.02578** — my independent count over all 3,650 labels:
  **identical to 5 dp** (median w 0.00859, median h 0.02578) ✓
* ⇒ **5.50 × 16.50 px @640** and **1.93 × 5.77 px @224** — matches my computation exactly ✓
* **3,650 boxes**, 2,000 `bullish_fvg` (class 1) / 1,650 `bearish_fvg` (class 0) — ✓ exact
* **155 1min + 140 5min** images, 207/44/44 split — ✓ exact
* Boxes per image: median **11**, range **0–24** — ✓ exact
* **Bar pitch = 7 px**: I derived this independently from the label x-centres — the most common
  gap is **7 px (81 occurrences)**, with 14, 21, 28, 35, 42 (= 2×7, 3×7, …) all present as
  multiples. 640 px / 7 px ⇒ **≈91 bars**, confirming the report's "≈90 bars" and therefore its
  0.525 uniform-downscale factor for a 60-bar 224×224 render ✓
* All 295 images are **640×640** JPEG (I parsed every SOF0 header) ✓

### A.3.4 "The model needs a white 640×640 render" — **VERIFIED**

* `research/huggingface/nq-fvg-detector/README.md:55` — `Trained on white background TradingView charts only.`
* `README.md:51` — `**Input size:** 640x640`
* I opened `test/images/1min-NQ-103_png.rf.bb6a8c94dd2554fb82e795a48b393e11.jpg` and histogrammed it:
  **269,643 px of `srgb(255,255,255)`**, then a cascade of 248–254 grey values (the gridlines and
  JPEG ringing), i.e. a **pure-white background with `#FAFAFA`-class gridlines**, teal up-candles,
  near-black down-candles, wicks, **no axes, no legend, no indicators**. The report's §A.7 table is
  accurate. The doc's demand (`iFVG几个模型的讨论.txt:137,279`) for a **black 224×224** render is
  therefore wrong on both axes.

### A.3.5 Two quantified sub-claims I could not reproduce — **UNSUPPORTED**

* **§A.8 item 4** ("the annotated candle is the third bar: 48.9 % bullish / 50.0 % bearish
  confirmation"). My own pixel test of the same hypothesis gave **92.3 % bullish / 58.5 % bearish**
  over 579 resolvable boxes (bar pitch 7 px, bar-slot quantised). The two numbers do not agree; my
  method is cruder, so I cannot call the report's figure wrong — but I also cannot reproduce it.
  **The substantive conclusion is unaffected and independently confirmed**: the annotation is a
  **per-candle marker**, not a gap-region box (A.3.2, step 1).
* **§A.9's histogram** (`n = 2,443`, median IoU 0.0000, 0.65 % above 0.75, 87.9 % exact zeros)
  requires reconstructing the FVG geometry from pixels; I could not reproduce it. **UNSUPPORTED** —
  but again, not load-bearing: the same conclusion follows from A.3.2 step 2 without any measurement.

---

## A.4 `research/analysis/ML_REUSE.md` → four external artifacts

### A.4.1 The two look-ahead defects in `xauusd-ml-trader` — **VERIFIED**

**Defect 1 — centered swing window.** `research/huggingface/xauusd-ml-trader/xauusd_trader/strategies/smc_strategy.py:36-55`:

```python
36	    for i in range(lookback, len(df) - lookback):
39	        right_highs = highs[i + 1:i + lookback + 1]     # <-- future bars
41	        if highs[i] > left_highs.max() and highs[i] > right_highs.max():
54	    df['last_swing_high'] = df['swing_high_price'].ffill()
```

The swing at index `j` is only knowable at `j + lookback`, but the flag is written at `j` and
`last_swing_low` is a plain forward-fill of that column. **VERIFIED** — exactly the defect described.

**Defect 2 — order block registered before the displacement that creates it.**
`smc_strategy.py:211-226`: the OB candle is `bearish_candles.iloc[-1]` from `df.iloc[i-lookback:i]`,
but the flags are written with `df.iloc[idx_pos, …]` where `idx_pos` is the **OB candle's own index**,
while the displacement/BOS is at `i`. The strategy therefore knows the order block several bars
before the move that created it exists. **VERIFIED**.

The report's other xauusd claims also check out:
`detect_liquidity_sweeps` (`smc_strategy.py:146`, `low < last_sl and close > last_sl`) ✓;
`detect_fvg` (`smc_strategy.py:290,295`, `low[i] > high[i-2]` / `high[i] < low[i-2]`) ✓;
`add_atr` is `true_range.rolling(14).mean()`, **not** Wilder ✓ (`data_loader.py:187`);
`add_session_labels` documents "Sessions (UTC)" while reading `df.index.hour` with no tz handling ✓
(`data_loader.py:191-204`); **no LICENSE file** although `README.md:234` claims "MIT License - See
LICENSE file" ✓; and the **cost model is declared but never applied** — `spread_pips`,
`pip_value`, `commission_per_lot`, `slippage_pips` occur **only** at their definition lines
`backtesting/wfo_engine.py:30-33` and nowhere else in the package, while
`risk_management.py:294` books `pnl = direction × (exit − entry) × size` with no cost term ✓.

### A.4.2 The 3-class-label claim — **VERIFIED**

`xauusd_trader/ml/ensemble_model.py:102-126`:

```python
115	    forward_returns = df['close'].shift(-forward_bars) / df['close'] - 1
122	    labels = pd.Series(0, index=df.index)
123	    labels[forward_returns > threshold] = 1
124	    labels[forward_returns < -threshold] = -1
```

Docstring: `1 = Buy / -1 = Sell / 0 = Hold`. **VERIFIED** — a 3-class *directional* label, exactly as
the report says, and incompatible with the doc's binary `1 = 2R TP / 0 = SL` meta-label.

### A.4.3 Qlib "no futures / long-only / no shorts" — **VERIFIED** (one cited piece of evidence is wrong)

* **No futures instrument type.** `grep -rniE "future" --include=*.py qlib/` returns **275 hits**,
  not the "only 'future information' / `get_next_trading_date(..., future=True)` / `__future__`"
  list the report states. Every hit is the English word or the `future=True` calendar kwarg
  (`qlib/contrib/ops/high_freq.py:13,22`, `qlib/backtest/utils.py:69`, …) — **so the substantive
  conclusion (no futures instrument type, no contract multiplier, no expiry/roll logic) holds, but
  the evidence as written is wrong.** Marked **WRONG (evidence), VERIFIED (conclusion)**.
* **Equity-only `Exchange`** — `qlib/backtest/exchange.py:46` `limit_threshold`, `:139-155` the
  limit-type logic, `:109-112` `trade_unit, 100 for China A market`, `:227` the adjusted-price
  guard, plus `check_stock_suspended` at `qlib/contrib/strategy/rule_strategy.py:77`. ✓
* **Long-only, no shorts** — `qlib/backtest/position.py:231-243`: the docstring documents
  `{'count': …, 'amount': …}` and `__init__(self, cash, position_dict: Dict[str, Union[Dict[str,float], float]])` —
  a **stock count**, no direction. `grep -ni "short" qlib/backtest/position.py` → **0 hits**.
  `qlib/backtest/decision.py:32-33` defines only `SELL = 0` / `BUY = 1`, and `:84-85` rejects any
  other direction. ✓
* **Canonical strategy is cross-sectional top-k** — `qlib/contrib/strategy/signal_strategy.py:74-88`:
  `class TopkDropoutStrategy(BaseSignalStrategy)` with `topk`, `n_drop`, `method_sell="bottom"`,
  `method_buy="top"`. ✓
* **IC / RankIC** — present in `qlib/contrib/evaluate_portfolio.py:229 get_rank_ic`,
  `qlib/contrib/report/analysis_position/score_ic.py:19-22`,
  `qlib/contrib/report/analysis_model/analysis_model_performance.py:295` ("Information Coefficient (IC)").
  The report cites `qlib/contrib/evaluate.py` for this; that file holds `risk_analysis`,
  `indicator_analysis`, `backtest_daily`, `long_short_backtest` — **the IC/RankIC code is in
  `evaluate_portfolio.py` / `eva/alpha.py` / `report/analysis_position/score_ic.py`**. Minor citation
  imprecision; the report's C.1 table does cite `eva/alpha.py` correctly.
* **Rolling machinery is YAML-bound** — `qlib/contrib/rolling/base.py:5` `from ruamel.yaml import YAML`,
  `:44` the `--conf_path <path to the yaml>` invocation, `:119-121` `yaml.load(f)`;
  `qlib/workflow/task/gen.py:143-144` `ROLL_EX`/`ROLL_SD`, `:153,180,293-294` `trunc_days`;
  `pyproject.toml` pulls `mlflow<3.13`, `redis`, `ruamel.yaml>=0.17.38`, `python-redis-lock`, `pymongo`. ✓
* **HEAD `5435523` (2026-10-08), MIT licence** ✓ exact.
* **AlphaGPT has no IC/RankIC** — `grep -rniE "rankic|information coefficient"` over
  `research/github/AlphaGPT/` → **0 hits** ✓. The report's correction of the design doc's stated
  reason for rejecting AlphaGPT is correct.
* AlphaGPT `FORMULA_VOCAB` pluggability (`model_core/vocab.py:18,31,38-39`), the 12-operator
  `OPS_CONFIG` (`model_core/ops.py:25-38`), `FeatureEngineer` requiring `raw_dict['liquidity']` and
  `raw_dict['fdv']` (`model_core/factors.py:114-115,168-169`), Apache-2.0, upstream HEAD `d851f22`
  2026-06-12 vs mirror `5d38411` 2026-01-11 (5-month lag), and the mirror's missing `vocab.py` —
  all **VERIFIED**.

### A.4.4 The ICT corpus's "SMT Absent still yields VALID" — **VERIFIED**

`research/huggingface/ict-6000-mentorship-master/data/train-00000-of-00001.parquet` — 6,000 rows,
columns `instruction`/`output` ✓. 4,000 rows match `Audit this …` ✓.

I parsed the instruction's `Liquidity Context:` line for the SMT state and crossed it with the
verdict parsed from the output:

```
              INVALID  VALID
ABSENT          852     481     <- "SMT Divergence: Not Present" still yields VALID 481 times
CONFIRMED      1701     966
```

**VERIFIED.** The corpus treats SMT as optional, exactly as the report says.

### A.4.5 The ICT corpus's *counts* — **6 WRONG** (the qualitative conclusions hold)

| Report claim | My measurement | Verdict |
|---|---|---|
| "**2,287** fully parseable" Audit rows | **all 4,000** parse under the natural grammar (`Swing Low = X, Swing High = Y (50% Equilibrium = Z)` + `between A and B (CE/50% = C, located at N%)`); CE arithmetic holds **4,000/4,000**; FVG-inside-range **4,000/4,000**; printed 50% equilibrium matches `(X+Y)/2` to 2 dp for all 4,000 | **WRONG** |
| "Entry price == the FVG edge — **966/966**" | **1,447/1,447** (the Entry/Stop/Target fields exist only on the 1,447 VALID rows) | count **WRONG**, claim **VERIFIED** |
| "Stop = swing extreme ± a fixed per-instrument buffer — **966/966**" | buffer is exact and deterministic: **NQ ±1.0, ES ±1.0, YM ±4.0, XAUUSD ±0.4** (EURUSD/GBPUSD ±0.0) | claim **VERIFIED**, count **WRONG** |
| "Target = the opposite swing extreme, exactly — 966/966" | **1,447/1,447** | count **WRONG**, claim **VERIFIED** |
| "Time windows … → INVALID — **756 rows, 100 % INVALID (252 each)**" | **1,323 rows, 100 % INVALID, 441 each** for {New York Lunch Hour, 2 Minutes Before 08:30 News, Dead Asian Transition} | **WRONG** (the 100 %-INVALID conclusion holds) |
| "Killzone windows (6 of them) → **148–176 VALID, 80–109 INVALID** per window" | measured per window: VALID **223 / 255 / 265 / 251 / 217 / 236**, INVALID **225 / 193 / 183 / 197 / 227 / 205**, n = 441–448 each | **WRONG** |
| instruction template set `{NQ,ES,YM,XAUUSD}` | **7 instruments**: NQ 572, ES 572, YM 572, EURUSD 571, GBPUSD 571, XAUUSD 571, BTCUSDT 571 | **WRONG** |
| "only **5,419** distinct instruction templates" | **5,564** distinct instructions (of 6,000); 5,093 distinct outputs | **WRONG** |
| "'Live Market Application' repeated verbatim **5,000×**, 'Anti-Retail' **4,500×**" | **1,000** and **1,500** outputs respectively | **WRONG** |

The report's *decision* (ADAPT as a test-vector corpus, not training data) and its two most important
content claims — "gates 2–3 are asserted, not derived" and "the prices are fabricated" — are
**VERIFIED** (NQ dealing ranges 20,331–20,735 against ES 5,785–5,903 in the same "session"; EURUSD
rows carry 1.08–1.09 prices). The counts in §D.3's table should be corrected before the corpus is
turned into `tests/fixtures/ict_audit_cases.json` — a fixture built from 966 rows when 1,447 exist
silently drops 33 % of the corpus.

---

## A.5 `research/analysis/DATA_FEASIBILITY.md` → `research/github/dataBaseLake/` + `research/kaggle/`

### A.5.1 The manifest contradiction — **VERIFIED**

* `03_governed_lake/nautilus_databank/MANIFEST.md:8` — "Total Indexed BarTypes: **63**",
  `:9` — "Total Validated Bars: **42,278,836**", `:10` — "Total Storage Size: **1048.76 MB (1.02 GB)**",
  `:6` — coverage 2020-01-01 → Present (2026).
* Universe rows: `| 27 | NQ.CME-1-DAY-LAST-EXTERNAL | 1-Day | 7 | 2020-01-02 to 2026-09-25 | 1,695 |` and
  `| 08 | ES.CME-1-DAY-LAST-EXTERNAL | 1-Day | … | 1,695 |`. ✓
* `grep -n "CME-1-MINUTE" 03_governed_lake/nautilus_databank/MANIFEST.md` → **no match**. The
  1-minute bar types are crypto, FX, metals and US equities/ETFs (QQQ 1,304,397; SPY 1,281,134;
  IWM 1,117,000 — all ✓ as reported).
* `03_governed_lake/v2_parquet_lake/manifest/manifest.json` (v2.1.0, `last_updated_utc`
  2026-10-20T16:55:18Z) → `catalog.us_futures.symbols.NQ` / `.ES` both list
  `timeframes: ['1m','5m','15m','1h','2h','4h','1d']`, `path: us_futures/{NQ,ES}/`. ✓
* `03_governed_lake/v2_parquet_lake/us_futures/` contains **only a 0-byte `.gitkeep`** ✓.

**The two manifests genuinely contradict each other about NQ/ES 1-minute bars, and the report's
framing of it ("the parquet manifest's 1m claim is aspirational, or the 1m partitions exist only on
the share and were never back-filled into the databank") is correct.** §B2 step 4 is the right 5-minute
action.

### A.5.2 Kaggle characterisations — **VERIFIED**

* `research/kaggle/nq-fvg-dataset/NQ-FVG-Dataset/` — **295** JPEG images (207 train / 44 valid /
  44 test) and **295** label files, `data.yaml` with `nc: 2`,
  `names: ['bearish_fvg','bullish_fvg']` ✓. All 295 images are 640×640 ✓.
* `research/kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv` — 4,503 lines =
  **4,502 data rows** ✓, 12 columns exactly as listed ✓, range
  **2026-07-14 04:00 UTC → 2026-09-22 07:45 UTC** ✓, step histogram
  `{15 min: 4452, 75 min: 38, 2955 min: 8, 2940: 1, 60: 1, 4755: 1}` → **48 gaps > 60 min** ✓,
  weekday coverage `Thu 921, Tue 920, Wed 920, Fri 841, Mon 828, Sun 72` ✓, **0 OHLC geometry
  violations** ✓, label counts Bullish_FVG 490 / Bearish_FVG 487 / Bullish_OB 392 ✓.

### A.5.3 §C2's "agreement = 1.000" — **WRONG. This is the report's most consequential error.**

`DATA_FEASIBILITY.md` §C2 states:

> "**The decisive verification:** I recomputed the FVG columns from the OHLC with the plain 3-candle
> predicate … **agreement = 1.000 for both directions**"

and §E6 check 3 instructs: *"restrict it to a geometry unit test (`assert recomputed_3c_fvg ==
Bullish_FVG`)"*.

**I refuted this.** Measured on the same file:

| Predicate | row-level exact agreement | events (bull/bear) | same-direction overlap (bull/bear) |
|---|---|---|---|
| wick `l[i]>h[i-2]` / `h[i]<l[i-2]` | **0.638** | 490 / 487 | **69 / 46** (14.1 % / 9.4 % recall) |
| body `c[i]>o[i-2]` | 0.134 | 2,204 / 2,267 | 305 / 272 |
| body+close `c[i]>h[i-2]` | 0.388 | 1,329 / 1,374 | 201 / 165 |
| 3-bar gap `l[i]>h[i-3]` | 0.559 | 761 / 726 | 100 / 62 |
| wick **with any size threshold 0 → 10** | 0.638 → 0.777 | — | recall only ever falls |

The **counts** match exactly (490 bullish events = 490 bullish labels; 487 = 487) — which is almost
certainly what the report mistook for agreement. But the **sets overlap by only 14 % / 9 %**, and
**95 bars carry the *opposite* direction's gap** (54 bearish-labelled rows have a bullish wick gap;
41 bullish-labelled rows have a bearish one). Total overlap = 210 of 977; same-direction = 115.

**The labels are therefore NOT a deterministic function of this CSV's OHLC.** They were computed on a
different (higher-resolution or differently-resampled) series. Two corroborating facts:
`Bullish_FVG` has **128** adjacent True-True pairs and `Bearish_FVG` **119** (247 total), i.e. the
labels are **forward-filled flags**, not per-bar events; and the report's own recommendation
("never join them by exact timestamp") would have been the right instinct.

**Harm done if uncaught:** the prescribed unit test `assert recomputed_3c_fvg == Bullish_FVG`
**fails on 86 % of the rows**. Any implementer who trusts it either has to weaken the assertion
(losing the test) or believes the CSV is an oracle and tunes to it. §C2's table row "FVG labels
usable as ground truth — Only as a geometry unit-test oracle" and §G's closing bullet "the gold one
is … a series whose FVG labels are a deterministic function of its own OHLC" are both **false**.

**This correction is already recorded in `.field-guide/sources.md`** ("the gold Kaggle dataset's FVG
labels are NOT reproducible from its own OHLC") — the field guide is right and
`DATA_FEASIBILITY.md` is wrong on this point.

### A.5.4 Three smaller errors in `DATA_FEASIBILITY.md`

* **Boxes-per-image histogram is off by one.** The report lists "1 (1 file), 2 (1), 3 (3), 4 (4), 5 (5),
  6 (7), **7 (22 files)**, 8 (25) …". Measured: **{0:1, 2:1, 3:1, 4:3, 5:4, 6:5, 7:7, 8:22, 9:25,
  10:26, 11:34, 12:26, 13:22, 14:31, 15:26, 16:23, 17:10, 18:9, 19:12, 20:3, 21:2, 23:1, 24:1}**.
  There is **no** file with exactly 1 box, and every bucket from 7 up is shifted by one.
  (The *conclusions* — 1 negative image, median ≈ 11 — are right.)
* **Price range.** The report says "price range 3,969.50 – 4,751.30". That is the **Close** range
  (verified exactly); the full OHLC range is **Low 3,963.00 / High 4,755.00**.
* **Image size.** The report says "22–29 KB each"; measured **18.0–32.5 KB**.
* **F7 is refuted.** The report says "no NT model expresses slippage as 'ticks' natively — it must be
  mapped onto the fill model" and lists `help(FillModel)` as a needed check. The installed package
  already ships **`OneTickSlippageFillModel`** ("Fill model that forces exactly one tick of slippage
  for all orders") and **`PerContractFeeModel(commission: Money)`** — i.e. the doc's "1 tick
  slippage" and the "$4.5 round-turn per contract" both have native NT implementations. F7 is
  **closed by the installed package**, not open.

### A.5.5 Verified network/reachability claims

* **CBOE VXN daily file** — `curl -sL https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv`
  → final URL `https://cdn-api.cboe.com/...`, **HTTP 200**, `content-type: text/csv`, header
  `DATE,OPEN,HIGH,LOW,CLOSE`, first row `09/14/2009,26.410000,26.480000,24.810000,24.930000`,
  4,327 data rows through 11/20/2026. **Exactly as reported** ✓ — and confirmed **daily only**,
  so the "1-hour VXN change rate" feature is unsatisfiable from free data ✓.
* **SMB reachability** — `ping 192.168.1.6` 0 % loss ✓; `/dev/tcp/192.168.1.6/445` **OPEN** ✓;
  `mount | grep -Ei "cifs|smb|192.168"` → empty ✓.
* **可用 / 可入湖 marking** — `grep -rn "可入湖" research/github/dataBaseLake/` → **0 hits**;
  `可用` → **1 hit**, `README.md:80`, prose only ✓. The report's conclusion that the convention has
  no machine-readable home is correct.
* **`data_sources.json`** contains no NQ/ES/CME reference ✓.

---

## A.6 `research/nautilus/NAUTILUS_API.md` → the installed `nautilus_trader` 1.221.0

Interpreter: `/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`.
Package: `/home/da/.local/lib/python3.11/site-packages/nautilus_trader/`, version **1.221.0** ✓.

### A.6.1 The 7 recorded smoke tests — **all 7 reproduce** (2 only after adding the missing imports)

| # | Recorded | My result | Verdict |
|---|---|---|---|
| 1 | `BarSpecification(int step, BarAggregation aggregation, PriceType price_type) -> None` | identical docstring | **VERIFIED** |
| 2 | `NQ.XCME-1-MINUTE-LAST-EXTERNAL` | identical | **VERIFIED** (the *command as written* omits the imports and raises `NameError: name 'BarType' is not defined`) |
| 3 | `ValueError: Error parsing \`BarType\` from 'NQ.XCME-1-MINUTE-LAST', invalid token: '' at position 0` | byte-identical | **VERIFIED** |
| 4 | `20000.25 20000.00 100` | identical | **VERIFIED** |
| 5 | `write_data(self, data: 'list[Data \| Event] \| list[NautilusRustDataType]', start: 'int \| None' = None, end: 'int \| None' = None, skip_disjoint_check: 'bool' = False) -> 'None'` | byte-identical | **VERIFIED** |
| 6 | `customdataclass OK` | identical | **VERIFIED** |
| 7 | `ImportError: cannot import name 'Future' from 'nautilus_trader.model.instruments'` | reproduces | **VERIFIED, but the recorded output is not the real output** — see below |

**Two corrections to the smoke-test log:**

1. **Test 7's recorded output is fabricated.** The report shows a trailing
   `# available: ['CryptoFuture', 'FuturesContract', 'FuturesSpread']`. The actual exception message is
   `ImportError: cannot import name 'Future' from 'nautilus_trader.model.instruments'
   (/home/da/.local/lib/python3.11/site-packages/nautilus_trader/model/instruments/__init__.py)` —
   there is no `# available:` suffix. The *substance* is right, but the log was tidied rather than
   pasted, which is exactly the kind of thing an audit must not let slide in a document whose purpose
   is to be a verbatim record.
2. **Tests 2 and (by extension) the BarType round-trip are recorded as commands that do not run.**
   The §7 log presents `$PY -c "bt = BarType(InstrumentId.from_str('NQ.XCME'), …)"` with no import
   line. As written it raises `NameError`. The reported *outputs* are correct once the imports are
   added. `BarType.from_str(str(bt))` round-trips to `NQ.XCME-1-MINUTE-LAST-EXTERNAL` ✓ (I verified).

### A.6.2 The surrounding assertions — **VERIFIED**, with one imprecision

* `nautilus_trader.model.custom_data` → `ModuleNotFoundError` ✓; `nautilus_trader.model.custom.customdataclass` imports ✓.
* `nautilus_trader.core.data.Data` public attributes → **exactly** `['fully_qualified_name', 'is_signal', 'ts_event', 'ts_init']` ✓.
* `Bar` public attributes include `bar_type, open, high, low, close, volume, ts_event, ts_init, is_revision, is_signal, is_single_price, fully_qualified_name, from_dict, from_pyo3, from_raw` ✓.
* **No `nautilus` console script**: `nautilus_trader-*.dist-info/entry_points.txt` **does not exist**,
  and `which nautilus` → not found. `python -m nautilus_trader.backtest` / `.live` are importable ✓.
* **No YAML**: `grep -rl "yaml" …/nautilus_trader/` → **0 files** ✓. `msgspec.json.decode` is the
  config path ✓.
* **Imprecision:** §3 says `nautilus_trader.model.instruments` "exports **exactly**: `CryptoFuture`,
  `FuturesContract`, `FuturesSpread`". It actually exports **15** public classes
  (`BettingInstrument, BinaryOption, Cfd, Commodity, CryptoFuture, CryptoOption, CryptoPerpetual,
  CurrencyPair, Equity, FuturesContract, FuturesSpread, IndexInstrument, Instrument, OptionContract,
  OptionSpread, SyntheticInstrument`). Only the three *futures-family* classes are correct; the
  sentence as written is false.
* The `FuturesContract` signature block (§3) matches the installed docstring, including
  `activation_ns`/`expiration_ns` being mandatory ✓, and the `[UNVERIFIED]` marker on the assembled
  call is appropriate ✓.
* `AGENTS.md`'s claim that the doc's `BarSpecification`/`BarType` usage is "not an old API" is
  **confirmed** by execution ✓ — the field guide's correction stands.

---

# B. Cross-report contradiction table

| # | Topic | Report A claim | Report B claim | What the source supports | **Reconciled statement the project must adopt** |
|---|---|---|---|---|---|
| **B1** | **Inversion window** | `PINE_RULES.md` §B.3 R14/R15, §C-2: window is **[0,15]** bars from `fvgBar1`; no lower bound; "the 7 does not exist" | `RULE_SPEC.md` T04 **[DOC] L123**, Appendix A `INVERSION_MIN_BARS = 7`: window is **[7,15]**; A05 makes it configurable, doc-literal (7,15) "normative" | The **doc** says "7 至 15 根 K 线内" (`iFVG几个模型的讨论.txt:123`); the **code** implements only an upper bound (`pine:658`, `pine:499`) — verified by re-derivation: confirmation-candle age 0…15 | **Implement `INVERSION_WINDOW = (0, 15)` as the code-derived default and `(7, 15)` as the doc-derived variant; A/B them in phase 1. Do not hard-code 7.** The doc is self-contradictory (L123 vs L73), so neither number is "the truth" — but the code is the only executable evidence. |
| **B2** | **FVG minimum-gap filter** | `PINE_RULES.md` §B.1 R6 / §C-4: **absent**; "no ATR anywhere in the file"; "the doc's rule must be re-derived from the doc, not from code" | `RULE_SPEC.md` T02 **[DOC] L121**: `gap_size > 0.25 * ATR(14)`, with `MIN_GAP_ATR_MULT = 0.25` in Appendix A | Doc **L121** and **L280** state it; the **code has zero ATR calls** (verified: `grep -ci atr` = 0) | **Implement the ATR floor as a *doc-derived* flag, default OFF for the code-derived baseline and ON for the doc-derived variant. Never describe either as "the" rule.** The replica's README says the original runs "the most sensitive setting by default", so the doc's floor is likely NOT the original's default either. |
| **B3** | **Liquidity sweep: mandatory or optional?** | `PINE_RULES.md` §B.2 R12 / §C-21: `onlyShowSweptIFVG = input.bool(false, …)` (`pine:11`) — **OFF by default**, an optional gate | `RULE_SPEC.md` §1.4 Step 2 / T-row: the sweep is **前置条件 A** — a **mandatory precondition** of the rule engine | The **doc** makes it mandatory; the **code** makes it optional and off. Both are right about their own source | **The doc's step-2 sweep is mandatory.** Implement it as a hard gate per the doc, and record the *code's* optional variant as an A/B arm. Note: the code's sweep object is a 3-bar HTF fractal; the doc's is an EQH/EQL/PDH/PDL pierce — **these are not the same predicate** (see B7). |
| **B4** | **Session / killzone windows** | `PINE_RULES.md` §B.4 R20 / §C-13: sessions exist **only as an alert filter** (`pine:123-126`, sole consumer `pine:497`); defaults `0930-1600` enabled, `2000-0000` / `0200-0500` disabled — **not** a signal gate | `RULE_SPEC.md` Step 1 / T05, T06 **[DOC] L115**: the state machine is **only activated** in `09:30–11:30` and `13:30–15:30` ET — a hard gate | Doc **L115** says `仅在…激活` (only activated in); the code's `0930-1600` is a **wider** window and is **alert-only** | **Adopt the doc's two killzones (09:30–11:30, 13:30–15:30 ET, endpoint-inclusive, `America/New_York` with DST) as a hard signal gate.** Do not adopt the code's session logic at all — it is a notification window, and it is wider. |
| **B5** | **The "A/A+ only" phase-1 gate** | `PINE_RULES.md` §B.3 R18 / §C-10: **no scoring, no grades anywhere in the code**; the replica author "left out the grade box" because "the grading is mechanical" | `RULE_SPEC.md` T32/T34, §1.7: a concrete rubric (`+2` SMT, `+1` no-OB, `+1` ≥2R target, `+1` IoU, `+1` normal regime; A+ ≥5, A = 4, B = 3, C ≤2), flagged `[UNSPECIFIED]` A09/A10 with the rubric as a **proposal** | **Neither source defines A/A+.** The only implementation-bearing text is `research/github/IFVG-Ultimate-Dodgy/README.md:18`: *"Setup grade box — left out entirely. Dodgy himself has said the grading is mechanical, meaning there's a fixed set of rules generating the grade that doesn't imply actual grade."* | **THE PHASE-1 GATE IS UNIMPLEMENTABLE AS WRITTEN.** See §C.1 for the substitute. Until a rubric is adopted, the phase-1 backtest **must report every rule candidate** with a *transparent, reproducible* set of binary flags, and the "A/A+ only" subset must be defined as a **declared function of those flags** — not as an inherited grade. |
| **B6** | **Vision input size and background** | `VISION_AUDIT.md` §B: render **white, 640×640**, ~90 bars; "delete the 224×224 and 纯黑背景 requirements from the doc" | `RULE_SPEC.md` T22 **[DOC] L137** + A20: the doc mandates 224×224 and black background; A20 *proposes* rendering in the model's style but leaves the tag `[DOC]` | Doc **L137/L279** says 224×224 black; the model card says 640×640 white (`README.md:51,55`) and the training images are verifiably white 640×640 (my histogram: 269,643 px of `#FFFFFF`) | **Render 640×640, white, TradingView-style. The doc's 224×224/black requirement is superseded** — the shipped weights are the only executable evidence of what the layer must look like. Record the style version next to every cached feature. |
| **B7** | **What the "sweep" actually is** | `PINE_RULES.md` §B.2 R10: the sweep target is a **3-bar fractal on HTF swing highs/lows**, strict pierce, **single-shot consumption** (`pine:560-575`, `pine:619-630`) | `RULE_SPEC.md` Step 2 / T-row: the sweep is **NQ 刺穿前期波段高点/低点 (EQH/EQL/PDH/PDL)** — same-timeframe level clusters plus previous-day and session levels | The doc's object is richer than the code's; the code has **no** PDH/PDL/EQH/EQL at all (`grep -niE "PDH|PDL|EQH|EQL" → no match`) | **Use the doc's object (EQH/EQL/PDH/PDL), computed from 1-minute bars with an exchange calendar**, and treat the code's HTF-fractal sweep as a *different, weaker* feature (a confluent one, not the gate). This is a doc-derived rule; label it as such. |
| **B8** | **Vision IoU definition and threshold** | `RULE_SPEC.md` A32: resolve I06 as **2-D pixel-space IoU**; keep `VISION_IOU_THRESHOLD = 0.75` | `VISION_AUDIT.md` §C.2: D1 (1-D vs gap) scores **0.00** for a perfect match; D2 (2-D vs 3-bar rect) is capped at **≈0.26**; D3/D4 (vs the **third candle's body** + bar-index selector) score **1.00** and are reachable | Both are wrong as written; the model's own ground truth shows the boxes wrap **candle bodies** (my measurement: median interior candle fraction **1.000**, 0 % >80 % empty) and are therefore **disjoint from the geometric gap** | **Adopt `VISION_AUDIT.md`'s D4 contract** (x = bar-index selector, y = 1-D vertical IoU against the third candle's body, plus class match), **calibrate τ ≈ 0.5 on the Kaggle test split**, and **delete `VISION_IOU_THRESHOLD = 0.75`** from `RULE_SPEC.md` Appendix A. The 0.75 threshold is unreachable on two independent grounds. |
| **B9** | **Stop placement** | `PINE_RULES.md` §B.5 R22 / §C-16: stop = the **extreme of the FVG→confirmation window** (`pine:293,462`); the swing origin is the **break-even**, not the stop | `RULE_SPEC.md` A15: stop = the **swing extreme** over FVG-first-candle → confirmation bar, ±1 tick | The code says the first; the doc (L13: `止损通常设在近期的波段高低点外侧`) says the second. The code's *scan window* is close to the doc's *window*, but the **reference level differs** | **Decide and document one.** Recommended: the **code's** window extreme (`pine:293,462`) because it is computable from data the engine already holds and it is the only definition with a verified implementation; the swing origin stays as the break-even. Note this changes R and therefore every PF number. |
| **B10** | **Entry price** | `PINE_RULES.md` §D.1: the code uses `close[1]` (the confirmation candle's close) — **not fillable**; the honest port fills at `open(X+1)`. Config flag, report both | `RULE_SPEC.md` A14: **market order at the close of the confirmation candle** (`entry = close[k]`), with a retest variant | The code's `lvl = close[1]` (`pine:441`) is a *drawing* price in an `indicator()` with **no fills at all** | **Fill at the next bar's open (`open(X+1)`), and report the code's `close(X-1)` variant as a sensitivity.** The Pine has no order semantics, so "the code's entry" is a drawing artefact, not an executable rule. |
| **B11** | **Gold Kaggle CSV as an FVG oracle** | `DATA_FEASIBILITY.md` §C2: labels are a **deterministic function of the OHLC** ("agreement = 1.000"); usable as a **geometry unit-test oracle** | `.field-guide/sources.md` (and my measurement): labels are **not** reproducible; only 14 %/9 % same-direction overlap, 95 bars opposite-direction, labels forward-filled | **The field guide is right; `DATA_FEASIBILITY.md` §C2 is wrong** (see §A.5.3) | **Demote the gold CSV to "a plausible-rate smoke test only".** Delete the prescribed assertion `assert recomputed_3c_fvg == Bullish_FVG` — it fails on 86 % of rows. Never join the label columns to bars by timestamp. |
| **B12** | **Qlib / AlphaGPT rejection reason** | `RULE_SPEC.md` §2.7 / INV7: the doc's reason is "cross-sectional stock-pool ranking computing IC/RankIC" | `ML_REUSE.md` §B.3: AlphaGPT has **no IC/RankIC at all** (0 grep hits); the real reason is its hard-wired crypto-meme feature set. Qlib *does* use IC/RankIC | Verified: AlphaGPT 0 hits; Qlib has `get_rank_ic`, `score_ic.py`, `analysis_model_performance.py:295` | **Keep the decision, fix the reason.** Neither framework is the signal source (INV7 stands), but the doc's stated rationale is factually wrong about AlphaGPT and accidentally right about Qlib. Do not repeat "AlphaGPT computes IC" in any write-up. |

---

# C. Gaps the reports missed

## C.1 The grade system (A+/A/B/C) does not exist in **any** artifact — **the phase-1 gate may be unimplementable as written**

**Finding.** I searched every artifact in the repo:

| Source | Grade system? |
|---|---|
| `iFVG几个模型的讨论.txt` (the prose) | Only 3 mentions: L45 `多重共振评分系统（A+ 至 C 级）`, L107 `仅接受 A+ 级带 SMT 背离信号`, L170 `Checklist 过滤（只做 A/A+ 级）`. **No thresholds, no point values, no rubric.** |
| `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` | **Zero.** `grep -niE "score\|grade\|checklist\|a+"` → 0 hits. The only score-like artefact is the cosmetic `+`/`-` and a volume dot in the label text (`pine:453-454`). |
| `research/github/IFVG-Ultimate-Dodgy/README.md:18` | *"Setup grade box — left out entirely. Dodgy himself has said the grading is mechanical, meaning there's a fixed set of rules generating the grade that doesn't imply actual grade."* |
| Every other artifact (qlib, AlphaGPT, xauusd, ICT corpus, Kaggle, lake) | **Zero.** |
| `RULE_SPEC.md` §1.7 | A **proposal**, explicitly tagged `[UNSPECIFIED]` A09/A10, not evidence. |

**So the phase-1 acceptance gate (`iFVG几个模型的讨论.txt:170`: *Checklist 过滤（只做 A/A+ 级）* → **PF > 1.25**) has no implementable definition of its traded population.**

**Consequence, stated loudly:** a phase-1 backtest that filters on "A/A+" is filtering on a number
nobody has ever computed. Whichever rubric an implementer invents will *define* the result. A PF of
1.30 on an invented rubric is not evidence about the strategy; it is evidence about the rubric. And
because the rubric contains the doc's own `+2` SMT weight, an A/A+ filter is **implicitly an SMT
filter** — so "phase 1 is rule-only" is not even true of the doc's own gate.

**Concrete, defensible substitute — adopt this, and state it in `RULE_SPEC.md` as a supersession of
A09/A10:**

> **Phase 1 trades the *intersection* of the doc's five named checklist conditions, as five
> independently recorded booleans — no points, no grades.**
>
> `c1` sweep of an EQH/EQL/PDH/PDL level (doc L118)
> `c2` SMT divergence present (doc L119) — **recorded, not required**
> `c3` no uncleared opposing OB / tight equal-high-low in the entry direction (doc L125)
> `c4` a liquidity target ≥ 2R away exists (doc L126)
> `c5` the gap exceeded 0.25 × ATR(14) (doc L121)
>
> **Primary phase-1 population = `c1 ∧ c5` ∧ (doc-literal 7–15 window)** — the two conditions the
> doc states as *preconditions* (前置条件 A/B) plus the doc's only quantitative filter. Report the
> full truth table of all 5 flags × outcome, so the marginal contribution of each is visible.
> **A/A+ becomes a *reported label*, not a filter:** define `A+ ≡ c1 ∧ c2 ∧ c4`, `A ≡ c1 ∧ c4`,
> `B ≡ c1`, `C ≡ ¬c1` **as a post-hoc labelling of every logged candidate**, and report PF for
> each label. The phase-1 gate then has a single, unambiguous, reproducible population (`c1 ∧ c5`)
> and the grades become a *result* rather than an *input*.

**Why this is defensible:** it uses only conditions the doc states; it introduces no invented points;
it keeps every candidate in the log (INV4); and it converts the unverifiable grade into a
**reportable stratifier**, so the doc's own claim that A+ trades better than A becomes
*falsifiable* instead of *assumed*.

**What it costs:** the phase-1 population is smaller than the doc's (no SMT gate, so no filter on
SMT) → fewer trades → the sample-size problem in §D.3 becomes binding. And `c3` is uncomputable
without an OB detector (see §C.2), so `c3` must be recorded as **not-implemented** and excluded from
the label definition.

## C.2 The "≥ 2R liquidity target" rule — computable, but only after you redefine the target universe

**Findings.**

* No artifact computes liquidity pools. The Pine has **no take-profit logic at all** —
  `ict_CreateRR` (`pine:313-325`) draws horizontal *lines*; `grep -niE "draw on liquidity|liquidity pool"`
  across the Pine, the xauusd corpus and the HF artifacts → **no hits**. The README says the author
  *"went with RR based targets instead of nearest liquidity"* and that the original's dev "has said
  in his own videos that nearest-liquidity TP is too mechanical and in real scenarios he uses
  discretion".
* The doc's target vocabulary (`iFVG几个模型的讨论.txt:126`) is **EQH/EQL, untouched session highs/lows,
  or one-sided liquidity (LRLR)**. The first two are **computable from 1-minute bars alone**:
  PDH/PDL = previous RTH day's high/low (needs an exchange calendar for session boundaries);
  session highs/lows = per-`session_id` extremes; EQH/EQL = clusters of swing pivots at
  (approximately) equal prices — computable, but the **cluster tolerance is undefined**.
  **LRLR (single-sided liquidity, i.e. where stops are stacked) is NOT computable** — it requires
  an order-book or a stop-density model we do not have.
* The **ICT corpus does supply a computable target convention**: its output's
  `Draw on Liquidity (Target)` is the **opposite swing extreme of the stated dealing range** — I
  verified this on **1,447/1,447** VALID rows (target == the far swing extreme, exactly).

**Reconciled statement:** the ≥2R filter is implementable as
`∃ a liquidity level L on the target side with |L − entry| ≥ 2R`, where the level universe is
**{PDH, PDL, session highs/lows, unmitigated swing pivots}** (the ICT corpus's "opposite swing
extreme" is a defensible *proxy* for "unmitigated swing pivot"). LRLR must be **dropped** from the
implementation and recorded as out-of-scope. The 2R distance itself is computable once the stop is
decided (see B9) — note the ≥2R filter is **coupled to the stop choice**, so changing the stop
definition changes the traded population.

## C.3 The VXN regime series: daily vs intraday, and the "1-hour change rate"

**Findings.**

* **Daily VXN is available and verified reachable** — I re-fetched
  `https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv` (HTTP 200 → 307 →
  `cdn-api.cboe.com`, `text/csv`, 4,327 rows, 2009-09-14 → 2026-11-20). **Daily only.**
* The doc's own pipeline builds **daily** bars (`iFVG几个模型的讨论.txt:260`, `interval="1d"`), while
  the ML feature list requires "当前 VXN 绝对值及 **1 小时变化率**" (L146). **The feature is
  unsatisfiable from the doc's own data.** `RULE_SPEC.md` A18 says "do not fabricate" — correct, and
  `DATA_FEASIBILITY.md` A8 confirms CBOE's free file is daily-only.
* The **1-hour change rate is not the only inconsistency**: the doc's `shift(1).bfill()` also
  **back-fills from the future** at the head of the series, and `bfill()` across a long weekend
  silently carries a stale regime forward with no marker — both flagged in `DATA_FEASIBILITY.md` §E4.1
  and `RULE_SPEC.md` INV6. Both reports are right.
* **Not mentioned by either report:** the regime is used as a **gate**, not only a feature — doc L107
  (low vol → A+ only) and L109 (high vol → halve risk, bigger ATR gap). But the regime is a
  **daily** series while the gate is applied **intraday**, so a single day's regime governs the whole
  session. That is defensible (it is knowable at the open) but it means the "low-vol → A+ only" gate
  reintroduces the **undefined grade** of §C.1 into the phase-1 population, in a way that is even less
  reproducible. Nothing in the reports notes this.

**Reconciled statement:** the phase-1 gate must **drop the `1 小时变化率` feature entirely** (per
A18) and use **only the lagged daily VXN level** to bin the regime. Apply the regime as a
**reporting stratifier**, not a gate, in phase 1 — because its doc-stated policy depends on the
undefined grade. Fix the lag: use the previous trading day's close with a **no-backfill** rule
(drop the first observation rather than `bfill()` from the future), and mark every forward-filled
day in the feature table.

## C.4 The contract roll rule for NQ/ES continuous futures

**Findings.**

* `research/github/dataBaseLake/03_governed_lake/v2_parquet_lake/manifest/manifest.json` names the
  series *"E-mini Nasdaq 100 **Continuous** Futures"* and *"E-mini S&P 500 **Continuous** Futures"* —
  but **no artifact in the repo states the roll rule, the roll date, or the back-adjustment method.**
  The databank MANIFEST indexes only **daily** CME bars (1,695 each) — so even the daily series' roll
  handling is undocumented.
* The doc's own sample script (`iFVG几个模型的讨论.txt:234`) "filters roll noise by keeping the
  highest-volume contract per timestamp" — `groupby(level=0).first()` — which is (a) the wrong
  pandas level (§B2 of `RULE_SPEC.md`) and (b) **not back-adjusted**, so it produces price gaps at
  every roll. `RULE_SPEC.md` B6 says exactly this.
* `DATA_FEASIBILITY.md` §E1 gives the right threat model (a 50–150 point synthetic jump at a roll
  *is* a synthetic sweep and *does* form a synthetic FVG) and the right detector
  (`|open[t] − close[t−1]| > k·ATR(14)` with `k ≈ 3`).
* **Not mentioned by either report:** a roll gap is not the only artefact. The doc's rule step 2
  fires on **any** pierce of a prior swing high/low — a roll gap that gaps *down* through a prior
  swing **low** is a "bullish sweep" and would fire the entire rule chain. So the roll filter is not
  a nice-to-have; **without it, a single roll can manufacture a setup with a stop and a 2R target
  that the backtest then scores.**

**Reconciled statement:** the roll rule is a **precondition of phase 1**, not a data-quality nicety.
Minimum viable form: (i) a per-bar `contract_id` where the source provides one; (ii) where it does
not, a statistical roll detector (gap > k·ATR(14) with k ≈ 3) whose flagged bars are **excluded
from rule evaluation** and recorded as `roll_boundary`, never as trades; (iii) a single executable
`roll_boundary(ts, contract_id) -> bool` used by both the bar filter and the test; (iv) ATR, gap
size, swing levels and the R-multiple all computed in **one** price basis (never mixing adjusted and
raw).

## C.5 PDH/PDL and EQH/EQL — computable from 1-minute bars alone?

**Findings.** Both are computable, but neither is free, and one of them needs an object the project
does not have.

* **PDH/PDL** — previous *trading day's* high/low. From 1-minute bars this requires (i) an **exchange
  calendar** to determine the RTH session boundary (the CME Globex day is 18:00 ET → 17:00 ET next
  day, which is *not* a calendar day), and (ii) a decision on whether "previous day" means the
  previous *Globex* day or the previous *RTH* day. The doc does not say. `DATA_FEASIBILITY.md` §E2
  and §E3 correctly identify both the session-break problem and the DST problem
  (`23:00 UTC` under EST / `22:00 UTC` under EDT). **Computable, but the calendar must be pinned.**
* **EQH/EQL** — "equal highs/lows" are *clusters of pivot levels at the same price*. From 1-minute
  bars this is computable (find swing pivots, cluster them by price within a tolerance), but the
  **tolerance is undefined** in every artifact: the doc says `刺穿` (pierce) at L118, which is about
  the *sweep*, not the *clustering*; `RULE_SPEC.md` A07 proposes a **strict pierce** for the sweep and
  defers the equality question; `PINE_RULES.md` R10 finds **no equality detection at all** — the
  code's sweep levels are single HTF fractal pivots, consumed once. **Computable only after the
  tolerance is chosen**, and the choice changes which setups exist.
* **The doc's third object is not computable at all**: "紧贴的等高/等低点" (tightly adjacent equal
  highs/lows) in the checklist (L125) needs the same clustering, and "未清理的反向订单块 (OB)"
  (L125) needs **an order-block detector that exists nowhere** — `grep -rliE "order_?block"` over the
  Pine and over `qlib/qlib` → **no hits**; only the xauusd corpus has one, and its OB detector is
  precisely the one with the look-ahead defect (`ML_REUSE.md` §A.4). **Checklist item (a) is
  unimplementable as written.**
* **Neither report states this.** `RULE_SPEC.md` §1.4 Step 5 flags the proximity tolerance as A09
  but stops at "undefined"; neither report observes that **the OB half of the checklist has no
  detector in any artifact**, or that the ICT corpus's 4-gate structure (`VALID`/`INVALID`) is the
  only concrete checklist spec in existence — and its Gate 2 is *"sweep asserted | SMT confirmed or
  absent"*, i.e. **no OB gate at all**.

**Reconciled statement:** PDH/PDL is computable from 1m bars with a pinned Globex/RTH session
calendar; EQH/EQL is computable after an explicit, documented price-tolerance constant; the
checklist's **OB clause is not computable** and must be dropped from phase 1, recorded as
"not implemented", with the ICT corpus's 4-gate table used as the reference checklist instead.

---

# D. Verdict

## D.1 Is the four-layer design, as written, implementable with the evidence we have?

**Partially — and less than the reports collectively suggest.**

* **Layer 1 (deterministic rule engine) — YES, implementable.** Every mechanical predicate is
  pinned by an executable artifact or by the doc: 3-candle FVG geometry (`pine:354`, doc L121),
  body-close inversion through the far edge (`pine:437`, doc L123), stop at the window extreme
  (`pine:293,462`), entry at the next bar's open, fixed 1:2 RR. The contested parts (inversion
  window, ATR floor, sweep object) are **A/B-able** because both variants are cheap to implement
  and to compare. This layer can be written and unit-tested in days.
* **Layer 2 (vision cross-validation) — YES, but only after a re-specification.** The shipped
  weights demand a white 640×640 render and a **candle-body** target; the doc's 224×224 black
  render and the `IoU > 0.75` gate are unreachable. `VISION_AUDIT.md`'s D4 contract fixes it. The
  layer is a **feature generator and a sanity check**, not the noise filter the doc claims.
* **Layer 3 (meta-labeling) — YES, in principle**, on the doc's binary label; but it depends on
  layer 1 emitting a complete candidate log, and its feature list needs the **1-hour VXN change
  rate**, which is unsatisfiable from free data (drop it).
* **Layer 4 (RL position management) — NOT YET.** The RL cannot be built or evaluated until layers
  1–3 produce a trustworthy candidate log, and its action space still has no file path (A28) and two
  undefined grids (A29). Its state includes **order-book imbalance** (doc L151), for which **no data
  exists in this repo at all**.
* **The phase-1 gate itself is NOT implementable as written**, because "A/A+ only" has no
  implementable definition (§C.1). It becomes implementable the moment the substitute in §C.1 is
  adopted.

**The binding constraint is not the design — it is two data facts and one definition:**
(1) no reachable NQ/ES 1-minute pair with a documented roll rule, (2) no intraday VXN, and
(3) no definition of A/A+.

## D.2 The three findings that most change the plan

1. **`DATA_FEASIBILITY.md` §C2's "agreement = 1.000" is false — the gold Kaggle CSV is not an FVG
   oracle.** Measured: the 3-candle wick gap and the label columns have the *same count* (490 /
   487) but only **14 % / 9 %** same-direction row overlap, with **95 bars carrying the opposite
   direction's gap**; the labels are forward-filled booleans. The prescribed test
   `assert recomputed_3c_fvg == Bullish_FVG` **fails on 86 % of rows**. Any phase-1 geometry
   validation built on this CSV is circular and will be tuned to a wrong oracle. *(§A.5.3)*
2. **The vision layer's `IoU > 0.75` gate is unreachable — not because of resolution, but because
   of semantics.** The model's annotations wrap the **third candle's body** (median interior
   candle-colour fraction **1.000**, 0 % >80 % empty), and the FVG *gap* is the empty space between
   candle 1's wick and candle 3's wick — so a **perfect** detection scores **IoU = 0.00** against
   the rule zone. Independently, a 5.5 px-wide box tolerates <1 px of misalignment at 640×640 and
   <0.25 px at 224×224. **The layer must be re-specified as a bar-index + candle-body cross-check,
   and `VISION_IOU_THRESHOLD = 0.75` must be deleted.** *(§A.3.2, §B8)*
3. **The A+/A/B/C grade exists in no artifact, so the phase-1 acceptance gate has no defined traded
   population.** The only implementation-bearing text is the replica README saying the grading was
   "left out entirely" and is "mechanical". Implement the five named checklist conditions as
   booleans and **report** the grades instead of **filtering** on them — otherwise the PF > 1.25
   result is a property of an invented rubric. *(§C.1)*

## D.3 The single highest-risk assumption still unverified

**That the rule engine as specified produces a positive-expectancy signal at all.** Everything else
is an engineering or data-acquisition problem; this is the assumption that can make the entire
project a no-go, and it is unverified.

It is high-risk because **the strongest evidence available points the other way**: the replica's
author — who reverse-engineered the closed-source original from the author's own videos, and who
built the whole thing to be faithful — concluded in
`research/github/IFVG-Ultimate-Dodgy/README.md`:

> *"**So does the strategy have any value?** NO"*
> *"This indicator is constantly scanning for setups, and that's a bad thing. Price is always forming
> FVGs … given enough time, that FVG will always become an IFVG."*
> *"The only thing his model does to control for this is require the FVG to invert within 7–15
> candles, which cuts down the number of setups shown, but **doesn't meaningfully increase how often
> they actually work out**."*
> *"He isn't consistent about where his stop actually is … not based on a fixed rule stated up front."*

And the doc's own phase-1 rule (L170) says a negative pure-rule result means *the rule reproduction is
wrong*. Those two statements are in direct tension, and **only a measurement can resolve it.**

Compounding this: the sample size needed to resolve it is **not** small. At 1:2 RR, to distinguish
zero expectancy from +0.10 R/trade with a per-trade σ ≈ 1.25 R, you need roughly
`n ≈ (1.96 × 1.25 / 0.10)² ≈ 600` trades per arm — i.e. **~1 year of NQ 1-minute data at 2
candidates/day, or ~4 months at 7/day**. And the cost model is not pinned: the doc's "$4.5
round-turn" plus 1–2 ticks of NQ slippage is **$14.50–$24.50 all-in** (`DATA_FEASIBILITY.md` A5/E8),
which is 3.6 %–6.1 % of a 20-point stop — enough to turn PF 1.30 into PF 1.22. **A phase-1 run on
fewer than ~600 trades cannot settle the question and must not be reported as if it could.**

## D.4 The minimum credible phase-1 experiment

**E-1 — a rule-engine falsification test on the only real OHLCV series that exists in this repo.**

| | |
|---|---|
| **Inputs** | `research/kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv` — 4,502 bars, XAU/USD 15-minute, 2026-07-14 → 2026-09-22, OHLCV only. **No other price data for any index future is physically present in this repo** (the databank's `catalog/`, `commodities/`, `crypto/`, `fx/`, `metals/` trees are all empty; `v2_parquet_lake/us_futures/` holds only a 0-byte `.gitkeep`). |
| **What to build** | The **code-derived** core only, as a pure function of bars: 3-candle wick FVG → inversion confirmed by a **body close strictly through the far edge** → entry at the **next bar's open** → stop at the FVG→confirmation **window extreme** → fixed **1:2** RR target → next-bar-open fill. Log **every** candidate with its outcome (INV4). |
| **Arms (A/B, cheap and pre-registered)** | (a) inversion window **[0,15]** (code) vs **[7,15]** (doc); (b) ATR floor **off** (code) vs **> 0.25·ATR(14)** (doc); (c) entry at `open(X+1)` (honest) vs `close(X-1)` (code's drawing price); (d) sweep gate **on** (doc) vs **off** (code). Plus the phase-1 population flag `c1 ∧ c5` from §C.1. |
| **Sample size** | The whole file: 4,502 bars (15-minute, XAU/USD) covering ~47 days of trading over 70 calendar days. I ran a reference implementation of the code-derived rule over it: **571** iFVG candidates under the code arm (window [0,15], no ATR floor), **495** under the doc window [7,15], **255** / **224** with the 0.25×ATR floor added. Raw 3-candle wick FVG events: 977 (490 bullish / 487 bearish). **So the sample is hundreds of candidates, not tens** — enough to falsify a broken rule engine, **not** enough to validate an edge. Say so in the report. |
| **Metrics** | n candidates; win rate; **expectancy in R**; profit factor **cost-free**; **break-even round-trip cost per trade in R** (the instrument-agnostic number); max consecutive losses; the full 2×2×2×2 arm table. Report the arm table, not a single number. |
| **Pass / fail** | **PASS** if at least one pre-registered arm has **expectancy > 0** and **PF > 1.25 cost-free**, **and** the sign is stable across the entry-assumption arm (c) — otherwise the result is an artefact of the fill model. **FAIL** if every arm has expectancy ≤ 0: the rule reproduction is wrong (doc L170) and **phase 2 must not start**. |
| **Cost** | ≤ 1 day: the state machine is ~200 lines of pure Python, and the only dependency is pandas. |
| **What it does NOT prove** | NQ, 1-minute, the SMT leg, the VXN regime, the vision layer, the cost model, and any claim about profitability at scale. **It proves only that the rule engine is implemented without look-ahead and that the contested parameters have a stable sign.** |
| **Then, and only then, E-2** | Mount the lake (`DATA_FEASIBILITY.md` §B2 step 4) and run the real thing: NQ+ES 1-minute, **≥ 600 trades per arm**, all-in costs of **$14.50–$24.50** (not $4.50), PF reported at **0, 1 and 2 ticks**, and a **95 % CI on expectancy**. **The E-2 result is the one that decides whether this project continues.** |

*Why this is the minimum credible experiment:* it is the only test that can be run **today** on data
that physically exists here, it is falsifiable, it is cheap, and it attacks the exact risk in D.3 —
but it is explicitly a *rule-engine* test, not an edge test. Quoting a PF from it as evidence about
NQ would be the same category of error as `DATA_FEASIBILITY.md` §C2.

---

## Appendix — reproduction commands

All executed on this host, 2026-11-22, with
`PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`.

```bash
# PINE (all line references in §A.1)
awk 'NR>=350 && NR<=360 {printf "%d\t%s\n", NR, $0}' research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine
awk 'NR>=433 && NR<=460 {printf "%d\t%s\n", NR, $0}' research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine
awk 'NR>=495 && NR<=530 {printf "%d\t%s\n", NR, $0}' research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine
awk 'NR>=655 && NR<=672 {printf "%d\t%s\n", NR, $0}' research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine
grep -ci atr|smt|score|grade|checklist research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine   # 0 0 0 0 0
grep -oE 'ta\.[a-zA-Z_]+' research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine | sort | uniq -c
grep -c 'strategy\.' research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine                        # 0

# DOC line citations (§A.2)
awk 'NR>=105 && NR<=130 {printf "%d\t%s\n", NR, $0}' iFVG几个模型的讨论.txt
awk 'NR>=155 && NR<=180 {printf "%d\t%s\n", NR, $0}' iFVG几个模型的讨论.txt
awk 'NR>=255 && NR<=283 {printf "%d\t%s\n", NR, $0}' iFVG几个模型的讨论.txt
grep -n "0\.58" iFVG几个模型的讨论.txt            # no match -> 0.58 is SVG-only

# VXN binning (I05)
$PY -c "import pandas as pd; print(pd.cut([18.0],bins=[0,18,28,200],labels=[0,1,2]).astype(int)[0])"   # 0
$PY -c "import pandas as pd; print(pd.cut([28.0],bins=[0,18,28,200],labels=[0,1,2]).astype(int)[0])"   # 1  <-- report says 2

# Kaggle gold CSV (§A.5.3)
$PY - <<'EOF'
import pandas as pd, numpy as np
d=pd.read_csv('research/kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv')
h,l,o,c=[d[k].values.astype(float) for k in ('High','Low','Open','Close')]
lb=d.Bullish_FVG.values.astype(bool); lr=d.Bearish_FVG.values.astype(bool)
b=np.zeros(len(d),bool); r=np.zeros(len(d),bool)
b[2:]=l[2:]>h[:-2]; r[2:]=h[2:]<l[:-2]
print('events',b.sum(),r.sum(),'labels',lb.sum(),lr.sum())
print('same-dir overlap',(b&lb).sum(),(r&lr).sum())
print('cross-dir',(b&lr).sum(),(r&lb).sum())
print('exact agreement',(((b==lb)&(r==lr)).mean()))
EOF

# Vision boxes hug candle bodies (§A.3.2)
magick <image>.jpg -depth 8 rgb:- | <numpy> ; per-label box: fraction of interior pixels that are
teal (g-r>25) or near-black (max<110) vs background (min>232)

# Vision bar pitch (§A.3.3)
sorted label x-centres -> consecutive gaps: 7 px is the modal gap; 640/7 ~ 91 bars

# Checkpoint metadata (§A.3.1)
zipfile -> best/data.pkl -> pickle.Unpickler subclass with stubbed find_class/persistent_load

# Qlib (§A.4.3)
grep -rniE "rankic|information coefficient" --include=*.py research/github/qlib/qlib
grep -ni "short" research/github/qlib/qlib/backtest/position.py        # 0 hits
awk 'NR>=74 && NR<=90 {printf "%d\t%s\n", NR, $0}' research/github/qlib/qlib/contrib/strategy/signal_strategy.py

# ICT corpus (§A.4.4 / §A.4.5)
$PY - <<'EOF'
import pandas as pd, re
df=pd.read_parquet('research/huggingface/ict-6000-mentorship-master/data/train-00000-of-00001.parquet')
i=df['instruction'].astype(str); o=df['output'].astype(str); m=i.str.startswith('Audit this')
A=pd.DataFrame({'i':i[m].values,'o':o[m].values})
smt=A['i'].str.extract(r'SMT Divergence:\s*([^|\n]+)')[0].str.lower()
verd=A['o'].map(lambda x: re.findall(r'\b(VALID|INVALID)\b',x)[-1])
print(pd.crosstab(smt.str.contains('not present')|smt.str.contains('absent'), verd))
EOF

# Lake manifests (§A.5.1)
grep -n "CME-1-MINUTE" research/github/dataBaseLake/03_governed_lake/nautilus_databank/MANIFEST.md   # no match
python3 -c "import json;print(json.load(open('research/github/dataBaseLake/03_governed_lake/v2_parquet_lake/manifest/manifest.json'))['catalog']['us_futures']['symbols']['NQ'])"

# Nautilus (§A.6)
$PY -c "import inspect;from nautilus_trader.persistence.catalog import ParquetDataCatalog;print(inspect.signature(ParquetDataCatalog.write_data))"
$PY -c "from nautilus_trader.model.instruments import Future"            # ImportError
$PY -c "import nautilus_trader.model.custom_data"                       # ModuleNotFoundError
ls /home/da/.local/lib/python3.11/site-packages/nautilus_trader-*.dist-info/entry_points.txt   # absent
grep -rl yaml /home/da/.local/lib/python3.11/site-packages/nautilus_trader/                      # 0 files

# NT fill/fee models (§A.5.4, closes DATA_FEASIBILITY F7)
$PY -c "import nautilus_trader.backtest.models as m;print([n for n in dir(m) if n.endswith('Model')])"
# -> includes OneTickSlippageFillModel and PerContractFeeModel
```

### D.4.1 Reproduction of the E-1 candidate counts

```python
# reference implementation of the code-derived rule, run on the only real OHLCV series in-repo
import pandas as pd, numpy as np
d = pd.read_csv('research/kaggle/gold-xauusd-smc-trading-data/XAUUSD_15M_SMC_Data.csv')
h, l, o, c = [d[k].values.astype(float) for k in ('High', 'Low', 'Open', 'Close')]
n = len(d)
pc = np.concatenate(([np.nan], c[:-1]))
tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
atr = pd.Series(tr).rolling(14).mean().values

def run(minbars, maxbars, use_atr, mult=0.25):
    out = []
    for i in range(2, n):
        # bullish FVG (support) inverts to resistance -> SHORT
        if l[i] > h[i - 2] and (not use_atr or (l[i] - h[i - 2]) > mult * atr[i]):
            bot = h[i - 2]
            for k in range(i, min(i + maxbars + 1, n)):
                if k - i < minbars: continue
                if c[k] < bot: out.append(('short', i, k)); break
        # bearish FVG (resistance) inverts to support -> LONG
        if h[i] < l[i - 2] and (not use_atr or (l[i - 2] - h[i]) > mult * atr[i]):
            top = l[i - 2]
            for k in range(i, min(i + maxbars + 1, n)):
                if k - i < minbars: continue
                if c[k] > top: out.append(('long', i, k)); break
    return out

for label, (mn, mx, ua) in {
    'CODE window[0,15] no ATR':   (0, 15, False),
    'DOC  window[7,15] no ATR':   (7, 15, False),
    'CODE window[0,15] +0.25ATR': (0, 15, True),
    'DOC  window[7,15] +0.25ATR': (7, 15, True),
}.items():
    cand = run(mn, mx, ua)
    L = sum(1 for x in cand if x[0] == 'long')
    print(f'{label:26s}: {len(cand):4d} candidates (long {L}, short {len(cand)-L})')
```

```
CODE window[0,15] no ATR  :   571  (long 296, short 275)
DOC  window[7,15] no ATR  :   495  (long 254, short 241)
CODE window[0,15] +0.25ATR:   255  (long 125, short 130)
DOC  window[7,15] +0.25ATR:   224  (long 114, short 110)
raw 3-candle wick FVG events: 977 (bullish 490, bearish 487)
```

**Sanity cross-check on the NQ candidate rate.** The Kaggle training corpus is NQ 1-minute/5-minute
charts with 3,650 FVG annotations over 295 images ≈ 90 bars ⇒ **0.1375 raw FVGs per bar**
(`VISION_AUDIT.md` §E.1). The gold file gives **0.217 raw FVGs per bar**. The same order of
magnitude, so a 1-minute NQ series should produce a comparable candidate rate — which is what makes
the ~600-trades-per-arm sample-size estimate in §D.3 reachable in roughly 1 year at 2
candidates/day.
