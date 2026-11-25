# Environment facts

## 2026-11-22 — Python interpreter for this project is uv-managed 3.11, NOT the system python
`nautilus_trader` 1.221.0 requires `>=3.11,<3.14`. The system interpreter is `/usr/bin/python3` = **3.14.8**
and `import nautilus_trader` fails there. The interpreter that owns the installed package is:
`/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11`
(`nautilus_trader` lives in `/home/da/.local/lib/python3.11/site-packages/`, alongside pandas 2.3.3,
numpy 2.4.6, pyarrow 26.0.0, msgspec 0.22.0, fsspec 2025.12.0).

## 2026-11-22 — no conda on this host
The design discussion's `conda create -n nautilus_ifvg python=3.11` recipe cannot run: no `conda` binary,
no `~/miniconda3`, no `~/.conda`. Use `uv` instead (`/home/da/.local/bin/uv`, `uv venv --python 3.11`).

## 2026-11-22 — missing research dependencies
Not installed for the 3.11 interpreter: `databento`, `yfinance`, `mplfinance`, `ultralytics`, `lightgbm`,
`scikit-learn`, `pytest`. Installed for system python3.14: `pytest` (9.2.0) — unusable with the NT stack.

## 2026-11-22 — only three worker CLIs are installed
`herdr-dispatch doctor` lists 25 kinds, but the binaries that actually exist on PATH are `pi` (1.6.0),
`omp`, and `opencode` (v2.1.4). `codex`, `claude`, `cursor-agent`, `grok` are NOT on PATH — dispatching
those kinds fails with `binary not on PATH`. `herd-dispatch models --kind pi` works and lists four ids:
`minimax-cn/MiniMax-M2.7`, `minimax-cn/MiniMax-M2.7-highspeed`, `minimax-cn/MiniMax-M3`,
`minimax-cn/MiniMax-M3.1-Flash`. `models --kind omp` and `--kind opencode` return
`no model catalog probe for kind` — pass native flags via `--args` instead of `--model` for those.

## 2026-11-22 — nautilus_trader 1.221.0 ships no console script and no YAML support
There is no `nautilus` entry point in the wheel. The only entry points are
`python -m nautilus_trader.backtest --raw <json>` and `python -m nautilus_trader.live --raw <json>`.
Config decoding is msgspec JSON (`msgspec.json.decode(..., type=list[BacktestRunConfig])`); grepping the
package for `yaml`/`safe_load` returns nothing. Do not introduce YAML configs.

## 2026-11-22 — project root is not a git repository
`git status` in `/home/da/桌面/DodgysDD_ifvg` fails with `fatal: not a git repository`. Herdr `--worktree`
dispatch therefore has nothing to branch from until `git init` is run.

## 2026-11-22 — MiniMax token plan quota is exhausted under parallel worker load
Running 5 concurrent `pi` workers produced HTTP 429 `已达到 Token Plan 用量上限` (request_id prefix
`0751b5...`) in every pane. `pi` retried 3x and gave up. Keep **at most 2 workers** running at once on this
account, and prefer `omp` (M3.1-Flash) for cheap mechanical work.

## 2026-11-22 — GitHub clone needs the token in the URL, not `http.extraheader`
`git -c http.extraheader="Authorization: Bearer <tok>" clone` fails with
`fatal: could not read Username for 'https://github.com': terminal prompts disabled` (askpass is `/usr/bin/false`).
Working form: `GIT_TERMINAL_PROMPT=0 git clone --depth 1 "https://x-access-token:<tok>@github.com/<owner>/<repo>" <dir>`.
Note the token ends up in `.git/config` — strip it afterwards (`git remote set-url origin https://github.com/...`).

## 2026-11-22 — the Hugging Face token in the notes is EXPIRED
`$HUGGINGFACE_TOKEN` belongs to user `opclown1` and returns
`{"error":"User Access Token \"opclown1\" is expired"}` from `/api/whoami-v2`. The stale token is cached at
`~/.cache/huggingface/token` and silently breaks even **unauthenticated** downloads (the CLI sends it and the
server answers 401/404, so `hf download` reports "Model not found"). Fix: `mv ~/.cache/huggingface/token
~/.cache/huggingface/token.expired.bak`, then download anonymously — all three of our repos are public.

## 2026-11-22 — verified NautilusTrader 1.221.0 API facts (do not re-derive)
Full map: `research/nautilus/NAUTILUS_API.md`. The load-bearing corrections:
- **`BarSpecification` / `BarType` are NOT an old API.** `BarSpecification(1, BarAggregation.MINUTE,
  PriceType.LAST)` and `BarType(inst_id, spec)` work as the design doc writes them. `Price.from_str` and
  `Quantity.from_int` also work. The doc's sample is wrong for other reasons, not these.
- **`BarType` strings carry an `-EXTERNAL` suffix**: `NQ.XCME-1-MINUTE-LAST-EXTERNAL`. Parsing
  `'NQ.XCME-1-MINUTE-LAST'` raises `ValueError: ... invalid token: '' at position 0`.
- **There is no `Future` class.** `nautilus_trader.model.instruments` exports only `CryptoFuture`,
  `FuturesContract`, `FuturesSpread`. Use `FuturesContract`; its `activation_ns`/`expiration_ns` are
  mandatory uint64, so continuous-contract handling needs a decision.
- **`@customdataclass` lives in `nautilus_trader.model.custom`** — NOT `nautilus_trader.model.custom_data`
  (that module does not exist). `Data` exposes only `ts_event`, `ts_init`, `fully_qualified_name`,
  `is_signal`.
- **`ParquetDataCatalog` has no `write_bars`** — the only write verb is
  `write_data(data, start=None, end=None, skip_disjoint_check=False)`, and it **overwrites** existing
  data for the same class/instrument.

## 2026-11-22 — herdr server crashed once mid-fleet, but panes and worker sessions survived
The `herdr` process restarted; `herd-dispatch doctor` returned `ok: true` again and the worker panes
(`wE:p9`, `wE:pA`) came back **idle with their conversation context intact**. `herd-dispatch send --name
<job> --message "<resume instruction>"` revived them where they left off. Lesson: write the deliverable
file early and re-check `research/analysis/` after any crash rather than re-dispatching from scratch.

## 2026-11-22 — `herd-dispatch stop` does NOT clear the job record
`stop --name <job> --yes` closes the pane but leaves the entry in `.herd-dispatch/index.json` with its
last `status` (often `working`). `collect` on a stopped job refuses with
`{"ok": false, "error": "no live agent named <job>"}` and also leaves the record. There is **no verb**
that forgets a job, so a finished wave leaves phantom "working" entries that would make the next
captain believe the fleet is busy. Prune `index.json`'s `jobs` map directly (keep a `.bak`), dropping
every entry whose `pane_id` is no longer in `herdr agent list`. The `layouts` key is separate and
should be left alone — it records tab ownership for pane reuse.

## 2026-11-22 — the canonical lake is NFS, not SMB, and it is mountable
The lake's own `db_loader.py` documents its location as
`nfs://fnos2.local/fs/1000/nfs/iflow/database`, and **`fnos2.local` resolves to 192.168.1.6** — the
same NAS as the SMB share, but the **NFS export is world-accessible** (`showmount -e fnos2.local` ->
`/fs/1000/nfs *`). The SMB path rejects every credential; the NFS path needs none.
Mount it (needs sudo; `mount.nfs` fails with "failed to apply fstab options" when unprivileged):
```bash
sudo mount -t nfs -o rw,vers=3,proto=tcp fnos2.local:/fs/1000/nfs ~/iflow_lake
```
`/home/da/桌面/database/` is only a **working checkout** of the same repo; the authoritative data is on
the NFS mount. **Publish new governed partitions to the NFS mount, not just the local checkout.**
`nfs-cp` works directly and is fast (~58 MB in ~1 s): `nfs-cp nfs://fnos2.local/fs/1000/nfs/iflow/database/<rel> <dst>`.

## 2026-11-22 — the lake's db_loader path convention was stale and resolved NOTHING
`03_governed_lake/v2_parquet_lake/tools/db_loader.py` looked for `<db_root>/<asset>/<tf>/<SYM>_<tf>*.parquet`,
but the lake root has no top-level `crypto/`, `us_equities/`, `us_futures/` — the data lives under
`03_governed_lake/v2_parquet_lake/`. **Every** asset failed with `FileNotFoundError`. Fixed by trying
the `03_governed_lake/v2_parquet_lake/` prefix as well (old paths kept first, so nothing regresses);
the fix is published to both the local checkout and the NFS mount. Verified after the fix:
BTCUSDT 1m 2,046,240 rows / ETHUSDT 1m 2,046,240 / QQQ 15m 73,325 / NQ 1m 7,490 all load from the NAS.
`polars` and `duckdb` are required by the loader and were **missing** for the 3.11 interpreter
(PEP 668 blocks plain `pip install`; use `--break-system-packages`).

## 2026-11-22 — confirmed on the NFS lake: NQ/ES 1m really is one week
`.../v2_parquet_lake/us_futures/{NQ,ES}/1m/*.parquet` on the **NFS** mount: NQ **7,490** rows,
ES **7,489** rows, both **2026-09-24 -> 2026-10-01**. This is the authoritative copy and it agrees with
the local checkout. The `v2_parquet_lake/manifest` claim of `1m/5m/15m/1h/2h/4h/1d` for NQ/ES is
**aspirational**; only `1m` (1 week) and `1h`/`1d` (multi-year) actually exist.

## 2026-11-22 — Kaggle GPU quota verified independently (30 h/week, unused)
`kaggle quota` (account `opclown1`) returns:
```
resource  used   remaining  total   refreshAt
GPU       0.00h  30.00h     30.00h  2026-11-28T00:00:00+00:00
TPU       0.00h  20.00h     20.00h  2026-11-28T00:00:00+00:00
```
So a Kaggle T4 GPU **is** available and **none** of the quota is spent. But the measured cost model
(L5) says LightGBM needs **1.24 s/fold** on CPU and the whole 39-fold walk-forward is **55.6 s** locally —
so **do not spend GPU quota on the meta-labeler**. Reserve it for the vision detector, whose CPU-only
inference is 29–145 h for the candidate population.
`kaggle datasets list --mine` intermittently fails with
`SSLEOFError: [SSL: UNEXPECTED_EOF_WHILE_READING]` — the same TLS flakiness that breaks every other
transfer on this host; retry rather than treating it as an auth failure.

## 2026-11-23 — pushing to GitHub from this host needs the REST API, and workflows are impossible
Three separate blockers, each measured:
1. `git push` POSTs fail (`send-pack: unexpected disconnect`, `Empty reply from server`) while the
   **GET** side works — the egress drops long-lived connections on the packfile upload.
2. **Eight concurrent HTTPS POSTs all fail** (000) while a single POST succeeds in ~5 s. The host cannot
   sustain parallel TLS connections, so the blob upload must be **strictly sequential**
   (80 files ≈ 7 min).
3. The project token carries **`repo` scope only**. GitHub refuses any tree entry under
   `.github/workflows/` — from `git push` *and* from `POST /git/trees` (404 "Not Found"). The symptom
   looks like a bad payload; it is a scope refusal. Keep workflow files untracked until a token with
   the `workflow` scope exists.
Working path: `scripts/sync_via_api.sh` -> `scripts/push_via_api.py` (blobs -> tree -> commit ->
ref), then `git fetch origin && git reset --hard origin/main` so local and remote converge on the
same commit.

## 2026-11-24 — two writers on the NFS lake leave partitions unreadable, for root too
The fnOS NFS export (`vers=3`, `~/iflow_lake`) does not tolerate two processes renaming files into the
same directory tree. Running a second puller while the first was still writing produced a batch of
partitions that answer **EACCES on read for every client, `sudo` included**, while `stat` shows mode
`0777` and `os.replace` had already returned success:
```
head: cannot open '.../funding_rate/BTCUSDT/BTCUSDT_funding_rate.parquet' for reading: Permission denied
```
It is not a mode/ACL problem (`getfacl` shows `other::rwx`, a fresh file in the same directory reads
fine) and it is not a client cache: root hits the same error. The file is unrecoverable in place — the
only fix is to **delete and rewrite** it.
Measured consequences: 16 partitions from one concurrent pull batch, including both funding files and
half of the resampled timeframes.
Mitigation now in the code (`data_pipeline/pull_exchange.write_governed`):
* an **exclusive `flock` per target partition** (`.lock` beside the parquet);
* a **read-back of the Parquet metadata after the rename**, retried with a fresh inode;
* the writer raises rather than publishing a file it cannot read back.
Operational rule: **one writer per lake tree at a time.**
