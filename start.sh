#!/usr/bin/env sh
# Start the Meal Planner in the background (macOS/Linux). Safe to run when it is already running.
set -e
cd "$(dirname "$0")"
uv sync --quiet
[ -f planner.toml ] || cp planner.example.toml planner.toml
mkdir -p data
if ! uv run --quiet meals status >/dev/null 2>&1; then
  nohup uv run --quiet meals serve >>data/meals.log 2>&1 &
  i=0
  until uv run --quiet meals status >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 15 ]; then echo "The Meal Planner didn't start. See data/meals.log." >&2; exit 1; fi
    sleep 1
  done
fi
uv run --quiet meals status
