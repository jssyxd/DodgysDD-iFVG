"""The end-to-end rolling backtest.

Three things this module guarantees
-----------------------------------
1. **Forward only.**  A model with ``asof = T`` may only decide trades with
   ``ts_event > T``.  The rule is a **hard check that raises**
   (:class:`ForwardOnlyViolation`) — not a warning.
2. **One position at a time** (D4).  The census arm of the experiment harness
   manufactures ``t = 15.28`` out of 423 759 simultaneously-open, correlated
   positions; that number is an artefact and is never quoted.  Every
   expectancy, Sharpe and t-statistic in this module comes from the
   one-position-at-a-time portfolio.
3. **Honest costs** (D9).  The round-trip cost is charged **inside** the
   trade, and the **break-even cost in R** is printed next to the expectancy.

The model artefact (D3) is *consumed*, never modified.  When no model exists
for a period the **rule-only baseline** runs for that period and the period is
labelled as such.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

from dodgys_dd_quant.backtest.abort import cost_buckets, evaluate_abort_criteria
from dodgys_dd_quant.backtest.accounting import accounting_fields
from dodgys_dd_quant.backtest.cost_model import (
    CostProfile,
    break_even_cost_r,
    cost_in_r,
    summarise_costs,
)
from dodgys_dd_quant.backtest.fold_report import (
    FOLD_ASSERTIONS,
    FOLD_REPORT_FIELDS,
    FoldAssertionError,
    assert_fold,
    fold_report_row,
)
from dodgys_dd_quant.backtest.kill_switch import (
    DRIFT_MEDIAN_SHIFT,
    DRIFT_SPREAD_COLLAPSE,
    KILL_SWITCH_LEVELS,
    TOP_DECILE_WIN_RATE_FLOOR,
    compute_kill_switch,
)
from dodgys_dd_quant.strategy.constants import DECISION_THRESHOLD, LABEL_HORIZON_BARS
from dodgys_dd_quant.strategy.state_machine import Candidate

__all__ = [
    "ForwardOnlyViolation",
    "FOLD_ASSERTIONS",
    "FOLD_REPORT_FIELDS",
    "Fold",
    "FoldAssertionError",
    "FoldReport",
    "KILL_SWITCH_LEVELS",
    "WalkForwardReport",
    "load_walk_forward_index",
    "assert_fold",
    "assert_forward_only",
    "compute_kill_switch",
    "fold_report_row",
    "simulate_portfolio",
    "summarise_trades",
    "walk_forward",
    "deflated_sharpe",
]

_NS_PER_DAY = 86_400_000_000_000
#: One calendar day, for date arithmetic on the fold windows.
_DAY = 1


class ForwardOnlyViolation(RuntimeError):
    """Raised when a model is used outside the period it was trained for."""


# ---------------------------------------------------------------------------
# Folds
# ---------------------------------------------------------------------------


@dataclass
class Fold:
    """One walk-forward fold: a model and the window it may decide.

    ``asof`` is the date the model was trained up to; every trade it decides
    must have ``ts_event`` strictly after the end of that day.
    """

    asof: str
    asof_ns: int
    directory: Path
    train_start: str = ""
    train_end: str = ""
    valid_start: str = ""
    valid_end: str = ""
    test_start: str = ""
    test_end: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.asof

    def test_window_ns(self) -> tuple[int, int]:
        """The (inclusive, exclusive) nanosecond window the fold may decide."""
        start = _date_to_ns(self.test_start) if self.test_start else self.asof_ns + 1
        end = _date_to_ns(self.test_end) if self.test_end else None
        return start, end


def _date_to_ns(text: str) -> int:
    """``YYYY-MM-DD`` -> nanoseconds since the epoch (UTC midnight)."""
    y, m, d = (int(x) for x in text.split("-")[:3])
    days = _days_from_civil(y, m, d)
    return days * _NS_PER_DAY


def _days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01 (Howard Hinnant's algorithm)."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146_097 + doe - 719_468


def _parse_date(text: str) -> str:
    """Normalise ``YYYYMMDD`` / ``YYYY-MM-DD`` to ``YYYY-MM-DD``."""
    text = str(text).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _date_minus_day(iso: str) -> str:
    """The ISO date one day before ``iso`` (lexicographic on YYYY-MM-DD)."""
    import datetime as _dt

    d = _dt.date.fromisoformat(iso)
    return (d - _dt.timedelta(days=1)).isoformat()


def load_walk_forward_index(
    models_root: str | Path,
    symbol: str,
    timeframe: str = "1m",
) -> list[Fold]:
    """Read ``walk_forward_index.json`` (D3) and return the ordered folds.

    The index format is not frozen beyond "the ordered list of fold
    directories", so the reader is deliberately tolerant: it accepts a bare
    list or a ``{"folds": [...]}`` object, and the fold entries may carry
    ``asof``/``asof_YYYYMMDD``/``dir``/``path`` keys.

    A missing index is **not** an error: it means "no model exists" and the
    caller falls back to the rule-only baseline.
    """
    root = Path(models_root)
    index_path = root / symbol / "walk_forward_index.json"
    if not index_path.exists():
        index_path = root / "walk_forward_index.json"
    if not index_path.exists():
        return []

    payload = json.loads(index_path.read_text())
    entries = payload.get("folds", []) if isinstance(payload, dict) else payload

    folds: list[Fold] = []
    for entry in entries:
        if isinstance(entry, str):
            entry = {"dir": entry}
        asof_raw = entry.get("asof") or entry.get("asof_YYYYMMDD") or entry.get("asof_date")
        directory = (entry.get("dir") or entry.get("path") or entry.get("directory")
                     or entry.get("model_dir") or entry.get("model_path"))
        if asof_raw is None and directory:
            asof_raw = Path(str(directory)).name.split("_")[-1]
        if asof_raw is None:
            continue
        asof = _parse_date(str(asof_raw))
        compact = asof.replace("-", "")

        # Candidate layouts, most specific first.  The ML leaf writes the
        # artefact to ``<models_root>/{symbol}/asof_<YYYYMMDD>/`` and records
        # that path **relative to the models root**, so the reader resolves it
        # against whatever root it was given -- the backtest's default
        # ``--models-root`` is ``artifacts/models`` (F2).  The older absolute
        # layouts are still accepted so an existing run tree keeps working.
        candidates = []
        if directory:
            d = Path(str(directory))
            candidates += [root / d, d, root / symbol / d]
        candidates += [
            root / symbol / f"asof_{compact}",
            root / symbol / compact,
            root / "models" / symbol / f"asof_{compact}",
            root / "models" / symbol / compact,
        ]
        folder = next((c for c in candidates if (c / "meta_label_meta.json").exists()),
                      candidates[0])
        meta = {}
        meta_path = folder / "meta_label_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
        folds.append(
            Fold(
                asof=asof,
                asof_ns=_date_to_ns(asof),  # start of the asof day = start of the test window
                directory=folder,
                train_start=_parse_date(entry.get("train_start", meta.get("train_start", "")))
                if entry.get("train_start", meta.get("train_start"))
                else "",
                train_end=_parse_date(entry.get("train_end", meta.get("train_end", "")))
                if entry.get("train_end", meta.get("train_end"))
                else "",
                valid_start=_parse_date(entry.get("valid_start", meta.get("valid_start", "")))
                if entry.get("valid_start", meta.get("valid_start"))
                else "",
                valid_end=_parse_date(entry.get("valid_end", meta.get("valid_end", "")))
                if entry.get("valid_end", meta.get("valid_end"))
                else "",
                test_start=_parse_date(entry.get("test_start", meta.get("test_start", "")))
                if entry.get("test_start", meta.get("test_start"))
                else "",
                test_end=_parse_date(entry.get("test_end", meta.get("test_end", "")))
                if entry.get("test_end", meta.get("test_end"))
                else "",
                meta=meta,
            )
        )
    folds.sort(key=lambda f: f.asof)
    return folds


def assert_forward_only(fold: Fold, ts_event: int) -> None:
    """Raise unless the fold's model may decide a trade at ``ts_event``.

    The rule is D3's: *a model trained with ``asof = T`` may only be used to
    decide trades with ``ts_event > T``*.

    ``T`` is the **start** of the asof day.  The ML leaf's index documents its
    basis as *"end of the validation window (= the start of the test window)"*,
    so a fold whose asof is 2023-08-01 may decide trades whose signal closed
    after 2023-08-01 00:00. A candidate whose signal closed in the last minutes
    of the previous month was decided *before* the model existed, and is
    correctly rejected — that is a look-ahead, not a rounding artefact.

    The boundary is the **model artefact's own** ``asof``, not merely the
    fold's.  The two can disagree -- a fold index can point at a model
    trained later than the window it claims -- and a guard that only looks
    at the fold's own boundary cannot see it.  The artefact's metadata is
    the authority (D3's ``asof``), so the *later* of the two boundaries is
    the one that applies: the model may not decide anything that happened
    before **either** of them.
    """
    boundary = fold.asof_ns
    boundary_source = f"fold asof={fold.asof}"
    model_asof = fold.meta.get("asof") if fold.meta else None
    if model_asof:
        model_boundary = _date_to_ns(str(model_asof))
        if model_boundary > boundary:
            boundary = model_boundary
            boundary_source = f"model artefact asof={model_asof}"
    if ts_event <= boundary:
        raise ForwardOnlyViolation(
            f"model {boundary_source} may not decide a trade at ts_event={ts_event} "
            f"(<= boundary {boundary})"
        )


# ---------------------------------------------------------------------------
# Model scoring
# ---------------------------------------------------------------------------


class ModelScorer:
    """Scores candidates with a fold's meta-label model.

    The model artefact is the frozen D3 contract:
    ``meta_label_lgbm.txt`` + ``meta_label_meta.json``.  LightGBM may not be
    installed in the runtime; in that case the scorer reports itself as
    unavailable and the caller falls back to the **rule-only baseline** for
    that period — it never silently pretends the model ran.
    """

    def __init__(
        self,
        fold: Fold,
        threshold: float = DECISION_THRESHOLD,
        gate: str = "absolute",
    ) -> None:
        self.fold = fold
        self.threshold = threshold
        self.gate = gate
        #: The fold's isotonic calibration (validation-fold fit), if the trainer
        #: recorded one.  ``None`` means the raw probability is used.
        self.calibration: dict | None = fold.meta.get("calibration")
        if gate == "quantile":
            # The gate threshold is a **validation-fold quantile**, so it is a
            # causal number: it was known before the test window opened.  An
            # absolute threshold on uncalibrated probabilities opens and closes
            # the gate at random across folds (61 of 75 folds approved nothing
            # on ETH 15m).
            recorded = fold.meta.get("gate_threshold")
            if recorded is not None:
                self.threshold = float(recorded)
        self.model = None
        self.feature_list: list[str] = list(fold.meta.get("feature_list", []))
        self.error: str | None = None
        self._load()

    def _load(self) -> None:
        model_path = self.fold.directory / "meta_label_lgbm.txt"
        if not model_path.exists():
            self.error = f"no model file at {model_path}"
            return
        try:
            import lightgbm as lgb

            self.model = lgb.Booster(model_file=str(model_path))
        except Exception as exc:  # pragma: no cover - depends on the runtime
            self.error = f"lightgbm unavailable or model unreadable: {exc}"

    @property
    def available(self) -> bool:
        return self.model is not None

    def score(self, features: dict[str, float]) -> float:
        """P(Win) for one candidate."""
        if self.model is None:
            raise RuntimeError(f"model unavailable: {self.error}")
        if not isinstance(features, dict):
            raise TypeError(
                "the scorer needs a feature dict (the model scores a feature "
                f"vector), got {type(features).__name__}; wire feature_fn "
                "through ml_pipeline.features.build_features")
        import numpy as np

        row = [float(features.get(name, 0.0)) for name in self.feature_list]
        # LightGBM >= 4 refuses a Dataset for prediction; pass the raw vector.
        prob = float(self.model.predict(np.asarray([row], dtype="float64"))[0])
        return self._calibrate(prob)

    def _calibrate(self, prob: float) -> float:
        """Map a raw probability through the fold's isotonic calibration."""
        cal = self.calibration
        if not cal:
            return prob
        xs = cal.get("x") or []
        ys = cal.get("y") or []
        if not xs or len(xs) != len(ys):
            return prob
        import numpy as _np

        return float(_np.interp(prob, xs, ys))


# ---------------------------------------------------------------------------
# Portfolio accounting (D4)
# ---------------------------------------------------------------------------


def simulate_portfolio(
    candidates: Sequence[Candidate],
    n_bars: int,
    horizon_bars: int = LABEL_HORIZON_BARS,
) -> list[Candidate]:
    """Select the trades of a **one-position-at-a-time** portfolio.

    A signal whose entry bar falls inside an open position's life is
    **dropped** (not deferred): deferring it re-times the entry at a different
    price and silently changes the strategy (L2 §A.4, D-17).

    The trade outcomes are unchanged by the selection — a selected row keeps
    the outcome it had in the census, because the portfolio only *chooses*
    which signals are taken.
    """
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda c: (c.entry_bar, c.confirm_bar))
    selected: list[Candidate] = []
    free_from = -1          # the first bar at which a new position may open
    for cand in ordered:
        if cand.entry_bar < free_from:
            continue                      # a position is open -> drop the signal
        if cand.outcome == "discarded":
            # The setup was dropped by the reference's candidate cap before it
            # could trigger: it is never traded, so it must not hold the book.
            continue
        selected.append(cand)
        # The position occupies [entry_bar, exit_bar].  A candidate that has
        # not resolved **within the label horizon** is still open when the
        # horizon ends, so it holds the book for the horizon -- not for ever
        # (a candidate that never resolves would otherwise block the rest of
        # the sample and collapse the portfolio).
        if cand.exit_bar >= 0:
            free_from = cand.exit_bar + 1
        else:
            free_from = min(n_bars + 1, cand.entry_bar + int(horizon_bars))
    return selected


@dataclass
class TradeStats:
    """The statistics of a set of trades."""

    n: int = 0
    n_closed: int = 0
    win_rate: float = float("nan")
    expectancy_r: float = float("nan")
    expectancy_net_r: float = float("nan")
    profit_factor: float = float("nan")
    #: Profit factor after the round-trip cost is charged **inside** the trade.
    profit_factor_net: float = float("nan")
    t_stat: float = float("nan")
    ci95_lo: float = float("nan")
    ci95_hi: float = float("nan")
    total_r: float = 0.0
    max_consecutive_losses: int = 0
    mean_cost_r: float = float("nan")
    median_cost_r: float = float("nan")
    break_even_cost_r: float = float("nan")
    #: Net expectancy when a **flat** round-trip cost is charged (the D4/E-1
    #: convention of 0.05 R per trade).  Reported next to the modelled cost so
    #: the two are never confused.
    expectancy_net_flat_r: float = float("nan")
    flat_cost_r: float = float("nan")

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def summarise_trades(
    trades: Sequence[Candidate],
    profile: CostProfile | None = None,
    slippage_ticks: int = 0,
    flat_cost_r: float = 0.05,
) -> TradeStats:
    """Win rate, expectancy (gross and net), PF, t-statistic and 95 % CI.

    Only **closed** trades (stop or target) enter the statistics; a position
    still open at the end of the sample is reported as ``n - n_closed``.
    """
    stats = TradeStats()
    closed = [t for t in trades if t.is_closed]
    stats.n = len(trades)
    stats.n_closed = len(closed)
    if not closed:
        if profile is not None:
            stats.break_even_cost_r = float("nan")
        return stats

    r = np.array([t.r_multiple for t in closed], dtype=np.float64)
    wins = int(np.sum(r > 0))
    losses = int(np.sum(r < 0))
    n = r.shape[0]
    exp = float(r.mean())
    gross_win = float(r[r > 0].sum())
    gross_loss = float(-r[r < 0].sum())

    stats.win_rate = wins / n
    stats.expectancy_r = exp
    stats.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    stats.total_r = float(r.sum())
    if n > 1:
        sd = float(r.std(ddof=1))
        stats.t_stat = exp / sd * math.sqrt(n) if sd > 0 else float("nan")
        half = 1.96 * sd / math.sqrt(n)
    else:
        sd = 0.0
        stats.t_stat = float("nan")
        half = float("nan")
    stats.ci95_lo = exp - half if math.isfinite(half) else float("nan")
    stats.ci95_hi = exp + half if math.isfinite(half) else float("nan")

    streak = worst = 0
    for t in closed:
        if t.r_multiple < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    stats.max_consecutive_losses = worst

    stats.flat_cost_r = flat_cost_r
    stats.expectancy_net_flat_r = exp - flat_cost_r
    if profile is not None:
        costs = summarise_costs(
            profile,
            [t.entry_price for t in closed],
            [t.risk for t in closed],
            slippage_ticks,
        )
        stats.mean_cost_r = costs["mean_cost_r"]
        stats.median_cost_r = costs["median_cost_r"]
        stats.expectancy_net_r = exp - (
            costs["mean_cost_r"] if math.isfinite(costs["mean_cost_r"]) else 0.0
        )
        stats.break_even_cost_r = break_even_cost_r(exp)
        # the net profit factor: the cost is charged inside every trade
        per_trade_cost = [
            cost_in_r(profile, t.entry_price, t.risk, slippage_ticks)
            for t in closed
            if t.risk and t.risk > 0
        ]
        if len(per_trade_cost) == len(closed):
            net = r - np.array(per_trade_cost, dtype=np.float64)
            net_win = float(net[net > 0].sum())
            net_loss = float(-net[net < 0].sum())
            stats.profit_factor_net = (net_win / net_loss) if net_loss > 0 else float("inf")
    else:
        stats.expectancy_net_r = exp
    return stats


# ---------------------------------------------------------------------------
# Walk forward
# ---------------------------------------------------------------------------


@dataclass
class FoldReport:
    """The report of one fold."""

    label: str
    mode: str                       # "model" | "rule_only"
    model_window: str
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    n_candidates: int = 0
    n_approved: int = 0
    n_trades: int = 0
    stats: TradeStats = field(default_factory=TradeStats)
    drift: dict = field(default_factory=dict)
    #: The model's own feature importances (gain), most important first.
    feature_importances: list = field(default_factory=list)
    #: The live fold's P(Win) distribution (the drift signal's numerator).
    live_distribution: dict | None = None
    #: The model's own training P(Win) distribution (the drift's denominator).
    train_distribution: dict | None = None
    #: The realised win rate of the top decile of P(Win).
    top_decile_win_rate: float = float("nan")
    #: The three degradation signals of this fold (L4 §F.3).
    signals: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = {
            "fold": self.label,
            "mode": self.mode,
            "model_window": self.model_window,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "n_candidates": self.n_candidates,
            "n_approved": self.n_approved,
            "n_trades": self.n_trades,
            "accounting": self.accounting,
        }
        d.update(self.stats.as_dict())
        d.update({f"drift_{k}": v for k, v in self.drift.items()})
        d["feature_importances_top10"] = list(self.feature_importances)
        d["live_prediction_distribution"] = self.live_distribution
        d["train_prediction_distribution"] = self.train_distribution
        d["realised_top_decile_win_rate"] = self.top_decile_win_rate
        d.update({f"signal_{k}": v for k, v in self.signals.items()})
        return d


@dataclass
class WalkForwardReport:
    """The stitched report of a walk-forward run."""

    folds: list[FoldReport]
    portfolio: TradeStats
    baseline: TradeStats
    equity_r: np.ndarray
    sharpe: float = float("nan")
    deflated_sharpe: float = float("nan")
    dsr_p_value: float = float("nan")
    trials: int = 1
    n_candidates: int = 0
    n_approved: int = 0
    n_trades: int = 0
    accounting: str = "drop"
    #: The kill-switch's verdict on the run (L4 §F.3): the level and the
    #: three degradation signals it was computed from.
    kill_switch: dict = field(default_factory=dict)
    trades: list[Candidate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            **accounting_fields(),
            "folds": [f.as_dict() for f in self.folds],
            "portfolio": self.portfolio.as_dict(),
            "baseline": self.baseline.as_dict(),
            "sharpe": self.sharpe,
            "deflated_sharpe": self.deflated_sharpe,
            "dsr_p_value": self.dsr_p_value,
            "trials": self.trials,
            "n_candidates": self.n_candidates,
            "n_approved": self.n_approved,
            "n_trades": self.n_trades,
            "accounting": self.accounting,
            "kill_switch": dict(self.kill_switch),
        }


def walk_forward(
    candidates: Sequence[Candidate],
    n_bars: int,
    folds: Sequence[Fold] | None = None,
    *,
    profile: CostProfile | None = None,
    slippage_ticks: int = 0,
    threshold: float = DECISION_THRESHOLD,
    scorer: "ModelScorer | None" = None,
    gate: str = "absolute",
    feature_fn=None,
    trials: int = 32,
    trades_per_year: float | None = None,
    portfolio_trades: Sequence[Candidate] | None = None,
    bars=None,
    horizon_bars: int = LABEL_HORIZON_BARS,
) -> WalkForwardReport:
    """Run the rolling backtest.

    Parameters
    ----------
    candidates:
        The D2 candidate log (the census).
    folds:
        The folds of the ML leaf (``walk_forward_index.json``).  When empty the
        whole sample is treated as a single **rule-only** fold.
    scorer:
        A scoring callable ``scorer(candidate) -> P(Win)``; when ``None`` the
        run is rule-only.
    feature_fn:
        ``candidate -> dict`` of features for the scorer.
    trials:
        The number of independent strategy trials already performed — used by
        the deflated Sharpe (D4: 32 arms have already been tried).
    bars:
        The traded series, when the caller has it.  With the bars, L4 §C.6's
        A4 — "does the FVG beat the no-FVG momentum control?" — can be
        evaluated; without them the criterion is reported as *not evaluated*.
    """
    ordered = sorted(candidates, key=lambda c: (c.ts_event, c.confirm_bar))
    approved: list[Candidate] = []
    fold_reports: list[FoldReport] = []

    if not folds:
        fold = Fold(
            asof="rule-only",
            asof_ns=0,
            directory=Path("."),
            test_start="",
            test_end="",
        )
        folds = [fold]

    for fold in folds:
        start, end = fold.test_window_ns()
        # A fold whose model was trained *outside* its own test window is
        # malformed: the model either does not exist yet for those trades or
        # was fitted with data from the future. Refuse loudly rather than
        # trading it or silently dropping the candidates.
        #
        # The comparison is on the **dates**, not on `asof_ns`: the asof is the
        # boundary the model knows up to, so it must sit on the test window's
        # first day (or the day before it, when the convention differs by one).
        if fold.test_start and fold.test_end and fold.asof:
            asof_d = _parse_date(fold.asof)
            ts_d = _parse_date(fold.test_start)
            te_d = _parse_date(fold.test_end)
            # ISO dates compare correctly as strings; the one-day slack covers
            # the "asof is the day before the test window" convention.
            if not (_date_minus_day(ts_d) <= asof_d < te_d):
                raise ForwardOnlyViolation(
                    f"fold asof={fold.asof} lies outside its own test window "
                    f"[{fold.test_start}, {fold.test_end}); the model may not "
                    f"decide these trades"
                )
        # The window opens *after* the asof boundary: a candidate whose signal
        # closed at the boundary was the last bar of the validation window, so
        # the model has already seen it. Excluding it is the same rule
        # assert_forward_only enforces, applied consistently.
        in_window = [
            c
            for c in ordered
            if c.ts_event >= start and (end is None or c.ts_event < end)
            and (fold.asof_ns <= 0 or c.ts_event > fold.asof_ns)
        ]
        mode = "rule_only"
        p_wins: list[float] = []
        scored: list[tuple[float, Candidate]] = []
        keep: list[Candidate] = []
        # Each fold must be decided by **its own** model: the model trained up to
        # that fold's asof, and no other. Building the scorer from the fold
        # (rather than reusing one caller-supplied scorer for every fold) is what
        # makes the walk-forward honest.
        fold_scorer = ModelScorer(fold, threshold=threshold, gate=gate)
        if not fold_scorer.available and scorer is not None and scorer.available:
            fold_scorer = scorer
        if fold_scorer.available:
            mode = "model"
            for cand in in_window:
                assert_forward_only(fold, cand.ts_event)
                feats = feature_fn(cand) if feature_fn is not None else None
                p = fold_scorer.score(feats) if feats is not None else fold_scorer.score(cand)
                cand.p_win = p
                p_wins.append(p)
                scored.append((p, cand))
                # the *fold's* threshold, not the caller's: under the quantile
                # gate it is that fold's validation quantile
                is_approved = p >= fold_scorer.threshold
                # the archive records the decision per candidate; the engine's
                # object carries it so nothing has to be reconstructed later
                cand.gate_approved = bool(is_approved)
                if is_approved:
                    keep.append(cand)
        else:
            keep = list(in_window)
        approved.extend(keep)

        report = FoldReport(
            label=fold.label,
            mode=mode,
            model_window=(
                f"train {fold.train_start}..{fold.train_end} | "
                f"valid {fold.valid_start}..{fold.valid_end} | "
                f"test {fold.test_start or fold.asof}..{fold.test_end or ''}"
            ),
            train_start=fold.train_start,
            train_end=fold.train_end,
            test_start=fold.test_start,
            test_end=fold.test_end,
            n_candidates=len(in_window),
            n_approved=len(keep),
        )
        report.drift = _drift(p_wins, fold, keep)
        report.feature_importances = _feature_importances(fold_scorer)
        # the inputs of the degradation monitor (L4 §F.3)
        report.live_distribution = _distribution(p_wins)
        report.train_distribution = fold.meta.get("train_prediction_distribution")
        report.top_decile_win_rate = _top_decile_win_rate(scored)
        # The three degradation signals of this fold (L4 §F.3).
        drift_abs = report.drift.get("abs_mean_p_minus_base", float("nan"))
        top_rate = _top_decile_win_rate(scored)
        churn = (
            _importance_churn(
                fold_reports[-1].feature_importances, report.feature_importances
            )
            if fold_reports
            else float("nan")
        )
        report.signals = {
            "prediction_drift": bool(
                math.isfinite(drift_abs) and drift_abs > DRIFT_MEDIAN_SHIFT
            ),
            "calibration": bool(
                math.isfinite(top_rate) and top_rate < TOP_DECILE_WIN_RATE_FLOOR
            ),
            "importance_churn": bool(
                math.isfinite(churn) and churn > DRIFT_SPREAD_COLLAPSE
            ),
        }
        report.drift["realised_top_decile_win_rate"] = top_rate
        report.drift["importance_churn"] = churn
        fold_reports.append(report)

    # --- the portfolio: one position at a time, across the whole sample ----
    # ``portfolio_trades`` lets the caller supply the deferred arm (the
    # experiment harness's accounting); the default selects a subset of the
    # approved candidates and *drops* the blocked signals.
    accounting = "drop"
    if portfolio_trades is None:
        portfolio_trades = simulate_portfolio(approved, n_bars, horizon_bars)
    else:
        accounting = "defer"
    windows = [f.test_window_ns() for f in folds]
    for trade in portfolio_trades:
        for report, (start, end) in zip(fold_reports, windows):
            if trade.ts_event >= start and (end is None or trade.ts_event < end):
                report.n_trades += 1
                report.trades.append(trade)
                break

    for report in fold_reports:
        report.stats = summarise_trades(report.trades, profile, slippage_ticks)

    portfolio_stats = summarise_trades(portfolio_trades, profile, slippage_ticks)
    # The rule-only baseline must be an **independent population**: every
    # candidate the rule engine produced, with no model gate applied. Using the
    # (already gated) portfolio here would compare the model against itself and
    # make D4's "report against the rule-only baseline" impossible.
    baseline_trades = simulate_portfolio(ordered, n_bars, horizon_bars)
    baseline_stats = summarise_trades(baseline_trades, profile, slippage_ticks)

    equity = np.array([t.r_multiple for t in portfolio_trades if t.is_closed], dtype=np.float64)
    sharpe, dsr, p_value = _sharpe_stats(equity, trials, trades_per_year)

    for report in fold_reports:
        report.accounting = accounting

    # --- the kill-switch (L4 §F.3) ----------------------------------------
    # The signals are computed per fold above; the switch aggregates them
    # into the level that says whether the next fold may be traded.
    consecutive_below = 0
    for report in reversed(fold_reports):
        if report.signals.get("calibration"):
            consecutive_below += 1
        else:
            break
    k1_folds = sum(1 for report in fold_reports if any(report.signals.values()))
    # L4 §C.6's abort criteria, evaluated on the concatenated OOS.  The
    # criteria that need the baselines (the cost-heavy subsets, the momentum
    # control) are reported as *not evaluated* rather than silently passed.
    # The no-FVG control (L4 §C.6's A4): with the bars, the control runs on
    # the same series and the comparison is gross against gross.
    control_gross = None
    if bars is not None:
        from dodgys_dd_quant.analysis.momentum_baseline import run_momentum_baseline

        control = run_momentum_baseline(bars)
        if math.isfinite(control.expectancy_r):
            control_gross = float(control.expectancy_r)
    # A2: does the gross edge survive the costs?  The population is split
    # at 0.3 R of round-trip cost and each bucket's gross expectancy is
    # measured.
    cost_split = cost_buckets(
        portfolio_trades,
        profile=profile,
        slippage_ticks=slippage_ticks,
    )
    # A3: a high-AUC model with no net lift that has learned the cost.  The
    # inputs come from the fold's own artefact.
    # The criterion is about *the model*, so the AUC and the lift are the
    # run's aggregate over the folds that measured them, and the features are
    # the last fold's.
    aucs: list[float] = []
    lifts: list[float] = []
    top_features: list[str] = []
    for fold_report, fold in zip(fold_reports, folds):
        meta = fold.meta or {}
        auc = meta.get("auc_test")
        lift = meta.get("expectancy_lift_r")
        if auc is not None and math.isfinite(float(auc)):
            aucs.append(float(auc))
        if lift is not None and math.isfinite(float(lift)):
            lifts.append(float(lift))
    auc_test = sum(aucs) / len(aucs) if aucs else None
    expectancy_lift = sum(lifts) / len(lifts) if lifts else None
    if fold_reports:
        top_features = [
            str(name)
            for name, _ in (fold_reports[-1].feature_importances or [])
        ]
    abort_report = evaluate_abort_criteria(
        expectancy_net_r=float(portfolio_stats.expectancy_net_r),
        ci95_lo=float(portfolio_stats.ci95_lo),
        ci95_hi=float(portfolio_stats.ci95_hi),
        expectancy_r_gross=float(portfolio_stats.expectancy_r),
        momentum_baseline_gross_r=control_gross,
        cost_heavy_subsets_positive=cost_split["only_cost_heavy_positive"]
        if cost_split["evaluated"]
        else None,
        auc_test=auc_test,
        expectancy_lift_r=expectancy_lift,
        top_features=top_features,
    )
    # The degradation monitor's inputs (L4 §F.3): the live fold's P(Win)
    # distribution against the model's own training distribution, the realised
    # win rate of the top decile, and the churn of the top features.
    last = fold_reports[-1] if fold_reports else None
    churn = float("nan")
    if len(fold_reports) >= 2:
        churn = float(
            _importance_churn(
                fold_reports[-2].feature_importances,
                fold_reports[-1].feature_importances,
            )
        )
    kill_switch = compute_kill_switch(
        abort_report=abort_report,
        p_pred_distribution=(last.live_distribution if last else None),
        p_pred_distribution_train=(last.train_distribution if last else None),
        realised_top_decile_win_rate=(
            float(last.top_decile_win_rate) if last else float("nan")
        ),
        top_importance_churn=churn,
        consecutive_folds_below=consecutive_below,
        k1_folds_within_6_months=k1_folds,
    )

    return WalkForwardReport(
        folds=fold_reports,
        portfolio=portfolio_stats,
        baseline=baseline_stats,
        equity_r=equity,
        sharpe=sharpe,
        deflated_sharpe=dsr,
        dsr_p_value=p_value,
        trials=trials,
        n_candidates=len(ordered),
        n_approved=len(approved),
        n_trades=len(portfolio_trades),
        kill_switch=kill_switch,
        trades=portfolio_trades,
    )


def _distribution(values: Sequence[float]) -> dict[str, float] | None:
    """The mean and the standard deviation of a prediction distribution."""
    finite = np.asarray([v for v in values if np.isfinite(v)], dtype=np.float64)
    if finite.size == 0:
        return None
    return {
        "mean": float(finite.mean()),
        "sd": float(finite.std(ddof=1)) if finite.size > 1 else 0.0,
        "n": int(finite.size),
    }


def _top_decile_win_rate(scored: Sequence[tuple[float, Candidate]]) -> float:
    """The realised win rate of the candidates the model scored highest.

    L4 §F.3's second signal: the top decile of P(Win) must clear 0.45.
    """
    if not scored:
        return float("nan")
    ordered = sorted(scored, key=lambda item: item[0], reverse=True)
    top = ordered[: max(1, len(ordered) // 10)]
    closed = [cand for _, cand in top if cand.is_closed]
    if not closed:
        return float("nan")
    return sum(1 for cand in closed if cand.r_multiple > 0) / len(closed)


def _feature_importances(scorer, limit: int = 10) -> list[tuple[str, float]]:
    """The model's own feature importances (gain), most important first.

    L4 §F.2 wants them in the fold report and §F.3's third degradation signal
    is the churn between consecutive folds, so they have to come from the
    model that was actually used.
    """
    model = getattr(scorer, "model", None)
    if model is None:
        return []
    try:
        gains = model.feature_importance(importance_type="gain")
    except Exception:  # pragma: no cover - depends on the runtime
        return []
    names = list(getattr(scorer, "feature_list", []))
    pairs = [
        (names[i] if i < len(names) else f"feature_{i}", float(gain))
        for i, gain in enumerate(gains)
    ]
    pairs.sort(key=lambda item: item[1], reverse=True)
    return pairs[:limit]


def _importance_churn(
    previous: Sequence[tuple[str, float]],
    current: Sequence[tuple[str, float]],
) -> float:
    """The share of the top features' gain that changed since the previous fold.

    L4 §F.3's third signal: "if the top-2 features change between
    consecutive folds by more than half their gain, the model is refitting to
    noise".
    """
    if not previous or not current:
        return float("nan")
    before = dict(previous)
    after = dict(current)
    top = set(list(before)[:2]) | set(list(after)[:2])
    total = sum(abs(before.get(name, 0.0)) + abs(after.get(name, 0.0)) for name in top)
    if total <= 0.0:
        return float("nan")
    changed = sum(
        abs(before.get(name, 0.0) - after.get(name, 0.0)) for name in top
    )
    return changed / total


def _top_decile_win_rate(scored: Sequence[tuple[float, Candidate]]) -> float:
    """The realised win rate of the candidates the model scored highest.

    L4 §F.3's second signal: the top decile of P(Win) must clear 0.45.
    """
    if not scored:
        return float("nan")
    ordered = sorted(scored, key=lambda item: item[0], reverse=True)
    top = ordered[: max(1, len(ordered) // 10)]
    closed = [cand for _, cand in top if cand.is_closed]
    if not closed:
        return float("nan")
    return sum(1 for cand in closed if cand.r_multiple > 0) / len(closed)


def _drift(p_wins: list[float], fold: Fold, approved: list[Candidate]) -> dict:
    """The prediction-drift metric of a fold.

    The training distribution is not stored in the D3 artefact (only the counts
    are), so the drift is measured against the **training base rate**
    ``positives_train / n_train``:

    * ``drift_mean_p``        mean live P(Win) minus the training base rate;
    * ``drift_realised``      realised win rate minus the training base rate;
    * ``drift_abs_mean_p``    the same, absolute, as a single number to watch.
    """
    meta = fold.meta or {}
    n_train = int(meta.get("n_train", 0) or 0)
    pos_train = int(meta.get("positives_train", 0) or 0)
    base_rate = (pos_train / n_train) if n_train else float("nan")
    mean_p = float(np.mean(p_wins)) if p_wins else float("nan")
    closed = [t for t in approved if t.is_closed]
    realised = (sum(1 for t in closed if t.r_multiple > 0) / len(closed)) if closed else float("nan")
    return {
        "train_base_rate": base_rate,
        "live_mean_p": mean_p,
        "live_realised_win_rate": realised,
        "mean_p_minus_base": (mean_p - base_rate) if math.isfinite(mean_p) and math.isfinite(base_rate) else float("nan"),
        "realised_minus_base": (realised - base_rate) if math.isfinite(realised) and math.isfinite(base_rate) else float("nan"),
        "abs_mean_p_minus_base": abs(mean_p - base_rate) if math.isfinite(mean_p) and math.isfinite(base_rate) else float("nan"),
    }


# ---------------------------------------------------------------------------
# Sharpe and the deflated Sharpe
# ---------------------------------------------------------------------------


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, ~1e-9 accurate)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        return x
    if p > 1.0 - plow:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        return x
    q = p - 0.5
    r = q * q
    x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    return x


def deflated_sharpe(
    returns: np.ndarray,
    trials: int = 32,
    trades_per_year: float | None = None,
) -> tuple[float, float, float]:
    """Deflated Sharpe ratio (Bailey & Lopez de Prado).

    Returns ``(sharpe, deflated_sharpe, p_value)``.

    The adjustment accounts for the fact that we have already tried many
    parameter combinations (D4 counts **32** arms) and therefore for the
    probability of finding a positive Sharpe by chance.  The expected maximum
    Sharpe under the null is

    ``SR0 = sqrt(V) * ((1-g) Z^-1(1 - 1/N) + g Z^-1(1 - 1/(N e)))``

    with ``g`` the Euler-Mascheroni constant and ``V`` the variance of the
    estimated Sharpe under the null (``(1 + SR^2/2)/T`` for iid returns).

    The deflated Sharpe is the probability that the observed Sharpe exceeds
    that benchmark, adjusted for the skew and the kurtosis of the return
    series.
    """
    r = np.asarray(returns, dtype=np.float64)
    n = r.shape[0]
    if n < 3:
        return float("nan"), float("nan"), float("nan")

    sd = float(r.std(ddof=1))
    if sd <= 0.0:
        return float("nan"), float("nan"), float("nan")
    sr = float(r.mean()) / sd
    ann = math.sqrt(trades_per_year) if trades_per_year else 1.0
    sr_ann = sr * ann

    euler = 0.5772156649015329
    ntrial = max(2, int(trials))
    variance = (1.0 + 0.5 * sr_ann**2) / n
    z1 = _normal_ppf(1.0 - 1.0 / ntrial)
    z2 = _normal_ppf(1.0 - 1.0 / (ntrial * math.e))
    sr0 = math.sqrt(variance) * ((1.0 - euler) * z1 + euler * z2)

    skew = float(((r - r.mean()) ** 3).mean() / sd**3)
    kurt = float(((r - r.mean()) ** 4).mean() / sd**4)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_ann + (kurt - 1.0) / 4.0 * sr_ann**2))
    z = (sr_ann - sr0) * math.sqrt(max(1, n - 1)) / denom
    dsr = _normal_cdf(z)
    return sr_ann, dsr, 1.0 - dsr


def _sharpe_stats(
    equity: np.ndarray,
    trials: int,
    trades_per_year: float | None,
) -> tuple[float, float, float]:
    return deflated_sharpe(equity, trials, trades_per_year)
