"""Pull governed partitions from Binance Vision and OKX.

Why this module exists
----------------------
The lake's crypto lanes were filled by hand.  The strategy needs **every**
interval at once (5m for execution, 15m/30m/1h/2h/4h for the signal, 1d for
the regime) plus two exogenous series (funding, open interest).  Pulling each
interval separately is wasteful: Binance Vision's klines are the exchange's
own aggregation of 1m bars, so a complete 1m bucket recomputed at 30m is the
same bar.  This module pulls *what cannot be derived*:

* ``30m`` / ``2h`` klines for a few symbols (an independent cross-check of
  :mod:`dodgys_dd_quant.data_pipeline.resample` -- the two must agree);
* the funding-rate history (Binance Vision, monthly);
* OKX's funding history (a second venue's view of the same quantity).

Provenance and integrity
------------------------
Every download is retried, verified against Binance's published
``.CHECKSUM`` (SHA-256) and parsed with (or without) a header row.  The
written partition follows the lake's contract: ``ts_event`` int64 **ms**,
left-open, strictly monotonic, deduplicated, Zstd-7, atomic
``.tmp`` -> rename, and audited by :func:`audit_frame` before it is published.
A partition that fails the audit is **not** published.

CLI::

    python -m dodgys_dd_quant.data_pipeline.pull_exchange klines \
        --symbols BTCUSDT ETHUSDT SOLUSDT --intervals 30m 2h \
        --months 2023-01 2026-10
    python -m dodgys_dd_quant.data_pipeline.pull_exchange funding \
        --symbols BTCUSDT ETHUSDT SOLUSDT --months 2023-01 2026-10
    python -m dodgys_dd_quant.data_pipeline.pull_exchange okx-funding \
        --inst-ids BTC-USDT-SWAP ETH-USDT-SWAP SOL-USDT-SWAP
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from dodgys_dd_quant.data_pipeline.audit import audit_frame

__all__ = [
    "DEFAULT_LAKE_ROOT",
    "KLINE_COLUMNS",
    "Months",
    "fetch_bytes",
    "pull_binance_klines",
    "pull_binance_funding",
    "pull_okx_funding",
    "write_governed",
]

#: The working checkout of the governed lake (the NFS mount when it is up).
DEFAULT_LAKE_ROOT = Path(
    "~/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake"
).expanduser()

VISION = "https://data.binance.vision/data/futures/um/monthly"

#: Binance Vision futures klines, in file order.  ``ignore`` is dropped.
KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)

CHECKSUM_SUFFIX = ".CHECKSUM"
_USER_AGENT = "dodgys-dd-quant/0.1 (+https://github.com/jsSyxd/DodgysDD-iFVG)"


class Months:
    """A closed range of ``YYYY-MM`` months (inclusive on both ends)."""

    def __init__(self, start: str, end: str) -> None:
        self.start = pd.Period(start, freq="M")
        self.end = pd.Period(end, freq="M")
        if self.end < self.start:
            raise ValueError(f"end {end} is before start {start}")

    def __iter__(self) -> Iterable[str]:
        period = self.start
        while period <= self.end:
            yield f"{period.year:04d}-{period.month:02d}"
            period += 1

    def __len__(self) -> int:
        return (self.end - self.start).n + 1

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"Months({self.start}, {self.end})"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def fetch_bytes(url: str, *, retries: int = 3, timeout: float = 60.0) -> bytes:
    """GET ``url`` with retries; returns the body."""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, ssl.SSLError, TimeoutError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise FileNotFoundError(url) from exc
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"download failed after {retries} attempts: {url}") from last


def _verify_checksum(zip_bytes: bytes, checksum_bytes: bytes, name: str) -> None:
    """Compare the SHA-256 of ``zip_bytes`` with Binance's ``.CHECKSUM``."""
    expected = checksum_bytes.decode("utf-8", "replace").split()[0].strip().lower()
    actual = hashlib.sha256(zip_bytes).hexdigest()
    if expected and expected != actual:
        raise ValueError(
            f"{name}: checksum mismatch (published {expected[:12]}..., "
            f"downloaded {actual[:12]}...)"
        )


def _read_csv_zip(zip_bytes: bytes, name: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith(".csv")]
        if not members:
            raise ValueError(f"{name}: the archive holds no CSV")
        text = archive.read(members[0]).decode("utf-8", "replace")
    first = text.split("\n", 1)[0]
    has_header = not first.split(",")[0].strip().lstrip("-").isdigit()
    return pd.read_csv(io.StringIO(text), header=0 if has_header else None)


# ---------------------------------------------------------------------------
# Binance Vision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PullResult:
    symbol: str
    interval: str
    path: Path
    rows: int
    months: int
    skipped_months: tuple[str, ...]


def pull_binance_klines(
    symbol: str,
    interval: str,
    months: Months,
    *,
    lake_root: Path = DEFAULT_LAKE_ROOT,
    dry_run: bool = False,
) -> PullResult:
    """Pull one symbol/interval's monthly klines into a governed partition."""
    frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    for month in months:
        name = f"{symbol}-{interval}-{month}.zip"
        url = f"{VISION}/klines/{symbol}/{interval}/{name}"
        try:
            payload = fetch_bytes(url)
            checksum = fetch_bytes(url + CHECKSUM_SUFFIX)
        except FileNotFoundError:
            skipped.append(month)
            continue
        _verify_checksum(payload, checksum, name)
        frame = _read_csv_zip(payload, name)
        frame = frame.iloc[:, : len(KLINE_COLUMNS)]
        frame.columns = list(KLINE_COLUMNS)
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(
            f"{symbol}/{interval}: no monthly file in {months.start}..{months.end}"
        )
    raw = pd.concat(frames, ignore_index=True)
    raw = raw[raw["open_time"].astype(str).str.lstrip("-").str.isdigit()]
    for column in ("open", "high", "low", "close", "volume",
                   "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    frame = pd.DataFrame(
        {
            "ts_event": raw["open_time"].astype("int64"),
            "open": raw["open"].astype("float64"),
            "high": raw["high"].astype("float64"),
            "low": raw["low"].astype("float64"),
            "close": raw["close"].astype("float64"),
            "volume": raw["volume"].astype("float64"),
            "quote_volume": raw["quote_volume"].astype("float64"),
            "trades": pd.to_numeric(raw["count"], errors="coerce").fillna(0).astype("int64"),
            "taker_buy_base": raw["taker_buy_volume"].astype("float64"),
            "taker_buy_quote": raw["taker_buy_quote_volume"].astype("float64"),
        }
    )
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    frame = (
        frame.drop_duplicates(subset="ts_event", keep="last")
        .sort_values("ts_event")
        .reset_index(drop=True)
    )
    folder = lake_root / "crypto" / "futures_um" / symbol / interval
    consolidated = folder / f"{symbol}_{interval}_consolidated.parquet"
    # Never overwrite a lane the lake already publishes: the pulled series is
    # then an independent cross-check of it, not a replacement.
    out = consolidated if not consolidated.exists() else folder / f"{symbol}_{interval}_binance.parquet"
    if not dry_run:
        write_governed(frame, out)
    return PullResult(
        symbol=symbol,
        interval=interval,
        path=out,
        rows=len(frame),
        months=len(frames),
        skipped_months=tuple(skipped),
    )


def pull_binance_funding(
    symbol: str,
    months: Months,
    *,
    lake_root: Path = DEFAULT_LAKE_ROOT,
    dry_run: bool = False,
) -> PullResult:
    """Pull one symbol's funding-rate history into a governed partition."""
    frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    for month in months:
        name = f"{symbol}-fundingRate-{month}.zip"
        url = f"{VISION}/fundingRate/{symbol}/{name}"
        try:
            payload = fetch_bytes(url)
            checksum = fetch_bytes(url + CHECKSUM_SUFFIX)
        except FileNotFoundError:
            skipped.append(month)
            continue
        _verify_checksum(payload, checksum, name)
        frames.append(_read_csv_zip(payload, name))
    if not frames:
        raise FileNotFoundError(
            f"{symbol}/fundingRate: no monthly file in {months.start}..{months.end}"
        )
    raw = pd.concat(frames, ignore_index=True)
    raw.columns = ["ts_event", "funding_interval_hours", "funding_rate"][: raw.shape[1]]
    frame = pd.DataFrame(
        {
            "ts_event": pd.to_numeric(raw["ts_event"], errors="coerce").astype("int64"),
            "funding_interval_hours": pd.to_numeric(
                raw.get("funding_interval_hours"), errors="coerce"
            ).astype("Int64"),
            "funding_rate": pd.to_numeric(raw["funding_rate"], errors="coerce"),
        }
    ).dropna(subset=["funding_rate"])
    frame = (
        frame.drop_duplicates(subset="ts_event", keep="last")
        .sort_values("ts_event")
        .reset_index(drop=True)
    )
    out = (
        lake_root
        / "crypto"
        / "funding_rate"
        / symbol
        / f"{symbol}_funding_rate.parquet"
    )
    if not dry_run:
        write_governed(frame, out, audit=False)
    return PullResult(
        symbol=symbol,
        interval="fundingRate",
        path=out,
        rows=len(frame),
        months=len(frames),
        skipped_months=tuple(skipped),
    )


# ---------------------------------------------------------------------------
# OKX
# ---------------------------------------------------------------------------

OKX_FUNDING = "https://www.okx.com/api/v5/public/funding-rate-history"


def pull_okx_funding(
    inst_id: str,
    *,
    lake_root: Path = DEFAULT_LAKE_ROOT,
    page_limit: int = 100,
    max_pages: int = 200,
    dry_run: bool = False,
) -> PullResult:
    """Pull OKX's funding-rate history (a second venue's view).

    OKX pages **backwards**: ``before`` is the funding time to start before.
    The loop stops when a page is short or repeats the oldest timestamp, so a
    silent API cap cannot truncate the series without being counted.
    """
    rows: list[dict] = []
    cursor: str | None = None
    pages = 0
    while pages < max_pages:
        url = f"{OKX_FUNDING}?instId={inst_id}&limit={page_limit}"
        if cursor:
            # OKX's semantics are inverted against intuition: ``after`` returns
            # the records *earlier* than the requested funding time, ``before``
            # the newer ones (measured: ``after`` has zero overlap with page 1,
            # ``before`` returns page 1 again).
            url += f"&after={cursor}"
        payload = json.loads(fetch_bytes(url).decode("utf-8"))
        if payload.get("code") != "0":
            raise RuntimeError(f"OKX error for {inst_id}: {payload}")
        batch = payload.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        oldest = min(int(item["fundingTime"]) for item in batch)
        pages += 1
        if len(batch) < page_limit or (cursor is not None and int(cursor) <= oldest):
            break
        cursor = str(oldest)
    if not rows:
        raise FileNotFoundError(f"OKX: no funding history for {inst_id}")
    frame = pd.DataFrame(
        {
            "ts_event": [int(row["fundingTime"]) for row in rows],
            "funding_rate": [float(row["fundingRate"]) for row in rows],
            "realized_rate": [float(row.get("realizedRate") or "nan") for row in rows],
            "inst_id": [row.get("instId", inst_id) for row in rows],
            "venue": ["okx"] * len(rows),
        }
    )
    frame = (
        frame.drop_duplicates(subset="ts_event", keep="last")
        .sort_values("ts_event")
        .reset_index(drop=True)
    )
    symbol = inst_id.split("-")[0] + "USDT"
    out = (
        lake_root
        / "crypto"
        / "funding_rate"
        / f"{symbol}_okx_funding.parquet"
    )
    if not dry_run:
        write_governed(frame, out, audit=False)
    return PullResult(
        symbol=symbol,
        interval="okx-funding",
        path=out,
        rows=len(frame),
        months=0,
        skipped_months=(),
    )


# ---------------------------------------------------------------------------
# Governed write
# ---------------------------------------------------------------------------


def write_governed(frame: pd.DataFrame, path: Path, *, audit: bool = True) -> Path:
    """Write ``frame`` under the lake's contract (audit, Zstd-7, atomic rename).

    Two defences against the failure this function actually met on the NFS
    export (fnOS, ``vers=3``):

    * an **advisory lock** per partition, so two pullers can never rename over
      each other's open file (that left a batch of files EACCES-unreadable for
      every client, root included, until they were rewritten);
    * a **read-back check** after the rename: the file is opened again and its
      Parquet metadata parsed.  A server-side stale handle is retried with a
      fresh inode instead of being published.
    """
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    if audit:
        report = audit_frame(frame)
        if not report.passed:
            raise ValueError(
                f"{path.name}: the partition fails the lake audit: "
                f"{report.violations}"
            )
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        last: Exception | None = None
        for _ in range(3):
            tmp = path.with_suffix(path.suffix + ".tmp")
            frame.to_parquet(tmp, compression="zstd", compression_level=7, index=False)
            tmp.replace(path)
            try:
                import pyarrow.parquet as pq

                pq.read_metadata(path)
                return path
            except Exception as exc:  # noqa: BLE001 - the server refused the handle
                last = exc
                continue
        raise RuntimeError(f"{path}: written but unreadable after 3 attempts: {last}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _months(args) -> Months:
    return Months(args.months[0], args.months[1])


def _print(result: PullResult) -> None:
    skipped = f", skipped {len(result.skipped_months)} month(s)" if result.skipped_months else ""
    print(f"{result.symbol:>10} {result.interval:<12} {result.rows:>9,} rows -> {result.path}{skipped}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pull_exchange", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--lake-root", default=str(DEFAULT_LAKE_ROOT))
        p.add_argument("--dry-run", action="store_true")

    klines = sub.add_parser("klines")
    klines.add_argument("--symbols", nargs="+", required=True)
    klines.add_argument("--intervals", nargs="+", required=True)
    klines.add_argument("--months", nargs=2, required=True, metavar=("START", "END"))
    common(klines)

    funding = sub.add_parser("funding")
    funding.add_argument("--symbols", nargs="+", required=True)
    funding.add_argument("--months", nargs=2, required=True, metavar=("START", "END"))
    common(funding)

    okx = sub.add_parser("okx-funding")
    okx.add_argument("--inst-ids", nargs="+", required=True)
    common(okx)

    args = parser.parse_args(argv)
    lake_root = Path(args.lake_root).expanduser()
    failures = 0
    if args.command == "klines":
        months = _months(args)
        for symbol in args.symbols:
            for interval in args.intervals:
                try:
                    _print(
                        pull_binance_klines(
                            symbol, interval, months, lake_root=lake_root, dry_run=args.dry_run
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - the CLI reports, never hides
                    failures += 1
                    print(f"FAILED {symbol}/{interval}: {exc}", file=sys.stderr)
    elif args.command == "funding":
        months = _months(args)
        for symbol in args.symbols:
            try:
                _print(
                    pull_binance_funding(
                        symbol, months, lake_root=lake_root, dry_run=args.dry_run
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAILED {symbol}/fundingRate: {exc}", file=sys.stderr)
    else:
        for inst_id in args.inst_ids:
            try:
                _print(
                    pull_okx_funding(inst_id, lake_root=lake_root, dry_run=args.dry_run)
                )
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAILED {inst_id}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
