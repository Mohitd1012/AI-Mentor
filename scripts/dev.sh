#!/usr/bin/env bash
# Start AI Mentor in development mode.
# Launches the Python backend and the Tauri dev app.

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
DESKTOP="$ROOT/desktop"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log()  { echo -e "${GREEN}[mentor]${NC} $*"; }
warn() { echo -e "${YELLOW}[mentor]${NC} $*"; }
err()  { echo -e "${RED}[mentor]${NC} $*"; }

# ── Prereq checks ────────────────────────────────────────────────────────────
log "Checking prerequisites..."

if ! command -v ollama &>/dev/null; then
  err "Ollama not found. Install from https://ollama.ai"
  exit 1
fi

if ! ollama list &>/dev/null; then
  warn "Ollama is not running. Starting it..."
  ollama serve &>/dev/null &
  sleep 2
fi

if ! command -v python3 &>/dev/null; then
  err "Python 3 not found."
  exit 1
fi

# ── Python venv ──────────────────────────────────────────────────────────────
VENV="$BACKEND/.venv"
if [ ! -d "$VENV" ]; then
  log "Creating Python virtual environment..."
  python3 -m venv "$VENV"
fi

log "Installing Python dependencies..."
"$VENV/bin/pip" install -q -r "$BACKEND/requirements.txt"

# ── Start backend ─────────────────────────────────────────────────────────────
log "Starting Python backend on :8765..."
cd "$BACKEND"
"$VENV/bin/python" main.py &
BACKEND_PID=$!

# Wait for backend to be ready
for i in $(seq 1 15); do
  if curl -s http://localhost:8765/health &>/dev/null; then
    log "Backend ready ✓"
    break
  fi
  sleep 0.5
done

# ── Start Tauri dev ───────────────────────────────────────────────────────────
log "Starting Tauri desktop app..."
cd "$DESKTOP"
npm run tauri dev

# ── Cleanup ───────────────────────────────────────────────────────────────────
log "Shutting down backend (pid $BACKEND_PID)..."
kill "$BACKEND_PID" 2>/dev/null || true
