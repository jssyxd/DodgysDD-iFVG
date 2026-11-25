"""The accounting statement every headline number must carry (D4).

The captain's decision **D4** is blunt about the trap this repo must not
repeat:

    *"The 'census' arm (one position per candidate, 423,759 overlapping
    positions) shows t = 15.28 and a CI excluding zero.  That is an artefact
    of correlated trades and is **not** a result.  The t-statistic must
    always be quoted from the one-position-at-a-time arm."*

R1's F8 found the trainer's CLI printing exactly that un-caveated figure.
The trainer was fixed; the **other** reporting surfaces were not:

* the walk-forward report (JSON),
* the per-fold rows,
* the kill-switch report,
* the trial registry's Parquet artefact,
* the runner's terminal output.

So the statement lives in one module and every surface carries it.  It is
data, not prose in a docstring: a report that does not carry it is a
report whose numbers can be quoted without their accounting.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ACCOUNTING_VERSION",
    "ACCOUNTING_STATEMENT",
    "accounting_fields",
    "accounting_line",
]

#: The version of the statement, so a report says *which* statement it
#: carries.
ACCOUNTING_VERSION = "d4-1"

#: The statement itself.
ACCOUNTING_STATEMENT = (
    "One position at a time. The expectancy, the profit factor and the "
    "t-statistic are quoted from this arm only: the overlapping census arm "
    "(one position per candidate) is correlated and is an artefact, not a "
    "result (D4). Costs are the configured profile, and the rule-only "
    "baseline is the comparison."
)


def accounting_fields() -> dict[str, Any]:
    """The statement as a field pair, for the JSON reports."""
    return {
        "accounting_statement": ACCOUNTING_STATEMENT,
        "accounting_version": ACCOUNTING_VERSION,
    }


def accounting_line() -> str:
    """The statement as one printable line."""
    return f"accounting: {ACCOUNTING_STATEMENT}"
