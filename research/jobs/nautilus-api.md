# Job: Verify the NautilusTrader 1.221.0 API surface this project must target

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. The system will use **NautilusTrader 1.221.0** as both the
backtest and live engine. The design discussion (`iFVG几个模型的讨论.txt`) contains sample code for
`data_pipeline/prepare_parquet.py` that was written against an **older** NautilusTrader API generation
(different `Bar`/`BarSpecification`/`BarType` construction, `Price.from_str` usage, `TestInstrumentProvider`
imported but unused, CME instruments never actually defined). We need a verified, current API map before
anyone writes the real modules.

Sailing state already established by the captain (do not re-derive):
- `nautilus_trader` 1.221.0 is installed at `/home/da/.local/lib/python3.11/site-packages/nautilus_trader/`
- The owning interpreter is `/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`
- System `python3` is 3.14 and CANNOT import nautilus_trader (needs >=3.11,<3.14)
- Installed alongside: pandas 2.3.3, numpy 2.4.6, pyarrow 26.0.0, msgspec 0.22.0, fsspec 2025.12.0
- NOT installed: databento, yfinance, mplfinance, ultralytics, lightgbm, scikit-learn, pytest

## Your task
Produce `research/nautilus/NAUTILUS_API.md` — a verified API map for 1.221.0, grounded in the actual installed
package source, not in memory or web recollection.

Cover, for each item: the correct import path, the exact constructor signature (as it exists in 1.221.0),
and a minimal correct usage snippet.

1. **Bar construction & types** — `Bar`, `BarType`, `BarSpecification` (and whether `BarSpecification` still
   exists or has been replaced, e.g. by `BarType` string parsing), `PriceType`, `BarAggregation`,
   `Price.from_str` vs `Price(value, precision)`, `Quantity`. The doc's sample uses
   `BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)` — verify whether that constructor still
   exists in 1.221.0 and what the correct form is now.
2. **Instrument definitions** — how to define a real CME future (NQ.XCME, ES.XCME): tick size, multiplier,
   price precision, expiry. Which class (`Future`, `FuturesContract`, `CryptoFuture`?) and which factory
   (`InstrumentProvider`, `Instrument` constructor). Why `InstrumentId.from_str("NQ.XCME")` alone is NOT a
   tradable instrument. Give the exact code to register NQ and ES with correct specs
   (NQ: tick 0.25, multiplier 20; ES: tick 0.25, multiplier 50).
3. **ParquetDataCatalog** — the real API for writing/reading bars: `ParquetDataCatalog(path)`, `write_data`,
   `write_bars`/`write_bars_batch`, `bar_type` arguments, how the catalog path is laid out on disk, and how
   to read bars back for a backtest.
4. **Custom Data** — the exact way to define a custom event type in 1.221.0: `nautilus_trader.core.data.Data`
   subclass, the `@customdataclass` decorator (is it `@customdataclass`? confirm the import path), required
   fields (`ts_event`, `ts_init`), and how to feed such data into the engine in backtest and live.
5. **Strategy / events** — the `Strategy` base class: how to subscribe to bars for multiple instruments in one
   strategy, the correct handler names (`on_data`, `on_bar`?), how to place a bracket order (the exact method
   names for entry + stop + target, e.g. `submit_order`, `order_list`/`bracket_order`), position management
   (`positions`, `net_positions`), and how to log/export trade records for the ML pipeline.
6. **Engine config** — how `BacktestRunConfig` is structured in 1.221.0 and how a JSON config is consumed
   (confirm `python -m nautilus_trader.backtest --raw <file>` and the msgspec decode path). Confirm whether
   YAML is supported at all. Show a minimal working backtest JSON for NQ+ES 1-minute bars including
   venue fees and slippage.
7. **Backtest engine API** — how to run a backtest programmatically (`BacktestEngine` construction,
   `add_data`, `add_venue`, `add_instrument`, `run()`), and how to obtain per-trade results for label
   generation.

## Method
- Read the installed source directly: `grep`/`rg` in
  `/home/da/.local/lib/python3.11/site-packages/nautilus_trader/` and read the relevant modules.
- Use the 3.11 interpreter to introspect (`inspect.signature`, `help`) — that is authoritative.
- If something does NOT exist in 1.221.0, say so explicitly and give the 1.221.0 replacement.

## Acceptance
- Write ONLY `research/nautilus/NAUTILUS_API.md`.
- Every claim must be traceable to a file path in the installed package or an introspection result. Include
  the exact import path for each symbol.
- Include a "**diff vs the doc's sample code**" section listing every API the doc's `prepare_parquet.py`
  uses incorrectly or that no longer exists, with the corrected form.
- Include a "**smoke-tested snippets**" section: 2–3 short snippets you actually executed with the 3.11
  interpreter, with the command line and the observed output. A snippet that you did not run must be labelled
  `[UNVERIFIED]`.

## Constraints
- Write ONLY `research/nautilus/NAUTILUS_API.md`.
- Do NOT `pip install` anything (numpy/pandas/pyarrow are present; databento etc. are not and not needed here).
- Do NOT modify the installed nautilus_trader package.
- Do NOT create strategies, configs, or source files in the project — this job produces documentation only.

## Surprises
Deliverable: `research/nautilus/NAUTILUS_API.md`. Report any API that surprised you (renamed, removed, or
behaving differently than the doc assumed) in your final message — the captain transcribes those into
`.field-guide/`.

## Field guide (read before you start)
Read `.field-guide/env.md` and `.field-guide/sources.md` in the project root for environment quirks and
the exact re-fetch procedure for external artifacts. Do not edit the guide.
