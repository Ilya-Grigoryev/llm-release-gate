#!/usr/bin/env bash
# Copy the artifacts of every finished drift job to data/runs/drift/<repository>/<run id>-<attempt>/; jobs already
# copied are skipped. Run from the gate's repository:  study/fetch-drift.sh [DEST]
set -eu
DEST=${1:-data/runs/drift}
for repo in workbench-support receipt-intake telecom-support; do
  gh run list -R "Ilya-Grigoryev/$repo" --workflow drift.yml --status completed --limit 200 \
    --json databaseId,attempt -q '.[] | "\(.databaseId) \(.attempt)"' |
  while read -r id attempt; do
    dir="$DEST/$repo/$id-$attempt"
    [ -d "$dir" ] && continue
    mkdir -p "$dir"
    gh run download "$id" -R "Ilya-Grigoryev/$repo" -D "$dir" || { rmdir "$dir" 2>/dev/null; echo "no artifact: $repo $id"; }
  done
done
