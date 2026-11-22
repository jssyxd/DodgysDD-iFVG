# DodgysDD iFVG — Audit Report and Build Status

**Date:** 2026-11-23 · **Repo:** `jssyxd/DodgysDD-iFVG` (private) · **Lake:** NFS `fnos2.local/fs/1000/nfs/iflow/database`
**Method:** 5 read-only audit leaves → 2 implementation leaves (isolated worktrees) → 1 adversarial
review by a different model → captain integration and verification.

Every number below was **executed on this host**, not quoted from a report.

---

## 1. The five questions, answered

### Q1 — Is the "visual iFVG detection + parameter-feature double validation" implemented?

**No — nothing was implemented.** `dodgys_dd_quant/` did not exist; the only Python was
`research/experiments/e1_rule_falsification.py`. There was no renderer, no detector wrapper, no IoU,
no clarity score, no gate. (`research/audit/L1_VISION.md`)

**Worse, the design cannot work as written.** The detector's annotations wrap the **third candle's
body**, which is **disjoint** from the FVG *gap* (for a bullish FVG `gap = [high_{i-2}, low_i]`, the
third candle's body sits at or above `gap_high`). So under the discussion's metric a **perfect**
detection scores **IoU = 0.00**. Measured on the model's own labels: median **0.0000**, **87.9 %
exactly zero**, **0.65 % above 0.75**. The `IoU > 0.75` gate is unreachable **by construction**.

### Q2 — Are the two sides (vision and rule features) aligned?

**No.** The rule engine measures the *price gap*; the detector measures the *candle body*. They are
different objects, so a disagreement is an artefact, not evidence.

Corrected contract: a **2-D box IoU against the third candle's body rectangle** (perfect match = 1.0),
with the detector's own box as the reference; threshold ≈ 0.5 calibrated on the Kaggle test split, not
0.75 inherited. The model also needs a **white 640×640** render (its card: *"Trained on white
background TradingView charts only"*), not the discussion's black 224×224 — where the median FVG box
is **1.9 × 5.8 px**.

### Q3 — Is DodgysDD's decision logic faithfully reproduced?

**No: 8 of 30 rules faithful, 3 partial, 19 absent** (`research/audit/L2_RULES.md`).

The reference implementation contains **no ATR filter, no SMT divergence, no A+/A/B/C grading and no
checklist**. The discussion's `0.25 × ATR(14)` gap floor, the SMT leg and the grade system have **no
code basis** in any artefact we have. Two further corrections:

- The inversion window is **[1, 15]**, not `[7, 15]` and not `[0, 15]`: age 0 is arithmetically
  impossible (`low[c] > high[c-2]` versus the age-0 trigger `close[c] < high[c-2]`, with
  `close[c] >= low[c]`). Verified empirically — the trigger-age histogram over 423,770 candidates
  starts at **age 1**, with **zero** at age 0.
- The published `//@version=6` replica would detect **no candidates at all**: it uses
  `ta.lowestbars(3) == -1`, and in **v5/v6 `ta.lowestbars` returns the in-window offset (0..n-1)**, never
  −1 — that is v4 semantics. The replica is not a numerically reproducible reference on v6.
- "Faithful to the doc" and "faithful to the Pine" are **different rules**: the doc makes the killzone
  a signal gate; the Pine makes it an **alert** filter defaulting to `0930-1600`.

**And the reference replica's own author concludes the strategy has "NO" value** — while documenting
that the original indicator *erases losers after the fact*.

### Q4 — Are VXN / VIX correlated, and do they reach the decision?

**No — nothing was implemented, on any of the five paths** (`research/audit/L3_REGIME.md`):

```
CORRELATION CHECK IMPLEMENTED:  no
REGIME IN STRATEGY:             no
REGIME IN ORDER DECISION:       no
REGIME IN ML FEATURES:          no
REGIME IN RL STATE:             no
```

VXN **is** now ingested and governed (CBOE official, 4,327 daily bars, 2009→2026), and the regime
layer is wired into the engine with a **strict one-day lag** (a bar on day D may only see day D−1's
close — the D-series close is published after the cash close). But **no correlation test has been run**,
and no regime-conditioned result exists.

**VIX is not ingested.** The regime index is pluggable so MES (VIX) and GC (GVZ) can be added when
sourced; today only VXN (NQT/QQQ), DVOL (crypto) and CMC20 (crypto cross-sectional) exist.

### Q5 — Is the data sufficient, and how should rolling ML / RL / e2e / dynamic backtesting work?

**Data** (`research/audit/L4_ROLLING.md`, `DATA_ACQUISITION.md`):

| | |
|---|---|
| **Sufficient for phase 1 on NQ?** | **No.** The lake holds NQ/ES **1-minute only for one week** (7,490 / 7,489 rows). The missing thing is not "1-minute NQ" but **multi-year 1-minute NQ **per contract** with a documented roll rule** — a roll gap prints like a liquidity sweep. |
| **Free mirrors for CME 1m?** | **None.** Every free mirror was scanned: Twelve Data's lake source is an **equities** dataset (129 stock/ETF tickers, zero futures, in all three splits), Yahoo serves ~1–2 days of 1-minute, cryptohftdata has no candle family, OKX needs ~14,000 requests per symbol. **Databento (~$10–30) is the only route** — exactly what the design doc already recommends. |
| **Sufficient on crypto?** | **Conditional.** BTCUSDT/ETHUSDT have **2,046,240 gap-free 1-minute bars** (2023-01-01 → 2026-11-21) and support the 6/1/1 walk-forward arithmetically (40 folds). |
| **Top missing items** | ① multi-year NQ+ES 1m per contract + roll rule (**Databento, ~$100–300**); ② the roll-rule detector; ③ intraday VXN/VIX; ④ order-book imbalance for NQ. |

**Rolling ML / RL / e2e / dynamic backtesting** — all now implemented and executed:

- **Rolling ML**: 6/1/1 monthly purged walk-forward, embargo = the label horizon, per-fold
  LightGBM, D3 artefacts.
- **Rolling RL**: not built — and **it should not be**. The RL manages an edge that does not exist;
  it also has no order-book-imbalance state for NQ.
- **E2E**: `dodgys_dd_quant.backtest.runner` — rule engine → D2 log → features → per-fold model →
  gated portfolio → costs → DSR.
- **Dynamic backtesting**: the walk-forward *is* the dynamic backtest; its dynamic signal is the
  per-fold prediction distribution vs the training base rate.

---

## 2. The result that decides the project

**On 2,046,240 real BTCUSDT 1-minute bars, 366,500 candidates, 39 walk-forward folds:**

| | n trades | E[R] gross | E[R] net | PF | t | 95 % CI |
|---|---|---|---|---|---|---|
| **Rule only** (one position at a time) | 21,539 | **−0.0002** | −0.4986 | 1.000 | −0.02 | [−0.019, +0.019] |
| **ML-gated** (`P(Win) ≥ 0.58`) | 652 | **+0.0675** | −0.5245 | 1.105 | 1.20 | [−0.043, +0.178] |

- The 1:2 **break-even win rate is exactly 33.3 %**; the measured win rate is **33.3 %**. The rule
  engine is a **coin flip**, not a near-miss.
- **`auc_test` is 0.483–0.521 across all 39 folds** — the meta-labeler has **no predictive power**.
- The 0.58 gate passes **0 candidates in most folds** (the base rate is 0.34), so it discards 97 % of
  the signals and still leaves a CI that includes zero.
- **The cost is 0.50–0.83 R per trade** — the FVG stop is so tight that Binance's 8 bp round trip is
  most of the risk unit. The break-even cost is **0.009 R**: the edge is ~80× too small.
- **DSR p = 0.82–0.98** over 32 tried arms.

**The ML layer cannot rescue a zero-edge signal.** L1 showed the arithmetic before it was run: to
reach PF 1.25 while keeping 80 % of trades, a gate must remove a sub-population winning **9.7 %**
against a 32.7 % base — and the detector's labels contain **zero outcome information**, so an
outcome-uncorrelated filter leaves the expectancy unchanged while shrinking the sample (`t` scales as
`1/√q`).

**A methodological trap worth naming.** The first version of this test counted 423,770
*simultaneously-open, correlated* positions as independent bets and produced **t = 15.28** with a CI
excluding zero. That result is an artefact. A backtest must hold at most **one** position at a time, and
significance must be quoted from that arm. The R1 review independently reproduced the corrected
number (n = 15,928 vs 15,929; E[R] = −0.0197; t = −1.76).

---

## 3. What was built

```
dodgys_dd_quant/
  strategy/{constants,structure,state_machine,regime}.py    # the rule engine, causal, D2 log
  ml_pipeline/{features,labels,splits,train_meta_labeler,kaggle_export}.py
  backtest/{cost_model,walk_forward,runner}.py               # E2E walk-forward + DSR
tests/unit/                                                   # 79 pass, 2 skipped (need LightGBM)
```

- **Rule engine**: pure function of bar history; causal swings; one-shot sweep levels; ATR floor;
  inversion window configurable `[1,15]`/`[7,15]`; BE-intact gate; checklist as five booleans
  **reported, never filtered on**; VXN regime with a one-day lag; D2 candidate log written verbatim.
- **ML pipeline**: binary meta-labels; purged walk-forward with an embargo tied to the label horizon;
  LightGBM; D3 artefacts; a Kaggle kernel generator that never sees the test fold.
- **Backtest**: costs isolated in the config (D9); one-position-at-a-time; per-fold model; the
  forward-only guard **raises** on a malformed fold; the rule-only baseline is an **independent**
  population; per-fold and deflated-Sharpe statistics.
- **Governance**: a `pre-commit` **and** a `pre-push` credential guard; the `repo`-scoped token
  forced a REST-API push path (`scripts/sync_via_api.sh`), because `git push`'s POST and any
  `.github/workflows/` entry are both refused without the `workflow` scope.

**R1's verdict was CONDITIONAL FAIL** with 12 findings. F1 (vacuous forward-only guard), F2 (the D3
producer and consumer could not interoperate — the ML path had *never* run inside the backtest),
F3 (the model path could not predict), F4 (the "rule-only baseline" was the gated portfolio), F5
(`minutes_from_us_open` was minutes since midnight) and F9 (`~` never expanded, so the authoritative
NFS lake was unused) are **closed**. F6/F7/F8/F10/F11/F12 remain open and are itemised in
`research/audit/R1_REVIEW.md`.

---

## 4. Can Kaggle be used for training and rolling training?

**Yes for the vision layer; no for the meta-labeler.** Measured (`research/audit/L5_ENV.md`, and the
quota re-verified independently):

| Capability | Verdict | Measured |
|---|---|---|
| Kaggle **GPU** | ✅ available | `kaggle quota` → GPU **30.00 h** total, **0.00 h** used, refreshes 2026-11-28 |
| Kaggle **CPU kernel** | ✅ | account `opclown1`, ≥100 private kernels, `COMPLETE` |
| Kaggle **Datasets** upload | ⚠️ slow | **15.7 KB/s** effective; the 58 MB unit of transfer takes ≈ 1 h; whole-lake push ≈ 18 h/GB |
| Kaggle **download** | ✅ | 120–155 KB/s |
| Local **LightGBM** | ✅ | **1.24 s/fold**; the whole 39-fold walk-forward = **55.6 s** end-to-end |
| Local **GPU** | ❌ | no `nvidia-smi`; AMD iGPU only; 14 GiB RAM, 12 GiB used |

**Conclusion:** train the meta-labeler **locally** (55.6 s for the entire rolling year — Kaggle is
pointless for that). Spend Kaggle's 30 GPU-hours only on the **vision detector**, whose CPU-only
inference over the candidate population is **29–145 h**. Push to Kaggle Datasets only the **D2 candidate
log + feature table per symbol** (5–10 MB, ≈ 11 min), never the lake — the NFS lake is already local.

---

## 5. What to do next, in order

1. **Do not start phase 2.** The gate is "pure rule, PF > 1.25". Measured PF is **≤ 1.051** and the
   edge is ~80× smaller than the round-trip cost. Either the rule reproduction is wrong, or the edge
   is not there.
2. **Decide the target instrument.** The E2E works; it runs on BTCUSDT. If the target stays NQ, buy
   **Databento** multi-year 1-minute NQ+ES (per contract, with the roll rule) — that is the only
   remaining blocker and it is a purchase, not an engineering task.
3. **Define A/A+** so the phase-1 population is computable, or state explicitly that phase 1 runs on
   *all* candidates and that the grade is reported, not filtered.
4. **Only then** re-run the same test with one position at a time and real costs. If PF > 1.25 there,
   the vision layer becomes worth building as an offline batch feature (not as a gate), the meta-labeler
   becomes worth training, and the RL becomes worth building last.

**The honest summary: the rules are specified, the engine is implemented and verified, the data
question is answered, and the edge is not demonstrated.** The upstream author's own reverse-engineering
of the closed-source indicator reached the same conclusion — and he had the advantage of the original's
source.

---

## 6. Where to look

| Question | File |
|---|---|
| What the strategy is, rule by rule | `research/docs/RULE_SPEC.md` |
| The reference implementation, rule by rule | `research/analysis/PINE_RULES.md` |
| Why the vision gate cannot work | `research/analysis/VISION_AUDIT.md` |
| Rule fidelity matrix | `research/audit/L2_RULES.md` |
| Regime: what exists, what to test | `research/audit/L3_REGIME.md` |
| Data sufficiency + rolling design | `research/audit/L4_ROLLING.md` |
| Environment, Kaggle, rolling plan | `research/audit/L5_ENV.md` |
| Adversarial review of the built code | `research/audit/R1_REVIEW.md` |
| Lake inspection, acquisition, governance | `research/analysis/DATA_ACQUISITION.md` |
| The falsification test and its result | `research/experiments/E1_RESULTS.md` |
| The executed end-to-end walk-forward | `research/experiments/E2E_MODEL_WALKFORWARD.txt` |
| Captain's frozen contracts and decisions | `.herd-swarm/decisions.md` |
| Environment surprises | `.field-guide/` |
