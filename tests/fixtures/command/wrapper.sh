#!/bin/sh
# Stands in for `uv run` or `npx`: the agent runs as a child of this shell. Writes the child's pid to $1.
sleep 30 &
echo $! > "$1"
wait
