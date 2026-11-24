#!/usr/bin/env bash
# Copy every finished drift job to DEST/<repository>/<run id>/ with the run's metadata from the GitHub API (run.json);
# a run already copied at its latest attempt is skipped. Then mirror DEST to COPY. Run from the gate's repository:
#   study/fetch-drift.sh [DEST] [COPY]
set -eu
DEST=${1:-data/runs/drift}
COPY=${2:-../notes/runs/drift}
for repo in workbench-support receipt-intake telecom-support; do
  gh run list -R "Ilya-Grigoryev/$repo" --workflow drift.yml --status completed --limit 300 \
    --json databaseId,attempt -q '.[] | "\(.databaseId) \(.attempt)"' |
  while read -r id attempt; do
    dir="$DEST/$repo/$id"
    [ "$(cat "$dir/.attempt" 2>/dev/null)" = "$attempt" ] && continue
    mkdir -p "$dir"
    gh api "repos/Ilya-Grigoryev/$repo/actions/runs/$id" > "$dir/run.json"
    if gh run download "$id" -R "Ilya-Grigoryev/$repo" -D "$dir" 2>/dev/null; then
      echo "$attempt" > "$dir/.attempt"  # only on success: a failed copy is tried again next time
    else
      echo "not copied, try again: $repo $id"
    fi
  done
done
mkdir -p "$COPY" && rsync -a "$DEST/" "$COPY/"
