"""The per-fold report (L4 §F.2) and the five per-fold assertions (L5 §D.5).

L4 §F.2 specifies what every fold must write; L5 §D.5 specifies what the
backtest must **assert** on every fold, and says that *a failure must abort
the run, not be logged and ignored*.

The two live together in one module because they are the two halves of the
same obligation: a fold's report is only trustworthy if the assertions ran.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from dodgys_dd_quant.backtest.accounting import ACCOUNTING_STATEMENT

__all__ = [
    "FOLD_ASSERTIONS",
    "FOLD_REPORT_FIELDS",
    "FoldAssertionError",
    "assert_fold",
    "fold_report_row",
]


class FoldAssertionError(RuntimeError):
    """Raised when one of the five per-fold assertions fails.

    It aborts the run: L5 §D.5 is explicit that a failed assertion must
    never be logged and ignored.
    """


#: The fields every fold must write (L4 §F.2).
#:
#: The names are the audit's own, so the report and the audit speak the
#: same language: ``PF``, ``PF_net``, ``expectancy_R_gross``,
#: ``expectancy_R_net``, ``max_drawdown_R``, ``cost_R``.
FOLD_REPORT_FIELDS: tuple[str, ...] = (
    "fold",
    "train_start",
    "train_end",
    "valid_start",
    "valid_end",
    "test_start",
    "test_end",
    "asof",
    "n_candidates",
    "n_candidates_labeled",
    "n_censored",
    "base_rate",
    "n_trades",
    "n_trades_kept",
    "kept_fraction",
    "win_rate",
    "expectancy_R_gross",
    "expectancy_R_net",
    "PF",
    "PF_net",
    "max_drawdown_R",
    "max_consecutive_losses",
    "auc_test",
    "accuracy_test",
    "brier_score",
    "feature_importances_top10",
    "p_pred_distribution",
    "p_pred_distribution_train",
    "cost_R",
    "n_roll_boundary_bars_excluded",
    "ci95_lo",
    "ci95_hi",
    #: The D4 accounting statement: a fold row is a headline number, so it
    #: says which arm it came from (an extension of L4 §F.2's field set).
    "accounting_statement",
)


def fold_report_row(
    *,
    fold_index: int,
    windows: Mapping[str, str],
    asof: str,
    n_candidates: int,
    n_candidates_labeled: int,
    n_censored: int,
    n_trades: int,
    n_trades_kept: int,
    win_rate: float,
    expectancy_r_gross: float,
    expectancy_r_net: float,
    pf: float,
    pf_net: float,
    max_drawdown_r: float,
    max_consecutive_losses: int,
    auc_test: float,
    accuracy_test: float,
    brier_score: float,
    p_pred_distribution: Sequence[float],
    p_pred_distribution_train: Sequence[float],
    cost_r: float,
    n_roll_boundary_bars_excluded: int,
    base_rate: float | None = None,
    ci95_lo: float = float("nan"),
    ci95_hi: float = float("nan"),
    feature_importances_top10: Sequence[tuple[str, float]] = (),
) -> dict[str, Any]:
    """Build one row of the per-fold report.

    The derived fields are computed here rather than passed in, so a row
    cannot claim a ``kept_fraction`` that disagrees with its own counts:
    ``base_rate`` is the label base rate of the fold (never assumed
    constant across folds) and ``kept_fraction`` is the funnel's ratio.
    """
    kept_fraction = (n_trades_kept / n_trades) if n_trades else float("nan")
    row: dict[str, Any] = {
        "fold": int(fold_index),
        "train_start": windows.get("train_start", ""),
        "train_end": windows.get("train_end", ""),
        "valid_start": windows.get("valid_start", ""),
        "valid_end": windows.get("valid_end", ""),
        "test_start": windows.get("test_start", ""),
        "test_end": windows.get("test_end", ""),
        "asof": asof,
        "n_candidates": int(n_candidates),
        "n_candidates_labeled": int(n_candidates_labeled),
        "n_censored": int(n_censored),
        "base_rate": float(base_rate) if base_rate is not None else float("nan"),
        "n_trades": int(n_trades),
        "n_trades_kept": int(n_trades_kept),
        "kept_fraction": kept_fraction,
        "win_rate": float(win_rate),
        "expectancy_R_gross": float(expectancy_r_gross),
        "expectancy_R_net": float(expectancy_r_net),
        "PF": float(pf),
        "PF_net": float(pf_net),
        "max_drawdown_R": float(max_drawdown_r),
        "max_consecutive_losses": int(max_consecutive_losses),
        "auc_test": float(auc_test),
        "accuracy_test": float(accuracy_test),
        "brier_score": float(brier_score),
        "feature_importances_top10": list(feature_importances_top10),
        "p_pred_distribution": list(p_pred_distribution),
        "p_pred_distribution_train": list(p_pred_distribution_train),
        "cost_R": float(cost_r),
        "n_roll_boundary_bars_excluded": int(n_roll_boundary_bars_excluded),
        "ci95_lo": float(ci95_lo),
        "ci95_hi": float(ci95_hi),
        "accounting_statement": ACCOUNTING_STATEMENT,
    }
    missing = [name for name in FOLD_REPORT_FIELDS if name not in row]
    if missing:  # pragma: no cover - a programming error, not a data error
        raise ValueError(f"the fold report is missing field(s): {missing}")
    return row


# ---------------------------------------------------------------------------
# The five assertions (L5 §D.5)
# ---------------------------------------------------------------------------

#: The five assertions every fold of every backtest must make.
FOLD_ASSERTIONS: tuple[str, ...] = (
    "forward_only",
    "exactly_one_fold",
    "not_inside_own_span",
    "metadata_agrees",
    "never_saw_test_month",
)


def assert_fold(
    fold,
    *,
    rows_ts: Sequence[int],
    next_asof_ns: int | None = None,
    backtest_feature_list: Sequence[str] | None = None,
) -> None:
    """Make the five assertions of L5 §D.5 on one fold.

    Parameters
    ----------
    fold:
        The fold.  It is duck-typed -- it needs ``asof``, ``asof_ns``,
        ``meta`` and (for assertion 3) the fold's own test window.
    rows_ts:
        The event timestamps of the candidates this fold decided.
    next_asof_ns:
        The next fold's asof, or ``None`` for the last fold.  It is the
        upper bound of the window in which this fold's model is in force.
    backtest_feature_list:
        The feature list the backtest built.  Assertion (4) compares it
        with the artefact's own, so feature drift between training and
        testing is caught.

    Raises
    ------
    FoldAssertionError
        On the first failed assertion.  The run aborts.
    """
    ts = [int(t) for t in rows_ts]
    meta = dict(getattr(fold, "meta", None) or {})

    # (1) forward-only: the model was live strictly before the decision.
    boundary = int(getattr(fold, "asof_ns", 0))
    model_asof = meta.get("asof")
    if model_asof:
        boundary = max(boundary, _date_to_ns(str(model_asof)))
    if ts and min(ts) <= boundary:
        raise FoldAssertionError(
            f"forward_only: a candidate at ts_event={min(ts)} was decided by a "
            f"model whose boundary is {boundary}"
        )

    # (2) every candidate is decided by exactly one fold, the most recent one.
    if ts and next_asof_ns is not None and max(ts) >= int(next_asof_ns):
        raise FoldAssertionError(
            f"exactly_one_fold: a candidate at ts_event={max(ts)} belongs to the "
            f"next fold (its asof is {int(next_asof_ns)})"
        )

    # (3) no fold may be applied inside its own train/valid/test span.
    test_start = meta.get("test_start") or getattr(fold, "test_start", "")
    if ts and test_start:
        test_start_ns = _date_to_ns(str(test_start))
        inside = [t for t in ts if t < test_start_ns]
        if inside:
            raise FoldAssertionError(
                f"not_inside_own_span: {len(inside)} candidate(s) fall before the "
                f"fold's own test window ({test_start})"
            )

    # (4) the artefact's own metadata agrees with the index.
    if meta.get("asof") is not None and str(meta["asof"]) != str(getattr(fold, "asof", "")):
        raise FoldAssertionError(
            f"metadata_agrees: the artefact says asof={meta['asof']} but the index "
            f"says asof={getattr(fold, 'asof', '')}"
        )
    if backtest_feature_list is not None:
        artefact_features = meta.get("feature_list")
        if artefact_features is not None and list(artefact_features) != list(
            backtest_feature_list
        ):
            raise FoldAssertionError(
                "metadata_agrees: feature drift -- the artefact was trained on "
                f"{list(artefact_features)} but the backtest builds "
                f"{list(backtest_feature_list)}"
            )

    # (5) the model never saw the test month.
    max_ts_read = meta.get("max_ts_read")
    if max_ts_read is not None and test_start:
        if int(max_ts_read) >= _date_to_ns(str(test_start)):
            raise FoldAssertionError(
                f"never_saw_test_month: the model read up to ts={int(max_ts_read)}, "
                f"which is inside the test window ({test_start})"
            )


def _date_to_ns(text: str) -> int:
    """``YYYY-MM-DD`` -> nanoseconds since the epoch (UTC midnight)."""
    import datetime as _dt

    y, m, d = (int(x) for x in str(text).split("-")[:3])
    return int(
        _dt.datetime(y, m, d, tzinfo=_dt.timezone.utc).timestamp() * 1_000_000_000
    )
