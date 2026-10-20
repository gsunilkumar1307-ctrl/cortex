#!/bin/bash
# ════════════════════════════════════════════════════════════
#  CORTEX — One-shot launcher
#  Usage:  bash start-cortex.sh
# ════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRAIN_DIR="$ROOT/cloud-brain"
DESKTOP_DIR="$ROOT/desktop-app"
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

# ── 1. Gemini API key ──────────────────────────────────────
if [ -z "${GEMINI_API_KEY:-}" ]; then
  if [ -f "$HOME/.zshrc" ]; then
    SAVED_KEY=$(grep -E "^export GEMINI_API_KEY=" "$HOME/.zshrc" 2>/dev/null | head -1 | cut -d'"' -f2 | cut -d"'" -f2 || true)
    if [ -n "$SAVED_KEY" ]; then
      export GEMINI_API_KEY="$SAVED_KEY"
    fi
  fi
fi

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo -e "${Y}  GEMINI_API_KEY not set.${NC}"
  if [ -t 0 ]; then
    echo -n "  Paste your Gemini API key (or press Enter for Local Offline Mode): "
    read -r USER_KEY || true
    if [ -n "$USER_KEY" ]; then
      export GEMINI_API_KEY="$USER_KEY"
      PROFILE="$HOME/.zshrc"
      [ ! -f "$PROFILE" ] && touch "$PROFILE"
      if ! grep -q "GEMINI_API_KEY" "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo "export GEMINI_API_KEY=\"$GEMINI_API_KEY\"  # Added by Cortex" >> "$PROFILE"
        ok "API key saved to ~/.zshrc (permanent — won't ask again)"
      fi
    fi
  fi
fi

if [ -n "${GEMINI_API_KEY:-}" ]; then
  ok "Gemini API key configured"
else
  warn "Running in Local Mode (offline regex intent engine + Apple Mail automation)"
fi
export CORTEX_EXECUTION_MODE="live"
ok "Execution mode: live (automation enabled)"

# ── 2. Python dependency check ─────────────────────────────
info "Installing Python dependencies..."
PYTHON="python3"
$PYTHON -m pip install -r "$BRAIN_DIR/requirements.txt" \
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
GEMINI_API_KEY="$GEMINI_API_KEY" \
  $PYTHON -m uvicorn app.server:app \
  --host 127.0.0.1 \
  --port 8765 \
  --app-dir "$BRAIN_DIR" \
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
