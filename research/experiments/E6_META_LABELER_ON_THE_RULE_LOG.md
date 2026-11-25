# E6 — the meta-labeler on the 284k rule-candidate log, and the MNQ prereg

## 1. The default input

`python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler` now defaults
`--candidates` to `logs/rule_candidates/candidates.parquet` when the flag is
omitted (and says so in its output).  The log holds 284,083 candidates from 98
cells (70 crypto, 28 MNQ/MES), y = 93,386 targets / 181,271 stops / 9,426
unresolved, every feature column complete.

Retrain command (the mixed log needs an explicit embargo; 1 h x 60 bars =
3,600 minutes, the engine's 60 h horizon):

    python -m dodgys_dd_quant.ml_pipeline.train_meta_labeler \
        --symbol MIXED --timeframe mixed --run-root artifacts/models_mixed \
        --bar-interval-minutes 60 --horizon-bars 60

## 2. Result: no change

136 folds trained, 193,467 test rows scored, 27,503 admitted by the
validation-quantile gate.

| statistic | value |
|---|---|
| AUC mean / median | **0.5120 / 0.5121** (min 0.398, max 0.671) |
| gated lift mean / median | -0.0057 / +0.0076 |
| folds with a positive lift | 68 / 136 (a coin flip) |
| base rate (test) | 0.340 |
| per-kind AUC (last 8 folds) | crypto **0.529** over 26,051 rows; futures 10 rows, not measurable |

The previous single-instrument runs measured **0.485-0.522**.  A 284k-row
population with 98 cells, a balanced-ish label and every feature did not move
the AUC off 0.51: the features carry no information about *this* label, and that
is now measured on 40x more data.

## 3. The MNQ 15m doc cell: pre-registered, then rejected

The matrix found MNQ 15m doc at E_net **+0.0769 R** (n=998, t=2.22) -- the only
cell that looked like a lead.  Before touching it again:

1. the 28 futures cells were registered as trials (`matrix-2026-11-25:*`),
   taking the registry to **104** trials;
2. `prereg-mnq-15m-doc` was registered **with its decision rule** (net > 0 and
   DSR p < 0.05 at N = the registry's count; no further filter);
3. only then was the DSR computed, on the net per-trade series.

| quantity | value |
|---|---|
| n (closed, net) | 942 |
| E_net | +0.0769 R |
| Sharpe per trade | 0.0516 |
| **deflated Sharpe p** | **0.8380** (N = 106) |

**Rejected.**  With 106 trials a Sharpe of 0.05 per trade is expected noise; the
data point is real, the *edge* is not established.

## 4. What this means for the next step

* Training is not the bottleneck: 284k rows, correct purging, calibrated gate,
  and AUC 0.512.  More features of the same kind will not help.
* The rule layer's gross expectancy on this population is small and
  instrument-specific; the meta-labeler cannot rescue it (it never could --
  A1 has fired on every run).
* The remaining honest avenues are **new information** (order flow / OFI, the
  actual ICT session structure, tick-level execution effects) or **new
  instruments with the costs that do not dominate** (the NQ/ES 1m lane is now
  multi-year, so a proper NQ/ES 1m/15m test is finally possible).
