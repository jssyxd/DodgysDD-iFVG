# Leaf L5 — Environment & resources: can this box train models, and can Kaggle be used?

## Context
Project: `/home/da/桌面/DodgysDD_ifvg`. The user asks whether the current environment and the Kaggle
credentials can be used to train models and to run *rolling* training on Kaggle, plus *local* rolling
backtests.

**Read-only audit leaf.** Own exactly one file: `research/audit/L5_ENV.md`.
You may write scratch files under `/tmp` only.

## Required reading
- `.herd-swarm/decisions.md` — **D4** (the honest baseline), **D5** (data reality), **D9** (costs).
- `research/analysis/DATA_ACQUISITION.md` — what data exists and where.
- `research/nautilus/NAUTILUS_API.md` — the verified engine API.
- `research/experiments/E1_RESULTS.md` — the falsification result the ML must beat.

## Your task → `research/audit/L5_ENV.md`

### A. Machine inventory — measured, not assumed
Probe and report the **actual** state of this host:
- CPU: model, core count, RAM, free disk per filesystem (`df -h`), and the measured current bandwidth
  (the captain measured ~69 KB/s earlier under load — re-measure and state the method).
- GPU: `nvidia-smi` present? CUDA version? VRAM? Is it usable by the 3.11 interpreter?
- Python interpreters on the box: list every `python3*` and its version, and which one owns
  `nautilus_trader`, `pandas`, `polars`, `duckdb`, `pyarrow`, `numpy`, `lightgbm`, `sklearn`, `torch`,
  `ultralytics`, `mplfinance`, `pytest`. Use the project interpreter
  `/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11` as the reference.
  State exactly what is **missing** and the cost to add it (note PEP 668 → `--break-system-packages`,
  or a `uv venv`).
- Package managers available: `uv`, `pip`, `conda` (absent), `poetry`.

### B. Kaggle capability — probe it for real
Credentials: `KAGGLE_USERNAME` / `KAGGLE_KEY` are in `一些必备apikey和环境.txt` (read it; **never** write
the key into any file you create).
- `kaggle kernels list`, `kaggle datasets list`, `kaggle competitions list` — does the CLI work, and is
  the account in good standing?
- **Is Kaggle GPU actually available?** Determine what the account can do: check
  `kaggle kernels list --mine` for existing kernels, and check whether the account has GPU quota. If the
  CLI cannot report GPU quota, say so and give the exact URL/dashboard a human must open.
- Measure the **upload bandwidth** for the Kaggle API (upload a small file to a scratch dataset and time
  it), because the lake's 58 MB parquet per symbol is the unit of transfer.
- **Can we push the governed lake to Kaggle Datasets?** Check the dataset-size limit and whether the
  Parquet layout survives the round trip. State the practical plan.

### C. Can the model training actually run here?
- **LightGBM** (the doc's meta-labeler): not installed. Assess CPU training feasibility for the real
  problem size (how many candidates? 423,759 census / ~16 k one-at-a-time trades per fold), and give a
  measured estimate — install it if you can (into a **throwaway venv** under `/tmp`, NOT the project
  interpreter, to avoid disturbing the environment), train a trivial model on synthetic data of the right
  shape, and report the wall-clock.
- **ultralytics / torch** (the vision detector): can the 44 MB `best.pt` be loaded and run? If torch is
  absent, report the install size and whether the box has GPU headroom. Do **not** download a full
  CUDA stack if it would fill the disk — report the estimate instead.
- **Gymnasium / SB3 / torch** for the RL layer: not installed. Assess.

### D. The rolling-training design (what "Kaggle 滚动训练" would mean)
This is the user's explicit question. Specify it concretely:
- The **walk-forward** schedule that the doc demands (6 months train / 1 month validate / 1 month test,
  rolling monthly) and how it maps onto Kaggle **Kernels** (one kernel per fold? one kernel that loops?
  what is the wall-clock per fold and the total?).
- What must be **uploaded** per fold (the candidate log, the feature table) and what comes back (the
  model artefact — but see D3: the artefact contract is frozen, so a Kaggle kernel must emit exactly
  `meta_label_lgbm.txt` + `meta_label_meta.json` into `artifacts/models/{symbol}/{asof}/`).
- How the **local** rolling backtest consumes those artefacts in order (a fold's model may only decide
  trades with `ts_event > fold.asof`) — the exact assertion the backtest must make.
- The **schedule**: how long does a full 6/1/1 rolling year take end-to-end, locally and on Kaggle?
- The **cost**: Kaggle GPU quota is 30 h/week (verify or state the assumption), so how many folds fit?
- An explicit statement of what a Kaggle kernel does **not** solve: it does not remove the need for a
  causal backtest, and it must never see the test fold.

### E. The end-to-end model, and dynamic backtesting
The user asks for an "e2e 模型" and for "根据动态的训练情况动态的回测". Specify:
- The end-to-end pipeline as a concrete pipeline of stages with the artefact produced by each stage and
  the gate that must pass between them (rule engine → features → meta-label → RL → paper trade).
- What "**dynamic backtesting**" can honestly mean, given D4: the honest version is a
  **walk-forward simulation** where each period is decided by the model that was live at that time, and
  the report shows the *degradation* of the model over time (the training curve becomes part of the
  strategy). Give the concrete implementation (per-fold metrics table, equity curve stitched from folds,
  and the **deflated Sharpe** / multiple-testing correction for the many arms already tried).
- The **failure modes** this design must guard against: model drift, feature drift, regime change,
  and the fact that the current baseline expectancy is ~0 (so any "improvement" must be tested against
  that, not against zero).

### F. Resource verdict
A table: capability | available? | measured evidence | what it would take.
Rows: local CPU training (LightGBM), local GPU training (torch/ultralytics), Kaggle CPU kernel,
Kaggle GPU kernel, Kaggle Datasets hosting of the lake, local rolling backtest, local RL training.

## Constraints
- Write **only** `research/audit/L5_ENV.md` (create `research/audit/` if needed).
- Read-only elsewhere. Scratch work in `/tmp` only. **Do not** modify the project interpreter's
  site-packages, the NFS lake, or the project's own venv.
- If you install anything, install it into a `/tmp` virtualenv and say so.
- Never write a credential value into any file.
- `[FACT]` / `[INFERENCE]` / `[PROPOSAL]`, with commands and measured outputs.

## Deliverable
`research/audit/L5_ENV.md`. Final reply: the capability table in one line each, plus the honest answer to
"can we train on Kaggle and roll locally".
