#!/usr/bin/env bash
# Clone the third-party components this harness integrates alongside the
# Python control-plane. These repos are NOT vendored into this repository;
# see CREDITS.md for provenance and licenses.
#
# Usage: ./scripts/fetch_components.sh [target-dir]   (default: repo root)
set -euo pipefail

TARGET="${1:-$(cd "$(dirname "$0")/.." && pwd)}"

declare -A COMPONENTS=(
  [Agent-Reach]="https://github.com/Panniantong/agent-reach"
  [Awesome-Redteam]="https://github.com/Threekiii/Awesome-Redteam"
  [CL4R1T4S]="https://github.com/elder-plinius/CL4R1T4S"
  [T3MP3ST]="https://github.com/elder-plinius/T3MP3ST"
  [adhd]="https://github.com/UditAkhourii/adhd"
  [claude-bug-bounty]="https://github.com/shuvonsec/claude-bug-bounty"
  [jsleak]="https://github.com/channyein1337/jsleak"
  [mempalace]="https://github.com/MemPalace/mempalace"
)

for name in "${!COMPONENTS[@]}"; do
  url="${COMPONENTS[$name]}"
  if [ -d "$TARGET/$name" ]; then
    echo "skip  $name (already present)"
  else
    echo "clone $name <- $url"
    git clone --depth 1 "$url" "$TARGET/$name"
  fi
done

echo
echo "NOTE: the harness design spec applies TWEAK/MODIFIED changes to several"
echo "of these components (see bug_bounty_harness_design_v2_1.md). Fresh clones"
echo "are stock upstream; re-apply the local modifications before wiring them in."
