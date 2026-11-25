# Drawdown control — the NQ killzone arm

Portfolio: **one position at a time, drop** (the engine's own `simulate_portfolio`), **6,745** trades. Raw expectancy **+0.0697 R**, win rate **35.66 %**.

Every rule is causal: its inputs (`atr14`, the lagged VXN regime, the running equity, the loss streak, the price path) are known at the trade's entry.

`normalised` divides by the rule's **mean size**, so a rule is not credited for simply trading smaller.

## A. Position sizing (scales each trade)

| rule | mean size | trades | total R | total R (normalised) | max DD (R) | max DD (normalised) | DD length | Sortino | win% |
|---|---|---|---|---|---|---|---|---|---|
| R0 baseline | 1.000 | 6745 | +470.0 | +470.0 | 45.0 | 45.0 | 459 | 0.070 | 35.7 |
| R1 vol target | 1.273 | 6745 | +655.5 | +515.1 | 111.2 | 87.4 | 487 | 0.065 | 35.7 |
| R2 regime | 0.895 | 6745 | +424.0 | +473.6 | 42.0 | 46.9 | 322 | 0.068 | 35.7 |
| R3 dd brake | 0.621 | 6745 | +295.5 | +475.7 | 28.0 | 45.1 | 825 | 0.067 | 35.7 |
| R4 streak brake | 0.806 | 6745 | +348.0 | +431.9 | 47.0 | 58.3 | 830 | 0.061 | 35.7 |
| R6 vol + regime | 1.211 | 6745 | +624.5 | +515.9 | 113.4 | 93.6 | 487 | 0.063 | 35.7 |
| R5 wide-stop cap (risk > p95) | 0.975 | 6745 | +468.0 | +480.0 | 42.0 | 43.1 | 407 | 0.071 | 35.7 |

**Baseline:** total +470.0 R, max drawdown **45.0 R**, Sortino 0.070.

| rule | max DD (normalised) change | total R (normalised) kept | verdict |
|---|---|---|---|
| R1 vol target | -94.2 % (positive = smaller DD) | 109.6 % | no help |
| R2 regime | -4.3 % (positive = smaller DD) | 100.8 % | no help |
| R3 dd brake | -0.2 % (positive = smaller DD) | 101.2 % | no help |
| R4 streak brake | -29.6 % (positive = smaller DD) | 91.9 % | no help |
| R6 vol + regime | -108.1 % (positive = smaller DD) | 109.8 % | no help |
| R5 wide-stop cap (risk > p95) | +4.3 % (positive = smaller DD) | 102.1 % | **marginal, both axes improve** |

## B. Outcome management (changes the R distribution)

The design doc's RL action space names a **break-even trigger** and a **partial take-profit**. These cannot be tested by reweighting — the trade's terminal R changes — so they are replayed on the raw bars.

| rule | mean size | trades | total R | total R (normalised) | max DD (R) | max DD (normalised) | DD length | Sortino | win% |
|---|---|---|---|---|---|---|---|---|---|
| R7 break-even at +1R | 1.000 | 6745 | +329.0 | +329.0 | 79.0 | 79.0 | 861 | 0.049 | 26.1 |
| R8 50% at +1R, rest to 2R/BE | 1.000 | 6745 | +344.0 | +344.0 | 48.5 | 48.5 | 860 | 0.051 | 52.7 |
| R9 50% at +1R, stop stays | 1.000 | 6745 | +411.5 | +411.5 | 37.5 | 37.5 | 319 | 0.061 | 35.6 |

| rule | max DD change vs baseline | total R kept | E[R] | verdict |
|---|---|---|---|---|
| R7 break-even at +1R | -75.6 % | 70.0 % | +0.0488 | no help |
| R8 50% at +1R, rest to 2R/BE | -7.8 % | 73.2 % | +0.0510 | no help |
| R9 50% at +1R, stop stays | +16.7 % | 87.6 % | +0.0610 | trade-off |

## C. What this measures, and what it does not

* A sizing rule only helps if `max DD (normalised)` falls while `total R (normalised)` holds; cutting both is just smaller trading.

* An outcome rule is judged on the same two numbers, but it is allowed to move `E[R]` — break-even trades a lower expectancy for a shorter tail.

* One instrument, one contract, no per-trade dollar cap. The per-trade risk cap is the same arithmetic in dollar space.

* The meta-labeler's `P(Win)` is **not** a sizing input: its median out-of-sample AUC is 0.497, so a probability-weighted size would be sizing on noise.
