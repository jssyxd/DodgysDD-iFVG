"""The write-once trial registry (L4 §F.5).

L4 §F.5 is blunt about what is missing:

    *"A complete, immutable trial registry. Every backtest configuration
    ever run, with its full OOS return series, appended to a write-once
    ledger. ... Without the registry, DSR is not computable and the number
    of trials is unknowable -- which is exactly how the census arm got
    reported."*

So the registry is **append-only**: a trial is registered *before* its
result is inspected, and a name can never be registered twice.  The ledger
is a JSON-lines file, because a single Parquet file cannot be appended to
atomically; ``to_parquet`` writes the derived Parquet artefact the audit
names.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from dodgys_dd_quant.backtest.accounting import ACCOUNTING_STATEMENT

__all__ = ["TrialRegistry", "Trial", "trial_count_for"]


class Trial:
    """One registered trial: a configuration and its OOS return series."""

    __slots__ = ("name", "config", "oos_returns", "index")

    def __init__(
        self,
        name: str,
        config: dict,
        oos_returns: Sequence[float],
        index: int,
    ) -> None:
        self.name = name
        self.config = config
        self.oos_returns = [float(r) for r in oos_returns]
        self.index = index

    @property
    def n_trades(self) -> int:
        return len(self.oos_returns)

    @property
    def sharpe(self) -> float:
        """The trial's own Sharpe ratio (the trial-count input of the DSR)."""
        r = np.asarray(self.oos_returns, dtype=np.float64)
        if r.shape[0] < 3:
            return float("nan")
        sd = float(r.std(ddof=1))
        if sd <= 0.0:
            return float("nan")
        return float(r.mean()) / sd

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "config": self.config,
            "oos_returns": self.oos_returns,
            "sharpe": self.sharpe,
        }


def trial_count_for(registry: "TrialRegistry", *, include_current: bool = True) -> int:
    """The DSR's trial count ``N``, taken from the ledger.

    L4 §F.5 insists that ``N`` comes from the registry: "without the
    registry, DSR is not computable and the number of trials is unknowable".
    The run that is being reported is itself a trial, so the count is the
    ledger's size plus one unless the caller has already registered it.
    """
    return max(2, registry.trial_count() + (1 if include_current else 0))


class TrialRegistry:
    """The append-only ledger of every configuration that was run.

    Parameters
    ----------
    root:
        The directory the ledger lives in.  It is created if missing.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "registry.jsonl"

    # --- reading -----------------------------------------------------------

    def trials(self) -> list[Trial]:
        """Every registered trial, oldest first."""
        out: list[Trial] = []
        if not self.ledger_path.exists():
            return out
        with self.ledger_path.open("rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                out.append(
                    Trial(
                        name=record["name"],
                        config=record.get("config", {}),
                        oos_returns=record.get("oos_returns", []),
                        index=int(record.get("index", len(out))),
                    )
                )
        return out

    def trial_count(self) -> int:
        """The number of registered trials -- the DSR's ``N``."""
        return len(self.trials())

    def names(self) -> set[str]:
        return {trial.name for trial in self.trials()}

    # --- writing -----------------------------------------------------------

    def record(
        self,
        *,
        name: str,
        config: dict | None = None,
        oos_returns: Sequence[float] = (),
    ) -> Trial:
        """Register one trial.

        The name must be new: a configuration is registered **once**, before
        its result is inspected, and re-registering it would silently
        change ``N``.
        """
        if name in self.names():
            raise ValueError(
                f"the trial {name!r} is already registered; the registry is write-once"
            )
        trial = Trial(
            name=name,
            config=dict(config or {}),
            oos_returns=list(oos_returns),
            index=self.trial_count(),
        )
        line = json.dumps(
            {
                "index": trial.index,
                "name": trial.name,
                "config": trial.config,
                "oos_returns": trial.oos_returns,
            },
            sort_keys=True,
        )
        # Append and flush: the ledger must survive a crash, because a
        # half-registered trial is a trial nobody counted.
        with self.ledger_path.open("at", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return trial

    # --- the statistics the DSR needs --------------------------------------

    def trial_statistics(self) -> dict[str, float]:
        """The skewness, kurtosis and Sharpe variance of the trial series.

        These are three of the five inputs L4 §F.5 says the registry must
        make knowable: the number of trials, the skewness and kurtosis of
        the trial return series, and the variance of the trial Sharpes.
        """
        trials = self.trials()
        sharpes = [t.sharpe for t in trials]
        finite = np.asarray([s for s in sharpes if np.isfinite(s)], dtype=np.float64)
        skew = kurt = sharpe_var = float("nan")
        if finite.shape[0] >= 3:
            sd = float(finite.std(ddof=1))
            if sd > 0:
                skew = float(((finite - finite.mean()) ** 3).mean() / sd**3)
                kurt = float(((finite - finite.mean()) ** 4).mean() / sd**4)
            sharpe_var = float(finite.var(ddof=1))
        return {
            "n_trials": len(trials),
            "trial_sharpe_mean": float(finite.mean()) if finite.size else float("nan"),
            "trial_sharpe_variance": sharpe_var,
            "trial_skew": skew,
            "trial_kurtosis": kurt,
        }

    def to_parquet(self, path: str | Path | None = None) -> Path:
        """Write the derived Parquet artefact (the audit's file name)."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        trials = self.trials()
        target = Path(path) if path is not None else self.root / "registry.parquet"
        table = pa.table(
            {
                "index": pa.array([t.index for t in trials], pa.int64()),
                "name": pa.array([t.name for t in trials], pa.string()),
                "sharpe": pa.array([t.sharpe for t in trials], pa.float64()),
                "n_trades": pa.array([t.n_trades for t in trials], pa.int64()),
                "oos_returns": pa.array(
                    [t.oos_returns for t in trials], pa.list_(pa.float64())
                ),
                # the D4 accounting statement travels with the artefact
                "accounting_statement": pa.array(
                    [ACCOUNTING_STATEMENT] * len(trials), pa.string()
                ),
                "config": pa.array(
                    [json.dumps(t.config, sort_keys=True) for t in trials], pa.string()
                ),
            }
        )
        pq.write_table(table, target)
        return target
