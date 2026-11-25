"""The Nautilus backtest configuration, built and executed.

The audit left the engine configuration unverified in the installed API:

    *"[UNVERIFIED] -- A minimal working backtest JSON for NQ+ES 1-minute bars
    with venue fees and slippage is [UNVERIFIED] -- it must be built and
    executed before it is trusted."*

These probes do exactly that: the configuration is built from the repo's own
instrument definitions and cost model, it is decoded with **Nautilus's own**
msgspec decoder, and the backtest is actually run over the catalog.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from bench.probes import register

__all__ = []


def _bundle(root: Path, instrument: str = "NQ") -> Path:
    """Build the catalog and the configuration bundle in a temporary root."""
    from bench import fixtures

    from dodgys_dd_quant.data_pipeline.backtest_config import write_backtest_config_bundle
    from dodgys_dd_quant.data_pipeline.prepare_parquet import (
        CME_CONTRACT_SPECS,
        cme_contract,
        write_catalog,
    )

    bars = fixtures.btc_1m()
    contract = cme_contract(CME_CONTRACT_SPECS[instrument])
    catalog = write_catalog(
        bars, instrument=contract, catalog_path=root / "catalog"
    )
    return write_backtest_config_bundle(
        root,
        catalog_path=catalog,
        instrument_ids=[f"{instrument}.XCME"],
        commission=4.50,
    )


@register(
    "data.backtest_config_decodes_with_nautilus",
    "rolling",
    45,
    "the backtest configuration decodes with Nautilus's own decoder and carries the cost model",
)
def _config_decodes() -> tuple[bool, str]:
    """The configuration is a **list** and its venue carries the models.

    Nautilus 1.221's config layer is msgspec JSON (no YAML), the venue
    refers to its fill and fee models by ``module:Class`` path, and the
    instance id must be a version-4 UUID.
    """
    from dodgys_dd_quant.data_pipeline.backtest_config import config_from_json

    with tempfile.TemporaryDirectory() as tmp:
        path = _bundle(Path(tmp))
        payload = path.read_text(encoding="utf-8")
        decoded = config_from_json(payload)
        if len(decoded) != 1:
            return False, f"the configuration holds {len(decoded)} runs, expected 1"
        config = json.loads(payload)[0]
        venue = config["venues"][0]
        if "OneTickSlippageFillModel" not in venue.get("fill_model", {}).get(
            "fill_model_path", ""
        ):
            return False, "the venue does not use the one-tick slippage fill model"
        if "FixedFeeModel" not in venue.get("fee_model", {}).get(
            "fee_model_path", ""
        ):
            return False, "the venue does not use the fixed fee model"
        commission = venue.get("fee_model", {}).get("config", {}).get("commission", "")
        if "4.50" not in commission:
            return False, f"the venue's commission is {commission!r}, expected $4.50"
        instance = config["engine"]["instance_id"]
        if len(instance) != 36 or instance[14] != "4":
            return False, f"the instance id {instance!r} is not a version-4 UUID"
    return True, (
        "the configuration decodes with Nautilus's decoder and carries the "
        "one-tick fill model and the fixed fee"
    )


@register(
    "data.nautilus_backtest_runs_the_catalog",
    "rolling",
    50,
    "the Nautilus backtest actually runs over the catalog the ingest writes",
)
def _backtest_runs() -> tuple[bool, str]:
    """The smoke test the API doc asks for: the configuration is executed.

    The run goes through the shipped entry point
    (``python -m nautilus_trader.backtest --raw <json>``), so it exercises the
    catalog, the data client, the venue and the engine's lifecycle.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = _bundle(Path(tmp))
        payload = path.read_text(encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "nautilus_trader.backtest", "--raw", payload],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmp,
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
            return False, f"the backtest failed: {' | '.join(tail)}"
        if "BacktestEngine" not in (result.stdout + result.stderr):
            return False, "the backtest produced no engine output"
    return True, "the Nautilus backtest ran over the catalog and disposed cleanly"


@register(
    "data.backtest_config_is_reproducible",
    "rolling",
    35,
    "the same configuration bytes twice: the instance id is derived, not random",
)
def _config_reproducible() -> tuple[bool, str]:
    """A random instance id would make every run a different run."""
    from dodgys_dd_quant.data_pipeline.backtest_config import (
        deterministic_instance_id,
    )

    first = deterministic_instance_id("catalog|NQ.XCME|1-MINUTE-LAST-EXTERNAL")
    second = deterministic_instance_id("catalog|NQ.XCME|1-MINUTE-LAST-EXTERNAL")
    other = deterministic_instance_id("catalog|ES.XCME|1-MINUTE-LAST-EXTERNAL")
    if first != second:
        return False, "the instance id is not deterministic"
    if first == other:
        return False, "two different configurations share an instance id"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # the same root twice: the same catalog path, the same seed, the same
        # instance id -- so the bytes must match
        one = _bundle(root).read_text(encoding="utf-8")
        two = _bundle(root).read_text(encoding="utf-8")
        if one != two:
            return False, "two builds of the same configuration differ"
    return True, "the same configuration always produces the same instance id"
