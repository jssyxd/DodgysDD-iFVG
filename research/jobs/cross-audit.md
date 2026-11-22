# Job: Cross-audit the four analysis reports against their source evidence

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. Four analysis reports were produced by sibling workers in
`research/analysis/`. You are the **auditor**. Your job is NOT to add new findings — it is to **verify**
these claims against the underlying artifacts and to find errors, overstatements and gaps.

| Report | Produced from | Covers |
|---|---|---|
| `research/docs/RULE_SPEC.md` | `iFVG几个模型的讨论.txt` (the prose) | the doc's rules, threshold provenance, ambiguity register |
| `research/analysis/PINE_RULES.md` | `research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine` | the reference implementation, rule table, divergence analysis |
| `research/analysis/VISION_AUDIT.md` | `research/huggingface/nq-fvg-detector/` + `research/kaggle/nq-fvg-dataset/` | the vision cross-validation layer |
| `research/analysis/ML_REUSE.md` | `research/huggingface/xauusd-ml-trader/`, `research/github/AlphaGPT/`, `research/github/qlib/`, `research/huggingface/ict-6000-mentorship-master/` | external reuse decisions |
| `research/analysis/DATA_FEASIBILITY.md` | `research/kaggle/*`, `research/github/dataBaseLake/` | whether phase 1 is reachable |
| `research/nautilus/NAUTILUS_API.md` | the installed `nautilus_trader` 1.221.0 package | the engine API |

## Your task
Produce `research/audit/AUDIT.md`.

### A. Claim verification
Take the **load-bearing claims** from each report and verify each against its cited source. Prioritise
claims that, if wrong, would change the build:

1. From `PINE_RULES.md`: the FVG geometry line, the inversion trigger predicate, the `graceCandles` value
   and the **[0,15] vs [7,15]** window conclusion, the "no ATR / no SMT / no scoring / no checklist"
   absence claims, the `hideLosing` erasure block, the session-gates-alerts-only claim.
2. From `RULE_SPEC.md`: the [DOC]/[DERIVED]/[UNSPECIFIED] tagging of the key thresholds — spot-check 8
   of them against the actual line numbers in `iFVG几个模型的讨论.txt`, and confirm the cited lines say
   what the spec claims they say.
3. From `VISION_AUDIT.md`: the IoU definition and what a perfect match scores; the resolution arithmetic;
   the claim that the model needs a white 640×640 render.
4. From `ML_REUSE.md`: the two look-ahead defects claimed in `xauusd-ml-trader`; the 3-class-label claim;
   the Qlib "no futures / long-only / no shorts" claims; the ICT corpus's "SMT Absent still yields VALID".
5. From `DATA_FEASIBILITY.md`: the claim that the databank MANIFEST shows NQ/ES **daily only** while the
   parquet manifest advertises 1m; the Kaggle dataset characterisations (295 JPGs / 4502 rows).
6. From `NAUTILUS_API.md`: re-run the 7 smoke-test commands and confirm each still produces the recorded
   output.

For each claim report: **VERIFIED** (you reproduced it), **WRONG** (you refuted it — give the evidence),
or **UNSUPPORTED** (the report asserts it but the cited source does not establish it).

### B. Cross-report consistency
The six reports were written independently and may contradict each other. Find every contradiction:
- the inversion window (PINE says [0,15]; RULE_SPEC may say 7–15 as [DOC])
- the FVG gap filter (PINE: absent; RULE_SPEC: `> 0.25*ATR(14)` as [DOC])
- the sweep filter (mandatory vs optional)
- the session/killzone windows (doc's 09:30–11:30 / 13:30–15:30 vs the code's 0930-1600 alert session)
- the "A/A+ only" phase-1 filter — does any artifact define what A or A+ means? If not, say so loudly:
  **the phase-1 gate may be unimplementable as written.**
- the vision input size (224 vs 640) and background (black vs white)
- the IoU threshold (0.75) — is it reachable under the chosen definition?

Produce a contradiction table: topic → report A claim → report B claim → which one the source supports →
the single reconciled statement the project must adopt.

### C. Gaps the reports missed
What is still unknown that blocks the build? Check specifically:
- the grade system (A+/A/B/C) — does it exist in ANY artifact, or is it only in the doc's prose? If it
  exists nowhere, the phase-1 gate "A/A+ setups only" has no implementable definition. Propose a
  concrete, defensible substitute and state its consequences.
- the "≥2R liquidity target" rule — is it computable from the artifacts, or is it unimplementable without
  the equity-pool database the original indicator never had?
- the VXN regime series: daily vs intraday, and the "1-hour change rate" feature.
- the contract roll rule for NQ/ES continuous futures.
- what the design doc calls "PDH/PDL" and "EQH/EQL" — are they computable from 1m bars alone?

### D. Verdict
End with a short, blunt verdict:
1. Is the four-layer design, as written, implementable with the evidence we have? (yes/no/partially)
2. What is the single highest-risk assumption still unverified?
3. What is the **minimum credible phase-1 experiment** that would settle whether this strategy has a
   positive EV — stated as a concrete, small, falsifiable test (inputs, sample size, metric, pass/fail),
   using only the artifacts that actually exist here.

## Constraints
- Write ONLY `research/audit/AUDIT.md`.
- Do NOT rewrite the other reports. Do NOT fix the artifacts. You verify and you report.
- Cite the exact file path and line number for every verification you perform.
- Be adversarial toward the reports — they were written by sibling agents that may have over-claimed.
  A report that turns out to be wrong is a finding, not a failure of the audit.
- Read `.field-guide/env.md` and `.field-guide/sources.md` first: they already record many verified facts,
  and you should not re-derive them. But DO check whether each field-guide claim is itself accurate.

## Surprises
Deliverable: `research/audit/AUDIT.md`. Final message: the three findings that most change the plan, and
the minimum credible phase-1 experiment in three lines. The captain transcribes lasting surprises into
`.field-guide/`.
