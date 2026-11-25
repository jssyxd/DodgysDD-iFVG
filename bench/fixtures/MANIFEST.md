# Benchmark fixtures

Every dataset the benchmark uses is committed here as a gzip-compressed CSV so
the benchmark runs **offline and deterministically**, with no mount of the
governed NFS lake and no network.

The files are **read-only slices of the governed lake** (`/home/da/iflow_lake/.../03_governed_lake/v2_parquet_lake/`).
Nothing was written back: the lake's governance contract (monotone UTC
timestamps, no duplicates, `High >= max(Open, Close)`, `Low <= min(Open, Close)`,
strictly positive prices, `Volume >= 0`) is preserved by construction, because
the slices are copied verbatim.

## Format

```
ts_ms,o,h,l,c,v
```

| column | meaning |
|---|---|
| `ts_ms` | the bar's **open** time, int64 milliseconds since the epoch (the lake's left-open convention) |
| `o,h,l,c` | the prices in **integer cents** -- exact, and text-compressible |
| `v` | the volume, rounded to an integer |

`bench/fixtures.py` reconstructs the nanosecond time index and the float
prices on load.

## Files

| file | source partition | rows | span |
|---|---|---|---|
| `btcusdt_1m_2023q1.csv.gz` | `crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet` | 84,960 | 2023-01-01 → 2023-03-01 |
| `ethusdt_1m_2023q1.csv.gz` | `crypto/futures_um/ETHUSDT/1m/ETHUSDT_1m_consolidated.parquet` | 84,960 | 2023-01-01 → 2023-03-01 |
| `btcusdt_15m_2024_2026.csv.gz` | `crypto/futures_um/BTCUSDT/15m/BTCUSDT_15m_consolidated.parquet` | 98,139 | 2024-01-01 → 2026-10-16 |
| `qqq_15m.csv.gz` | `us_equities/QQQ/15m/QQQ_15m_consolidated.parquet` | 73,325 | 2022-10-14 → 2026-10-14 |
| `vxn_1d.csv.gz` | `macro/vxn/VXN_1d_consolidated.parquet` | 4,327 | 2009-09-14 → 2026-11-20 |

`ETHUSDT` is the **SMT reference instrument** for the BTC series (the doc
assigns ES/YM to NQ and BTC↔ETH to crypto), so the SMT probes have a real
second series to compare against.

## Why these spans

* **BTCUSDT 1m 2023 Q1** -- the engine's primary lane. 84,960 bars is a
  quarter of real 1-minute crypto: enough for thousands of candidates, a full
  walk-forward fold set, and an SMT cross-check.
* **BTCUSDT 15m 2024-2026** -- a longer, coarser lane for the rolling
  backtest, where the 6/1/1 monthly fold geometry needs more than a quarter.
* **QQQ 15m** -- the only long US-equity intraday sample in the lake, and the
  series L3 §C.7 nominates for the regime-correlation experiment (M-E1).
* **VXN 1d** -- the CBOE official daily close, the regime index itself.

## Regenerating

```bash
python3 - <<'PY'
import gzip, io, os
import numpy as np, pyarrow.parquet as pq
L = "/home/da/iflow_lake/iflow/database/03_governed_lake/v2_parquet_lake"
OUT = "bench/fixtures"
def write(name, df):
    buf = io.StringIO(); buf.write("ts_ms,o,h,l,c,v\n")
    ts = df["timestamp"].to_numpy()
    o = np.round(df["open"].to_numpy()*100).astype(np.int64)
    h = np.round(df["high"].to_numpy()*100).astype(np.int64)
    l = np.round(df["low"].to_numpy()*100).astype(np.int64)
    c = np.round(df["close"].to_numpy()*100).astype(np.int64)
    v = np.round(df["volume"].to_numpy()).astype(np.int64)
    for i in range(len(ts)):
        buf.write(f"{int(ts[i])},{int(o[i])},{int(h[i])},{int(l[i])},{int(c[i])},{int(v[i])}\n")
    with gzip.open(f"{OUT}/{name}.csv.gz", "wb", compresslevel=9) as f:
        f.write(buf.getvalue().encode())
def load(rel):
    return pq.read_table(f"{L}/{rel}").to_pandas()
btc1m = load("crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet")
write("btcusdt_1m_2023q1", btc1m[(btc1m.timestamp>=1672531200000)&(btc1m.timestamp<1677628800000)])
eth1m = load("crypto/futures_um/ETHUSDT/1m/ETHUSDT_1m_consolidated.parquet")
write("ethusdt_1m_2023q1", eth1m[(eth1m.timestamp>=1672531200000)&(eth1m.timestamp<1677628800000)])
btc15m = load("crypto/futures_um/BTCUSDT/15m/BTCUSDT_15m_consolidated.parquet")
write("btcusdt_15m_2024_2026", btc15m)
write("qqq_15m", load("us_equities/QQQ/15m/QQQ_15m_consolidated.parquet"))
vxn = load("macro/vxn/VXN_1d_consolidated.parquet")
v = vxn[["timestamp","close"]].copy()
v["open"]=v["close"]; v["high"]=v["close"]; v["low"]=v["close"]; v["volume"]=0
write("vxn_1d", v)
PY
```
