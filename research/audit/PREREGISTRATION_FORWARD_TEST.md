# PREREGISTRATION — the frozen configuration, forward test

**Written and committed BEFORE the test was run.** The commit that added this
file is the timestamp. Nothing in it may be changed in the light of the
results; if a parameter turns out to be wrong, the correction is a *new* file
and the original stays.

---

## 1. Why this test exists

The phase-1 configuration was **selected on NQ** after roughly sixty arms were
tried on that instrument (`research/audit/PHASE1_REPORT.md`). A configuration
chosen as the best of sixty, on the same sample it is measured on, is a
hypothesis. This document pre-registers the test that decides it.

## 2. The frozen configuration

No parameter of this may be changed for the duration of the test.

| parameter | value | why |
|---|---|---|
| rule set | `pine` — the reference-faithful leg tracker + BE-intact gate | the arm that carries the edge |
| inversion window | `doc` (7–15 bars) | as run on NQ |
| reward:risk | **2.0** | the doc's ratio; the RR sweep showed the edge is flat in RR, so this is not a tuned choice |
| session | **the doc's NY killzone** (09:30–11:30 and 13:30–15:30 ET) | the largest entry-side lever measured (+0.049 R) |
| checklist | **score ≥ 3, with ≥ 4 of the conditions decidable** | the implementable version of the doc's "A/A+ only" gate (the grade itself has no definition in any artefact — D8) |
| risk per trade | 1 unit R, stop beyond the gap→confirmation window extreme | the reference's geometry |
| accounting | **one position at a time, blocked signals dropped** | D4; the census arm is never quoted |
| costs | the instrument's own profile (`nq` / `es` / `binance`), 1 tick of slippage for the futures | D9 |
| regime | VXN for the futures, BTCDVOL for the crypto | as run on NQ |

**Explicitly NOT applied** (each was measured and found not to help on NQ):
the meta-labeler gate (AUC 0.47–0.53), the vision layer's confidence gate
(redundant with the checklist), the ATR gap floor, the mandatory sweep
precondition, any stop multiplier, and any vision IoU gate.

## 3. The test data — and why it did not participate in the selection

| test | instrument | period | why it is out of sample |
|---|---|---|---|
| **A** | **BTCUSDT 1m**, SMT reference **ETHUSDT** | 2023-01-01 → 2026-11-21 | a **different market**. No BTC bar, and no ETH bar, entered any of the ~60 selection arms — every one of them was NQ. |
| **A1** | BTCUSDT, **the tail only** | **2025-07-26 → 2026-11-21** | strictly forward on **every** axis: the NQ sample ends 2025-07-25, so no BTC bar in this window existed, or could have been seen, while the configuration was being chosen. |
| **A2** | BTCUSDT, the earlier part | 2023-01-01 → 2025-07-25 | different market, overlapping in time with the NQ selection window |
| **B** | ES 1m, SMT reference NQ | 2020-11-17 → 2024-07-19 | different market; **already executed** — reported, not re-run |

The NQ sample itself (2015-01-01 → 2025-07-25) is **not** a forward test: it
is the selection sample. It is reported for reference only.

The NQ dataset on Hugging Face was last modified **2025-07-25** and has no
newer file, so a strictly-forward *same-instrument* test is impossible today.
Test A1 is the closest available substitute and is strictly later than any
selection data.

## 4. The contrast that is also pre-registered

For each instrument the **plain reference arm** (the same rule set, RR 2, but
**no killzone and no checklist**) is run on the same data. This separates two
questions that the NQ result conflated:

* does the **rule** carry an edge on this instrument? → the plain arm;
* do the **filters** (session, checklist) carry over? → the frozen arm minus
  the plain arm.

## 5. Decision criteria — fixed now

**PASS** requires **all three** of:

1. **net E[R] > 0** — the arm is profitable after the instrument's real costs;
2. the **95 % CI of the gross E[R] excludes 0**;
3. **≥ 200 trades** — below that the statistic is underpowered and the result
   is *inconclusive*, not a failure.

**FAIL** if any of the three is not met on a test with ≥ 200 trades.

**INCONCLUSIVE** if the trade count is below 200.

The criteria are applied to **each** of A, A1 and A2 separately. A1 is the
strictest (strictly forward); A2 is the most powerful; A is their union.

## 6. What is reported whatever the outcome

* Every run's full output, including the losers, is committed
  (`research/experiments/`). No candidate is hidden.
* The **deflated Sharpe** is reported against the **~60 arms** already tried in
  this project, so the multiple-testing context travels with the number.
* A PASS on one instrument is **not** a proof of the strategy. It means the
  *configuration generalises* to that instrument. The selection bias of the
  original ~60 arms is not removed by this test; only the *filters'* transfer
  is tested.
* If the frozen configuration fails here, it fails. The configuration is **not**
  re-tuned on the basis of this test — a second selection on the same data
  would repeat the original mistake.

## 7. The command

```bash
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
LAKE=~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake

# the frozen configuration, BTCUSDT, SMT reference ETHUSDT
$PY -m dodgys_dd_quant.backtest.runner \
    --symbol BTCUSDT --timeframe 1m --preset pine --rr 2.0 --killzone \
    --min-checklist 3 --min-checklist-known 4 \
    --cost-profile binance --slippage-ticks 0 --inversion-window doc \
    --regime dvol --reference-symbol ETHUSDT --trials 64 --no-write-candidates

# the plain reference arm on the same data
$PY -m dodgys_dd_quant.backtest.runner \
    --symbol BTCUSDT --timeframe 1m --preset pine --rr 2.0 \
    --cost-profile binance --slippage-ticks 0 --inversion-window doc \
    --regime dvol --reference-symbol ETHUSDT --trials 64 --no-write-candidates
```

`--trials 64` — the arms already tried in this project, plus the arms this test
adds.

---

# RESULT (appended after the test ran; the criteria above are unchanged)

Raw output: `research/experiments/PREREG_FORWARD_TEST.txt` and
`research/experiments/PREREG_FORWARD_TEST_POSTHOC.txt`.

## The pre-registered run, as specified

| test | trades | net E[R] | gross E[R] | 95 % CI | verdict |
|---|---|---|---|---|---|
| **A** frozen config, BTCUSDT 2023-01 → 2026-11 | 192 | −0.522 | −0.094 | [−0.289, 0.102] | **INCONCLUSIVE** (192 < 200) |
| **A1** frozen config, strictly forward 2025-07-26 → 2026-11 | 75 | −0.406 | +0.040 | [−0.285, 0.365] | **INCONCLUSIVE** (75 < 200) |
| **A2** frozen config, BTCUSDT 2023-01 → 2025-07-25 | 115 | −0.584 | −0.165 | [−0.412, 0.082] | **INCONCLUSIVE** (115 < 200) |

All three are **inconclusive** under criterion 3: the checklist filter left only
192 / 75 / 115 trades.

## The contrast (the plain reference arm)

| test | trades | net E[R] | gross E[R] | 95 % CI | t |
|---|---|---|---|---|---|
| **A′** plain arm, 2023-01 → 2026-11 | 16,133 | −0.427 | **+0.0380** | **[0.016, 0.060]** | 3.38 |
| **A1′** plain arm, strictly forward | 5,182 | −0.452 | +0.0299 | [−0.009, 0.069] | 1.51 |
| **A2′** plain arm, 2023-01 → 2025-07-25 | 10,926 | −0.414 | **+0.0420** | **[0.015, 0.069]** | 3.07 |

## What the mechanism turned out to be — and the post-hoc re-run

The three inconclusive results had a **mechanical cause**, found by inspecting
the candidates rather than by re-tuning anything: the **crypto regime index was
never calibrated**. `DvolRegimeIndex` binned the DVOL series with the **VXN's**
edges (0 / 18 / 28 / 200), but the DVOL daily close runs **34–90** (p50 = 51),
so every reading fell above 28 and the crypto regime read **81.8 % "high",
0 % "normal"**. The ``vxn_regime_normal`` checklist condition was therefore
**never true on crypto**, and the checklist could almost never reach a score
of 3: **3.6 %** of the BTCUSDT candidates against NQ's 21.1 %.

The bands were calibrated to the DVOL quantiles that reproduce the **VXN's own**
daily occupancy (low 35.6 %, normal 48.5 %, high 15.9 %) — the rule is "match
the reference regime's occupancy", not "pick round numbers". The calibrated
index now occupies 35.7 / 48.1 / 16.2 %.

Re-running the **identical** pre-registered commands with that defect fixed
(`research/experiments/PREREG_FORWARD_TEST_POSTHOC.txt`) gives an adequate
sample and a clear verdict:

| test | trades | net E[R] | gross E[R] | 95 % CI | verdict |
|---|---|---|---|---|---|
| A post-hoc | 884 | −0.448 | −0.016 | [−0.109, 0.077] | **FAIL** |
| A1 post-hoc (strictly forward) | 238 | −0.373 | +0.008 | [−0.172, 0.189] | **FAIL** |
| A2 post-hoc | 644 | −0.474 | −0.022 | [−0.130, 0.087] | **FAIL** |

**This is a post-hoc result and is labelled as such.** The pre-registered
verdict stands as INCONCLUSIVE; the post-hoc run upgrades it to FAIL with a
sample large enough to say so.

## The verdict

1. **The frozen configuration does not generalise.** On BTCUSDT it turns a
   +0.038 R gross edge into **−0.016 R** — the session and checklist filters
   were **NQ-specific**. The same was already true on ES (§8 of the phase-1
   report). The filters are **not** part of the strategy; they are part of the
   NQ result.
2. **The rule engine's gross edge does replicate**, on BTCUSDT over the full
   window: +0.0380 R, t = 3.38, CI [0.016, 0.060] — the same magnitude as NQ.
3. **But it does not hold in the only strictly-forward window available**:
   +0.0299 R, t = 1.51, CI **[−0.009, 0.069]** — the CI includes zero, so
   criterion 2 is **not** met.
4. **Net expectancy is hopeless on crypto at any of these edges**: the Binance
   round trip is 0.46 R against a 0.03–0.04 R edge. That is a fact about
   crypto's fee structure, not about the strategy.

**Nothing here re-opens the selection.** The configuration was not re-tuned on
the basis of this test, and the pre-registration's criteria were applied as
written.

## What would actually settle it

* **More NQ data.** The NQ dataset stops at 2025-07-25; the strictly-forward
  window on the *same* instrument does not exist yet. When a vendor's NQ
  1-minute history extends past 2025-07-25, that window — and only that
  window — is a clean forward test of the NQ configuration.
* **A cost-aware instrument.** The gross edge is real; the problem is that
  0.10 R of NQ fees sits against 0.03 R of edge. A venue with a materially
  cheaper round trip, or a strategy that trades a materially larger size per
  unit of risk, changes the arithmetic.
* **A better rule.** The filters did not transfer; the *rule* did. The
  remaining lever is the rule's edge itself, not a filter on top of it.
