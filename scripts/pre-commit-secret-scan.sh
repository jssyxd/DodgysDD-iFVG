#!/usr/bin/env bash
# Pre-commit guard: block credentials from ever entering the repository.
#
# Installed via .git/hooks/pre-commit (not tracked). The hook scans the *staged*
# content only, so it is fast and it cannot be bypassed by staging a subset.
#
# Patterns cover the credential families actually used in this project:
# GitHub PATs, Hugging Face tokens, Kaggle keys, cryptohftdata keys, plus the
# generic "high-entropy secret-ish" shapes that show up in pasted notes.
set -uo pipefail

fail=0

# Files that are allowed to contain the *names* of secrets but never their values.
ALLOW='^\.env\.example$|^\.field-guide/.*\.md$'

staged=$(git diff --cached --name-only --diff-filter=ACMR)
if [ -z "$staged" ]; then
    exit 0
fi

# 1) exact live-token shapes
PATTERNS='ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|hf_[A-Za-z0-9]{34}|KGAT_[A-Za-z0-9]{32}|sk-[A-Za-z0-9]{32}|xoxb-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

for f in $staged; do
    case "$f" in
        *.md) continue ;;   # markdown may quote a redacted example; the value patterns below still apply
    esac
    if git show ":$f" 2>/dev/null | grep -aEq "$PATTERNS"; then
        echo "BLOCKED: $f contains what looks like a live credential."
        fail=1
    fi
done

# 2) the specific tokens this project has used, in ANY file type.
#    The list lives OUTSIDE the repository (in .git/hooks/known_tokens.txt) so this
#    script never itself contains a credential and can be committed safely.
KNOWN_FILE="$(dirname "$0")/known_tokens.txt"
if [ -f "$KNOWN_FILE" ]; then
    KNOWN=$(paste -sd'|' "$KNOWN_FILE")
    if [ -n "$KNOWN" ]; then
        for f in $staged; do
            if git show ":$f" 2>/dev/null | grep -aEq "$KNOWN"; then
                echo "BLOCKED: $f contains a known live credential from the secrets notes."
                fail=1
            fi
        done
    fi
fi

# 3) the notes file itself must never be tracked
for f in $staged; do
    case "$f" in
        *apikey*|*API_KEY*|*环境.txt) echo "BLOCKED: $f looks like a secrets file."; fail=1 ;;
    esac
done

if [ "$fail" -ne 0 ]; then
    echo
    echo "Refusing the commit. Store credentials in .env (gitignored) and reference them by NAME."
    echo "See .env.example."
    exit 1
fi
exit 0
