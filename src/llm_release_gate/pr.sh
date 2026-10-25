#!/usr/bin/env bash
# Gate a pull or merge request: run the base version (from BASE_REV) and the candidate (this
# checkout) on the golden set, compare them and write OUT_DIR/comment.md; OUT_DIR/cases gets the golden set's
# text files (cases and text inputs, never images), for whoever reads the results. Run it through
# `python -m llm_release_gate.pr BASE_REV PROJECT_DIR CONFIG GOLDEN_DIR OUT_DIR` from the root of the
# repository; PROJECT_DIR is the project's directory in it (`.` for the root), CONFIG is relative to it.
# Exits with the gate's code: 0 pass, 10 quality fail, 11 inconclusive, 12 budget fail, 20 infra error.
set -uo pipefail
unset VIRTUAL_ENV  # each tree syncs and runs its own environment
base_rev=$1 example=$2 config=$3
golden=$(cd "$4" && pwd)
mkdir -p "$5" && out=$(cd "$5" && pwd)
root=$(pwd)
rm -rf "$out/cases" && mkdir "$out/cases"
# Links are followed and their targets copied as files, so nothing else of the set can come along.
(cd "$golden" && find -L . -type f ! -path '*/.*' \( -iname '*.yaml' -o -iname '*.yml' -o -iname '*.json' \
  -o -iname '*.txt' -o -iname '*.md' -o -iname '*.csv' \) -print0) |
  while IFS= read -r -d '' f; do mkdir -p "$out/cases/${f%/*}" && cp -L "$golden/$f" "$out/cases/$f"; done

infra() {  # MESSAGE [LOG]: a comment for a run that could not decide
  {
    printf '**Release gate: ⚠️ infra error**\n\n%s\n' "$1"
    if [ -n "${2:-}" ]; then printf '\n```\n%s\n```\n' "$(tail -n 15 "$2")"; fi
  } > "$out/comment.md"
  echo "infra error: $1" >&2
  exit 20
}

run() {  # TREE OUT: one version's runs, with that tree's own code
  cd "$1/$example" && uv sync --locked --quiet &&
    uv run python -m llm_release_gate.runner --config "$config" --golden "$golden" --out "$2"
}

trap 'git -C "$root" worktree remove --force "$out/base-tree" 2> /dev/null' EXIT
git worktree add --detach "$out/base-tree" "$base_rev" > /dev/null ||
  infra "Cannot check out the target branch ($base_rev)."
[ -f "$out/base-tree/$example/$config" ] ||
  infra "The target branch has no $example/$config, so there is no base version to compare with."

(run "$out/base-tree" "$out/base.jsonl") > "$out/base.log" 2>&1 & base_pid=$!
(run "$root" "$out/candidate.jsonl") > "$out/candidate.log" 2>&1 & candidate_pid=$!
wait "$base_pid"; base_status=$?
wait "$candidate_pid"; candidate_status=$?
for arm in base candidate; do echo "--- $arm"; cat "$out/$arm.log"; done
[ "$base_status" -eq 0 ] || infra "The base version did not finish its runs." "$out/base.log"
[ "$candidate_status" -eq 0 ] || infra "The candidate did not finish its runs." "$out/candidate.log"

cd "$root/$example"
prices=()
if [ -f prices.yaml ]; then prices=(--prices prices.yaml); fi
uv run python -m llm_release_gate.gate --base "$out/base.jsonl" --candidate "$out/candidate.jsonl" \
  --golden "$golden" ${prices[@]+"${prices[@]}"} --markdown "$out/comment.md" --json "$out/verdict.json" 2> "$out/gate.log"
code=$?
cat "$out/gate.log" >&2
if [ "$code" -eq 20 ] || [ ! -f "$out/comment.md" ]; then infra "The gate could not compare the runs." "$out/gate.log"; fi
exit "$code"
