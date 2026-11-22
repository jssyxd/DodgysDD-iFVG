# L2_RULES.md — Rule-fidelity audit: is DodgysDD's decision logic faithfully reproduced?

**Leaf:** L2 (rule fidelity) · **Question:** Q3 · **Mode:** read-only audit, one owned file.
**Date:** 2026-11-22 · **Repo:** `/home/da/桌面/DodgysDD_ifvg` @ `jssyxd/DodgysDD-iFVG` (private).

**Citation convention**
`doc:L###` → `iFVG几个模型的讨论.txt` (the master discussion, 283 lines) ·
`pine:L###` → `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` (694 lines, `@bdc0b04`) ·
`pineREADME:L###` → `research/github/IFVG-Ultimate-Dodgy/README.md` (83 lines) ·
`e1:L###` → `research/experiments/e1_rule_falsification.py` (431 lines) ·
`PINE_RULES §R#` / `§C-#` → `research/analysis/PINE_RULES.md` ·
`RULE_SPEC §…` → `research/docs/RULE_SPEC.md` · `AUDIT §…` → `research/audit/AUDIT.md` ·
`decisions.md D#` → `.herd-swarm/decisions.md` · `AGENTS.md` → repository guidelines.

**Evidence tags:** `[FACT]` = directly verifiable in a cited file · `[INFERENCE]` = follows from cited
facts but is not itself written anywhere · `[PROPOSAL]` = my recommendation, not yet decided.

---

## 0. Headline

> **[FACT] Q3's answer is NO.** The project's trading-decision logic exists in **exactly one Python
> file** (`research/experiments/e1_rule_falsification.py`, 431 lines), it is a **code-derived core**
> (not the doc's 5-step state machine), and it implements **8 of the 30** rules in the conformance
> matrix faithfully, **3** partially and **19** not at all. `dodgys_dd_quant/` — the package the
> design mandates — **does not exist**; there is no `state_machine.py`, no `detect_fvg`, no sweep
> detector, no inversion check, no test suite, no config tree.
>
> **[FACT] One correction to the sibling reports, established here by proof and by execution:** the
> inversion window is **[1, 15]**, not `[0, 15]`. Age 0 — "the confirmation candle is the FVG's own
> newest candle" — is *arithmetically impossible* under the Pine's own trigger predicate
> (`pine:L354` + `pine:L437`), because a bullish FVG requires `low[c] > high[c-2]` while its age-0
> trigger requires `close[c] < high[c-2]`, and `close[c] ≥ low[c]`. `PINE_RULES` §0.3-2, §R15,
> §C-2 and `AUDIT` §A.1.3 all assert age 0 is reachable; they are wrong on this point. See §A.5.

---

# A. Implementation status

## A.1 Repo-wide search — the rule engine is **absent** as a package

**[FACT]** The greps I ran, and their exact output:

```bash
$ ls -d dodgys_dd_quant configs tests data artifacts
ls: 无法访问 'dodgys_dd_quant': 没有那个文件或目录
ls: 无法访问 'configs': 没有那个文件或目录
ls: 无法访问 'tests': 没有那个文件或目录
ls: 无法访问 'data': 没有那个文件或目录
ls: 无法访问 'artifacts': 没有那个文件或目录

$ find . -name '*.py' \
    -not -path './research/github/*' -not -path './research/kaggle/*' \
    -not -path './research/huggingface/*' -not -path './.git/*' -not -path './.pi/*'
./research/experiments/e1_rule_falsification.py          # ← the only Python file in the repo

$ git ls-files '*.py'
research/experiments/e1_rule_falsification.py              # ← and the only tracked .py file

$ git ls-files | sed 's|/.*||' | sort | uniq -c | sort -rn
     28 research      3 scripts      3 .field-guide      2 .herd-swarm      1 README.md  …
```

**[FACT]** `research/github/`, `research/kaggle/` and `research/huggingface/` are gitignored
(`.gitignore` lines 9–11) and hold the *fetched upstream corpus*, not our code. They contain
`detect_fvg`, `detect_liquidity_sweeps` etc. in `research/huggingface/xauusd-ml-trader/`, but that is
a **third-party artefact** — `decisions.md` D7 fixes its verdict as **ADAPT** (port with the
look-ahead fixed), i.e. it is *input to a future port*, not a port.

**[FACT]** A grep for rule-engine symbols across every tracked code/config file
(`detect_fvg|find_fvg|state_machine|detect_sweep|inversion|ifvg`) returns hits **only** inside
`research/experiments/e1_rule_falsification.py` — its own docstring and comments. There is no
`configs/`, no `tests/`, no `data/`, no `artifacts/`, no `research/candidates/` directory.

**[FACT]** `research/analysis/ML_REUSE.md` §A.9 (L187–L233) contains a **specification sketch** of
`generate_ifvg_entry_signals()` and of the `DodgysDDStateMachine` state machine — but it is prose in a
report, not code. No file in the repo implements it.

**Verdict — implementation status by artefact:**

| Artefact | Kind | Status |
|---|---|---|
| `dodgys_dd_quant/strategy/state_machine.py` | mandated module | **ABSENT** — directory does not exist |
| `dodgys_dd_quant/strategy/dodgys_strategy.py` | mandated module | **ABSENT** |
| `dodgys_dd_quant/strategy/structure.py` (sweeps/EQH) | planned (ML_REUSE A.9) | **ABSENT** |
| `research/experiments/e1_rule_falsification.py` | experiment script | **PRESENT** — a code-derived core, 431 lines, stdlib + pyarrow |
| `research/analysis/ML_REUSE.md` §A.9 | specification sketch | **PRESENT as prose only** |

**[INFERENCE]** The repository is at D1's "wave 1 = read-only audit + specification". Nothing in the
repo is a *system*; `e1_rule_falsification.py` is an **experiment**, deliberately written as a
standalone script with its own bar/candidate dataclasses (`e1:L82–L110`) rather than as a reusable
engine.

## A.2 What E-1 *does* implement, rule by rule

**[FACT]** Mapping `e1_rule_falsification.py` against `PINE_RULES` §R1–R30:

| Rule | e1 implementation | Verdict vs the Pine |
|---|---|---|
| R2 — FVG geometry | `e1:L191-195` `bull = bars[c].l > bars[a].h` / `bear = bars[c].h < bars[a].l`; gap edges at `e1:L195` | **matches `pine:L354-356`** (strict, wick-based) |
| R13 — inversion trigger | `e1:L242-245` `bars[k-1].c < cand.gap_bottom` / `> cand.gap_top` | **matches `pine:L437`**, incl. the `close[1]` lag and strictness |
| R14/R15 — expiry | `e1:L248-250`, `e1:L294` on the *confirmation candle's* age | **matches `pine:L499`** in effect → window `[1,15]`, see §A.5 |
| R22 — stop placement | `e1:L267-277` `min low` / `max high` over `bars[c:k+1]` | **matches `pine:L293-302` + `pine:L462`** with the default `slPlacement="Wick"` (`pine:L45`) |
| R24 — resolution | `e1:L301-302` `low <= stop` / `high >= stop` (inclusive) | **matches `pine:L508`**; stop-before-target precedence preserved |
| R13/R22 — entry price | `e1:L260` `bars[k].o` (honest) / `e1:L262` `bars[k-1].c` (code's `lvl`, `pine:L441`) | **both arms implemented** |
| ATR floor (doc L121) | `e1:L196-201`, `atr_mult` arm `e1:L72` | doc-only; the Pine has **no** ATR (`grep -ci atr` → **0**) |
| ATR(14) | `e1:L137-152` Wilder RMA, `None` until warm | matches `RULE_SPEC` A02/A03 proposal |
| Sweep (doc L118) | `e1:L154-183` | **diverges** — see §A.3 D-06 |
| RR / 1:2 target | `e1:L79` `RR = 2.0`, `e1:L273/L277` | the Pine has **no TP**; this is the doc's phase-1 rule (`doc:L170`) |
| Concurrency | `e1:L253-254`, `e1:L77` | D4's one-position-at-a-time arm exists |

**[FACT]** Rules the Pine implements and E-1 **does not**: R1 (swing origin), R3 (FVG search window),
R4 (leg freeze), R5 (Single/Series candidate arbitration), R10's level-consumption, R12
(`onlyShowSweptIFVG` semantics), R16 (`requireBEIntact`), R17 (HTF-FVG gate), R20 (sessions),
R21 (bias), R23/R24 (break-even level + resolution), R25 (`hideLosing` — correctly *not* reproduced),
R27 (`setupHistory` cap), R28 (candidate cap).

## A.3 Every divergence between `e1_rule_falsification.py` and `ifvgUltimatePlus.pine`

| # | Divergence | Pine side | E-1 side | Material? |
|---|---|---|---|---|
| **D-01** | **No swing-origin / leg tracker.** The Pine creates an FVG candidate only inside a swing leg; E-1 creates one for *every* 3-candle gap. | `pine:L350-369` (origin), `pine:L371-377` (`checkFvg`), `pine:L426-429` (freeze) | `e1:L189-206` — no origin, no window, no freeze | **YES — largest structural gap** |
| **D-02** | **All candidates kept; no "one live candidate per direction".** The Pine keeps ≤1 live candidate per direction and *deletes* the worse gap from the array. | `pine:L383-403` (`liveEntry`, "better" comparison at `pine:L397`) | `e1:L203` `out.append(...)` — unbounded pending set | **YES** |
| **D-03** | Candidate array cap not implemented. | `pine:L286-291` (`MAX_TRACKED_SETUPS = 50`, `pine:L78`) | none | low (safe direction) |
| **D-04** | **`requireBEIntact` gate absent.** Pine default **on**; drops a setup whose confirmation close already reached the swing origin — a *predictive* filter. | `pine:L442`, `pine:L447` | no origin ⇒ no BE ⇒ no gate | **YES** |
| **D-05** | **Break-even level and BE resolution absent.** | `pine:L476` (`tr.bePrice := e.swingPrice`), `pine:L509` (`beHit`), `pine:L531-539` | none | **YES** — a setup that returns to its origin is neither closed nor repriced in E-1 |
| **D-06** | **The sweep detector is a different object.** Pine: 3-bar fractal on a **hand-aggregated HTF series**, strict pierce, **levels consumed once**. E-1: 5-bar fractal on the **same timeframe**, only the **most recent** pivot level, an **added body-reclaim** condition, **no consumption**. | `pine:L544-553` (auto map), `pine:L582-614` (aggregation), `pine:L616-630` (fractal), `pine:L560-575` (`findSweep`: `this.points.remove(i)`), `pine:L629-630` | `e1:L154-166` (`causal_swings(left=2,right=2)`), `e1:L171-182` (`last_h`/`last_l` only; `b.c < last_h` reclaim test; no removal) | **YES** |
| **D-07** | **Sweep→setup association differs.** Pine: leg-scoped flag `swept` = "a sweep occurred since the origin pivot". E-1: the sweep must be **on the confirmation bar itself**. | `pine:L405-424` (`swingSwept`, `liveEntry.swept`) | `e1:L251` `if require_sweep and not swept[k - 1]` | **YES** |
| **D-08** | HTF-FVG confluence gate absent. | `pine:L635-647`, `pine:L444-445` (`onlyShowHtfAlignedIFVG`, default `false` `pine:L12`) | none | none at Pine defaults; capability missing |
| **D-09** | Session / killzone absent. | `pine:L123-126`, `pine:L497-498` — **alert-only** | none | parity with the Pine (no signal gate); **divergence from `doc:L115`** |
| **D-10** | Bias filter absent. | `pine:L659-670`, default `Neutral` `pine:L7` | none | parity at default |
| **D-11** | `setupHistory` cap absent (and with it the "an evicted setup stops being managed" side-effect). | `pine:L482-495` | none | E-1 manages every setup → *safe* direction, but its population differs |
| **D-12** | Stop placements `"Body"` and `"IFVG"` not implemented. | `pine:L466-469` | `e1:L270-277` implements `"Wick"` only | parity at the default (`pine:L45` = `"Wick"`) |
| **D-13** | **RR is a drawing in the Pine; E-1 turns it into a real take-profit.** | `pine:L313-325` (`ict_CreateRR` — horizontal lines only; `grep -c "strategy\."` → **0**) | `e1:L79`, `e1:L273`, `e1:L277`, `e1:L302` | doc-derived addition (`doc:L170`), must be labelled |
| **D-14** | **Expiry clock.** Pine drops at `bar_index - fvgBar1 > graceCandles` *after* the trigger test ⇒ the trigger can still fire on evaluation bar `fvgBar1+16`, whose confirmation candle is `fvgBar1+15`. E-1 measures the **confirmation candle's** age `(k-1) - c`. | `pine:L499-500`, `pine:L437`, `pine:L658` | `e1:L248`, `e1:L294` | **MATCH** (both yield confirmation-candle age ≤ 15) — see §A.5 for the lower bound |
| **D-15** | **`hideLosing` erasure correctly NOT reproduced.** | `pine:L519-525` | every candidate is retained with an outcome | **MATCH** (INV4 honoured) |
| **D-16** | **Outcome-vocabulary defect** (not a fidelity divergence, a reporting bug): candidates that expire mid-series are appended to `done` **without** an `outcome`, while only candidates still pending at the *end* of the series get `outcome="expired"`. | — | `e1:L294-295` (append, no assignment) vs `e1:L318-319` (assign `"expired"`); `e1:L330-331` then reports `expired` and `unresolved` | see §A.4 |
| **D-17** | **"One position at a time" is a *deferred-entry* queue, not a dropped-signal queue** (methodology, not fidelity). | — | `e1:L253-254` `continue` leaves the candidate in `pending`, retried on every later bar; and the trigger block (`e1:L239-253`) runs **before** the resolution block (`e1:L298-316`) inside the same bar, so a position resolving on bar *k* still blocks bar *k* | see §A.4 |
| **D-18** | ATR floor is an addition relative to the Pine. | Pine has **no** ATR (`grep -ci atr` → 0) | `e1:L196-201` | doc-derived (`doc:L121`), implemented exactly |
| **D-19** | **Cost is applied after the fact, not inside the trade.** `outcome`/`r` are computed cost-free; `--cost-r` is subtracted from the *mean* R only. PF in the results is **gross**. | Pine has no cost model at all (`strategy.*` → 0 hits) | `e1:L303-312` (cost-free), `e1:L380` (`expectancy_net_r = expectancy_r - cost_r`) | D9 wants a 0/1/2-tick sweep; E-1 reports one cost level per run |

**[FACT]** The E-1 docstring's own provenance table (`e1:L21-33`) lists six Pine citations — FVG
geometry, expiry, inversion trigger, stop placement, RR targets — plus the bar-indexing convention
(`e1:L35-41`). It does **not** claim the leg tracker, the BE gate, the BE resolution, the candidate
arbitration, or the level consumption. So E-1's self-description is honest: it is a *code-derived
core*, not a full port.

## A.4 Two E-1 defects that are **not** fidelity divergences but do affect the numbers

**[FACT] D-16, measured.** In a 5 000-bar synthetic series (12 seeds, 6 692 confirmations), the
outcome census is `{stop: 449, target: 213, '': 441, expired: 8}` — i.e. **441 mid-series expiries
carry no outcome label**, while `summarise` reports `expired = 8` and `unresolved = 0`. No code path
ever assigns `"open"`, so trades still open at the end of the series are labelled `"expired"`.
The P&L statistics are unaffected (`closed` = `stop`/`target` only, `e1:L325`), but **the candidate
census is mis-reported by ~99 %** — and a "candidate log" built on this vocabulary would be wrong.

**[FACT] D-17, measured.** In the same harness the one-at-a-time arm confirmed **52** candidates at
the *first* bar on which the trigger condition held and **10** at a **later** bar — i.e. **16 % of the
"one position at a time" trades are deferred entries**, taken at a different (worse) price than the
signal, with the stop recomputed over the longer window `[c .. k']`. The remaining 1 326 of 1 415
candidates never confirmed at all — their window expired while a position was open.

**[INFERENCE]** The D4 trap (one position at a time) is *structurally* respected — the trades do not
overlap — but the arm is not a literal portfolio backtest: it is a queue. Any future E-2 on NQ must
**drop** the signal instead of deferring it, and must report the deferral rate.

## A.5 The age-0 correction: the inversion window is **[1, 15]**, not [0, 15]

**[FACT] The proof.** Take the Pine's own two lines.

*Bullish FVG* (`isLow = true`): `pine:L354` `fvgHere = low[1] > high[3]`; `pine:L356`
`fvgBottom = high[3]`. The trigger for a bullish-source FVG is `pine:L437`
`close[1] < e.fvgBottom`, i.e. `close[1] < high[3]`. But on the bar where the FVG is created,
`close[1] ≥ low[1] > high[3]`. **Contradiction** ⇒ age 0 can never trigger.

*Bearish FVG* (`isLow = false`): `pine:L354` `fvgHere = high[1] < low[3]`; `pine:L355`
`fvgTop = low[3]`. The trigger is `pine:L437` `close[1] > e.fvgTop`, i.e. `close[1] > low[3]`. But
`close[1] ≤ high[1] < low[3]`. **Contradiction** ⇒ age 0 can never trigger.

A body close can never lie outside its own bar's wick range, so the FVG's own completion bar can
never also be the inversion bar. The same argument holds in `"Series"` mode: the merged
`fvgBottom` is `min(high[c-4], high[c-2])` ≤ `high[c-2]` < `close[c]`, so the merged zone is not
reached by the same bar's close either.

**[FACT] The measurement.** Over 12 synthetic seeds / 4 000 bars each (6 692 confirmations), the
**minimum observed confirmation age is 1** and **age 0 occurs zero times**; and a direct scan of
every candidate found **zero** whose own newest bar would already satisfy the trigger.

**[FACT] What this corrects.**
`PINE_RULES` §0.3-2 ("The inversion window is `0–15` bars, not `7–15` … there is no lower bound"),
§R15 ("The confirmation bar may be the FVG's own newest candle — age 0"), §C-2 and §D.1, and
`AUDIT` §A.1.3 ("the confirmation candle's age therefore ranges 0 … 15 inclusive") all assert age 0 is
reachable. It is not. The correct statement is: the *evaluation* bar may be the FVG's completion bar
(`pine:L380` creates the candidate and `pine:L437` tests it on the same bar), but the *confirmation
candle* — whose close must penetrate — can never be that bar.

**[INFERENCE]** Consequences:
1. The code-derived window is **[1, 15]**, i.e. **15 ages**, not 16. "The code has no lower bound"
   remains true in the literal sense — there is no explicit minimum-age *test* anywhere in the file —
   but the **effective** lower bound is 1, enforced by the FVG/trigger geometry itself rather than by
   a test. Any port must therefore reproduce the *effective* window, not the absence of a test.
2. The doc's `[7, 15]` (doc:L123) still rejects **six** of those fifteen ages — the divergence is
   large and material, just not as large as "16 vs 9".
3. E-1's `code[0,15]` arm is *numerically identical* to a `[1,15]` arm; the age-0 case is unreachable
   in the implementation too, so no result changes.
4. **The doc's "7" is not a code rule, but it is not merely an invented UI label either.** `pine:L9`
   carries the **original indicator's own UI text**, inherited by the replica (`PINE_RULES` §0.3-2):
   `input.bool(true, title = "Allow 7 - 15 Candle IFVGs", tooltip = "If enabled, IFVGs may form within 15 candles.\nIf disabled, they must form within 6 candles.")`.
   The **title** says "7 - 15"; the **tooltip in the same input** says "may form within 15 candles"
   — no lower bound. So the *original indicator itself* carries the contradiction. The most
   defensible reading is that the original's behaviour is also max-only and the "7" is marketing
   text in the original's own UI, which the replica copied wholesale. **[INFERENCE]** this is
   consistent with `pineREADME:L48` ("The only thing his model does to control for this is require
   the FVG to invert within 7–15 candles") — the replica's author *believed* the lower bound existed
   and implemented only the upper one.

## A.6 Governance compliance (D2 / D4 / D8 / D9, INV4) — scored separately from the rules

| # | Obligation | Source | Status in E-1 | Score |
|---|---|---|---|---|
| G1 | One position at a time; never quote the concurrent arm's t-statistic | `decisions.md` D4 | Arm exists (`e1:L77`, `e1:L253`) but with **deferred-entry** semantics and a 1-bar blocking lag (§A.4 D-17) | **partial** |
| G2 | Costs in the config, reported at 0/1/2 ticks with the full round-trip fee; report the break-even round-trip cost in R | `decisions.md` D9 | `--cost-r` scalar (`e1:L369-372`), `be_cost_r` reported (`e1:L341`), but **PF is gross** and there is **no tick sweep** | **partial** |
| G3 | Every candidate persisted with its outcome; nothing erased | INV4 (`RULE_SPEC` §2.2), `decisions.md` D2 | **no erasure** ✓ (`e1:L289-320`) but **no persisted candidate log** (D2's parquet schema is unimplemented) and the outcome vocabulary is defective (§A.4 D-16) | **partial** |
| G4 | No look-ahead; decisions only on closed bars | INV6, `RULE_SPEC` §2.2 | Trigger uses `bars[k-1].c`; fill is `open(k+1)` or `close(k-1)`; ATR anchored at the FVG bar (`e1:L197`); sweep detector causal by construction (`e1:L154-166`) | **faithful** |
| G5 | "A/A+" must not be filtered on; report the distribution instead | `decisions.md` D8 | E-1 **declines** to apply A/A+ (`e1:L47-49`) — compliant in letter, but vacuous: no checklist exists to report | **n/a** |

**Governance tally: 1 faithful, 3 partial, 1 n/a.**

---

# B. Rule-by-rule conformance matrix

**Scoring rule.** For each rule I declare a **target**:
**PINE** = the replica's code is normative (verifiable, quotable) · **DOC** = the discussion prose is
normative (unverifiable against the closed-source original) · **BOTH** = the two agree ·
**GOV** = a project-governance rule, scored in §A.6 instead.
**Present in our code?** = does any file in this repo implement it. **Faithful?** =
`faithful` / `partial` / `absent` against the declared target.

`N = 30` rule rows.

| # | Rule | Target | Source (doc / pine) | Present in our code? | Faithful? | Gap / what is needed |
|---|---|---|---|---|---|---|
| 1 | Killzone activation: NY AM 09:30–11:30, NY PM 13:30–15:30 ET | **DOC** (hard gate) — in the Pine the sessions gate **alerts only** | doc:L114-116 · pine:L123-126, L497-498 | **No** — no session logic anywhere in `e1` | **absent** | A `session_id` + killzone predicate in the state machine, evaluated on the bar's **close** timestamp in `America/New_York`, DST-aware (`RULE_SPEC` A21). Note the Pine's own default window is `0930-1600` (`pine:L60`) and it is **not** a signal gate — so "faithful to the Pine" and "faithful to the doc" are *different* rules; both must be configurable and A/B'd. |
| 2 | PDH/PDL, Asian/London session highs/lows | **DOC** | doc:L116 | **No** | **absent** | Needs an exchange session calendar (CME Globex day 18:00→17:00 ET ≠ calendar day) — see §C.3 and `AUDIT` §C.5. |
| 3 | Unreclaimed 15m / 1H FVG zones | **DOC** | doc:L116 | **No** | **absent** | The Pine has the closest thing (HTF FVG zones, `pine:L635-647`) but as an *optional* gate (`pine:L12` default `false`) with no "unreclaimed" concept beyond mitigation (`pine:L270-274`). A port needs closed-HTF-bar-only publication (no lookahead) + a mitigation flag. |
| 4 | HTF-FVG confluence gate (price-band overlap) | **PINE** (default **off**) | pine:L635-647, L444-445 | **No** | **absent** *(parity at Pine defaults)* | Implementable: same 3-candle geometry on closed HTF bars, inclusive band overlap (`pine:L230-237`), zone mitigation, `maxHtfZones=3` with a keep-alive exemption. Turn on **only** as a labelled arm. |
| 5 | Liquidity sweep detection (doc: EQH/EQL/PDH/PDL) | **BOTH** — *different objects* | doc:L118 · pine:L560-575, L616-630 | **Partial** — `e1:L154-183` | **partial** | E-1 uses a 5-bar fractal on the **same** timeframe, keeps only the **last** pivot level, adds a **body-reclaim** condition (`e1:L179/L181`) and never consumes a level. The Pine uses a 3-bar fractal on a hand-aggregated **HTF** series, a *set* of levels, a strict pierce with **no** body condition, and **one-shot consumption**. The doc's object (EQH/EQL/PDH/PDL) is a third object again. Needs three separate detectors, each labelled. |
| 6 | Sweep level consumption (one-shot) | **PINE** | pine:L560-575 (`this.points.remove(i)`) | **No** | **absent** | A level can be swept repeatedly in E-1 → more sweeps, and a different `swept` flag. A faithful port must consume levels *unconditionally*, even when no leg is active (`PINE_RULES` §D.4). |
| 7 | Sweep as a **precondition** of the setup (前置条件 A) | **DOC** (mandatory) — **PINE**: optional gate, default off (`pine:L11`) | doc:L118 · pine:L443, L447 | **Partial** — `e1:L251` | **partial** | E-1 requires the sweep **on the confirmation bar** (`swept[k-1]`); the doc requires the sweep **before** the FVG, in the same impulse leg (`doc:L121`, `RULE_SPEC` A06/A12/A13); the Pine requires *a* sweep **since the origin pivot** (`pine:L421-424`). Three incompatible associations — needs a decision, then one implementation. |
| 8 | SMT divergence vs ES/YM, weight **+2** | **DOC** | doc:L119 · Pine: **absent** (`grep -ci smt` → 0; the only `request.security` is same-symbol, `pine:L635`) | **No** | **absent** | Needs a second instrument subscribed on the same timeline, a "same leg" definition (`RULE_SPEC` A08), and a level/rank for the "+2". The score itself has no artefact (`PINE_RULES` R18). |
| 9 | 3-candle FVG geometry, strict, wick-based | **BOTH** | doc:L121 · pine:L354-356 | **Yes** — `e1:L191-195` | **faithful** | — |
| 10 | Minimum gap `> 0.25 × ATR(14)` | **DOC** (the Pine has **no** ATR filter) | doc:L121, L280 · `grep -ci atr` → 0 | **Yes** — `e1:L196-201`, arm `e1:L72` | **faithful** | Implemented exactly (strict `>`). Anchored at the FVG's own bar (`e1:L197`) per `RULE_SPEC` A02. |
| 11 | ATR(14) definition, smoothing, warm-up | **DOC** | doc:L121 · `RULE_SPEC` A02/A03 | **Yes** — `e1:L137-152` | **faithful** | Wilder RMA, seeded at index 14, `None` while warm → no signal. Matches A03. |
| 12 | Inversion: **body close** strictly through the **far edge** | **BOTH** | doc:L123 · pine:L437, L441 | **Yes** — `e1:L242-245` | **faithful** | Strict `>`/`<`, on the *previous* bar's close, direction inverted vs the FVG type. ✓ |
| 13 | Inversion **window** | **DOC** `[7,15]` · **PINE** `[1,15]` | doc:L123 · pine:L9, L437, L499, L658 | **Yes** — both arms, `e1:L71` | **faithful** | The code arm is **numerically `[1,15]`**, not `[0,15]` (§A.5). The doc's "7" is the **original's own UI title** (`pine:L9`) contradicted by **its own tooltip** in the same input — it is a label, not a rule, and the doc's band rejects 6 of the 15 code ages. Keep `INVERSION_MIN_BARS`/`INVERSION_MAX_BARS` as separate constants and A/B them (`RULE_SPEC` A05). |
| 14 | `requireBEIntact` gate | **PINE** (default **on**; code-only, undocumented in the doc) | pine:L10, L442, L447 | **No** | **absent** | Needs the swing origin (row 15) first. It is a *predictive* filter (it removes setups **before** they exist), unlike `hideLosing` — so its absence changes the population, not just the rendering. |
| 15 | Swing-origin tracker (origin price + origin bar) | **PINE** (code-only) | pine:L350-369 | **No** | **absent** | Upstream of rows 14, 16, 17, 19, 20. Also carries the unresolved **one-bar ambiguity** (`PINE_RULES` §E-1, `AUDIT` §A.1.7: does `ta.lowestbars(3) == -1` mean "the extreme is the current bar" or "1 bar ago"?). Port **both** variants and reconcile. |
| 16 | FVG search window `bar_index-3 ≥ originBar-1` + leg freeze/unfreeze | **PINE** (code-only) | pine:L371-377, L426-429 | **No** | **absent** | Materially restricts *where* an FVG may form. The freeze release does **not** reset the origin (`PINE_RULES` §D.2) — a port that resets it will produce different BE levels. |
| 17 | One live candidate per direction ("Single" / "Series") | **PINE** (code-only) | pine:L383-403 | **No** — `e1:L203` keeps every gap | **absent** | **The highest-impact single omission** — see §D.3. The Pine's pending set is ≤ 2 (one per direction) and the worse gap is *deleted* from the array; E-1's is unbounded. |
| 18 | Stop placement: window extreme (Wick / Body / IFVG) | **PINE** (`Wick`) vs **DOC** ("beyond the recent swing high/low", doc:L13) | pine:L45, L293-302, L461-470 · doc:L13 | **Yes** for the Pine's `Wick` — `e1:L267-277` | **partial** | The two sources name **different objects**: the Pine's stop is the FVG→confirmation **window extreme**; the doc's is the **swing extreme** — and the Pine uses the swing extreme for the *break-even* instead (`PINE_RULES` §C-16: the two levels are swapped relative to the doc). `Body`/`IFVG` placements (`pine:L468/L469`) are not implemented. Both stop objects must be implemented and reported separately; they define `R`, so they change every downstream statistic. |
| 19 | Break-even level = the swing origin | **PINE** (code-only; the doc mentions BE *tracking* only in describing the replica, doc:L48) | pine:L476 | **No** | **absent** | Needs row 15. Log the origin bar index with every setup so its staleness is auditable (`PINE_RULES` §D.5). |
| 20 | Break-even **resolution** ends the trade | **PINE** (code-only) | pine:L509, L531-539 | **No** | **absent** | Note the Pine's two BE tests are *not equivalent*: the gate uses the **close** (inclusive, `pine:L442`), the live resolution uses the **high/low** (inclusive, `pine:L509`) — port both, separately. |
| 21 | RR projection / fixed 1:2 target | **DOC** (phase 1: 固定 1:2, doc:L170) — the **Pine has no TP at all** (`pine:L313-325` draws lines only; `grep -c "strategy\."` → 0) | doc:L170 · pine:L50-51, L313-325 | **Yes** — `e1:L79`, `e1:L273/L277`, `e1:L302` | **faithful** *(to the DOC; a doc-derived addition to the code)* | Must be labelled "doc-derived" wherever reported: the code-derived artefact has **no** exit rule at all. |
| 22 | Entry mechanics | **PINE** (`close[1]`, `pine:L441`) vs **DOC** (market at the confirmation close; retest variant, `RULE_SPEC` A14) | pine:L441, L458 · doc:L13 | **Yes** — **both** arms, `e1:L71`, `e1:L257-262` | **faithful** | The honest `open(k+1)` arm and the code's `close(k-1)` arm are both implemented and A/B'd, exactly as `PINE_RULES` §E-5 requires. Keep both as config flags; never report one without the other (E-1's own result shows the sign flips across this arm). |
| 23 | Target = the next liquidity pool at **≥ 2R** | **DOC** | doc:L126 | **No** | **absent** | See §C.2. Requires a liquidity-level universe (PDH/PDL, session extremes, unmitigated swing pivots). LRLR is **not** computable (`AUDIT` §C.2). |
| 24 | Checklist (a): no uncleared opposing **OB** / tight equal-high-low in front | **DOC** | doc:L125 | **No** | **absent** | See §C.4 — there is **no OB detector in any artefact** (`AUDIT` §C.5); the "tightly adjacent" tolerance is undefined (`RULE_SPEC` A09). |
| 25 | Grade **A+ / A / B / C** | **DOC** | doc:L45, L107, L170 · Pine: **zero** hits for `score\|grade\|checklist` | **No** | **absent** — *and unimplementable as written* | See §C.1 and `decisions.md` D8: implement the **five named conditions as booleans**, expose the sum as `checklist_score`, **report** the distribution, **do not filter**. |
| 26 | Bias direction filter (long-only / short-only) | **PINE** (default `Neutral`) | pine:L7, L659-670 | **No** | **absent** *(parity at default)* | Cheap to add; note the naming inversion (`enableBearOutput` gates the **bullish-FVG** tracker, which produces **shorts**). |
| 27 | `hideLosing` post-hoc erasure — **must not** be reproduced | **BOTH** (the doc forbids it: doc:L49, L113, L172) | pine:L8, L519-525 · doc:L49, L113 | **Yes — correctly NOT reproduced** (`e1:L289-320` keeps every candidate with an outcome) | **faithful** | The one place where our code honours a hard invariant. The Pine's default is `true` — i.e. the upstream artefact **does** erase losers, and the doc's warning is confirmed at code level. Keep E-1's behaviour; never implement `hideLosing` as a filter, only as a chart-renderer option. |
| 28 | `setupHistory` display cap (+ its management side-effect) | **PINE** (code-only) | pine:L13, L482-495 | **No** | **absent** *(safe direction)* | The Pine's cap of 2 silently **stops managing** an evicted unresolved setup. E-1 manages everything — the safer behaviour, but a different population. Reproduce as a *display* concern only. |
| 29 | Candidate array cap (50 per direction) | **PINE** (code-only) | pine:L78, L286-291 | **No** | **absent** *(safe direction)* | Same class as row 28: the Pine silently drops the oldest candidate when the array exceeds 50 per direction, so it can never trigger or be logged. |
| 30 | Sweep→leg association (the leg-scoped `swept` flag) | **PINE** (code-only) | pine:L405-424 | **No** | **absent** | `swept` = "a sweep occurred **since the origin pivot**"; it is reset only when a new pivot fires (`pine:L366`). E-1 has no leg, so it has no such flag — this is why row 7 can only be "partial". |

### B.1 Notes on three rows that need reading carefully

**Row 1 (killzone).** The replica's sessions are **alert-only** (`pine:L497-498` is the sole consumer);
the setups are created and drawn **regardless of session**. `AUDIT` §A.1.6 verified this. The doc's
killzones (doc:L115) are a **hard activation gate** and the Pine has **no counterpart**. So there is
no single "faithful" implementation of row 1 — there are two, and they disagree. Implement the
killzone as a **configurable gate, default OFF** (to match the code), and report the doc-literal
variant as a separate arm.

**Row 13 (window).** See §A.5. The label-vs-rule point stands and is now sharper: `pine:L9` carries the
original's **own** contradictory title/tooltip pair, so the "7" originates in the closed-source
indicator's UI, not in the doc's author. The doc's `[7,15]` is a *literal reading of a UI label*.

**Row 18 (stop).** Because `R` is defined from the stop, this row silently controls rows 10, 21, 23
and every expectancy/PF figure. Its two candidate objects (window extreme vs swing extreme) produce
**different win rates** (a tighter stop is hit more often) and different cost sensitivity (cost in R
scales as 1/R). It must be implemented as two named variants and reported side by side — never
silently picked.

---

# C. The four unimplementable / undefined rules

## C.1 The grade system (A+ / A / B / C)

**[FACT] It exists in no artefact.** Evidence, exhaustively:

| Source | Grade system? |
|---|---|
| `doc` prose | Three mentions, **no thresholds**: L45 `多重共振评分系统（A+ 至 C 级）`, L107 `仅接受 A+ 级带 SMT 背离信号`, L170 `Checklist 过滤（只做 A/A+ 级）` |
| `pine:L1-694` | **Zero.** `grep -niE "score\|grade\|checklist"` → no hits; `input.*` count = 50, none scoring-shaped; the only score-like artefact is a cosmetic `+`/`-` and a volume dot in the label text (`pine:L453-454`) |
| `pineREADME:L18` | *"Setup grade box — left out entirely. Dodgy himself has said the grading is mechanical, meaning there's a fixed set of rules generating the grade that doesn't imply actual grade."* |
| Every other artefact (qlib, AlphaGPT, xauusd, ICT corpus, Kaggle, lake) | **Zero** (`AUDIT` §C.1) |
| `RULE_SPEC` §1.7 | A **proposal**, tagged `[UNSPECIFIED]` A09/A10 — not evidence |

**[FACT]** The replica's own input `pine:L45` (`slPlacement`) etc. contain **no** scoring input; and
`AUDIT` §A.1.4 verified `atr|smt|score|grade|checklist|a+` → **0** hits case-insensitively.

**What it would take to make it implementable.** Nothing — it cannot be *recovered*, only *invented*.
The only implementable form is the substitute fixed by `decisions.md` D8 and `AUDIT` §C.1: the doc's
**five named checklist conditions as five booleans**, exposed as `checklist_score`, **reported** as a
distribution and as a stratifier, **never filtered on**.

**What it costs.** The phase-1 gate's traded population has to be re-specified. `AUDIT` §C.1's
recommended population is `c1 ∧ c5` (sweep ∧ ATR floor) — which makes phase 1 **smaller** and, because
the doc's rubric weights SMT at +2, an "A/A+" filter is *implicitly* an SMT filter, so "phase 1 is
rule-only" would not even be true of the doc's own gate.

## C.2 The "≥ 2R liquidity target"

**[FACT]** No artefact computes a liquidity pool. The Pine has **no** take-profit logic
(`pine:L313-325` draws lines; `strategy.*` → 0 hits); `pineREADME:L17` says the replica author
*"went with RR based targets instead of nearest liquidity"* and quotes the original's dev saying
*"nearest-liquidity TP is too mechanical"*.

**[FACT]** `AUDIT` §C.2 fixes the computable subset: the level universe is
**{PDH, PDL, session highs/lows, unmitigated swing pivots}**, with the ICT corpus's "opposite swing
extreme" as a defensible proxy for "unmitigated swing pivot" (verified on 1 447/1 447 VALID rows).
**LRLR (one-sided liquidity) is not computable** — it needs a stop-density or order-book model we do
not have.

**What it would take.** (i) a session-calendar-pinned PDH/PDL + session-extreme table; (ii) a swing-pivot
store with a documented mitigation rule; (iii) an explicit price-tolerance constant for EQH/EQL
clustering; (iv) a stop placed first, because the ≥2R distance is **coupled to the stop choice** —
changing the stop changes the traded population.

**What it costs.** One of the five checklist booleans (`c4`) depends on it; `c4` is part of `AUDIT`
§C.1's proposed `A+ ≡ c1 ∧ c2 ∧ c4` label, so without it the `A+` label is not computable either.

## C.3 PDH/PDL and session highs/lows — computable from 1-minute bars alone?

**[FACT]** **Yes, but not for free.** `AUDIT` §C.5: PDH/PDL is the previous *trading day's* high/low,
which from 1-minute bars needs (i) an **exchange calendar** to fix the RTH boundary — the CME Globex
day runs 18:00 ET → 17:00 ET next day, **not** a calendar day — and (ii) a decision on whether
"previous day" means the previous Globex day or the previous RTH day, **which the doc does not make**.
DST is a second trap: the session boundary is 23:00 UTC under EST and 22:00 UTC under EDT.

**[FACT]** EQH/EQL are computable from 1-minute bars (cluster pivot levels by price) **only after an
explicit tolerance constant is chosen** — the tolerance is undefined in every artefact, and it changes
which setups exist.

**[FACT]** The doc's *third* object is not computable at all: "紧贴的等高/等低点" (row 24) needs the same
clustering **and** an OB detector.

**What it costs.** An exchange calendar (a data dependency we do not have), plus a documented
"previous day" definition, plus a tolerance constant, plus a decision on the doc's Asian/London
session boundaries (never specified).

## C.4 Opposing OB / equal-high-low obstruction

**[FACT]** The reference implementation has **no order-block concept**: `grep -rliE "order_?block"`
over the Pine and over `qlib/qlib` → no hits (`AUDIT` §C.5). The only OB detector in the corpus is
`xauusd-ml-trader`'s, and `decisions.md` D7 rates it **ADAPT with the look-ahead fixed** — its OB is
"registered before its displacement", i.e. exactly the defect that makes it unusable as-is
(`AUDIT` §A.4.1).

**[FACT]** The ICT corpus's 4-gate structure (`VALID`/`INVALID`) is the only concrete checklist spec
in existence, and its Gate 2 is *"sweep asserted | SMT confirmed or absent"* — **no OB gate at all**
(`AUDIT` §C.5).

**What it would take.** A causal OB detector (a displacement leg's last opposite candle, published
**after** the displacement) plus a "cleared" state, plus a proximity tolerance for the equal-high/low
half.

**What it costs.** A new detector with no reference implementation to validate against, and a
look-ahead hazard that must be re-audited. **[PROPOSAL]** For phase 1, record `c3` as
**not-implemented** and exclude it from the grade labels — as `AUDIT` §C.1 already recommends.

---

# D. Faithfulness verdict

## D.1 The count

**Conformance over the `N = 30` rule rows of §B:**

| Bucket | Count | Rows |
|---|---|---|
| **Faithful** | **8** | 9 (FVG geometry), 10 (0.25×ATR floor), 11 (ATR-14), 12 (inversion trigger), 13 (window, both arms), 21 (1:2 target, doc-derived), 22 (entry mechanics, both arms), 27 (no `hideLosing` erasure) |
| **Partial** | **3** | 5 (sweep detection), 7 (sweep precondition), 18 (stop placement) |
| **Absent** | **19** | 1, 2, 3, 4, 6, 8, 14, 15, 16, 17, 19, 20, 23, 24, 25, 26, 28, 29, 30 |
| **Total** | **30** | |

**→ 8 faithful / 3 partial / 19 absent out of 30 (27 % faithful).**

**Governance (§A.6), scored separately: 1 faithful / 3 partial / 1 n/a out of 5.**

**[INFERENCE]** Read the number with its denominator in mind. 8/30 measures the *rule engine* against
a rule set drawn from **two disagreeing sources**. The 8 faithful rows are exactly the rules on which
the doc and the code **agree** — i.e. the intersection, which is the only part of "DodgysDD's logic"
that is unambiguous. **The correct summary is not "27 % implemented"; it is "the intersection is
implemented, and neither source's exclusive content is."**

**[FACT]** The faithful 8 are also, with one exception, the rules that E-1 chose *because* they were
in the Pine — the exception being row 21 (the 1:2 target), which the doc alone specifies.

## D.2 The minimum implementable set for the phase-1 gate

The gate (`doc:L170`): *"no ML, fixed 1:2 RR, Checklist filter (A/A+ only), EV must be positive under
~$4.5 round-trip fees and 1–2 ticks of slippage — **Profit Factor > 1.25**. If the pure-rule stage
is negative, the rule reproduction is wrong — never paper over it with ML."*

**[PROPOSAL] Minimum set — 11 items, in dependency order.** Everything else may wait.

| # | Item | Why it is in the minimum | Already have? |
|---|---|---|---|
| M1 | **Swing-origin / leg tracker** (origin price + origin bar, per direction) | upstream of M2, M6, M7 and of the BE level; without it there is no "leg" and therefore no "impulse leg" | ✗ |
| M2 | **One live candidate per direction** + the `Single` "better gap" arbitration + the leg freeze | this is what makes the setup population the same size as the reference's | ✗ |
| M3 | **FVG geometry + `close[1]` trigger + the confirmation-candle age window** | the core; keep E-1's implementation, correct the window to `[1,15]` | ✓ (E-1) |
| M4 | **ATR(14) Wilder + the 0.25×ATR floor** | the doc's only quantitative filter; already an arm | ✓ (E-1) |
| M5 | **Stop placement, both objects**: the Pine's *window extreme* and the doc's *swing extreme* | the stop defines `R`; it silently controls the target, the win rate, the PF and the cost sensitivity | partial (window extreme only) |
| M6 | **Break-even level = the swing origin** + the `requireBEIntact` gate | the Pine's default-ON predictive filter; it removes setups before they exist | ✗ |
| M7 | **Liquidity-sweep detector** with the level-consumption semantics, on a **documented** object (HTF fractal pivots *and/or* EQH/EQL/PDH/PDL) | the doc's 前置条件 A; also the sweep→leg association | partial |
| M8 | **Killzone / session gate, config flag, default OFF** | the doc's Step 1; the Pine has none — so it must be an *arm*, not the default | ✗ |
| M9 | **PDH/PDL + session extremes + an EQH/EQL pivot store** with an explicit tolerance | needed for the sweep objects *and* for the ≥2R target | ✗ |
| M10 | **Candidate log** to D2's parquet schema, one row per candidate, every candidate retained | INV4; without it there is no training data and no auditable census | ✗ (in-memory only) |
| M11 | **One-position-at-a-time accounting that *drops* blocked signals** (not defers them) + costs applied **inside** the trade classification + PF reported at 0/1/2 ticks | D4's trap and D9's cost model | partial |

**[FACT] What remains unimplementable even after M1–M11 are built:**

1. **"A/A+ only"** — the phrase has no definition (row 25, §C.1). It must be replaced by the D8
   substitute: five booleans, `checklist_score` reported, grades **labelled** post-hoc
   (`AUDIT` §C.1: `A+ ≡ c1 ∧ c2 ∧ c4`, `A ≡ c1 ∧ c4`, `B ≡ c1`, `C ≡ ¬c1`, with `c3` excluded as
   not-implemented). **The literal gate text remains unimplementable.**
2. **The OB clause of the checklist** (row 24, §C.4) — no OB detector exists in any artefact.
3. **The "tightly adjacent" equal-high/low tolerance** (row 24) — undefined in every artefact.
4. **LRLR as a liquidity target** (§C.2) — not computable without a stop-density/order-book model.
5. **The doc's SMT "+2" score** (row 8) — computable only after a "same leg" definition
   (`RULE_SPEC` A08) and a reference instrument; and the *score* has no artefact, so it can only be a
   recorded boolean.
6. **The doc's "≥2R" target as the actual TP** (row 23) — the replica uses RR targets and the original's
   dev calls nearest-liquidity TP "too mechanical" (`pineREADME:L17`). Implement it as an
   **eligibility filter** (`c4`), never as the pricing rule, or phase 1 silently becomes a
   different strategy from the one being tested.

**[INFERENCE]** With M1–M11, the phase-1 experiment becomes *meaningful* but is still **not** the
doc's phase 1: it is "the code-derived core + the doc's ATR floor + the doc's killzone and sweep as
switchable arms + a labelled grade". That is the honest maximum.

## D.3 The highest-risk fidelity gap

> ### **Row 17 + row 15: the swing-origin leg tracker and the "one live candidate per direction" arbitration.**
>
> **The rule:** the reference does **not** scan for FVGs. It scans for **swing legs**, and inside a
> leg it keeps **at most one live candidate per direction**, deleting the worse gap from the array
> (`pine:L383-403`); an FVG may only be created inside the leg and only while the leg is not frozen
> (`pine:L371-377`, `pine:L426-429`).
>
> **Why it is the highest risk.**
> 1. **It changes the denominator, not a subset.** Every other missing rule is a *filter* on a
>    population that already exists. This one determines how large the population is. The Pine's live
>    pending set is **≤ 2**; E-1's is unbounded (`e1:L203`).
> 2. **The measured symptom is already in the numbers.** E-1's concurrent arm on 2 046 240 BTCUSDT
>    1-minute bars produced **423 759 simultaneous positions** (`E1_RAW_OUTPUT_btcusdt1m_full.txt`)
>    — roughly one candidate every five bars. `pineREADME:L44-46` names *exactly* this as the
>    reference's central pathology: *"This indicator is constantly scanning for setups, and that's a
>    bad thing. Price is always forming FVGs, if there's a swing, there's basically always an FVG in
>    it."* **E-1 reproduces the pathology, not the mitigation.**
> 3. **It is upstream of three other absent rules.** The origin supplies the **break-even level**
>    (row 19), the **`requireBEIntact` gate** (row 14, default-ON and *predictive*), and the
>    **leg-scoped `swept` flag** (row 30) that makes row 7 possible at all. Implementing rows 14/19/30
>    without it is impossible.
> 4. **It is the only absent rule that could not be A/B-tested as an arm.** The ATR floor, the window
>    and the fill were all cheap A/B arms in E-1. The leg tracker requires **re-architecting the
>    candidate generator**; it cannot be bolted on as a filter. Every number E-1 produced therefore
>    carries an **unquantified** risk on this axis.
> 5. **[INFERENCE]** It also determines whether E-1's negative result is *about the strategy* or
>    *about the scanner*. With 423 759 overlapping candidates, the one-position-at-a-time arm is
>    selecting a small, mechanically-arbitrary subset of a hugely over-populated census — which is
>    exactly the condition under which the "no edge" verdict could be an artefact of the population
>    construction rather than of the iFVG pattern.
>
> **Runner-up (different axis): row 18, the stop object.** The Pine's *window extreme* and the doc's
> *swing extreme* are different objects, and `R` is derived from the stop — so this row silently
> controls the win rate, the PF, and the cost-in-R. It is cheap to fix (two variants) but it must be
> fixed before any PF is quoted.

---

# E. The reference replica's own verdict

## E.1 What the README says (verbatim)

**[FACT]** `pineREADME`:

> *"**So does the strategy have any value?** NO"* (L52-54)

> *"This indicator is constantly scanning for setups, and that's a bad thing. Price is always forming
> FVGs, if there's a swing, there's basically always an FVG in it. And given enough time, that FVG
> will always become an IFVG."* (L44-46)

> *"The only thing his model does to control for this is require the FVG to invert within 7–15
> candles, which cuts down the number of setups shown, but doesn't meaningfully increase how often
> they actually work out."* (L48)

> *"**Setup grade box** — left out entirely. Dodgy himself has said the grading is mechanical, meaning
> there's a fixed set of rules generating the grade that doesn't imply actual grade."* (L18)

> *"**HTF FVGs** — he never properly explains how he uses these. In practice they're treated as extra
> confluence at best. If a trade goes to profit without an HTF FVG lining up, **he still takes it**."*
> (L16)

> *"I also built HTF sweep confirmation into IFVG detection (turn on in settings) expecting it to clean
> things up. Setup quality barely changed, if anything it looked slightly worse. So I didn't bother
> coding HTF FVG confluence or SMT on top of it, especially since he takes trades without them as
> well."* (L50)

> *"**He hides invalidated IFVGs.** Meaning any setup that hit stoploss before reaching break even.
> This is in the code itself, it's not real-time quality filtering, it just removes losers after the
> fact it has happened."* (L28)

> *"**He isn't consistent about where his stop actually is.** There are clear cases where a stop placed
> below the IFVG low would have failed, and in those videos he explains it as the stop being below
> structure low instead. But on trades where the IFVG-low stop would have worked, he frames it as the
> stop being at the IFVG low, because it gives a higher RR. Both explanations get used depending on
> which one makes the trade look better after the fact, not based on a fixed rule stated up front."*
> (L34-36)

> *"**Any IFVG setup Dodgy sees on his chart is going to show up here too.**"* (L20)

## E.2 Analysis

**[INFERENCE]** The README separates two things that the doc conflates:

1. **The indicator's behaviour** — a deterministic, closed rule set that *draws* boxes. This is
   reproducible. The replica's claim (L20) is that it reproduces it.
2. **The author's actual trading behaviour** — discretionary, hindsight-explained, and *not* a rule set.

**[FACT]** The doc's Step 1/Step 2/Step 5 (killzones, PDH/PDL + HTF FVG context, SMT, the checklist, the
grade) describe the **idealised** system — i.e. the *indicator's* marketing description of itself.
The README says, from the author's own observation, that the human behind it **does not** trade that
way: he takes trades without HTF confluence (L16, L50), his grading is "mechanical" (L18),
and his stop placement is decided after the fact (L34-36).

**[INFERENCE] Therefore the two candidate fidelity targets differ, and the difference is exactly the
doc's Step 1, Step 2 and Step 5:**

| | Original **indicator's** behaviour | Original **author's trading** behaviour |
|---|---|---|
| Deterministic? | **Yes** — a Pine indicator, same input ⇒ same output | **No** — discretionary, hindsight-explained |
| Killzones / HTF context | Alert windows only (`pine:L497-498`) | Not a precondition |
| Sweep | Optional gate (`pine:L11` default `false`) | Taken with or without |
| SMT | **Absent from the code** | Taken without it (README L50) |
| Grade | Cosmetic in the replica (README L18) | "Mechanical" — a label, not a filter |
| Stop | Window extreme / IFVG edge (`pine:L461-470`) | **Inconsistent** (README L34-36) |
| Target | RR lines (`pine:L313-325`) | Discretionary; "nearest liquidity is too mechanical" (README L17) |
| Losers | Erased post-hoc by default (`pine:L8`, L519-525) | Never visible (README L28) |

**[INFERENCE] The answer to "what is the faithful target?":**

> **The faithful target must be the *indicator's behaviour*, not the author's trading behaviour.**
> Three reasons:
> 1. The author's trading behaviour is **not a rule set**, so "faithfully reproducing every rule" has
>    no referent. `doc:L80`'s mandate ("严格遵循 DodgysDD 的原始逻辑…忠实表达这一系列的每个规则") can only
>    be satisfied against something with rules.
> 2. `doc:L101` forbids replacing the iFVG rules with black boxes and `RULE_SPEC` INV8 requires the
>    engine to be "a pure function of bar history". A discretionary, hindsight-driven filter is
>    precisely a **predictor** — INV8 says the strategy *reacts*. Reproducing the author's behaviour
>    would violate the doc's own core principle.
> 3. The doc's Step 1/2/5 are the author's **description** of the indicator, and the README shows the
>    description is aspirational. Building the engine to the description would be building something
>    that **never existed**.

**[FACT] The corollary, and it is uncomfortable:** the doc's 5-step state machine (doc:L113-126) is a
**specification of the author's marketing description**, not a reverse-engineering of the code. The
replica's README is the closest thing we have to an *observation* of what the indicator actually does,
and it contradicts Steps 1, 2 and 5.

**[PROPOSAL] The operational consequence — how to hold both at once:**

1. **Two labelled rule sets, never merged.** `CODE` (every rule the replica implements, verbatim) and
   `DOC` (every rule the prose describes). Every candidate row in the log carries **which set
   produced it**. This is the honest form of `PINE_RULES` §E-3's advice.
2. **`CODE` is the baseline; `DOC` is an arm.** The baseline backtest is the code-derived core.
   Every DOC-only rule (ATR floor, killzone, sweep precondition, SMT, checklist, grade) is added
   **one at a time**, and its **marginal contribution is reported** — never bundled, never called
   "faithful".
3. **Never present a DOC-derived rule as code-verified.** `PINE_RULES` §E-7 and `AUDIT` §D.2 both
   require this.
4. **The grade is a *label*, never a filter** (`decisions.md` D8, `AUDIT` §C.1).

**[FACT] And the two verdicts now agree.** E-1 measured E[R] ∈ [−0.024 R, +0.014 R] over 32 arms on
2 046 240 real BTCUSDT 1-minute bars with one position at a time, every 95 % CI including zero, PF
never above 1.051 (`E1_RESULTS.md` §3.0, `decisions.md` D4). The replica's author — who reverse-
engineered the closed-source original from the author's own videos — concludes **"NO"** (`pineREADME:L52-54`).
**Two independent lines of evidence now point the same way.** **[INFERENCE]** this raises the prior that
the strategy has no mechanical edge, and it is why `decisions.md` D4 forbids starting phase 2 on the
strength of a positive ML result.

**[INFERENCE] But the replica's verdict is about the *code-derived* strategy on the author's *own*
chart data, and it is a statement about the *indicator*, not a proof about the *doc's* rules.** Three
things it does **not** settle: (i) the doc's ATR floor, killzone, sweep precondition, SMT and checklist
are **not in the code**, so the replica never tested them (he did test the HTF sweep filter and found
it made quality "slightly worse", L52-56 — the closest available evidence, and it points the wrong way
for the doc's Step 2); (ii) the replica's stop is *his* choice, and the README's own complaint (L34-36)
is that the author's stop placement is inconsistent — so **no** stop object in this repo is verified
against the author; (iii) his sample is one market's chart history, not a 3.9-year 1-minute panel.

**[INFERENCE] The sharpest reading of the README for our purposes is this:** the author's *own* claim
that the model has a filter is the inversion window — and the replica's author, having implemented it,
says it *"cuts down the number of setups shown, but doesn't meaningfully increase how often they
actually work out."* **The one rule the doc and the code agree on as the model's only control is the
one the replica's author measured and found worthless.** And §A.5 has shown that rule's effective
window is `[1,15]` in code and `[7,15]` in the doc — so the doc's version rejects **6 of the 15** ages
the code allows, and **that difference is itself untested** (E-1's arms flip sign across it).

---

# F. Appendix — reproduction

**[FACT]** Every command below was run on this host, 2026-11-22, with
`PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`.

```bash
# §A.1 — implementation status
ls -d dodgys_dd_quant configs tests data artifacts
find . -name '*.py' -not -path './research/github/*' -not -path './research/kaggle/*' \
    -not -path './research/huggingface/*' -not -path './.git/*' -not -path './.pi/*'
git ls-files '*.py'

# §A.1 / §A.3 — the Pine's absences
grep -ci atr research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine      # 0
grep -c "strategy\." research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine  # 0
grep -c "input\."  research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine    # 50
grep -niE "score|grade|checklist" research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine  # 0

# §A.5 — the age-0 proof and measurement (the probe used is the one described in §A.4/A.5;
#         it imports e1_rule_falsification.py read-only and never writes to the repo)
$PY research/experiments/e1_rule_falsification.py \
    --data /home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet \
    --cost-r 0.05
```

**[FACT]** Files read (read-only; nothing outside `research/audit/L2_RULES.md` was written):
`.herd-swarm/decisions.md` · `research/analysis/PINE_RULES.md` · `research/docs/RULE_SPEC.md` ·
`research/audit/AUDIT.md` · `research/analysis/ML_REUSE.md` §A.9 ·
`research/experiments/e1_rule_falsification.py` · `research/experiments/E1_RESULTS.md` ·
`research/experiments/E1_RAW_OUTPUT_btcusdt1m_full.txt` ·
`research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` ·
`research/github/IFVG-Ultimate-Dodgy/README.md` · `iFVG几个模型的讨论.txt` ·
`research/jobs/leaf-L2-rules.md` · `.herd-swarm/tree.md` · `AGENTS.md` · `README.md` · `.gitignore`.
