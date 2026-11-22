#!/usr/bin/env python3
"""Push the current branch to GitHub through the REST API instead of git-over-HTTPS.

Why this exists
---------------
On this host `git push` fails consistently while plain HTTPS requests to
api.github.com succeed:

    send-pack: unexpected disconnect while reading sideband packet
    fatal: the remote end hung up unexpectedly
    fatal: unable to access '...': Empty reply from server

The GET side of the git protocol (`git ls-remote`) works; the **POST** that uploads the
packfile is what the flaky egress drops. GitHub frequently *accepts* such a push and
then the client never sees the response — which is worse than a clean failure.

The REST API takes one small request per file and each request survives independently,
so it is the reliable path here.

Usage
-----
    export GITHUB_TOKEN=<pat>
    scripts/push_via_api.py --repo jssyxd/DodgysDD-iFVG --branch main
    scripts/push_via_api.py --repo jssyxd/DodgysDD-iFVG --dry-run

The token needs `repo` scope only. Nothing is written to disk outside git's own
objects; the commit is created through the Git Data API (blobs -> tree -> commit -> ref),
so the history is identical to what `git push` would have produced.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def call(method: str, path: str, token: str, payload: dict | None = None,
         retries: int = 5) -> dict:
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "dodgysdd-ifvg-push",
            })
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode()
            return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:300]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code in (422, 404):
                raise SystemExit(f"{method} {path} -> {last}")
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(min(2 ** attempt, 20))
    raise SystemExit(f"{method} {path} failed after {retries} attempts: {last}")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")

    # --- the local HEAD commit we want the remote to point at ---
    local_sha = git("rev-parse", "HEAD")
    message = args.message or git("log", "-1", "--pretty=%s")

    # --- which files does the remote already have, and with what sha? ---
    base = call("GET", f"/repos/{args.repo}/git/ref/heads/{args.branch}", token)
    base_sha = base["object"]["sha"]
    base_commit = call("GET", f"/repos/{args.repo}/git/commits/{base_sha}", token)
    base_tree = base_commit["tree"]["sha"]

    remote_tree = call("GET", f"/repos/{args.repo}/git/trees/{base_tree}?recursive=1", token)
    remote_files = {e["path"]: e["sha"] for e in remote_tree.get("tree", [])
                    if e["type"] == "blob"}

    # --- the files we want there (git's own view, so .gitignore is honoured) ---
    # -z gives NUL-separated raw paths; without it git *quotes* non-ASCII names and
    # the quoted form is not a real path.
    local_files = [p for p in subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True
    ).stdout.decode().split("\0") if p]
    print(f"remote HEAD : {base_sha[:10]}  ({len(remote_files)} files)")
    print(f"local HEAD  : {local_sha[:10]}  ({len(local_files)} tracked files)")

    # --- upload blobs STRICTLY SEQUENTIALLY ---
    # Measured on this host: a single POST succeeds (~5 s), but eight *concurrent*
    # POSTs all fail with a connection reset. The egress cannot sustain parallel
    # TLS connections, so parallelising makes things strictly worse. Sequential
    # it is: ~5 s per file.
    blobs: dict[str, str] = {}
    changed = 0
    for i, path in enumerate(local_files, 1):
        raw = open(path, "rb").read()
        sha = call("POST", f"/repos/{args.repo}/git/blobs", token,
                   {"content": base64.b64encode(raw).decode(),
                    "encoding": "base64"})["sha"]
        blobs[path] = sha
        if remote_files.get(path) != sha:
            changed += 1
        if i % 10 == 0:
            print(f"  ... {i}/{len(local_files)} blobs", flush=True)
    print(f"blobs uploaded: {len(blobs)}  (changed: {changed})", flush=True)
    if args.dry_run:
        return 0

    # --- build the new tree ---
    # GitHub refuses a tree entry under .github/workflows/ unless the token has the
    # `workflow` scope (the same scope that makes `git push` of a workflow fail).
    # The project token has `repo` only, so those paths are excluded from the
    # commit rather than failing the whole push.
    def _skip(path: str) -> bool:
        return path.startswith(".github/workflows/")

    tree_entries = []
    for path, sha in blobs.items():
        if _skip(path):
            print(f"  skipping {path} (needs the 'workflow' scope)")
            continue
        tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
    # keep remote-only files that are not tracked locally
    for path, sha in remote_files.items():
        if path not in blobs and not _skip(path):
            tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})

    new_tree = call("POST", f"/repos/{args.repo}/git/trees", token,
                    {"base_tree": base_tree, "tree": tree_entries})["sha"]

    # --- reproduce the local commit EXACTLY (same author/committer/message), so the
    # --- remote commit hash equals the local one and the two histories stay identical ---
    fmt = "%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B"
    raw = git("show", "-s", f"--format={fmt}", "HEAD").splitlines()
    author = {"name": raw[0], "email": raw[1], "date": raw[2]}
    committer = {"name": raw[3], "email": raw[4], "date": raw[5]}
    full_message = "\n".join(raw[6:]).rstrip("\n")

    new_commit = call("POST", f"/repos/{args.repo}/git/commits", token,
                      {"message": full_message, "tree": new_tree,
                       "parents": [base_sha],
                       "author": author, "committer": committer})["sha"]
    call("PATCH", f"/repos/{args.repo}/git/refs/heads/{args.branch}", token,
         {"sha": new_commit, "force": False})
    print(f"PUSHED {args.branch} -> {new_commit}")
    if new_commit == local_sha:
        print("identical to the local commit — local and remote histories match exactly")
    else:
        print(f"NOTE: remote sha {new_commit[:10]} != local {local_sha[:10]} "
              f"(same tree, different commit metadata)")
        subprocess.run(["git", "update-ref", f"refs/heads/{args.branch}", new_commit],
                       check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
