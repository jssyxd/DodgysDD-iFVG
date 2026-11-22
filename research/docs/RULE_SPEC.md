# RULE_SPEC.md — Canonical DodgysDD iFVG Rule Specification

**Status:** extracted from `iFVG几个模型的讨论.txt` (283 lines, UTF-8/CRLF) — the single source of truth.
**Scope:** strategy semantics (deterministic core), system semantics (four-layer EV stack), traceability.
**Audience:** implementers (state machine, vision, ML, RL) and the reviewer agent, who will check every
claim against the cited line numbers.

### 0.1 Source and citation conventions

| Tag | Meaning |
|---|---|
| **[DOC]** | Stated verbatim (or as an unambiguous numeral) in the discussion. |
| **[DOC-SVG]** | Stated only in one of the two attached diagrams (`diagram-四层正 EV 量化系统完整架构.svg`, `diagram-目录结构规划.svg`), **not** in the discussion prose. |
| **[DERIVED]** | Logically forced by the discussion, but never written down. |
| **[UNSPECIFIED]** | The discussion needs a value and does not give one. Every such item has an ID (`A01`…`A30`), a proposed default, and a one-line rationale (§1.6). |
| **[X-ART]** | Cross-checked against a secondary artifact already present in the repo (`research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine`, `research/huggingface/nq-fvg-detector/README.md`). Cited as `pine:NNN`. **Not** normative — the discussion wins; the artifact only settles *how* to read the discussion. |

Line citations are `L<n>` for the discussion file. Diagram citations are `SVG-A:n` (four-layer) and
`SVG-B:n` (directory plan). Artifact citations are `pine:NNN` / `hf:NNN`.

### 0.2 Notation

- `c[i]` — the i-th closed bar of the **traded** timeframe (1-minute by default, L169). `c[i-2]`, `c[i-1]`,
  `c[i]` are the three FVG candles, oldest → newest; `c[i-1]` is the displacement candle.
- `gap_size` — for a bullish FVG `c[i].low - c[i-2].high`; for a bearish FVG `c[i-2].low - c[i].high`.
- `ATR(14)` — see `A02`/`A03` for the exact definition (anchor bar, smoothing, warm-up).
- `R` — risk unit = distance from entry to stop for that trade (L126 uses "2R" as a distance).
- `ET` — `America/New_York`, DST-aware (see `I08` for the EST/ET contradiction in the doc).
- All inequalities below are **strict** unless explicitly marked `≤` / `≥`.

---

## 1. Part A — Strategy semantics (the deterministic core)

### 1.1 What the strategy is (concept)

The doc's framing is **reaction, not prediction** (L3, L86):

- A classical FVG is three bars where the middle bar's displacement leaves the first and third bars' wicks
  non-overlapping, forming a price-imbalance band (L5).
- iFVG is "wait for failure": price retests a **bullish** FVG, fails to hold it as support, and instead
  **breaks it down with a solid body candle**; the former support band **inverts into a resistance band**
  (L6).
- The trade is then taken in the new direction, stop beyond the recent swing extreme, target the next
  liquidity pool (L13).

Everything below is the mechanical rendering of that sentence.

### 1.2 Exact FVG geometry (unambiguous inequalities)

Source: **L121** — `• 扫荡发生前的最后一段推进波中，识别 3 根 K 线构成的常规 FVG（Candle[i-2].high < Candle[i].low 为看涨 FVG，反之亦然），且缺口大小必须大于 0.25 * ATR(14)。`
Corroborated by L5 (`第一根与第三根 K 线的影线没有重叠`) and L280 (`0.25 ATR 间距判定`).

**Bullish FVG (support band) — [DOC] L121, L5**

```
c[i-2].high  <  c[i].low            # STRICT; equality (zero-width gap) is NOT an FVG
G_bull       =  [ c[i-2].high , c[i].low ]      # lower edge = c[i-2].high, upper edge = c[i].low
gap_size     =  c[i].low - c[i-2].high
valid  ⟺  gap_size > 0.25 * ATR(14)            # L121: "必须大于" = strictly greater
```

**Bearish FVG (resistance band) — [DOC] L121 ("反之亦然")**

```
c[i-2].low   >  c[i].high            # STRICT
G_bear       =  [ c[i].high , c[i-2].low ]      # lower edge = c[i].high, upper edge = c[i-2].low
gap_size     =  c[i-2].low - c[i].high
valid  ⟺  gap_size > 0.25 * ATR(14)
```

Decisions that the doc leaves implicit, stated here once:

| Decision | Value | Basis |
|---|---|---|
| Strict vs inclusive comparison | **Strict** (`<` / `>`) | L121 writes `<`; L5 requires the wicks *not to overlap* (a zero-width gap is not a gap). A bar that merely touches (`c[i-2].high == c[i].low`) is **not** an FVG. |
| Which edge is which | `c[i-2]` side = the **older** boundary; `c[i]` side = the **newer** boundary | L121 notation |
| The gap must exceed the ATR floor | `>` (not `≥`) | L121 "必须大于" |
| Gap size is measured **edge to edge** (full band width), not wick-to-wick of the middle candle | yes | L121 "缺口大小" |

### 1.3 The inversion (iFVG) predicate — the trigger of the whole system

Source: **L123** — `• 价格反向运行，在 7 至 15 根 K 线内，出现一根实体收盘价（Body Close）彻底穿透该 FVG 远端边界（仅仅影线刺穿不算反转）的 K 线。`
Supporting: L6 (bullish support fails and is broken down → becomes resistance), L12 (`用一根收盘价彻底穿过该 FVG 区域的 K 线将其"破坏"`).

**Definition of "far edge" (远端边界) — [DERIVED] from L6 + L123, cross-checked `pine:437`:**
the far edge is the boundary of the gap that lies **opposite to the direction the price travelled into the
gap**. A downside break of a support band must clear the band's **lower** edge; an upside break of a
resistance band must clear the band's **upper** edge. For our geometry that is always the `c[i-2]` side.

| FVG | Inversion direction | Far edge | Trigger predicate (on bar `k`) |
|---|---|---|---|
| Bullish `G_bull = [c[i-2].high, c[i].low]` | becomes **resistance** → **SHORT** | `c[i-2].high` (lower edge) | `close[k] < c[i-2].high` |
| Bearish `G_bear = [c[i].high, c[i-2].low]` | becomes **support** → **LONG** | `c[i-2].low` (upper edge) | `close[k] > c[i-2].low` |

Corroboration: `pine:437` — `bool trigger = sourceBearish ? close[1] > e.fvgTop : close[1] < e.fvgBottom;`
where for a bullish-source FVG `fvgBottom == high[3] == c[i-2].high`, and for a bearish-source FVG
`fvgTop == low[3] == c[i-2].low`. The artifact uses exactly the inequalities above, with the **close of the
last completed bar** (`close[1]`) — i.e. the decision fires on bar close, never intra-bar.

Consequences fixed by this table:

- A wick-only penetration never triggers (L123 `仅仅影线刺穿不算反转`): because the predicate is on
  `close`, a bar whose *wick* cleared the far edge but whose close did not is rejected.
- Equality (`close[k] == far edge`) is **not** a trigger — see `A01`.
- The confirming bar must be **strictly after** `c[i]` (`k > i`); the FVG must be complete (bar `c[i]` closed)
  before the trigger bar is evaluated.

### 1.4 The 5-step state machine

The doc's own framing: build a pure rule engine named `DodgysDDStateMachine` that follows "the following 5
steps of state transition" and that **completely eliminates after-the-fact erasure of invalidated signals**
(**L113**). Name and purity are [DOC] L113.

The class is a **pure function of the bar history** (no I/O, no engine calls) so it is unit-testable
without a backtest — this is a repository convention from `AGENTS.md`, consistent with L113's "纯规则引擎".

---

#### Step 1 — HTF context & killzones (大周期背景与时间窗口) — L114–L116

```
1. 大周期背景与时间窗口（HTF & Killzones）：
   • 仅在美东时间 09:30–11:30（NY AM Session） 及 13:30–15:30（NY PM Session） 激活。
   • 标记前日高低点（PDH/PDL）、亚洲/伦敦盘高低点、以及 15m/1H 级别的未回补 FVG。
```

| | |
|---|---|
| **Precondition** | Bar stream for the traded instrument and the reference instrument is aligned and monotonic; previous session's aggregates are available. |
| **Exact predicate** | `killzone(bar_close_ts_et) == true` where `killzone = (09:30 ≤ t ≤ 11:30) ∨ (13:30 ≤ t ≤ 15:30)` [DOC L115]. **Endpoint-inclusive** (decision; see `A21`). Evaluated on the bar's **close** timestamp, not its open, so a bar straddling 11:30 is judged by when it closed. |
| **State carried forward** | `pdh`, `pdl` (previous day high/low), Asian-session high/low, London-session high/low, unreclaimed 15m and 1H FVG zones [DOC L116], `session_id` (RTH date), `bars_in_session`. |

#### Step 2 — Liquidity sweep + SMT divergence (前置条件 A) — L117–L119

```
2. 前置条件 A —— 流动性扫荡（Liquidity Sweep）与 SMT 背离：
   • NQ 刺穿前期波段高点/低点（EQH/EQL/PDH/PDL）。
   • 交叉验证： 同步检查 ES（或 YM）在同一波段是否未能创出新高/新低。若出现 SMT 背离，信号基础权重 +2 分。
```

| | |
|---|---|
| **Precondition** | Swing levels exist: prior pivot highs/lows (EQH/EQL) plus PDH/PDL from Step 1. Reference instrument (ES or YM) bars are available on the same timeline (L92: subscribe NQ + ES in one strategy instance, nanosecond timestamp alignment). |
| **Exact predicate (sweep)** | ∃ level `L` such that `high[k] > L` (sweep of a high) or `low[k] < L` (sweep of a low) — a **strict pierce** by ≥ 1 tick, not a touch (`A07`). |
| **Exact predicate (SMT)** | On the same leg, the reference instrument (ES or YM) **did not** make a new high (for an NQ high sweep) / new low (for an NQ low sweep) → `smt_divergence = true` → **`score += 2`** [DOC L119]. "Same leg" is undefined (`A08`). |
| **State carried forward** | `sweep_direction` (up/down), `swept_level`, `sweep_bar`, `smt_flag`, `score = 2` if SMT else 0. |

#### Step 3 — Initial (opposite-direction) FVG identification (前置条件 B) — L120–L121

```
3. 前置条件 B —— 反向初始 FVG 识别（Singular FVG）：
   • 扫荡发生前的最后一段推进波中，识别 3 根 K 线构成的常规 FVG（Candle[i-2].high < Candle[i].low 为看涨 FVG，反之亦然），且缺口大小必须大于 0.25 * ATR(14)。
```

| | |
|---|---|
| **Precondition** | The FVG must belong to the **last impulse leg before the sweep** (`扫荡发生前的最后一段推进波中`, L121) → its `c[i]` bar index is ≤ the sweep bar index, and the FVG must be the **most recent** qualifying one (`标记出最近的一个反向 FVG 区域`, L11). Its direction must be **opposite** to the sweep (`最近的一个反向 FVG`, L11). See `A12`/`A13`. |
| **Exact predicate** | Geometry per §1.2 (`c[i-2].high < c[i].low` bullish / `c[i-2].low > c[i].high` bearish) **and** `gap_size > 0.25 * ATR(14)`. |
| **State carried forward** | `fvg_dir` (bullish/bearish), `gap_low`, `gap_high`, `fvg_c1_idx`, `fvg_c3_idx`, `gap_size`, `atr14`, `trade_direction` (opposite of `fvg_dir`, i.e. sweep-of-high → SHORT). |

#### Step 4 — Inversion confirmation (核心触发) — L122–L123

| | |
|---|---|
| **Precondition** | Step 3 passed and the candidate has not expired: `k - anchor ≤ max_bars` and (if the minimum is enforced) `k - anchor ≥ min_bars` (`A04`, `A05`). |
| **Exact predicate** | `close[k] < c[i-2].high` for a bullish FVG (→ SHORT) / `close[k] > c[i-2].low` for a bearish FVG (→ LONG) — §1.3. |
| **State carried forward** | `confirm_bar`, `confirm_close`, `entry_price_candidate` (= `close[k]`, `A14`), `direction`. |

#### Step 5 — Structural purification & target confirmation (结构净化与目标确认, Checklist 评分) — L124–L126

```
5. 结构净化与目标确认（Checklist 评分）：
   • 无阻挡检查： 确认入场方向前方没有未清理的反向订单块（OB）或紧贴的等高/等低点阻挡。
   • 明确流动性目标（Draw on Liquidity）： 距离入场位至少 2R 处存在明确的 EQH/EQL、未触及的时段高低点或单边流动性（LRLR）。
```

| | |
|---|---|
| **Precondition** | Step 4 produced a direction and an entry price. Stop placement is resolved first, because R depends on it (`A15`). |
| **Exact predicate (a) no obstacle** | No uncleared opposing order block, and no *tightly adjacent* equal-high/equal-low, lies in the entry direction between entry and target (`紧贴的` = "tightly adjacent" — proximity tolerance undefined, `A09`). |
| **Exact predicate (b) target** | ∃ a liquidity target (EQH/EQL, untouched session high/low, or one-sided liquidity LRLR) at distance `≥ 2R` from entry [DOC L126 `距离入场位至少 2R`]. |
| **State carried forward** | `checklist_flags`, `checklist_score`, `grade ∈ {A+, A, B, C}`, `target_level`, `target_distance_R`, `stop_price`, `risk_per_unit`. |

**Grading** — the doc states the grades exist but never defines them: L45 (`多重共振评分系统（A+ 至 C 级）`),
L107 (`仅接受 A+ 级带 SMT 背离信号`), L170 (`Checklist 过滤（只做 A/A+ 级）`). See `A09`/`A10` — this is
one of the highest-impact gaps.

### 1.5 Threshold register (every number in the discussion, with source line)

| ID | Threshold / value | Tag | Source | Note |
|---|---|---|---|---|
| T01 | FVG geometry: `c[i-2].high < c[i].low` (bullish), inverse (bearish) | [DOC] | L121 | §1.2 |
| T02 | Min gap `> 0.25 * ATR(14)` | [DOC] | L121, L280 | anchor/`A02` |
| T03 | ATR lookback `14` | [DOC] | L121 | smoothing/warm-up `A03` |
| T04 | Inversion window `7 … 15` bars | [DOC] | L123; also L45, L280, SVG-B | contradicted by L73 → `I01`; anchor `A04`; band-vs-max `A05` |
| T05 | Killzone NY AM `09:30–11:30` ET | [DOC] | L115 | inclusive `A21` |
| T06 | Killzone NY PM `13:30–15:30` ET | [DOC] | L115 | inclusive `A21` |
| T07 | VXN regime bins `[0, 18, 28, 200]` → labels `0/1/2` | [DOC] | L265–L266 | code form; prose form L107–L109 → `I05` |
| T08 | VXN low-vol `VXN < 18` | [DOC] | L107 | |
| T09 | VXN normal `18 ≤ VXN ≤ 28` | [DOC] | L108 | boundary conflict `I05` |
| T10 | VXN high `VXN > 28` | [DOC] | L109 | |
| T11 | VXN low-vol policy: A+ only **with** SMT; RR `1:1.5 ~ 1:2` | [DOC] | L107 | |
| T12 | VXN normal policy: RR `1:2.5 ~ 1:3`, target = opposite-side liquidity pool | [DOC] | L108 | |
| T13 | VXN high-vol policy: halve risk (`1% → 0.5%`), larger min ATR gap | [DOC] | L109 | larger gap value unspecified `A19` |
| T14 | SMT divergence weight `+2` | [DOC] | L119 | |
| T15 | Grades `A+ / A / B / C` | [DOC] | L45, L107, L170 | thresholds undefined `A09`/`A10` |
| T16 | Liquidity target `≥ 2R` from entry | [DOC] | L126 | |
| T17 | Meta-label label: `1 = 达到2R止盈`, `0 = 触发止损` | [DOC] | L143 | |
| T18 | Meta-label gate `P(Win) < 0.58` → abandon trade | [DOC-SVG] | SVG-A (`若 P(Win) < 阈值 (如 0.58)，直接拦截放弃交易`) | **absent from the discussion prose** — see §2.3 |
| T19 | Visual IoU gate `> 0.75` (and `规则引擎触发 == True`) | [DOC] | L139 | |
| T20 | Vision "filters ~35% of false-breakout noise" | [DOC] | L139 | asserted, no evidence in doc |
| T21 | Chart window: last `60` indicator-free candles | [DOC] | L137, L274, L279 | |
| T22 | Render size `224×224` | [DOC] | L137 | model input is 640×640 → `A20` |
| T23 | "Visual Clarity Score" (视觉形态置信度) | [DOC] (named) | L138 | formula undefined `A16` |
| T24 | Walk-forward: train `6` months / validate `1` month / test `1` month, rolled monthly | [DOC] | L145 | embargo length `A17` |
| T25 | Purged walk-forward with embargo (时间隔离带) | [DOC] | L282 | length `A17` |
| T26 | Meta-label features: checklist score, SMT flag, visual confidence, VXN level, **VXN 1-hour change rate**, bars from FVG formation to inversion, minutes from US open | [DOC] | L146 | 1h-change source `A18` |
| T27 | RL: position management only, **must never open a position** | [DOC] | L150 | hard invariant §2.2 |
| T28 | RL state: open PnL in R, VXN regime, holding time, order-book imbalance | [DOC] | L151 | |
| T29 | RL reward: Sortino-like; extra penalty for reaching `1.5R` then failing to move the stop | [DOC] | L152 | |
| T30 | RL action space: position multiplier + dynamic BE trigger + partial TP ratio; multipliers `0.5x, 1.0x, 1.5x` | [DOC-SVG] | SVG-A | |
| T31 | Migration target Sharpe `> 1.8`, max drawdown `< 10%` (sample-out-of-sample) | [DOC] | L156 | |
| T32 | Phase-1 gate: Profit Factor `> 1.25`, EV must be positive | [DOC] | L170 | |
| T33 | Phase-1 cost model: `~$4.5` round-trip fees, `1–2 Tick` slippage | [DOC] | L170 | |
| T34 | Phase-1 RR: fixed `1:2`; setups `A/A+` only | [DOC] | L170 | |
| T35 | Phase-2 goal: win rate from `~45%` → `> 55%`, materially lower max drawdown | [DOC] | L173 | |
| T36 | Phase-3: `4` weeks forward paper trading on IB / Tradovate / Rithmic | [DOC] | L175 | |
| T37 | MES min-gap ATR coefficient `0.25 → 0.20` | [DOC] | L160 | |
| T38 | GC windows: London `03:00 EST`, COMEX `08:20 EST` | [DOC] | L162 | |
| T39 | BTC/ETH: 24/7; sweeps concentrate `09:30 EST` and `UTC 00:00` | [DOC] | L163 | |
| T40 | QQQ: overnight gap (盘前跳空缺口) as primary liquidity target | [DOC] | L161 | |
| T41 | HTF context levels: PDH/PDL, Asia/London session highs/lows, unreclaimed 15m/1H FVGs | [DOC] | L116 | |
| T42 | Signal integrity: no post-hoc erasure of invalidated setups | [DOC] | L113, L49, L70, L172 | hard invariant §2.2 |
| T43 | Phases 1/2/3 durations: weeks 1–2 / 3–4 / 5–6 | [DOC] | L168, L171, L174 | |
| T44 | Reference instruments: ES (or YM) for SMT; multi-contract subscription in one strategy | [DOC] | L92, L119, L169 | |
| T45 | Baseline risk per trade `1%` of equity | [DERIVED] | L109 (`从 1% 降至 0.5%` implies a 1% baseline) | |
| T46 | Risk 0.5% in high-vol regime | [DOC] | L109 | |
| T47 | Data: NQ + ES 1m/5m ticks/bars + VXN | [DOC-SVG] | SVG-A | |
| T48 | Data source: Databento DBN (~`$10–$30` for years of NQ/ES continuous) | [DOC] | L206 | cost, not a strategy threshold |
| T49 | VXN lag: `Close.shift(1).bfill()` (previous day's close = today's known state) | [DOC] | L207, L261–L262 | |
| T50 | VXN retrieval: CBOE / Databento / yfinance `^VXN`, daily **or** intraday, forward-filled + 1-bar lag | [DOC] | L207 | code builds daily only → `A18` |
| T51 | Direction of control: rules decide direction, ML filters, RL manages | [DOC] | L86, L101, L143, L150 | hard invariant §2.2 |

### 1.6 Ambiguity register / [UNSPECIFIED] items — the open decisions

Each entry: the underdetermined question, the evidence, a **proposed default**, a one-line rationale, and an
impact rating (**H** = changes which trades are taken / changes P&L materially, **M** = changes behaviour in
a subset of cases, **L** = cosmetic/config).

| ID | Question | Evidence | Proposed default | Rationale | Imp. |
|---|---|---|---|---|---|
| **A01** | What exactly does "实体收盘价彻底穿透该 FVG 远端边界" mean — close *beyond* the far edge, or *equal* to it? | L12, L123 | **Strict**: `close[k] < far_edge` (bearish inversion) / `close[k] > far_edge` (bullish inversion). Equality does **not** trigger. | "彻底穿透" = *thoroughly penetrates* implies going past, and the artifact uses strict `<`/`>` (`pine:437`). | **H** |
| **A02** | Which bar's ATR(14) is used for the gap floor? | L121 | ATR(14) computed on the **traded timeframe** as of the **close of the FVG's third candle `c[i]`** (the bar at which the gap becomes known). | The gap is measured when it forms; using a later ATR would be look-ahead. | **H** |
| **A03** | ATR definition: smoothing method, and the warm-up rule | L121 | Wilder RMA (`alpha = 1/14`) over the last 14 closed bars; require ≥ 14 prior closed bars, else **no signal** (not a zero-ATR signal). | Wilder RMA is the de-facto TA standard; the warm-up rule prevents `ATR=0` from passing every gap floor. | **H** |
| **A04** | Does the 7–15 bar window count from **FVG formation** or from the **sweep**? | L121, L123 | Count from the **FVG's third candle `c[i]`** (the bar at which the FVG becomes knowable). The sweep must occur *within* the same window. | The FVG is a prerequisite of the sweep (L121), so its own clock is the only one guaranteed to start first; the artifact's expiry clock also runs from the FVG bar (`pine:499`). | **H** |
| **A05** | Is `7 至 15` a **band** (min 7, max 15) or a **maximum** of 15? | L123 ("7 至 15"), L45 ("7–15"), L73 ("15根K线内") | Implement `INVERSION_MIN_BARS` / `INVERSION_MAX_BARS` as **separate constants**; normative default from the doc = **(7, 15)**; **flag that the doc contradicts itself** (`I01`) and that the artifact implements max-only with an off-by-one (`pine:658`, `pine:499`). | A hard minimum of 7 bars kills setups whose sweep arrives late; the doc's own L73 says "within 15". Keep both knobs so the fleet can A/B it. | **H** |
| **A06** | What is "the last impulse leg" (`最后一段推进波`)? | L121 | The contiguous run of bars ending at the sweep bar, bounded backwards by the most recent opposing pivot; the FVG must have its `c[i]` inside that run and be the **most recent** qualifying FVG at the sweep. | L121 + L11 ("最近的一个"). | **M** |
| **A07** | How are EQH/EQL detected — exact touch or proximity? | L118 (`刺穿`) | **Strict pierce**: `high > level` (or `low < level`) by ≥ 1 tick; the level is **consumed** on first sweep (one-shot). Swing levels = 3-bar pivots on the HTF (auto 15m for a 1m chart). | "刺穿" = pierce; the artifact removes the swept level from the set (`pine:560`, `pine:567`). | **H** |
| **A08** | What is "the same leg" for the SMT comparison, and which reference instrument (ES **or** YM)? | L119 | Compare on the **same impulse leg**, defined as the bar range between the reference instrument's last extreme and the sweep bar; SMT = reference did **not** make a new extreme in that range. Reference = **ES** by default, YM as fallback. | L119 names both without a rule; one default is needed for determinism. | **M** |
| **A09** | What are the checklist score thresholds per grade (A+/A/B/C)? | L45, L107, L124–L126, L170 | Concrete rubric (§1.7): base 0; **+2** SMT divergence (L119); **+1** no opposing OB in front; **+1** clear target ≥ 2R; **+1** vision IoU pass; **+1** VXN regime == normal. Grades: `A+ ≥ 5`, `A = 4`, `B = 3`, `C ≤ 2`. | The doc's own only quantified score input is the SMT `+2` (L119); the rubric must exist because phase 1 trades A/A+ only (L170). | **H** |
| **A10** | How is **A+** distinguished from **A**? | L107 (`仅接受 A+ 级带 SMT 背离信号`) | **A+ requires SMT divergence AND a vision IoU pass AND a ≥2R target**; A = any other combination meeting the A score. | L107 ties A+ to SMT explicitly; the vision pass is the other "resonance" the doc names (L138–L139). | **H** |
| **A11** | Does the checklist require the target at **≥ 2R**, or exactly 2R? Is the target RR what actually drives the TP? | L126 (`至少 2R`) | **≥ 2R** is an eligibility filter; the actual TP is the **RR-derived price** (1:2 in phase 1, L170) unless the liquidity target is closer, in which case use the target price. | "至少" = at least; but a 1:2 fixed RR must resolve when the target is at 2.5R. | **M** |
| **A12** | Must the sweep **precede** the FVG, or may they be simultaneous / the FVG may follow the sweep? | L121 (`扫荡发生前`) vs L11 (`在扫荡发生前后的波动中`) | FVG's `c[i]` **strictly before** the sweep bar; the sweep may be on the same bar as `c[i]`'s close only if `c[i] < sweep_bar`. | §三 is the "strict restoration" section (L111–L113) and is later/more authoritative than the conceptual L11 → `I02`. | **H** |
| **A13** | Which direction must the FVG be relative to the sweep? | L11 (`反向 FVG`), L6 | **Opposite**: sweep of a **high** → **bullish** FVG → **SHORT**; sweep of a **low** → **bearish** FVG → **LONG**. | L6's worked example (bullish support broken → resistance) plus L11's "反向". | **H** |
| **A14** | Entry mechanics: market at the confirmation close, or limit on the retest of the inverted FVG edge? | L13 (`在缺口被破坏后（或价格小幅回踩该已反转的 FVG 边缘时）顺着新方向入场`) | **Market order at the close of the confirmation candle** (i.e. `entry = close[k]`), with the retest-limit variant implemented as a config flag (`entry_mode` = `"close"` or `"retest"`), default `"close"`. | Deterministic and lookahead-free; matches the artifact (`pine:441` — `float lvl = close[1]`; the trade is built at `pine:458`). | **H** |
| **A15** | Where exactly is the stop? "beyond the recent swing high/low" — which swing, how many ticks beyond? | L13 (`止损通常设在近期的波段高低点外侧`) | Stop = the **swing extreme** (lowest low / highest high) over the window from the FVG's first candle to the confirmation bar, **± 1 tick beyond** it. | "外侧" = outside; the artifact's `ict_ScanExtreme` uses exactly that window (`pine:293`, `pine:462`). | **H** |
| **A16** | What is the "Visual Clarity Score" formula? | L138 (`输出视觉形态置信度（Visual Clarity Score）与边界框重合度（IoU）`) | **Visual Clarity Score := the detector's class confidence of the box matched to the rule FVG**, in [0,1]; if no box matches, the score is 0 and the candidate is rejected by the IoU gate anyway. | The doc names the score as the model's confidence output; no other formula is compatible with "视觉形态置信度". | **M** |
| **A17** | How long is the walk-forward embargo? | L282 (`带时间隔离带（Embargo）`) | **Embargo = 1 trading day on each side of the test window** (plus purging of any train label whose 2R/SL horizon overlaps the test window). | The label horizon ends only when the trade resolves (L143), so a 1-day embargo is the minimum defensible gap. | **M** |
| **A18** | How is the "1-hour VXN change rate" obtained from a **daily** VXN series? | L146 (feature) vs L260 (`interval="1d"`) | **Do not fabricate.** Either (a) fetch intraday VXN (1m/5m) and compute `close[t]/close[t-1h] - 1`, or (b) if only daily is available, **drop the feature** from the feature set. | The doc requires the feature but the pipeline builds daily bars; a daily proxy would duplicate the level feature. | **M** |
| **A19** | How much larger is the min ATR gap in the high-vol regime? | L109 (`要求更大的 ATR 最小缺口阈值`) | Raise the coefficient `0.25 → 0.35` in regime 2. | Mirrors the only quantified per-market adjustment in the doc (MES `0.25 → 0.20`, L160) — a ±0.10 step. | **M** |
| **A20** | Render convention: doc mandates black background 224×224; the referenced model was trained on white-background TradingView charts at 640×640 | L137, L279 vs `hf:55` (`Trained on white background TradingView charts only`), `hf:51` (`Input size: 640x640`) | **Render in the model's training style** (white background, TradingView-like) at **640×640**, then resize to the model's input; or retrain on black 224×224. Never mix silently. | Using the shipped weights on a black 224×224 render invalidates the IoU gate (T19) entirely. | **H** |
| **A21** | Killzone boundaries inclusive? And ET or fixed EST? | L115 (`美东时间 09:30–11:30`) vs L159/L162/L163 (`09:30 EST`, `03:00 EST`, `08:20 EST`) | **Endpoint-inclusive**, `America/New_York` with DST. | "EST" used as a label for "US Eastern" in a doc whose other line says 美东时间; a fixed offset misplaces the window by an hour half the year → `I08`. | **M** |
| **A22** | Which NQ contract (continuous vs front month), tick size, multiplier, roll rule? | L226–L227 (`InstrumentId.from_str("NQ.XCME")`), L206 | Define explicit `Future` instruments (NQ/ES front-month or a documented continuous series) with tick size 0.25 / multiplier $20 (NQ) and 0.25 / $50 (ES), and a stated roll rule. | `InstrumentId.from_str` alone is not tradable in Nautilus; the sample code never defines an instrument. | **H** |
| **A23** | Train/serve skew: phase 2 trains on *all* phase-1 signals, but the vision gate rejects 35% before the ML layer ever sees them | L172 vs L139 | Train the meta-labeler on **all** phase-1 candidates **and** keep the vision IoU as a feature; at inference the ML layer only sees vision-gated candidates. | L172 explicitly exports "所有历史信号样本（包含成功与失败的）". | **M** |
| **A24** | Does the ML layer apply to every candidate or only to A/A+ ones? | L170 vs L143 | The ML layer applies to **every** vision-gated candidate; grade is one of its features. | Keeps the meta-labeler's decision surface wide; phase-1's A/A+ restriction is a phase-1 baseline choice, not a permanent filter. | **L** |
| **A25** | Single vs clustered/series FVG candidates? | L121 (`Singular FVG`), `pine:6` | **Single**: one candidate per 3-candle FVG. A "Series" mode (merge consecutive FVGs into one zone) is a later config flag. | L121 names it "Singular FVG". | **M** |
| **A26** | How many candles of price history must the engine keep before the first signal is allowed? | not stated | Require ≥ 60 bars (vision window, T21) + 14 bars (ATR warm-up, `A03`) + swing-lookback; emit no setup until then. | Derived from the windows the doc itself imposes. | **L** |
| **A27** | Maximum holding period / time stop for a trade? | not stated | **None** beyond the bracket (SL at `A15`, TP at the RR/target price); the RL layer manages the open position. | L152 gives the RL layer the management job; a hard time stop would pre-empt it. | **M** |
| **A28** | Where does the RL layer live in the package tree? | SVG-B lists only `data_pipeline/`, `vision_validator/`, `strategy/`, `ml_pipeline/` | Add `dodgys_dd_quant/rl/` with `ppo_agent.py`, `reward.py`, `state_builder.py`. | Neither diagram assigns the RL a path; §2.3 confirms the gap. | **M** |
| **A29** | What are the RL's discrete BE-trigger and partial-TP action grids? | SVG-A (action space), L152 | BE trigger grid `{0.0R, 0.5R, 1.0R, 1.5R}`; partial-TP ratio grid `{0, 0.25, 0.5, 0.75, 1.0}`; position multiplier `{0.5x, 1.0x, 1.5x}` (SVG-A). | The SVG fixes the multiplier set but not the other two; grids must be finite for PPO. | **M** |
| **A30** | Does "1% risk per trade" mean 1% of equity at risk (stop-based) or 1% notional exposure? | L109 (`单笔风险敞口减半（如从 1% 降至 0.5%）`) | **1% of equity at risk to the stop** (size = 0.01·equity / (stop_distance·multiplier)), halved to 0.5% in regime 2. | "风险敞口" = risk exposure, not notional; the doc ties the halving to risk, and the RL multiplier scales this number. | **M** |

### 1.6.1 Threshold → open-decision cross-reference

Every row of the register above is tagged **[UNSPECIFIED]**: the discussion requires the value and does not
give it. The table below links each affected threshold to the decision that must be settled, so a reviewer
can verify that no threshold was left dangling.

| Threshold(s) | Open decision(s) | Why it matters |
|---|---|---|
| T02, T03 | `A02`, `A03` | Which ATR, anchored where — decides whether a small gap is accepted. |
| T04 | `A04`, `A05` | The window's anchor and whether it is a band or a maximum — decides which candidates survive at all. |
| T05, T06, T38, T39, T40 | `A21` | Killzone endpoints and ET vs fixed EST. |
| T07–T10, T37 | `I05`, `A34` | VXN bin boundaries are off-by-one in the doc's own code; other regime indices have no bins. |
| T11, T15, T34 | `A09`, `A10` | The A+/A/B/C rubric — phase 1 trades A/A+ only, so this decides the traded population. |
| T12, T16 | `A11` | Whether the ≥2R target filter and the RR-derived TP can disagree, and which one prices the exit. |
| T13, T45, T46 | `A19`, `A30` | High-vol risk halving and the undefined "larger ATR gap". |
| T14, T44 | `A08` | What "the same leg" means for SMT, and which reference instrument. |
| T17, T42 | `A33` | The unlabelled third outcome of a trade that neither reaches 2R nor stops out. |
| T18 | `A24` | Whether the ML gate applies to every candidate or only to A/A+. |
| T19 | `A32` | 2-D pixel IoU vs 1-D price-axis IoU. |
| T20 | `I09` | The "~35% noise filtered" claim has no evidence in the doc — do not cite it as a result. |
| T21 | `A26` | Minimum history before the first signal is allowed. |
| T22 | `A20` | Render size/background vs the shipped model's training distribution. |
| T23 | `A16` | The "Visual Clarity Score" formula. |
| T24, T25 | `A17` | Embargo length and purge horizon. |
| T26, T51 | `A18`, `A23`, `A31` | VXN 1-hour change from a daily series; train/serve skew; the SVG-only "time-decay feature". |
| T28, T29, T30 | `A29` | Discrete BE-trigger and partial-TP grids for the RL action space. |
| T32, T33 | `A22` | Instrument definitions (tick size, multiplier, roll) needed to charge fees and slippage honestly. |
| T41 | `A07` | How EQH/EQL are detected. |

### 1.7 Proposed checklist rubric (default for `A09`/`A10` — needs fleet sign-off)

| Component | Points | Source |
|---|---|---|
| Base | 0 | — |
| SMT divergence present | **+2** | L119 |
| No uncleared opposing OB / tight equal-high-low in front | +1 | L125 |
| Clear liquidity target at ≥ 2R | +1 | L126 |
| Vision IoU > 0.75 | +1 | L139 |
| VXN regime == 1 (normal) | +1 | L108 |

Grades: **A+** ≥ 5 · **A** = 4 · **B** = 3 · **C** ≤ 2.
A+ additionally **requires** SMT + vision-IoU pass (`A10`). Phase 1 trades **A/A+ only** (L170); low-vol
regime trades **A+ with SMT only** (L107).

### 1.8 Internal inconsistencies found in the discussion (reported, not silently resolved)

| ID | Inconsistency | Lines | Handling |
|---|---|---|---|
| **I01** | The inversion window is "7 至 15 根 K 线" in the state machine, but "15根K线内" in the backtest-script offer. A band `[7,15]` and a maximum of `15` are different filters (a band rejects a valid 3-bar inversion). | L123 vs L73 (also L45, L280, SVG-B) | Reported; `A05` keeps both constants configurable and marks the doc-literal band `(7,15)` as normative until the fleet rules. |
| **I02** | The FVG is found "扫荡发生**前**的最后一段推进波中" (before the sweep) but "在扫荡发生**前后的**波动中" (before *or after* the sweep). | L121 vs L11 | Reported; `A12` proposes *before* (the §三 section is the explicit "strict restoration" section, L111–L113). |
| **I03** | Two different "module" numbering schemes coexist: §四 calls the vision/ML/RL modules **1/2/3** (the rule engine is §三), the four-layer SVG calls them **layers 1/2/3/4** (rule engine = 1), and the directory SVG numbers **modules 1–6** by file. | L133, L141, L148 vs SVG-A vs SVG-B | §2.3 tabulates all three; this spec uses the SVG layer numbering for the pipeline and the SVG-B file numbering for the package. |
| **I04** | The ML layer's declared inputs in the SVG (`规则评分 + 视觉置信度 + VXN Regime + 时间衰减特征`) do not match the prose feature list (`规则 Checklist 得分、SMT 是否发生、视觉检测置信度、当前 VXN 绝对值及 1 小时变化率、缺口形成到反转消耗的 K 线数量、距离美股开盘的分钟数`). The SVG has a "time-decay feature" that the prose never defines, and omits SMT / VXN-1h / bars-to-inversion / minutes-from-open. | SVG-A vs L146 | Reported; the **prose list (L146)** is normative; "时间衰减特征" is mapped onto "缺口形成到反转消耗的 K 线数量" (`A31`, below). |
| **I05** | The VXN regime prose says `18 ≤ VXN ≤ 28` is normal and `VXN > 28` is high, but the code's `pd.cut(bins=[0,18,28,200])` is right-closed: `(0,18] → 0`, `(18,28] → 1`, `(28,200] → 2`. So VXN == 18 → code says *low* (prose says normal); VXN == 28 → code says *normal*, which **agrees** with the prose (the audit in `research/audit/AUDIT.md` §A.2.2 confirmed this by execution: `pd.cut([28.0],bins=[0,18,28,200])` → **1**). The bins are also open at 0 and at 200, so out-of-range values become NaN and `.astype(int)` raises. | L265–L267 vs L107–L109 | Reported; §1.9 gives the corrected binning. |
| **I06** | The vision layer is described twice with different IoU definitions: "计算其与规则引擎所识别 FVG 价格区间在**像素坐标系**下的 IoU" vs "计算其与规则引擎在**垂直价格轴**上的 IoU". | L274 vs L279 | Reported; `A32` proposes 2-D pixel-space IoU (L274 is the module's own job description). |
| **I07** | The rendering convention (black background, L279) contradicts the referenced model's training distribution (white-background TradingView charts, `hf:55`); the render size (224×224, L137) contradicts the model's input size (640×640, `hf:51`). | L137, L279 vs `hf:51`, `hf:55` | Reported; `A20` resolves it. |
| **I08** | The killzones are "美东时间" (ET) in the state machine but "EST" in the migration table and "09:30 EST" for the baseline window. | L115 vs L159, L162, L163 | Reported; `A21` proposes DST-aware ET. |
| **I09** | The "≈35% noise filtered" claim (L139) has no supporting computation in the doc, and the same doc says the vision layer is an *additional* filter on top of a rule layer whose false-signal rate is unknown. | L139 | Reported as an unverified assertion; do not cite it as a performance claim. |
| **I10** | The doc says the meta-labeling classifier learns "这次信号能不能赚钱" (binary 1 = 2R TP, 0 = SL), but never defines the **third** outcome (a trade that is still open, or that exits between 0 and 2R). | L143 | Reported; `A33` proposes: label `1` if the trade reaches +2R, `0` if it hits the stop, and **exclude** (drop) trades that neither resolved within the horizon. |
| **I11** | The doc's sample `prepare_parquet.py` writes bars for `InstrumentId.from_str("NQ.XCME")` without ever defining the instrument, and the file ends with `请谨慎使用此类代码` (L202, L270) — the doc's own warning. | L209–L270 | §2.4 / Appendix B. |

### 1.9 Corrected VXN regime binning (resolves `I05`)

Using the prose semantics (L107–L109) and the doc's bins/labels (L265–L266):

```python
VXN_REGIME_LOW, VXN_REGIME_NORMAL, VXN_REGIME_HIGH = 0, 1, 2
# bins: (-inf, 18) -> 0 | [18, 28] -> 1 | (28, inf) -> 2
# values <= 0 are impossible for VXN; values > 200 map to 2 (high), never NaN
```

The doc's literal `pd.cut(bins=[0,18,28,200])` yields a *different* mapping at exactly 18 and exactly 28 and
raises on out-of-range values. **The prose (L107–L109) is normative; the code sample must be fixed.**

---

## 2. Part B — System semantics

### 2.1 The four-layer architecture

Doc header: **四、四层正 EV 量化系统完整架构** (L128); the pipeline diagram is `diagram-四层正 EV 量化系统完整架构.svg`.

Layer order and data flow (from SVG-A, prose §四 L133–L152, and §一 L86):

```
Data layer : NQ + ES 1m/5m Tick/Bar + VXN 指数                (SVG-A)
      │
      ├──► 1. 确定性规则引擎 (DodgysDD 状态机)                (SVG-A)
      │          │  产生候选事件 (Candidate Setup)            (SVG-A)
      │          ▼
      │      2. 视觉交叉验证 (YOLOv8/v26 图像检测)             (SVG-A)
      │          │  识别图表形态与清晰度得分                    (SVG-A)
      │          ▼
      └──► 3. 元标签机器学习过滤器 (Meta-Labeling + LightGBM 滚动训练)   (SVG-A)
                 输入 : 规则评分 + 视觉置信度 + VXN Regime + 时间衰减特征
                 输出 : 胜率预测概率 P
                 [Win] ── 若 P(Win) < 阈值 (如 0.58)，直接拦截放弃交易
                 ▼
             4. 强化学习执行与风控代理 (PPO / SAC Agent in NautilusTrader)
                 动作空间 : 仓位乘数 (0.5x, 1.0x, 1.5x) + 动态保本触发点 (BE Trigger) + 分批止盈比例
```

Prose layer roles:

- **Layer 1 (rules)** — L111–L126: the deterministic engine; the *only* source of direction.
- **Layer 2 (vision)** — L133–L139: cross-validate the rule layer against a chart model; hard gate
  `规则引擎触发 == True AND IoU > 0.75`.
- **Layer 3 (meta-labeling)** — L141–L146: LightGBM/CatBoost binary classifier on walk-forward windows;
  labels `1 = 2R TP`, `0 = SL`; gate `P(Win) < 0.58` → abandon.
- **Layer 4 (RL)** — L148–L152: PPO/SAC for position management and exit optimisation.

The doc's own summary of the whole design (L86): `规则定骨架（严格锁定 DodgysDD 逻辑），机器学习做过滤（Meta-Labeling 元标签过滤低胜率信号），强化学习管执行与风控（动态仓位与保本追踪）`.

### 2.2 Hard invariants (must be asserted in tests)

| # | Invariant | Source |
|---|---|---|
| **INV1** | **The RL agent must never open a position.** | L150 `严格禁止 RL 自行开仓，仅负责开仓后的仓位管理与离场优化` |
| **INV2** | **The rule engine alone decides direction**; ML and RL may only filter or manage. | L143 (`让 DodgysDD 规则决定"买卖方向"`), L101, L86 |
| **INV3** | **ML is a filter, never a signal generator.** The meta-labeler outputs a probability and an accept/abort decision only. | L86, L143 |
| **INV4** | **No signal may be erased after the fact.** Every candidate setup — winner and loser — is persisted with its outcome. | L113 (`完全杜绝事后擦除失效信号`), L49 (the upstream "Hide Losing Setups" defect), L70, L172 |
| **INV5** | **Layer 2 is a hard gate, not a re-scorer**: a candidate passes only if `rule_trigger == True AND IoU > 0.75`; the vision layer may not alter direction or price levels. | L139 |
| **INV6** | **No look-ahead**: every exogenous series is lagged. VXN uses the previous period's close (`shift(1).bfill()`) and the regime label is derived from the lagged value. A decision may never use the current bar's close for a signal that fires on that same bar's close. | L207, L261–L262 |
| **INV7** | **AlphaGPT / Qlib may never replace the iFVG rules with black-box formulas.** | L101 `绝不能用黑盒公式替代 iFVG 规则` |
| **INV8** | **The strategy reacts, it does not predict** — the engine is a pure function of bar history. | L3, L113 |

Test obligations that follow (per `AGENTS.md` "Testing & QA"): assert VXN is lagged; assert walk-forward
splits have an embargo; assert the IoU threshold is applied; assert the RL never emits an open action.

### 2.3 Diagram ↔ prose reconciliation

`diagram-四层正 EV 量化系统完整架构.svg` (SVG-A) text, in document order:

| SVG-A | Layer | Matches prose? |
|---|---|---|
| `数据层 : NQ + ES 1m/5m Tick/Bar + VXN 指数` | data | ✓ consistent with L92, L169, L206; the "1m/5m" and "Tick" granularity appears **only** here (L169 says 1-minute bars for phase 1). |
| `1. 确定性规则引擎 (DodgysDD 状态机)` → `产生候选事件 (Candidate Setup)` | rules | ✓ L113–L126 |
| `2. 视觉交叉验证 (YOLOv8/v26 图像检测)` → `识别图表形态与清晰度得分` | vision | ✓ L133–L139; the SVG's "清晰度得分" is the Visual Clarity Score (`A16`) |
| `3. 元标签机器学习过滤器 (Meta-Labeling + LightGBM 滚动训练)` | ML | ✓ L141–L146 |
| `输入 : 规则评分 + 视觉置信度 + VXN Regime + 时间衰减特征` | ML inputs | ✗ **disagrees with L146** → `I04` |
| `输出 : 胜率预测概率 P` ; `若 P(Win) < 阈值 (如 0.58)，直接拦截放弃交易` | ML gate | ✓ semantically; **the value 0.58 appears nowhere in the discussion prose** — it is SVG-only (`T18`) |
| `4. 强化学习执行与风控代理 (PPO / SAC Agent in NautilusTrader)` | RL | ✓ L148–L152 (SAC is SVG-only; the prose says PPO, L175) |
| `动作空间 : 仓位乘数 (0.5x, 1.0x, 1.5x) + 动态保本触发点 (BE Trigger) + 分批止盈比例` | RL action space | ✓ consistent with L152; the multiplier set `{0.5, 1.0, 1.5}` is **SVG-only**; the prose's "halve the risk" (L109) is the 0.5x case |
| `Win` badge on the ML→RL edge | — | SVG-only: the ML layer's "pass" output is what feeds the RL layer |

`diagram-目录结构规划.svg` (SVG-B) — package root `dodgys_dd_quant/`:

| # | Path | SVG-B comment | Reconciles with prose? |
|---|---|---|---|
| 1 | `data_pipeline/prepare_parquet.py` | `# 1. Databento/Tick数据与 VXN清洗并写入 Nautilus ParquetCatalog` | ✓ L209–L269 |
| 2 | `vision_validator/visual_cv.py` | `# 2. 无指标裸 K实时渲染 + YOLO视觉与规则 IoU交叉验证` | ✓ L272–L274, L279 |
| 3 | `strategy/custom_data.py` | `# 3. VXN指数与视觉验证信号的自定义 Data对象` | ✓ L93, L280 (`VXNRegimeData`) |
| 4 | `strategy/state_machine.py` | `# 4. 忠实还原 DodgysDD的 iFVG状态机（流动性扫荡 +SMT+7-15根反转）` | ✓ L111–L126; the SVG repeats the 7–15 figure → `I01` |
| 5 | `strategy/dodgys_strategy.py` | `# 5. NautilusTrader主策略（ NQ/ES多合约订阅 +执行 +日志导出）` | ✓ L92, L281 |
| 6 | `ml_pipeline/meta_labeling_train.py` | `# 6. 交易日志特征工程 + 滚动窗口 (Walk-Forward)LightGBM训练` | ✓ L145–L146, L282 |

**Disagreements between the diagrams and the prose:**

1. **ML input list** (SVG-A) ≠ prose feature list (L146) → `I04`.
2. **`0.58`** exists only in SVG-A; the prose gives no threshold → `T18` is `[DOC-SVG]`.
3. **RL action-space multipliers `{0.5x, 1.0x, 1.5x}`** exist only in SVG-A; the prose only describes "halve the risk" (L109).
4. **`SAC`** appears only in SVG-A; the prose names **PPO** (L175) — implement PPO, note SAC as an option.
5. **Data granularity** "1m/5m Tick/Bar" is SVG-only; L169 specifies 1-minute bars for the phase-1 backtest, and L207/L274 speak of bars/ticks separately. Use 1-minute bars as the baseline, tick data only where explicitly required.
6. **No `rl/` package in SVG-B** — the RL layer has no file path anywhere → `A28`.
7. **Numbering** — three schemes coexist → `I03`.

### 2.4 The `prepare_parquet.py` sample — port, do not paste

The doc's sample (L209–L269) is wrapped by two identical warnings: **L202 `请谨慎使用此类代码`** and **L270
`请谨慎使用此类代码`**. Treat the block as a *sketch*: the doc itself flags it.

**Correction to `AGENTS.md`.** `AGENTS.md` (Risks) states: *"The doc's `prepare_parquet.py` sample targets an
older NautilusTrader API (`BarSpecification`/`BarType` construction, `Price.from_str` precision). The
installed 1.221 API differs — port it, don't paste it."* **I checked this against the installed
1.221.0 and the three cited calls all work as written** (Python 3.11.17, `nautilus_trader 1.221.0`):

```
BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)  → 1-MINUTE-LAST       # OK
BarType(InstrumentId.from_str("NQ.XCME"), bar_spec)        → NQ.XCME-1-MINUTE-LAST-EXTERNAL  # OK
Price.from_str("20000.00")                                 → Price(20000.00), precision 2      # OK
Bar(bar_type=..., open=..., high=..., low=..., close=..., volume=Quantity.from_int(10),
    ts_event=..., ts_init=...)                             → OK
ParquetDataCatalog(...).write_data(bars)                   → method exists                      # OK
```

So the sample is **not** broken by an API rename. It is broken by other things, which is the real risk:

| # | Defect in the sample | Line | Consequence |
|---|---|---|---|
| B1 | No instrument is ever defined. `InstrumentId.from_str("NQ.XCME")` creates an *identifier*, not a tradable `Future`. `TestInstrumentProvider` is imported (L220) but never used. | L226–L227 | Bars reference an instrument the engine cannot trade. CME tick size/multiplier/precision are unspecified anywhere → `A22`. |
| B2 | `df.sort_values("volume", ascending=False).groupby(level=0).first().sort_index()` groups by `level=0`. A Databento `to_df()` frame is indexed by `(instrument, ts_event)` → `level=0` groups by **instrument**, not timestamp. | L234 | The whole continuous-series construction is wrong; it must group by the timestamp level (`level=-1`) to pick the highest-volume contract per timestamp. |
| B3 | `Price.from_str(f"{row['open']:.2f}")` hard-codes 2 decimals. | L245–L248 | Fine for NQ/ES (precision 2), wrong for GC (0.1) and for any instrument with different precision. Must use the instrument's price precision. |
| B4 | `yf.download("^VXN", start="2022-01-01", interval="1d")` — modern yfinance returns a MultiIndex *column* frame, so `vxn_df["Close"]` does not exist. | L260–L262 | `KeyError` at runtime; needs column flattening. |
| B5 | `pd.cut(bins=[0,18,28,200]).astype(int)` — right-closed bins conflict with the prose at the 18/28 boundaries, and any value ≤ 0 or > 200 becomes NaN, which `.astype(int)` rejects. | L263–L267 | See `I05`; use the corrected binning in §1.9. |
| B6 | The roll logic does not back-adjust prices; it selects the max-volume contract per timestamp, which produces price gaps at the roll. | L234 | Backtest P&L is corrupted across rolls. |
| B7 | The `conda create -n nautilus_ifvg python=3.11` recipe cannot run on this host (no conda). Use the uv-managed 3.11 interpreter. | L199–L201 | Environment fact (`.field-guide/env.md`), not a doc defect. |
| B8 | The doc says to use "最新 1 个月" for validation but the sample's VXN table is built on **daily** bars only, while L146 needs an intraday 1-hour change rate. | L146, L260 | `A18`. |

**Verdict:** port the *shape* of the script (DBN → `Bar` objects → `ParquetDataCatalog`, plus a cleaned VXN
table), but rewrite B1, B2, B4, B5 and B6 against the 1.221 API. Do not paste it.

### 2.5 Phase gates

| Phase | Weeks | Scope | Acceptance gate | Source |
|---|---|---|---|---|
| **1 — pure-rule baseline** | 1–2 (L168) | NautilusTrader backtest on NQ + ES **1-minute** bars, `DodgysDDStateMachine` only, no ML | EV must be **positive** under realistic costs: **~$4.5 round-trip fees**, **1–2 tick** slippage, **fixed 1:2 RR**, checklist filter **A/A+ only** → **Profit Factor > 1.25**. *"如果纯规则阶段为负，说明规则细节还原有误，绝不能直接上 ML 掩盖问题。"* (If the pure-rule stage is negative, the rule reproduction is wrong — never mask it with ML.) | L168–L170 |
| **2 — features + vision** | 3–4 (L171) | Export **all** phase-1 signals (wins **and** losses), attach VXN history and vision scores; train the first meta-labeling classifier | Max drawdown **significantly** lower and win rate **from ~45% → >55%** | L171–L173 |
| **3 — RL + paper trading** | 5–6 (L174) | PPO position/BE management; switch to LiveNode against IB / Tradovate / Rithmic simulation | **4 weeks** of forward testing confirming **live slippage == backtest slippage** | L174–L175 |

Steady-state targets (stated as a *migration precondition*, not a phase gate): sample-out-of-sample
**Sharpe > 1.8** and **max drawdown < 10%** before migrating away from NQ (L156).

**Gate ordering rule:** a phase may not start until the previous phase's gate is met, and a **negative
phase-1 result must be treated as a rule-reproduction defect, never as an ML problem** (L170).

### 2.6 Cross-market migration table (verbatim, L158–L163)

```
目标品种	联动 SMT 参考品种	波动率 Regime 指标	核心微调参数
NQ / MNQ	ES / YM	VXN	基准模板（美股开盘 09:30 EST 核心窗口）
MES	NQ / RTY	VIX	缺口最小 ATR 系数从 0.25 调整为 0.20（ES 波动率低于 NQ）
QQQ	SPY / IWM	VXN	需加入盘前跳空缺口（Overnight Gap）作为首要流动性目标
GC (黄金)	SI (白银) / DXY	GVZ (黄金波动率)	激活时间窗口切换为 伦敦开盘 (03:00 EST) 与 COMEX 开盘 (08:20 EST)
BTC / ETH	BTC 与 ETH 互为 SMT	DVOL (Deribit 波动率)	24/7 市场，核心流动性扫荡集中在 美股开盘 (09:30 EST) 与 日线 UTC 00:00 交割前后
```

Machine-readable form (the "core micro-tweak" column, verbatim semantics):

| Target | SMT reference | Regime index | Key tuning | Spec tags |
|---|---|---|---|---|
| NQ / MNQ | ES / YM | VXN | baseline template, core window 09:30 ET | [DOC] L159 |
| MES | NQ / RTY | VIX | min-gap ATR coefficient **0.25 → 0.20** | [DOC] L160 |
| QQQ | SPY / IWM | VXN | add the overnight gap as the primary liquidity target | [DOC] L161 |
| GC (gold) | SI (silver) / DXY | GVZ | killzones switch to London open (03:00 ET) and COMEX open (08:20 ET) | [DOC] L162 |
| BTC / ETH | BTC ↔ ETH (mutual) | DVOL (Deribit vol) | 24/7; sweeps concentrate at the US open (09:30 ET) and around UTC 00:00 | [DOC] L163 |

The doc's explicit promise: **"无需重写核心状态机"** — the core state machine is **not** rewritten per
market, only parameters change (L156). Per-`AGENTS.md`, the MES coefficient change is the *only* quantified
per-market tweak; everything else (killzone shifts for GC, overnight-gap target for QQQ, 24/7 handling for
crypto) is **parameter-level**, and the migration table gives values only for the killzones.

Note the regime index swaps per market: VXN (NQ/QQQ) → VIX (MES) → GVZ (GC) → DVOL (BTC/ETH). The **bins**
`[0, 18, 28, 200]` are stated for **VXN only** (L265–L266); the corresponding bins for VIX/GVZ/DVOL are
**not specified** → `[UNSPECIFIED]`, see `A34`.

### 2.7 The architectural argument against AlphaGPT / Qlib as the signal source

The doc's section **二、核心架构决策 (1. 为什么不建议直接套用 AlphaGPT / Qlib 挖掘主信号？)** — L98–L101,
in the user's own framing (L76–L79 lists AlphaGPT, Qlib and the community mirror as candidate
factor-mining tools):

> **架构错配** (architecture mismatch): AlphaGPT (symbolic-regression formula-factor generation) and Qlib
> (cross-sectional multi-factor ranking) were designed for **cross-sectional stock-pool ranking**, computing
> **IC / RankIC**, not for a **single futures contract's discrete event-driven state machine**
> (L100).

> **正确定位** (correct positioning): the DodgysDD deterministic logic must be strictly preserved as the
> **"signal trigger"**; one may borrow only Qlib's **rolling retraining** and **concept-drift adaptation
> (DDG-DA)** ideas, or use AlphaGPT to mine **"micro auxiliary features"** at discrete event times (e.g. the
> volume-price slope at the breakout instant) — **"绝不能用黑盒公式替代 iFVG 规则"** (never replace the iFVG
> rules with black-box formulas) (L101).

**The limited role the doc DOES assign them:**

| Allowed | Forbidden | Source |
|---|---|---|
| Borrow Qlib's *rolling-retraining* and *concept-drift-adaptation (DDG-DA)* **ideas** | Using them as the signal source | L101 |
| Use AlphaGPT to mine **micro auxiliary features at discrete event times** (e.g. volume-price slope at the breakout) | Replacing the iFVG rules with generated formulas | L101 |
| Use them as a **sub-directory / backtest backend** | Letting cross-sectional rank replace per-event decisions | L100 (architecture rationale), L86 (rules define the skeleton) |

This is codified as **INV7** (§2.2).

---

## 3. Part C — Traceability appendix

`L<n>` = `iFVG几个模型的讨论.txt` line n. `SVG-A` = `diagram-四层正 EV 量化系统完整架构.svg`,
`SVG-B` = `diagram-目录结构规划.svg`. `pine:` = `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine`,
`hf:` = `research/huggingface/nq-fvg-detector/README.md`.

| Spec item | Statement (abbreviated) | Source line(s) | Tag |
|---|---|---|---|
| S1 | iFVG = wait for failure; bullish support broken by body → becomes resistance | L6 | [DOC] |
| S2 | Standard steps: sweep → FVG → break → retest entry, stop beyond swing, target next pool | L10–L13 | [DOC] |
| S3 | Timeframes 1–15 min, NQ-like high-vol instruments, US-open sessions | L17 | [DOC] |
| S4 | Upstream indicator `iFVG Ultimate+ / DodgysDD` implements sweep detection, **7–15 bar** inversion validation, SMT confirmation, A+–C grading | L45 | [DOC] |
| S5 | Upstream defaults to "Hide Losing Setups" — post-hoc erasure of losers | L49 | [DOC] |
| S6 | Community note: mechanical iFVG win rate swings widely without HTF structure + session filter; show all invalidated signals | L70 | [DOC] |
| S7 | User's hard requirement: strictly follow DodgysDD's original logic; NautilusTrader as engine | L80–L81 | [DOC] |
| S8 | Design principle: rules = skeleton, ML = filter, RL = execution & risk | L86 | [DOC] |
| S9 | NT: backtest/live isomorphic; multi-contract SMT alignment; custom `Data` streams for VXN + vision boxes | L91–L93 | [DOC] |
| S10 | AlphaGPT/Qlib architecture mismatch + permitted role | L100–L101 | [DOC] |
| S11 | VXN regime bands and per-regime policy (A+-only & RR 1:1.5–1:2 / RR 1:2.5–1:3 / halve risk & bigger ATR gap) | L107–L109 | [DOC] |
| S12 | `DodgysDDStateMachine`, pure rules, no post-hoc erasure | L113 | [DOC] |
| S13 | Killzones 09:30–11:30 and 13:30–15:30 ET | L115 | [DOC] |
| S14 | PDH/PDL, Asia/London session extremes, unreclaimed 15m/1H FVGs | L116 | [DOC] |
| S15 | Sweep: NQ pierces prior swing high/low (EQH/EQL/PDH/PDL) | L118 | [DOC] |
| S16 | SMT divergence → **+2** score | L119 | [DOC] |
| S17 | FVG in the last impulse leg before the sweep; 3-candle geometry; gap > 0.25·ATR(14) | L121 | [DOC] |
| S18 | Inversion: within 7–15 bars, a **body close** through the **far edge**; wick does not count | L123 | [DOC] |
| S19 | Checklist: no uncleared opposing OB / tight equal-high-low ahead | L125 | [DOC] |
| S20 | Checklist: clear liquidity target at **≥ 2R** (EQH/EQL, untouched session extreme, LRLR) | L126 | [DOC] |
| S21 | Vision: 60 indicator-free candles, mplfinance, **224×224** tensor | L137 | [DOC] |
| S22 | Vision outputs Visual Clarity Score + IoU | L138 | [DOC] |
| S23 | Vision gate: `rule == True AND IoU > 0.75`; claims ~35% noise filtered | L139 | [DOC] |
| S24 | Meta-labeling: rules decide direction, classifier decides "did this make money"; `1 = 2R TP`, `0 = SL`; LightGBM/CatBoost | L143 | [DOC] |
| S25 | Walk-forward 6mo/1mo/1mo, rolled monthly | L145 | [DOC] |
| S26 | Feature list (7 features incl. VXN level + **1-hour change rate**) | L146 | [DOC] |
| S27 | RL forbidden from opening; position management only | L150 | [DOC] |
| S28 | RL state space (PnL in R, VXN regime, holding time, order-book imbalance) | L151 | [DOC] |
| S29 | RL reward: Sortino-like + penalty for reaching 1.5R without moving the stop → learn BE trigger and partial TP | L152 | [DOC] |
| S30 | Migration precondition: sample-OOS Sharpe > 1.8, max DD < 10%; core state machine not rewritten | L156 | [DOC] |
| S31 | Migration table (5 rows) | L158–L163 | [DOC] |
| S32 | Phase 1: NQ+ES 1-minute backtest, rules only, PF > 1.25, $4.5 round-trip, 1–2 tick slippage, 1:2 RR, A/A+ only; never mask a negative result with ML | L169–L170 | [DOC] |
| S33 | Phase 2: export all signals incl. failures; win rate ~45% → >55%, lower max DD | L172–L173 | [DOC] |
| S34 | Phase 3: PPO, LiveNode on IB/Tradovate/Rithmic sim, 4 weeks forward test, slippage parity | L175 | [DOC] |
| S35 | Environment recipe (conda) + `请谨慎使用此类代码` | L198–L202 | [DOC] |
| S36 | Databento for NQ/ES tick/1-minute; VXN via CBOE/Databento/yfinance with forward-fill + 1-bar lag | L206–L207 | [DOC] |
| S37 | `prepare_parquet.py` sample + `请谨慎使用此类代码` | L209–L270 | [DOC] |
| S38 | VXN alignment table: `shift(1).bfill()`, `pd.cut(bins=[0,18,28,200], labels=[0,1,2])` | L260–L268 | [DOC] |
| S39 | Vision module: 60 candles → detector → pixel-space IoU | L274 | [DOC] |
| S40 | Module summaries: black-background 60-candle render, `VXNRegimeData`, 0.25 ATR, 7–15 bar body inversion, bracket orders, embargoed purged walk-forward | L278–L282 | [DOC] |
| S41 | Four-layer SVG: data layer; 4 layers; ML inputs/outputs; `P(Win) < 0.58` gate; RL action space `0.5x/1.0x/1.5x` + BE trigger + partial TP | SVG-A | [DOC-SVG] |
| S42 | Directory SVG: package `dodgys_dd_quant/` with modules #1–#6 | SVG-B | [DOC-SVG] |
| S43 | FVG geometry cross-check (`close[1] < fvgBottom` / `> fvgTop`) | `pine:437` | [X-ART] |
| S44 | Grace window = 15 (or 6) bars, measured from the FVG bar | `pine:658`, `pine:499` | [X-ART] |
| S45 | Sweep = strict pierce of a 3-bar-pivot HTF swing level, consumed once | `pine:560`, `pine:567`, `pine:622-627` | [X-ART] |
| S46 | Stop = swing extreme from the FVG bar to the confirmation bar; BE = swept swing level | `pine:293`, `pine:462`, `pine:476` | [X-ART] |
| S47 | Entry at the confirmation candle's close | `pine:458` | [X-ART] |
| S48 | Model trained on white-background TradingView charts, 640×640, classes bullish_fvg/bearish_fvg | `hf:42-43`, `hf:51`, `hf:55` | [X-ART] |

### 3.1 Additional [UNSPECIFIED] items raised by this analysis (continuing the `A##` series)

| ID | Question | Proposed default | Rationale | Imp. |
|---|---|---|---|---|
| **A31** | What is the SVG-only "时间衰减特征" (time-decay feature) in the ML input list? | Map it onto L146's "缺口形成到反转消耗的 K 线数量" (bars from FVG formation to inversion), i.e. `bars_since_fvg`. | It is the only time-decay quantity in the prose feature list; no separate feature is needed. | **L** |
| **A32** | Pixel-space IoU (L274) vs price-axis IoU (L279)? | **2-D pixel-space IoU**: the detector's box vs the rule FVG rectangle rendered into the same image. | L274 is the module's own job statement and matches "边界框重合度" (L138). | **M** |
| **A33** | Third meta-label outcome (neither 2R TP nor SL). | Drop such samples from training (and exclude them from the win-rate denominator, consistently in both training and evaluation). | Otherwise the label space is ill-defined; dropping is the only option that does not bias the classifier. | **M** |
| **A34** | Regime-index bins for VIX (MES), GVZ (GC), DVOL (BTC/ETH) — the doc gives `[0,18,28,200]` for VXN only. | Scale by the index's own scale: use the **percentile** mapping instead of absolute points — regime 0 = bottom third of the trailing 1-year distribution, 1 = middle, 2 = top third — until absolute bins are specified per index. | Absolute VXN numbers do not transfer to VIX/GVZ/DVOL; percentiles are index-agnostic and keep the 3-way semantics (L265–L266). | **M** |
| **A35** | Confidence threshold for the detector's boxes (the model card suggests `conf=0.25`). | `conf = 0.25` (the model card's own operating point), and take the highest-confidence box per class. | Documented operating point for the only available weights; no basis in the doc. | **L** |

---

## Appendix A — Constants module (single source of tunables)

Per `AGENTS.md` ("Put all tunable thresholds in **one** constants module — never inline magic numbers"), the
minimum contents implied by this spec:

```python
# dodgeys_dd_quant/constants.py
MIN_GAP_ATR_MULT          = 0.25   # T02  L121   (0.20 for MES — L160)
ATR_PERIOD                = 14     # T03  L121
INVERSION_MIN_BARS        = 7      # T04  L123   (see I01/A05)
INVERSION_MAX_BARS        = 15     # T04  L123
KILLZONE_AM_ET            = (time(9,30), time(11,30))   # T05 L115
KILLZONE_PM_ET            = (time(13,30), time(15,30))  # T06 L115
VXN_REGIME_BINS           = (18.0, 28.0)                # T07/T08/T09/T10 L107-L109, L265
VXN_REGIME_LABELS         = (0, 1, 2)                   # T07 L266
VXN_LAG_BARS              = 1      # T49 L262
META_LABEL_THRESHOLD      = 0.58   # T18 SVG-A
VISION_IOU_THRESHOLD      = 0.75   # T19 L139
VISION_WINDOW_BARS        = 60     # T21 L137
VISION_RENDER_SIZE        = (224, 224)  # T22 L137  (see A20 — model wants 640×640)
CHECKLIST_SCORE_A_PLUS    = 5      # A09/A10
CHECKLIST_SCORE_A         = 4      # A09
CHECKLIST_SCORE_B         = 3      # A09
SMT_SCORE_WEIGHT          = 2      # T14 L119
MIN_TARGET_R              = 2.0    # T16 L126
PHASE1_RR                 = 2.0    # T34 L170
PHASE1_MIN_PROFIT_FACTOR  = 1.25   # T32 L170
PHASE1_FEES_ROUND_TRIP    = 4.5    # T33 L170
PHASE1_SLIPPAGE_TICKS     = (1, 2) # T33 L170
RISK_PER_TRADE            = 0.01   # T45 L109
RISK_PER_TRADE_HIGH_VOL   = 0.005  # T46 L109
RL_BE_TRIGGER_GRID        = (0.0, 0.5, 1.0, 1.5)   # A29
RL_PARTIAL_TP_GRID        = (0.0, 0.25, 0.5, 0.75, 1.0)  # A29
RL_POSITION_MULTIPLIERS   = (0.5, 1.0, 1.5)         # T30 SVG-A
RL_BE_PENALTY_AT_R        = 1.5    # T29 L152
```

## Appendix B — Two warnings carried from the discussion

1. **L202 / L270: `请谨慎使用此类代码`** — the doc attaches this caution to the environment recipe and to the
   `prepare_parquet.py` sample. See §2.4 for the itemised defects (B1–B8). Port the script; do not paste it.
2. **L49, L70, L113, L172** — the doc repeatedly stresses that invalid setups must remain visible
   (`建议在实盘前务必开启"显示所有失效信号"进行样本外测试`; `完全杜绝事后擦除失效信号`). This is **INV4** and
   is the single most-cited behavioural requirement in the specification.

## Appendix C — Secondary-artifact cross-check (non-normative)

`research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` (MIT, `cantolab/IFVG-Ultimate-Dodgy`) was read
locally (nothing was downloaded for this spec) to check how the doc's numbers map onto an actual
implementation. Findings that bear on the ambiguities above:

| Finding | Evidence | Bears on |
|---|---|---|
| FVG geometry is exactly the doc's, with strict inequalities | `pine:354` (`low[1] > high[3]` / `high[1] < low[3]`) | §1.2 |
| Inversion trigger is the **close** of the last completed bar beyond the `c[i-2]`-side edge | `pine:437` | `A01`, §1.3 |
| The window is a **maximum** of 15 bars (or 6 with "Allow 7–15 Candle IFVGs" off), measured from the FVG bar | `pine:658`, `pine:499`, tooltip `pine:9` | `A04`, `A05`, `I01` |
| "7–15" in the doc most plausibly describes the original's *two modes* (≤6 or ≤15), not a band | `pine:9` | `I01` |
| Entry = close of the confirmation candle; stop = swing extreme from the FVG bar; BE = the swept level | `pine:441`, `pine:458`, `pine:293`, `pine:462`, `pine:476` | `A14`, `A15` |
| Sweep = strict pierce of a 3-bar-pivot HTF swing level, consumed once | `pine:560`, `pine:567`, `pine:622-627` | `A07` |
| The upstream indicator's "Hide Losing Setups" default is `true` | `pine:8` | INV4, L49 |
| The reimplementation's author could **not** reproduce the A+–C grading ("Dodgy himself has said the grading is mechanical… a fixed set of rules generating the grade") and deliberately omitted it | `README.md` "Setup grade box — left out entirely" | `A09`, `A10` — the grade rubric is genuinely undocumented |
| The author's own verdict: the strategy has **no** demonstrated edge; the sweep filter and HTF/SMT confluence "barely changed" setup quality | `README.md` "What I noticed building this" / "Does the strategy have any value? NO" | Sanity-check for the phase-1 gate (L170): a negative rule-only result must be treated as a reproduction defect (INV4/L170), **not** hidden |

**These are cross-checks, not authority.** Where the artifact and the discussion disagree (notably the
window semantics, `I01`), the discussion governs until the fleet rules, and the conflict is reported above.
