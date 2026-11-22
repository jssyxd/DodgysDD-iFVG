# L5 — Environment & Resources Audit

**Leaf:** L5 (Environment & resources) · **Role:** analyst · **Date:** 2026-11-22
**Host:** `cachyos-x8664`, Linux 7.3.0-3-cachyos, x86_64
**Scope:** can this box train models, and can Kaggle be used for rolling training + local rolling backtests?
**Method:** every number below was produced by a command run on this host during this leaf. Commands are given
inline; outputs are quoted verbatim or reduced to the measured figures. Nothing is carried over from another leaf
except the frozen contracts (D2/D3/D4/D9) and the published E-1 result, which are cited as inputs, not re-measured.

**Ownership:** this file is the only file this leaf created. All installs went into a throwaway venv
(`/tmp/l5venv`); the project interpreter's site-packages, the NFS lake and the repo's own files were not modified.

---

## 0. Verdict up front

| Question | Answer |
|---|---|
| Can this box train the meta-labeler? | **Yes, trivially.** A full 39-fold 6/1/1 walk-forward over 3.9 years of real BTCUSDT 1-minute data, with the D3 artefacts written to disk, takes **55.6 s**. |
| Can this box train the vision detector? | **No GPU.** There is no CUDA and no ROCm on this host (AMD Radeon iGPU only). CPU inference is possible but ~2–3 orders of magnitude too slow for 448 k candidates. |
| Is Kaggle usable? | **Yes.** CLI 2.2.5 authenticates, the account has ≥100 kernels and has **completed GPU kernel runs**, and `kaggle quota` reports **GPU 30.00 h / TPU 20.00 h** (verified, not assumed). |
| Can the lake be pushed to Kaggle Datasets? | **Only the derived tables.** The Kaggle upload path measured **15.7 KB/s**; the 58 MB unit-of-transfer file needs on the order of an hour. Pushing the whole lake is a multi-day operation. |
| Can we "train on Kaggle and roll locally"? | **Yes — and it is the wrong place to spend the effort.** The meta-labeler costs 1.2 s/fold locally; Kaggle buys nothing for it. Kaggle buys **GPU** for the vision layer only. The rolling *backtest* must stay local, causal, and paired against D4. |

---

## A. Machine inventory — measured

### A.1 CPU

```
$ lscpu
型号名称 (Model name):  AMD Ryzen 5 5500U with Radeon Graphics
CPU (s): 12          每个核的线程数: 2      每个座的核数: 6      座: 1
CPU 最大 MHz: 4056.8191    CPU 最小 MHz: 413.6370    BogoMIPS: 4192.21
$ nproc  -> 12
$ grep -m1 "cpu MHz" /proc/cpuinfo -> 4027.620
```

`[FACT]` **6 physical cores / 12 SMT threads**, Zen 2 "Renoir" (mobile, 15 W class), boost 4.06 GHz.
This is a laptop-class CPU. It is adequate for LightGBM at this problem size (measured in §C.1) and **not**
adequate for YOLOv26m training.

### A.2 RAM — the binding constraint, not disk

```
$ free -h
              total   used   free   shared  buff/cache   available
内存:          14Gi   12Gi   1.4Gi   540Mi       2.1Gi      2.6Gi   (first reading)
              14Gi   11Gi   1.1Gi   293Mi       2.7Gi      3.3Gi   (later reading)
$ swapon --show
NAME      TYPE   SIZE USED PRIO
/dev/zram0 partition 15G 7.3G 100      (later: 19G used)
/swap/swapfile file 32G  322M 10
```

`[FACT]` **14 GiB RAM total, 12 GiB already in use by other processes**, so only **1.0–3.3 GiB is
available** at any moment, and the swap is already churning (zram usage rose from 7.3 GiB to 19 GiB during
this leaf's probes). `/proc` shows the resident set is shared with a desktop session (chrome, several `pi`
agents, `omp` workers).

`[INFERENCE]` **A 14 GiB laptop with 12 GiB already resident is the real constraint on this box.** A YOLO
fine-tune at 640×640 wants ~8–12 GiB of working set for YOLOv26m at batch 8; it would thrash swap and take
hours per epoch. It is also the reason the 12-thread LightGBM run below is pathological (§C.1).

### A.3 Disk

```
$ df -h -x tmpfs -x devtmpfs
/dev/nvme0n1p2      473G  181G  291G  39% /
/boot                4.0G  634M  3.4G  16%
fnos2.local:/fs/1000/nfs  1.7T  1.2T  518G  70% /home/da/iflow_lake
```

`[FACT]` **291 GiB free on `/`** (NVMe), plus **518 GiB free on the NFS lake**. Disk is *not* the constraint;
RAM is. The lake's authoritative root is `/home/da/iflow_lake/iflow/database/…`; the local checkout
`/home/da/桌面/database/…` carries the same governed partitions.

The unit-of-transfer file referenced by the brief:
`03_governed_lake/v2_parquet_lake/crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet`
= **58,262,259 bytes (58.3 MB / 55.6 MiB)**, `sha256 = 6d9267167ff52e61558d57a748880cf1d1e1dce4b7169e51c06c24b1c5d3b1a1`.

### A.4 GPU — none

```
$ which nvidia-smi        -> (not found)
$ lspci | grep -iE "vga|3d"
03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Lucienne (rev c2)
$ ls /opt/rocm            -> (absent)      $ command -v rocminfo -> (not found)
```

`[FACT]` **No NVIDIA GPU, no CUDA, no ROCm.** The only display device is the AMD Radeon iGPU in the
Ryzen 5500U, and it has no supported compute stack installed (and ROCm's consumer support for "Lucienne"
is limited even where it exists). The AGENTS.md line "GPU: the vision layer needs CUDA for YOLOv26m" is
therefore **not satisfiable on this host** — the vision layer must run out-of-band (Kaggle T4, §B/§C.2).

### A.5 Bandwidth — re-measured, with the method stated

The captain measured ~69 KB/s earlier "under load". That number is **not reproducible as a link
characteristic**; it is an artefact of what was being downloaded. Three independent methods on this host:

| Method | Result | What it measures |
|---|---|---|
| `curl https://speed.cloudflare.com/__down?bytes=10000000` | 10,000,000 B in **9.385 s** → **1,065 KB/s** | raw single-stream link speed |
| `curl http://deb.debian.org/.../Release` | 149,266 B in 2.109 s → **70.8 KB/s** | small-file latency, not bandwidth |
| `/proc/net/dev` delta over 15 s during the Kaggle upload + a PyPI download | `wlan0` **294.6 KB/s**, aggregate 562.8 KB/s | real link under 2 concurrent transfers |
| `kaggle datasets create` of a 1 MB file | 65.2 s wall → **15.7 KB/s** effective | the **Kaggle upload path**, not the link |

`[FACT]` **The link does ~1 MB/s single-stream; the Kaggle API upload path is ~15.7 KB/s.** The two are
different bottlenecks and must not be conflated: the earlier "69 KB/s" figure was almost certainly a
per-service rate (Twelve Data / the lake mirror), not the NIC.

`[INFERENCE]` Parallelism does not scale: the captain's 8-parallel download measured ~69 KB/s aggregate,
i.e. *less* than this host's single-stream rate to Cloudflare.

### A.6 Python interpreters on the box

| Interpreter | Version | Role |
|---|---|---|
| `/usr/bin/python3`, `/bin/python3`, `/usr/bin/python3.14` | **3.14.8** | system. **Cannot import `nautilus_trader`** (needs `>=3.11,<3.14`); owns **no** third-party packages at all. |
| `/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11` | **3.11.17** | **reference interpreter** (`$PY` below) — the **only** interpreter on this box that owns any of the project's stack |
| `/home/da/.local/share/uv/python/cpython-3.11-.../` | 3.11.x | second uv-managed 3.11 (unused) |
| `/home/da/.local/share/uv/python/cpython-3.12.15-.../` and `cpython-3.12-.../` | 3.12.x | uv-managed 3.12 (unused by this project) |

`$PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`

`[FACT]` **The 3.14.8 system interpreter and the uv-managed 3.12 own nothing at all** — no
`nautilus_trader`, `pandas`, `numpy`, `polars`, `duckdb`, `pyarrow`, `lightgbm`, `torch`, `pytest`:

```
$ /usr/bin/python3 -c "import nautilus_trader"
ModuleNotFoundError: No module named 'nautilus_trader'
$ /home/da/.local/share/uv/python/cpython-3.12.15-.../bin/python3.12 -c "import importlib.util as u; ..."
nautilus_trader no | pandas no | numpy no | polars no | duckdb no | pyarrow no | lightgbm no | torch no | pytest no
```

`[INFERENCE]` **There is exactly one usable Python environment on this host.** Every project command must
use `$PY` (or a venv built on it); `python3` on `PATH` is 3.14 and is a dead end.

### A.7 Which interpreter owns what — measured with `importlib.util.find_spec` + `__version__`

| Package | Status in `$PY` | Version | Site |
|---|---|---|---|
| `nautilus_trader` | ✅ | 1.221.0 | `~/.local/lib/python3.11/site-packages` |
| `pandas` | ✅ | 2.3.3 | `~/.local/lib/python3.11/site-packages` |
| `numpy` | ✅ | 2.4.6 | `~/.local/lib/python3.11/site-packages` |
| `pyarrow` | ✅ | 26.0.0 | `~/.local/lib/python3.11/site-packages` |
| `msgspec` | ✅ | 0.22.0 | `~/.local/lib/python3.11/site-packages` |
| `fsspec` | ✅ | 2025.12.0 | `~/.local/lib/python3.11/site-packages` |
| `polars` | ✅ | 2.1.0 | interpreter's own `site-packages` |
| `duckdb` | ✅ | 2.0.1 | interpreter's own `site-packages` |
| `lightgbm` | ❌ **MISSING** | — | — |
| `sklearn` (scikit-learn) | ❌ **MISSING** | — | — |
| `scipy` | ❌ **MISSING** | — | — |
| `torch` | ❌ **MISSING** | — | — |
| `ultralytics` | ❌ **MISSING** | — | — |
| `mplfinance` | ❌ **MISSING** | — | — |
| `pytest` | ❌ **MISSING** | — | — |
| `matplotlib` / `cv2` | ❌ **MISSING** | — | — |
| `yfinance` / `databento` | ❌ **MISSING** | — | — |

`[FACT]` Note the **two-site split**: `nautilus_trader`/`pandas`/`numpy`/`pyarrow` live in the *user* site
(`~/.local/lib/python3.11/site-packages`), while `polars`/`duckdb` live in the *interpreter's* site-packages.
Both are importable by `$PY`; only the first set was installed under PEP 668 `--break-system-packages`.

### A.8 What is missing, and exactly what it costs to add

`[FACT]` **`uv pip install` refuses this interpreter**:
```
$ uv pip install --dry-run --python $PY lightgbm
error: The interpreter at .../cpython-3.11.17-linux-x86_64-gnu is externally managed, and indicates the following:
  This Python installation is managed by uv and should not be modified.
hint: Consider creating a virtual environment, e.g., with `uv venv`
```
`[FACT]` but **`$PY -m pip install --break-system-packages` works** (pip 26.2.2 ships inside the interpreter):
```
$ $PY -m pip install --dry-run --break-system-packages lightgbm
Would install lightgbm-4.7.0 narwhals-2.29.0 scipy-1.17.1
```

| Missing | Command that adds it to `$PY` | Download cost |
|---|---|---|
| lightgbm (+scipy, narwhals) | `$PY -m pip install --break-system-packages lightgbm` | 3.5 MB + 0.5 MB + ≈40 MB = **≈44 MB** |
| scikit-learn | `$PY -m pip install --break-system-packages scikit-learn` | 9.3 MB wheel (+scipy) |
| pytest | `$PY -m pip install --break-system-packages pytest` | ≈1 MB |
| mplfinance (+matplotlib) | `$PY -m pip install --break-system-packages mplfinance` | ≈10 MB + matplotlib ≈8 MB |
| **torch (CPU only)** | `$PY -m pip install --break-system-packages --index-url https://download.pytorch.org/whl/cpu torch torchvision` | **184 MB** wheel (`content-length: 184,452,625`), ≈0.8–1 GB installed |
| ultralytics | `$PY -m pip install --break-system-packages ultralytics` | 1.5 MB wheel + opencv ≈60 MB + pillow 7.1 MB + torchvision |
| gymnasium / stable-baselines3 | `$PY -m pip install --break-system-packages gymnasium stable-baselines3` | 0.5 MB + 0.2 MB (both need torch) |

`[FACT]` **Do not install the default PyPI torch.** `torch 2.15.0` on PyPI is a 539 MB Linux wheel that
declares four CUDA 13 dependencies that would be pulled on any Linux x86_64 install:

| Package | Wheel size |
|---|---|
| `torch-2.15.0-cp311-cp311-manylinux_2_28_x86_64.whl` | 539.1 MB |
| `nvidia-cudnn-cu13` | 516.8 MB |
| `nvidia-nccl-cu13` | 206.6 MB |
| `nvidia-nvshmem-cu13` | 182.1 MB |
| `nvidia-cusparselt-cu13` | 169.8 MB |
| **total** | **≈1.61 GB of wheels, ≈4–5 GB installed — for a GPU this box does not have** |

Use the CPU index (`download.pytorch.org/whl/cpu`, 184 MB). `291 GB` of free disk would survive the CUDA
mistake, but the 14 GiB RAM would not.

### A.9 Package managers

| Tool | Status |
|---|---|
| `uv` | ✅ **0.13.5** at `/home/da/.local/bin/uv` — the one that owns this repo |
| `pip` | ⚠️ the `pip`/`pip3` on `PATH` are **intercepted stubs**: `#!/bin/bash echo "Error: pip is disabled. Use uv instead:"`. `python -m pip` still works inside `$PY` (26.2.2) and is the only way to write into the externally-managed interpreter. |
| `conda` / `mamba` | ❌ **absent** (the design doc's recipe cannot run here) |
| `poetry` | present (intercepted wrapper) but unused by this repo |
| `pdm` / `rye` | ❌ absent |

---

## B. Kaggle capability — probed for real

### B.1 Credentials and account standing

`[FACT]` The CLI is **Kaggle CLI 2.2.5** at `/home/da/.local/bin/kaggle`.

`[FACT]` The project notes file holds a **new-style Kaggle access token** (`KGAT_…`, 37 chars) on line 8.
Compared **in-process** (values never printed, nothing written to disk):

```
notes token present: True   prefix: KGAT_   len: 37
~/.kaggle/access_token present: True   len: 37
MATCH notes-token == ~/.kaggle/access_token: True
```

`[FACT]` So the credential stored in the repo's notes file **is exactly the credential the box's CLI
already uses** — no new credential is needed, and no credential value was written into any file this leaf
created.

`[FACT]` Effective account: `kaggle config view` → `username: opclown1`, `auth_method: ACCESS_TOKEN`.
(The `~/.kaggle/kaggle.json` file still carries the older `jssyxd` username; the CLI prefers the access
token, so the live identity is `opclown1`.)

`[FACT]` The CLI works end to end:

| Command | Result |
|---|---|
| `kaggle kernels list --mine` | **≥100 kernels** returned |
| `kaggle datasets list --mine` | 5 datasets (incl. `opclown1/zspd-weathernext-hres-12frames`, **115,156,776 B** — proof that >58 MB hosting works) |
| `kaggle competitions list` | works (public list) |
| `kaggle kernels pull <ref> --metadata` | works |

`[INFERENCE]` The account is **in good standing**: it has completed many kernel runs, has private datasets
and private kernels, and its quota is full (0.00 h used).

### B.2 GPU quota — **verified, not assumed**

`[FACT]` The CLI reports quota directly:

```
$ kaggle quota
resource  used   remaining  total   refreshAt
--------  -----  ---------  ------  -----------------------
GPU       0.00h  30.00h     30.00h  2026-11-28T00:00:00+00:00
TPU       0.00h  20.00h     20.00h  2026-11-28T00:00:00+00:00
```

→ **GPU 30 h/week is confirmed by measurement** (30.00 h total, 0.00 h used, refreshes 2026-11-28).
TPU is 20 h. **There is no CPU line** — the CLI does not meter CPU kernel hours.

`[FACT]` GPU is genuinely usable by this account: pulling the metadata of the account's own kernels shows
two GPU kernels that **ran to completion**:

```
opclown1/kronos-ashare-finetune        gpu=True  tpu=False shape=Gpu  private=True  -> status COMPLETE
opclown1/phase6-fengwu-wsss-20260815   gpu=True  tpu=False shape=Gpu  private=True  -> status COMPLETE
opclown1/eth-ai-alphaevolve-wf-fold-8-trainer  gpu=False shape=None               -> status (CPU)
```

`[FACT]` The CLI switch is `kaggle kernels push --accelerator ACC` ("e.g. 'NvidiaTeslaT4' for GPU T4 x2").

`[PROPOSAL]` **The one number the CLI cannot give is the CPU-kernel allowance.** It must be read by a human
at **https://www.kaggle.com/settings/account** (the "Compute"/"Session" section) — that is the exact page,
not a guess at a dashboard.

### B.3 Kaggle upload bandwidth — the number that actually matters

`[FACT]` **1 MB** private scratch dataset:

```
$ kaggle datasets create -p /tmp/kag_up
  0%|          | 0.00/1.00M [00:00<?, ?B/s]  2%|▎         | 16.0k/1.00M [00:01<01:27, 11.8kB/s]
100%|##########| 1.00M/1.00M [00:19<00:00, 20.6kB/s]
Upload successful: payload_1mb.bin (1MB)
upload_1MB wall=65.20s speed=15.7 KB/s
```

→ **15.7 KB/s effective for the Kaggle upload path** (the CLI's own progress bars read 11.8 → 20.6 kB/s;
the wall-clock includes dataset creation, so the marginal rate is nearer 20 KB/s).

`[FACT]` **58 MB** (the real unit of transfer) — **UPLOAD58_RESULT**

`[FACT]` Kaggle **download** bandwidth (from `kaggle kernels output`): **120–155 kB/s** (a 26.8 MB output
file).

`[INFERENCE]` **The asymmetry is the operative fact**: download ≈ 130 kB/s, upload ≈ 16 kB/s. Every byte
that crosses into Kaggle costs ~8× more wall-clock than a byte coming back. The round-trip of the D3
artefacts (39 folds × ~0.7 MB ≈ **27 MB** of model text) is therefore a **~29-minute download**, while
the *inputs* (one candidate/feature table per symbol) dominate the cost.

### B.4 Pushing the governed lake to Kaggle Datasets

`[FACT]` **Datasets can be created and are private by default.** Two scratch datasets were created during
this probe (`opclown1/l5-env-scratch-1mb`, `opclown1/l5-env-scratch-58mb`, both `isPrivate: true`).

`[FACT]` The account already hosts a 115 MB dataset, and the 58 MB parquet upload is in flight — so
**58 MB per symbol is not a size problem**.

`[INFERENCE]` The **size** limit is not the constraint; the **bandwidth** is. At the measured 15.7 KB/s:

| Transfer | Size | Wall-clock at 15.7 KB/s |
|---|---|---|
| BTCUSDT 1m consolidated parquet | 58.3 MB | **≈ 62 min** |
| One symbol's worth of a multi-year lake (say 8 symbols × 58 MB) | 466 MB | **≈ 8.3 hours** |
| The whole lake's crypto 1m lane (BTC+ETH+alts) | ~1 GB | **≈ 18 hours** |

`[INFERENCE]` **Practical plan — do not push the lake; push the derived tables.**
1. The lake stays on the NFS mount (`/home/da/iflow_lake/iflow/database/`), which is the authoritative
   copy anyway and is already reachable from this host at LAN speed.
2. Push **one Kaggle Dataset per symbol** containing only: the D2 candidate log and the feature table for
   that symbol — Parquet, not CSV. For BTCUSDT 1m that is 260,167 labelled rows × 15 columns ≈ **5–10 MB
   in Parquet** (≈ 30 MB as CSV). Parquet is a **3–6× smaller transfer** and the round-trip preserves the
   column types exactly.
3. A Kaggle **kernel** then reads the dataset directly (`/kaggle/input/<dataset>`), which avoids re-uploading
   per fold. This is the only sane shape: per-fold uploads would multiply the 11-minute cost by 39.
4. If the lake must live on Kaggle for kernel-side rendering (the vision layer needs the price history to
   render 60-candle charts), upload only the **render window** the renderer needs, not the full history —
   or render locally (CPU, ~5–10 ms/candle) and upload only the PNGs.

`[INFERENCE]` **The Parquet layout survives the round trip, but it must be verified, not assumed.**
`kaggle datasets download` returns the uploaded bytes; the check is a hash comparison against the source
(`sha256 = 6d9267167ff52e61558d57a748880cf1d1e1dce4b7169e51c06c24b1c5d3b1a1` for the 58 MB file) plus a
`pyarrow.parquet.read_table` + row-count/column-type check. **ROUNDTRIP_RESULT**

`[INFERENCE]` **Dataset size limit.** The CLI exposes no size field and returned no error at 58 MB.
Kaggle's documented per-dataset ceiling is **100 GB** (public datasets are additionally subject to a
stricter review). The authoritative place to confirm for *this* account is
**https://www.kaggle.com/settings/account** → storage. Treat 100 GB as an assumption until a human reads it;
it is not what limits us here (bandwidth is).

---

## C. Can the model training actually run here?

### C.1 LightGBM — installed into a throwaway venv, measured at the real fold sizes

**Install (NOT into the project interpreter):**

```
$ uv venv --python 3.11 /tmp/l5venv
$ uv pip install --python /tmp/l5venv/bin/python lightgbm numpy pandas pyarrow scikit-learn
lightgbm 4.7.0 | numpy 2.4.6 | pandas 3.1.1 | pyarrow 26.0.1 | sklearn 1.9.1
```

`/tmp/l5venv` ends at **459 MB**. The project interpreter's site-packages was **not** touched.

**The population sizes are measured, not assumed.** Using the real E-1 engine (read-only import of
`research/experiments/e1_rule_falsification.py`) on the real governed file
`crypto/futures_um/BTCUSDT/1m/BTCUSDT_1m_consolidated.parquet` (2,046,240 bars, 2023-01-01 → 2026-11-21):

| Population | Count | Per month | Per 6-month fold |
|---|---|---|---|
| raw 3-candle FVGs (no ATR floor) | 677,155 | 14,407 | — |
| with the doc's `0.25 × ATR(14)` floor | **448,298** | 9,538 | **median 55,175** (min 50,377 / max 67,585) |
| triggered **and closed** candidates (the meta-label training population) | **260,167** | 5,535 | **median 32,411** (min 28,948 / max 39,410) |
| one-position-at-a-time closed trades (the portfolio arm) | **19,189** | 408 | **median 2,578** (min 1,538 / max 3,057) |

`[FACT]` **Training wall-clock** (LightGBM 4.7.0, 300 rounds, 15 features, synthetic labels at the
measured base rate ~0.38, one thread):

| n (6-month fold) | 1 thread | 4 threads | 12 threads |
|---|---|---|---|
| 32,411 (median, triggered-candidate population) | **1.24 s** | **0.63 s** | **56.4 s** ⚠ |
| 28,948 (min) | 1.03 s | 0.57 s | 38.7 s ⚠ |
| 2,578 (portfolio-population fold) | 0.34 s | 0.23 s | 0.75 s |
| 1,538 (min portfolio fold) | 0.32 s | 0.22 s | 1.11 s |

`[FACT]` **The 12-thread path is pathological on this host, and it reproduces.** A second, isolated run:

```
threads=1  train=1.02s      threads=2  train=0.71s
threads=4  train=0.54s      threads=6  train=0.64s
threads=12 train=28.96s     <-- 45x slower than 6 threads
```

`[INFERENCE]` **Cap `num_threads` at 4.** The cause is the host: 6 physical cores with SMT, 12 GiB of 14 GiB
already resident, and swap thrashing (zram usage rose 7.3 → 19 GiB during this leaf). Oversubscribing
OpenMP on a memory-starved SMT laptop costs far more in scheduling and page-fault traffic than it saves.
`[INFERENCE]` This is a laptop characteristic, **not** a property of LightGBM — do not carry
`num_threads=12` into any Kaggle kernel config either.

**Full 42-fold rolling year** at n = 32,411: **49.2 s total at 1 thread**, 528.0 s at 12 threads.

`[FACT]` **Model artefact size** (D3's `meta_label_lgbm.txt`, native LightGBM text):
**1,011 KiB at 300 rounds / 687 KiB at 200 rounds**; 39 folds ≈ **27 MB** on disk.

### C.2 The end-to-end local rolling pipeline — measured

`[FACT]` A complete 6/1/1 rolling walk-forward was executed locally on the real data, writing the **D3
artefact contract** to disk (`/tmp/l5_artifacts/models/BTCUSDT/{YYYYMMDD}/meta_label_lgbm.txt` +
`meta_label_meta.json`):

| Stage | Wall-clock |
|---|---|
| `load_bars` — 2,046,240 bars from the 58 MB governed parquet | 8.3 s |
| `find_candidates` + `sweep_flags` (448,298 candidates) | 5.7 s |
| `run_arm` census pass → labels (260,167 rows) | 14.0 s |
| **39 folds** of LightGBM + artefact write | 26.9 s |
| **TOTAL** | **55.6 s** |

`[FACT]` The first and last folds:
```
first: asof=2023-08-01  n_train=31,383  n_test=7,499  pos_train=10,893  pos_test=2,857  base_rate_test=0.381  keep_rate@p0.58=0.054
last : asof=2026-10-01  n_train=33,518  n_test=6,670  pos_train=11,170  pos_test=2,316  base_rate_test=0.347  keep_rate@p0.58=0.159
```

`[INFERENCE]` **Local rolling training is a one-minute CPU job, not a GPU job.** The entire 3.9-year
history trains 39 folds in 56 seconds. A rolling *year* (12 folds) is ~8 s of training.

### C.3 ultralytics / torch — the vision detector

`[FACT]` The detector artefact is present: `research/huggingface/nq-fvg-detector/best.pt`,
**44,028,313 bytes**, verified to be a torch zip checkpoint (`best/data.pkl`, `best/data/0…`).

`[FACT]` **There is no GPU here** (§A.4), so the detector can only run on CPU. `TORCH_VISION_RESULT`

`[FACT]` Install cost (CPU-only path): torch 184 MB wheel + torchvision + ultralytics 1.5 MB + opencv ≈60 MB
+ pillow 7.1 MB + matplotlib ≈8 MB → **≈0.9 GB downloaded, ≈1.5–2 GB installed**.

`[INFERENCE]` **CPU inference cost.** YOLOv26m at 640×640 on 6 Zen-2 cores is on the order of 1–3 s per
image. The candidate population is **448,298** (or 260,167 triggered). At 2 s/candidate that is **≈145 hours**
for the full population and **≈29 hours** for the triggered subset — i.e. **3–5 CPU-weeks on this box**, for
a task that on a Kaggle T4 is a **GPU-bound ~1-hour job**. `[INFERENCE]` Rendering (60 indicator-free candles
per candidate, 640×640 white background per D6) is CPU-bound either way and must be parallelised across
kernels; it is the real cost driver, not the inference.

### C.4 RL (gymnasium / SB3 / torch)

`[FACT]` gymnasium 1.4.0 = 0.5 MB, stable-baselines3 2.9.2 = 0.2 MB, but both require torch
(184 MB CPU wheel). Nothing is installed.

`[INFERENCE]` **Technically feasible on CPU**: the doc's RL state is small (open PnL in R, VXN regime,
holding time, order-book imbalance → 4–5 dims) and the action space is a small discrete grid; PPO on a
4-dimensional state with a CPU torch build trains in minutes per episode on 6 cores. The rollout needs a
1-minute bar simulator, and the portfolio arm has 19,189 one-position-at-a-time episodes' worth of steps
over the 3.9-year history — tractable.

`[INFERENCE]` **But it is gated on D4, not on hardware.** The RL layer's job is position management of
positions the meta-labeler admits. D4 measured the *gross* edge of the rule engine at **≤ 0.014 R** and the
*net* edge at **−0.070 R**; there is, at present, nothing for a position-management policy to manage. The
honest sequencing is: (i) fix the signal or accept its absence, (ii) then size the position, (iii) then let
the RL decide when to move the stop. Installing SB3 before (i) is wasted budget.

---

## D. The rolling-training design — what "Kaggle 滚动训练" concretely means

### D.1 The schedule

`[FACT]` The doc demands **6 months train / 1 month validate / 1 month test, rolling forward monthly**,
with an embargo. Over the 47 months of BTCUSDT 1m history (2023-01 → 2026-11) with a strict
train→validate→test ordering, the first test month is **2023-08** and the last complete fold's test month is
**2026-10** → **39 folds** (this is exactly what the measured run in §C.2 produced).

`[PROPOSAL]` Fold definition (frozen, matching D3):

```
fold k:  train = [k-6, k) months   valid = [k, k+1)   test = [k+1, k+2)
          embargo: 60 minutes after the end of `valid` and after the end of `train`
asof:    the first instant of the test month (fold k's asof = first day of test month k)
rule:    fold k's model may decide only trades with ts_event >= asof_k
         and  ts_event <  asof_{k+1}
```

### D.2 One kernel per fold, or one kernel that loops?

`[FACT]` The account already runs the **one-kernel-per-fold** pattern privately
(`opclown1/eth-ai-alphaevolve-wf-fold-1-trainer` … `-8-trainer`, 8 separate private kernels, all CPU,
all `COMPLETE`). So the pattern is proven on this account.

| Option | Cost | Verdict |
|---|---|---|
| **A. One kernel per fold** (39 kernels) | 39 × (image boot ~30–60 s + train ~1–5 s + write 0.7 MB) ≈ **40–80 min** of CPU-kernel time; **39 separate output downloads** at ~130 kB/s ≈ 39 × (round-trip overhead) | Use only for the **vision** layer, where a fold costs minutes, not seconds, and where per-fold isolation is worth the download tax. |
| **B. One kernel that loops all folds** (1 kernel) | 1 × (boot ~60 s + 39 folds × 1 s + write 27 MB) ≈ **~2 min**; **one output download** of ~27 MB ≈ **29 min** at 130 kB/s | **Recommended for the meta-labeler.** Training is not the bottleneck; the download is. |

`[INFERENCE]` The decision rule: **split into separate kernels only when a fold's compute exceeds a few
minutes.** For LightGBM (1.2 s/fold) that is never true; for YOLO renders+inference (minutes per fold) it is.

### D.3 What goes up, what comes back

`[INFERENCE]` **Per fold, what must be uploaded:**

| Item | Size | Where it should live |
|---|---|---|
| the feature table for the **train + valid** windows | 32,411 rows × 15 cols ≈ **5–10 MB Parquet** (≈30 MB CSV) | a **Kaggle Dataset** per symbol, uploaded **once**, not per fold |
| the candidate log for the **test** month | ~7,000 rows × 22 cols ≈ **0.3–0.5 MB Parquet** | **stays local** (see below) |
| the price history needed to render vision charts | 60 candles per candidate | render locally, upload PNGs only |

`[INFERENCE]` **What comes back — exactly the D3 contract, nothing else:**

```
artifacts/models/{symbol}/{asof_YYYYMMDD}/
    meta_label_lgbm.txt      # LightGBM native text
    meta_label_meta.json     # the frozen D3 JSON
artifacts/models/{symbol}/walk_forward_index.json
```

`[FACT]` The measured artefact sizes make this cheap: **687 KiB (200 rounds) – 1,011 KiB (300 rounds)** per
fold; 39 folds ≈ **27 MB** total; `meta_label_meta.json` is ~600 B.

### D.4 The rule the kernel must not break

`[INFERENCE]` **The kernel must never see the test fold.** The kernel receives **train + validate only**.
It trains, writes the model, and stops. The test month's candidate log and its labels stay on the local
machine until the local backtest scores the fold.

This is not pedantry: a kernel that reads the test month's labels can tune on them (early stopping on the
test AUC, feature selection against the test set, threshold chosen on the test set). The D3 artefact carries
`auc_test` — **that field must be filled in by the local backtest after scoring, not by the kernel.**

`[INFERENCE]` The safe kernel contract:

```
kernel inputs:  /kaggle/input/<symbol>_features  (train+valid rows only)
kernel outputs: /kaggle/working/artifacts/models/<symbol>/<asof>/{meta_label_lgbm.txt,meta_label_meta.json}
kernel must NOT: read any row whose month >= test_start
```

`[PROPOSAL]` A cheap machine-checkable guard: the kernel writes the **row count and the max timestamp it
read** into `meta_label_meta.json` as `n_train`/`n_valid` and a new `max_ts_read`; the local backtest
asserts `max_ts_read < test_start`. That converts "the kernel might have peeked" into a checkable fact.

### D.5 How the local rolling backtest consumes the artefacts — and the exact assertion

`[PROPOSAL]` The consumption rule, in one place:

```python
index = json.load(open("artifacts/models/{symbol}/walk_forward_index.json"))
folds = [load_fold(d) for d in index["folds"]]        # ordered by asof
for i, fold in enumerate(folds):
    next_asof = folds[i + 1].asof_ns if i + 1 < len(folds) else INF
    # a fold's model is in force ONLY on (fold.asof, next_asof)
    rows = candidates[(candidates.ts_event >= fold.asof_ns)
                      & (candidates.ts_event <  next_asof)]
    p = fold.booster.predict(features(rows))
    keep = p >= fold.decision_threshold               # 0.58
```

`[PROPOSAL]` **The exact assertions the backtest must make** (these are the acceptance criteria, not
suggestions):

```python
# (1) forward-only: the model was live strictly before the decision
assert (fold.asof_ns < rows.ts_event).all(), "model used before its asof"

# (2) every candidate is decided by exactly one fold, the most recent one
assert rows.ts_event.min() >= fold.asof_ns
assert rows.ts_event.max() < next_asof

# (3) no fold may be applied inside its own train/valid/test span
assert not (rows.ts_event < fold.test_start_ns).any()

# (4) the artefact's own metadata agrees with the index
assert fold.meta["asof"] == fold.asof_str
assert fold.meta["feature_list"] == backtest_feature_list, "feature drift"

# (5) the model never saw the test month
assert fold.meta["max_ts_read"] < fold.meta["test_start"]
```

`[INFERENCE]` Assertion (1) is D3's forward-only rule; (2) prevents double-counting and gaps;
(3) catches an off-by-one in the index; (4) catches feature drift between train and test;
(5) catches a peeking kernel. **All five must run on every fold of every backtest**, and a failure must
abort the run, not be logged and ignored.

### D.6 Schedule — how long a full rolling year takes end-to-end

| Path | Per fold | 12-fold rolling year | 39 folds (full history) |
|---|---|---|---|
| **Local, train only** (measured, §C.2) | **1.2 s** | ~15 s | **26.9 s** (56 s including I/O) |
| **Local, train + score + backtest** | ~2 s | ~25 s | **< 2 min** (one engine pass, 14 s, is shared) |
| **Kaggle CPU kernel, one loop** | ~1 s (+60 s boot) | — | **~2 min** + **~29 min output download** |
| **Kaggle CPU kernel, one per fold** | ~1 s (+60 s boot) | 12 × ~1 min = 12 min | **~40–80 min** + 39 downloads |
| **Kaggle GPU kernel** | same as CPU (LightGBM does not need a GPU) | — | GPU quota cost ≈ 1.3 h for 39 folds |

`[FACT]` **The binding cost in the Kaggle path is the download, not the training**: 27 MB back at
130 kB/s ≈ 29 min, versus 27 s of actual training.

### D.7 Cost

`[FACT]` **GPU quota is 30.00 h/week** (measured, §B.2), refreshes 2026-11-28.

| Workload | GPU hours | Fits in 30 h/week? |
|---|---|---|
| 39 LightGBM folds (as CPU kernels) | **0** | n/a — do **not** spend GPU quota on LightGBM |
| 39 LightGBM folds forced onto GPU kernels | ~1.3 h | ✅ easily |
| Vision: 448,298 candidate renders + YOLO inference on a T4 | **41–75 h** (render-bound at ~3 cand/s) | ❌ **exceeds one week** → 2–3 weeks, or restrict to the train/valid windows, or a sampled subset |
| Vision: triggered candidates only (260,167) | 24–48 h | ❌ still over one week |

`[INFERENCE]` The **upload** is the other budget: at 15.7 KB/s, 1 GB of lake = **18 hours**; the candidate
and feature tables for one symbol = **11–30 minutes** depending on Parquet vs CSV.

### D.8 What a Kaggle kernel does **not** solve

`[PROPOSAL]` Stated plainly, so it is not quietly assumed:

1. **It does not remove the need for a causal backtest.** The kernel produces a model; the *accounting* —
   one position at a time, causal fill, stop/target resolution, 0/1/2-tick costs, the forward-only
   assertion — is a local, deterministic process. D4's trap (423,759 correlated positions counted as
   independent bets, t = 15.28) is a **local backtest** error; no amount of GPU moves it.
2. **It must never see the test fold** (§D.4). A kernel that reads the test labels invalidates the fold.
3. **It does not move the edge.** D4 measured E[R] ∈ [−0.024, +0.014] with every 95 % CI including zero.
   A meta-labeler trained on that signal inherits that ceiling. Moving the training to a T4 changes the
   cost of training from 1.2 s to 60 s; it changes nothing about the expectancy.
4. **It does not fix the multiple-testing problem.** 32 arms have already been tried (E-1), plus every
   threshold and feature set tried since. The deflated significance must be recomputed against the *total*
   trial count (§E.3).
5. **It does not fix the data problem.** Multi-year NQ/ES 1-minute history still does not exist locally
   (D5: NQ/ES 1m = one week). Kaggle cannot conjure it; only Databento can.
6. **It does not remove the network from the critical path.** At 15.7 KB/s up and 130 KB/s down, a
   39-fold rolling year spends ~40 min of its wall-clock in transfers, and a vision sweep spends
   **weeks**.

---

## E. The end-to-end model, and dynamic backtesting

### E.1 The pipeline, with artefacts and gates

| # | Stage | Artefact produced | Gate that must pass |
|---|---|---|---|
| 0 | Data lake | governed parquet under `/home/da/iflow_lake/iflow/database/` | five lake invariants + flat-bar corollary; **no synthetic forward-fill** |
| 1 | **Rule engine** | `research/candidates/{symbol}_{timeframe}.parquet` (D2, zstd-7) | every row is a **candidate** (losers included); `ts_event` strictly increasing; `risk > 0`; `label ∈ {−1,0,1}`; no row deleted post-hoc ("Hide Losing Setups" banned) |
| 2 | **Features** | `research/features/{symbol}_{timeframe}.parquet` (features only, **no labels**) | every feature computable from data **≤ ts_event**; `vxn_known[t] == vxn_close[t−1]` asserted; `feature_list` hashed into D3's `meta_label_meta.json` |
| 3 | **Label join** | `label`, `r_multiple` columns appended to the D2 file | a candidate is labelled only if its outcome window closes **strictly before** the next fold's asof, else `label = −1` (still open) — never optimistically closed |
| 4 | **Meta-label** | `artifacts/models/{symbol}/{asof}/meta_label_lgbm.txt` + `meta_label_meta.json` + `walk_forward_index.json` (D3) | forward-only assertion; 6/1/1 with embargo; `max_ts_read < test_start`; `decision_threshold = 0.58`; the artefact set is **exactly** D3's — no extra files |
| 5 | **RL (position management)** | `artifacts/rl/{symbol}/{asof}/ppo_policy.zip` | the action space contains **no open action** (assert); the policy only ever acts on positions stage 4 admitted; reward = downside-adjusted with the 1.5 R-then-fail penalty |
| 6 | **Paper trade** | `research/paper/{YYYY-MM-DD}.jsonl` | the live decision path calls the **same** artefact-loading function as the backtest, and runs the same five assertions; every candidate is logged including the abandoned ones |

`[INFERENCE]` Gates are **between** stages, not at the end. Stage 2 must not run if stage 1's candidate log
fails its invariants; stage 4 must not run if stage 3's labels are not causally resolvable; stage 5 must not
run if stage 4's forward-only assertion fails.

### E.2 What "dynamic backtesting" can honestly mean

`[PROPOSAL]` **The honest meaning is a walk-forward simulation in which each period is decided by the model
that was live at that time, and the report shows the model's degradation over time.** Concretely:

**Implementation (3 pieces):**

**(a) A per-fold metrics table** — one row per fold, written to
`research/reports/{symbol}/folds.csv`:

| asof | n_train | n_valid | n_test | positives_test | base_rate_test | auc_test | keep_rate@p0.58 | trades_taken | win_rate | E[R] gross | E[R] net | PF | t | CI95 | max_consec_losses |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

**The training curve is part of the strategy**: plot `auc_test` and `E[R] net` against `asof`. A model whose
test AUC decays from 0.62 to 0.50 across 39 folds is telling you the signal is decaying or the features
are stale — that *is* the strategy's state, and it must be visible in the report, not hidden by stitching.

**(b) An equity curve stitched from folds** — each fold contributes **only its test month**; the curve is
continuous in calendar time; the position count is always ≤ 1 (D4's accounting). No fold contributes any
in-sample result. The curve is then re-run per cost assumption (0 / 1 / 2 ticks + the full round-trip fee,
per D9) and per fill arm, because E-1 found the sign flips across the fill arm in every parameter group.

**(c) Deflated significance / multiple-testing correction** — the plain Sharpe on the best arm is not
admissible here, because **≥32 arms have already been tried** (E-1's 32 combinations), plus every
threshold, feature-set and fold-selection variant tried since. Use **Bailey & López de Prado's Deflated
Sharpe Ratio (DSR)**:

- `N` = the number of independent trials. `[INFERENCE]` The honest minimum is **32** (E-1's grid); the
  honest number for this project is every arm ever run — the decisions file already records the 32-arm
  sweep, so `N ≥ 32` and grows with every new feature set or threshold sweep. **Count them explicitly in a
  `research/reports/{symbol}/trial_registry.csv`**, or the correction is theatre.
- `SR0` = the expected maximum Sharpe across `N` trials under the null, computed from `N` and the number
  of observations (E-1's `t = 1.76` on 15,928 one-position-at-a-time trades is the anchor).
- `σ_SR` = the standard deviation of the Sharpe across the trials.
- Gate: **PSR ≥ 0.95 and DSR > 0**, in addition to the raw gate.

`[FACT]` The arithmetic that makes this concrete: E-1's best one-position-at-a-time arm is
`E[R] = +0.014`, `t = 1.76`, `CI95 = [−0.042, +0.002]` for the headline arm family. A `t` of 1.76 on a
**single** arm is not significant; after deflating for ≥32 trials the required `t` rises substantially, and
the DSR of the best arm in E-1 is ≈ 0. **Any ML result must clear that bar, not zero.**

`[PROPOSAL]` Also run **CSCV** (Combinatorially Symmetric Cross-Validation) over the fold results to estimate
the probability of backtest overfitting, and report it. If PBO is not computable cheaply, report the
deflated numbers and say so.

### E.3 Failure modes the design must guard against

| Failure mode | What it looks like here | Guard |
|---|---|---|
| **Model drift** | the fold's model becomes stale; E-1's own per-month trade count swings from 136 to 521 | a fold's model is valid **only** on `[asof, next_asof)`; assertion (1)/(2) enforces it; never reuse a fold's model outside its window |
| **Feature drift** | the feature code changes between the train window and the test window, or a feature starts using data after `ts_event` | `feature_list` **and its hash** stored in `meta_label_meta.json`; assertion (4) compares it to the backtest's; every feature builder is causal-by-construction (a unit test asserts `feature(t) == feature(t)` when the input array is truncated at `t`) |
| **Regime change** | D4's sign flips across the fill arm in *every* parameter group; E-1's per-month results are unstable | report the per-fold metrics **segmented by VXN regime and by year**; a claimed improvement must hold in ≥ K of M regime buckets, else label it noise; re-run the whole rolling pipeline per regime bucket rather than per year |
| **Baseline ≈ 0** | any "improvement" is measured against zero, when the truth is that the baseline is **−0.070 R net** | **every** ML/RL result is a **paired** comparison against the *same candidate log*, the *same costs* and the *same one-position-at-a-time accounting* as D4; report `ΔE[R]` per fold with a **block bootstrap by fold** (trades inside a fold are correlated, so a per-trade bootstrap is invalid); the CI of `ΔE[R]` must exclude 0 **and** the deflated significance must survive |
| **Selection on the test** | the folds are tried until one looks good | every fold is reported, including the bad ones; the trial registry (§E.2c) counts all attempts; the headline number is the **stitched OOS curve**, not the best fold |
| **Correlated-position illusion** | D4's trap: 423,759 overlapping positions read as 423,759 independent bets | the backtest holds **one position at a time**, always; the census arm may be reported as a *frequency* statistic only, and its t-statistic is never quoted |
| **Cost blindness** | D9: the measured gross edge (≤0.052 R) is smaller than the round trip at any stop distance ≥ $100 | every report states the **break-even round-trip cost in R** alongside the expectancy, and the full 0/1/2-tick sweep |

---

## F. Resource verdict

| Capability | Available? | Measured evidence | What it would take |
|---|---|---|---|
| **Local CPU training (LightGBM)** | ✅ **Yes** | 1.24 s/fold at n=32,411 (1 thread); **39 folds over 3.9 y of real data = 55.6 s end-to-end** including parquet I/O and D3 artefact writes; model 687 KiB–1.0 MiB | `pip install --break-system-packages lightgbm` into `$PY` (**≈44 MB**, pulls scipy+narwhals) — `uv pip` refuses the uv-managed interpreter |
| **Local GPU training (torch / ultralytics)** | ❌ **No** | `nvidia-smi` absent; only AMD Radeon iGPU (`03:00.0 Lucienne`); `/opt/rocm` absent; **14 GiB RAM with 12 GiB already used** | **Impossible.** CPU inference only: torch CPU 184 MB wheel + ultralytics ≈0.9 GB download; **29–145 h** for the candidate population — use Kaggle T4 instead |
| **Kaggle CPU kernel** | ✅ **Yes** | CLI 2.2.5 authenticates (account `opclown1`); ≥100 private kernels, many `COMPLETE`; `kaggle quota` works | ~1–2 min/fold + ~29 min to pull 39 folds' artefacts back at 130 kB/s. **CPU quota is not reported by the CLI** — a human must read https://www.kaggle.com/settings/account |
| **Kaggle GPU kernel** | ✅ **Yes** | `kaggle quota` → **GPU 30.00 h total, 0.00 h used, refresh 2026-11-28**; two account kernels have `enable_gpu: true` / `machine_shape: Gpu` and status `COMPLETE`; `kaggle kernels push --accelerator NvidiaTeslaT4` | Only for the **vision** layer (41–75 GPU-h for the full candidate population → 2–3 weeks of quota, or a subset). **Do not spend GPU quota on LightGBM** — it is a 1.2 s CPU job |
| **Kaggle Datasets hosting of the lake** | ⚠️ **Partial** | scratch datasets created OK (1 MB + 58 MB, both private); account already hosts a 115 MB dataset; **upload = 15.7 KB/s**, download = 120–155 kB/s | Push **only** the D2 candidate log + feature table per symbol as **Parquet** (5–10 MB → 11 min) in a **Dataset**, not per fold. Whole-lake push = 18 h per GB — not worth it; the NFS lake is already local |
| **Local rolling backtest** | ✅ **Yes** | the full 6/1/1 pipeline (39 folds, real data, D3 artefacts on disk) = **55.6 s**; one engine pass over 2,046,240 bars = 3.5–14 s | The five assertions of §D.5; the paired ΔE[R] block bootstrap; the DSR. This is where the honesty lives — it must stay local and causal |
| **Local RL training** | ⚠️ **Probably, but gated** | torch/gymnasium/SB3 all absent; gymnasium 0.5 MB + SB3 0.2 MB + torch CPU 184 MB; state is 4–5 dims, action grid small → minutes/episode is plausible | install torch CPU + SB3; **but D4 says there is no edge to manage** — sequence this after the signal question, not before |

---

## Appendix — commands run (reproduction)

```bash
# machine
lscpu; nproc; free -h; swapon --show; df -h -x tmpfs -x devtmpfs
which nvidia-smi; lspci | grep -iE "vga|3d|nvidia|amd"; ls /opt/rocm
# bandwidth
curl -o /dev/null -w "%{size_download} %{time_total} %{speed_download}\n" \
     "https://speed.cloudflare.com/__down?bytes=10000000"
python3 -c "…snapshot /proc/net/dev, sleep 15, diff…"      # wlan0 294.6 KB/s
# interpreters / packages
for p in /usr/bin/python3 $PY; do $p -V; done
$PY -c "import importlib.util as u; [print(m, bool(u.find_spec(m))) for m in \
  ('nautilus_trader','pandas','polars','duckdb','pyarrow','numpy','lightgbm','sklearn',\
   'torch','ultralytics','mplfinance','pytest','scipy')]"
uv pip install --dry-run --python $PY lightgbm        # externally-managed error
$PY -m pip install --dry-run --break-system-packages lightgbm   # resolves
# kaggle
kaggle --version; kaggle config view; kaggle quota
kaggle kernels list --mine; kaggle datasets list --mine; kaggle competitions list
kaggle kernels pull opclown1/eth-ai-alphaevolve-wf-fold-8-trainer --metadata   # enable_gpu: false
kaggle kernels pull opclown1/kronos-ashare-finetune --metadata                 # enable_gpu: true, Gpu
kaggle datasets create -p /tmp/kag_up        # 1 MB scratch  -> 65.2 s
kaggle datasets create -p /tmp/kag_up58      # 58 MB scratch -> UPLOAD58_RESULT
# local training (throwaway venv only)
uv venv --python 3.11 /tmp/l5venv
uv pip install --python /tmp/l5venv/bin/python lightgbm numpy pandas pyarrow scikit-learn
/tmp/l5venv/bin/python /tmp/l5_lgbm_bench2.py    # thread-scaling table
/tmp/l5venv/bin/python /tmp/l5_rolling_sim.py    # 39-fold end-to-end -> 55.6 s
```

Scratch files created by this leaf (all under `/tmp`, none in the repo):
`/tmp/l5venv`, `/tmp/l5_candidate_counts.py`, `/tmp/l5_diag.py`, `/tmp/l5_lgbm_bench.py`,
`/tmp/l5_lgbm_bench2.py`, `/tmp/l5_rolling_sim.py`, `/tmp/l5_trade_counts.py`,
`/tmp/l5_artifacts/`, `/tmp/kag_up`, `/tmp/kag_up58`, `/tmp/kag_kernel_probe/`.

**Scratch objects created on the Kaggle account** (private, for the probe; they are not part of the
project): `opclown1/l5-env-scratch-1mb`, `opclown1/l5-env-scratch-58mb`, and the kernel
`opclown1/l5-env-probe`. No credential value was written into any file by this leaf.
