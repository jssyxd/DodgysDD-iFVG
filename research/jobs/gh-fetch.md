# Job: Clone all referenced GitHub repositories locally

## Context
Project root: `/home/da/桌面/DodgysDD_ifvg`. This is a greenfield quantitative-trading research repo for the
DodgysDD "Inversion Fair Value Gap" (iFVG) strategy on NautilusTrader. We are pulling every community
artifact referenced in the design discussion so a fleet of agents can study them offline.

The design discussion (`iFVG几个模型的讨论.txt`) references these GitHub projects:
1. `cantolab/IFVG-Ultimate-Dodgy` — open-source Pine Script v6 reimplementation of the closed-source
   "iFVG Ultimate+ | DodgysDD" TradingView indicator. THE most important artifact: it encodes the
   authoritative rule parameters (7–15 bar inversion window, A+..C scoring, SMT divergence, RR targets).
2. `imbue-bit/AlphaGPT` — symbolic-regression / Transformer factor mining (only a *reference*, see below).
3. `microsoft/qlib` — Microsoft AI quant platform (large; cross-sectional stock ranking; likely NOT a fit).
4. `Hyde1989/AlphaGPT-By-imbue-bit` — community mirror/backup of AlphaGPT.
5. `jssyxd/dataBaseLake` — the user's own data-lake repo that defines the strict audit/governance standard
   any newly downloaded backtest data must pass before being marked 可用 / 可入湖.

## Your task
Clone all five into `research/github/`, one directory each:
- `research/github/IFVG-Ultimate-Dodgy`
- `research/github/AlphaGPT`
- `research/github/qlib`
- `research/github/AlphaGPT-By-imbue-bit`
- `research/github/dataBaseLake`

## How
- Credentials: `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` (user `jssyxd`, repo-read only, expires 2027-02-18).
  Use `git -c http.extraheader="Authorization: Bearer <token>" clone --depth 1 <url> <dir>`
  if an anonymous clone is rate-limited or fails. Do NOT write the token into any tracked file.
- `microsoft/qlib` is large. If `--depth 1` still exceeds ~3 GB, clone it shallow WITHOUT submodules and
  note the size in your report. Do not attempt a full history clone.
- For `AlphaGPT` and `AlphaGPT-By-imbue-bit`, also record the default branch, HEAD commit sha, commit date,
  and license file presence.

## Acceptance — write your findings to `research/github/CLONE_REPORT.md`
For EACH of the five repos, report:
- HEAD sha, branch, date, size on disk, license (file + SPDX id if recognizable)
- Top-level directory tree (2 levels deep, directories and notable files only)
- Language breakdown (use `github-linguist`-style reasoning from file extensions; `cloc` may not be installed —
  approximate by counting extensions with `find`)
- README summary: 3–6 bullets on what the project actually is, its architecture, and its stated purpose
- For `IFVG-Ultimate-Dodgy`: list every file, its size, and quote the full Pine Script `input.*` parameter
  list with default values (this is the highest-value output of this job)
- For `dataBaseLake`: list the directory structure, any README/manifest/schema/audit files, and quote the
  rules that define 可用 / 可入湖 marking, file naming, and folder layout
- For `AlphaGPT` / `qlib`: state plainly whether each is a cross-sectional stock framework or usable as a
  single-contract event-driven factor engine (be concrete about what its core abstractions are)

## Constraints
- Write ONLY inside `research/github/`. Do not touch any other directory in the project.
- Do NOT modify, patch, or run any cloned repository's code. Read-only analysis only.
- Do NOT run `pip install`, `npm install`, or build steps in the clones.
- If a clone fails, retry once with the auth header, then report the failure precisely (command + error)
  and move on to the next repo.

## Surprises
Your deliverable is `research/github/CLONE_REPORT.md`. Also report any environment surprise (missing binary,
auth failure, huge repo, unexpected license) in your final message — that is what the captain transcribes
into `.field-guide/`.

## Field guide (read before you start)
Read `.field-guide/env.md` and `.field-guide/sources.md` in the project root for environment quirks and
the exact re-fetch procedure for external artifacts. Do not edit the guide.
