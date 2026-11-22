# E-1 — Rule-engine falsification test: RESULTS (rev. 2)

**Executed:** 2026-11-22 · **Code:** `research/experiments/e1_rule_falsification.py` (stdlib + pyarrow)
**Raw outputs:** `E1_RAW_OUTPUT_xauusd.txt`, `E1_RAW_OUTPUT_btcusdt1m.txt`
**Command:**
```bash
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
$PY research/experiments/e1_rule_falsification.py --cost-r 0.0                     # Kaggle XAUUSD 15m
$PY research/experiments/e1_rule_falsification.py \
    --data /home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet \
    --cost-r 0.05                                                                      # governed lake BTCUSDT 1m
```

> ### ⚠️ Revision 2 corrects Revision 1
> **Revision 1 of this report was computed with unlimited concurrent positions** (one position per
> candidate). That is a *signal census*, not a portfolio: the trades overlap heavily, so they are
> strongly correlated and the iid t-statistic is inflated. Revision 2 adds a **one-position-at-a-time**
> arm, which is what a real backtest does and which makes the t-statistic meaningful.
> **Every headline number in Revision 1 is superseded.** See §3 for the corrected figures.
> The finding is unchanged in direction and **stronger**: there is no edge.

---

## 1. What is tested

The **code-derived** iFVG core, every predicate cited to
`research/github/IFVG-Ultimate-Dodgy/ifvgUltimatePlus.pine`:

| Element | Source | Implementation |
|---|---|---|
| FVG geometry | pine:354-355 | bullish `low[c] > high[a]`; bearish `high[c] < low[a]` |
| Inversion trigger | pine:437 | bullish FVG → `close[k-1] < gap_bottom` → **short**; bearish → `close[k-1] > gap_top` → **long** |
| Expiry | pine:499 | drop when `bar_index - c > grace` |
| Stop | pine:293-296, 462 | long → window **min low**; short → window **max high** (`slPlacement="Wick"`) |
| Target | pine:317, 321 | `entry ± 2·risk` (fixed 1:2) |

No look-ahead: the trigger uses a bar that has strictly closed; the fill is the next bar's open (or, in
the `code:close(k)` arm, the confirmation close). If a bar touches both the stop and the 2R target, the
**stop wins** (conservative).

**Arms (pre-registered):** inversion window `code[0,15]` vs `doc[7,15]` · ATR floor `none` vs `0.25×ATR(14)`
· fill `open(k)` vs `close(k-1)` · sweep gate `off` (code default) vs `on` (doc) · **concurrency
`concurrent` (census) vs `one-at-a-time` (portfolio)**.

**Not applied:** the "A/A+ only" phase-1 filter — no artifact defines A or A+.

## 2. Data

| Run | Series | Bars | Range |
|---|---|---|---|
| XAUUSD 15m | Kaggle CSV (the only price file that shipped with this repo) | 4,502 | 2026-07-14 → 2026-09-22 |
| **BTCUSDT 1m** | **governed lake** `crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet` (newly ingested from Binance Vision) | 305,280 | 2023-01-01 → 2023-07-31 (partial: the download is still running) |

The Kaggle CSV's own `Bullish_FVG`/`Bearish_FVG` columns are **not** used — they are forward-filled
booleans that are not reproducible from that CSV's own OHLC (14 %/9 % same-direction overlap).

---

## 3. CORRECTED RESULTS

### 3.0 ⭐ BTCUSDT 1-minute, **FULL 3.9-YEAR DATASET** (2,046,240 bars, 2023-01-01 → 2026-11-21)

This is the decisive run: real one-minute bars, 3.9 years, gap-free, taken from the
governed lake partition that this session ingested. Cost assumption 0.05 R round trip.

| Concurrency | n | win% | E[R] | E_net (0.05 R) | PF | t | 95 % CI |
|---|---|---|---|---|---|---|---|
| `concurrent` (census) | 423,759 | 34.4 | **+0.033** | −0.017 | 1.051 | **15.28** | [+0.029, +0.038] |
| **`one-at-a-time`** | **15,928** | 32.7 | **−0.020** | −0.070 | **0.971** | **−1.76** | [−0.042, +0.002] |
| `concurrent`, sweep on | 189,207 | 34.0 | +0.021 | −0.029 | 1.032 | 6.52 | [+0.015, +0.028] |
| **`one-at-a-time`**, sweep on | 26,326 | 33.7 | **+0.011** | −0.039 | 1.017 | 1.30 | [−0.006, +0.028] |

**Every one-at-a-time arm across all 32 combinations has a 95 % CI that includes
zero**, and the expectancy ranges from **−0.024 R to +0.014 R** — i.e. centred on
nothing. With a 0.05 R round-trip cost **every arm is negative**. The **sign flips
across the fill arm in every one of the four parameter groups**, so the result is
not stable under defensible parameterisation.

The concurrent census arm again shows a large t-statistic (**15.28**) and a CI
excluding zero — and again it is **entirely an artefact** of 423,759 simultaneously
open, mutually correlated positions.

### 3.1 BTCUSDT 1-minute, partial dataset (305,280 bars, 2023-01 → 2023-07)

| Concurrency | n | win% | E[R] | E_net (0.05 R cost) | PF | t | 95 % CI |
|---|---|---|---|---|---|---|---|
| `concurrent` (census) | 63,308 | 35.1 | **+0.052** | +0.002 | 1.080 | **9.08** | [+0.041, +0.063] |
| **`one-at-a-time`** | **1,693** | 33.0 | **−0.011** | −0.061 | 0.983 | **−0.33** | [−0.078, +0.056] |
| `concurrent`, sweep on | 28,526 | 34.6 | +0.037 | −0.013 | 1.057 | 4.40 | [+0.021, +0.054] |
| **`one-at-a-time`**, sweep on | 3,475 | 34.1 | +0.023 | −0.027 | 1.035 | 0.95 | [−0.024, +0.070] |

**The entire apparent significance is a concurrency artefact.** At 63,308 overlapping positions the
t-statistic reaches 9.08 and the CI excludes zero. As soon as the backtest is allowed to hold **one
position at a time** — 1,693 trades — the edge is **−0.011 R, t = −0.33, CI [−0.078, +0.056]**, i.e.
indistinguishable from zero.

Across the 32 arms: 31/32 have positive **gross** expectancy, but **no one-at-a-time arm has a 95 % CI
that excludes zero**, and with a 0.05 R round-trip cost **every one-at-a-time arm has net expectancy
≤ +0.002 R** — effectively zero.

### 3.2 XAUUSD 15-minute (4,502 bars)

Best one-at-a-time arm: E[R] = **+0.200**, PF = 1.333, **n = 54**, t = 0.83, CI **[−0.227, +0.560]** —
pure noise at that sample size. The sign **flips across the fill/sweep arms in every parameter group**.
Revision 1's "best arm PF = 1.193" was a *concurrent* figure and is superseded.

### 3.3 The cost arithmetic

For NQ (tick 0.25 pt = $5.00, multiplier $20) the design doc's ~$4.50 fee + 1–2 ticks of slippage is
**$14.50–$24.50** per round turn:

| Typical NQ risk/trade | $14.50 | $24.50 |
|---|---|---|
| $200 (10 pts) | 0.073 R | 0.123 R |
| $400 (20 pts) | 0.036 R | 0.061 R |
| $100 (5 pts) | 0.145 R | 0.245 R |

The measured gross edge on real 1-minute data is **≤ 0.052 R** — below the round-trip cost at **any**
stop distance of $100 or more. The edge is *entirely* a function of trading costs, not of the signal.

---

## 4. Verdict

**FAIL.** The pre-registered criterion was: PASS if some arm has expectancy > 0 **and** PF > 1.25
cost-free **and** a stable sign; FAIL if every arm has expectancy ≤ 0.

On the **full 3.9-year BTCUSDT 1-minute dataset** (2,046,240 bars, gap-free, from the
governed lake) the substantive answer is unambiguous:

- With a **one-position-at-a-time** portfolio, expectancy is **−0.024 R to +0.014 R** across all 32
  arms — centred on zero. **Every 95 % CI includes zero.** The best gross edge is **0.014 R**, and
  the *worst* arm is negative.
- **PF never exceeds 1.051** (the census arm), versus the **> 1.25** gate the design doc demands.
- With a realistic 0.05 R round-trip cost, **every arm is negative** (E_net from −0.070 to −0.033).
- The sign **flips across the fill arm in every parameter group** — the result is not stable.
- On the shorter XAUUSD sample the sign is likewise not stable, and every CI includes zero.

**Interpretation:** the iFVG rule engine, implemented faithfully from the reference source with no
look-ahead, does **not** demonstrably produce a positive-expectancy signal. The revision-1 "best arm"
was an artefact of counting 63,308 simultaneously-open, mutually-correlated positions as if they were
63,308 independent bets.

**This does not prove the strategy cannot work on NQ.** It proves that (a) on the one market with
multi-year real 1-minute data available to us, it does **not**; and (b) the phase-1 gate as written
("A/A+ only") is still not computable. It also *reinforces* the upstream replica author's own
conclusion that the strategy has "NO" value — the author who reverse-engineered the closed-source
original from DodgysDD's own videos.

**Consequence:** phase 2 (vision layer, meta-labeling, RL) must not start. What is needed is not more
modeling — it is (i) multi-year NQ+ES 1-minute data (the Twelve Data pushdown now running; otherwise
Databento), and (ii) a defensible definition of the A/A+ population, and then (iii) a re-run of this
exact test with one position at a time and real costs.

## 5. What this test still does not prove

It does not prove anything about NQ, about the SMT leg, about the VXN regime, about the vision layer,
or about the closed-source original's behaviour (the replica is a partial re-implementation). It proves
that **the rule engine as specified has no detectable edge on the data we can actually test it on**,
and it removes the false hope that the concurrent-position artefact was a real result.

## 6. Reproduction notes

- The `concurrent` arm is kept in the grid deliberately: it is the *signal census* (how often the
  pattern fires) and it is the trap. Never quote its t-statistic.
- `E-1_RAW_OUTPUT_*.txt` contain the full 32-arm tables.
- `research/experiments/e1_rule_falsification.py --data <parquet>` runs the same engine against any
  governed-lake Parquet, so this test can be re-run the moment the full BTCUSDT/ETHUSDT 1m history
  lands (the download is unattended; `scripts/finish_crypto_1m.sh` promotes and re-audits it).
