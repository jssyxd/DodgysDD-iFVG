"""The gaps the audits still name in the rolling stack (L4 §F.5, R1 F12).

* **L4 §F.5 item 5** -- the PBO via CSCV, the selection-procedure half of
  the multiple-testing correction.  It was never built.
* **L4 §F.5 items 1-2** -- the DSR's trial count must come from the
  write-once ledger, not from a constant.
* **R1 F12** -- the producer, the consumer and the README must agree on the
  artefact layout.
* **doc L152** -- the RL's reward (Sortino-like, with the 1.5R failure
  penalty) and its state (the open P&L in R, the regime, the holding time and
  the order-flow imbalance).
* **Q5** -- a contract roll leaves a price gap that must not be read as a
  liquidity sweep.
"""

from __future__ import annotations

import re
from dataclasses import replace

from bench.probes import register

__all__ = []


def _bars():
    from bench import fixtures

    return fixtures.btc_1m()


@register(
    "rolling.pbo_via_cscv",
    "rolling",
    60,
    "the PBO via CSCV exists and detects a selection that does not generalise (L4 §F.5)",
)
def _pbo() -> tuple[bool, str]:
    """L4 §F.5 item 5: the PBO from CSCV over the out-of-sample segments.

    The estimator must split the segments into every possible pair of
    halves, select the best in-sample configuration, and measure how often
    that selection lands in the bottom half out of sample.
    """
    import numpy as np

    from dodgys_dd_quant.backtest.cscv import cscv_pbo

    n_segments = 10
    n_configs = 20

    # (a) a configuration that is good everywhere: the selection generalises.
    dominant = np.zeros((n_segments, n_configs))
    dominant[:, 0] = 1.0
    good = cscv_pbo(dominant)
    if good.pbo != 0.0:
        return False, f"a dominant configuration still produced a PBO of {good.pbo}"

    # (b) configurations that are only good in one segment: the selection is
    #     an artefact of the in-sample half and never generalises.
    overfit = np.full((n_segments, n_configs), 0.5)
    for k in range(n_segments):
        overfit[:, k] = -1.0
        overfit[k, k] = 10.0
    bad = cscv_pbo(overfit)
    if bad.pbo < 0.9:
        return False, f"a selection that never generalises scored a PBO of {bad.pbo}"

    # (c) the split count is the combinatorial one.
    import math

    expected = math.comb(n_segments, n_segments // 2)
    if bad.n_splits != expected:
        return False, f"{bad.n_splits} splits, expected C({n_segments}, {n_segments // 2})={expected}"

    # (d) noise is not zero and not one.
    rng = np.random.default_rng(11)
    noise = cscv_pbo(rng.normal(size=(n_segments, n_configs)))
    if not (0.0 < noise.pbo < 1.0):
        return False, f"a noise matrix produced a degenerate PBO of {noise.pbo}"
    return True, (
        f"CSCV over {bad.n_splits} splits: a generalising selection scores "
        f"{good.pbo}, a non-generalising one {bad.pbo}, noise {noise.pbo:.3f}"
    )


@register(
    "rolling.dsr_trial_count_comes_from_the_registry",
    "rolling",
    40,
    "the DSR's trial count comes from the write-once ledger, not a constant (L4 §F.5)",
)
def _dsr_trials() -> tuple[bool, str]:
    """L4 §F.5: "the number of trials ``N`` -- from the registry".

    A constant in the CLI is exactly the defect the audit names, so the count
    must be read from the ledger and must grow with it.
    """
    import tempfile
    from pathlib import Path

    import numpy as np

    from dodgys_dd_quant.backtest.trials import TrialRegistry, trial_count_for
    from dodgys_dd_quant.backtest.walk_forward import deflated_sharpe

    with tempfile.TemporaryDirectory() as tmp:
        registry = TrialRegistry(Path(tmp))
        if registry.trial_count() != 0:
            return False, "a fresh registry is not empty"
        registry.record(name="a", oos_returns=[0.1, -0.2, 0.3])
        registry.record(name="b", oos_returns=[0.2, -0.1, 0.4])
        count = trial_count_for(registry)
        if count != 3:
            return False, (
                f"the ledger holds {registry.trial_count()} trials, the DSR "
                f"count should be 3 (the ledger plus the run being reported)"
            )

        returns = np.asarray([0.2, -0.1, 0.3, 0.15, -0.05, 0.25, 0.1, 0.2], dtype=float)
        small = deflated_sharpe(returns, trials=2)
        ledger = deflated_sharpe(returns, trials=count)
        if not (ledger[1] <= small[1]):
            return False, (
                f"the DSR did not fall with the trial count: {small[1]:.4f} at "
                f"N=2, {ledger[1]:.4f} at N={count}"
            )

        # registering the run grows the ledger
        registry.record(name="c", oos_returns=[0.05, 0.1, -0.02])
        if registry.trial_count() != 3:
            return False, "the run was not appended to the ledger"
    return True, (
        f"the ledger drives the DSR's N (3 trials -> DSR {ledger[1]:.4f} against "
        f"{small[1]:.4f} at N=2)"
    )


@register(
    "rolling.artefact_layout_is_documented",
    "rolling",
    40,
    "the README, the producer and the consumer agree on the artefact layout (F12)",
)
def _artefact_layout() -> tuple[bool, str]:
    """R1 F12: the producer/consumer/README trio must not disagree.

    The producer writes ``{run_root}/models/{symbol}/asof_{YYYYMMDD}/``; the
    README documents it and the backtest's reader looks for it.  The check
    reads the documented template out of the README and compares it with the
    directory the producer actually creates.
    """
    from pathlib import Path

    from dodgys_dd_quant.ml_pipeline.train_meta_labeler import (
        INDEX_FILENAME,
        META_FILENAME,
        MODEL_FILENAME,
        model_dir_for,
    )

    readme = Path("dodgys_dd_quant/ml_pipeline/README.md").read_text(encoding="utf-8")

    template = re.search(
        r"(?P<root>[\w./-]*?)models/\{symbol\}/\{asof_YYYYMMDD\}/", readme
    )
    if template is None:
        return False, "the README documents no artefact layout"

    symbol = "BTCUSDT"
    compact = "20240102"
    documented = (
        template.group("root")
        + f"models/{symbol}/asof_{compact}/"
    )
    produced = model_dir_for("artifacts", symbol, compact)
    if Path(documented) != produced:
        return False, (
            f"the README documents {documented!r}, the producer writes "
            f"{str(produced)!r}"
        )

    for name in (MODEL_FILENAME, META_FILENAME, INDEX_FILENAME):
        if name not in readme:
            return False, f"the README does not mention the artefact {name!r}"
    return True, (
        f"the README documents {documented!r} and names all three artefacts"
    )


@register(
    "rolling.rl_reward_penalises_stalled_profits",
    "rolling",
    45,
    "the RL reward is downside-adjusted and carries the 1.5R failure penalty (doc L152)",
)
def _rl_reward() -> tuple[bool, str]:
    """doc L152: the reward is Sortino-like and penalises a stall at 1.5R.

    The failure mode the doc singles out is *"reaching 1.5R and then failing
    to move the stop"*, so a trade that peaked above 1.5R and closed far
    below it must be penalised, while a trade that never reached 1.5R must
    not.
    """
    from dodgys_dd_quant.rl.reward import (
        PENALTY_THRESHOLD_R,
        RewardConfig,
        episode_reward,
        is_penalised,
        sortino_step_reward,
    )

    config = RewardConfig()
    stalled = episode_reward(realised_r=-0.2, peak_r=2.0, config=config)
    clean = episode_reward(realised_r=-0.2, peak_r=0.8, config=config)
    if not stalled < clean:
        return False, (
            f"a stalled 1.5R trade scored {stalled}, a clean one {clean}"
        )
    if is_penalised(2.0, -0.2, config) is not True:
        return False, "the 1.5R failure penalty does not fire"
    if is_penalised(0.8, -0.2, config) is not False:
        return False, "the 1.5R failure penalty fires below the threshold"

    # the step reward is downside-adjusted: the same gain with a larger
    # downside deviation must score lower
    calm = sortino_step_reward(0.5, 0.1)
    noisy = sortino_step_reward(0.5, 0.5)
    if not calm > noisy:
        return False, (
            f"the step reward is not downside-adjusted: {calm} against {noisy}"
        )
    return True, (
        f"a stalled 1.5R trade scores {stalled:.4f} against {clean:.4f}, and "
        f"the step reward falls from {calm:.4f} to {noisy:.4f} with downside"
    )


@register(
    "rolling.rl_state_carries_regime_and_flow",
    "rolling",
    45,
    "the RL state carries the P&L in R, the regime, the holding time and the imbalance (doc L152)",
)
def _rl_state() -> tuple[bool, str]:
    """doc L152: the state is the open P&L in R, the VXN regime, the holding
    time and the order-book imbalance.

    Every component must be scale free (the doc's own requirement for a
    policy that transfers across markets), so the same position in two
    differently priced markets produces the same vector.
    """
    import numpy as np

    from dodgys_dd_quant.rl.state_builder import build_state

    small = build_state(
        entry_price=100.0,
        current_price=101.0,
        risk=1.0,
        peak_price=102.0,
        regime=1,
        holding_bars=5,
        max_holding_bars=10,
        high=101.5,
        low=100.5,
        close=101.0,
    )
    large = build_state(
        entry_price=10000.0,
        current_price=10100.0,
        risk=100.0,
        peak_price=10200.0,
        regime=1,
        holding_bars=5,
        max_holding_bars=10,
        high=10150.0,
        low=10050.0,
        close=10100.0,
    )
    if not np.allclose(small.as_vector(), large.as_vector()):
        return False, "the state is not scale free"
    if small.open_pnl_r != 1.0:
        return False, f"the open P&L is {small.open_pnl_r} R, expected 1.0"
    if small.vxn_regime != 1:
        return False, "the state does not carry the regime band"
    if small.holding_time_bars != 0.5:
        return False, f"the holding time is {small.holding_time_bars}, expected 0.5"
    if not (0.0 <= small.order_book_imbalance <= 1.0):
        return False, "the imbalance proxy is not bounded"
    if not np.isfinite(small.as_vector()).all():
        return False, "the state vector carries a non-finite value"
    return True, (
        f"the state is scale free across a 100x price change: "
        f"{small.as_vector().tolist()}"
    )


@register(
    "rolling.roll_gap_does_not_fake_a_sweep",
    "rolling",
    50,
    "a contract roll's price gap is excluded from the signal population (Q5)",
)
def _roll_gap() -> tuple[bool, str]:
    """Q5: "the roll rule matters: a roll gap can fake a liquidity sweep".

    The engine must detect the discontinuous jump of a contract switch and
    exclude the bars around it -- from the sweep events and from the
    confirmations.
    """
    import numpy as np

    from dodgys_dd_quant.strategy.state_machine import PRESETS, run_state_machine
    from dodgys_dd_quant.strategy.structure import Bars

    bars = _bars()
    base = PRESETS["honest"]

    # Build a series with a contract roll: the prices jump 5 % half way.
    n = len(bars)
    jump_at = n // 2
    factor = np.ones(n)
    factor[jump_at:] = 1.05
    rolled = Bars(
        ts=bars.ts,
        open=bars.open * factor,
        high=bars.high * factor,
        low=bars.low * factor,
        close=bars.close * factor,
        volume=bars.volume,
        symbol=bars.symbol,
        timeframe=bars.timeframe,
    )

    plain = list(run_state_machine(rolled, base))
    guarded = list(
        run_state_machine(
            rolled, replace(base, roll_gap_frac=0.02, roll_bars_around=2)
        )
    )
    if not plain:
        return False, "no candidates to inspect"

    excluded = set(range(jump_at - 2, jump_at + 3))
    inside = [c for c in guarded if c.confirm_bar in excluded]
    if inside:
        return False, (
            f"{len(inside)} candidates were confirmed inside the roll window"
        )
    dropped = len(plain) - len(guarded)
    if dropped <= 0:
        return False, "the roll guard dropped nothing"

    # and the jump itself must not be read as a sweep
    from dodgys_dd_quant.strategy.state_machine import _sweep_events
    from dodgys_dd_quant.strategy.structure import causal_pivots

    pivots = causal_pivots(rolled.high, rolled.low, left=2, right=2)
    events = _sweep_events(rolled, pivots, base)
    fake = [ev for ev in events if ev.bar in excluded]
    if fake:
        return False, f"{len(fake)} sweeps were read inside the roll window"
    return True, (
        f"the roll guard dropped {dropped} candidates and suppressed every "
        f"sweep inside the jump"
    )
