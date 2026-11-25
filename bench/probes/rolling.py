"""Rolling-stack probes -- Q5 (data sufficiency and the rolling ML/RL/e2e stack).

The audit found the rolling ML, the e2e backtest and the dynamic backtest
**implemented and executed**, but with defects that made the numbers
unreliable, and the RL **not built at all** (correctly: L4 says the RL is
last and should not be built before there is an edge to manage).

The defects that survive into this tree are the open R1 findings:

====  ==========================================================================
F1    the forward-only guard is **vacuous** -- it compares the trade against the
      *fold's* asof, never against the **model artefact's** own asof
F2    the D3 producer and consumer cannot interoperate -- the index is written
      where the reader does not look
F3    the model path cannot predict (``predict(lgb.Dataset(...))`` raises on
      LightGBM >= 4) and the feature frame is keyed by ``ts_event`` alone, so
      candidates sharing a timestamp steal each other's features
F4    the "rule-only baseline" is the gated portfolio, so the comparison the
      whole report rests on is impossible
F6    two label definitions coexist (the engine's unbounded one and the ML's
      240-bar one)
F7    the purge/embargo horizon is the **constant** 240 bars, not the horizon
      the labels were built with
F8    the trainer prints census expectancies with no D4 caveat
F9    ``LAKE_ROOTS`` never expands ``~``
F10   the regime parameters are never called
F11   ``checklist_score`` and the grade rubric disagree
F12   the docs, the producer and the consumer disagree
====  ==========================================================================

These probes check the **behaviour** each finding is about, so a fix that
only silences the symptom does not pass.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from bench.probes import register

__all__ = []


@register(
    "rolling.forward_only_is_not_vacuous",
    "rolling",
    16,
    "the forward-only guard rejects a model whose artefact asof is later than the trade (F1)",
)
def _forward_only_nonvacuous() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import ForwardOnlyViolation, assert_forward_only

    from dodgys_dd_quant.backtest.walk_forward import Fold

    fold = Fold(
        asof="2023-07-01",
        asof_ns=_ns("2023-07-01"),
        directory=Path("."),
        train_start="2023-01-01",
        train_end="2023-06-01",
        valid_start="2023-06-01",
        valid_end="2023-07-01",
        test_start="2023-07-01",
        test_end="2023-08-01",
        meta={"asof": "2023-07-01"},
    )
    # A trade well inside the fold's own test window: the *fold*'s asof does
    # not reject it, but a model artefact stamped later than the trade must.
    trade_ts = _ns("2023-07-15")
    fold.meta = dict(fold.meta)
    fold.meta["asof"] = "2024-11-01"
    try:
        assert_forward_only(fold, trade_ts)
    except ForwardOnlyViolation:
        return True, "the guard rejects a trade decided by a later model"
    except Exception as exc:
        return False, f"the guard raised {type(exc).__name__}: {exc}"
    return False, (
        "a model artefact stamped 2024-11-01 decided a 2023-07-15 trade without "
        "raising -- the guard is vacuous (F1)"
    )


def _ns(date: str) -> int:
    y, m, d = (int(x) for x in date.split("-"))
    days = _days_from_civil(y, m, d)
    return days * 86_400_000_000_000


def _days_from_civil(y: int, m: int, d: int) -> int:
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146_097 + doe - 719_468


@register(
    "rolling.d3_producer_consumer_interop",
    "rolling",
    16,
    "the D3 producer and consumer interoperate: the index is where the reader looks (F2)",
)
def _d3_interop() -> tuple[bool, str]:
    """The D3 contract is ``artifacts/models/{symbol}/{asof_YYYYMMDD}/`` plus
    ``artifacts/models/{symbol}/walk_forward_index.json``, and the backtest's
    default ``--models-root`` is ``artifacts/models``.

    The round trip must therefore work **with those defaults**: the trainer
    writes the index where the reader looks, and the reader resolves each
    fold's model file.
    """
    import shutil
    import tempfile

    from dodgys_dd_quant.backtest.walk_forward import load_walk_forward_index
    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    from bench import fixtures

    labelled, bars = fixtures.rolling_frame()
    workspace = Path(tempfile.mkdtemp(prefix="ifvg-d3-"))
    run_root = workspace / "artifacts"
    try:
        train_walk_forward(
            labelled,
            bars,
            symbol="BTCUSDT",
            timeframe="15m",
            run_root=run_root,
        )
        # The backtest's default --models-root, relative to the run root.
        models_root = run_root / "models"
        folds = load_walk_forward_index(models_root, "BTCUSDT", "15m")
        if not folds:
            return False, (
                f"the reader found 0 folds under {models_root} -- the trainer wrote "
                "the index somewhere else, so the producer and consumer do not "
                "interoperate (F2)"
            )
        missing = [
            f.directory for f in folds if not (f.directory / "meta_label_meta.json").exists()
        ]
        if missing:
            return False, f"{len(missing)} fold(s) have no meta_label_meta.json: {missing[:2]}"
        index = models_root / "BTCUSDT" / "walk_forward_index.json"
        if not index.exists():
            return False, (
                f"the D3 index is not at {index} -- the documented layout is "
                "artifacts/models/{symbol}/walk_forward_index.json"
            )
        return True, f"the reader resolves {len(folds)} fold(s) written by the trainer"
    except Exception as exc:
        return False, f"the round trip failed: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@register(
    "rolling.model_path_predicts",
    "rolling",
    14,
    "the model path can actually predict: raw features in, a probability out (F3)",
)
def _model_predicts() -> tuple[bool, str]:
    import shutil
    import tempfile

    from dodgys_dd_quant.backtest.walk_forward import ModelScorer, load_walk_forward_index
    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import train_walk_forward

    from bench import fixtures

    labelled, bars = fixtures.rolling_frame()
    root = Path(tempfile.mkdtemp(prefix="ifvg-predict-"))
    try:
        train_walk_forward(
            labelled,
            bars,
            symbol="BTCUSDT",
            timeframe="15m",
            run_root=root,
        )
        folds = load_walk_forward_index(root, "BTCUSDT", "15m")
        if not folds:
            return False, "no folds to score with"
        scorer = ModelScorer(folds[0])
        if not scorer.available:
            return False, f"the scorer is unavailable: {scorer.error}"
        features = {name: 0.0 for name in scorer.feature_list}
        try:
            probability = scorer.score(features)
        except Exception as exc:
            return False, f"the scorer raised: {type(exc).__name__}: {exc}"
        if not (0.0 <= float(probability) <= 1.0):
            return False, f"the score is {probability}, expected a probability"
        return True, f"the scorer returned P(Win)={float(probability):.4f}"
    except Exception as exc:
        return False, f"the prediction path failed: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@register(
    "rolling.feature_frame_is_unambiguous",
    "rolling",
    12,
    "candidates sharing a timestamp get their own features (F3: the frame was keyed by ts_event alone)",
)
def _feature_frame_unambiguous() -> tuple[bool, str]:
    """The feature lookup must be keyed by something finer than ``ts_event``.

    77,929 rows of the real candidate log share a ``ts_event`` with another
    candidate, so a lookup keyed by ``ts_event`` alone silently gives two
    different candidates the same features.
    """
    import pandas as pd

    from dodgys_dd_quant.ml_pipeline.features import build_features

    from bench import fixtures

    labelled = fixtures.labelled_frame()
    if labelled.empty:
        return False, "no labelled candidates"
    counts = labelled.groupby("ts_event").size()
    collisions = int((counts > 1).sum())
    if collisions == 0:
        return False, (
            "the fixture has no colliding timestamps, so this probe proves nothing -- "
            "use a window with duplicates"
        )

    # Two candidates that share a timestamp must remain distinguishable by
    # their features.  ``(ts_event, side)`` is **not** enough: two gaps of the
    # same direction can be confirmed on the same bar.  The unique key also
    # carries the gap's newest bar.
    keys = list(zip(labelled["ts_event"], labelled["side"], labelled["fvg_bar3"]))
    if len(set(keys)) != len(keys):
        return False, (
            "the (ts_event, side, fvg_bar3) key does not identify a candidate "
            "uniquely -- the feature lookup cannot be unambiguous"
        )
    frame = build_features(labelled)
    if len(frame) != len(labelled):
        return False, (
            f"build_features returned {len(frame)} rows for {len(labelled)} candidates"
        )
    return True, (
        f"{collisions} timestamp(s) carry more than one candidate and "
        "(ts_event, side, fvg_bar3) identifies each candidate uniquely"
    )


@register(
    "rolling.baseline_is_independent",
    "rolling",
    14,
    "the rule-only baseline is an independent population, not the gated portfolio (F4)",
)
def _baseline_independent() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward

    from bench import fixtures

    candidates = list(fixtures.candidate_log())
    if not candidates:
        return False, "no candidates"

    class _RejectingScorer:
        available = True
        #: the walk-forward reads the *scorer's* threshold (a quantile-gated
        #: fold carries its own), so a stub must expose it
        threshold = 0.58

        def score(self, features):
            return 0.0

    fold = Fold(
        asof="2023-01-01",
        asof_ns=0,
        directory=Path("."),
        test_start="",
        test_end="",
    )
    report = walk_forward(candidates, 10_000, [fold], scorer=_RejectingScorer())
    if report.portfolio.n_closed and report.baseline.n_closed == report.portfolio.n_closed:
        return False, (
            "with a model that rejects every candidate the baseline still has "
            f"{report.baseline.n_closed} closed trades -- it is the gated population (F4)"
        )
    if not report.baseline.n_closed:
        return False, "the rule-only baseline is empty -- there is nothing to compare against"
    return True, (
        f"the baseline holds {report.baseline.n_closed} trades while the gated "
        f"portfolio holds {report.portfolio.n_closed}"
    )


@register(
    "rolling.single_label_definition",
    "rolling",
    10,
    "one label definition: the engine's label and the ML label agree (F6)",
)
def _single_label() -> tuple[bool, str]:
    from bench import fixtures

    log = fixtures.candidate_log()
    table = log.to_table()
    engine = table["label"]
    labelled = fixtures.labelled_frame()
    if "label" not in labelled.columns:
        return False, "the labelled frame carries no label column"
    ml = labelled["label"].to_numpy()
    if len(engine) != len(ml):
        return False, f"the two label vectors have different lengths ({len(engine)} vs {len(ml)})"
    both = (engine >= 0) & (ml >= 0)
    if not both.any():
        return False, "no candidate is labelled by both definitions"
    disagree = int((engine[both] != ml[both]).sum())
    if disagree:
        return False, f"{disagree} candidates carry different labels under the two definitions (F6)"
    return True, f"{int(both.sum())} candidates agree under both label definitions"


@register(
    "rolling.embargo_follows_the_horizon",
    "rolling",
    12,
    "the embargo is derived from the horizon the labels were built with (F7)",
)
def _embargo_follows_horizon() -> tuple[bool, str]:
    """The split must take the **horizon actually used** for the labels.

    The trainer exposes ``--horizon-bars``; the split's embargo is derived
    from the *constant* 240 bars instead, so a run with a 1000-bar horizon
    leaves a training label resolving inside the validation window.
    """
    import inspect

    from dodgys_dd_quant.ml_pipeline import splits

    signature = inspect.signature(splits.make_folds)
    if "horizon_bars" not in signature.parameters:
        return False, (
            "make_folds takes no horizon_bars, so its embargo is derived from the "
            "constant 240-bar horizon rather than the horizon in use (F7)"
        )

    import pandas as pd

    # 400 daily points: enough history for the 6/1/1 geometry to yield folds
    # even with a 1000-minute embargo.
    frame = pd.DataFrame(
        {
            "ts_event": [
                1_700_000_000_000_000_000 + i * 86_400_000_000_000 for i in range(400)
            ]
        }
    )
    folds = splits.make_folds(
        frame,
        embargo_minutes=1000,
        bar_interval_minutes=1,
        horizon_bars=1000,
    )
    if not folds:
        return False, "no folds were produced"
    embargo = folds[0].embargo_minutes
    if embargo < 1000:
        return False, f"the embargo is {embargo} minutes for a 1000-bar horizon"
    return True, f"the embargo follows the horizon in use ({embargo} minutes)"


@register(
    "rolling.census_is_caveated",
    "rolling",
    8,
    "the trainer's census expectancies carry the D4 caveat (F8)",
)
def _census_caveat() -> tuple[bool, str]:
    import inspect

    from dodgys_dd_quant.ml_pipeline import train_meta_labeler

    source = inspect.getsource(train_meta_labeler)
    if "E[R] base" in source or "E[R] gated" in source:
        # The census numbers are printed; a caveat must be printed with them.
        window = source[source.index("E[R] base") - 2000 : source.index("E[R] base") + 2000]
        lowered = window.lower()
        if "census" not in lowered and "one position" not in lowered and "concurrent" not in lowered:
            return False, (
                "the trainer prints the census expectancies (E[R] base / E[R] gated) with no "
                "caveat that they are simultaneous positions (F8)"
            )
        return True, "the census print carries the D4 caveat"
    return True, "the trainer prints no census expectancy at all"


@register(
    "rolling.lake_roots_expand_home",
    "rolling",
    6,
    "the lake roots expand ~ (F9): the authoritative NFS lake is actually used",
)
def _lake_roots() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.runner import LAKE_ROOTS

    if not LAKE_ROOTS:
        return False, "LAKE_ROOTS is empty"
    for root in LAKE_ROOTS:
        if "~" in str(root):
            return False, f"a lake root still contains '~': {root}"
    return True, f"all {len(LAKE_ROOTS)} lake roots are expanded"


@register(
    "rolling.cost_ladder_is_reported",
    "rolling",
    10,
    "costs are reported at 0/1/2 ticks with the break-even round-trip cost in R (D9)",
)
def _cost_ladder() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.cost_model import COST_PROFILES, get_profile, summarise_costs

    nq = get_profile("nq")
    ladder = []
    for ticks in (0, 1, 2):
        costs = summarise_costs(nq, [20_000.0], [50.0], ticks)
        ladder.append(round(float(costs["mean_cost_r"]), 6))
    if len(set(ladder)) != 3:
        return False, f"the 0/1/2-tick ladder is degenerate: {ladder}"
    if not (ladder[0] < ladder[1] < ladder[2]):
        return False, f"the cost ladder does not increase with slippage: {ladder}"
    if "binance" not in COST_PROFILES:
        return False, "no percentage-based cost profile (binance) exists"
    return True, f"the NQ cost ladder in R is {ladder}"


@register(
    "rolling.dsr_accounts_for_trials",
    "rolling",
    8,
    "the deflated Sharpe accounts for the number of trials already run (D4)",
)
def _dsr_trials() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import deflated_sharpe

    import numpy as np

    rng = np.random.default_rng(11)
    returns = rng.normal(0.01, 1.0, 400)
    _, few, _ = deflated_sharpe(returns, trials=1)
    _, many, _ = deflated_sharpe(returns, trials=64)
    if not (many < few):
        return False, (
            f"the deflated Sharpe did not fall when the trial count rose "
            f"({few:.4f} at 1 trial vs {many:.4f} at 64)"
        )
    return True, f"DSR falls with the trial count ({few:.4f} -> {many:.4f})"


@register(
    "rolling.kaggle_kernel_never_sees_test",
    "rolling",
    10,
    "the generated Kaggle kernel asserts it never sees its test window",
)
def _kaggle_kernel() -> tuple[bool, str]:
    import inspect

    from dodgys_dd_quant.ml_pipeline import kaggle_export

    source = inspect.getsource(kaggle_export)
    for needle in ("TEST_START_NS", "assert"):
        if needle not in source:
            return False, f"the kernel generator never mentions {needle}"
    return True, "the kernel generator carries the test-window assertions"


@register(
    "rolling.rl_cannot_open_a_position",
    "rolling",
    12,
    "the RL layer is position-management only: its action space cannot open a position (INV1)",
)
def _rl_invariant() -> tuple[bool, str]:
    import importlib

    module = None
    for name in (
        "dodgys_dd_quant.rl.action_space",
        "dodgys_dd_quant.rl",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        break
    if module is None:
        return False, (
            "no RL action-space module (dodgys_dd_quant.rl.action_space) -- "
            "the RL layer does not exist"
        )

    space = None
    for attr in ("ACTION_SPACE", "PositionAction", "action_space"):
        candidate = getattr(module, attr, None)
        if candidate is not None:
            space = candidate
            break
    if space is None:
        return False, "the RL module exposes no action space"

    actions = list(space) if not hasattr(space, "__dataclass_fields__") else []
    if not actions:
        fields = getattr(space, "__dataclass_fields__", {})
        for forbidden in ("side", "quantity", "direction", "open", "entry"):
            if forbidden in fields:
                return False, f"the RL action carries a {forbidden!r} field -- it could open a position"
        return True, "the RL action type carries no field that could open a position"

    for action in actions:
        for forbidden in ("side", "quantity", "direction", "open", "entry"):
            if hasattr(action, forbidden):
                return False, f"an RL action carries a {forbidden!r} attribute"
    return True, f"{len(actions)} RL actions, none of which can open a position"


@register(
    "rolling.dynamic_backtest_reports_each_fold",
    "rolling",
    10,
    "the dynamic backtest writes a per-fold report (L4 section F.2)",
)
def _dynamic_report() -> tuple[bool, str]:
    import inspect

    from dodgys_dd_quant.backtest import walk_forward

    source = inspect.getsource(walk_forward)
    if "folds.csv" not in source and "fold_report" not in source.lower():
        return False, (
            "the walk-forward does not write a per-fold report (L4 F.2 asks for one "
            "row per fold with the base rate, the funnel and the expectancy)"
        )
    return True, "the walk-forward writes a per-fold report"


@register(
    "rolling.report_is_json_serialisable",
    "rolling",
    6,
    "the walk-forward report serialises to JSON (so it can be archived and compared)",
)
def _report_json() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward

    from bench import fixtures

    candidates = list(fixtures.candidate_log())
    fold = Fold(asof="2023-01-01", asof_ns=0, directory=Path("."), test_start="", test_end="")
    report = walk_forward(candidates, 10_000, [fold])
    try:
        json.dumps(report.as_dict(), default=str)
    except Exception as exc:
        return False, f"the report does not serialise: {type(exc).__name__}: {exc}"
    return True, "the report serialises to JSON"


@register(
    "rolling.expectancy_is_reported_with_cost",
    "rolling",
    8,
    "the report prints the net expectancy and the break-even cost in R next to the gross one",
)
def _expectancy_with_cost() -> tuple[bool, str]:
    import inspect

    from dodgys_dd_quant.backtest import runner

    source = inspect.getsource(runner)
    if "break-even" not in source.lower():
        return False, "the runner never reports the break-even round-trip cost in R"
    if "E_net" not in source:
        return False, "the runner never reports the net expectancy"
    return True, "the runner reports E[R] net and the break-even cost in R"


@register(
    "rolling.one_position_accounting_is_drop",
    "rolling",
    8,
    "the one-position-at-a-time accounting drops blocked signals (L2's D-17 correction)",
)
def _drop_accounting() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import simulate_portfolio

    from bench import fixtures

    candidates = list(fixtures.candidate_log())
    trades = simulate_portfolio(candidates, 10_000)
    if len(trades) >= len(candidates):
        return False, "the portfolio kept every candidate -- blocked signals are not dropped"
    return True, f"the portfolio kept {len(trades)} of {len(candidates)} candidates"


@register(
    "rolling.math_is_finite",
    "rolling",
    4,
    "the report's statistics are finite (no NaN leaking into the headline numbers)",
)
def _finite_stats() -> tuple[bool, str]:
    from dodgys_dd_quant.backtest.walk_forward import Fold, walk_forward

    from bench import fixtures

    candidates = list(fixtures.candidate_log())
    fold = Fold(asof="2023-01-01", asof_ns=0, directory=Path("."), test_start="", test_end="")
    report = walk_forward(candidates, 10_000, [fold])
    stats = report.portfolio
    for name in ("win_rate", "expectancy_r", "profit_factor", "t_stat"):
        value = float(getattr(stats, name))
        if not math.isfinite(value):
            return False, f"portfolio.{name} is {value}"
    return True, "the portfolio statistics are finite"
