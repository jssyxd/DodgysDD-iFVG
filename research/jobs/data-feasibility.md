# Job: Determine what market data is actually available and whether the phase-1 gate is reachable

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. The plan is a NautilusTrader backtest of the DodgysDD iFVG
strategy on **NQ** (with **ES** as the SMT reference instrument) at **1-minute** granularity, then a
meta-labeling filter, then RL position management.

The **phase-1 acceptance gate is strict and non-negotiable**: the *pure rule engine alone*, with fixed 1:2
RR, A/A+ setups only, under ~$4.5 round-turn fees and 1–2 ticks of slippage, must show
**Profit Factor > 1.25**. The design doc is explicit that a negative pure-rule result means the rule
reproduction is wrong and must never be masked by ML.

Data available / referenced:
- `research/kaggle/nq-fvg-dataset/` — FVG-labelled NQ candles (see `research/kaggle/DATASET_REPORT.md`)
- `research/kaggle/gold-xauusd-smc-trading-data/` — XAU/USD OHLC + FVG/OB boolean labels
- `research/kaggle/fvgnet-manifest.txt` — manifest only for a ~45 GB dataset
- The user's data lake: `smb://192.168.1.6/iflow/database`, governed by `github.com/jssyxd/dataBaseLake`
  (cloned at `research/github/dataBaseLake/`). New downloads must pass that repo's audit/governance standard
  and be marked 可用 / 可入湖 before use.
- Supplemental sources named by the user: Binance and OKX official history, cryptohftdata.com

Your job is to answer the question that decides whether phase 1 is even possible: **do we have, or can we
obtain, the data required to run a faithful 1-minute NQ+ES event-driven backtest with realistic costs?**

## Your task
Produce `research/analysis/DATA_FEASIBILITY.md`.

### A. Requirement checklist
Derive from the design doc exactly what the backtest needs, and check each item against what we actually have:
- NQ 1-minute OHLCV, multi-year, with **session boundaries** (Asia/London/NY) and correct timezone handling
- ES 1-minute OHLCV for SMT comparison, **time-aligned** to NQ (same exchange calendar, same timestamps)
- Continuous-contract or properly rolled contract data — and how roll gaps are handled (a roll gap can fake a
  liquidity sweep! this must be handled explicitly)
- **Tick size 0.25** and the real fee model ($4.5/round-trip) — where do these come from, and are they right
  for the contract and the broker
- Realistic **slippage of 1–2 ticks** and how to configure it in NautilusTrader
- Enough history to satisfy a 6-month train / 1-month validate / 1-month test walk-forward, and to hold out
  a genuine out-of-sample period
- VXN (or an equivalent regime series) — and note the daily-vs-intraday problem in the design doc

Mark each: **AVAILABLE** / **PARTIAL** / **MISSING**, with the evidence path.

### B. What the data lake actually holds
Inspect `smb://192.168.1.6/iflow/database` (mount path, or `smbclient`/`mount` if already mounted — check
`/mnt`, `/media`, and `mount | grep cifs`) and report what is there for NQ/ES/crypto. If the share is not
reachable from this machine, say so plainly and describe exactly what commands the captain must run elsewhere
to inventory it — do not fabricate an inventory.
Read `research/github/dataBaseLake/` and state the governance rules that any new data must satisfy
(quoting the actual README/manifest/schema), plus the 可用 / 可入湖 marking convention.

### C. The two Kaggle datasets — sufficiency verdict
For each: can it drive the phase-1 backtest? Specifically: what resolution, what symbol, what date range,
is there an ES counterpart, are there session markers, are the FVG labels usable as ground truth for
validating our FVG detector, and are the timestamps continuous across session breaks and weekends?
State plainly if a dataset is a **labelled toy** that cannot support a profitability claim.

### D. A concrete data acquisition plan
A prioritised, costed plan to obtain a sufficient dataset, given the constraints (no Databento subscription
assumed; the user's own lake and the crypto sources are the primary channels). For each option: source, what
it gives, cost (free / paid, roughly), the effort, the governance steps to pass it into the lake, and the
risk it fails. End with a recommendation for the cheapest path that can actually satisfy phase 1, and state
the **earliest date** phase 1 could realistically start.

### E. Leakage & integrity checklist
The specific data-integrity traps for this strategy, each with the check that catches it:
- roll gaps faking a sweep; contract splicing
- a "sweep" that is just a session boundary or a data gap
- DST transitions inside the killzone windows (NY AM 09:30–11:30 ET — what happens on the DST switch days?)
- missing bars silently forward-filled (the doc uses `.bfill()` on VXN — where else could bfill leak?)
- VXN regime computed from a value that was not knowable at the trade time
- survivorship/selection in "which FVG labels did the dataset author keep?"

## Constraints
- Write ONLY `research/analysis/DATA_FEASIBILITY.md`.
- Do NOT download large datasets. Do NOT pip install. Do NOT modify the data lake.
- Network reads of metadata (HTTP HEAD, API listing, `kaggle datasets files`) are fine; bulk downloads are not.
- Never state a fact you did not verify. Where something is unverifiable from here, write
  "UNVERIFIED — needs <specific command or access>".

## Surprises
Deliverable: `research/analysis/DATA_FEASIBILITY.md`. Final message: the phase-1 go/no-go answer in one line,
plus the single biggest data gap. Captain transcribes into `.field-guide/`.
