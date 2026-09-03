#!/bin/sh
# Keep this script LF-only: Docker executes it directly in a Linux container.
set -eu

uv run alembic upgrade head
exec uv run python -m app
