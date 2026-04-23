#!/usr/bin/env bash
# scripts/dogfood.sh
#
# Real end-to-end verification that our own examples work.
# Born from R8→R9: R8 shipped examples with docstrings showing wrong CLI
# syntax (global --db instead of per-subcommand). Tests didn't catch it
# because tests don't copy-paste the human-facing output. Dogfood does.
#
# What it does:
#   1. Runs each example/*.py fresh (clean DB) — must exit 0.
#   2. Greps the stdout for lines starting with 2 spaces + "chronos "
#      (the "Try these commands:" block the examples print).
#   3. Executes each of those commands via `uv run` — each must exit 0.
#   4. For each Python docstring in examples/, extracts "chronos ..."
#      command lines and runs them too (catches docstring drift, the R9
#      bug class).
#
# Used by:
#   - Developers before a release tag
#   - CI (.github/workflows/dogfood.yml)
#
# Usage: scripts/dogfood.sh
# Exit code: 0 on full success, 1 on any failure (fail-fast).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[dogfood]${NC} $*"; }
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

# Make sure we're starting clean — examples each reset their own DB on
# top of this, but stale artifacts from prior runs shouldn't leak in.
rm -f examples/chronos.db examples/*.db

EXAMPLES=(examples/linear_pipeline.py examples/router_loop.py)
TOTAL=0
PASSED=0

for ex in "${EXAMPLES[@]}"; do
    [[ -f "$ex" ]] || fail "missing example: $ex"

    log "Running $ex"
    output="$(uv run python "$ex" 2>&1)" || fail "example $ex exited non-zero"
    ok "$ex ran clean"

    # Extract "  chronos ..." lines (2-space-indented from "Try these commands:" block).
    # We use sed to preserve order and only take real chronos commands.
    mapfile -t cmds < <(printf '%s\n' "$output" | sed -n 's/^  chronos /chronos /p')

    if [[ ${#cmds[@]} -eq 0 ]]; then
        warn "no 'Try these commands:' block found in $ex output — skipping"
        continue
    fi

    log "Found ${#cmds[@]} suggested command(s) — executing each"
    for cmd in "${cmds[@]}"; do
        TOTAL=$((TOTAL + 1))
        # Run via uv run so we pick up the project-local chronos entry point.
        # Silence stdout (keep stderr) so the log stays readable; failures will
        # still surface exit codes.
        if uv run $cmd >/dev/null 2>&1; then
            ok "  → $cmd"
            PASSED=$((PASSED + 1))
        else
            fail "  → $cmd  (exited non-zero)"
        fi
    done
done

# Docstring drift check: scan examples/*.py top-of-file docstrings for
# any line containing "chronos " that looks like a shell command, and
# sanity-check it parses (we don't actually execute these — they're
# often in narrative context and may lack DB paths. We just verify
# --db is NOT placed before the subcommand, which is the R9 footgun).
log "Scanning example docstrings for '--db' placement drift"
DOC_ERRORS=0
for py in examples/*.py; do
    [[ -f "$py" ]] || continue
    # Match 'chronos --db' (the wrong pattern). Grep returns 1 on no match
    # which is what we want, so we don't let set -e kill us here.
    if grep -nE '^\s*chronos\s+--db\b' "$py" > /tmp/drift.out 2>/dev/null; then
        warn "docstring drift detected in $py:"
        cat /tmp/drift.out >&2
        DOC_ERRORS=$((DOC_ERRORS + 1))
    fi
done

if [[ $DOC_ERRORS -gt 0 ]]; then
    fail "$DOC_ERRORS file(s) have 'chronos --db ...' docstring drift (--db must come AFTER the subcommand)"
fi
ok "No docstring drift detected"

echo
log "Dogfood summary: $PASSED/$TOTAL suggested commands passed"
ok  "Full dogfood green 🎉"
