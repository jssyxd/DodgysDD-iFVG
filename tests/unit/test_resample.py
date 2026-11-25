"""The data-lane builders: strict timeframes, month ranges, checksum policy.

The bug these tests pin: a partial bucket must never be emitted.  A 30-minute
bar missing one of its six 5-minute bars is not an observation of the market,
it is a gap wearing a bar's clothes -- and the lake's contract forbids exactly
that ("no synthetic forward-fill").
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from dodgys_dd_quant.data_pipeline.audit import audit_frame
from dodgys_dd_quant.data_pipeline.pull_exchange import (
    Months,
    _verify_checksum,
)
from dodgys_dd_quant.data_pipeline.resample import (
    build_timeframes,
    interval_minutes,
    resample_ohlcv,
)

MINUTE = 60_000


def _frame(ts_minutes: list[int], price: float = 100.0) -> pd.DataFrame:
    n = len(ts_minutes)
    return pd.DataFrame(
        {
            "ts_event": np.asarray(ts_minutes, dtype=np.int64) * MINUTE,
            "open": np.full(n, price),
            "high": np.full(n, price + 1.0),
            "low": np.full(n, price - 1.0),
            "close": np.full(n, price + 0.5),
            "volume": np.ones(n),
        }
    )


def test_interval_minutes_maps_every_requested_timeframe():
    assert [interval_minutes(tf) for tf in ("5m", "15m", "30m", "1h", "2h", "4h", "1d")] == [
        5, 15, 30, 60, 120, 240, 1440,
    ]
    with pytest.raises(ValueError):
        interval_minutes("7m")


def test_a_complete_bucket_is_aggregated_exactly():
    # exactly one complete 5-minute bucket: minutes 0..4
    bars, incomplete = resample_ohlcv(_frame(list(range(5))), 5, base_minutes=1)
    assert incomplete == 0
    assert len(bars) == 1
    assert bars.iloc[0]["volume"] == pytest.approx(5.0)
    assert bars.iloc[0]["high"] == pytest.approx(101.0)
    assert bars.iloc[0]["ts_event"] == 0


def test_an_incomplete_bucket_is_dropped_and_counted():
    # minutes 0..3 and 5..9: the 0-5 bucket misses minute 4
    bars, incomplete = resample_ohlcv(_frame([0, 1, 2, 3, 5, 6, 7, 8, 9]), 5, base_minutes=1)
    assert incomplete == 1
    assert len(bars) == 1
    assert bars.iloc[0]["ts_event"] == 5 * MINUTE


def test_five_minute_base_to_thirty_minutes():
    source = _frame(list(range(0, 60, 5)))  # twelve 5m bars = two 30m buckets
    bars, incomplete = resample_ohlcv(source, 30, base_minutes=5)
    assert incomplete == 0
    assert len(bars) == 2
    assert bars.iloc[0]["volume"] == pytest.approx(6.0)


def test_a_non_ascending_source_raises():
    with pytest.raises(ValueError, match="strictly ascending"):
        resample_ohlcv(_frame([0, 2, 1, 3, 4]), 5, base_minutes=1)


def test_build_timeframes_refuses_a_missing_base_lane(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_timeframes("NOPEUSDT", ["5m"], lake_root=tmp_path)


def test_the_auditor_accepts_the_lakes_canonical_ts_event_column():
    report = audit_frame(_frame(list(range(5))))
    assert report.passed


def test_months_iterates_inclusively_and_rejects_a_backwards_range():
    months = list(Months("2023-11", "2024-02"))
    assert months == ["2023-11", "2023-12", "2024-01", "2024-02"]
    assert len(Months("2023-11", "2024-02")) == 4
    with pytest.raises(ValueError):
        Months("2024-02", "2023-11")


def test_a_checksum_mismatch_is_fatal():
    payload = b"not the file"
    published = hashlib.sha256(b"a different file").hexdigest().encode() + b"  x.zip\n"
    with pytest.raises(ValueError, match="checksum mismatch"):
        _verify_checksum(payload, published, "x.zip")
    good = hashlib.sha256(payload).hexdigest().encode() + b"  x.zip\n"
    _verify_checksum(payload, good, "x.zip")  # must not raise
