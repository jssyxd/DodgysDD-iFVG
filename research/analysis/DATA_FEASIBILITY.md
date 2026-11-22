# Data feasibility for the phase-1 gate

**Question:** do we have, or can we obtain, the data required to run a faithful 1-minute NQ+ES
event-driven backtest with realistic costs?

**Date of analysis:** 2026-11-22 (Sunday, host clock `CST +0800`).

**Verdict (one line):** **NO-GO today, GO achievable within ~1–2 weeks** — the governed lake *declares*
exactly the series we need (NQ/ES continuous, 1m) but its bytes live on an SMB share that is not
mounted and not authenticated from this machine, and the two Kaggle datasets in-repo cannot drive a
backtest at all.

**Single biggest data gap:** *time-aligned, provenance-documented NQ **and** ES 1-minute continuous
series over ≥3 years, with an explicit, testable roll rule.* The lake manifest promises it; nothing
reachable from this machine proves it. Everything else (VXN, fee/slippage model, sessions) is solvable
in days.

---

## 0. How to read this document

* Every row in §A carries an evidence path. If a fact could not be checked from this host it is
  written as **`UNVERIFIED — needs <specific command or access>`**.
* Nothing in §B–§C is inferred from a dataset's name. Where a dataset was inspected, the inspection
  method is stated (footer probe, column read, image view, grep).
* The **phase-1 gate** being tested is the one in `iFVG几个模型的讨论.txt` L170 / `AGENTS.md`:
  pure rule engine only, fixed 1:2 RR, A/A+ setups only, ~$4.5 round-turn fees, 1–2 ticks slippage,
  **Profit Factor > 1.25**. A negative pure-rule result means the rule reproduction is wrong and must
  never be masked by ML.

---

## A. Requirement checklist

Requirements are derived from `iFVG几个模型的讨论.txt` (the master design doc) and pinned by
`research/docs/RULE_SPEC.md` (690 lines, the authoritative rule spec with resolved ambiguities).

| # | Requirement | Source | Status | Evidence |
|---|---|---|---|---|
| A1 | **NQ 1-minute OHLCV, multi-year** | doc L169/L205; RULE_SPEC T47 | **PARTIAL** | *Declared:* `research/github/dataBaseLake/03_governed_lake/v2_parquet_lake/manifest/manifest.json` → `catalog.us_futures.symbols.NQ` = "E-mini Nasdaq 100 Continuous Futures", `timeframes: [1m,5m,15m,1h,2h,4h,1d]`, `path: us_futures/NQ/`. *Not reachable:* `research/github/dataBaseLake/03_governed_lake/v2_parquet_lake/us_futures/` contains only `.gitkeep` (0 B) — Parquet is git-ignored. *Free candidate exists but unproven:* HF `mdelcristo/NQ-F_1min_OHLCV_Parquet` — footer-probed: schema `timestamp: timestamp[ns]` (tz-**naive**), `open/high/low/close: double`, `volume: int64`; 11 yearly files `NQ_1min_2015…2025.parquet`, 49,906,336 B total; row counts 2015→329,886, 2020→348,461, 2025→195,610 (partial, ends 2025-07-25 02:14). |
| A2 | **Session boundaries (Asia/London/NY) + correct timezone** | doc L116, L115; RULE_SPEC A21, I08 | **PARTIAL** | No source ships session markers — all three candidate datasets are bare OHLCV. Sessions are *derivable* from UTC timestamps + a session table, but must be built. Timezone is a live trap: the community NQ file stores **`timestamp[ns]` with no tz**; its first bar is `23:00` on 2015-01-01, 2020-01-01 and 2025-01-01 (all EST months) — consistent with CME Globex 18:00 ET open, i.e. UTC wall-clock stored tz-naively. RULE_SPEC A21 pins `America/New_York` with DST, endpoint-inclusive; I08 flags the doc's own `EST` vs `ET` contradiction. |
| A3 | **ES 1-minute OHLCV for SMT, time-aligned to NQ** | doc L119, L169; RULE_SPEC T47 | **PARTIAL** | *Declared:* same manifest → `catalog.us_futures.symbols.ES` = "E-mini S&P 500 Continuous Futures", `path: us_futures/ES/`, same 7 timeframes. *Free candidate:* HF `Khanhpham1992/es-futures-1m` → `es_continuous_1m.parquet`; footer-probed: schema `instrument_id: large_string`, OHLC double, `volume: int64`, **`adj_open/adj_high/adj_low/adj_close`**, `datetime: timestamp[ns, tz=UTC]`; **646,948 rows, 2020-11-17 00:00 UTC → 2024-07-19 20:59 UTC**. `msj-21/es-futures-1m` is byte-identical in layout (282,386,358 B total). *Alignment to the NQ file is not established* — see §E1/E3. |
| A4 | **Continuous-contract definition + explicit roll-gap handling** | RULE_SPEC A22 ("a stated roll rule"); §E1 | **MISSING** | The lake manifest *names* the series "Continuous Futures" but **no source in this repo states the roll rule, the roll date, or the roll adjustment method**. The community NQ file has **no `instrument_id` and no adjusted columns** → any roll artefact is baked in and *unrecoverable*. The community ES file *does* carry `instrument_id` + `adj_*`, so its roll is identifiable but still undocumented. A roll gap can fabricate a liquidity sweep and a 3-candle FVG; without a roll rule this cannot be excluded. |
| A5 | **Tick size 0.25; multiplier; real fee model** | RULE_SPEC A22; `research/nautilus/NAUTILUS_API.md` §3 | **PARTIAL** | Tick 0.25, multiplier 20 (NQ) / 50 (ES), price_precision 2, lot_size 1, venue XCME — pinned in `research/nautilus/NAUTILUS_API.md:154-165` and RULE_SPEC A22. The **~$4.50 round-turn fee is a design-doc number with no named broker and no stated per-side/round-trip semantics** → `UNVERIFIED — needs the actual broker schedule (Rithmic / AMP / IB / Tradovate) and the intended commission basis`. Also note: 1–2 ticks of slippage on NQ is **$5.00–$10.00 per side** (0.25 × $20), so the true round-trip friction is ≈ **$14.50–$24.50**, not $4.50. The phase-1 gate must be run against the all-in number, not the commission alone. |
| A6 | **Slippage 1–2 ticks, configured in NautilusTrader** | doc L170; AGENTS.md "cost model belongs in the backtest config" | **PARTIAL** | The mechanism exists in the installed package: `nautilus_trader.backtest.models` exports `FillModel`, `MakerTakerFeeModel`, `FixedFeeModel` (verified by import under the 3.11 interpreter; `PercentageFeeModel` is **absent**); `nautilus_trader/backtest/config.py` references them. But `research/nautilus/NAUTILUS_API.md:242` records that **"a minimal working backtest JSON for NQ+ES 1-minute bars with venue fees and slippage is `[UNVERIFIED]`"**, and no NT model expresses slippage as "ticks" natively — it must be mapped onto the fill model. `UNVERIFIED — needs: python -c "from nautilus_trader.backtest.models import FillModel, MakerTakerFeeModel; help(FillModel); help(MakerTakerFeeModel)"` under the 3.11 interpreter, then a 20-bar smoke backtest proving a 1-tick adverse fill on a market order. |
| A7 | **History length for 6-mo train / 1-mo validate / 1-mo test + genuine OOS** | doc L143-L145; RULE_SPEC T47 | **AVAILABLE** | Length is *not* the binding constraint. Community NQ: 2015→2025-07 (10.5 y). Community ES: 2020-11→2024-07 (3.7 y) → ~28 rolling monthly windows + a held-out tail. Lake databank coverage is 2020-01-01→2026 (`research/github/dataBaseLake/03_governed_lake/nautilus_databank/MANIFEST.md`). |
| A8 | **VXN / equivalent regime series** | doc L207, L265-L267; RULE_SPEC T07-T10, T49, T50, A18 | **PARTIAL** | **Daily VXN: AVAILABLE and verified reachable** — `https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv` → HTTP 307 → `https://cdn-api.cboe.com/.../VXN_History.csv` → **HTTP 200, `content-type: text/csv`**, header `DATE,OPEN,HIGH,LOW,CLOSE`, first row `09/14/2009,26.410000,26.480000,24.810000,24.930000`. **Intraday VXN: MISSING** — CBOE's free file is daily only, and the doc's pipeline builds `yf.download("^VXN", …, interval="1d")`; the required **1-hour change rate** (T26) is therefore unsatisfiable from free data (RULE_SPEC A18: *"Do not fabricate… either fetch intraday VXN or drop the feature"*). `yfinance` is also not installed for 3.11. |
| A9 | **Contract roll artefacts excluded from rule decisions** | §E1 | **MISSING** | Depends on A4. Nothing in the repo implements or tests it. |
| A10 | **A second SMT reference instrument (YM)** | doc L119, L159 | **MISSING (not blocking)** | No YM series in the manifest or in any candidate. ES alone satisfies the rule; YM is optional. |
| A11 | **Order-book imbalance for RL state** | doc L151; RULE_SPEC T28 | **MISSING (phase-3 only)** | No L2/book data in the lake or candidates. Not required for the phase-1 gate. |

### A-snapshot

| Status | Items |
|---|---|
| **AVAILABLE** | A7 (history length) |
| **PARTIAL** | A1, A2, A3, A5, A6, A8 |
| **MISSING** | A4, A9 (roll rule — blocking), A10, A11 (non-blocking) |

**The phase-1 gate is blocked on exactly two things: a reachable NQ+ES 1-minute pair (A1/A3) and a
documented roll rule (A4/A9).** Everything else is days of work, not months.

---

## B. What the lake actually holds, and the governance that governs it

### B1. Reachability from this host — **NOT REACHABLE**

Verified on 2026-11-22:

| Check | Command | Result |
|---|---|---|
| Host alive | `ping -c 2 192.168.1.6` | ✅ 0% loss, avg **10.1 ms** rtt |
| SMB service | `cat < /dev/null > /dev/tcp/192.168.1.6/445` | ✅ **port 445 OPEN** |
| CIFS mount | `mount \| grep -Ei "cifs\|smb\|192.168"` | ❌ **empty — no CIFS/SMB mount exists** |
| Mount points | `ls -la /mnt /media` | `/mnt` contains only `t6`; `/media` is empty |
| GVFS | `ls /run/user/1000/gvfs/` | ❌ directory does not exist |
| Anonymous share list | `smbclient -L //192.168.1.6 -N` | ❌ `session setup failed: NT_STATUS_LOGON_FAILURE` |
| Anonymous share open | `smbclient //192.168.1.6/iflow -N -c "ls"` | ❌ `NT_STATUS_LOGON_FAILURE` |
| Tooling present | `which smbclient mount.cifs` | ✅ `/usr/bin/smbclient`, `/usr/bin/mount.cifs` |

**Conclusion: the SMB server is up and reachable on the network, but this machine holds no mount and
no credentials.** No SMB user/password is stored anywhere in the repo — `一些必备apikey和环境.txt`
contains only a GitHub token, an HF token, a Kaggle token and a cryptohftdata API key. I did **not**
attempt credential guessing.

Note also that the lake's own manifest points at a **different share sub-path** than the one in the
notes: `research/github/dataBaseLake/03_governed_lake/nautilus_databank/MANIFEST.md:4-5` records the
storage root as `/run/user/1000/gvfs/smb-share:server=192.168.1.6,share=iflow/数据库5/nautilus_databank`
and the catalog at `…/iflow/数据库5/nautilus_databank/catalog`, whereas `一些必备apikey与环境.txt` says
the lake is at `smb://192.168.1.6/iflow/database`. **Both `数据库5` ("database5") and `database` may
exist under the `iflow` share** — the exact layout must be discovered, not assumed.

### B2. Exact commands the captain must run (on a machine that can authenticate to the share)

```bash
# 0) obtain the SMB credentials for user @192.168.1.6 from the share owner (not in this repo)

# 1) mount read-only
sudo mkdir -p /mnt/iflow
sudo mount -t cifs //192.168.1.6/iflow /mnt/iflow \
  -o username=<user>,password=<pass>,vers=3.0,uid=$(id -u),gid=$(id -g),ro
#   NOTE: the governed-lake methodology warns that GVFS/SMB mounts do not support chmod or
#   unix file locks (research/github/dataBaseLake/03_governed_lake/nautilus_databank/skills/
#   quant-data-governance-engine/references/methodology.md §1) -> prefer a CIFS mount, not GVFS.

# 2) discover the real layout (database vs 数据库5)
find /mnt/iflow -maxdepth 2 -type d | sort
ls -la /mnt/iflow/

# 3) inventory the governed lake
LAKE=/mnt/iflow/database                       # or /mnt/iflow/数据库5 — whichever exists
du -sh "$LAKE"/* | sort -h
find "$LAKE" -maxdepth 3 -type d | sort

# 4) THE decisive check — do the declared NQ/ES 1-minute partitions actually exist?
ls -la "$LAKE"/03_governed_lake/v2_parquet_lake/us_futures/NQ/
ls -la "$LAKE"/03_governed_lake/v2_parquet_lake/us_futures/ES/
find "$LAKE" -path '*us_futures*' -name '*.parquet' | head -50

# 5) enumerate the Nautilus databank bar types (the 1-minute CME index types are what we need)
ls "$LAKE"/数据库5/nautilus_databank/catalog/data/bar/ 2>/dev/null \
  || ls "$LAKE"/nautilus_databank/catalog/data/bar/
ls "$LAKE"/nautilus_databank/catalog/data/bar/ | grep -E '^(NQ|ES)\.'

# 6) crypto lane inventory (phase-3 lane only)
find "$LAKE" -maxdepth 3 -type d -iname '*crypto*' | sort
```

### B3. What the lake *declares* (verified from the git clone)

From `research/github/dataBaseLake/03_governed_lake/v2_parquet_lake/manifest/manifest.json`
(v2.1.0, `last_updated_utc` 2026-10-20T16:55:18Z):

* `catalog.us_futures.market` = **"CME Equity Index Continuous Futures"**, `symbols_count: 4`:
  * `ES` — "E-mini S&P 500 Continuous Futures", `path: us_futures/ES/`, timeframes `1m,5m,15m,1h,2h,4h,1d`
  * `NQ` — "E-mini Nasdaq 100 Continuous Futures", `path: us_futures/NQ/`, timeframes `1m,5m,15m,1h,2h,4h,1d`
  * `MBT` — Micro Bitcoin Futures (CME), `5m,15m,1h,2h`
  * `MET` — Micro Ether Futures (CME), `5m,15m,1h,2h`
* `catalog.us_equities` — QQQ / SPY / TQQQ (`1m…1d`).
* `catalog.global_futures` — CL, GC, ZN, FDAX, HSI, NK225.
* `catalog.crypto` — 30 USDT-M perpetuals; `catalog.crypto_indices` — CMC20.

**But the bytes are not in the clone.** `03_governed_lake/v2_parquet_lake/{us_futures,global_futures,us_equities,crypto}/`
each hold only a 0-byte `.gitkeep`; `.gitignore` excludes `*.parquet` and the whole
`03_governed_lake/nautilus_databank/{catalog/data,commodities,crypto,equities_indices,fx,metals,rates_bonds}/`
tree. The lake is restored from the SMB share (or via `bootstrap_lake.py`), not from git.

### B4. What the *other* lake manifest says — and it contradicts the optimistic reading

`research/github/dataBaseLake/03_governed_lake/nautilus_databank/MANIFEST.md` enumerates the **63
Nautilus BarTypes / 42,278,836 bars / 1.02 GB** actually indexed in the databank (storage root
`…/iflow/数据库5/nautilus_databank`, coverage 2020-01-01→2026). Its universe table lists:

* `NQ.CME-1-DAY-LAST-EXTERNAL` — 1-Day, 7 chunks, 2020-01-02→2026-09-25, 1,695 bars, 0.11 MB
* `ES.CME-1-DAY-LAST-EXTERNAL` — 1-Day, 7 chunks, 2020-01-02→2026-09-25, 1,695 bars, 0.11 MB

**There is no 1-minute CME index-futures bar type in the databank.** The 1-minute bar types in that
manifest are crypto (BTC/ETH/SOL/XRP/BNB/DOGE), FX (EURUSD/GBPUSD/USDJPY/USDCHF/USDCNY), metals
(SILVER/XPDUSD/XPTUSD/XAUCNH/GOLD), and **US equities/ETFs** (QQQ 1,304,397 bars; SPY 1,281,134; IWM
1,117,000; SLV/TLT/IEF/GLD/USO/UNG/PAXGUSDT). NQ and ES exist there **daily only**.

**Read this carefully before planning:** the `v2_parquet_lake` *manifest* advertises NQ/ES at 1m, but
the only *index* of actually-materialised data (the Nautilus databank MANIFEST.md) shows CME index
futures at **1-Day**. Either the `us_futures/` 1m partitions exist on the share and were never
back-filled into the databank, or the manifest is aspirational. **Command B2 step 4 settles it.**
This is the single highest-value 5-minute action in the whole plan.

### B5. Governance rules any new data must satisfy

**Contract (`manifest.json` → `governance_contract`), quoted:**

* `"time_index_definition": "UTC Unix Timestamp int64 milliseconds (Left-aligned Bar Open Time)"`
* `"timestamp_unit": "milliseconds"`, `"alignment_rule": "left_open_time"`
* `"lookahead_bias_guarantee": true`
* `supported_timeframes: ["1m","5m","15m","1h","2h","4h","1d"]`
* `mandatory_columns`: `timestamp` (int64, bar **open** time, ms since UTC epoch), `datetime`
  (string ISO UTC), `open/high/low/close` (float64), `volume` (float64), `quote_volume`,
  `taker_buy_volume` (crypto-specific)
* `storage_specification`: `primary_format: parquet`, `compression: zstd`, `compression_level: 7`,
  `row_group_target: 100000`

**Mathematical invariants (`README.md` §4 "数据治理契约与五大数学不变量"), quoted:**

1. 时间戳严格单调性：$ts_i > ts_{i-1}$，纳秒级 UTC 严格单调递增
2. 彻底去重：杜绝时间戳碰撞与重复记录
3. K 线几何有效性：$High \ge \max(Open, Close)$ 且 $Low \le \min(Open, Close)$
4. 价格正值性：$Open, High, Low, Close > 0$
5. 成交量非负性：$Volume \ge 0$
6. 真实断点治理：加密货币 24/7 真实行情中断记录入 `defects.json`，**严禁前向伪造合成插值**；股票期货严格根据法定交易所日历对齐交易时段

> Translation of the binding clause: **real breaks are recorded in `defects.json`; synthesising
> forward-filled interpolation is strictly forbidden; equity/future bars must be aligned to the
> official exchange calendar.** This is the clause that makes §E4's bfill leakage a governance
> violation, not merely a bug.

**Audit commands (`README.md` §4-§5):** `python incremental_update.py --audit` (one-shot audit),
`python incremental_update.py --sync-manifest` (metadata re-registration),
`python bootstrap_lake.py --status | --list | --dataset <id> | --tier 01_raw_lake` (restore).

**Schema standards (`skills/quant-data-governance-engine/SKILL.md` + `references/methodology.md`):**

* Research Parquet: `timestamp: timestamp[us, tz=UTC]`, `symbol`, `timeframe`,
  `bar_type = <symbol>.<venue>-<timeframe>-LAST-EXTERNAL`, `ts_event`/`ts_init` as **uint64 ns**,
  OHLCV float64.
* Native Nautilus catalog path: `<catalog_root>/data/bar/<bar_type>/<chunk>.parquet`, ingested via
  `BarDataWrangler(bar_type, instrument)` + `ParquetDataCatalog.write_data()`.
* NT stores Price/Quantity as `fixed_size_binary[16]` (128-bit decimal) internally — relevant because
  the doc's sample code hard-codes 2-decimal `Price.from_str(f"{…:.2f}")` and would round NQ prices
  to 0.01 while the tick is 0.25 (harmless for price, but `price_precision` must match the instrument
  or the engine rejects the price — `research/nautilus/NAUTILUS_API.md:34`).
* Gaps: crypto gap > 1.5 × expected interval → logged to `defects.json`; equities/futures must use
  official exchange calendars.

### B6. The 可用 / 可入湖 marking convention — **it is not defined inside the lake repo**

Verified by grep across the whole clone:

* `grep -rn "可入湖" research/github/dataBaseLake/` → **0 hits.**
* `grep -rn "可用" … --include="*.md" --include="*.py" --include="*.json"` → **1 hit**, and it is
  prose, not a status marker: `README.md:80` — `# 2. 列出注册表中的所有可用大数据集` ("list all *available*
  large datasets in the registry").

So the "mark it 可用 / 可入湖 before use" rule exists **only** in the user's own note
(`一些必备apikey和环境.txt`: *"每次补充增量下载数据到本地数据湖需要按原数据湖…的严格审计、治理、清晰
标准后标记为"可用"、"可入湖"后方可使用"*). There is **no marker file, no schema field, no directory
convention** implementing it in `dataBaseLake`.

**Consequence:** the convention has no machine-readable home, so it cannot be enforced or audited
automatically. Before any new data enters the lake, decide and write down where the marker lives.
The natural fit, consistent with the existing layout, is a status field in
`03_governed_lake/v2_parquet_lake/manifest/manifest.json` plus a per-dataset entry under
`03_governed_lake/quant_data_inventory/` — **but that is a proposal, not an existing convention, and
this document does not assert it as fact.**

### B7. The lake's *registered* download sources contain no CME futures

`research/github/dataBaseLake/data_sources.json` registry (v1.0.0, updated 2026-10-14), 9 datasets:
`hf_mito0o852_ohlcv1m` (81.7 GB), `hf_123olp_binance_futures` (16.1 GB),
`hf_twelvedata_fwm` (47.2 GB), `hf_omchoksi108_cloud_lake` (4.3 GB),
`hf_yifishbossman` (2.8 GB), `hf_zoanana990_qtrade` (0.5 GB), `cdd_all_exchanges` (4.4 GB),
`gh_getdata_finance` (3.0 GB), `kaggle_quandl_wiki` (1.7 GB), `cmc_crypto_index_cmc20` (0.16 GB).

**None of them is a CME NQ/ES source.** The registry's headline entry is misleading for our purpose:
I queried the HF API for `mito0o852/OHLCV-1m` and read its `cardData.dataset_info.splits` —
**129 splits, all US equity tickers (AOM, FORD, INVA, XFLT.PRA, …), and programmatically
`"NQ" in splits == False`, `"ES" in splits == False`, `"MNQ" in splits == False`.** Despite the
registry describing it as "全球多资产 1m OHLCV (1992-2026)", the dataset card says
*"US Stock Market Minute-Level Candlestick Data (1992–2026) … originally sourced from Finnhub.io … across
thousands of U.S. stocks"*. It is equities, not futures. **The lake has no registered route to NQ/ES
1-minute data.** That is why §D has to go outside the registry.

---

## C. The two Kaggle datasets — sufficiency verdict

### C1. `research/kaggle/nq-fvg-dataset/` → **LABELLED TOY. Cannot drive a backtest. Cannot be a
ground-truth oracle for a time series.**

Verified structure (`data.yaml`: `nc: 2`, `names: ['bearish_fvg','bullish_fvg']`; Roboflow
train/valid/test layout):

| Split | Images | Labels |
|---|---|---|
| train | 207 | 207 |
| valid | 44 | 44 |
| test | 44 | 44 |
| **total** | **295** | **295** |

* Files: `1min-NQ-<n>_png.rf.<hash>.jpg` (155) and `5min-NQ-<n>_png.rf.<hash>.jpg` (140).
* Image format: JPEG, **640×640**, 22–29 KB each, 9.1 MB total.
* Labels: YOLO detection format, `class x_center y_center width height`, normalised; class
  `0 = bearish_fvg`, `1 = bullish_fvg`. Boxes per image: min 0 (1 file), 1 (1 file), 2 (1), 3 (3),
  4 (4), 5 (5), 6 (7), **7 (22 files)**, 8 (25), 9 (26), 10 (22), 11 (26), 12 (31), 13 (26),
  14 (23), 15 (10), 16 (9), 17 (12), 18 (10), 19 (3), 20 (2), 21–23 (1 each).
* **I opened one image** (`test/images/1min-NQ-103_png.rf.bb6a8c94dd2554fb82e795a48b393e11.jpg`):
  a **white-background** TradingView-style candlestick chart, ≈80 candles, black/teal candles, a light
  grid, **no price axis, no time axis, no date, no volume**.

| Question | Verdict |
|---|---|
| Resolution | 1-min and 5-min **charts**, not bars |
| Symbol | NQ (by filename only) |
| Date range | **UNKNOWN — no timestamp is recoverable from the images** |
| ES counterpart | **None** |
| Session markers | **None** |
| FVG labels usable as ground truth for validating our FVG detector | **NO.** They are pixel boxes on a chart with no price scale and no time axis. They can validate *shape* detection (the YOLO task) but cannot validate a *numeric* FVG detector, and cannot be joined to any OHLCV series. |
| Continuous across sessions/weekends | **N/A** — each image is an isolated window |
| Can it support a profitability claim? | **NO — categorically.** There is no price series, no volume, no time, no outcome. It is the training set for the vision model, nothing more. |

Two further points that matter for phase 2:

* **Rendering-convention clash.** These charts are white-background TradingView renders; the design
  doc (`iFVG几个模型的讨论.txt`, module 1) requires **black-background 224×224** mplfinance renders.
  The doc's own model (`ibtsam/nq-fvg-detector`) was trained on the *white* style. Mixing them silently
  degrades the vision layer — already flagged in AGENTS.md "Risks".
* **Selection bias** — see §E6. This dataset is almost entirely *positives*; it cannot measure the
  false-positive rate that the vision layer claims to cut by "~35%".

### C2. `research/kaggle/gold-xauusd-smc-trading-data/` → **USEFUL AS A GEOMETRY UNIT-TEST ORACLE ONLY.
Not NQ, not 1-minute, not a profitability source, and the labels carry zero independent information.**

One file: `XAUUSD_15M_SMC_Data.csv`, 4,502 data rows + header, 572 KB.
Metadata (`gold-xauusd-smc-trading-data.metadata.json`): Apache-2.0, 26 downloads, 5 votes;
*"Historical OHLC (Open, High, Low, Close) and volume data for Gold Futures (XAU/USD) was
programmatically collected using the open-source 'yfinance' Python library, which pulls public financial
data from Yahoo Finance."*

Measured facts (pandas on the 3.11 interpreter):

| Property | Value |
|---|---|
| Range | **2026-07-14 04:00 UTC → 2026-09-22 07:45 UTC** (≈ 70 calendar days, ≈ 10 weeks) |
| Resolution | 15-minute; step histogram: 15 min × 4,452, **75 min × 38**, 2,955 min × 8, 2,940 × 1, 60 × 1, 4,755 × 1 → **48 gaps > 60 min** |
| Weekday coverage | Thu 921, Tue 920, Wed 920, Fri 841, Mon 828, **Sun 72** → the weekend/holiday is *not* modelled as a session calendar |
| Symbol | **XAU/USD spot**, price range 3,969.50 – 4,751.30 |
| Columns | `Datetime, Close, High, Low, Open, Volume, Bullish_FVG, Bearish_FVG, Body_Size, Is_Bearish, Strong_Bullish_Move, Bullish_OB` |
| Label counts | Bullish_FVG 490, Bearish_FVG 487, Bullish_OB 392 |
| OHLC geometry violations | **0** |

**The decisive verification:** I recomputed the FVG columns from the OHLC with the plain 3-candle
predicate (`bullish: high[i-2] < low[i]`; `bearish: low[i-2] > high[i]`) and compared row-by-row:
**agreement = 1.000 for both directions**, and the recomputed count for bullish (490) equals the
label count exactly (487 bearish likewise).

> **Therefore the `Bullish_FVG` / `Bearish_FVG` columns are a deterministic function of the OHLC — they
> are not independent ground truth.** They are useful only as a **unit-test oracle for the FVG
> geometry** ("does our detector implement `high[i-2] < low[i]` correctly?"). They cannot validate a
> *threshold*, an ATR filter, an inversion, or any outcome, and they say nothing about profitability.
> Note also the doc's FVG floor is `gap_size > 0.25 × ATR(14)` — this CSV has **no ATR filter applied**,
> so it is *not* a test of the actual rule.

| Question | Verdict |
|---|---|
| Resolution | 15-min — **too coarse for a 1-minute strategy** |
| Symbol | XAU/USD, not NQ |
| Date range | ~70 days — **far too short** for 6/1/1 walk-forward + OOS |
| ES counterpart | **None** |
| Session markers | **None** (derivable from UTC only) |
| FVG labels usable as ground truth | **Only as a geometry unit-test oracle** (they are recomputable) |
| Continuous across session breaks / weekends | **No** — 48 unexplained gaps, weekend sessions partially present |
| Can it support a profitability claim? | **NO.** Wrong symbol, wrong resolution, wrong length, and no independent labels. |

### C3. `research/kaggle/fvgnet-manifest.txt` (for completeness) → **not usable**

Manifest only for `wangqizhou/fvgnet` (~45 GB, not downloaded). Contents: `data.csv` (10,901 B),
`class.dic` (88 B), `demo.ipynb` (4.69 MB), `labels/2021-11-03_*.png` … `2021-11-10_*.png` (252 label
PNGs spanning **4 sessions: 2021-11-03 → 2021-11-10**), and `outdoor/Converted/*.h5` (213.9 MB each,
×20 ≈ 4.3 GB) plus `outdoor/RGB` and `outdoor/SPECIM/2022-01-24_00{5..16}/`. No futures OHLCV; the bulk
is outdoor-camera RGB→H5 capture data. **Not a source for phase 1.**

### C4. HF community 1-minute candidates (found via the HF API; metadata + Parquet footer probes only)

These are not "Kaggle datasets", but they are the only free NQ/ES 1-minute pairs discoverable from
this host, so they are graded here.

| Dataset | What it is | Grading |
|---|---|---|
| `mdelcristo/NQ-F_1min_OHLCV_Parquet` | MIT, 6,671 downloads, last modified 2025-07-25. 11 yearly Parquets, 2015–2025, **49.9 MB total**. Footer-probed schema `timestamp: timestamp[ns]` (**tz-naive**), OHLC double, volume int64; 1 row group/file. Rows: 2015 → 329,886 (2015-01-01 23:00 → 2015-12-31 21:59); 2020 → 348,461 (2020-01-01 23:00 → 2020-12-31 21:59); 2025 → 195,610 (2025-01-01 23:00 → **2025-07-25 02:14**, partial). README is only `--- license: mit ---`. | **PARTIAL.** Row density is consistent with a full ~23 h/day Globex minute feed (~330–348 k/yr). **But**: no provenance, no source vendor, **no `instrument_id`, no adjusted columns → roll artefacts baked in and unrecoverable**, and tz-naive timestamps. Cannot enter the lake as 可入湖 without a provenance note and an explicit roll treatment. |
| `Khanhpham1992/es-futures-1m` and `msj-21/es-futures-1m` | 990 / 496 downloads, last modified 2026-04-20 / 2026-06-07. Two files each: `es_continuous_1m.parquet` + `es_features_ready.parquet`; 282,386,358 B total. Footer-probed `es_continuous_1m.parquet`: `instrument_id` (per-contract!), OHLC, volume, **`adj_open/adj_high/adj_low/adj_close`**, `datetime: timestamp[ns, tz=UTC]`; **646,948 rows, 2020-11-17 00:00 UTC → 2024-07-19 20:59 UTC**; 1 row group. | **PARTIAL.** Schema is *better* than the NQ file (tz-aware, per-contract id, back-adjusted series → roll is identifiable). **But** row density is ~177 k/yr vs the NQ file's ~340 k/yr, i.e. the ES series looks **truncated or thinned** relative to a full Globex feed. **UNVERIFIED — needs a column read of `datetime` + `instrument_id` (~15 MB of the 141 MB file) to establish spacing and per-contract coverage.** No README, no licence tag on the repo. |
| `lynx1231/historical-equity-index-futures-data-sample` | 898 downloads, licence `other`. Free **evaluation sample** from the commercial vendor `futuresforexandsomeindexes.com`. `catalog.csv` (read in full) lists per-contract observation counts and timestamp bounds for minute + daily: NQ roots `NQH26/NQM26/NQU26/NQZ26` (111,536 / 116,124 / 52,454 / 6,232 minute obs), ES roots `ESH26/ESM26/ESU26/ESZ26` (115,276 / 120,688 / 54,881 / 5,324), plus RTY and HSI. Total 912,183 observations; 4 roots / 16 contract codes. | **PARTIAL.** The only source found with a **proper per-contract, calendar-aware schema and a checksummed manifest** — i.e. it shows what a provenance-grade product looks like. But it is a *sample* of 2025–2026 contracts, per-contract minute counts imply ~300–350 bars/day (**thinner than a full Globex feed — UNVERIFIED — needs the Parquet read**), and the commercial licence forbids using it as the production lake source. |

Other HF searches run (`"NQ futures 1 minute"`, `"nasdaq futures"`, `"ES futures"`, `"ES 1min"`,
`"CME futures"`, `"equity index futures"`, `"nasdaq 100 futures"`, `"futures minute"`,
`"NQ continuous"`) surfaced **no other credible NQ/ES 1-minute dataset**.

---

## D. Data acquisition plan (prioritised, costed)

Constraint: no Databento subscription assumed; the user's own lake and the crypto sources are the
primary channels. Every option below states source / what it gives / cost / effort / governance path /
failure risk.

### Option 0 — Unblock and inventory the lake *(do this first)*

| | |
|---|---|
| **Source** | `smb://192.168.1.6/iflow` (mount per §B2) |
| **What it gives** | The *only* series that already satisfies the governance contract: `03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/` at 1m, plus the Nautilus databank catalog |
| **Cost** | **Free** (0 licence, 0 download — the data is already owned) |
| **Effort** | 0.5 day: mount + inventory (§B2) + one parquet metadata read |
| **Governance path** | None needed — it is already governed. Audit with `python incremental_update.py --audit` to confirm |
| **Risk it fails** | **Moderate.** The databank MANIFEST.md lists CME index futures at **1-Day only** (§B4), so `us_futures/{NQ,ES}/` 1m may be an aspirational manifest entry with no bytes behind it. Also the share root may be `数据库5` not `database`. **Decision point: command B2 step 4.** |
| **If it succeeds** | Phase 1 can start within days, on the cleanest possible data |

### Option 1 — Free community 1-minute pair (fallback if Option 0 fails)

| | |
|---|---|
| **Source** | HF `mdelcristo/NQ-F_1min_OHLCV_Parquet` (NQ, 50 MB, 2015–2025) + HF `Khanhpham1992/es-futures-1m` → `es_continuous_1m.parquet` (ES, 141 MB, 2020-11→2024-07) |
| **What it gives** | NQ 1m OHLCV, ~10.5 y; ES 1m OHLCV with per-contract `instrument_id` and back-adjusted series, ~3.7 y |
| **Cost** | **Free** (0 licence fee). Licence status: NQ repo says MIT; ES repo carries **no licence tag** — treat as "all rights reserved / unknown" until clarified |
| **Effort** | 1–2 days: download (0.2 GB), convert to the lake's UTC-ms/zstd-7 parquet schema, **write the roll rule**, align NQ↔ES, audit |
| **Governance path** | Land in `01_raw_lake/` with a provenance note (source URL, retrieval date, file SHA-256, schema). Then run `incremental_update.py --audit`; only promote to `03_governed_lake/v2_parquet_lake/us_futures/` after the five invariants pass and the **可用 / 可入湖 marker is applied** (§B6) |
| **Risk it fails** | **High on paper, moderate in practice.** (a) NQ file has **no roll metadata** → the roll gaps must be *detected* statistically (see §E1), not read from a contract column; (b) ES file's ~2× lower density than NQ means the two series may not be **time-aligned** — SMT requires both legs to have a bar within 60 s (see §E3); (c) both repos are single-user uploads with no provenance — they fail the lake's lineage standard and would have to be quarantined with an explicit "unverified provenance" flag; (d) licensing is unclear for the ES repo |
| **Mitigation** | Overlap-check NQ 2015–2025 against ES 2020-11–2024-07, and **require the ES side to be rebuilt from its `instrument_id` per-contract bars** so the roll is explicit rather than inherited |

### Option 2 — Commercial vendor (provenance-grade reference and fallback)

| | |
|---|---|
| **Source** | `futuresforexandsomeindexes.com` (the vendor behind the free HF sample `lynx1231/…`) |
| **What it gives** | Per-contract, calendar-aware NQ/ES minute + daily, with `catalog.csv`, `manifest.json`, `checksums.sha256` and a schema contract — i.e. the exact shape the lake wants |
| **Cost** | Free sample (0); full catalogue **priced — UNVERIFIED — needs a quote from the vendor's site; also confirm redistribution rights** (the sample's licence is `other`) |
| **Effort** | 1 day to evaluate the sample; unknown for the full set |
| **Governance path** | Same as Option 1 (raw → audit → governed), plus a licence file recording redistribution permission |
| **Risk it fails** | **Cost/licence.** Redistribution into a shared lake may be prohibited; per-month pricing for 3+ years × 2 symbols may exceed the Databento route |

### Option 3 — Databento (the design doc's own recommendation)

| | |
|---|---|
| **Source** | Databento, CME Globex schemas for NQ/ES |
| **What it gives** | Nanosecond-timestamped OHLCV-1m, **per-contract** (so rolls are explicit), native DBN → `ParquetDataCatalog` |
| **Cost** | The design doc asserts *"订阅 CME 历史数据包仅需约 $10–$30"* (`iFVG几个模型的讨论.txt`) for several years of continuous NQ/ES. **Current Databento pricing is UNVERIFIED — needs a check of `https://databento.com/pricing` for the CME historical per-GB rate on the Globex schemas; multi-year 1-minute for two symbols is plausibly $100–$300, not $10–$30.** |
| **Effort** | 1–2 days: subscribe, download, DBN → Parquet, contract-roll assembly, audit |
| **Governance path** | Cleanest: raw DBN → `01_raw_lake/` → `prepare_parquet`-equivalent → audit → governed. Also the only route that satisfies A4 (roll rule) *by construction* |
| **Risk it fails** | **Budget.** Multi-year 1m for two CME symbols is not a $10 download; if the per-GB rate bites, this becomes a decision the user must approve explicitly |

### Option 4 — Broker-native history

| | |
|---|---|
| **Source** | Interactive Brokers / Tradovate / Rithmic historical bars |
| **What it gives** | The same feed the live/paper phase will see — best slippage parity |
| **Cost** | Account required; market-data subscriptions for CME can cost monthly |
| **Effort** | 1 day |
| **Governance path** | Licence check: broker feeds usually forbid redistribution into a shared lake |
| **Risk it fails** | **High.** Historical minute depth is limited and usually thinned (IBKR's futures 1-minute history is not a reliable multi-year source); and the licence likely blocks lake ingestion. **UNVERIFIED — needs an account query against the specific broker's historical-bar limits** |

### Option 5 — Crypto lane (Binance / OKX / cryptohftdata) — **out of scope for the phase-1 gate**

| | |
|---|---|
| **Source** | Binance + OKX official history (API keys in `一些必备apikey和环境.txt`); `cryptohftdata.com` (API key present) |
| **What it gives** | 24/7 minute bars for BTC/ETH — the **phase-4** migration lane (doc L163, DVOL regime) |
| **Cost** | Free (both official APIs); cryptohftdata is a commercial service — pricing **UNVERIFIED** |
| **Effort** | 1 day |
| **Governance path** | `cdd_all_exchanges` / `hf_123olp_binance_futures` are already registered in `data_sources.json`; crypto gaps must go to `defects.json` per invariant 6 |
| **Risk it fails** | None for this gate — **but it does not substitute for NQ/ES**, and `cryptohftdata` is crypto-focused by name and docs; no NQ/ES catalogue was verified from it. **UNVERIFIED — needs `GET` against its OpenAPI spec / dataset listing** |

### Recommendation (cheapest path that can actually satisfy phase 1)

1. **Run Option 0 today (2026-11-22).** It is free, takes ~30 minutes, and it is the only route that
   yields data already inside the governance contract. If
   `03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/` has 1-minute Parquet with a date range
   covering ≥ 3 years → **use it, and the phase-1 gate is unblocked**.
2. **In parallel, start Option 1's download + audit (free, 0.2 GB)** as insurance. The NQ file is 50 MB
   and the ES file 141 MB; together they cover 2020-11 → 2025-07 with an explicit ES contract column.
   While it downloads, write the **roll-detection rule** (§E1) and the **N↔ES alignment check** (§E3) —
   these are needed whichever source wins.
3. **Only if both 0 and 1 fail** → Option 3 (Databento) or Option 2 (vendor), with an explicit budget
   approval. The design doc's "$10–$30" should be re-verified before anyone commits.
4. **Do not** let Option 4 or 5 gate phase 1: broker history is too shallow, and crypto is a different
   strategy lane.

### Earliest realistic start dates

| Milestone | Optimistic (lake has it) | Realistic (free community path) | Paid route |
|---|---|---|---|
| Lake mounted + inventory done | **2026-11-23** | 2026-11-23 | 2026-11-23 |
| Source decided + data in hand | 2026-11-23 | 2026-11-24 | 2026-11-27 (delivery delay) |
| Roll rule written + NQ↔ES alignment proven | 2026-11-24 | 2026-11-26 | 2026-11-28 |
| Governed Parquet written + `--audit` green | 2026-11-24 | 2026-11-27 | 2026-11-29 |
| Nautilus catalog + 20-bar smoke run | 2026-11-25 | 2026-11-27 | 2026-11-29 |
| **Phase-1 backtest can start** | **2026-11-25** | **2026-11-27** | **2026-11-29** |

**Earliest realistic phase-1 start: 2026-11-25 via the lake path; 2026-11-27 via the free community
path.** The rule engine itself (`research/docs/RULE_SPEC.md` is already decision-ready) can be written
*now*, in parallel, since it is pure and needs no data until the catalog exists.

**One caveat that caps all of the above:** the phase-1 gate's cost model is not yet pinned. Until the
broker fee schedule and the NT fill/slippage configuration are fixed, a "Profit Factor > 1.25" result
is not interpretable, because the difference between $4.50 and $24.50 of round-trip friction on a
20-point stop is ~2.5 % of R — the difference between PF 1.30 and PF 1.22.

---

## E. Leakage & integrity checklist

Each row: the trap → why it bites *this* strategy → the check that catches it → where the check goes.
Every check must be an **assertion in a test**, not a convention.

### E1. Roll gaps faking a liquidity sweep / contract splicing

* **Why it bites:** the strategy's first precondition is "price pierces a prior swing high/low". A
  continuous series spliced at the H→M roll contains an artificial ~50–150 point jump. That jump
  (a) *is* a synthetic sweep of the old contract's high, and (b) can form a synthetic 3-candle FVG
  around it. Every downstream stage — ATR, gap floor, checklist score — is then computed on a price
  series that never existed. This is the classic way a "positive EV" backtest is manufactured.
* **Checks:**
  1. Require a per-bar `instrument_id`/contract code. Where the source has none (the community NQ
     file), **detect** the roll: flag any bar where `abs(open[t] − close[t−1]) > k × ATR(14)` (k ≈ 3)
     **and** the move is not explained by a scheduled roll date → write to `defects.json`, exclude the
     bar and the `k` bars either side from rule evaluation, and record it in the signal log as
     `roll_boundary`, **not** as a trade.
  2. Where the source is back-adjusted (the community ES file has `adj_*`), **never mix adjusted and
     raw prices**: ATR, gap size, swing levels and the R-multiple must all be computed in the *same*
     price basis. A silent mix changes the stop distance and therefore every R.
  3. Assert the roll rule is **documented and executable**: a single function
     `roll_boundary(ts, contract_id) -> bool` used by both the bar filter and the test.
  4. Assert no signal's FVG window (`c[i]` … `c[i]+15]`) or its sweep reference crosses a flagged roll
     boundary — RULE_SPEC A04 anchors the 7–15 bar clock on `c[i]`, so the window is well-defined and
     must be checked against the boundary list.
* **Governance hook:** invariant 6 (真实断点治理) — breaks are recorded, never synthesised.

### E2. A "sweep" that is only a session boundary or a data gap

* **Why it bites:** the rule compares the current bar's high against a *stored* swing high. If the
  stored swing high came from a different session (or the series has a 75-minute hole, as the gold CSV
  demonstrably does), the "sweep" is an artefact of the discontinuity, not of order flow. The gold CSV
  has **48 gaps > 60 min** — a live example of what such artefacts look like.
* **Checks:**
  1. Assert `ts[t] − ts[t−1] == 60_000_000_000 ns` inside a trading session. Any gap > 60 s is a
     **hard boundary**: reset the swing/EQ structure, drop pending FVG candidates whose window would
     span it, and emit no sweep across it.
  2. Treat the CME maintenance break (17:00→18:00 ET) and the RTH/Globex break (16:00→17:00 ET) as
     explicit boundaries. A "sweep of the previous session high" at 18:00 ET is a different phenomenon
     from an intraday sweep and must be labelled, not merged.
  3. Assert that the reference level used in a sweep was observed **within the same session_id**
     (RULE_SPEC A41 carries `session_id`).
* **Where:** unit tests over the rule engine's fixture bars, plus a whole-dataset scan asserting zero
  gaps inside a session.

### E3. DST transitions inside the killzone windows

* **Why it bites:** the killzone is `09:30 ≤ t ≤ 11:30 ET` and `13:30 ≤ t ≤ 15:30 ET`, **endpoint-
  inclusive**, evaluated on the bar's **close** timestamp (RULE_SPEC A21 / T05 / T06). "ET" means
  `America/New_York` **with DST**. On the two US switch days (2nd Sunday March, 1st Sunday November)
  the UTC offset of the window changes by one hour: 09:30 ET = 13:30 UTC under EDT and 14:30 UTC under
  EST. A pipeline that hard-codes UTC−5 places the window an hour early for half the year — silently
  halving or doubling the sampled trades. The design doc itself contradicts here (`I08`: "美东时间" in
  the state machine vs "09:30 EST" in the migration table). Note that the CME Globex session hours are
  fixed in **Chicago time**, which shifts with the same US DST dates, so both the session boundary and
  the killzone move together — but only if both are converted with a tz database.
* **Checks:**
  1. Use `zoneinfo.ZoneInfo("America/New_York")` — never a fixed `timedelta(hours=-5)`. Assert the
     module contains no literal UTC offset.
  2. For every trading day in the dataset, assert that **exactly one** bar closes in `[09:30, 11:30]`
     ET and one in `[13:30, 15:30]`, and that the count of bars per window is constant across DST
     (120 with a 60-minute grid and one endpoint convention; **pin the convention in a constant and
     assert it**, rather than assuming).
  3. Explicitly assert the **switch days**: the UTC offset of 09:30 ET must differ by exactly ±1 h
     between the day before and the day after each switch, and the bar count in the window must be
     identical.
  4. Assert the first bar of each session is at the documented Globex open in **UTC** — **23:00 UTC
     under EST, 22:00 UTC under EDT**. (My probes of the community NQ file were all January = EST and
     showed `23:00`; the EDT branch is **UNVERIFIED — needs the same footer probe on a June file**,
     e.g. `NQ_1min_2020.parquet`'s June rows.)
* **Where:** a dedicated `tests/unit/test_sessions_dst.py`, run over every date in the series.

### E4. Missing bars silently forward-filled — where else can `bfill` leak?

* **The documented case:** `vxn_df["vxn_known"] = vxn_df["Close"].shift(1).bfill()` (doc L261-L262;
  RULE_SPEC T49). Two distinct leaks here: (a) `shift(1).bfill()` **back-fills from the future** at the
  head of the series — the first rows take a value from a later date; (b) a daily series b-filled
  across a multi-day holiday or a data outage silently carries a stale regime forward with no marker.
* **The other places bfill/ffill can leak — all must be audited:**
  1. **VXN daily→intraday join.** B-fill at most one calendar day; count and log every fill; assert
     the maximum fill run ≤ 4 days (a long weekend/holiday) and that no fill crosses a data outage.
  2. **Bar-level resampling** (1m→5m/15m/1h for the RULE_SPEC T41 "unreclaimed 15m/1H FVG zones").
     A resample that forward-fills into an empty session creates phantom 15m/1h bars at the open.
     Assert every aggregated bar has ≥1 real contributing 1m bar and that no aggregate spans a gap.
  3. **The NQ↔ES SMT join — the most dangerous one.** If NQ and ES timestamps are aligned with
     `ffill`/`bfill` to make a rectangular frame, ES's *previous close* is carried into a window where
     ES had no bar, manufacturing an **SMT divergence out of a session mismatch**. The SMT check must
     use an **inner join** and require both legs to have a bar within 60 s; otherwise the SMT result is
     **"unknown"**, and "unknown" must **not** be scored as "divergence" (the +2 checklist points,
     RULE_SPEC A09 — a false +2 here manufactures A+ grades, which are the only grades phase 1 trades).
  4. **ATR warm-up.** `min_periods` must be explicit: RULE_SPEC A03 requires ≥ 14 prior closed bars,
     Wilder RMA α = 1/14, and *"else no signal (not a zero-ATR signal)"*. Any `ffill`/`min_periods=1`
     in the ATR path makes early bars pass the `0.25 × ATR` floor spuriously — precisely the bars with
     the least history.
  5. **Session aggregates.** Asia/London highs and lows (RULE_SPEC T41) must not be carried across an
     empty overnight; recompute them per `session_id`.
* **Governance hook:** invariant 6 — *"严禁前向伪造合成插值"*. Any forward-fill in the bar path is a
  governance violation, not a modelling choice.
* **Where:** a global assertion — *no bar-level forward-fill anywhere* — plus per-module tests listed
  above.

### E5. VXN regime computed from a value not knowable at the trade time

* **Why it bites:** the regime is a feature *and* a gate (RULE_SPEC T07-T10, T11-T13: A+ only in
  low vol, RR 1:2.5–1:3 in normal vol, halved risk + larger gap in high vol). A regime label computed
  from a value that was not published yet at decision time is a silent look-ahead that flatters the
  backtest.
* **What is legitimately knowable:** CBOE's VXN daily close is final after the US close (~16:15 ET), so
  the **previous** trading day's close *is* known at 09:30 ET the next day. The doc's `shift(1)` is
  therefore directionally right — it is the `bfill()` and the binning that are wrong.
* **Checks:**
  1. Assert the regime for bar *t* is a pure function of VXN observations with timestamps **strictly
     before** the bar's decision time. Implement as a unit test that **perturbs the current day's VXN
     and asserts no regime label changes** — a direct look-ahead test.
  2. Use the **corrected binning** from RULE_SPEC §1.9, not the doc's `pd.cut(bins=[0,18,28,200])`:
     the doc's bins are right-closed, so VXN == 18 is classified *low* and VXN == 28 *high* against the
     prose (RULE_SPEC I05), and the open ends make out-of-range values NaN so `.astype(int)` raises.
  3. Assert the head of the series has no back-filled-from-the-future regime values.
  4. If intraday VXN is ever obtained, the 1-hour change must be `close[t−1h]`, never `close[t]`
     (RULE_SPEC A18: *"Do not fabricate"*).
* **Where:** `tests/unit/test_vxn_regime.py`, plus an assertion in the feature builder that the
  regime column is constant within a trading day and derived only from lagged data.

### E6. Survivorship / selection in "which FVG labels did the dataset author keep?"

* **Why it bites — the NQ chart dataset:** of the 295 labelled images, **only 1 has zero FVG boxes**
  (1 file has 1 box; 22 files have 7; the median is ~10). The windows were pre-selected around FVGs.
  Any accuracy, precision or "the vision layer filters ~35 % of the noise" claim measured on this set
  is measured on **positives only** — it cannot estimate the false-positive rate, which is the only
  number the vision layer is supposed to deliver (doc module 1: *"这能过滤掉约 35% 的假突破噪音"*).
  The pre-selection also means the chart background distribution (no-FVG windows) is absent.
* **Why it bites — the gold CSV:** the opposite bias. Its labels are a **deterministic function of the
  OHLC** (verified 100 % agreement), so they leak nothing but also *inform nothing* — any "the
  detector agrees with the dataset" metric on it is circular.
* **Checks:**
  1. Build a **negative set** from the real NQ 1-minute series: random 60-bar windows with **no**
     rule-engine FVG, rendered in the *same* style as the training images, and report the detector's
     false-positive rate on it. Only then is a "35 % noise filter" claim admissible.
  2. Never quote precision/recall for the YOLO detector from the 295-image set alone; label it as
     "positives only".
  3. Never use the gold CSV as a profitability, threshold, or detector-accuracy source — restrict it
     to a geometry unit test (`assert recomputed_3c_fvg == Bullish_FVG`).
  4. **Post-hoc erasure:** the upstream closed-source indicator *hides losing setups* (AGENTS.md
     "Signal integrity"; doc on `IFVG-Ultimate-Dodgy`). If the chart generator inherited that filter,
     the vision dataset is pre-filtered to winners.
     **UNVERIFIED — needs the generator/provenance of `ibtsamsadiq/nq-fvg-dataset` and the
     `ibtsam/nq-fvg-detector` model card** (both referenced in `.field-guide/sources.md`).
  5. Symmetrically: **our own signal log must never drop losing setups** (AGENTS.md "Signal integrity"
     — *"Never delete or hide failed signals in logs, charts, or training data"*). Assert that the
     number of logged candidates equals the number of logged outcomes.

### E7. (bonus) Timezone-naive timestamps

* **Why it bites:** the community NQ file stores `timestamp: timestamp[ns]` with **no timezone**. Any
  code that does `dt.tz_localize("UTC")` after the fact is *asserting* UTC rather than *knowing* it —
  and if the source was actually local time, every session boundary and every killzone is off by
  hours.
* **Checks:** assert the dtype carries UTC before any session logic; assert the first bar of each
  session lands on the Globex open in UTC (23:00 under EST / 22:00 under EDT — see E3); assert the
  NQ and ES series are expressed in the *same* timezone convention before alignment.

### E8. (bonus) Costs are not what the gate assumes

* **Why it bites:** the gate says "~$4.5 round-turn fees and 1–2 ticks slippage". On NQ a tick is
  $5.00 (0.25 × $20), so 1–2 ticks is $5–$10 **per side** → **$10–$20 round trip** of slippage on top
  of $4.50 of commission. The all-in round-trip friction is therefore ≈ **$14.50–$24.50**, and at a
  20-point stop ($400) that is 3.6 %–6.1 % of R. A backtest that charges $4.50 total will overstate PF
  materially.
* **Checks:** (a) assert the venue fee model in the backtest config equals the *broker schedule*, not
  the doc's number; (b) assert the slippage model produces a **measured** adverse fill of 1–2 ticks on
  a market order in a 20-bar smoke backtest (`research/nautilus/NAUTILUS_API.md:242` records that the
  fees/slippage JSON is still `[UNVERIFIED]`); (c) report PF at **0, 1 and 2 ticks** as a sensitivity
  table, not a single number; (d) make ES costs zero (it is a reference instrument, never traded) and
  assert that.

---

## F. Consolidated list of what could not be verified from this host

| # | Claim | Command / access needed |
|---|---|---|
| F1 | Whether `us_futures/{NQ,ES}/` 1-minute Parquet actually exists on the SMB share | mount per §B2, then `ls -la /mnt/iflow/database/03_governed_lake/v2_parquet_lake/us_futures/{NQ,ES}/` |
| F2 | Whether the share root is `database`, `数据库5`, or both | `find /mnt/iflow -maxdepth 2 -type d` |
| F3 | SMB credentials for the share | from the share owner — **not present in this repo** |
| F4 | The lake's actual roll rule for the "Continuous Futures" series | the lake's own pipeline code on the share, or `research/github/dataBaseLake/02_pipeline_engine/scripts/multi_asset_incremental_updater.py` (read: it exists in the clone but was not audited for roll handling) |
| F5 | Where the 可用 / 可入湖 marker is stored | **no definition exists in the repo** — needs a decision (§B6) |
| F6 | Broker commission schedule behind "$4.5 round-turn" | the actual broker's schedule; the broker is unnamed in the doc |
| F7 | NautilusTrader fee/slippage JSON wiring for 1–2 ticks | `help(FillModel)`, `help(MakerTakerFeeModel)` under the 3.11 interpreter; then a 20-bar smoke run — `research/nautilus/NAUTILUS_API.md:242` still marks this `[UNVERIFIED]` |
| F8 | ES series bar spacing and per-contract coverage (the density looked thinned) | a column read of `datetime`+`instrument_id` from `es_continuous_1m.parquet` (~15 MB) |
| F9 | Whether the community NQ file is front-month-continuous or something else | no `instrument_id`, no README; requires statistical roll detection (E1) or the uploader |
| F10 | Databento's current CME pricing | `https://databento.com/pricing` — the doc's "$10–$30" is unverified |
| F11 | cryptohftdata's dataset catalogue (crypto only? NQ/ES present?) | `GET` its OpenAPI/docs endpoint with the key from `一些必备apikey与环境.txt` |
| F12 | Whether the NQ chart dataset was generated with the "hide losing setups" filter | the generator provenance for `ibtsamsadiq/nq-fvg-dataset` and the `ibtsam/nq-fvg-detector` model card |
| F13 | CME's published NQ/ES tick size and multiplier (0.25 / 20 / 50) | CME contract-spec pages; the values used here are the project's assumption per RULE_SPEC A22 and `research/nautilus/NAUTILUS_API.md` |
| F14 | Whether intraday VXN is obtainable for free | CBOE publishes the free file as **daily only**; intraday needs a paid source |

---

## G. Bottom line

* **Phase 1 is reachable, but not today.** It needs ~2–5 days of data work plus the (already
  spec-ready) rule engine.
* The binding constraint is **one**: get a NQ+ES 1-minute pair that (i) is reachable, (ii) has a
  documented roll rule, and (iii) passes `incremental_update.py --audit`.
* The lake is the best candidate and costs nothing to check — **do command §B2 step 4 first**.
* The two Kaggle datasets in `research/kaggle/` are **irrelevant to the gate**: the NQ one is a
  295-image vision corpus with no OHLCV, and the gold one is a 70-day 15-minute XAU/USD series whose
  FVG labels are a deterministic function of its own OHLC. Neither can support a profitability claim.
* Do **not** let the ML/vision layers start before the pure-rule baseline is run and read — the design
  doc is explicit that a negative pure-rule result means the rule reproduction is wrong, and the data
  gaps in §A/E are exactly the kind of defect that would produce one.
