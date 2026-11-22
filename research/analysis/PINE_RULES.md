# PINE_RULES.md — the reference iFVG implementation, extracted from code

**Deliverable of:** reverse-engineering of the only executable statement of the rules we have.
**Source of truth for this file:** `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` (694 lines, `//@version=6`).
**Repo:** `https://github.com/cantolab/IFVG-Ultimate-Dodgy.git` @ `bdc0b04` ("Update ifvgUltimatePlus.pine", Ken / cantoindicators@gmail.com, 2026-08-21).
**Files in the repo:** exactly two — `ifvgUltimatePlus.pine` and `README.md`. There is **no** second `.pine` file, no older version, no branch other than `main`, and a single commit. **The analysed file is therefore both the most complete and the latest.**
**Citations:** `pine:L###` = line number in that file. Code is quoted **verbatim**.

---

## 0. Read this before you port anything

### 0.1 The replica is NOT the original — it is a deliberate partial re-implementation

The doc (`iFVG几个模型的讨论.txt`) calls `cantolab/IFVG-Ultimate-Dodgy` a "高还原度开源复刻" (high-fidelity open-source replica) and, in the same paragraph, describes the *closed-source* original as implementing "流动性扫荡检测、7–15 根 K 线内的缺口反转验证、SMT 背离确认以及多重共振评分系统（A+ 至 C 级）".

The replica's own README says the opposite, in the author's own words:

> **"What I left out and why**
> The original is a messy indicator with a lot of unnecessary inputs, most of which Dodgy doesn't even use himself.
> 1. **Sensitivity** — he keeps this on the most sensitive setting by default, meaning every IFVG setup is shown even the small ones. So my code shows everything as well.
> 2. **HTF FVGs** — … In practice they're treated as extra confluence at best. If a trade goes to profit without an HTF FVG lining up, **he still takes it**.
> 3. **TP lines** — I went with RR based targets instead of nearest liquidity. …
> 4. **Setup grade box** — left out entirely. Dodgy himself has said the grading is mechanical …

and

> **"I also built HTF sweep confirmation into IFVG detection (turn on in settings) expecting it to clean things up. Setup quality barely changed, if any, it looked slightly worse. So I didn't bother coding HTF FVG confluence or SMT on top of it, especially since he takes trades without them as well."**

**Consequence for us:** the replica and the design doc describe two different systems. Where the replica is silent (ATR gap filter, SMT, grading, checklist, killzone filtering, nearest-liquidity TP, OB blocking), the silence is **the replica's omission, not evidence that the original lacks it**. Conversely, several things the replica *does* implement (HTF swing-based sweep, BE-intact gate, hide-losing erasure, display-only history cap) are **absent from the doc** and are real, code-backed behaviours.

This document therefore separates three tiers of evidence:

| Tier | Meaning |
|---|---|
| **[CODE]** | Implemented in the replica. Verifiable, quotable, port it as-is (modulo §D). |
| **[CODE-ABSENT]** | Explicitly declared in the doc but *not implemented anywhere* in the replica. The doc's claim is about the closed-source original; **unverifiable from this repo**. |
| **[CODE-ONLY]** | Implemented in the replica but **never mentioned** in the doc. Highest-value findings. |

### 0.2 v6-only syntax in use

`//@version=6` (pine:L1). v6-relevant constructs used: `type`/`method` declarations with field mutation (`e.ifvgConfirmed := true`, `z.attachCount += 1`), `array.new<T>()`, `box.new(..., xloc = xloc.bar_time)`, `label.new(..., xloc = xloc.bar_index)`, `switch` expressions, `ta.lowestbars/ta.highestbars` (v5+ signature, no `source` argument), `request.security(..., lookahead = barmerge.lookahead_off)`, `alert(..., alert.freq_once_per_bar_close)`, `input.session`, `table.new`. The script is an **`indicator()`**, not a `strategy()` — **there are no `strategy.*` calls, no commission model, no slippage model, no order fills anywhere in the file.** Everything about "RR target" and "stop" is *drawing primitives*, not exchange of orders.

### 0.3 The five headline findings

1. **No ATR filter, no minimum-gap coefficient.** `grep -ni "atr"` over the whole file returns **nothing**. The gap is measured **edge-to-edge on wicks** and *any* strictly-positive gap qualifies. The doc's `gap > 0.25 * ATR(14)` has **no counterpart in this code at all**.
2. **The inversion window is `0–15` bars, not `7–15`.**


> **CORRECTION (2026-11-22, leaf L2).** The statement that the inversion window is
> **[0, 15]** with **no lower bound**, and that the FVG's own newest candle can be the
> confirmation candle (age 0), is **wrong**. Age 0 is **arithmetically impossible**:
> a bullish FVG requires `low[c] > high[c-2]`, while the age-0 trigger requires
> `close[c] < high[c-2]`, and `close[c] >= low[c]`; symmetrically for the bearish case.
> Verified empirically: over 423,759 BTCUSDT 1-minute candidates the trigger-age
> histogram starts at **age 1** and **no candidate triggers at age 0**.
> The effective window is **[1, 15]**. See `research/audit/L2_RULES.md` §A.5.
 `graceCandles = allowExtIFVG ? 15 : 6` (pine:L658) is only an **upper bound**; there is no lower bound. The confirmation candle may be the very candle that completes the FVG (age 0). The label "Allow 7 - 15 Candle IFVGs" (pine:L9) is inherited UI text — the tooltip in the same line says "may form within 15 candles", contradicting the title.
3. **There is no scoring system and no A+/A/B/C grade in the code.** No points, no score variable, no cutoffs. The only "score-like" artefact is a cosmetic `"+"`/`"-"` suffix and a volume dot in the label text (pine:L453-454).
4. **No SMT, no PDH/PDL, no EQH/EQL, no OB, no killzone filter.** The only liquidity reference is a **3-bar fractal on manually aggregated HTF swing highs/lows** (pine:L619-630). The doc's session windows exist in the code **only as alert filters** (pine:L123-126, L497-498).
5. **`hideLosing` really does erase losers post-hoc** — and it is `true` by default. On a stop hit the box, entry line and label are deleted and the record is removed from `setupRecords` (pine:L519-525). The doc's warning is confirmed at the code level.

---

# A. Full input-parameter inventory

All 50 `input.*` declarations, verbatim, with default and range. `inline` groups are UI-only and carry no semantics.

### A.(a) Structural / FVG params

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 1 | L6 | `ifvgMode          = input.string("Single", title = "Detection", options = ["Single", "Series"], group = grpGeneral)` | `"Single"` | `Single`/`Series` | `Single` = keep only the best (largest) FVG per leg; `Series` = merge consecutive FVGs into one widening zone. |
| 2 | L12 | `onlyShowHtfAlignedIFVG = input.bool(false, title = "Only show IFVGs with HTF FVGs", group = grpGeneral, tooltip = "If true, an IFVG setup is only shown/confirmed if its price range overlaps an HTF FVG zone.")` | `false` | bool | **Hard gate**: require the IFVG price band to overlap an HTF FVG zone. |
| 3 | L30 | `maxHtfZones       = input.int(3, "Max Zones Shown", minval = 1, maxval = 20, group = grpHtfFvg, tooltip = "Zones attached to a still-active IFVG setup are kept regardless of this limit.")` | `3` | 1–20 | Max retained HTF FVG zones (attached/kept-alive zones exempt). |

### A.(b) Sweep / liquidity params

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 4 | L11 | `onlyShowSweptIFVG = input.bool(false, title = "Only show IFVGs with HTF sweep", group = grpGeneral, tooltip = "If true, an IFVG setup is only shown/confirmed if an HTF sweep occurred during its swing (per the Swing Sweep Filter setting).")` | `false` | bool | **Hard gate**: the leg must contain an HTF liquidity sweep. |
| 5 | L16 | `htfMode           = input.string("Auto", "Alignment Mode", options = ["Auto", "Custom"], group = grpLiquidity, inline = "htf")` | `"Auto"` | `Auto`/`Custom` | HTF used by the **sweep** detector: auto-mapped or custom. |
| 6 | L17 | `customHTF         = input.timeframe("60", "Custom", group = grpLiquidity, inline = "htf", active = htfMode == "Custom")` | `"60"` | any TF | Custom sweep HTF. |
| 7 | L18 | `showSweep         = input.bool(true, "Show Sweeps", group = grpLiquidity)` | `true` | bool | Draw sweep lines/labels. Does **not** gate detection (the sweep state is computed regardless). |
| 8 | L19 | `sweepColorBuy     = input.color(color.gray, "Bullish Sweep", group = grpLiquidity, inline = "sweepcolor", active = showSweep)` | `color.gray` | — | Colour of the *low* sweep line (used with `sweepColorBuy` for `validBearish`). |
| 9 | L20 | `sweepColorSell    = input.color(color.gray, "Bearish Sweep", group = grpLiquidity, inline = "sweepcolor", active = showSweep)` | `color.gray` | — | Colour of the *high* sweep line. |
| 10 | L21 | `sweepWidth        = input.int(1, "Width", minval = 1, maxval = 4, group = grpLiquidity, inline = "sweepstyle", active = showSweep)` | `1` | 1–4 | Line width. |
| 11 | L22 | `sweepStyleStr     = input.string("Dotted", "Style", options = ["Dotted", "Dashed", "Solid"], group = grpLiquidity, inline = "sweepstyle", active = showSweep)` | `"Dotted"` | 3 opts | Line style. |
| 12 | L23 | `sweepLabelText    = input.string("$$$", "Label Text", group = grpLiquidity, inline = "sweeplabel", active = showSweep)` | `"$$$"` | string | Sweep label text. |
| 13 | L24 | `sweepLabelSizeStr = input.string("Small", "Label Size", options = ["Tiny", "Small", "Normal", "Large"], group = grpLiquidity, inline = "sweeplabel", active = showSweep)` | `"Small"` | 4 opts | Sweep label size. |

### A.(c) Inversion-timing params

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 14 | L9 | `allowExtIFVG      = input.bool(true, title = "Allow 7 - 15 Candle IFVGs", tooltip = "If enabled, IFVGs may form within 15 candles.\nIf disabled, they must form within 6 candles.", group = grpGeneral)` | `true` | bool | **The only timing knob.** `true` → `graceCandles = 15`; `false` → `graceCandles = 6`. It is an **upper bound only**. |
| 15 | L10 | `requireBEIntact   = input.bool(true, title = "Require BE not breached on inversion", group = grpGeneral, tooltip = "If true, setups where the confirmation candle itself already reaches B.E are completely hidden.")` | `true` | bool | **Hard gate**: drop the setup entirely if the confirmation close has already reached the break-even level. |

### A.(d) Scoring / grade params

**None.** There is not a single `input.*` that produces a score, a grade, a checklist, a point value or a threshold band. The only inputs that look remotely "scoring-adjacent" are cosmetic:

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 16 | L39 | `ifvgLineText      = input.string("IFVG", "Label Text", group = grpIFVG, inline = "ifvgtext")` | `"IFVG"` | string | Label prefix (the replica renames the original's `DD` to `IFVG`). |
| 17 | L40 | `textSizeStr       = input.string("Small", "Label Size", options = ["Tiny", "Small", "Normal", "Large"], group = grpIFVG, inline = "ifvgtext")` | `"Small"` | 4 opts | Label size. |

### A.(e) HTF / killzone / session params

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 18 | L27 | `showHtfFvg        = input.bool(true, "Show HTF FVG", group = grpHtfFvg)` | `true` | bool | Draw HTF FVG zones. Does not gate detection. |
| 19 | L28 | `htfFvgMode        = input.string("Auto", "Alignment Mode", options = ["Auto", "Custom"], group = grpHtfFvg, inline = "htffvg")` | `"Auto"` | `Auto`/`Custom` | HTF used by the **HTF FVG** detector. **Independent** of `htfMode` (the sweep HTF). |
| 20 | L29 | `manualHtfFvg      = input.timeframe("60", "Custom", group = grpHtfFvg, inline = "htffvg", active = htfFvgMode == "Custom")` | `"60"` | any TF | Custom HTF-FVG timeframe. |
| 21 | L31 | `htfBullColor      = input.color(color.new(color.blue, 85), "Bullish Zone", group = grpHtfFvg, inline = "htfcolor")` | blue @85% | — | Bullish HTF zone colour. |
| 22 | L32 | `htfBearColor      = input.color(color.new(color.red, 85), "Bearish Zone", group = grpHtfFvg, inline = "htfcolor")` | red @85% | — | Bearish HTF zone colour. |
| 23 | L58 | `enableAlerts   = input.bool(true, "Enable Alerts", group = grpAlerts, tooltip = "Master switch. Alerts only fire when this is enabled AND the confirmation candle falls within an enabled session below.")` | `true` | bool | Master alert switch. **Alerts only — not a trade filter.** |
| 24 | L59 | `session1Enable = input.bool(true, "Session 1", group = grpAlerts, inline = "s1")` | `true` | bool | Enable alert session 1. |
| 25 | L60 | `session1Time   = input.session("0930-1600", "", group = grpAlerts, inline = "s1")` | `"0930-1600"` | session | Alert window 1, evaluated in `America/New_York`. |
| 26 | L61 | `session2Enable = input.bool(false, "Session 2", group = grpAlerts, inline = "s2")` | `false` | bool | Enable alert session 2. |
| 27 | L62 | `session2Time   = input.session("2000-0000", "", group = grpAlerts, inline = "s2")` | `"2000-0000"` | session | Alert window 2 (crosses midnight). |
| 28 | L63 | `session3Enable = input.bool(false, "Session 3", group = grpAlerts, inline = "s3")` | `false` | bool | Enable alert session 3. |
| 29 | L64 | `session3Time   = input.session("0200-0500", "", group = grpAlerts, inline = "s3")` | `"0200-0500"` | session | Alert window 3. |

### A.(f) RR / exit / break-even params

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 30 | L43 | `showSL      = input.bool(true, title = "Stoploss", group = grpLimits, inline = "sl")` | `true` | bool | Draw the stop. **Side effect: the stop price is only computed when this is `true`** — and the RR projections are created *inside* that same block (pine:L461-473). |
| 31 | L44 | `colorSL     = input.color(color.gray, title = "", group = grpLimits, inline = "sl")` | `color.gray` | — | Stop line colour. |
| 32 | L45 | `slPlacement = input.string("Wick", title = "Stoploss Placement", options = ["Wick", "Body", "IFVG"], group = grpLimits, inline = "sl")` | `"Wick"` | `Wick`/`Body`/`IFVG` | Where the stop sits: the extreme wick, the extreme bar's body edge, or the FVG's far edge. |
| 33 | L46 | `showBE      = input.bool(true, title = "Break Even", group = grpLimits, inline = "be")` | `true` | bool | Draw the break-even line (at the swing origin). |
| 34 | L47 | `colorBE     = input.color(color.orange, title = "", group = grpLimits, inline = "be")` | `color.orange` | — | Break-even line colour. |
| 35 | L50 | `showRR  = input.bool(true, "Enable Projections?", group = grpRR, inline = "rrb")` | `true` | bool | Draw RR target lines. |
| 36 | L51 | `rrInput = input.string("1,2", "", group = grpRR, inline = "rrb", active = showRR)` | `"1,2"` | comma list of floats | Comma-separated RR ratios, e.g. `"1,2,3"` → lines at 1R, 2R, 3R. |
| 37 | L52 | `rrColor = input.color(color.gray, "", group = grpRR, inline = "rrc", active = showRR)` | `color.gray` | — | RR line colour. |
| 38 | L53 | `rrStyle = input.string("Dashed", "", options = ["Solid", "Dashed", "Dotted"], group = grpRR, inline = "rrc", active = showRR)` | `"Dashed"` | 3 opts | RR line style. |
| 39 | L54 | `rrWidth = input.int(1, "", minval = 1, group = grpRR, inline = "rrc", active = showRR)` | `1` | ≥1 | RR line width. |

### A.(g) Visual / display params

| # | Line | Declaration (verbatim) | Default | Range | Meaning |
|---|---|---|---|---|---|
| 40 | L7 | `biasMode          = input.string("Neutral", title = "Bias", options = ["Neutral", "Bullish", "Bearish"], group = grpGeneral)` | `"Neutral"` | 3 opts | **Direction filter**: `Bullish` suppresses short setups *and* stops tracking their candidate FVGs; `Bearish` suppresses long setups. Not cosmetic — a hard gate. |
| 41 | L8 | `hideLosing        = input.bool(true, title = "Hide Losing Setups", group = grpGeneral, tooltip = "Invalidated IFVGs are hidden")` | `true` | bool | **Erases** stop-hit setups from the chart post-hoc. |
| 42 | L13 | `setupHistory      = input.int(2, "Number of Setups Displayed", minval = 0, maxval = 50, group = grpGeneral, tooltip = "Number of past IFVG setups (active or resolved) to keep drawn on the chart. 0 = unlimited.")` | `2` | 0–50 | Display cap. **Side effect: it also removes the evicted setup from the active-trade array, so an unresolved setup that ages out stops being managed.** |
| 43 | L35 | `colorIFVGBull     = input.color(color.blue, "Long Color", group = grpIFVG, inline = "ifvgline")` | blue | — | Long entry line colour. |
| 44 | L36 | `colorIFVGBear     = input.color(color.red, "Short Color", group = grpIFVG, inline = "ifvgline")` | red | — | Short entry line colour. |
| 45 | L37 | `colorIFVGBullBox  = input.color(color.new(color.gray, 50), "Bullish IFVG", group = grpIFVG, inline = "ifvgbox")` | grey @50% | — | FVG box fill. |
| 46 | L38 | `colorIFVGBearBox  = input.color(color.new(color.gray, 50), "Bearish IFVG", group = grpIFVG, inline = "ifvgbox")` | grey @50% | — | FVG box fill. |
| 47 | L67 | `showWatermark = input.bool(true, title = "Show?", inline = "wm1", group = grpWatermark)` | `true` | bool | Watermark table. |
| 48 | L68 | `wmTextColor   = input.color(#000000, title = "", inline = "wm1", group = grpWatermark)` | `#000000` | — | Watermark text colour. |
| 49 | L69 | `wmSize1Str    = input.string("Normal", title = "Title/Symbol Size", inline = "wm2", group = grpWatermark, options = ["Tiny", "Small", "Normal", "Large", "Huge"])` | `"Normal"` | 5 opts | Watermark title size. |
| 50 | L70 | `wmSize3Str    = input.string("Small", title = "Date Size", inline = "wm3", group = grpWatermark, options = ["Tiny", "Small", "Normal", "Large", "Huge"])` | `"Small"` | 5 opts | Watermark date size. |

*(There are exactly 50 `input.*` declarations in the file — `grep -c "input\."` = 50. `ifvgMode` (L6) is grouped under (a) structural/FVG because it controls candidate merging; it also has a display effect and is cross-referenced from (d).)*

**Non-input constants** (pine:L74-86, L95-96, L127):

```pine
MAX_SWING_HISTORY  = 50
MAX_TRACKED_SETUPS = 50
NY_TZ              = "America/New_York"
HTF_LABEL_OFFSET   = 3
```
```pine
showHtfCE    = true
showHtfLabel = true
```
```pine
volSma = ta.sma(volume, 20)
```

---

# B. Rule table

Each rule: name → verbatim Pine → precise restatement → numbers → **gate / score** classification.

**Legend:** `GATE` = blocks the signal from existing at all. `SCORE` = contributes points to a grade. `STATE` = neither; shapes the state machine without gating. `DRAW` = pure drawing.

---

## B.1 FVG detection

### R1 — Swing-origin detection (3-bar pivot) — [CODE] — STATE
```pine
350	    bool  pivotOrigin = isLow ? ta.lowestbars(3) == -1  : ta.highestbars(3) == -1
351	    bool  pivotOpp    = isLow ? ta.highestbars(3) == -1 : ta.lowestbars(3) == -1
352	    float originSrc   = isLow ? low[1]  : high[1]
353	    float oppSrc      = isLow ? high[1] : low[1]
```
```pine
358	    if pivotOrigin
359	        originPrice  := originSrc
360	        originBar    := bar_index - 1
361	        frozen       := false
362	        frozenPrice  := na
363	        freezeBar    := na
364	        liveEntry    := na
365	        clusterLast1 := na
366	        sweepLn      := na
367	        sweepLbl     := na
368	        sweepLnPrice := na
369	        sweepLnTime  := na
```
**Restatement.** Two independent trackers run (one per FVG direction). Each tracker watches for a 3-bar fractal pivot: `isLow=true` (bullish-FVG tracker) fires when the current bar is the **lowest of the last 3 bars**; `isLow=false` fires when the current bar is the **highest of the last 3 bars**. On such a pivot the tracker records an *origin*: `originBar = bar_index - 1` and `originPrice = low[1]` (for `isLow=true`) or `high[1]` (for `isLow=false`), and resets all leg state (freeze, live candidate, sweep line).

**The pivot fires on the bar *after* the extreme, but the origin is taken from the bar *before* the extreme.** Under Pine's `ta.lowestbars(3) == -1` convention (offset `-1` ⇒ the extreme is the current bar), the actual extreme sits at `bar_index` while the recorded origin is `bar_index - 1`. **This one-bar asymmetry is the single most likely source of off-by-one divergence in a port.** See §D.1 and §E-1.

**Numbers:** pivot lookback `3` bars; origin offset `1` bar back; origin value `low[1]`/`high[1]`.
**Classification:** STATE (defines the leg; feeds the BE level and the FVG search window).

### R2 — FVG geometry — [CODE] — STATE (candidate creation)
```pine
354	    bool  fvgHere     = isLow ? low[1] > high[3] : high[1] < low[3]
355	    float fvgTop      = isLow ? low[1] : low[3]
356	    float fvgBottom   = isLow ? high[3] : high[1]
```
```pine
379	        if checkFvg
380	            int fvgBar1 = bar_index - 1
381	            int fvgBar3 = bar_index - 3
```
**Restatement.** With `A = bar_index-3` (oldest), `B = bar_index-2` (middle), `C = bar_index-1` (newest):

| Tracker | Condition | Gap zone | Direction |
|---|---|---|---|
| `isLow = true` → `validBullish` | `C.low > A.high` | top `= C.low`, bottom `= A.high` | **Bullish FVG** (gap up). Later inverts into resistance → **short**. |
| `isLow = false` → `validBearish` | `C.high < A.low` | top `= A.low`, bottom `= C.high` | **Bearish FVG** (gap down). Later inverts into support → **long**. |

This is exactly the textbook ICT geometry (`c[i-2].high < c[i].low` bullish, `c[i-2].low > c[i].high` bearish, with `c[i]` = newest), and it matches the doc's L121 inequality. **Both comparisons are strict** — a zero-width gap (equality) is rejected.

**Gap size is measured on wicks** (`low`/`high`), never on bodies, and there is **no minimum size**. The full gap width is `C.low - A.high` (bullish) / `A.low - C.high` (bearish).

**Numbers:** 3 candles; ATR lookback — **none**; minimum-gap coefficient — **none** (`0.25 * ATR(14)` does not exist in this file).
**Classification:** STATE (candidate creation). The *inversion* (R12) is what gates the trade.

### R3 — FVG search-window gate — [CODE] — STATE
```pine
377	        bool checkFvg = (not frozen or bar_index == freezeBar + 1) and bar_index - 3 >= originBar - 1 and fvgHere
```
**Restatement.** Three conditions: (a) the leg is not frozen, *or* we are on the single bar `freezeBar + 1`; (b) the FVG's **oldest** candle `bar_index-3` must satisfy `bar_index - 3 >= originBar - 1`; (c) the FVG geometry holds.

Condition (b) means the FVG triple may start **one bar before** the origin bar; i.e. the origin candle may be the middle or the newest candle of the FVG triple. At the pivot bar itself (`bar_index = originBar+1`) the condition reads `originBar-2 >= originBar-1` → **false**, so an FVG can never be created on the pivot bar itself.
**Numbers:** tolerance `- 1` bar.
**Classification:** STATE.

### R4 — Leg freeze / unfreeze (opposite pivot) — [CODE] — STATE
```pine
371	    if not na(originBar)
372	        if frozen
373	            bool broken = isLow ? oppSrc > frozenPrice : oppSrc < frozenPrice
374	            if broken
375	                frozen := false
```
```pine
426	        if not frozen and pivotOpp
427	            frozen      := true
428	            frozenPrice := oppSrc
429	            freezeBar   := bar_index
```
**Restatement.** When the *opposite* 3-bar pivot occurs (a swing high for the `isLow=true` tracker), the leg is **frozen**: no further FVG may be created except on the single bar `freezeBar + 1`. The freeze is released when price breaks beyond the frozen extreme (`oppSrc > frozenPrice` for a low-origin leg, `<` for a high-origin leg) — a **strict** comparison against the *previous* bar's opposite extreme (`high[1]` / `low[1]`).

Critically: **releasing the freeze does *not* reset `originBar`.** The origin (and therefore the BE level) can survive arbitrarily long after the leg was broken. The BE level of a setup can therefore belong to a swing many bars old.
**Numbers:** freeze window = pivot bar to `freezeBar+1` inclusive.
**Classification:** STATE.

### R5 — Single vs Series handling of overlapping candidates — [CODE] — STATE
```pine
383	            if not na(liveEntry) and not liveEntry.ifvgConfirmed and validArr.indexof(liveEntry) < 0
384	                liveEntry    := na
385	                clusterLast1 := na
386	
387	            if na(liveEntry)
388	                liveEntry    := ict_PushCandidate(validArr, fvgBar1, fvgBar3, fvgTop, fvgBottom, originBar, originPrice)
389	                clusterLast1 := fvgBar1
390	            else if not liveEntry.ifvgConfirmed
391	                if ifvgMode == "Series" and fvgBar1 == clusterLast1 + 1
392	                    liveEntry.fvgTop    := math.max(liveEntry.fvgTop, fvgTop)
393	                    liveEntry.fvgBottom := math.min(liveEntry.fvgBottom, fvgBottom)
394	                    liveEntry.fvgBar1   := fvgBar1
395	                    clusterLast1 := fvgBar1
396	                else
397	                    bool better = isLow ? fvgTop > liveEntry.fvgTop : fvgBottom < liveEntry.fvgBottom
398	                    if better
399	                        int oldIdx = validArr.indexof(liveEntry)
400	                        if oldIdx >= 0
401	                            validArr.remove(oldIdx)
402	                        liveEntry    := ict_PushCandidate(validArr, fvgBar1, fvgBar3, fvgTop, fvgBottom, originBar, originPrice)
403	                        clusterLast1 := fvgBar1
```
**Restatement.** Only **one live candidate per direction** exists at a time (`liveEntry`).
- If no live candidate → push a new one.
- `Series` mode + the new FVG's newest candle is exactly `clusterLast1 + 1` (consecutive bars) → **merge**: widen the zone (`max` top, `min` bottom) and move `fvgBar1` forward. The zone therefore *grows* with each consecutive FVG.
- `Single` mode (default) → keep the **better** gap: for a bullish FVG, the one with the **higher top** (`fvgTop > liveEntry.fvgTop`); for a bearish FVG, the one with the **lower bottom** (`fvgBottom < liveEntry.fvgBottom`). The loser is removed from the candidate array.
- A confirmed (`ifvgConfirmed`) live candidate is never replaced.
- A live candidate that has been removed from the array (e.g. expired, see R14) is nulled.

**Numbers:** "better" comparison is strict (`>` / `<`), so equal-quality gaps keep the older one.
**Classification:** STATE.

### R6 — No ATR / no minimum-gap filter — [CODE-ABSENT] — (would-be GATE)
`grep -ni "atr" ifvgUltimatePlus.pine` → **no match**. The only `ta.*` calls in the entire file are `ta.sma` (L85, volume), `ta.lowestbars` (L350, L351) and `ta.highestbars` (L350, L351).
**Restatement.** The replica applies **no volatility-normalised gap filter**; every strictly-positive wick gap qualifies as an FVG. The README states this is deliberate ("he keeps this on the most sensitive setting by default … So my code shows everything as well").
**Classification:** absent — the doc's `0.25 * ATR(14)` must be re-implemented from the doc, not from this code.

---

## B.2 Liquidity sweep detection

### R7 — Sweep HTF selection (Auto map) — [CODE] — STATE
```pine
544	autoHTF() =>
545	    switch timeframe.period
546	        "1"   => "15"
547	        "3"   => "30"
548	        "5"   => "60"
549	        "15"  => "240"
550	        "60"  => "1D"
551	        "240" => "1W"
552	        "1D"  => "1M"
553	        =>      "1M"
```
```pine
580	htf = htfMode == "Auto" ? autoHTF() : customHTF
```
**Restatement.** The sweep reference timeframe is a fixed mapping from the chart timeframe. **Note the fall-through case `"1M"`** for any unmapped chart TF (e.g. `"2"`, `"10"`, `"30"`, `"120"`).

**This map is *different* from the HTF-FVG map (R19):** on a 30m chart the sweep HTF is `"1M"` but the FVG HTF is `"240"`; on a daily chart the sweep HTF is `"1M"` but the FVG HTF is `"1W"`.
**Numbers:** 1→15, 3→30, 5→60, 15→240, 60→1D, 240→1W, 1D→1M, else→1M.
**Classification:** STATE.

### R8 — Manual HTF bar aggregation (no `request.security`) — [CODE] — STATE
```pine
582	var float htfCurH     = high
583	var int   htfCurHTime = time
584	var float htfCurL     = low
585	var int   htfCurLTime = time
586	
587	var float[] htfHighs    = array.new<float>()
588	var float[] htfLows     = array.new<float>()
589	var int[]   htfHighTime = array.new<int>()
590	var int[]   htfLowTime  = array.new<int>()
591	
592	htfChanged = time(htf) != time(htf)[1]
593	
594	if htfChanged
595	    htfHighs.push(htfCurH)
596	    htfLows.push(htfCurL)
597	    htfHighTime.push(htfCurHTime)
598	    htfLowTime.push(htfCurLTime)
599	    if htfHighs.size() > MAX_SWING_HISTORY + 5
600	        htfHighs.shift()
601	        htfLows.shift()
602	        htfHighTime.shift()
603	        htfLowTime.shift()
604	    htfCurH     := high
605	    htfCurHTime := time
606	    htfCurL     := low
607	    htfCurLTime := time
608	else
609	    if high > htfCurH
610	        htfCurH     := high
611	        htfCurHTime := time
612	    if low < htfCurL
613	        htfCurL     := low
614	        htfCurLTime := time
```
**Restatement.** The script **does not** use `request.security` for the sweep. It hand-rolls HTF bars: it tracks the running extreme of the current HTF bar together with the **chart-bar time at which that extreme occurred**, and on each HTF bar boundary (`time(htf) != time(htf)[1]`) it commits the completed HTF bar. Four parallel arrays hold the history; the arrays are capped at `MAX_SWING_HISTORY + 5 = 55` entries.

Note the running extreme keeps only the *latest* extreme's time (a new high replaces the time; an equal high does **not** update it — `high > htfCurH` is strict).
**Numbers:** history cap 55 HTF bars.
**Classification:** STATE.

### R9 — HTF swing-point (3-bar fractal) detection — [CODE] — STATE
```pine
616	var SwingSet stHigh = SwingSet.new(array.new<SwingPoint>())
617	var SwingSet stLow  = SwingSet.new(array.new<SwingPoint>())
618	
619	if htfChanged and htfHighs.size() >= 3
620	    n = htfHighs.size()
621	    midHigh = htfHighs.get(n - 2)
622	    if midHigh >= htfHighs.get(n - 3) and midHigh >= htfHighs.get(n - 1)
623	        stHigh.addPoint(midHigh, htfHighTime.get(n - 2))
624	
625	    midLow = htfLows.get(n - 2)
626	    if midLow <= htfLows.get(n - 3) and midLow <= htfLows.get(n - 1)
627	        stLow.addPoint(midLow, htfLowTime.get(n - 2))
```
**Restatement.** A **3-bar fractal on the completed HTF high/low series**. The middle HTF bar (`n-2`) is a swing high when `midHigh >= htfHighs[n-3] and midHigh >= htfHighs[n-1]` — **non-strict on both sides** (ties count as swings). The swing's timestamp is the chart-bar time of that HTF bar's extreme. The swing is only *known* two HTF bars after the extreme HTF bar completed (it is published when HTF bar `n` closes).

The swing set is capped at `MAX_SWING_HISTORY = 50` points (L555-558, oldest dropped).
**Numbers:** fractal length 3; `>=`/`<=` (ties included); lag 2 HTF bars to publication.
**Classification:** STATE.

### R10 — Sweep detection (strict pierce; points consumed) — [CODE] — STATE
```pine
560	method findSweep(SwingSet this, float testPrice, bool isHigh) =>
561	    bool  found  = false
562	    float foundY = na
563	    int   foundT = na
564	    if this.points.size() > 0
565	        for i = this.points.size() - 1 to 0
566	            pt = this.points.get(i)
567	            bool isSwept = isHigh ? testPrice > pt.y : testPrice < pt.y
568	            if isSwept
569	                bool better = not found or (isHigh ? pt.y > foundY : pt.y < foundY)
570	                if better
571	                    foundY := pt.y
572	                    foundT := pt.t
573	                found := true
574	                this.points.remove(i)
575	    [found, foundY, foundT]
```
```pine
629	[sweepLowFound, sweepLowPrice, sweepLowTime]    = stLow.findSweep(low, false)
630	[sweepHighFound, sweepHighPrice, sweepHighTime] = stHigh.findSweep(high, true)
```
**Restatement.**
- **What is swept:** only the **HTF 3-bar fractal swing highs and swing lows** (R9). There is **no EQH, no EQL, no PDH, no PDL, no session high/low** anywhere in the file.
- **Tolerance / proximity: there is none.** The test is a strict pierce: `high > pt.y` for a swing high, `low < pt.y` for a swing low. No buffer, no proximity band, no ATR tolerance.
- **Wick vs body:** the sweep is detected with the bar's **`high`/`low`** — i.e. the extreme. There is **no requirement that the body fails to reclaim the level**; a bar that closes far beyond the swing level is still a "sweep". Conversely the sweep may be a pure wick. The script never inspects the body at all for sweeps.
- **Consumption semantics (important):** every swept swing point is **removed from the swing set** (`this.points.remove(i)` inside the `if isSwept` branch — for *every* swept point, not just the best one). **Each swing level can therefore be swept only once, ever.** The returned `foundY/foundT` is the *best* swept point (highest swept high / lowest swept low).
- The sweep test runs on **every chart bar** against the **current bar's** high/low. The swept points are consumed even if no FVG tracker is active at that moment — a sweep that happens with no leg in progress is **lost**.
- `sweepLowFound` (sell-side sweep) is fed to the **bearish-FVG tracker**; `sweepHighFound` (buy-side sweep) is fed to the **bullish-FVG tracker** — i.e. the sweep direction is *opposite* to the eventual trade direction, which is what makes sense (a short is preceded by a buy-side grab).

**Numbers:** strict `>` / `<`; no tolerance; single-shot consumption.
**Classification:** STATE (produces the `swept` tag) + optional GATE via R12.

### R11 — Sweep ↔ leg association (`swept` flag) — [CODE] — STATE
```pine
405	        if sweepValid
406	            bool betterSweep = na(sweepLnPrice) or (isLow ? sweepPrice > sweepLnPrice : sweepPrice < sweepLnPrice)
407	            if betterSweep
408	                sweepLnPrice := sweepPrice
409	                sweepLnTime  := sweepTime
410	            if na(sweepLn)
411	                sweepLn  := line.new(sweepLnTime, sweepLnPrice, time, sweepLnPrice, xloc = xloc.bar_time, color = sweepLineColor, style = sweepLineStyle, width = sweepWidth)
412	                sweepLbl := label.new(bar_index, sweepLnPrice, sweepLabelText, xloc = xloc.bar_index, style = label.style_label_left, color = na, textcolor = sweepLineColor, size = sweepLabelSize, text_font_family = font.family_monospace)
413	            else
414	                line.set_xy1(sweepLn, sweepLnTime, sweepLnPrice)
415	                line.set_xy2(sweepLn, time, sweepLnPrice)
416	                label.set_xy(sweepLbl, bar_index, sweepLnPrice)
417	        else if not na(sweepLn)
418	            line.set_xy2(sweepLn, time, sweepLnPrice)
419	            label.set_xy(sweepLbl, bar_index, sweepLnPrice)
```
```pine
421	        bool swingSwept = not na(sweepLn)
422	
423	        if not na(liveEntry)
424	            liveEntry.swept := swingSwept
```
**Restatement.** Within an active leg, the tracker remembers the **best** sweep seen (`higher` high for a low-origin leg, `lower` low for a high-origin leg — note the comparison at L406 is inverted relative to R10's "best" selection, because here "best" means the most extreme *in the leg's direction*) and draws a line from the sweep's time to the current bar. The flag `swept` is simply **"a sweep has occurred since the origin was set"** — it is `true` from the first sweep onwards and stays true until a new pivot resets `sweepLn` (L366).

The sweep line is reset to `na` only when a new origin pivot fires (L366-369), so `swept` is scoped to the current leg.
**Classification:** STATE.

### R12 — `onlyShowSweptIFVG` gate — [CODE] — **GATE**
```pine
443	                    bool  passSweepFilter = not onlyShowSweptIFVG or e.swept
```
```pine
447	                    if not beBreached and passSweepFilter and passHtfFilter
```
**Restatement.** When enabled, the setup only exists if the leg carried an HTF sweep. **Default `false`** ⇒ off by default. The doc has no equivalent.
**Classification:** GATE (optional, off by default).

---

## B.3 Inversion confirmation & timing

### R13 — Inversion trigger predicate — [CODE] — **GATE**
```pine
437	                bool trigger = sourceBearish ? close[1] > e.fvgTop : close[1] < e.fvgBottom
```
```pine
440	                    bool  ifvgBullish = sourceBearish
441	                    float lvl         = close[1]
```
**Restatement.** The inversion is confirmed when the **close** of the *previous* bar (`close[1]`) has **fully penetrated the far edge** of the FVG:

| FVG type | Trigger | Trade | Entry price |
|---|---|---|---|
| Bearish FVG (`validBearish`, gap `[A.low … C.high]`) | `close[1] > fvgTop` (= `close[1] > A.low`) → close **above the gap's top edge** | **long** (`ifvgBullish = true`) | `lvl = close[1]` |
| Bullish FVG (`validBullish`, gap `[A.high … C.low]`) | `close[1] < fvgBottom` (= `close[1] < C.low`) → close **below the gap's bottom edge** | **short** (`ifvgBullish = false`) | `lvl = close[1]` |

- **Body close, not wick** ✓ — the doc's "仅仅影线刺穿不算反转" is confirmed.
- **Far edge, strictly** — `>` / `<`, not `>=` / `<=`. A close *exactly* on the edge does **not** trigger.
- **`close[1]`, not `close`** — the predicate is evaluated on bar `X` using the close of bar `X-1`. So the **confirmation candle is `X-1`**, and the code *draws* the signal on bar `X`.
- The trade direction is the **opposite** of the FVG type (a bullish FVG inverting gives a short) ✓ textbook iFVG.

**Numbers:** strict inequality; 1-bar evaluation lag.
**Classification:** **GATE** — this is *the* trigger of the whole system.

### R14 — Candidate expiry (`graceCandles`) — [CODE] — STATE
```pine
658	int  graceCandles      = allowExtIFVG ? 15 : 6
```
```pine
499	                if not trigger and bar_index - e.fvgBar1 > graceCandles
500	                    arr.remove(i)
```
**Restatement.** A candidate that has not yet triggered is **removed** from the candidate array when `bar_index - e.fvgBar1 > graceCandles`. `e.fvgBar1` is the **newest candle of the FVG** (`= bar_index-1` at creation, and updated forward in `Series` mode).

Because the trigger uses `close[1]` (R13), the **last bar on which the inversion may occur** is `fvgBar1 + graceCandles`:
- `allowExtIFVG = true` → `graceCandles = 15` → inversion allowed on bars `fvgBar1 + 0 … fvgBar1 + 15`.
- `allowExtIFVG = false` → `graceCandles = 6` → inversion allowed on bars `fvgBar1 + 0 … fvgBar1 + 6`.

**There is no lower bound.** The window is **[0, 15]**, not [7, 15]. See §C-2.

Expiry is evaluated *after* the trigger test on the same bar, so the candidate survives one extra bar and is only dropped on the bar after the last legal confirmation.
**Numbers:** 15 / 6.
**Classification:** STATE (an expiry, not a gate — but it silently discards un-triggered candidates).

### R15 — The confirmation bar may be the FVG's own newest candle — [CODE] — (structural)
**Restatement.** Because the candidate is created on bar `X` (using candles `X-3, X-2, X-1`) and the trigger is tested on the same bar `X` with `close[1] = close(X-1)`, **the bar that completes the FVG can itself be the inversion candle** (age 0). There is no minimum separation between FVG formation and inversion.

In the doc's notation (`c[i-2]`, `c[i-1]`, `c[i]` = the three FVG candles, `c[i]` newest), the inversion may occur on `c[i]` itself. The doc's L122-123 requires **7 to 15** bars.
**Classification:** structural divergence — see §C-2.

### R16 — `requireBEIntact` gate — [CODE] — **GATE**
```pine
442	                    bool  beBreached  = requireBEIntact and (ifvgBullish ? lvl >= e.swingPrice : lvl <= e.swingPrice)
```
```pine
447	                    if not beBreached and passSweepFilter and passHtfFilter
```
**Restatement.** At confirmation time, compare the confirmation close `lvl = close[1]` with the **swing origin price** `e.swingPrice`:
- long (`ifvgBullish = true`): breached if `close[1] >= swingPrice` (the swing high),
- short: breached if `close[1] <= swingPrice` (the swing low).

If breached, **the setup is not created at all** — no box, no entry line, no trade. This is the "the confirmation candle has already taken me to break-even, so the trade is worthless" filter.

Note the comparison is `>=` / `<=` (**non-strict**) — reaching exactly the BE level counts as breached. And it uses the **close**, whereas the live BE resolution (R21) uses the **high/low** — a close that is below a long's BE high is *not* "breached" by this gate but the bar's high may still trigger the BE resolution later in the same bar (R21). **The two tests are not equivalent.**
**Numbers:** default `true`.
**Classification:** **GATE** (default on).

### R17 — HTF FVG confluence gate — [CODE] — **GATE** (optional)
```pine
635	[hH1, hL1, hH3, hL3, hT2] = request.security(syminfo.tickerid, htfFvgTF, [high[1], low[1], high[3], low[3], time[2]], lookahead = barmerge.lookahead_off)
```
```pine
637	var int hLastSeenT2 = na
638	hNewBar = hT2 != hLastSeenT2
639	hLastSeenT2 := hT2
640	
641	if hNewBar
642	    bool hBull = hL1 > hH3
643	    bool hBear = hH1 < hL3
644	    if hBull
645	        f_addHtfZone(true, hT2, hL1, hH3)
646	    if hBear
647	        f_addHtfZone(false, hT2, hL3, hH1)
```
```pine
444	                    HtfImbalance matchedZone = f_findHtfOverlap(e.fvgTop, e.fvgBottom)
445	                    bool  passHtfFilter   = not onlyShowHtfAlignedIFVG or not na(matchedZone)
```
**Restatement.**
- The HTF FVG uses the **same 3-candle geometry** (R2) but on the HTF series: bullish if `prevHTF.low > htf[3].high`, zone `[htf[3].high, prevHTF.low]`; bearish if `prevHTF.high < htf[3].low`, zone `[prevHTF.high, htf[3].low]`.
- `request.security(..., lookahead = barmerge.lookahead_off)` → **no repainting**; only closed HTF bars are used.
- The `hNewBar` detector (`time[2]` of the HTF changed) publishes the zone **one HTF bar after the HTF bar that contains it closes**.
- Zones are **mitigated** (and their drawings deleted) when price breaks through them (pine:L266-278):
```pine
268	            if not z.mitigated
269	                bool brokeThrough = z.bullish ? low < z.bottom : high > z.top
270	                if brokeThrough
271	                    z.mitigated := true
272	                    z.deleteDrawings()
```
- The gate checks whether the **IFVG price band overlaps** any live HTF FVG zone (`f_findHtfOverlap`, pine:L230-237, inclusive overlap: `not (bottom > z.top or top < z.bottom)`). `f_findHtfOverlap` returns the **last** matching zone in the array.
- **Default `false`** ⇒ off by default. The README says the original treats HTF FVGs as "extra confluence at best".
**Classification:** **GATE** (optional, off by default).

### R18 — Scoring / grading — [CODE-ABSENT] — (would-be SCORE)
**There is no scoring system.** No point values, no score variable, no cutoffs, no grade labels anywhere in the file. The closest thing:
```pine
453	                        bool   volAbove = volume[1] > volSma[1]
454	                        string txt = ifvgLineText + (ifvgBullish ? "+" : "-") + (volAbove ? " ● " : "")
```
with `volSma = ta.sma(volume, 20)` (pine:L85). The `+`/`-` encodes the trade direction; the `●` encodes `volume[1] > SMA(volume,20)[1]` — i.e. the *confirmation bar's* volume vs its own 20-period average, **lagged by one bar**. Both are **purely cosmetic label decorations**. The volume comparison is **not** a filter.

**Classification:** absent. The doc's A+/A/B/C rubric (L124-126) has **no code counterpart in this repo**. The README explicitly says the grade box was "left out entirely" because "the grading is mechanical".

---

## B.4 HTF / session / bias

### R19 — HTF-FVG timeframe selection (a *second*, different map) — [CODE] — STATE
```pine
128	f_getMappedHTF() =>
129	    string tf = timeframe.period
130	    if tf == "1" or tf == "1m"
131	        "15"
132	    else if tf == "3" or tf == "3m"
133	        "30"
134	    else if tf == "5" or tf == "5m"
135	        "60"
136	    else if tf == "15" or tf == "15m"
137	        "240"
138	    else if tf == "30" or tf == "30m"
139	        "240"
140	    else if tf == "60" or tf == "1h" or tf == "1H"
141	        "1D"
142	    else if tf == "240" or tf == "4h" or tf == "4H"
143	        "1W"
144	    else if tf == "1D" or tf == "D"
145	        "1W"
146	    else
147	        "60"
```
```pine
149	htfFvgTF = htfFvgMode == "Auto" ? f_getMappedHTF() : manualHtfFvg
```
**Numbers:** 1→15, 3→30, 5→60, 15→240, 30→240, 60→1D, 240→1W, 1D→1W, else→60. **Diverges from the sweep map (R7) at 30m (240 vs 1M), 1D (1W vs 1M) and the else-branch (60 vs 1M).**
**Classification:** STATE.

### R20 — Session windows are **alert-only** — [CODE] — (not a gate)
```pine
123	bool inSession1 = session1Enable and not na(time(timeframe.period, session1Time, NY_TZ))
124	bool inSession2 = session2Enable and not na(time(timeframe.period, session2Time, NY_TZ))
125	bool inSession3 = session3Enable and not na(time(timeframe.period, session3Time, NY_TZ))
126	bool inAlertSession = inSession1 or inSession2 or inSession3
```
```pine
497	                        if enableAlerts and inAlertSession
498	                            alert((ifvgBullish ? "Bullish" : "Bearish") + " IFVG confirmed on " + syminfo.ticker, alert.freq_once_per_bar_close)
```
**Restatement.** The three session windows are **exclusively an alert filter**. The setups are created and drawn **regardless of the session**; the session only decides whether an `alert()` fires. Defaults: session 1 = `0930-1600` NY **enabled**, sessions 2 (`2000-0000`) and 3 (`0200-0500`) disabled. Timezone is hard-coded `"America/New_York"` (NY_TZ) and the session is evaluated **on the chart timeframe** (`time(timeframe.period, session, NY_TZ)`), i.e. it is a bar-in-session test, DST-aware.

**The doc's killzones (09:30–11:30 and 13:30–15:30 ET, L114-116) have no counterpart.** The only overlap is the coarse `0930-1600` default.
**Classification:** not a gate — **alert-only**.

### R21 — `biasMode` direction gate — [CODE] — **GATE**
```pine
659	bool enableBullOutput  = biasMode != "Bearish"
660	bool enableBearOutput  = biasMode != "Bullish"
661	
662	if enableBearOutput
663	    ict_TrackLine(true, validBullish, sweepHighFound, sweepHighPrice, sweepHighTime, sweepColorSell)
664	if enableBullOutput
665	    ict_TrackLine(false, validBearish, sweepLowFound, sweepLowPrice, sweepLowTime, sweepColorBuy)
666	
667	if enableBearOutput
668	    ict_CheckIFVG(validBullish, activeTrades, false, graceCandles)
669	if enableBullOutput
670	    ict_CheckIFVG(validBearish, activeTrades, true, graceCandles)
```
**Restatement.** `biasMode` gates **both** the candidate tracking and the confirmation check:
- `Bullish` → long setups only; the bearish-FVG tracker is never called, so no short candidates are even created.
- `Bearish` → short setups only.
- `Neutral` (default) → both.

Note the naming inversion: `enableBearOutput` gates the **bullish-FVG** tracker, which produces **short** setups. (Naming is about the *output* direction, and the `ict_TrackLine(isLow=true, validBullish, …)` call produces shorts because a bullish FVG inverts into resistance.)

**Numbers:** default `"Neutral"`.
**Classification:** **GATE**.

---

## B.5 Stop, break-even, RR, erasure

### R22 — Stop-loss placement — [CODE] — STATE (defines R & the exit test)
```pine
293	ict_ScanExtreme(bool ifvgBullish, int fromBar) =>
294	    int   span      = bar_index - fromBar
295	    float bestPrice = na
296	    int   bestBar   = na
297	    for j = 0 to span
298	        float val = ifvgBullish ? low[span - j] : high[span - j]
299	        if na(bestPrice) or (ifvgBullish ? val < bestPrice : val > bestPrice)
300	            bestPrice := val
301	            bestBar   := fromBar + j
302	    [bestBar, bestPrice]
```
```pine
461	                        if showSL
462	                            [bestBar, bestPrice] = ict_ScanExtreme(ifvgBullish, e.fvgBar1)
463	                            int   offset       = bar_index - bestBar
464	                            bool  candleBullish = close[offset] > open[offset]
465	                            float bodyPrice     = (ifvgBullish == candleBullish) ? open[offset] : close[offset]
466	                            float slPrice = switch slPlacement
467	                                "Wick" => bestPrice
468	                                "Body" => bodyPrice
469	                                "IFVG" => ifvgBullish ? e.fvgBottom : e.fvgTop
470	                            tr.slPrice := slPrice
```
**Restatement.**
- The scan window is `[e.fvgBar1, bar_index]` — from the FVG's **newest candle** to the **bar on which the confirmation was detected** (i.e. `fvgBar1` … `confirmation_bar + 1`).
- For a **long**: the extreme is the **minimum low** in that window; for a **short**: the **maximum high**.
- `slPlacement`:
  - **`"Wick"` (default):** the extreme price itself (`bestPrice`).
  - **`"Body"`:** the body-side edge of the extreme bar — `open[offset]` if the extreme bar's direction matches the trade direction, else `close[offset]`; i.e. for a long, the lower body edge of that bar.
  - **`"IFVG"`:** the FVG's far edge — for a long `e.fvgBottom`, for a short `e.fvgTop`.
- The stop **does not** use the swing origin (the origin is the BE level, R23). The doc's "止损通常设在近期的波段高低点外侧" (stop beyond the recent swing high/low) is therefore **not** what this code does: the stop is the extreme of the FVG→confirmation window, and the swing origin is used for the *break-even* level instead.
- **The scan window includes the bar *after* the confirmation candle.** The entry is `close[1]` (the confirmation candle's close) but the stop is computed from data that includes the *next* bar's high/low. In a real engine this means: **signal fires on the close of bar X; enter no earlier than the open of bar X+1** (see §D.3).
- **Side effect:** the stop price is only computed when `showSL` is `true`; the RR projections are created *inside* the same block (L473), so **turning the stop off also turns the RR lines off**.

**Numbers:** default `"Wick"`.
**Classification:** STATE (but it is the *exit* definition, so it is effectively a gate on "is this trade a loser").

### R23 — Break-even level = the swing origin — [CODE] — STATE
```pine
475	                        if showBE
476	                            tr.bePrice := e.swingPrice
477	                            tr.beLine  := line.new(e.swingBar, e.swingPrice, x2, e.swingPrice, color = colorBE, style = line.style_solid)
478	                            tr.beLabel := label.new(x2, e.swingPrice, "B.E", style = label.style_label_left, color = noColor, textcolor = colorBE, size = size.small, text_font_family = font.family_monospace)
```
**Restatement.** `e.swingPrice` / `e.swingBar` are the origin recorded at R1 — the extreme of the pivot bar **one bar before** the 3-bar pivot bar. For a **long** (from an inverted bearish FVG) the BE is the **swing high**; for a **short** it is the **swing low**. Because R4 never resets `originBar` when the leg is broken, this level can be very old.

Note the asymmetry: the stop is the *window extreme*, the break-even is the *swing origin* — two different references.
**Classification:** STATE.

### R24 — Trade resolution (SL hit / BE hit) — [CODE] — STATE
```pine
502	ict_ManageTrades(array<Trade> trades) =>
503	    int n = trades.size()
504	    if n > 0
505	        for i = n - 1 to 0
506	            Trade tr = trades.get(i)
507	            if not tr.resolved
508	                bool slHit = tr.bullish ? (not na(tr.slPrice) and low <= tr.slPrice) : (not na(tr.slPrice) and high >= tr.slPrice)
509	                bool beHit = tr.bullish ? (not na(tr.bePrice) and high >= tr.bePrice) : (not na(tr.bePrice) and low <= tr.bePrice)
510	
511	                if slHit
...
530	                    trades.remove(i)
531	                else if beHit
...
539	                    trades.remove(i)
```
**Restatement.**
- Long: `slHit` when `low <= slPrice`; `beHit` when `high >= bePrice`. Short: `slHit` when `high >= slPrice`; `beHit` when `low <= bePrice`. Both are **inclusive** (`<=` / `>=`) and use the **current bar's** high/low.
- `slHit` takes precedence over `beHit` (checked first).
- On **either** resolution the SL/BE/RR drawings are deleted and the trade is removed from the active array. On `beHit` the setup box and entry line **remain** (only a BE "win" — the trade is considered finished at break-even).
- `ict_ManageTrades` is called on **every** bar, including the very bar the trade was created (the call order at pine:L662-672 is: track → check → **manage**). Therefore **a setup whose confirmation-detection bar itself made the window extreme is resolved as "stopped out" on that same bar** (for the `Wick` placement, `slPrice == that bar's extreme` ⇒ `low <= slPrice` is true by equality).

**Numbers:** inclusive comparisons; 1-bar-later bar semantics.
**Classification:** STATE.

### R25 — `hideLosing` post-hoc erasure — [CODE] — **the doc's warned-about behaviour, confirmed**
```pine
511	                if slHit
512	                    tr.resolved := true
513	                    line.delete(tr.slLine)
514	                    label.delete(tr.slLabel)
515	                    line.delete(tr.beLine)
516	                    label.delete(tr.beLabel)
517	                    ict_DeleteRR(tr)
518	                    f_detachHtfZone(tr)
519	                    if hideLosing
520	                        box.delete(tr.fvgBox)
521	                        line.delete(tr.entryLine)
522	                        label.delete(tr.entryLabel)
523	                        int recIdx = setupRecords.indexof(tr)
524	                        if recIdx >= 0
525	                            setupRecords.remove(recIdx)
526	                    else
527	                        line.set_color(tr.entryLine, colorSL)
528	                        label.set_textcolor(tr.entryLabel, colorSL)
529	                        label.set_color(tr.entryLabel, noColor)
530	                    trades.remove(i)
```
**Restatement.** When a setup's stop is hit:
- `hideLosing = true` (default): the FVG box, the entry line and the entry label are **deleted**, and the trade is removed from `setupRecords`. The setup **vanishes from the chart**. Nothing marks it as a loser. **This is exactly the "erase losing setups after the fact" behaviour the doc warns about** — and it is the default.
- `hideLosing = false`: the setup stays, but the entry line/label are recoloured to the stop colour.

Note this is **pure post-hoc erasure**: the decision to hide is made *after* the loss. It is not a predictive filter.
**Numbers:** default `true`.
**Classification:** GATE on *observability* — it does not change which signals fire, only which are visible.

### R26 — RR projection — [CODE] — DRAW (not an exit)
```pine
313	ict_CreateRR(Trade tr, int x1, int x2) =>
314	    if showRR and not na(tr.slPrice)
315	        ratios = ict_ParseFloats(rrInput)
316	        if ratios.size() > 0
317	            float riskRange = math.abs(tr.entryPrice - tr.slPrice)
318	            lns = array.new<line>()
319	            lbs = array.new<label>()
320	            for r in ratios
321	                float rrPrice = tr.bullish ? tr.entryPrice + riskRange * r : tr.entryPrice - riskRange * r
322	                lns.push(line.new(x1, rrPrice, x2, rrPrice, color = rrColor, style = rrLineStyle, width = rrWidth))
323	                lbs.push(label.new(x2, rrPrice, str.tostring(r) + "R", xloc = xloc.bar_index, style = label.style_label_left, color = na, textcolor = rrColor, size = textSize, text_font_family = font.family_monospace))
324	            tr.rrLines  := lns
325	            tr.rrLabels := lbs
```
```pine
304	ict_ParseFloats(string src) =>
305	    var out = array.new<float>()
306	    array.clear(out)
307	    for part in str.split(str.replace_all(src, " ", ""), ",")
308	        v = str.tonumber(part)
309	        if not na(v)
310	            out.push(v)
311	    out
```
**Restatement.** `rrInput` is parsed into a list of floats (spaces stripped, split on commas, unparseable parts dropped). For each ratio `r`, a horizontal line is drawn at `entry ± |entry - sl| * r`, labelled `"<r>R"`. Default `rrInput = "1,2"` ⇒ lines at 1R and 2R.

**These are drawing primitives only.** There is no take-profit order, no partial TP, no exit rule anywhere. `R` is defined as `|entry − stop|` using the *placed* stop (so it changes with `slPlacement`). The doc's "目标看向下一个流动性池" (target the next liquidity pool) and "固定 1:2 盈亏比" are **not implemented** — the RR line is a *visualisation* of a hypothetical 1:2, and the README says the author deliberately replaced nearest-liquidity TP with RR lines.

**Numbers:** default `"1,2"`.
**Classification:** DRAW.

### R27 — `setupHistory` display cap (with a management side-effect) — [CODE] — STATE
```pine
482	                        while setupHistory > 0 and setupRecords.size() > setupHistory
483	                            Trade oldest = setupRecords.shift()
484	                            int oldIdx = trades.indexof(oldest)
485	                            if oldIdx >= 0
486	                                trades.remove(oldIdx)
487	                            box.delete(oldest.fvgBox)
488	                            line.delete(oldest.entryLine)
489	                            label.delete(oldest.entryLabel)
490	                            line.delete(oldest.slLine)
491	                            label.delete(oldest.slLabel)
492	                            line.delete(oldest.beLine)
493	                            label.delete(oldest.beLabel)
494	                            ict_DeleteRR(oldest)
495	                            f_detachHtfZone(oldest)
```
**Restatement.** Default `setupHistory = 2`: only the **2 most recent** setups are kept drawn. When a third arrives, the oldest is shifted out, its drawings are deleted **and it is removed from the active-trade array** — so an **unresolved** setup that ages out of the window **stops being managed**: its stop is never tested, it is never resolved, and (because it is no longer in `activeTrades`) it is never erased either. It simply disappears.

`setupHistory = 0` disables the cap ("unlimited"). This is the replica's version of the original's "only shows 1-2 setups to keep charts clean" complaint (README §2). **The doc does not mention this at all.**
**Numbers:** default `2`, range 0–50.
**Classification:** STATE (display cap + a real behavioural side-effect).

### R28 — Candidate array cap — [CODE] — STATE
```pine
286	ict_PushCandidate(array<SwingFVG> arr, int fvgBar1, int fvgBar3, float top, float bottom, int oBar, float oPrice) =>
287	    SwingFVG sw = SwingFVG.new(fvgBar1, fvgBar3, top, bottom, oBar, oPrice)
288	    arr.push(sw)
289	    if arr.size() > MAX_TRACKED_SETUPS
290	        arr.shift()
291	    sw
```
**Restatement.** At most `MAX_TRACKED_SETUPS = 50` candidates per direction; the oldest is dropped when exceeded. A dropped candidate is dropped silently (never confirmed, never logged).
**Numbers:** 50.

---

# C. Gap analysis vs the design doc (`iFVG几个模型的讨论.txt`)

Legend: **ABSENT-in-code** = the doc's rule has no counterpart here (see §0.1 — the replica explicitly omits it). **MATERIAL** = >10 % on a threshold, or a rule present in code but absent from the doc.

| # | Rule | In code? | Doc location & stated value | Code value | Divergence | Material? |
|---|---|---|---|---|---|---|
| C-1 | **FVG geometry (3 candles)** | ✅ yes | L121 `c[i-2].high < c[i].low` bullish, 反之亦然 | `C.low > A.high` / `C.high < A.low`, strict, **wicks** | none — **agrees** | — |
| C-2 | **Inversion window** | ⚠️ partial | L122-123 "在 7 至 15 根 K 线内" | `graceCandles = 15` (or `6`); window **[0, 15]**, **no lower bound** | **The "7" does not exist.** Minimum age is 0 (the FVG's own newest candle may be the confirmation candle). The upper bound matches (15) but is measured from the FVG's **newest candle**, not from the FVG's **middle/oldest** candle. | **YES** |
| C-3 | **Body-close penetration of the far edge** | ✅ yes | L122-123 "实体收盘价彻底穿透…影线刺穿不算" | `close[1] > fvgTop` / `close[1] < fvgBottom`, **strict** `>`/`<` | agrees; the doc does not specify strict-vs-inclusive → code is strict | — (worth pinning) |
| C-4 | **Minimum gap `> 0.25 * ATR(14)`** | ❌ **absent** | L121, L280 "0.25 ATR 间距判定" | **no ATR anywhere in the file**; any strictly-positive wick gap qualifies | The replica omits it deliberately ("most sensitive setting by default"). **The doc's rule must be re-derived from the doc, not from code.** | **YES** |
| C-5 | **ATR lookback 14** | ❌ absent | L121 | — | same as C-4 | **YES** |
| C-6 | **Liquidity sweep: EQH / EQL / PDH / PDL** | ❌ **absent** | L117-118 "NQ 刺穿前期波段高点/低点（EQH/EQL/PDH/PDL）" | Sweeps are **HTF 3-bar fractal swing highs/lows** only (R9/R10). No equal-high/equal-low detection, no PDH/PDL, no session high/low anywhere. | **Completely different object.** The code's sweep is a *multi-bar HTF fractal*; the doc's is a *same-timeframe level cluster*. | **YES** |
| C-7 | **Sweep tolerance / "wick pierces, body doesn't"** | ⚠️ not implemented | implied by L118 ("扫止损") | Strict pierce of the bar's `high`/`low` vs the swing level. **No tolerance.** **No body condition** — the bar's close is never examined. | No proximity band, no reclaim requirement. | **YES** (a rule the doc assumes is *absent* from code) |
| C-8 | **SMT divergence (ES/YM cross-check)** | ❌ **absent** | L117-119; also the doc's description of the original | **No second instrument, no `request.security` cross-symbol call, no SMT.** The only `request.security` (L635) is same-symbol HTF FVG. | README: "I didn't bother coding … SMT on top of it". **The entire multi-instrument layer of the design doc has no code basis in this repo.** | **YES** |
| C-9 | **SMT score `+2`** | ❌ absent | L119 "信号基础权重 +2 分" | no scoring at all | — | **YES** |
| C-10 | **Checklist scoring A+/A/B/C** | ❌ **absent** | L124-126; "多重共振评分系统（A+ 至 C 级）" | **No score, no points, no cutoffs, no grades.** README: "Setup grade box — left out entirely." | **The entire "grade" concept is unverifiable from this repo.** | **YES** |
| C-11 | **Checklist: no uncleared opposing OB / equal-high-low in front** | ❌ absent | L125 | no OB concept, no equality detection | — | **YES** |
| C-12 | **Checklist: clear liquidity target ≥ 2R away** | ❌ absent | L126 | no target computation; RR lines are display-only, driven by the *placed stop*, not by a liquidity map | — | **YES** |
| C-13 | **Killzones 09:30–11:30 / 13:30–15:30 ET** | ⚠️ **not a filter** | L114-116 "仅在美东时间 09:30–11:30 及 13:30–15:30 激活" | Sessions exist but are **alert-only** (L497-498). Default session 1 = `0930-1600` NY. Sessions 2/3 = `2000-0000`, `0200-0500`, disabled. | **The doc's windows are a hard activation gate; the code has no session gate at all.** The code's `0930-1600` is a *different, wider* window and is not a gate. | **YES** |
| C-14 | **Timezone handling** | ✅ yes | L114-116 (implicit ET) | `NY_TZ = "America/New_York"` hard-coded (L79); sessions DST-aware; evaluated on the chart TF | agrees in spirit; code is explicit where the doc is not | — |
| C-15 | **HTF context: 15m/1H unreclaimed FVGs, Asian/London session levels** | ⚠️ partial | L114-116 | Only the **HTF FVG zone** exists (R17), as an *optional* gate (default off). No session-high/low tracking, no "unreclaimed" state. | — | **YES** |
| C-16 | **Stop beyond the recent swing high/low** | ⚠️ different object | L13 "止损通常设在近期的波段高低点外侧" | Stop = the **extreme of the FVG→confirmation window** (R22); the *swing origin* is the **break-even** level, not the stop. | **The two levels are swapped relative to the doc's description.** | **YES** |
| C-17 | **RR target 1:2 / target the next liquidity pool** | ⚠️ display-only | L13, L136 (phase-1: 固定 1:2 盈亏比) | `rrInput = "1,2"` draws 1R and 2R lines; **no TP order, no exit rule, no liquidity target**. README: "TP lines — I went with RR based targets instead of nearest liquidity." | **The code contains no take-profit logic whatsoever.** | **YES** |
| C-18 | **"Hide Losing Setups"** | ✅ yes | the doc's warning about the original | Present and **default `true`** (R25). Erasure = box + entry line + label deleted, record removed. | The doc's warning is **confirmed at code level**. | — (confirms the doc) |
| C-19 | **"only shows 1-2 setups to keep charts clean"** | ✅ yes | *not mentioned in the doc* | `setupHistory = 2` (R27) + the side-effect that evicted setups stop being managed. | **Code-only, undocumented, and it silently changes which setups get resolved.** | **YES** |
| C-20 | **"Require BE not breached on inversion"** | ✅ yes | *not mentioned in the doc* | `requireBEIntact = true` (R16) — **default on**: setups whose confirmation close has already reached BE are **never created**. This removes signals before they exist — a *predictive* filter, unlike `hideLosing`. | **Code-only, undocumented, and it changes the signal set.** | **YES** |
| C-21 | **"Only show IFVGs with HTF sweep"** | ✅ yes | *not mentioned* | `onlyShowSweptIFVG = false` (off by default) | code-only | (off by default) |
| C-22 | **"Only show IFVGs with HTF FVGs"** | ✅ yes | *not mentioned* | `onlyShowHtfAlignedIFVG = false` (off by default) | code-only | (off by default) |
| C-23 | **Bias filter (long-only / short-only)** | ✅ yes | *not mentioned* | `biasMode` (R21), default `Neutral` | code-only | (display/config) |
| C-24 | **Volume marker `volume[1] > SMA(volume,20)[1]`** | ✅ yes | *not mentioned* | Cosmetic `●` in the label (R18). **Not a filter.** | code-only, but harmless | no |
| C-25 | **`Single` vs `Series` FVG handling** | ✅ yes | *not mentioned* | R5: default `Single` keeps the largest gap per leg; `Series` merges consecutive gaps into a growing zone. | code-only; **changes the signal set materially** | **YES** |
| C-26 | **Leg freeze at the opposite pivot** | ✅ yes | *not mentioned* | R4: FVGs can only be created between the origin pivot and the opposite pivot (+1 bar), unless the leg is broken. | code-only, materially restricts where FVGs may form | **YES** |
| C-27 | **FVG search window `bar_index-3 >= originBar-1`** | ✅ yes | *not mentioned* | R3 | code-only | **YES** |
| C-28 | **Swing levels are consumed once** | ✅ yes | *not mentioned* | R10: a swept HTF swing level is removed from the set and can never be swept again. | code-only; a port that reuses levels will produce more sweeps | **YES** |
| C-29 | **HTF sweep timeframe map** | ✅ yes | *not mentioned* | R7: 1→15, 3→30, 5→60, 15→240, 60→1D, 240→1W, 1D→1M, else→1M. **A different map from the FVG one** (R19). | code-only | **YES** |
| C-30 | **`requireBEIntact` uses close, live BE uses high/low** | ✅ yes | *not mentioned* | R16 vs R24 — the two "BE reached" tests differ (close-inclusive vs high/low-inclusive) and can disagree. | code-only inconsistency | **YES** |
| C-31 | **Same-bar SL resolution artifact** | ✅ yes | *not mentioned* | R22+R24: the stop is computed from a window that includes the confirmation-detection bar, and `ict_ManageTrades` runs on that same bar ⇒ a setup whose detection bar is the window extreme is "stopped out" at birth (and erased if `hideLosing`). | code-only; **a live port that enters at the next open will not reproduce these instant losses.** | **YES** |
| C-32 | **`showSL = false` also kills the RR lines** | ✅ yes | *not mentioned* | R22/R26: `ict_CreateRR` is called inside the `if showSL` block. | code-only quirk | no (display) |
| C-33 | **Session windows `0930-1600` / `2000-0000` / `0200-0500`** | ✅ yes | *not mentioned* | R20, alert-only. | code-only | no (alert) |
| C-34 | **No cost/slippage model** | ✅ yes (absent) | AGENTS.md: `~$4.5` round-turn fees, 1–2 ticks slippage | The script is an `indicator()`; **zero** `strategy.*` calls; the cost model must live in the backtest config (AGENTS.md is right about this). | agrees | — |
| C-35 | **Pine version** | ✅ yes | the doc: original is "Pine Script v6" | `//@version=6` ✓ | agrees | — |

### C.1 Summary of the material divergences

**Against the doc (the doc claims something the code does not do):** C-2 (window), C-4/C-5 (ATR), C-6/C-7 (sweep object), C-8/C-9 (SMT), C-10/C-11/C-12 (scoring/checklist), C-13 (killzones), C-16 (stop reference), C-17 (no TP).

**Against the doc (the code does something the doc never mentions):** C-19, C-20, C-25, C-26, C-27, C-28, C-30, C-31, C-32.

**Root cause of the first group:** the replica's README states these were *deliberately omitted* by the author. The doc's claims are about the **closed-source original**, which we have never seen. **Do not treat "absent in code" as "absent in the original"** — but equally, do not treat the doc's numbers as code-verified.

---

# D. Porting notes — Python / NautilusTrader event-driven engine

## D.0 Pine constructs that need rework (general)

| Pine construct | Where | Non-repainting Python/Nautilus equivalent | Trap |
|---|---|---|---|
| `low[1]`, `close[1]`, `high[3]` (history offsets) | L352-356, L437, L441, L453 | Keep a rolling `deque`/pandas window of closed bars per instrument; index `[-2]`, `[-4]`. **Never** use the forming bar. | The whole indicator is written in terms of the *previous* bar. A naïve port that shifts everything by one bar will invert long/short. |
| `bar_index` | L294, L360, L377, L380-381, L450, L499 | A monotonically increasing integer counter per instrument, incremented on each **closed** bar. | Must be per-instrument and must count *bars*, not timestamps (gaps in data must not shift it). |
| `time(htf) != time(htf)[1]` | L592 | Compute the HTF bucket id from the bar's timestamp (floor to the HTF period) and compare with the previous bar's bucket id. | Must use **exchange-local** time or an explicit timezone for intraday HTF bucketing; CME session breaks mean a "1D" bucket is not a calendar day. |
| `ta.lowestbars(3) == -1` / `ta.highestbars(3) == -1` | L350-351 | `argmin`/`argmax` over the last 3 closed bars, returning the offset; treat offset `0` (current) as the "pivot" case. **See §E-1 for the offset convention.** | The `-1` is a *sentinel*, not an index. Getting this wrong shifts the origin by one bar. |
| `ta.sma(volume, 20)` | L85 | `volume.rolling(20).mean()` on closed bars. | Non-repainting as long as the window is complete; warm-up must be handled explicitly (no silent NaN). |
| `request.security(..., lookahead = barmerge.lookahead_off)` | L635 | Build the HTF series yourself from **closed** HTF bars and index it with an explicit `htf_index` that only advances when the HTF bar closes. | `lookahead_off` is the correct discipline. If you resample with pandas `resample()` you get **look-ahead by default** — label the HTF bar with its *open* time and only expose it after its close. |
| `hNewBar = hT2 != hLastSeenT2` | L638 | Same bucket-change detector on the HTF. | The HTF FVG must be published **one HTF bar late** (it uses `high[1]/low[1]/high[3]/low[3]` of the last *closed* HTF bar). |
| `barstate.islast` | L687 | Guard the watermark render on the final bar of the dataset. | Cosmetic only. |
| `alert(..., alert.freq_once_per_bar_close)` | L498 | Emit on bar close. | The session test (R20) must be evaluated on the **bar's timestamp**, not on wall-clock now. |
| `array<T>` / `type` / `method` (mutable objects) | throughout | Python dataclasses + `list`s, or explicit state dicts per direction. | Pine `array.remove(i)` while iterating `for i = n-1 to 0` is safe **only** because the loop runs backwards. A Python `for e in arr:` loop that removes elements will skip items — iterate over a snapshot. |
| `var` inside a function | L338-348 | Module-level state objects keyed by direction. | **See §E-2 — a Pine semantic that is not safe to assume.** |
| `strategy.*` calls | **none** | Real Nautilus orders: `MarketOrder` / bracket `StopMarketOrder` + `LimitOrder`. | The Pine has **no fills, no commission, no slippage**. The cost model belongs in the backtest config (AGENTS.md). |
| `syminfo.ticker`, `timeframe.period` | L498, L580 | Instrument id + bar type. | Two different "HTF" maps must be implemented separately (R7 vs R19). |
| Tick / pip size | — | NQ: tick 0.25 pt = $5.00/contract (MNQ $0.50); ES: 0.25 pt = $12.50. `Price` precision must match the instrument definition. | The replica does **no** price rounding — `slPrice`/`bePrice` are raw floats that can sit mid-tick. A real order must be rounded to the tick grid, and the rounding rule (nearest / away-from-entry) changes the R multiple. **Decide and document this.** |

## D.1 (Highest risk #1) The inversion trigger and its bar semantics — R13/R14/R15

**Pine construct:** `close[1] > e.fvgTop` evaluated on bar `X`, entry `lvl = close[1]`, `x1 = bar_index - 1`.

**Port:**
- On the close of bar `X`: if `close(X-1) > fvgTop` → the **confirmation candle is `X-1`** and the entry price is `close(X-1)`.
- The signal is *knowable* at the close of `X`. **You cannot fill at `close(X-1)`.** The honest port is: signal at the close of `X`, submit a market order that fills at the open of `X+1` (or at `close(X)` if you allow a bar-close fill — that is a different, more optimistic assumption and must be stated).
- Consequently, **the confirmation candle for the purpose of "how old is this FVG" is `X-1`**, and the age used for the `graceCandles` test is `X-1 − fvgBar1`.

**Trap:** the doc's 7-bar minimum is not implementable from this code (C-2). If we adopt the doc's `[7, 15]`, we must **add** the lower bound explicitly and say so; it is a doc-derived rule, not a code-derived one.

## D.2 (Highest risk #2) FVG detection and the leg window — R1/R2/R3/R4/R5/R28

**Pine constructs:** `ta.lowestbars(3)`, `ta.highestbars(3)`, `var` leg state, `bar_index - 3 >= originBar - 1`, the freeze.

**Port:** two independent `LegState` objects (`bullish`, `bearish`), each holding `origin_price`, `origin_bar`, `frozen`, `frozen_price`, `freeze_bar`, `live_candidate`, `cluster_last1`, `sweep_line_*`. Per bar, per direction:
1. Detect the pivot → if it fires, reset the leg exactly as L358-369 does (this also **discards the live candidate pointer** but *not* the candidate already in the array).
2. If the leg has an origin: apply the unfreeze test, then the FVG-window test, then the geometry test.
3. Push / merge / replace the candidate per R5.

**Traps:**
- The origin is `bar_index - 1`, **not** the extreme bar — a one-bar offset that silently moves the BE level and the window.
- The freeze release does **not** reset the origin, so an old origin can survive arbitrarily long. If the port resets the origin on unfreeze, the BE levels will differ.
- `Series` mode mutates `fvgBar1` forward, which changes (a) the age test and (b) the stop-scan window start.
- `Single` mode's "better gap" test removes the loser from the array — the loser then can never trigger, and its removal shifts indices (iterate backwards).

## D.3 (Highest risk #3) Stop placement, resolution, and the erasure switch — R22/R24/R25

**Pine constructs:** `ict_ScanExtreme` (a `for j = 0 to span` loop over `low[span-j]`), `slPlacement` switch, `ict_ManageTrades` called on the same bar the trade was created.

**Port:**
- Compute the window `[fvgBar1, X]` extremes at the close of `X` (X = the confirmation-detection bar). Long → `min(low)`, short → `max(high)`.
- Apply the `slPlacement` switch (Wick / Body / IFVG) with the same strict/non-strict comparisons.
- **Do not** evaluate the stop against bar `X`'s own range if you intend to fill at `X+1`'s open — the Pine's same-bar evaluation is an artifact (C-31). Two defensible ports:
  - **(a) faithful-to-Pine:** evaluate the stop on bar `X` using bar `X`'s low/high ⇒ setups whose detection bar is the window extreme are instant losers (and erased when `hideLosing`).
  - **(b) live-honest:** enter at `X+1`'s open, then evaluate the stop from `X+1` onwards.
  **The two produce materially different P&L. Pick one, write it down, and make it a config flag** — this is exactly the "faithfulness vs realism" trade-off the phase-1 gate depends on.
- **Never implement `hideLosing` as a filter.** Log every candidate with its outcome; `hideLosing` is a *visualisation* flag. In Nautilus this is a logging/metrics decision, never a deletion of the event.
- Round the stop to the instrument's tick grid and record the pre-rounding value too — the R multiple changes.

## D.4 (Highest risk #4) The HTF sweep detector — R7/R8/R9/R10/R11

**Pine constructs:** manual HTF aggregation with `time(htf) != time(htf)[1]`, `ta.highestbars`-style fractal on the HTF series, `findSweep` **mutating** the swing set.

**Port:**
- Build HTF bars from the LTF bar stream (or from a separate HTF bar stream) with **explicit bucket boundaries**; store for each completed HTF bar: `high`, `low`, and the **LTF bar timestamp at which each extreme occurred** (the Pine keeps one timestamp per extreme, updated only on a *strict* new extreme).
- Detect the 3-bar fractal on the completed HTF series with `>=`/`<=` (ties count) and publish it **two HTF bars later**.
- **The destructive part is the trap:** `findSweep` *removes* every swept point. A port that merely flags sweeps will produce a different number of sweeps (a level can be swept many times in the port, once in the Pine). This is not cosmetic: it changes `swept`, hence the `onlyShowSweptIFVG` gate, hence the signal set.
- The sweep test uses the current bar's `high`/`low` — an **inclusive** current-bar value, and the swept points are consumed **even when no leg is active**. Reproduce the consumption unconditionally, then apply the leg association afterwards.

## D.5 (Highest risk #5) Break-even level and the BE-intact gate — R16/R23/R24

**Pine constructs:** `e.swingPrice` (the origin), `requireBEIntact` at confirmation, `beHit` in `ict_ManageTrades`.

**Port:**
- `be_price = origin_price` of the leg (the pivot extreme recorded at L359-360) — **not** the stop, and **not** the FVG edge.
- The confirmation-time gate: long ⇒ reject if `close(confirmation) >= be_price`; short ⇒ reject if `close(confirmation) <= be_price`. **Inclusive.** The gate happens *before* the trade object is created — so in Nautilus it is a **signal filter**, and the rejected setup must still be **logged** (AGENTS.md: "Never delete or hide failed signals").
- The live resolution uses the bar's high/low, not the close — a long's BE is hit when `high >= be_price`. The two tests disagree by design; port both, separately.
- Because the origin is not reset on unfreeze (D.2), `be_price` can be an old swing. Reproduce, and log the origin bar index with every setup so the staleness is auditable.

## D.6 (Highest risk #6) HTF FVG confluence gate — R17

**Pine constructs:** `request.security` with `lookahead_off`, the `hNewBar` detector, `f_findHtfOverlap` (inclusive overlap), zone mitigation.

**Port:**
- Compute HTF FVGs from **closed** HTF bars only, using the same `prev_low > htf3_high` / `prev_high < htf3_low` geometry, publishing one HTF bar after the HTF bar closes.
- Maintain a zone list with `mitigated` flags (mitigated when `low < zone.bottom` for a bullish zone, `high > zone.top` for a bearish one) and a `maxHtfZones` cap of 3 with the `keepAlive` exemption for attached zones.
- The gate is a **price-band overlap test** between the IFVG zone and any live HTF zone: `not (bottom > z.top or top < z.bottom)` — inclusive on both edges.
- Default is **off**; if we turn it on we are changing the signal set and must say so in the phase-1 report.

## D.7 Pine-semantics hazards that need a decision (not a rewrite)

1. **`var` inside a function called from two call sites** — see §E-2. The whole `ict_TrackLine` leg state (`originPrice`, `originBar`, `frozen`, `liveEntry`, `clusterLast1`, `sweepLn*`) is declared `var` **inside** the function, and the function is called once per direction per bar. If Pine shares that state between the two call sites, the two directions clobber each other (e.g. the bearish tracker would inherit the bullish tracker's origin and its `frozen` flag). **The port must implement per-direction state** (which is certainly the author's intent — note the deliberate use of *passed-in* arrays and the `SwingSet` object for the shared-by-design state). But the replica's *rendered output* may differ from that intent, so a chart-vs-code reconciliation is required before we trust any backtest derived from this file.
2. **`request.security` on the HTF-FVG only** — everything else (sweeps) is hand-rolled. A port that resamples with pandas will get subtly different HTF bars (session boundaries, DST, holidays). Use the exchange session calendar.
3. **`session` handling** — `input.session("0930-1600", ...)` with `NY_TZ` is DST-aware and evaluated per chart bar. A port that uses a fixed UTC offset will be wrong for ~2 months a year.
4. **`barstate.islast` / `alert.freq_once_per_bar_close`** — the alert fires on the *close of the detection bar `X`*, but the message describes the confirmation candle `X-1`. Preserve the bar index in the log.

---

# E. Open questions / verification checklist

| # | Question | Why it matters | How to close it |
|---|---|---|---|
| E-1 | **What exactly does `ta.lowestbars(3) == -1` mean?** If `-1` means "the current bar is the extreme", the recorded origin (`bar_index-1`) is one bar *before* the actual swing. If it means "the extreme was 1 bar ago", the origin is the swing itself. | The origin sets the BE level and the FVG search window → every setup's BE and every candidate's admissibility. | Render the replica on a chart with the IFVG boxes + BE lines and check whether the BE line sits at the swing high/low or one bar inside it. Alternatively port both variants and compare the setup sets. |
| E-2 | **Does Pine share function-local `var` state across call sites?** | If yes, the replica's two directions interfere and its output is not the "intended" algorithm. | Port per-direction state (correct intent), then reconcile against the replica's chart output on a fixed symbol/timeframe. If they disagree, the discrepancy *is* the answer to E-1/E-2 combined. |
| E-3 | **Does the original (closed source) really implement ATR-0.25, SMT and the A+..C grading?** The doc says yes; the replica says the author omitted them on purpose. | The whole four-layer architecture (meta-labeling features, "checklist score" feature) is built on the doc's claim. | We cannot read the original. Decide explicitly: implement the doc's rules as *additional* filters on top of the code-derived core, label them "doc-derived, unverified", and measure each one's marginal contribution separately. **Never present them as code-verified.** |
| E-4 | **Is the lower bound of 7 bars real in the original?** The replica's own input title says "Allow 7 - 15 Candle IFVGs" but implements `[0,15]`. | Removing the 0-age confirmations changes the signal count and the win rate materially. | Implement the window as a config `[min_age, max_age]` with `(0,15)` as the code-derived default and `(7,15)` as the doc-derived variant; A/B them in phase 1. |
| E-5 | **Which entry assumption?** `close(X-1)` (Pine's fiction) vs `open(X+1)` (live-honest). | Decides whether the same-bar stop artifact (C-31) exists. | Make it a config flag and report phase-1 numbers under both. |
| E-6 | **Should `hideLosing` and `setupHistory` be reproduced at all?** | They are display features with real side-effects (R25, R27). | **No.** Log everything; never delete a signal. Reproduce them only in the chart renderer, never in the event/log path. |
| E-7 | **The doc's "SMT +2 points" and "A+/A/B/C" have no code.** | The meta-labeling feature list (AGENTS.md) includes "checklist score" and "SMT flag" — those features cannot be produced from this repo. | Emit the code-derived features (grade-relevant proxies: gap width, FVG age at inversion, sweep flag, HTF-FVG overlap flag, BE-intact flag, volume ratio) and add the doc-derived features only as clearly-labelled proxies. |

---

## Appendix — provenance and integrity

- The cloned repo was **read only**; nothing in `research/github/IFVG-Ultimate-Dodgy/` was modified. No `.pine` file was executed; no TradingView/Pine interpreter was run.
- `research/docs/RULE_SPEC.md` (the sibling worker's prose-derived spec) treats the Pine file as **non-normative** ("[X-ART] … Not normative — the discussion wins"). **This document takes the opposite stance**: where the code and the prose disagree, the code is the better evidence of *implemented* behaviour, and the disagreement is reported explicitly in §C rather than silently resolved.
- Citation convention: `pine:L###` = line number in `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` @ `bdc0b04`.
