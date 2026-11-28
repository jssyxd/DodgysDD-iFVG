"""Purged walk-forward splits with an embargo.

The geometry is fixed by ``RULE_SPEC`` **T24** / **T25**:

    6 months train / 1 month validate / 1 month test, rolled **monthly**.

Two protections are applied on top of the plain calendar windows:

**Purge.**  A training sample may not *overlap* the validation or the test
window in time.  A sample's label is only known once its trade has resolved,
so the sample owns the time span ``[ts_event, ts_event + horizon]``.  A
training sample is therefore kept only when

    ts_event + horizon <= train_end

i.e. its whole label window lies inside the training window.  The same rule is
applied to the *validation* tail, because early stopping on the validation fold
is a model-selection decision: a validation label that was resolved with bars
from the test window would leak test information into the model.

**Embargo.**  A gap of ``embargo_minutes`` separates the end of the training
window from the start of the validation/test window.  The embargo must be at
least the **maximum holding period** of the strategy, which is derived from the
label construction (``labels.max_holding_minutes``) and never assumed here.

The fold windows tile: with a one-month step and a one-month test window the
test windows are consecutive, so the out-of-sample predictions can be
concatenated into one continuous series (the ``qlib`` concept D7 asks to
reimplement rather than adopt).

There is a second planner, :func:`make_folds_days`, which cuts the same
sample on **calendar-day** boundaries instead of calendar months: train on
the previous 15 days, validate on the 15 days after that, trade the next 30
days, stepping forward 30 days per fold.  It carries the identical purge,
embargo and forward-only contracts; only the geometry changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dodgys_dd_quant.ml_pipeline import (
    DEFAULT_BAR_INTERVAL_MINUTES,
    FOLD_STEP_MONTHS,
    TEST_MONTHS,
    TRAIN_MONTHS,
    VALID_MONTHS,
)
from dodgys_dd_quant.ml_pipeline.labels import max_holding_minutes

__all__ = ["Fold", "make_folds", "make_folds_days", "fold_plan"]

# ---------------------------------------------------------------------------
# The day-based walk-forward geometry (the operator's scheme): train on the
# previous 15 days, validate on the 15 days after that, trade the next 30 days,
# stepping forward 30 days per fold.  A day boundary is midnight UTC.
# ---------------------------------------------------------------------------
TRAIN_DAYS = 15
VALID_DAYS = 15
TEST_DAYS = 30
FOLD_STEP_DAYS = 30


@dataclass(frozen=True)
class Fold:
    """One walk-forward fold with explicit index sets."""

    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    embargo_minutes: int
    horizon_minutes: int
    train_idx: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0, dtype=np.int64))
    valid_idx: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0, dtype=np.int64))
    test_idx: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0, dtype=np.int64))
    purged_train: int = 0
    purged_valid: int = 0
    #: The explicit asof boundary.  ``None`` -> the end of the validation
    #: window (the monthly convention of RULE_SPEC T24/T25).  The day-based
    #: planner sets it to the **last calendar day before the test window**,
    #: because a day boundary is midnight UTC: the model may know the
    #: validation days, and the test window opens on the next midnight.
    asof_boundary: pd.Timestamp | None = None

    @property
    def asof(self) -> pd.Timestamp:
        """The date from which this fold's model may be used (D3 forward-only rule).
        It is the **end of the validation window** (= the start of the test
        window), not the end of the training window: the early-stopping
        decision was taken on the validation labels, so the model must not be
        applied to trades inside that window.  With this choice the folds
        tile exactly -- fold *i*'s model is in force over fold *i*'s test
        window, and fold *i+1*'s over the next one.

        The day-based planner overrides it with the last **calendar day**
        before the test window (see ``asof_boundary``); the two conventions
        describe the same boundary, one as an instant and one as a day.
        """
        if self.asof_boundary is not None:
            return self.asof_boundary
        return self.valid_end

    @property
    def asof_ns(self) -> int:
        """``asof`` in nanoseconds since the epoch: the **start of the asof
        day** (UTC midnight), which is the convention the D3 consumer
        (``backtest.walk_forward``) applies to the artefact's ``asof`` date.
        """
        return int(self.asof.floor("D").value)

    @property
    def asof_compact(self) -> str:
        """``asof`` in the ``YYYYMMDD`` form used by the artefact directory."""
        return self.asof.strftime("%Y%m%d")

    def to_dict(self) -> dict:
        """JSON-serialisable description of the fold (no index sets)."""
        return {
            "index": self.index,
            "asof": self.asof.strftime("%Y-%m-%d"),
            "train_start": self.train_start.strftime("%Y-%m-%d"),
            "train_end": self.train_end.strftime("%Y-%m-%d"),
            "valid_start": self.valid_start.strftime("%Y-%m-%d"),
            "valid_end": self.valid_end.strftime("%Y-%m-%d"),
            "test_start": self.test_start.strftime("%Y-%m-%d"),
            "test_end": self.test_end.strftime("%Y-%m-%d"),
            "embargo_minutes": self.embargo_minutes,
            "horizon_minutes": self.horizon_minutes,
            "n_train": int(self.train_idx.size),
            "n_valid": int(self.valid_idx.size),
            "n_test": int(self.test_idx.size),
            "purged_train": int(self.purged_train),
            "purged_valid": int(self.purged_valid),
        }


def _month_start(ts: pd.Timestamp) -> pd.Timestamp:
    """UTC month start of ``ts``."""
    return pd.Timestamp(year=ts.year, month=ts.month, day=1, tz="UTC")


def _add_months(ts: pd.Timestamp, months: int) -> pd.Timestamp:
    """Add whole months, keeping the day (1) and the time of day of ``ts``.

    The time of day matters: the embargo shifts the window start away from
    midnight, and dropping it would silently shorten the validation window.
    """
    total = ts.year * 12 + (ts.month - 1) + months
    year, month0 = divmod(total, 12)
    return ts.replace(year=int(year), month=int(month0) + 1, day=1)


def _window_indices(
    ts_sorted: np.ndarray,
    order: np.ndarray,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> np.ndarray:
    """Positional indices (into the *original* frame) of ``ts`` inside [start, end)."""
    lo = int(np.searchsorted(ts_sorted, start.value, side="left"))
    hi = int(np.searchsorted(ts_sorted, end.value, side="left"))
    if hi <= lo:
        return np.empty(0, dtype=np.int64)
    return np.sort(order[lo:hi]).astype(np.int64)


def make_folds(
    candidates: pd.DataFrame,
    *,
    train_months: int = TRAIN_MONTHS,
    valid_months: int = VALID_MONTHS,
    test_months: int = TEST_MONTHS,
    step_months: int = FOLD_STEP_MONTHS,
    embargo_minutes: int | None = None,
    bar_interval_minutes: int = DEFAULT_BAR_INTERVAL_MINUTES,
) -> list[Fold]:
    """Build the rolling, purged, embargoed walk-forward folds.

    Parameters
    ----------
    candidates:
        The candidate log (or the labelled frame).  Only ``ts_event`` is used
        for the split; the index sets are **positional indices into this
        frame**, so the caller can slice it directly.
    train_months, valid_months, test_months, step_months:
        The calendar geometry (defaults 6 / 1 / 1 / 1).
    embargo_minutes:
        The gap between the end of the training window and the start of the
        validation window.  ``None`` -> the maximum holding period derived from
        the label construction.  A smaller value is **rejected**: it would let a
        training label resolve inside the validation window.
    bar_interval_minutes:
        The bar spacing of the traded series, used to convert the holding
        period into minutes.

    Returns
    -------
    A list of ``Fold`` objects, oldest first.
    """
    if "ts_event" not in candidates.columns:
        raise ValueError("candidates must carry a 'ts_event' column")
    if train_months <= 0 or valid_months <= 0 or test_months <= 0 or step_months <= 0:
        raise ValueError("train/valid/test/step months must all be positive")

    horizon_minutes = max_holding_minutes(bar_interval_minutes)
    if embargo_minutes is None:
        embargo_minutes = horizon_minutes
    embargo_minutes = int(embargo_minutes)
    if embargo_minutes < horizon_minutes:
        raise ValueError(
            f"embargo_minutes={embargo_minutes} is smaller than the maximum holding "
            f"period ({horizon_minutes} min = {horizon_minutes // max(1, bar_interval_minutes)} "
            f"bars). The embargo must be at least the maximum holding period, otherwise a "
            "training label can resolve inside the validation window."
        )

    ts = candidates["ts_event"].astype("int64").to_numpy()
    if ts.size == 0:
        return []
    order = np.argsort(ts, kind="stable")
    ts_sorted = ts[order]

    data_start = pd.Timestamp(int(ts_sorted[0]), unit="ns", tz="UTC")
    data_end = pd.Timestamp(int(ts_sorted[-1]), unit="ns", tz="UTC")
    anchor = _month_start(data_start)

    horizon_ns = horizon_minutes * 60 * 1_000_000_000
    embargo = pd.Timedelta(minutes=embargo_minutes)

    folds: list[Fold] = []
    k = 0
    while True:
        train_start = _add_months(anchor, k * step_months)
        train_end = _add_months(anchor, k * step_months + train_months)
        valid_start = train_end + embargo
        valid_end = _add_months(valid_start, valid_months)
        test_start = valid_end
        test_end = _add_months(test_start, test_months)
        if test_start >= data_end:
            break

        train_idx = _window_indices(ts_sorted, order, train_start, train_end)
        valid_idx = _window_indices(ts_sorted, order, valid_start, valid_end)
        test_idx = _window_indices(ts_sorted, order, test_start, test_end)

        # --- purge: a sample's label window must stay inside its own window
        purged_train = 0
        if train_idx.size:
            keep = ts[train_idx] + horizon_ns <= train_end.value
            purged_train = int((~keep).sum())
            train_idx = train_idx[keep]
        purged_valid = 0
        if valid_idx.size:
            keep = ts[valid_idx] + horizon_ns <= valid_end.value
            purged_valid = int((~keep).sum())
            valid_idx = valid_idx[keep]

        folds.append(
            Fold(
                index=k,
                train_start=train_start,
                train_end=train_end,
                valid_start=valid_start,
                valid_end=valid_end,
                test_start=test_start,
                test_end=test_end,
                embargo_minutes=embargo_minutes,
                horizon_minutes=horizon_minutes,
                train_idx=train_idx,
                valid_idx=valid_idx,
                test_idx=test_idx,
                purged_train=purged_train,
                purged_valid=purged_valid,
            )
        )
        k += 1
    return folds


def make_folds_days(
    candidates: pd.DataFrame,
    *,
    train_days: int = TRAIN_DAYS,
    valid_days: int = VALID_DAYS,
    test_days: int = TEST_DAYS,
    step_days: int = FOLD_STEP_DAYS,
    embargo_minutes: int | None = None,
    bar_interval_minutes: int = DEFAULT_BAR_INTERVAL_MINUTES,
) -> list[Fold]:
    """Build the rolling, purged, embargoed walk-forward folds on **day** boundaries.

    The monthly planner (:func:`make_folds`) cuts the sample into calendar
    months; this one cuts it into calendar **days**.  A day boundary is
    midnight UTC and the day index of a candidate is the UTC day of its
    ``ts_event``.

    The geometry mirrors :func:`make_folds` exactly:

    * train on the previous ``train_days`` days,
    * validate on the ``valid_days`` days after that,
    * trade the next ``test_days`` days,
    * and step forward ``step_days`` days per fold.

    The two protections are the same contracts as in the monthly scheme.

    **Purge.**  A sample is kept only when its whole label window lies inside
    its own window (``ts_event + horizon <= window_end``) -- for the training
    *and* for the validation fold, because early stopping on the validation
    labels is a model-selection decision.

    **Embargo.**  ``embargo_minutes`` separates the end of the training window
    from the start of the validation window.  It defaults to the maximum
    holding period (``labels.max_holding_minutes``) and a **smaller value is
    rejected**: a training label could then resolve inside the validation
    window.  The embargo is paid for by the *tail* of the training window, so
    the validation and the test windows keep their exact day counts.

    A fold whose training window holds no usable row is **skipped** (it could
    not produce a model), and the test windows of the emitted folds never
    overlap: ``step_days`` must be at least ``test_days``.

    Returns
    -------
    A list of ``Fold`` objects, oldest first.
    """
    if "ts_event" not in candidates.columns:
        raise ValueError("candidates must carry a 'ts_event' column")
    if train_days <= 0 or valid_days <= 0 or test_days <= 0 or step_days <= 0:
        raise ValueError("train/valid/test/step days must all be positive")
    if step_days < test_days:
        raise ValueError(
            f"step_days={step_days} is smaller than test_days={test_days}: the "
            "out-of-sample test windows would overlap, so the OOS predictions "
            "could not be concatenated into one continuous series"
        )

    horizon_minutes = max_holding_minutes(bar_interval_minutes)
    if embargo_minutes is None:
        embargo_minutes = horizon_minutes
    embargo_minutes = int(embargo_minutes)
    if embargo_minutes < horizon_minutes:
        raise ValueError(
            f"embargo_minutes={embargo_minutes} is smaller than the maximum holding "
            f"period ({horizon_minutes} min = {horizon_minutes // max(1, bar_interval_minutes)} "
            f"bars). The embargo must be at least the maximum holding period, otherwise a "
            "training label can resolve inside the validation window."
        )

    ts = candidates["ts_event"].astype("int64").to_numpy()
    if ts.size == 0:
        return []
    order = np.argsort(ts, kind="stable")
    ts_sorted = ts[order]

    data_start = pd.Timestamp(int(ts_sorted[0]), unit="ns", tz="UTC")
    data_end = pd.Timestamp(int(ts_sorted[-1]), unit="ns", tz="UTC")
    anchor = data_start.floor("D")  # midnight UTC of the first candidate's day

    horizon_ns = horizon_minutes * 60 * 1_000_000_000
    embargo = pd.Timedelta(minutes=embargo_minutes)

    folds: list[Fold] = []
    k = 0
    while True:
        train_start = anchor + pd.Timedelta(days=k * step_days)
        valid_start = train_start + pd.Timedelta(days=train_days)
        valid_end = valid_start + pd.Timedelta(days=valid_days)
        test_start = valid_end
        test_end = test_start + pd.Timedelta(days=test_days)
        if test_start >= data_end:
            break
        # the embargo is the gap between the end of the training window and the
        # start of the validation window: the training window gives up its tail
        train_end = valid_start - embargo

        train_idx = _window_indices(ts_sorted, order, train_start, train_end)
        valid_idx = _window_indices(ts_sorted, order, valid_start, valid_end)
        test_idx = _window_indices(ts_sorted, order, test_start, test_end)

        # --- purge: a sample's label window must stay inside its own window
        purged_train = 0
        if train_idx.size:
            keep = ts[train_idx] + horizon_ns <= train_end.value
            purged_train = int((~keep).sum())
            train_idx = train_idx[keep]
        purged_valid = 0
        if valid_idx.size:
            keep = ts[valid_idx] + horizon_ns <= valid_end.value
            purged_valid = int((~keep).sum())
            valid_idx = valid_idx[keep]

        index = k
        k += 1
        if train_idx.size == 0:
            # a fold without usable training rows cannot produce a model
            continue

        folds.append(
            Fold(
                index=index,
                train_start=train_start,
                train_end=train_end,
                valid_start=valid_start,
                valid_end=valid_end,
                test_start=test_start,
                test_end=test_end,
                embargo_minutes=embargo_minutes,
                horizon_minutes=horizon_minutes,
                train_idx=train_idx,
                valid_idx=valid_idx,
                test_idx=test_idx,
                purged_train=purged_train,
                purged_valid=purged_valid,
                # the model may know the validation days; the test window
                # opens on the next midnight, so the last known day is the one
                # before it
                asof_boundary=test_start - pd.Timedelta(days=1),
            )
        )
    return folds


def fold_plan(folds: list[Fold]) -> list[dict]:
    """JSON-serialisable description of the whole fold plan."""
    return [fold.to_dict() for fold in folds]
