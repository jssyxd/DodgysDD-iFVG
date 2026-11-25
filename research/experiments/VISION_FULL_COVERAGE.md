# Vision at full coverage — the signal does not discriminate

The vision signals were re-scored on the **corrected** NQ killzone candidate set
(after the timezone fix moved the gate to the real NY session), so
`vision_iou` / `vision_confidence` are now populated for **11,097 of 11,132**
candidates (**99.69 %**) instead of 44 %.

| quantity | value |
|---|---|
| point-biserial r(`vision_iou`, `label`) | **−0.0044** |
| point-biserial r(`vision_confidence`, `label`) | **−0.0009** |
| IoU ≥ 0.75 vs the rest (two-proportion z) | **−0.38** |
| check rerun by `scripts/vision_signals.py` | 76.6 % of detected boxes clear the doc's 0.75 gate |

Win rate by the doc's IoU gate (baseline is 35.20 %):

| group | n | win% | E[R] |
|---|---|---|---|
| IoU ≥ 0.75 | 8,622 | 35.14 | +0.0543 |
| 0 < IoU < 0.75 | 52 | 38.46 | +0.1538 |
| IoU = 0 (not detected) | 2,423 | 35.49 | +0.0648 |

Win rate by the detector's confidence — flat and non-monotone:

| conf | n | win% | E[R] |
|---|---|---|---|
| [0.00, 0.01) | 1,936 | 35.18 | +0.0553 |
| [0.01, 0.30) | 305 | 39.02 | +0.1705 |
| [0.30, 0.50) | 1,342 | 35.54 | +0.0663 |
| [0.50, 0.65) | 2,261 | 34.85 | +0.0456 |
| [0.65, 0.80) | 3,775 | 34.60 | +0.0379 |
| [0.80, 1.01) | 1,478 | 36.47 | +0.0940 |

## What this changes

The earlier **z = +2.26** for the detector's confidence was measured on the raw,
**unfiltered** census, where the low-confidence group coincided with the bad
setups that the killzone and the checklist now remove. Once those filters are in
place, the vision confidence has **nothing left to say** — and this now holds at
~100 % coverage rather than on a 5.9 % sample.

The vision layer remains **mechanically correct** and it **corrected a wrong
audit** (the doc's `IoU > 0.75` gate is reachable: 76.6 % of detected boxes
clear it). It is a **geometry cross-check**, not a trading filter.

`checklist_score`'s correlation with the label is still **−0.0176**: the five
named conditions together carry no linear signal on this arm either.
