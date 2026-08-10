#!/usr/bin/env bash
# Re-apply local-only patches after merging upstream/main.
# Usage: bash local/apply-patches.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

shopt -s nullglob
patches=(local/patches/*.patch)
if ((${#patches[@]} == 0)); then
  echo "No patches in local/patches/"
  exit 0
fi

for patch in "${patches[@]}"; do
  echo "Applying ${patch}..."
  if git apply --check "${patch}"; then
    git apply "${patch}"
    echo "  ok"
  elif git apply --reverse --check "${patch}" >/dev/null 2>&1; then
    echo "  already applied, skip"
  else
    echo "  FAILED: resolve conflict then refresh ${patch}" >&2
    exit 1
  fi
done
