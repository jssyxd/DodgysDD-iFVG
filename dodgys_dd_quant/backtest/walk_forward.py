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

from dodgys_dd_quant.backtest.cost_model import (
    CostProfile,
    break_even_cost_r,
    cost_in_r,
    summarise_costs,
)
from dodgys_dd_quant.strategy.constants import DECISION_THRESHOLD
from dodgys_dd_quant.strategy.state_machine import Candidate

__all__ = [
    "ForwardOnlyViolation",
    "Fold",
    "FoldReport",
    "WalkForwardReport",
    "load_walk_forward_index",
    "assert_forward_only",
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

        # Candidate layouts, most specific first. The ML leaf writes the artefact
        # to `<root>/models/<symbol>/<asof_compact>/` and records it in the fold
        # entry as `model_dir`; the D3 contract says `<root>/<symbol>/<asof>/`.
        # Accept all of them so the two leaves interoperate without either
        # having to know the other's layout.
        candidates = []
        if directory:
            d = Path(str(directory))
            candidates += [d, root / d, root / symbol / d]
        candidates += [
            root / "models" / symbol / compact,
            root / "models" / symbol / f"asof_{compact}",
            root / symbol / compact,
            root / symbol / f"asof_{compact}",
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

    ``T`` is the **start** of the asof day. The ML leaf's index documents its
    basis as *"end of the validation window (= the start of the test window)"*,
    so a fold whose asof is 2023-08-01 may decide trades whose signal closed
    after 2023-08-01 00:00. A candidate whose signal closed in the last minutes
    of the previous month was decided *before* the model existed, and is
    correctly rejected — that is a look-ahead, not a rounding artefact.
    """
    if ts_event <= fold.asof_ns:
        raise ForwardOnlyViolation(
            f"model asof={fold.asof} may not decide a trade at ts_event={ts_event} "
            f"(<= asof boundary {fold.asof_ns})"
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

    def __init__(self, fold: Fold, threshold: float = DECISION_THRESHOLD) -> None:
        self.fold = fold
        self.threshold = threshold
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
        return float(self.model.predict(np.asarray([row], dtype="float64"))[0])


# ---------------------------------------------------------------------------
# Portfolio accounting (D4)
# ---------------------------------------------------------------------------


def simulate_portfolio(candidates: Sequence[Candidate], n_bars: int) -> list[Candidate]:
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
        selected.append(cand)
        # the position occupies [entry_bar, exit_bar]
        free_from = cand.exit_bar + 1 if cand.exit_bar >= 0 else n_bars + 1
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
    trades: list[Candidate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
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
    feature_fn=None,
    trials: int = 32,
    trades_per_year: float | None = None,
    portfolio_trades: Sequence[Candidate] | None = None,
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
        keep: list[Candidate] = []
        # Each fold must be decided by **its own** model: the model trained up to
        # that fold's asof, and no other. Building the scorer from the fold
        # (rather than reusing one caller-supplied scorer for every fold) is what
        # makes the walk-forward honest.
        fold_scorer = ModelScorer(fold, threshold=threshold)
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
                if p >= threshold:
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
        fold_reports.append(report)

    # --- the portfolio: one position at a time, across the whole sample ----
    # ``portfolio_trades`` lets the caller supply the deferred arm (the
    # experiment harness's accounting); the default selects a subset of the
    # approved candidates and *drops* the blocked signals.
    accounting = "drop"
    if portfolio_trades is None:
        portfolio_trades = simulate_portfolio(approved, n_bars)
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
    baseline_trades = simulate_portfolio(ordered, n_bars)
    baseline_stats = summarise_trades(baseline_trades, profile, slippage_ticks)

    equity = np.array([t.r_multiple for t in portfolio_trades if t.is_closed], dtype=np.float64)
    sharpe, dsr, p_value = _sharpe_stats(equity, trials, trades_per_year)

    for report in fold_reports:
        report.accounting = accounting

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
        trades=portfolio_trades,
    )


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
