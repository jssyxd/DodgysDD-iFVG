# Job: Reverse-engineer the reference iFVG Pine Script into an exact rule table

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. The design discussion (`iFVG几个模型的讨论.txt`) says the
authoritative implementation of the DodgysDD iFVG strategy is the **closed-source** TradingView indicator
"iFVG Ultimate+ | DodgysDD" (by TakingProphets, invite-only). The open-source reverse-engineered replica is
`cantolab/IFVG-Ultimate-Dodgy`, already cloned at `research/github/IFVG-Ultimate-Dodgy/` by a sibling worker
(read its `research/github/CLONE_REPORT.md` if present).

This replica is the **only executable statement of the real rules we have**. Our own NautilusTrader
implementation must match it, and the design doc's prose is a lossy summary of it. Your job is to extract the
rules *from the code*, not from the prose.

A sibling worker is producing `research/docs/RULE_SPEC.md` from the prose alone. You are the counterpart that
grounds the spec in code. Where the two disagree, the code wins (and the disagreement must be reported).

## Your task
Produce `research/analysis/PINE_RULES.md`.

### A. Full input-parameter inventory
Every `input.*` declaration in the Pine Script, verbatim, with its default, min/max, and a one-line meaning.
Group them: (a) structural/FVG params, (b) sweep/liquidity params, (c) inversion-timing params,
(d) scoring/grade params, (e) HTF/killzone/session params, (f) RR/exit/BE params, (g) visual or display params.

### B. Rule table (the core deliverable)
For each rule the script implements, give:
- the rule name
- the exact Pine code (quoted)
- a precise English restatement
- the concrete numeric values in play
- whether it is a **hard gate** (blocks the signal) or a **score contribution** (feeds the A+..C grade)

Cover at minimum:
1. FVG detection — the exact 3-candle geometry for bullish/bearish, the ATR lookback and the minimum-gap
   coefficient, and whether the gap is measured on wicks or bodies
2. Liquidity sweep detection — what exactly is swept (EQH/EQL/PDH/PDL?), the tolerance/proximity rule, the
   requirement that a wick pierces and the body does not (or whatever the code actually does)
3. The inversion confirmation — the bar-count window (the doc says 7–15; read the code for the real bounds),
   what "body close penetrates" means precisely (which edge, `>` or `>=`), and whether the confirmation bar
   may be the same bar as the sweep
4. SMT divergence — the reference instrument(s), how the comparison is made, and how it feeds the score
5. The scoring system — the **exact point values** for every component and the **exact score cutoffs** that
   map to A+, A, B, C (or whatever the labels are). The doc says "A+ 至 C 级" but gives no numbers; extract
   them from the code.
6. HTF filter and killzone/session windows — the exact times, the timezone handling, and which HTF
   timeframes are used
7. RR target projection, break-even tracking, and any "hide losing setups" behaviour (the doc warns the
   original erases losers — confirm whether this replica has that switch and what it hides)
8. Any filter or feature the doc does NOT mention at all (these are the highest-value findings — the doc's
   summary may have dropped real logic)

### C. Gap analysis vs the design doc
A table: every rule in the script → present/absent in `iFVG几个模型的讨论.txt` → the doc's stated value vs the
code's actual value. Flag every **material** divergence (>10% on a threshold, or a rule present in code but
absent from the doc).

### D. Porting notes
For the 6 highest-risk rules to port into a Python/NautilusTrader event-driven engine, note the Pine-specific
constructs that need rework: `ta.` series functions and their non-repainting equivalents, `request.security()`
lookahead pitfalls, bar-state vs close-state semantics, array/object lifetime, `strategy.*` calls vs real
orders, and Pine's tick/pip size model.

## Constraints
- Write ONLY `research/analysis/PINE_RULES.md`.
- Do NOT modify the cloned repo. Do NOT run TradingView or any Pine interpreter.
- Quote code verbatim; do not paraphrase the algorithm — the port depends on exactness.
- If the repo contains multiple .pine files or versions, analyse all of them and say which is the most
  complete/latest.
- If the script uses `//@version=6` and any v6-only syntax, note it — our port targets Python, but the
  semantics matter.

## Surprises
Deliverable: `research/analysis/PINE_RULES.md`. In your final message list the 5 rules you consider most
critical to port correctly and any rule that contradicts the design doc. The captain transcribes lasting
surprises into `.field-guide/`.
