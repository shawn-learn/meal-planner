#!/usr/bin/env sh
# Stop the Meal Planner that start.sh started.
cd "$(dirname "$0")"
exec uv run --quiet meals stop
