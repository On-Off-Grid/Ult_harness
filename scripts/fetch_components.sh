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
  # adhd is overridden by BRANCHES[adhd] below (fork + local-rename branch),
  # which carries the package rename + 6 security frames (Phase 4.5).
  [adhd]="https://github.com/UditAkhourii/adhd"
  # NOTE: claude-bug-bounty uses the On-Off-Grid FORK, not stock upstream.
  # The fork (b2e9eb7a) is 140 unique commits with no merge base to upstream —
  # it IS the customized component. See patches/local-tweaks.md §1.
  [claude-bug-bounty]="https://github.com/On-Off-Grid/claude-bug-bounty"
  [jsleak]="https://github.com/channyein1337/jsleak"
  [mempalace]="https://github.com/MemPalace/mempalace"
)

# Per-component branch override (default: upstream default branch).
# adhd pulls the On-Off-Grid fork's local-rename branch, which carries the
# package rename + the 6 security frames (Phase 4.5). See local-tweaks.md §2.
declare -A BRANCHES=(
  [adhd]="git@github.com:On-Off-Grid/adhd.git|local-rename"
)

for name in "${!COMPONENTS[@]}"; do
  url="${COMPONENTS[$name]}"
  if [ -d "$TARGET/$name" ]; then
    echo "skip  $name (already present)"
  else
    if [ -n "${BRANCHES[$name]:-}" ]; then
      # "remote|branch" — full clone (not depth 1) so the branch history is kept.
      br_remote="${BRANCHES[$name]%%|*}"
      br_branch="${BRANCHES[$name]#*|}"
      echo "clone $name <- $br_remote ($br_branch)"
      git clone --quiet --branch "$br_branch" "$br_remote" "$TARGET/$name"
    else
      echo "clone $name <- $url"
      git clone --depth 1 "$url" "$TARGET/$name"
    fi
  fi
done

echo
echo "NOTE: several components carry local modifications. The adhd fork branch"
echo "and the claude-bug-bounty fork are pulled automatically above. Any fresh"
echo "stock clones (jsleak go.mod shim, etc.) still need patches/local-tweaks.md"
echo "re-applied before wiring in. See patches/local-tweaks.md for the full list."
