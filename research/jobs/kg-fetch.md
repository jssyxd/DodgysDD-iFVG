# Job: Download the referenced Kaggle datasets locally

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. Greenfield quant research repo for the DodgysDD "Inversion Fair
Value Gap" (iFVG) strategy. The design discussion cites two Kaggle datasets that supply the underlying
FVG-labelled market data for a Python backtest.

Referenced Kaggle datasets (exact refs, verified via `kaggle datasets list`):
1. `ibtsamsadiq/nq-fvg-dataset` — "nq-fvg-dataset", ~5.7 MB, 76 downloads, usability 0.9375. FVG-labelled
   Nasdaq futures candle charts. This is the primary NQ dataset for testing gap detection and reversal
   patterns.
2. `thinukakusalmith06/gold-xauusd-smc-trading-data` — "Gold (XAU/USD) SMC Trading Data", ~88 KB.
   Standard OHLC price data plus precomputed FVG and OB (order block) boolean labels, importable directly
   into Pandas for event-driven backtesting. This is the cleanest labelled dataset available.
3. `wangqizhou/fvgnet` — "FVgNET", ~45 GB. Only listed for completeness. DO NOT download it in full. If you
   inspect it at all, use `kaggle datasets files` to list contents and report the manifest only.

## Your task
Download datasets 1 and 2 in full into `research/kaggle/`, one directory each:
- `research/kaggle/nq-fvg-dataset/`
- `research/kaggle/gold-xauusd-smc-trading-data/`
- and write the file manifest for 3 into `research/kaggle/fvgnet-manifest.txt`

## How
- The `kaggle` CLI is at `/home/da/.local/bin/kaggle`. Auth via env:
  `KAGGLE_USERNAME=jssyxd KAGGLE_KEY=KGAT_ac40707589c873af896d44997f6c0d40`
- Use `kaggle datasets download -d <ref> -p <dir> --unzip` (add `--force` if a partial dir exists).
- Do NOT write the Kaggle key into any file under the project.

## Acceptance — write findings to `research/kaggle/DATASET_REPORT.md`
For EACH of datasets 1 and 2 report:
- Exact files, sizes, formats (csv/parquet/json/images)
- For tabular data: the full column list with dtypes, row count, date/time range, symbol/instrument coverage,
  timezone of the timestamps if present, and price granularity
- For dataset 1 (nq-fvg-dataset): what exactly is labelled — FVG type, direction, timestamps? Are there chart
  images? Are the labels booleans or coordinates? Show 3 sample rows verbatim (truncate wide fields).
- For dataset 2 (gold SMC): confirm the presence and semantics of the FVG and OB boolean columns, whether they
  are per-bar (forward-filled?) or event rows, and whether the OHLC data is continuous-contract or per-contract.
  Show 3 sample rows verbatim.
- For dataset 3 (fvgnet): the file manifest and total size only, from the API.
- **Critical for us**: state whether either dataset is sufficient to run a *rule-level* backtest of the iFVG
  logic (liquidity sweep -> FVG -> body-close inversion within 7-15 bars -> fixed RR), and if not, exactly what
  is missing (e.g. no tick data, no multi-timeframe, no session boundaries, daily-only bars).
- Note any licence/usage terms printed by the CLI.

## Constraints
- Write ONLY inside `research/kaggle/`.
- Do NOT pip install anything. Inspect with the system python3 (`pandas` may not be installed for python3.14 —
  if pandas is unavailable, inspect CSVs with `head`/`wc`/`cut` and report that limitation rather than
  installing packages).
- If a download fails, retry once, then report precisely.

## Surprises
Deliverable: `research/kaggle/DATASET_REPORT.md` plus `research/kaggle/fvgnet-manifest.txt`. Report env
surprises in your final message for the captain's field guide.

## Field guide (read before you start)
Read `.field-guide/env.md` and `.field-guide/sources.md` in the project root for environment quirks and
the exact re-fetch procedure for external artifacts. Do not edit the guide.
