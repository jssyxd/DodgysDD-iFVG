# Swarm Decision Record

The captain appends one dated entry per decision. Workers **read** this file; workers never write to it.
If a worker needs a decision that is not here, it states the question in its deliverable and stops
short of guessing.

---

## D1 — 2026-11-22 — The four-layer system is **not implemented**; it is only researched

**Decision.** Treat `research/` as *evidence*, and `dodgys_dd_quant/` as *the thing to build*.
Every answer to the user's questions 1–4 is therefore "not implemented", and the audit's job is to
specify exactly what must exist, with file paths and contracts.

**Why.** The repo contains: the design discussion, six analysis/audit reports, a verified NautilusTrader
1.221.0 API map, a governed data lake with real 1-minute crypto data, and one experiment script
(`research/experiments/e1_rule_falsification.py`). There is no `dodgys_dd_quant/` package, no vision
module, no meta-labeling pipeline, no RL agent.

**Consequence.** Wave 1 is read-only audit + specification. Wave 2 builds the two highest-leverage
modules (rolling ML, and the E2E rolling backtest that consumes them).

---

## D2 — 2026-11-22 — Frozen contract: the candidate log

Both implementation leaves must agree on this table. It is the single seam between the rule engine and
the ML pipeline. **Both leaves write code against this spec; neither may change it.**

File: `research/candidates/{symbol}_{timeframe}.parquet` (Parquet, zstd-7)

| Column | Type | Meaning | Source |
|---|---|---|---|
| `ts_event` | int64 ns | event time of the **confirmation** bar close | rule engine |
| `symbol` | str | e.g. `BTCUSDT` | rule engine |
| `side` | int8 | +1 long, −1 short | rule engine |
| `entry_price` | f64 | fill price | rule engine |
| `stop_price` | f64 | stop | rule engine |
| `target_price` | f64 | target | rule engine |
| `risk` | f64 | `abs(entry − stop)`, the R unit | rule engine |
| `fvg_low` | f64 | gap lower edge | rule engine |
| `fvg_high` | f64 | gap upper edge | rule engine |
| `fvg_bar1` | int64 | index of the FVG's **oldest** candle | rule engine |
| `fvg_bar3` | int64 | index of the FVG's **newest** candle | rule engine |
| `confirm_bar` | int64 | index of the inversion-confirmation candle | rule engine |
| `bars_to_inversion` | int32 | `confirm_bar − fvg_bar3` | derived |
| `minutes_from_us_open` | int32 | minutes since 09:30 ET on that day | derived |
| `checklist_score` | f64 | the doc's five named checks as a score | rule engine |
| `smt_divergence` | int8 | 1 yes, 0 no, −1 unknown (no reference instrument) | rule engine |
| `sweep_detected` | int8 | 1 yes, 0 no | rule engine |
| `vxn_known` | f64 | **lagged** VXN (previous close) | regime module |
| `vxn_regime` | int8 | 0 low / 1 normal / 2 high | regime module |
| `vision_iou` | f64 | vision↔rule agreement, NaN if not computed | vision module |
| `vision_confidence` | f64 | detector confidence, NaN if not computed | vision module |
| `label` | int8 | 1 = hit target, 0 = hit stop, −1 = still open / unlabelled | outcome join |
| `r_multiple` | f64 | realised R (NaN while open) | outcome join |

**Invariant:** every row is a **candidate**, including losers. Nothing is filtered out of this log
("Hide Losing Setups" is banned).

---

## D3 — 2026-11-22 — Frozen contract: the model artefact

Written by the ML leaf, read by the backtest leaf. Both code against this exactly.

Directory: `artifacts/models/{symbol}/{asof_YYYYMMDD}/`

- `meta_label_lgbm.txt` — LightGBM native text format.
- `meta_label_meta.json`:
  ```json
  {
    "symbol": "BTCUSDT", "timeframe": "1m",
    "asof": "2026-01-31",
    "train_start": "2025-08-01", "train_end": "2025-12-31",
    "valid_start": "2025-12-01", "valid_end": "2025-12-31",
    "test_start": "2026-01-01", "test_end": "2026-01-31",
    "embargo_minutes": 60,
    "feature_list": ["...", "..."],
    "decision_threshold": 0.58,
    "n_train": 0, "n_valid": 0, "n_test": 0,
    "positives_train": 0, "positives_test": 0,
    "auc_test": null, "accuracy_test": null
  }
  ```
- `walk_forward_index.json` — the ordered list of fold directories, so a live/paper run knows which model
  was in force on which date.

**Forward-only rule:** a model trained with `asof = T` may only be used to decide trades with
`ts_event > T`. The backtest leaf must assert this.

---

## D4 — 2026-11-22 — The honest baseline: the rule engine currently shows **no edge**

**Decision.** Any ML/RL deliverable must be reported **against** this baseline, and must not be
presented as an improvement unless it beats it on the same data, the same costs, and the same
one-position-at-a-time accounting.

**Why.** `research/experiments/E1_RESULTS.md` (rev. 2) measures, on 2,046,240 real BTCUSDT 1-minute
bars (2023-01-01 → 2026-11-21), with **one position at a time**:
- expectancy across 32 arms: **−0.024 R … +0.014 R**; every 95 % CI includes zero;
- **PF never exceeds 1.051** against the design doc's **> 1.25** gate;
- with a 0.05 R round trip every arm is negative;
- the sign flips across the fill arm in every parameter group.

**Trap that must not be repeated:** the "census" arm (one position per candidate, 423,759 overlapping
positions) shows t = 15.28 and a CI excluding zero. That is an artefact of correlated trades and is
**not** a result. The t-statistic must always be quoted from the one-position-at-a-time arm.

---

## D5 — 2026-11-22 — Data reality that constrains every leaf

Measured, not assumed (see `research/analysis/DATA_ACQUISITION.md`):

| Asset | 1-minute | Multi-year lane |
|---|---|---|
| BTCUSDT | **2,046,240 bars, 2023-01-01 → 2026-11-21, 0 gaps** | 15m from 2024-01; `bar_ofi` 1m from 2023-01 |
| ETHUSDT | **2,046,240 bars, 2023-01-01 → 2026-11-21, 0 gaps** | 15m from 2020-01 |
| NQ / ES / GC | **7,490 / 7,489 / 7,714 bars, one week only** | 1h from 2024-05; 1d from 2021-10 |
| QQQ | 2,428 bars (1 week) | **15m from 2022-10** (73,325 bars) |
| VXN (CBOE) | 4,327 daily bars, 2009-09-14 → 2026-11-20 | — |
| Funding (BTC/ETH) | 4,200 prints each, 2023-01 → 2026-10 | — |

Canonical location is the **NFS** lake: `nfs://fnos2.local/fs/1000/nfs/iflow/database`
(mount: `sudo mount -t nfs -o rw,vers=3,proto=tcp fnos2.local:/fs/1000/nfs ~/iflow_lake`).
The local checkout `/home/da/桌面/database/` is a working copy; the NFS mount is authoritative.

**VIX is NOT ingested.** The migration table assigns VIX to MES and VXN to NQ/QQQ. VXN is what exists.

---

## D6 — 2026-11-22 — The vision layer's gate must be re-specified, not inherited

**Decision.** Any vision work targets a **2-D box IoU against the third candle's body**, not the doc's
1-D vertical interval IoU against the price gap.

**Why.** The detector's annotations wrap the **candle body**, which is **disjoint** from the FVG *gap*
(for a bullish FVG `gap = [high_{i-2}, low_i]`, the third candle's body sits at or above `gap_high`).
Under the doc's literal metric a **perfect** detection scores **IoU = 0.00**; measured on the model's own
labels: median 0.0000, 87.9 % exactly zero, 0.65 % above 0.75. The gate is unreachable by construction.
The model also needs a **white 640×640** render (its card says "Trained on white background TradingView
charts only"), not the doc's black 224×224, where the median FVG box is 1.9 × 5.8 px.

**Consequence.** `VISION_IOU_THRESHOLD = 0.75` must be **deleted**, replaced by a calibrated
body-IoU threshold (start ≈ 0.5) — and the layer's honest claim narrows to *"the vision model
independently localises the same bar"*, not "verifies clean price action".

---

## D7 — 2026-11-22 — Which external components may be reused

**Decision.** Reuse verdicts are fixed (from `research/analysis/ML_REUSE.md`) and may not be re-litigated:

| Artefact | Verdict |
|---|---|
| `xauusd-ml-trader` | **ADAPT** — port `detect_liquidity_sweeps`, `detect_fvg`, `add_atr`, session labels, risk sizing, **with the look-ahead fixed** (its swing detector uses a centred window; order blocks are registered before their displacement). Do **not** reuse its ML layer (3-class directional label). |
| `AlphaGPT` | **BORROW-IDEAS-ONLY** — not a port target. It has no IC/RankIC at all; its fitness is a dense cross-sectional P&L over a hard-wired crypto feature set. |
| `AlphaGPT-By-imbue-bit` | **DISCARD** — stale by ~5 months and materially different. |
| `qlib` | **BORROW-IDEAS-ONLY** — take the *concept* (expanding monthly folds, tail truncation/purge, concatenated OOS predictions) and reimplement; do not adopt (no futures, long-only, YAML+mlflow/redis/mongo). |
| `ict-6000-mentorship-master` | **ADAPT as a test-vector corpus only** (`tests/fixtures/ict_audit_cases.json`); its gates 2–3 are *asserted*, not derived, and SMT is optional there. |

---

## D8 — 2026-11-22 — "A/A+" is unimplementable as written

**Decision.** No leaf may filter on a grade that no artefact defines. The substitute is fixed:
implement the doc's **five named checklist conditions as booleans**, expose their sum as
`checklist_score`, **report** the distribution of scores, and **do not filter** on it by default.
The phase-1 population must be stated explicitly in every backtest report.

---

## D9 — 2026-11-22 — Cost model

**Decision.** Costs live in the backtest config, never in strategy logic, and are always reported at
**0 / 1 / 2 ticks** with the **full** round-trip fee.

- NQ: tick 0.25 pt = **$5.00**, multiplier **$20**; fee ≈ **$4.50**/round trip → **$9.50 / $14.50 / $19.50**
- Binance USDT-M futures: taker **0.04 %**/side → **0.08 %** round trip, plus slippage in ticks.

**Why it matters:** the measured gross edge is **≤ 0.052 R**. Unless `1 R` (the stop distance) is large
relative to the round-trip cost, the edge is consumed by costs alone. Any backtest report must state the
**break-even round-trip cost in R** alongside the expectancy.

---

## D10 — 2026-11-22 — Worktree isolation and the untracked research corpus

`research/github/`, `research/huggingface/`, `research/kaggle/` are **gitignored** (large binaries), so a
worktree does **not** contain them. Workers needing those artefacts must read them from the main tree
at the absolute path `/home/da/桌面/DodgysDD_ifvg/research/...`, **read-only**.

The NFS lake at `~/iflow_lake` and `~/.cache/quant_db` are **shared** between all leaves. A leaf must
not delete or overwrite another leaf's lake files; new writes go to leaf-owned paths.

---

## D11 — 2026-11-22 — The project is published to GitHub and synced from a single script

**Decision.** `jssyxd/DodgysDD-iFVG` is the canonical remote. It was created **private** (the user has
~100 repos, many public; this one is reversible in one click, and the lake's structure plus in-flight
research should not be public by default). The remote URL is kept **credential-free**; the token is
supplied at push time from the environment.

```bash
export GITHUB_TOKEN=<token>
scripts/sync_github.sh              # commit + push
scripts/sync_github.sh --check      # report drift, push nothing
```

**Credential hygiene — enforced, not merely intended.** Before the first push, four live tokens
(GitHub PAT, Hugging Face, Kaggle, cryptohftdata) were found in tracked files and **scrubbed**, replaced
by `$GITHUB_TOKEN` / `$HUGGINGFACE_TOKEN` / `$KAGGLE_KEY` / `$CRYPTOHFTDATA_API_KEY`. A pre-commit
guard (`scripts/pre-commit-secret-scan.sh`, installed at `.git/hooks/pre-commit`) now blocks any commit
that would introduce a live credential:
- generic shapes (`ghp_*`, `hf_*`, `KGAT_*`, `sk-*`, `xoxb-*`, `AKIA*`, private-key headers),
- the project's **known** token values, read from `.git/hooks/known_tokens.txt` — deliberately **outside**
  the repository so the guard script itself never holds a credential and can be committed,
- any file whose *name* looks like a secrets file.
`一些必备apikey和环境.txt` is gitignored; `.env.example` carries **names only**.

**What is not committed:** `research/github/`, `research/huggingface/`, `research/kaggle/` (the fetched
upstream corpus — large binaries, re-fetchable from `.field-guide/sources.md`), plus `data/`,
`artifacts/`, `research/candidates/`, `*.parquet`, `*.zip`, `.pi/` and `.herd-dispatch/`.

**Note for leaves:** the repo root was `git init`-ed for this. That is why `--worktree` isolation is now
possible. Worktrees therefore **do not** contain the gitignored upstream corpus — a leaf that needs it
must read it read-only from `/home/da/桌面/DodgysDD_ifvg/research/...`.

---

## D12 — 2026-11-22 — The vision layer is **not** to be built as a gate (from leaf L1)

**Decision.** Do not implement the discussion's vision layer as a *gate*. If it is built at all, build it
as an **offline batch feature extractor** that fills the D2 columns `vision_iou` / `vision_confidence`,
and only after the two experiments L1 names have run.

**Why.** L1's arithmetic, against the D4 baseline (base win rate **w = 0.327**):

- A gate that keeps a fraction `q` of candidates helps **only if the removed set is worse than the base**.
  To reach the design's `PF > 1.25` while keeping 80 % of trades, the gate must remove a sub-population
  whose win rate is **9.7 %** — roughly **3.4× better than random at finding losers**. Keeping 90 % of
  trades cannot reach PF 1.25 at all (the ceiling is 0.363 < 0.385).
- The shipped detector's labels are **hand-drawn FVG rectangles**. They contain **zero outcome
  information**. Its precision/recall (0.888/0.908, mAP@50 0.932) measure *"is there an FVG here"*, not
  *"will this trade make money"*. An outcome-uncorrelated filter leaves the expectancy **unchanged**
  while shrinking the sample — and `t` scales as `1/√q`, so it strictly **dilutes** statistical power.
- The mechanism the doc relies on (a human seeing "clean" structure) **is not implemented by this model
  at all**: the dataset has no cleanliness label.

**Consequences.**
1. `VISION_IOU_THRESHOLD = 0.75` is **deleted** (D6 already replaced the metric).
2. The ML feature set must **degrade gracefully** without the vision columns — the trainer excludes them
   and records the exclusion in the artefact metadata.
3. The vision layer is **not** on the critical path for phase 1.

---

## D13 — 2026-11-22 — The rule engine must be rebuilt, not patched (from leaf L2)

**Decision.** Build `dodgys_dd_quant/strategy/` as a **new package** that satisfies the conformance
matrix, rather than growing `research/experiments/e1_rule_falsification.py` into production. The
experiment script stays as the *falsification harness* and remains the source of the baseline.

**Why.** L2's tally over the 30-rule matrix: **8 faithful, 3 partial, 19 absent**. The existing code
implements a *code-derived core* only — no killzones, no PDH/PDL, no session extremes, no SMT, no
BE-intact gate, no checklist, no grade, and the sweep levels are not consumed once (so a level can be
"swept" repeatedly, which the Pine does not allow).

**Two corrections L2 established, both now applied to the sibling reports:**
1. **The inversion window is [1, 15], not [0, 15].** Age 0 is arithmetically impossible — a bullish FVG
   needs `low[c] > high[c-2]`, the age-0 trigger needs `close[c] < high[c-2]`, and `close[c] >= low[c]`
   (symmetric for bearish). Verified empirically: over 423,759 BTCUSDT 1-minute candidates the
   trigger-age histogram starts at **age 1**, with **zero** triggering at age 0.
   `PINE_RULES` §0.3-2/§R15/§C-2 and `AUDIT` §A.1.3 carried the wrong claim; correction notes have been
   added to both.
2. **"Faithful to the doc" and "faithful to the Pine" are different rules.** The doc makes the killzone
   a hard signal gate; the Pine makes it an **alert** filter and defaults to `0930-1600`. Both must be
   configurable and A/B'd, never conflated.

**Also fixed.** The doc's "A/A+" gate has no implementable definition (D8) → the checklist becomes five
named booleans whose sum is `checklist_score`, **reported, never filtered on**.

## 2026-11-24 — Nautilus Strategy port (doc module #5)

**D1 — the strategy consumes a precomputed candidate feed.** The rule engine is a pure function of the
whole bar history; calling it per event is O(history) per bar. The Nautilus strategy therefore consumes
the engine's D2 candidate log (or the archive) at each confirmation bar's close and owns execution,
position accounting and the export. Parity is defined on the candidate set and the fill prices, not on
re-implementing the rules.

**D2 — map only the execution-relevant switches**: inversion window, sweep gate, HTF alignment,
break-even exit, setup-history cap, candidate cap, direction bias, killzone-as-alert (never a gate),
fixed RR. `hideLosing` has no counterpart (INV4 forbids erasing a signal).

**D3 — ownership for the (deferred) swarm**: feed → `strategy/custom_data.py` + test; catalog →
`data_pipeline/catalog_builder.py` + test; mapping → `research/nautilus/PINE_TO_NAUTILUS.md`; strategy →
`strategy/dodgys_strategy.py` + test; runner → `backtest/nautilus_runner.py` + test; parity →
`tests/integration/test_nautilus_port.py`. Briefs live in `.herd-dispatch/jobs/` (gitignored).

Blocker for the swarm: `herd-dispatch assign` fails with `timed out waiting for agent startup` and
`watch` reports `herdr agent list` unavailable, so the captain implemented wave 1–2 itself. Measured
parity on a 2,000-bar BTCUSDT 30m slice: 240 candidates → 52 brackets → **49 positions**, the same 49
as the engine's one-position portfolio.
