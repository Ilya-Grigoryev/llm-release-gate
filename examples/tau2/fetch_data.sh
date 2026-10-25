#!/bin/sh
# tau2-bench v1.0.1 data the example needs (telecom and the user simulator's guidelines), ~30 MB, outside git.
# Usage: sh fetch_data.sh [dir]   (default: ../../data/tau2-bench; the adapter reads TAU2_DATA_DIR or this default)
set -eu
dir=${1:-../../data/tau2-bench}
[ -d "$dir/.git" ] && { echo "$dir exists"; exit 0; }
git clone --quiet --depth 1 --branch v1.0.1 --filter=blob:none --no-checkout \
  https://github.com/sierra-research/tau2-bench "$dir"
git -C "$dir" sparse-checkout set --no-cone \
  '/data/tau2/user_simulator/' \
  '/data/tau2/domains/telecom/*.toml' '/data/tau2/domains/telecom/*.md' \
  '/data/tau2/domains/telecom/tasks.json' '/data/tau2/domains/telecom/split_tasks.json' \
  '/LICENSE'
git -C "$dir" checkout --quiet
echo "tau2-bench v1.0.1 data in $dir/data"
