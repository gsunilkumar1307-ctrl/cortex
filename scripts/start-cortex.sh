#!/bin/bash
# ════════════════════════════════════════════════════════════
#  CORTEX — One-shot launcher
#  Usage:  bash start-cortex.sh
# ════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
[ ! -d "$BACKEND_DIR" ] && BACKEND_DIR="$ROOT/cloud-brain"
DESKTOP_DIR="$ROOT/apps/desktop"
[ ! -d "$DESKTOP_DIR" ] && DESKTOP_DIR="$ROOT/desktop-app"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

# ── Pretty output ──────────────────────────────────────────
G='\033[0;32m'; B='\033[0;34m'; Y='\033[1;33m'
R='\033[0;31m'; C='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${G}✓${NC} $1"; }
info() { echo -e "  ${B}→${NC} $1"; }
warn() { echo -e "  ${Y}⚠${NC}  $1"; }
fail() { echo -e "  ${R}✕${NC} $1"; exit 1; }

echo ""
echo -e "${C}  ╔═══════════════════════════════════╗${NC}"
echo -e "${C}  ║      C O R T E X   v0.2           ║${NC}"
echo -e "${C}  ║  Premium AI Desktop Assistant      ║${NC}"
echo -e "${C}  ╚═══════════════════════════════════╝${NC}"
echo ""

# ── 1. Local Ollama & Model Configuration ─────────────────
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.5:9b}"

info "Verifying local Ollama service at $OLLAMA_HOST..."
if curl -s -f "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  ok "Local Ollama service active"
else
  info "Local Ollama service not running. Starting Ollama automatically..."
  OLLAMA_BIN="$(which ollama 2>/dev/null || true)"
  [ -z "$OLLAMA_BIN" ] && [ -x "/usr/local/bin/ollama" ] && OLLAMA_BIN="/usr/local/bin/ollama"
  [ -z "$OLLAMA_BIN" ] && [ -x "/opt/homebrew/bin/ollama" ] && OLLAMA_BIN="/opt/homebrew/bin/ollama"
  [ -z "$OLLAMA_BIN" ] && [ -x "/Applications/Ollama.app/Contents/Resources/ollama" ] && OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"

  if [ -n "$OLLAMA_BIN" ]; then
    if ! pgrep -x ollama >/dev/null 2>&1; then
      "$OLLAMA_BIN" serve > "$LOG_DIR/ollama.log" 2>&1 &
    fi
  elif [ -d "/Applications/Ollama.app" ]; then
    open -a Ollama --background
  else
    warn "Ollama installation not found. Local AI will be marked unavailable."
  fi

  # Bounded retries: wait for Ollama to become healthy (max 20s)
  OLLAMA_READY=0
  for i in $(seq 1 40); do
    sleep 0.5
    if curl -s -f "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
      OLLAMA_READY=1
      break
    fi
  done
  if [ $OLLAMA_READY -eq 1 ]; then
    ok "Local Ollama service started successfully"
  else
    warn "Local Ollama did not respond within 20s. Check $LOG_DIR/ollama.log"
  fi
fi

if curl -s -f "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  MODEL_NAME="${OLLAMA_MODEL%%:*}"
  if curl -s "$OLLAMA_HOST/api/tags" | grep -q "$MODEL_NAME"; then
    ok "Local model verified: $OLLAMA_MODEL"
  else
    warn "Model $OLLAMA_MODEL not found in Ollama tags. Run: ollama pull $OLLAMA_MODEL"
  fi
else
  warn "Local AI unavailable: Ollama service is not responding at $OLLAMA_HOST"
fi
ok "Inference engine: Local Ollama (Apple Silicon native MLX / zero cloud cost)"

export CORTEX_EXECUTION_MODE="live"
ok "Execution mode: live (automation enabled)"

# ── 2. Python dependency check ─────────────────────────────
info "Installing Python dependencies..."
PYTHON="python3"
REQ_FILE="$BACKEND_DIR/requirements.txt"
[ ! -f "$REQ_FILE" ] && REQ_FILE="$ROOT/cloud-brain/requirements.txt"
$PYTHON -m pip install -r "$REQ_FILE" \
  -q --disable-pip-version-check 2>&1 \
  | grep -v "already satisfied" || true
$PYTHON -m playwright install chromium >/dev/null 2>&1 || true
ok "Python deps ready"

# ── 3. Node dependency check ───────────────────────────────
if [ ! -d "$DESKTOP_DIR/node_modules" ]; then
  info "Installing Node packages (first time — ~1 min)..."
  npm install --prefix "$DESKTOP_DIR" 2>&1 | tail -3
fi
ok "Node deps ready"

# ── 4. Kill anything already on port 8765 / 5173 ──────────
for PORT in 8765 5173; do
  PID=$(lsof -ti tcp:$PORT 2>/dev/null || true)
  if [ -n "$PID" ]; then
    warn "Port $PORT in use — killing PID $PID"
    kill -9 $PID 2>/dev/null || true
    sleep 0.5
  fi
done

# ── 5. Start cloud brain ───────────────────────────────────
info "Starting Cortex cloud brain..."
APP_MODULE="backend.api.server:app"
APP_DIR="$ROOT"
if [ ! -d "$ROOT/backend" ]; then
  APP_MODULE="app.server:app"
  APP_DIR="$ROOT/cloud-brain"
fi

OLLAMA_HOST="$OLLAMA_HOST" \
OLLAMA_MODEL="$OLLAMA_MODEL" \
  $PYTHON -m uvicorn "$APP_MODULE" \
  --host 127.0.0.1 \
  --port 8765 \
  --app-dir "$APP_DIR" \
  --reload \
  --log-level warning \
  > "$LOG_DIR/brain.log" 2>&1 &
BRAIN_PID=$!

# Wait until /health responds (max 20s)
READY=0
for i in $(seq 1 20); do
  sleep 1
  if curl -sf http://127.0.0.1:8765/health > /dev/null 2>&1; then
    READY=1; break
  fi
  # Check the process didn't crash
  if ! kill -0 $BRAIN_PID 2>/dev/null; then
    echo ""
    echo -e "${R}  Brain crashed. Last log:${NC}"
    tail -20 "$LOG_DIR/brain.log"
    fail "Cloud brain failed to start. Fix the error above and retry."
  fi
done
[ $READY -eq 0 ] && { warn "Brain not responding after 20s — check $LOG_DIR/brain.log"; }
ok "Cloud brain running  →  http://127.0.0.1:8765  (PID $BRAIN_PID)"

# ── 6. Start Vite dev server ───────────────────────────────
info "Starting UI server..."
npm run dev --prefix "$DESKTOP_DIR" \
  > "$LOG_DIR/vite.log" 2>&1 &
VITE_PID=$!

# Wait until port 5173 is open (max 25s)
READY=0
for i in $(seq 1 25); do
  sleep 1
  if curl -sf http://127.0.0.1:5173 > /dev/null 2>&1; then
    READY=1; break
  fi
  if ! kill -0 $VITE_PID 2>/dev/null; then
    echo ""
    echo -e "${R}  Vite crashed. Last log:${NC}"
    tail -20 "$LOG_DIR/vite.log"
    kill $BRAIN_PID 2>/dev/null || true
    fail "Vite failed to start. Fix the error above and retry."
  fi
done
[ $READY -eq 0 ] && { warn "Vite not responding after 25s — check $LOG_DIR/vite.log"; }
ok "UI server running     →  http://127.0.0.1:5173  (PID $VITE_PID)"

# ── 7. Open Electron ───────────────────────────────────────
echo ""
echo -e "${G}  ✨ Opening Cortex — enjoy!${NC}"
echo -e "  ${B}Logs:${NC} $LOG_DIR"
echo ""

# Trap Ctrl+C / window close → kill children
cleanup() {
  echo ""
  echo -e "${Y}  Shutting down Cortex...${NC}"
  kill $BRAIN_PID $VITE_PID 2>/dev/null || true
  ok "All processes stopped. Goodbye."
  echo ""
}
trap cleanup EXIT INT TERM

npm run electron --prefix "$DESKTOP_DIR"
