# E7 — the design doc's own setting, on multi-year NQ/ES 1-minute data

The doc's phase-1 gate is NQ/ES, ~$4.5 round-turn fees, 1-2 ticks of slippage,
fixed 1:2 RR, and a profit factor > 1.25.  Every earlier test was on crypto,
where the fee *is* 0.6-1.1 R and therefore decides the result.  This is the
first run on the instrument and the cost model the document actually names.

Data: `NQ_1m` (3,664,241 bars, 2015-01 → 2025-07) and `ES_1m` (646,948 bars,
2020-11 → 2024-07) from the governed lake.  The common window is used whenever
the SMT reference is required.  Costs: the `nq` profile = $4.50 round trip +
1 tick of base crossing, plus 1 or 2 ticks of slippage ($9.50 / $14.50 per
round turn).  Regime VXN (daily, lagged), SMT reference the other index, one
position at a time (D4).

| cell | n | win % | E[R] gross | E_net | PF | t |
|---|---|---|---|---|---|---|
| NQ, `doc`, $9.50, 4h horizon | 1,798 | 29.9 | **-0.0464** | -0.0791 | 0.934 | -1.33 |
| NQ, `doc`, $14.50, 4h | 1,798 | 29.9 | -0.0464 | -0.0903 | 0.934 | -1.33 |
| NQ, `doc`, $9.50, 60h horizon | 1,877 | 30.7 | -0.0173 | -0.0481 | 0.975 | -0.50 |
| NQ, `honest`, $9.50, 4h | 16,488 | 31.0 | -0.0215 | -0.0948 | 0.969 | -1.87 |
| ES, `doc`, $9.50, 4h | 865 | 27.7 | **-0.1329** | -0.2729 | 0.816 | -2.76 |
| ES, `honest`, $9.50, 4h | 9,157 | 30.1 | -0.0916 | -0.4215 | 0.869 | -6.23 |
| NQ, `doc`, $9.50, 4h, 2015 → 2025 | 5,348 | 33.2 | -0.0093 | -0.0822 | 0.986 | -0.47 |

## What this settles

1. **The cost is no longer the explanation.** On NQ the round trip is
   0.033 R (4h) / 0.069 R (60h) -- an order of magnitude below crypto.  If the
   rules had a gross edge, it would show here.  It does not: the gross
   expectancy is **negative in all seven cells**, including the full 2015-2025
   history.
2. **The doc's phase-1 gate fails on its own terms.** PF 0.93-0.99 against the
   required > 1.25, on the instrument the document names, with its own fees.
   The 29.9-33.2 % win rates are at or below the 33.3 % a 1:2 payoff needs
   before costs.
3. **The 60-hour horizon is slightly better than 4 hours** (-0.017 vs -0.046
   gross on `doc`) but nowhere near positive -- consistent with the crypto
   finding that the intraday horizon truncates the trade, without rescuing it.
4. **ES is worse than NQ** (-0.133 vs -0.046 gross), which also rules out
   "the wrong instrument".

## Consequence

The next information source is the one the design doc's RL layer already names:
**order-flow imbalance**.  The lake carries `bar_ofi` on the 1m BTCUSDT
perpetual (3 years) and depth-20/L2 microstructure files; an OFI-conditioned
entry filter is a genuinely new signal, not another transform of the same OHLCV.
It is the next experiment, and it must be pre-registered against the registry
(now 106 trials) exactly as the 30m and MNQ hypotheses were.
