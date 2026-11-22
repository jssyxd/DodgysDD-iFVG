# Leaf L2 — Rule fidelity: is DodgysDD's decision logic faithfully reproduced?

## Context
Project: `/home/da/桌面/DodgysDD_ifvg`. The design discussion demands (L80): *"归根到底，一定要严格遵循
DodgysDD的原始逻辑、系统理念，忠实表达这一系列的每个规则"* — faithfully reproduce **every** rule.

**Read-only audit leaf.** Own exactly one file: `research/audit/L2_RULES.md`.

## Required reading
- `.herd-swarm/decisions.md` — **D7** (fixed reuse verdicts), **D8** ("A/A+" is unimplementable as
  written), **D4** (the concurrency trap), **D5** (data reality).
- `research/analysis/PINE_RULES.md` — the rule-by-rule extraction from the reference Pine source.
- `research/docs/RULE_SPEC.md` — the spec derived from the prose, with its `[DOC]`/`[DERIVED]`/`[UNSPECIFIED]`
  tags and the `A01`–`A30` ambiguity register.
- `research/audit/AUDIT.md` §A.1, §A.2.
- The reference implementation: `/home/da/桌面/DodgysDD_ifvg/research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine`
  and its `README.md` (**read-only**; that tree is gitignored).
- The discussion `iFVG几个模型的讨论.txt` L111–126 (the 5-step state machine) and L42–51 (the description
  of the closed-source original and the open-source replica).

## The question
**Q3 — Is DodgysDD's trading-decision logic faithfully reproduced anywhere in this project?**

"Faithfully" means: for each rule that the *authoritative source* implements, can our system reproduce
the same decision on the same data? The authoritative sources are (a) the **closed-source** original
`iFVG Ultimate+ | DodgysDD` (described in prose only), and (b) the **open-source replica**
`cantolab/IFVG-Ultimate-Dodgy`, which its author states is a *deliberate partial* re-implementation.

## Your task → `research/audit/L2_RULES.md`

### A. Implementation status
Search the repo for any implementation of the rule engine — a state machine, a signal generator, a
`detect_fvg`, a sweep detector, an inversion check. State plainly: implemented / partially / absent,
with file+line evidence or the exact greps you ran to conclude "absent".

Note `research/experiments/e1_rule_falsification.py` **does** implement a code-derived core — audit it
properly: which rules does it implement, which does it omit, and does it match the Pine semantics
(bar indexing, `close[1]` lag, the expiry rule, the stop placement)? List every divergence you find
between it and `ifvgUltimatePlus.pine`, with line references on both sides.

### B. Rule-by-rule conformance matrix
The heart of the deliverable. One row per rule, from the union of:
- the discussion's 5-step state machine (L114–126),
- the replica's implemented rules (`research/analysis/PINE_RULES.md` §R1–R30),
- the doc's checklist conditions (L124–126).

Columns:
| # | Rule | Source (doc line / pine line) | Present in our code? | Faithful? | Gap / what is needed |

Rules to include at minimum:
1. HTF context + killzone windows (NY AM 09:30–11:30, NY PM 13:30–15:30 ET) — and note that in the
   replica these gate **alerts only**, not signals.
2. PDH/PDL, session highs/lows, unreclaimed 15m/1H FVG tracking.
3. Liquidity sweep (EQH/EQL/PDH/PDL) — required by the doc, **optional** in the replica.
4. SMT divergence vs ES/YM, +2 score.
5. 3-candle FVG geometry.
6. The `0.25 × ATR(14)` minimum gap — **absent from the replica**.
7. Inversion confirmation: body close strictly through the far edge, within the window.
8. The inversion window: `[0,15]` (code) vs `[7,15]` (doc) — and the fact that the doc's "7" is a UI
   label, not a rule.
9. `requireBEIntact` gate.
10. Stop placement (Wick / Body / IFVG) and the window extreme.
11. Break-even at the swing pivot.
12. RR projection.
13. Checklist: no opposing OB / equal-high-low in front; a clear liquidity target ≥ 2R.
14. Grade A+/A/B/C — **does it exist in any artefact?**
15. `hideLosing` post-hoc erasure — and our prohibition on it.

### C. The four unimplementable / undefined rules
For each, state what it would take to make it implementable and what it costs:
- the **grade system** (A+/A/B/C) — evidence it exists nowhere;
- the **≥2R liquidity target** (needs an EQH/EQL/PDH/PDL + "untouched session extreme" database);
- **PDH/PDL and session highs/lows** — computable from 1m bars alone?
- **opposing OB / equal-high-low obstruction** — the doc's "no uncleared opposing order block" needs OB
  detection, which the reference implementation does not have.

### D. Faithfulness verdict
- A single number: **how many of the N rules in the matrix are implemented faithfully** (and how many
  partially, how many not at all).
- The **minimum set that must be implemented** for the phase-1 gate ("pure rule engine, A/A+ only,
  PF > 1.25") to be a meaningful test — and an explicit statement of which parts of that gate remain
  unimplementable even after that minimum set is built.
- The **highest-risk fidelity gap** — the single rule whose absence would most change the results, and
  why.

### E. The reference replica's own verdict
Quote and analyse the replica README's findings (it concludes the strategy has "NO" value; it says the
grading is "mechanical"; it says the author trades without HTF/SMT confluence). State what this means for
"faithfully reproducing DodgysDD": is the faithful target the **original indicator's behaviour** or the
**author's actual trading behaviour**, and do they differ?

## Constraints
- Write **only** `research/audit/L2_RULES.md` (create `research/audit/` if needed).
- Read-only elsewhere. Do not modify the replica or the reports you cite.
- Use `[FACT]` / `[INFERENCE]` / `[PROPOSAL]`. Cite file+line for everything.
- Do not implement code. Specify it.

## Deliverable
`research/audit/L2_RULES.md`. Final reply: the conformance count (faithful / partial / absent out of N),
the minimum implementable set, and the highest-risk fidelity gap.
