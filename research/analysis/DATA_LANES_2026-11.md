Data lanes, 2026-11-24 — what was pulled and what it verified
=============================================================

Sources and their verdicts (measured, not assumed)
--------------------------------------------------
| source | endpoint | verdict |
|---|---|---|
| **Binance Vision** | `data.binance.vision/data/futures/um/monthly/klines/{SYM}/{TF}/` | **works**; each file carries a published `.CHECKSUM` (SHA-256), verified on every download |
| **Binance Vision** | `.../monthly/fundingRate/{SYM}/` | **works** (≈1 KB/month) |
| **Binance Vision** | `.../monthly/metrics/{SYM}/` | **404** — metrics exist only as **daily** files (`.../daily/metrics/...`), so open interest was **not** pulled (1,400 files/symbol would be needed) |
| **OKX** | `/api/v5/public/funding-rate-history` | works, but the endpoint exposes only ≈**96 days** (289 rows at 8 h); its pagination is **inverted**: `after` returns *older* records, `before` returns page 1 again (measured: `after` overlap 0, `before` overlap 99) |
| **cryptohftdata** | `https://cryptohftdata.com/` / `data.cryptohftdata.com` | **unreachable**: site 307 redirect, data host TLS `UNEXPECTED_EOF_WHILE_READING` — the same TLS failure the earlier audit recorded |

What is now in the lake
-----------------------
All partitions are governed: `ts_event` int64 **ms**, left-open, strictly
monotonic, deduplicated, Zstd-7, atomic rename, **audited** (the five lake
invariants plus the flat-bar corollary) before publication.

**Pulled from Binance Vision** (5m klines, 2023-01 → 2026-10):

| symbol | rows | range |
|---|---|---|
| BTCUSDT | 409,248 | 2023-01-01 → 2026-10-31 (+1) |
| ETHUSDT | 409,248 | 2023-01-01 → 2026-10-31 |
| SOLUSDT | 403,200 | 2023-01-01 → 2026-10-31 |
| BNBUSDT | 403,200 | 2023-01-01 → 2026-10-31 |
| XRPUSDT | 403,200 | 2023-01-01 → 2026-10-31 |

**Derived by strict resampling** (complete buckets only; 0 incomplete buckets
dropped for every symbol/timeframe):

| timeframe | BTC/ETH (from 1m) | SOL/BNB/XRP (from 5m) |
|---|---|---|
| 5m | 409,248 | 403,200 (pulled) |
| 15m | 136,416 | 134,400 |
| 30m | 68,208 | 67,200 |
| 1h | 34,104 | 33,600 |
| 2h | 17,052 | 16,800 |
| 4h | 8,526 | 8,400 |
| 1d | 1,421 | 1,400 |

Range: BTC/ETH 2023-01-01 → 2026-11-21 (the 1m lane runs to 2026-11-21);
SOL/BNB/XRP 2023-01-01 → 2026-10-31.

**Indicators**

| series | venue | rows | range |
|---|---|---|---|
| `BTCUSDT_funding_rate` | Binance | 4,200 (8 h) | 2023-01 → 2026-10 |
| `ETHUSDT_funding_rate` | Binance | 4,200 | 2023-01 → 2026-10 |
| `SOLUSDT_funding_rate` | Binance | 4,200 | 2023-01 → 2026-10 |
| `BNBUSDT_funding_rate` | Binance | 4,200 | 2023-01 → 2026-10 |
| `XRPUSDT_funding_rate` | Binance | 4,200 | 2023-01 → 2026-10 |
| `{BTC,ETH,SOL}USDT_okx_funding` | OKX | 289 each | ≈2026-08 → 2026-11 (venue cap) |

Cross-verification: the exchange's own lanes vs the resampled ones
------------------------------------------------------------------
The lake already carried a few higher-timeframe lanes.  They are an
**independent aggregation of the same 1m market**, so they are the check on
the resampler (and are never replaced):

| pair | bars matched | differing bars | max |delta| |
|---|---|---|---|
| BTC 15m consolidated (2024-01→2026-10) vs resampled | 98,139 | 8-16 (close/volume) | 204.4 (close) / 3,476 (volume) |
| SOL 15m consolidated vs resampled | 98,139 | 8-15 | 0.27 (close) / 148,492 (volume) |
| BNB 15m consolidated vs resampled | 98,139 | few | volume only (11,273) |
| XRP 15m consolidated vs resampled | 2,976 (one month vs 134,400) | ~0 | 6e-8 (float noise) |
| 1h / 4h / 1d (BTC, ETH, SOL) | all | 0 | ≤1.7e-9 (float noise) |

Reading: on the overlapping window the two agree to the last decimal except
for **8–16 bars out of 98,139** (0.01 %), all at the edges of the legacy
window.  The volume column is the one that differs where it differs, which is
what an exchange's last-bar update produces.

**A discovery about the legacy lanes:** most of them are one-month stubs —
`BTCUSDT_4h_consolidated` holds 186 bars, `BTCUSDT_1d_consolidated` 31, and
ETH/SOL/BNB/XRP 1h/4h/1d are 744/186/31 bars each, all covering 2024-01 only.
Every experiment that needed a multi-year higher timeframe therefore had to
come from 1m (BTC/ETH) or could not run at all (the altcoins).  That gap is
what these partitions close.

Operational hazards found
-------------------------
1. **Two writers on the NFS tree corrupt files.** A concurrent pull batch left
   16 partitions that answered `EACCES` on read for *every* client, root
   included, with mode `0777`; only delete-and-rewrite recovered them.  The
   writer now takes an exclusive `flock` per partition and **reads the Parquet
   metadata back** after the rename, retrying with a fresh inode.  Full note in
   `.field-guide/env.md`.
2. **Reads glitch while a writer is active.** A `pyarrow` metadata read during
   an active pull intermittently raised `ArrowInvalid`, while the same file
   read cleanly once the writer finished.  Verify partitions with no writer
   running.
3. `load_bars` and `audit_frame` accepted only the legacy column name
   `timestamp`; both now accept the lake's canonical `ts_event` (the resampled
   lanes use it), so the runner can be pointed at any partition.

Consumption
-----------
* `dodgys_dd_quant.data_pipeline.pull_exchange` — klines / funding / OKX;
* `dodgys_dd_quant.data_pipeline.resample` — strict higher timeframes;
* the runner reads a partition with `--data <path>` (otherwise it resolves the
  lake's `_consolidated` lane, which for BTC/ETH 15m is the shorter legacy
  lane, and for 4h/1d is a stub — pass the `_resampled` path explicitly until
  the lane is republished under the canonical name).
