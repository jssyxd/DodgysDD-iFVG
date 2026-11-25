# V2 gates — the higher-timeframe bias works, the liquidity precondition does not

NQ killzone arm, `nq` costs, 1 tick, RR 2, one position at a time (drop). Every
number is net of the round trip.

| preset | gate | trades | win% | E[R] gross | **E[R] net** | PF | t | DSR p |
|---|---|---|---|---|---|---|---|---|
| `pine` | none | 6,745 | 35.7 | +0.0697 | **+0.0116** | 1.108 | 3.98 | 0.051 |
| **`pine_htf15only`** | **15m bias agrees** | 4,280 | 36.1 | **+0.0822** | **+0.0251** | **1.129** | 3.73 | 0.083 |
| `pine_htfonly` | 1H bias agrees | 4,280 | 36.0 | +0.0801 | +0.0230 | 1.125 | 3.64 | 0.099 |
| `pine_liqonly` | ≥2R liquidity target | 5,399 | 34.1 | +0.0224 | **−0.0402** | 1.034 | 1.16 | 0.888 |
| `pine_htf15` | 15m bias **and** liquidity | 2,936 | 35.0 | +0.0504 | −0.0081 | 1.078 | 1.91 | 0.680 |
| `pine_htf` | 1H bias **and** liquidity | 2,939 | 35.0 | +0.0493 | −0.0092 | 1.076 | 1.87 | 0.694 |
| `pine_half_tp` | 50 % at +1R, stop stays | 6,744 | 35.6 | +0.0612 | +0.0031 | 1.129 | 4.45 | — |
| `pine_half_tp_be` | 50 % at +1R, stop → BE | 7,445 | 52.8 | +0.0567 | −0.0014 | 1.120 | 4.61 | — |

## What this establishes

1. **The higher-timeframe bias gate is the one V2 change that pays.** Requiring the
   last closed **15m** bar to agree with the trade's direction doubles the net
   expectancy (**+0.0116 → +0.0251**) and lifts the profit factor (1.108 → 1.129)
   while keeping 63 % of the trades. The 1H bucket is statistically indistinguishable
   from the 15m one (they agree on almost every killzone setup).
2. **The doc's "clear ≥2R liquidity target" precondition is harmful.** On its own it
   cuts the gross edge by two-thirds (+0.0697 → +0.0224) and turns the arm net
   **negative** (−0.0402). It removes the good trades, not the bad ones.
3. **The two gates together are worse than the bias gate alone**, because the harmful
   gate dominates. This is why the ablation matters: the combined preset looked like a
   failure of "multi-timeframe", when the failure is one specific condition.
4. **The partial take-profit is net-negative at this cost level** (see
   `RISK_MANAGEMENT_NET.md`): +0.0031 R net, and no drawdown improvement once costs
   are charged.

## The best arm now on record

`pine_htf15only` — the reference-faithful rule, the NY killzone, and a **15m bias
agreement** gate: **E[R] net +0.0251**, PF **1.129**, t **3.73**, 4,280 trades over
ten years. Its deflated-Sharpe p-value is **0.083** against the 64 arms tried, so it is
still a hypothesis rather than a validated edge — but it is the first configuration
that clears the cost with room to spare without inventing a rubric.

## What is NOT established

The cost is still 0.058 R against a 0.025 R net edge: the margin is thin and any
additional rule that trims the gross edge will eat it. A V2 that adds more filters is
likely to lose money; the head-room is in the cost/edge ratio.
