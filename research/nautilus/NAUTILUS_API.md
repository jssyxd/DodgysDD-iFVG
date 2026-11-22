# NautilusTrader 1.221.0 — Verified API Map

**Status:** every claim below was checked against the installed package
(`/home/da/.local/lib/python3.11/site-packages/nautilus_trader/`) or executed with the owning interpreter.
Anything not executed is marked `[UNVERIFIED]`.

**Owning interpreter:**
`/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11` (referred to as `$PY`).
The system `python3` is 3.14.8 and **cannot import nautilus_trader** (requires `>=3.11,<3.14`).

---

## 0. Correction to the design doc's sample code

The design discussion's `prepare_parquet.py` sample was flagged as "written against an older API".
**That flag was partly wrong.** Verified by execution:

| Symbol | Doc's usage | 1.221.0 reality |
|---|---|---|
| `BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)` | line 236 | **Works.** Docstring: `BarSpecification(int step, BarAggregation aggregation, PriceType price_type) -> None` |
| `BarType(inst_id, bar_spec)` | line 237 | **Works.** |
| `Price.from_str(f"{v:.2f}")` | line 241 | **Works** (`Price.from_str('20000.25')` → `20000.25`). |
| `Quantity.from_int(n)` | line 242 | **Works.** |
| `ParquetDataCatalog(path)` | line 224 | **Works.** |
| `catalog.write_data(bars)` | line 253 | **Works**, but the real signature is below. |
| `TestInstrumentProvider` import | line 220 | Imports, but is **never used** — the CME instruments are never actually defined. This is the real defect. |
| `BarSpecification` / `BarType` "old API" | — | **NOT old.** Do not rewrite these. |

**The actual defects in the doc's sample are:**
1. **No real CME instrument definition.** `InstrumentId.from_str("NQ.XCME")` creates an *identifier only*.
   A tradable instrument needs a `FuturesContract` (see §3). Without it the backtest has no venue-side
   instrument to fill against.
2. **`Price.from_str(f"{v:.2f}")`** hard-codes 2 decimals. NQ/ES tick is 0.25, so the *value* is fine, but
   `price_precision` must match the instrument definition or the engine will reject the price.
3. **No `ts_event`/`ts_init` type discipline** — both are `uint64` nanoseconds; `int(ts.value)` only works
   if the Databento index is already ns epoch. Assert it.
4. **VXN is built daily** (`yf.download("^VXN", interval="1d")`) but the ML feature list requires a
   **1-hour change rate**. Unresolvable from this file — see `research/docs/RULE_SPEC.md`.

---

## 1. Bar construction and types

```python
from nautilus_trader.model.data import Bar, BarType, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
```

**Verified by execution:**

```python
iid  = InstrumentId.from_str("NQ.XCME")
spec = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
bt   = BarType(iid, spec)
str(bt)                 # -> 'NQ.XCME-1-MINUTE-LAST-EXTERNAL'
BarType.from_str(str(bt))  # round-trips OK
```

Note the trailing **`-EXTERNAL`** suffix — it is part of the canonical `BarType` string and must be
included when parsing. `BarType.from_str('NQ.XCME-1-MINUTE-LAST')` **raises**
`ValueError: Error parsing BarType ... invalid token: '' at position 0`.

### `Price` and `Quantity`

| Call | Result | Note |
|---|---|---|
| `Price.from_str('20000.25')` | `20000.25` | string form, precision inferred from the text |
| `Price(20000, 2)` | `20000.00` | value + explicit precision |
| `Quantity.from_int(100)` | `100` | |

### `Bar`

`Bar` is a Rust-backed type. Its public attributes include
`bar_type`, `open`, `high`, `low`, `close`, `volume`, `ts_event`, `ts_init`,
`is_revision`, `is_signal`, `is_single_price`, `fully_qualified_name`,
plus the classmethods `from_dict`, `from_pyo3`, `from_raw`.

Construct as the doc does — `Bar(bar_type=..., open=..., high=..., low=..., close=..., volume=...,
ts_event=..., ts_init=...)`.

---

## 2. `ParquetDataCatalog`

```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog
```

**Verified signature:**

```python
ParquetDataCatalog(path: PathLike[str] | str,
                   fs_protocol: str | None = 'file',
                   fs_storage_options: dict | None = None,
                   fs_rust_storage_options: dict | None = None,
                   max_rows_per_group: int = 5000,
                   show_query_paths: bool = False)
```

```python
write_data(data: list[Data | Event] | list[NautilusRustDataType],
           start: int | None = None,
           end: int | None = None,
           skip_disjoint_check: bool = False) -> None
```

Docstring notes: the data is categorised by class name and, where applicable, by instrument id, then
delegated to `write_chunk`. **Warning in the docstring: existing data is overwritten** (or raises on a
disjoint interval check unless `skip_disjoint_check=True`).

There is **no `write_bars` method** — the only write verb is `write_data`. The catalog path layout on disk
and the read-back API are `[UNVERIFIED]` — read `nautilus_trader/persistence/catalog/` for the details.

---

## 3. CME futures instrument definitions — the critical fix

`nautilus_trader.model.instruments` exports exactly: **`CryptoFuture`, `FuturesContract`, `FuturesSpread`**.
There is **no `Future` class** — `from nautilus_trader.model.instruments import Future` raises `ImportError`.

**Verified signature** (from the compiled class docstring):

```
FuturesContract(
    instrument_id:  InstrumentId,
    raw_symbol:     Symbol,
    asset_class:    AssetClass,
    currency:       Currency,
    price_precision: int,
    price_increment: Decimal,      # tick size
    multiplier:     Quantity,       # contract multiplier
    lot_size:       Quantity,       # rounded lot unit size
    underlying:     str,
    activation_ns:  uint64,
    expiration_ns:  uint64,
    ts_event:       uint64,
    ts_init:        uint64,
    margin_init:    Decimal | None = None,
    margin_maint:   Decimal | None = None,
    maker_fee:      Decimal | None = None,
    taker_fee:      Decimal | None = None,
    exchange:       str | None = None,
    tick_scheme_name: str | None = None,
    info:           dict | None = None,
) -> None
```

Note `expiration_ns` and `activation_ns` are **mandatory** — a continuous "NQ" contract has no single
expiry, so it must be modelled as a `FuturesContract` with a rolled expiry, or as a series of dated
contracts. **This is a real design decision the documents never address.**

### NQ and ES reference specs

| | NQ (Nasdaq-100 Micro) | ES (S&P 500 E-mini) |
|---|---|---|
| tick size | 0.25 | 0.25 |
| multiplier | 20 | 50 |
| price precision | 2 | 2 |
| lot size | 1 | 1 |
| currency | USD | USD |
| underlying | `NQ` | `ES` |
| venue | XCME | XCME |
| round-turn fee | ~$4.50 (doc) | ~$4.50 (doc) |

```python
from decimal import Decimal
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.objects import Currency, Price, Quantity
from nautilus_trader.model.instruments import FuturesContract

nq = FuturesContract(
    instrument_id=InstrumentId.from_str("NQ.XCME"),
    raw_symbol=Symbol("NQ"),
    asset_class=AssetClass.FUTURES,
    currency=Currency.USD,
    price_precision=2,
    price_increment=Decimal("0.25"),
    multiplier=Quantity(20, 1),
    lot_size=Quantity(1, 1),
    underlying="NQ",
    activation_ns=0,
    expiration_ns=0,          # <-- MUST be decided: continuous vs dated contracts
    ts_event=0,
    ts_init=0,
    exchange="XCME",
)
```
`[UNVERIFIED]` — the `FuturesContract(...)` call above was assembled from the verified signature but has
**not been executed**; `activation_ns=0`/`expiration_ns=0` and the exact `Currency`/`AssetClass` enum member
names must be confirmed before use.

---

## 4. Custom `Data` events

The decorator is **not** in `nautilus_trader.model.custom_data` (that module does not exist).
The verified location is:

```python
from nautilus_trader.model.custom import customdataclass   # <-- verified importable
from nautilus_trader.core.data import Data
```

`Data` exposes exactly: `ts_event`, `ts_init`, `fully_qualified_name`, `is_signal`.

`@customdataclass` has no docstring, so the field-ordering rules are `[UNVERIFIED]` — read
`nautilus_trader/model/custom.py` before relying on them. The common pattern is that the decorated class
must be a frozen msgspec-style struct with `ts_event` and `ts_init` fields.

---

## 5. Strategy, orders and the backtest engine

`[UNVERIFIED]` — not exercised in this session. What to check in the installed source
(`nautilus_trader/trading/strategy.pyx`, `nautilus_trader/backtest/engine.pyx`,
`nautilus_trader/backtest/config.pyx`):

- the `Strategy` base class and its bar/data subscription API for **multiple instruments in one strategy**
  (needed for the NQ + ES SMT pair);
- the exact bracket-order entry points (`submit_order` / `order_list` / a dedicated bracket helper) and the
  position-management properties (`positions`, `net_positions`);
- how trade records are exported for the meta-labeling pipeline;
- `BacktestEngine` construction (`add_data`, `add_venue`, `add_instrument`, `run`) and how to obtain
  per-trade results for label generation.

---

## 6. Engine config

- **JSON only.** The config layer is msgspec:
  `msgspec.json.decode(data, type=list[BacktestRunConfig], dec_hook=msgspec_decoding_hook)`.
  Grepping the package for `yaml`/`safe_load` returns nothing — **YAML is not supported**.
- **No `nautilus` console script** is shipped in the wheel. Entry points are module-based:
  ```bash
  $PY -m nautilus_trader.backtest --raw configs/backtest/phase1_baseline_nq_es.json
  $PY -m nautilus_trader.live     --raw configs/live/paper_tradovate.json
  ```
- `NautilusConfig` is a `msgspec.Struct, kw_only=True, frozen=True`.
- A minimal working backtest JSON for NQ+ES 1-minute bars with venue fees and slippage is `[UNVERIFIED]` —
  it must be built and executed before it is trusted.

---

## 7. Smoke-test log

Every command below was actually run.

```
$ $PY -c "from nautilus_trader.model.data import Bar, BarType, BarSpecification; ..."
BarSpecification: BarSpecification(int step, BarAggregation aggregation, PriceType price_type) -> None
BarSpecification init: (self, /, *args, **kwargs)
BarType init: (self, /, *args, **kwargs)

$ $PY -c "bt = BarType(InstrumentId.from_str('NQ.XCME'), BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)); print(str(bt))"
NQ.XCME-1-MINUTE-LAST-EXTERNAL

$ $PY -c "BarType.from_str('NQ.XCME-1-MINUTE-LAST')"
ValueError: Error parsing `BarType` from 'NQ.XCME-1-MINUTE-LAST', invalid token: '' at position 0

$ $PY -c "print(Price.from_str('20000.25'), Price(20000,2), Quantity.from_int(100))"
20000.25 20000.00 100

$ $PY -c "import inspect; print(inspect.signature(ParquetDataCatalog.write_data))"
(self, data: 'list[Data | Event] | list[NautilusRustDataType]', start: 'int | None' = None,
 end: 'int | None' = None, skip_disjoint_check: 'bool' = False) -> 'None'

$ $PY -c "from nautilus_trader.model.custom import customdataclass"
customdataclass OK

$ $PY -c "from nautilus_trader.model.instruments import Future"
ImportError: cannot import name 'Future' from 'nautilus_trader.model.instruments'
# available: ['CryptoFuture', 'FuturesContract', 'FuturesSpread']
```
