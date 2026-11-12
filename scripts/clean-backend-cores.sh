#!/usr/bin/env bash
# clean-backend-cores.sh — one-shot cleanup + prevention for backend core dumps.
#
# Backend container was segfaulting in a Python multiprocessing worker and
# dropping ~830 MB ELF core files into ./backend/, ballooning the Docker
# build context to 129 GB. This script:
#
#   1. Deletes every core dump in ./backend/
#   2. Writes a backend/.dockerignore so future dumps never enter the build
#      context even if they do get written
#   3. Patches docker-compose.yml to set `ulimits.core: 0` on the backend
#      service so the kernel stops producing dumps in the first place
#   4. Reports what changed
#
# Idempotent — safe to run multiple times.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/fredu/docker-compose/bloomvalley}"
BACKEND_DIR="$REPO_DIR/backend"
COMPOSE_FILE="$REPO_DIR/docker-compose.yml"
DOCKERIGNORE="$BACKEND_DIR/.dockerignore"

if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "ERROR: $BACKEND_DIR not found. Set REPO_DIR= if the repo lives elsewhere." >&2
    exit 1
fi

# ── 1. Delete existing core dumps ──────────────────────────────────────────
echo "== Step 1: deleting existing core dumps =="
shopt -s nullglob
# Build the cores list from entries that actually exist. A bare "core" is a
# literal path, not a glob, so after a previous cleanup it would remain in
# the array as a dangling string and crash `du` under pipefail.
cores=()
[[ -f "$BACKEND_DIR/core" ]] && cores+=( "$BACKEND_DIR/core" )
for f in "$BACKEND_DIR"/core.*; do
    [[ -f "$f" ]] && cores+=( "$f" )
done
if [[ ${#cores[@]} -gt 0 ]]; then
    before_bytes=$(du -csb "${cores[@]}" 2>/dev/null | tail -1 | cut -f1 || echo 0)
    before_mb=$(( before_bytes / 1024 / 1024 ))
    echo "  found ${#cores[@]} dump(s), ${before_mb} MB total"
    rm -f "${cores[@]}"
    echo "  deleted"
else
    echo "  no core dumps found"
fi
shopt -u nullglob

# ── 2. Ensure backend/.dockerignore excludes dumps + caches ────────────────
echo "== Step 2: writing backend/.dockerignore =="
declare -A want=(
    [core]=1
    ["core.*"]=1
    ["*.pyc"]=1
    ["__pycache__/"]=1
    [".pytest_cache/"]=1
    [".mypy_cache/"]=1
    [".venv/"]=1
    ["venv/"]=1
)
touch "$DOCKERIGNORE"
added=()
for pat in "${!want[@]}"; do
    if ! grep -Fxq -- "$pat" "$DOCKERIGNORE"; then
        echo "$pat" >> "$DOCKERIGNORE"
        added+=( "$pat" )
    fi
done
if [[ ${#added[@]} -gt 0 ]]; then
    echo "  added entries: ${added[*]}"
else
    echo "  all entries already present"
fi

# ── 3. Patch docker-compose.yml to disable core dumps ──────────────────────
echo "== Step 3: ensuring backend has ulimits.core: 0 =="
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "  WARN: $COMPOSE_FILE not found, skipping"
else
    # Simple detection: does any ulimits block exist under backend service?
    # The service block is "  backend:" followed by its indented body up to
    # the next top-level service (two-space indent).
    if awk '
        /^  backend:$/      { in_backend = 1; next }
        in_backend && /^  [a-zA-Z]/ { in_backend = 0 }
        in_backend && /^    ulimits:/ { found = 1 }
        END { exit found ? 0 : 1 }
    ' "$COMPOSE_FILE"; then
        echo "  backend already has ulimits block — leaving alone"
    else
        # Insert ulimits.core: 0 right after "  backend:" line.
        # Timestamped backup so a mistake is easy to reverse.
        backup="$COMPOSE_FILE.bak.$(date +%Y%m%d-%H%M%S)"
        cp "$COMPOSE_FILE" "$backup"
        awk '
            /^  backend:$/ && !inserted {
                print
                print "    ulimits:"
                print "      core: 0"
                inserted = 1
                next
            }
            { print }
        ' "$backup" > "$COMPOSE_FILE"
        echo "  inserted 'ulimits: {core: 0}' under backend (backup at $backup)"
        echo "  apply with:  docker compose up -d --no-deps --force-recreate backend"
    fi
fi

# ── 4. Summary ──────────────────────────────────────────────────────────────
echo
echo "== Done =="
backend_size=$(du -sh "$BACKEND_DIR" 2>/dev/null | cut -f1)
echo "  backend/ size now: $backend_size"
echo "  next build context load should be seconds, not minutes"
