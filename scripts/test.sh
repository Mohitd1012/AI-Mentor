#!/usr/bin/env bash
# Run the backend test suite.

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$BACKEND/requirements.txt"
fi

cd "$BACKEND"
echo "Running unit tests..."
"$VENV/bin/pytest" tests/ -v -m "not integration" "$@"

echo ""
echo "To run integration tests (requires Ollama): ./scripts/test.sh -m integration"
