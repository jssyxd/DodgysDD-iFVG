#!/usr/bin/env bash
# The canonical benchmark entrypoint.
#
# Runs the capability benchmark offline and deterministically and prints the
# metrics in the `METRIC name=value` form the harness parses.
#
#   bash autoresearch.sh              # run the benchmark
#   bash autoresearch.sh --json out.json
#
# Exit codes:
#   0  the benchmark ran and no invariant was violated
#   1  an invariant was violated (a regression: the system is broken)
#   2  the benchmark itself could not run (missing fixture, broken import)
#
# No network, no clock dependence, no RNG state carried between runs: the
# fixtures are committed and every seeded computation is a pure function of
# its arguments.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# The 3.11 interpreter: nautilus_trader requires >=3.11,<3.14, and the
# system's own python3 is 3.14.
PYTHON="${AUTORESEARCH_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for candidate in \
    /home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11 \
    "$(command -v python3.11 || true)" \
    "$(command -v python3 || true)"
  do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)' 2>/dev/null; then
        PYTHON="$candidate"
        break
      fi
    fi
  done
fi

if [[ -z "$PYTHON" ]]; then
  echo "autoresearch.sh: no Python 3.11 interpreter found" >&2
  exit 2
fi

# Keep the run hermetic: no user site-packages auto-enabled, no implicit
# network.  The project's third-party dependencies (pandas, pyarrow, numpy)
# live in the *user* site directory of this interpreter, so that directory is
# resolved explicitly and put on PYTHONPATH rather than being picked up by
# whatever the ambient environment happens to have enabled.
export PYTHONNOUSERSITE=1
export PYTHONHASHSEED=0
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"

USER_SITE="$("$PYTHON" -c 'import site, sys; print(site.getusersitepackages())' 2>/dev/null || true)"
if [[ -n "$USER_SITE" && -d "$USER_SITE/pandas" ]]; then
  export PYTHONPATH="$USER_SITE${PYTHONPATH:+:$PYTHONPATH}"
fi

if ! "$PYTHON" -c 'import numpy, pandas, pyarrow' 2>/dev/null; then
  echo "autoresearch.sh: the benchmark needs numpy, pandas and pyarrow" >&2
  echo "  interpreter: $PYTHON" >&2
  echo "  install with: python3.11 -m pip install --break-system-packages numpy pandas pyarrow" >&2
  exit 2
fi

exec "$PYTHON" -m bench.run_benchmark "$@"
