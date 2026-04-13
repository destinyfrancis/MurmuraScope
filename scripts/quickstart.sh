#!/usr/bin/env bash
# =============================================================================
# MurmuraScope — Quick Start Wizard
# Usage: bash scripts/quickstart.sh  OR  make quickstart
# =============================================================================
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }
err()  { echo -e "${RED}✗ ERROR:${RESET} $*" >&2; }
hdr()  { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

# ── Navigate to project root (works wherever script is called from) ───────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     MurmuraScope  —  Quick Start         ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${RESET}"

# =============================================================================
# STEP 1 — Check prerequisites
# =============================================================================
hdr "Step 1/4 — Checking prerequisites"

# Python 3.10–3.11 required (OASIS does NOT support 3.12+)
if ! command -v python3 &>/dev/null; then
    err "python3 not found. Please install Python 3.10 or 3.11 first."
    echo "    → https://www.python.org/downloads/"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -ne 3 ] || [ "$PY_MINOR" -lt 10 ] || [ "$PY_MINOR" -gt 11 ]; then
    err "Python ${PY_VER} detected. MurmuraScope requires Python 3.10 or 3.11."
    echo "    OASIS (the simulation engine) does not support Python 3.12+."
    echo "    → https://www.python.org/downloads/release/python-31115/"
    exit 1
fi
ok "Python ${PY_VER}"

# Node.js
if ! command -v node &>/dev/null; then
    err "Node.js not found. Please install Node.js 18+ first."
    echo "    → https://nodejs.org/"
    exit 1
fi
NODE_VER=$(node --version)
ok "Node.js ${NODE_VER}"

# npm
if ! command -v npm &>/dev/null; then
    err "npm not found (should come with Node.js)."
    exit 1
fi
ok "npm $(npm --version)"

# =============================================================================
# STEP 2 — Configure .env
# =============================================================================
hdr "Step 2/4 — Configuring environment"

if [ ! -f ".env" ]; then
    cp .env.example .env
    ok "Created .env from .env.example"
else
    ok ".env already exists — keeping it"
fi

# Generate AUTH_SECRET_KEY if still placeholder
if grep -q "^AUTH_SECRET_KEY=your-secret-key-here" .env 2>/dev/null; then
    if command -v openssl &>/dev/null; then
        SECRET=$(openssl rand -hex 32)
        # Use temp file to avoid in-place sed portability issues
        tmp=$(mktemp)
        sed "s|^AUTH_SECRET_KEY=your-secret-key-here|AUTH_SECRET_KEY=${SECRET}|" .env > "$tmp"
        mv "$tmp" .env
        ok "Generated AUTH_SECRET_KEY (random 256-bit key)"
    else
        warn "openssl not found — please set AUTH_SECRET_KEY manually in .env"
    fi
fi

# Enable DEBUG mode for local dev (safe default; server won't reject missing key)
if grep -q "^DEBUG=false" .env 2>/dev/null; then
    tmp=$(mktemp)
    sed "s|^DEBUG=false|DEBUG=true|" .env > "$tmp"
    mv "$tmp" .env
    ok "Set DEBUG=true for local development"
fi

# Check OPENROUTER_API_KEY — prompt if missing or still placeholder
CURRENT_KEY=$(grep "^OPENROUTER_API_KEY=" .env 2>/dev/null | cut -d= -f2- || echo "")
if [ -z "$CURRENT_KEY" ] || [ "$CURRENT_KEY" = "sk-or-your-openrouter-key" ]; then
    echo ""
    echo -e "  ${BOLD}MurmuraScope needs an OpenRouter API key to run simulations.${RESET}"
    echo "  Get one free at: https://openrouter.ai/keys"
    echo ""
    read -r -p "  Paste your OPENROUTER_API_KEY (or press Enter to skip for now): " USER_KEY
    if [ -n "$USER_KEY" ]; then
        tmp=$(mktemp)
        sed "s|^OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=${USER_KEY}|" .env > "$tmp"
        mv "$tmp" .env
        ok "OPENROUTER_API_KEY saved to .env"
    else
        warn "Skipped — simulations will fail without an API key. Edit .env later."
    fi
else
    ok "OPENROUTER_API_KEY already set"
fi

# =============================================================================
# STEP 3 — Install dependencies
# =============================================================================
hdr "Step 3/4 — Installing dependencies"

# ── Python venv ───────────────────────────────────────────────────────────────
VENV_DIR="${PROJECT_ROOT}/.venv311"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating Python virtual environment (.venv311)..."
    python3 -m venv "$VENV_DIR"
    ok "Created .venv311"
else
    ok ".venv311 already exists"
fi

VENV_PIP="${VENV_DIR}/bin/pip"
VENV_PYTHON="${VENV_DIR}/bin/python"

echo "  Installing Python packages (this may take 2–3 min on first run)..."
"$VENV_PIP" install --quiet --upgrade pip
"$VENV_PIP" install --quiet -e ".[dev]"
ok "Python dependencies installed"

# ── Frontend npm ──────────────────────────────────────────────────────────────
echo "  Installing frontend packages..."
(cd frontend && npm install --silent)
ok "Frontend dependencies installed"

# ── Root package.json (concurrently) ─────────────────────────────────────────
if [ ! -f "package.json" ]; then
    warn "Root package.json not found — run this script from the project root."
fi
echo "  Installing root npm packages (concurrently)..."
npm install --silent
ok "Root npm packages installed"

# ── Ensure data directory exists ──────────────────────────────────────────────
mkdir -p data logs
ok "data/ and logs/ directories ready"

# =============================================================================
# STEP 4 — Launch
# =============================================================================
hdr "Step 4/4 — Starting MurmuraScope"

UVICORN="${VENV_DIR}/bin/uvicorn"
mkdir -p "${PROJECT_ROOT}/logs"

# ── Start backend in background ───────────────────────────────────────────────
echo "  Starting backend..."
"$UVICORN" backend.app:create_app --factory --reload --port 5001 \
    > "${PROJECT_ROOT}/logs/backend.log" 2>&1 &
BACKEND_PID=$!

# ── Wait for backend to be healthy (up to 45s) ────────────────────────────────
echo -n "  Waiting for backend to be ready"
RETRIES=0
until curl -sf http://localhost:5001/api/health > /dev/null 2>&1; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo ""
        err "Backend process crashed. Check logs:"
        echo "    tail -f ${PROJECT_ROOT}/logs/backend.log"
        exit 1
    fi
    if [ "$RETRIES" -ge 45 ]; then
        echo ""
        err "Backend did not become healthy after 45s. Check logs:"
        echo "    tail -f ${PROJECT_ROOT}/logs/backend.log"
        kill "$BACKEND_PID" 2>/dev/null || true
        exit 1
    fi
    echo -n "."
    sleep 1
    RETRIES=$((RETRIES + 1))
done
echo ""
ok "Backend ready  →  http://localhost:5001"

# ── Start frontend in background ─────────────────────────────────────────────
echo "  Starting frontend..."
(cd "${PROJECT_ROOT}/frontend" && npm run dev) \
    > "${PROJECT_ROOT}/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!

# Give Vite a moment to bind its port
sleep 2
ok "Frontend ready  →  http://localhost:5173"

# ── Open browser (macOS / Linux) ──────────────────────────────────────────────
if command -v open &>/dev/null; then
    open "http://localhost:5173"
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:5173"
fi

echo ""
echo -e "  ${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "  ${BOLD}║     MurmuraScope is running!             ║${RESET}"
echo -e "  ${BOLD}║                                          ║${RESET}"
echo -e "  ${BOLD}║  Frontend : http://localhost:5173        ║${RESET}"
echo -e "  ${BOLD}║  Backend  : http://localhost:5001        ║${RESET}"
echo -e "  ${BOLD}║  API docs : http://localhost:5001/docs   ║${RESET}"
echo -e "  ${BOLD}║                                          ║${RESET}"
echo -e "  ${BOLD}║  Logs  →  tail -f logs/backend.log       ║${RESET}"
echo -e "  ${BOLD}║  Stop  →  Ctrl+C                         ║${RESET}"
echo -e "  ${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ── Graceful shutdown on Ctrl+C ───────────────────────────────────────────────
cleanup() {
    echo ""
    echo -e "${YELLOW}  Shutting down MurmuraScope...${RESET}"
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    pkill -f "run_(twitter|parallel|facebook|instagram|reddit)_simulation.py" 2>/dev/null || true
    pkill -f "uvicorn.*5001" 2>/dev/null || true
    ok "Stopped. Goodbye!"
    exit 0
}
trap cleanup INT TERM

# Keep script alive until a child exits or user presses Ctrl+C
wait "$BACKEND_PID"
