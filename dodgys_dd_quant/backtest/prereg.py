"""Pre-registration: put the matrix in the ledger, then state the hypothesis.

The registry is write-once (``backtest/trials.py``), so this module does the
two things L4 §F.5 requires, in order:

1. **Register what was already run.**  The 5x7x2 baseline matrix *is* 70
   trials: each cell was measured.  Their OOS return series (the one-position
   portfolio's realised R per trade) go into the ledger, which is what makes
   ``N`` knowable at all.
2. **Register the next hypothesis before looking at its result.**  The
   decision rule is part of the trial's ``config``: a hypothesis whose
   acceptance criterion is chosen after seeing the numbers is not a
   pre-registration.

CLI::

    python -m dodgys_dd_quant.backtest.prereg matrix \
        --matrix artifacts/matrix_2026-11-24 --registry artifacts/trials
    python -m dodgys_dd_quant.backtest.prereg hypothesis \
        --registry artifacts/trials --name prereg-30m-doc
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import pandas as pd

from dodgys_dd_quant.backtest.trials import TrialRegistry, trial_count_for

__all__ = ["register_matrix", "register_hypothesis", "HYPOTHESIS_30M"]

#: The pre-registered hypothesis and, crucially, its decision rule.
HYPOTHESIS_30M = {
    "question": (
        "Does the doc preset's ATR gap floor carry a net edge at 30 minutes "
        "across the five liquid USDT perps?"
    ),
    "population": "BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT @ 30m",
    "config": {
        "timeframe": "30m",
        "preset": "doc",
        "horizon_minutes": 3600.0,
        "regime": "dvol",
        "cost_profile": "binance (0.08 % round trip + 1 tick, per-symbol tick)",
        "slippage_ticks": 1,
        "accounting": "one position at a time, drop (D4)",
        "sample": "2023-01 -> 2026-10 (the resampled lanes)",
    },
    "decision_rule": {
        "accept_if": [
            "the median of the five arms' E_net is > 0",
            "at least 3 of 5 arms have E_net > 0",
            "the best arm's deflated-Sharpe p-value < 0.05 with N = the "
            "registry's trial count (i.e. after deflating for every cell in "
            "the matrix and this hypothesis)",
        ],
        "reject_if": [
            "any of the above fails -- and no further filter is fitted on "
            "this sample; the hypothesis is closed",
        ],
        "why_this_rule": (
            "the matrix's 30m cells were the only cluster with a positive "
            "median (4 of the top 5 cells), but at 70 trials that observation "
            "is expected ~0.26 times under the null, so it needs a rule fixed "
            "in advance rather than a search after the fact"
        ),
    },
}


def register_matrix(matrix_dir: str | Path, registry_root: str | Path) -> dict:
    """Register every cell of the matrix as one trial (append-only)."""
    matrix_dir = Path(matrix_dir)
    registry_root = Path(registry_root)
    registry = TrialRegistry(registry_root)
    runs = pd.read_parquet(matrix_dir / "runs.parquet")
    cands = pd.read_parquet(
        matrix_dir / "candidates.parquet",
        columns=["run_id", "r_multiple", "selected", "y", "symbol", "timeframe", "preset"],
    )
    already = registry.names()
    added = 0
    for row in runs.itertuples():
        name = f"matrix-2026-11-24:{row.run_id}"
        if name in already:
            continue
        trades = cands[(cands.run_id == row.run_id) & cands.selected]
        returns = pd.to_numeric(trades.r_multiple, errors="coerce").dropna().tolist()
        registry.record(
            name=name,
            config={
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "preset": row.preset,
                "horizon_minutes": row.horizon_minutes,
                "cost_profile": row.cost_profile,
                "slippage_ticks": int(row.slippage_ticks),
                "regime": row.regime,
                "n_bars": int(row.n_bars),
                "n_candidates": int(row.n_candidates),
                "n_trades": int(row.n_trades),
                "expectancy_r": float(row.expectancy_r),
                "expectancy_net_r": float(row.expectancy_net_r),
                "note": "baseline matrix cell; OOS series = the one-position "
                        "portfolio's realised R per trade",
            },
            oos_returns=returns,
        )
        added += 1
    stats = registry.trial_statistics()
    return {"added": added, "registry": str(registry_root), **stats}


def register_hypothesis(registry_root: str | Path, name: str) -> dict:
    """Register the 30m hypothesis **and its decision rule** as one trial."""
    registry = TrialRegistry(Path(registry_root))
    if name in registry.names():
        return {"registered": False, "reason": "already registered", "name": name}
    registry.record(name=name, config=HYPOTHESIS_30M, oos_returns=())
    return {
        "registered": True,
        "name": name,
        "trials_before_run": trial_count_for(registry),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prereg", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_matrix = sub.add_parser("matrix")
    p_matrix.add_argument("--matrix", default="artifacts/matrix_2026-11-24")
    p_matrix.add_argument("--registry", default="artifacts/trials")

    p_hyp = sub.add_parser("hypothesis")
    p_hyp.add_argument("--registry", default="artifacts/trials")
    p_hyp.add_argument("--name", default="prereg-30m-doc")

    args = parser.parse_args(argv)
    if args.command == "matrix":
        print(json.dumps(register_matrix(args.matrix, args.registry), indent=2))
    else:
        print(json.dumps(register_hypothesis(args.registry, args.name), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
