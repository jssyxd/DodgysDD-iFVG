# Risk management on the NQ killzone arm — net of costs

**All numbers below are NET of the NQ round trip** (`nq` profile, 1 tick of slippage, mean **0.058 R per trade**). The gross numbers are in `DRAWDOWN_CONTROL.md`; they tell a different story, and that difference is the point of this file.

## 0. Why net changes everything

The gross edge is **+0.0697 R** per trade and the round trip is **0.058 R**. That leaves **+0.0116 R** net — a margin of 0.012 R. So a rule that costs 0.008 R of gross edge cuts the net edge by **more than half**, and any rule that trims the gross tail is not affordable at this cost level.

## 1. The three presets, full backtest (one position at a time, drop)

| preset | trades | win% | E[R] gross | **E[R] net** | PF | t | total R net | **max DD net** | Calmar-ish (total/DD) |
|---|---|---|---|---|---|---|---|---|---|
| pine (stop / full 2R target) | 6745 | 35.7 | +0.0697 | **+0.0116** | 1.108 | 3.98 | +78.1 R | **113.9 R** | 0.69 |
| pine_half_tp (50% at +1R, stop stays) | 6744 | 35.6 | +0.0612 | **+0.0031** | 1.129 | 4.45 | +20.6 R | **116.7 R** | 0.18 |
| pine_half_tp_be (50% at +1R, stop to BE) | 7445 | 52.8 | +0.0567 | **-0.0014** | 1.120 | 4.61 | -10.1 R | **115.8 R** | -0.09 |

## 2. A — position sizing (net), on the `pine` arm

| rule | mean size | trades | total R net | **E[R] net** | max DD net | DD per unit size |
|---|---|---|---|---|---|---|
| no rule (1.0x) | 1.000 | 6,745 | +78.1 R | **+0.0116** | **113.9 R** | 113.9 R |
| vol targeting (1/ATR) | 1.273 | 6,745 | -92.7 R | **-0.0137** | **293.2 R** | 230.3 R |
| VXN-high halving | 0.895 | 6,745 | +49.7 R | **+0.0074** | **113.1 R** | 126.4 R |
| drawdown brake | 0.523 | 6,745 | +34.6 R | **+0.0051** | **60.2 R** | 115.1 R |
| loss-streak brake | 0.806 | 6,745 | +31.7 R | **+0.0047** | **84.1 R** | 104.3 R |
| cap the widest stops | 0.975 | 6,745 | +77.3 R | **+0.0115** | **113.9 R** | 116.8 R |
| vol + regime | 1.211 | 6,745 | -107.6 R | **-0.0160** | **290.9 R** | 240.2 R |

A sizing rule trades *variance* for *level*, so the comparable numbers are **E[R] net** (per trade, per unit of risk) and **max DD net per unit of size**. The baseline is E[R] **+0.0116**, DD **113.9 R**.

**None of them reduces the net drawdown per unit of risk.** Vol targeting increases it (230 R per unit vs 114); the drawdown brake leaves it unchanged; the loss-streak brake makes it worse. The only rule that helps on both axes gross — capping the widest stops — helps by ~4 %, which is inside the noise.

## 3. B — exit management (net), replayed on the same trades

| rule | total R net | max DD net | E[R] net | verdict |
|---|---|---|---|---|
| break-even at +1R | -62.9 R | 146.3 R | -0.0093 | **worse on both** |
| 50% at +1R + BE | -47.9 R | 137.6 R | -0.0071 | **worse on both** |
| 50% at +1R, stop stays | +19.6 R | 116.7 R | +0.0029 | **worse on both** |

## 4. What the net numbers say

1. **The half-TP preset is net-negative versus the baseline**: total net R falls from **+78.1** to **+20.6**, and the net drawdown does **not** improve (113.9 → 116.7 R). The gross result (−16.7 % drawdown for −12.4 % profit) inverts once the fixed cost is charged: the profit loss is 74 % of the net.

2. **Break-even at +1R is the worst rule tested**: net total **−62.9 R** and a net drawdown of 146.3 R, both worse than doing nothing.

3. **The drawdown is larger than the total profit at this cost level**: +78.1 R of net profit against a **113.9 R** net drawdown over ten years. That is the single most important number in this report — the arm is not investable as it stands, and no exit rule fixes it.

4. The PF and t improve with half-TP (1.108 → 1.129, 3.98 → 4.45) because the R distribution is smoother, but the net expectancy — the thing that pays — falls.

## 5. The consequence for V2

Any V2 work that adds a **filter or an exit rule** must first recover the 0.058 R round trip. At a 0.012 R net margin there is no room for a rule that costs even a tenth of the gross edge. The lever with real head-room is the **cost/edge ratio**: a cheaper venue, a wider stop in dollar terms, or a gross edge several times larger — not another overlay.
