# Job: Download the referenced Hugging Face models and datasets locally

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. Greenfield quant research repo for the DodgysDD "Inversion Fair
Value Gap" (iFVG) strategy. We are pulling the Hugging Face artifacts cited in `iFVG几个模型的讨论.txt` so a
fleet of agents can study them offline.

Referenced HF artifacts:
1. `ibtsam/nq-fvg-detector` — **model**: YOLOv26m-based detector for FVG boxes on Nasdaq (NQ) charts.
   The design doc wants this fine-tuned/used as the vision cross-validation layer (module 1 of the four-layer
   system): render 60 indicator-free candles to 224x224, detect FVG boxes, compute IoU against the
   rule-engine FVG price zone, gate on IoU > 0.75.
2. `nerds-gaming/xauusd-ml-trader` — **model repo**: complete Python quant framework with liquidity-sweep
   detection, FVG imbalance detection, session (Asian/London/US) filtering and risk management. The doc says
   its code structure is easy to rewrite toward "FVG broken by body -> inverted entry" (the iFVG logic).
3. `mandiyaaman/ict-6000-mentorship-master` — **dataset**: structured ICT trading-rule reasoning dataset
   (liquidity sweeps, killzones, order-flow logic), intended for fine-tuning a trading assistant LLM.

Note: `ibtsam/nq-fvg-detector` returned HTTP 401 on the models API earlier but the repo resolves via the
website; `mandiyaaman/ict-6000-mentorship-master` is a **dataset** (401 on models API, 200 on datasets API).
Handle both accordingly — do not treat a 401 on the wrong endpoint as a failure.

## Your task
Download all three into `research/huggingface/`:
- `research/huggingface/nq-fvg-detector/`
- `research/huggingface/xauusd-ml-trader/`
- `research/huggingface/ict-6000-mentorship-master/`

## How
- Token: `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`. The `hf` CLI is at `/home/da/.local/bin/hf`.
  Use `HF_TOKEN=<token> hf download <repo_id> --local-dir <dir>`.
- Use `--exclude` only if a file is clearly irrelevant AND huge; prefer complete downloads for the detector
  (weights are essential). Log every file with its size.
- The `ict-6000-mentorship-master` dataset may be large (6000 rows of reasoning). Check size first via the
  datasets API; if it exceeds ~2 GB, download only the first few parquet/json shards plus metadata and say so.
- Do NOT put the token in any file under the project.

## Acceptance — write findings to `research/huggingface/DL_REPORT.md`
For EACH artifact report:
- Repo id, type (model/dataset), license (from the card), gated? (yes/no), last-modified
- Full file listing with sizes, and total bytes on disk
- For the detector: the model architecture (detected from the config/weights file), the class names, the input
  resolution, the number of parameters if derivable, the training data description from the card, and the
  **exact chart style it was trained on** (background color, whether indicators are drawn, aspect). This is
  critical: the design doc calls for a BLACK-background 224x224 render, and a model trained on
  white-background TradingView charts would silently misfire. Quote the card text that supports your answer.
- For `xauusd-ml-trader`: the file/module tree, what each module does, which framework it uses, how it
  defines liquidity sweep / FVG / session filters / risk management, and how the entry logic is structured
  (it should be order-block based — say exactly how to convert it to FVG-inversion entry)
- For the ICT dataset: schema/columns, row count, and 2–3 representative sample rows (verbatim, truncated)
  showing how a rule is expressed
- Any contradiction between the artifact and the design doc, stated plainly

## Constraints
- Write ONLY inside `research/huggingface/` (plus this report file).
- Do NOT run the downloaded code. Do NOT `pip install` anything. Do NOT load the YOLO weights (torch/ultralytics
  are not installed for the relevant interpreter). Inspect config/weights files statically instead
  (`unzip -l` on a `.pt` if it is a zip archive, read yaml/json/toml).
- If a download partially fails, retry once with the token in `HF_TOKEN`, then report precisely.

## Surprises
Deliverable: `research/huggingface/DL_REPORT.md`. Report env surprises (missing deps, gated repo, license
conflict, size) in your final message for the captain's field guide.

## Field guide (read before you start)
Read `.field-guide/env.md` and `.field-guide/sources.md` in the project root for environment quirks and
the exact re-fetch procedure for external artifacts. Do not edit the guide.
