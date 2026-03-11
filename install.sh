#!/bin/bash
# ============================================================================
#  HyperTrader — Installation Script
#  Handles complete setup: dependencies, database, configuration, and launch
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Symbols
CHECK="${GREEN}[OK]${NC}"
CROSS="${RED}[FAIL]${NC}"
ARROW="${CYAN}>>>${NC}"
WARN="${YELLOW}[!]${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================================
#  Header
# ============================================================================
clear 2>/dev/null || true
echo ""
echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║           H Y P E R T R A D E R          ║"
echo "  ║        Installation & Setup Script        ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${DIM}Automated trading bot with TradingView webhooks${NC}"
echo -e "  ${DIM}and Hyperliquid perpetual futures execution${NC}"
echo ""

# ============================================================================
#  Helper functions
# ============================================================================
log()    { echo -e "  ${ARROW} $1"; }
ok()     { echo -e "  ${CHECK} $1"; }
fail()   { echo -e "  ${CROSS} $1"; }
warn()   { echo -e "  ${WARN} $1"; }
header() { echo ""; echo -e "  ${BOLD}${BLUE}── $1 ──${NC}"; echo ""; }

command_exists() {
    command -v "$1" &>/dev/null
}

# ============================================================================
#  Step 1: Check Prerequisites
# ============================================================================
header "Step 1/6 — Checking Prerequisites"

PYTHON_CMD=""
NODE_CMD=""
NPM_CMD=""
ERRORS=0

# Find Python
if command_exists python3; then
    PYTHON_CMD="python3"
elif command_exists python; then
    PYTHON_CMD="python"
elif [ -f "/c/Users/$USER/AppData/Local/Programs/Python/Python312/python.exe" ]; then
    PYTHON_CMD="/c/Users/$USER/AppData/Local/Programs/Python/Python312/python.exe"
fi

if [ -n "$PYTHON_CMD" ]; then
    PY_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+')
    ok "Python found: $($PYTHON_CMD --version 2>&1) ($PYTHON_CMD)"

    # Check minimum version
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
        fail "Python 3.10+ required, found $PY_VERSION"
        ERRORS=$((ERRORS + 1))
    fi
else
    fail "Python not found. Install Python 3.10+ from https://python.org"
    ERRORS=$((ERRORS + 1))
fi

# Find Node.js
if command_exists node; then
    NODE_CMD="node"
    NPM_CMD="npm"
elif [ -f "/c/Program Files/nodejs/node.exe" ]; then
    export PATH="/c/Program Files/nodejs:$PATH"
    NODE_CMD="node"
    NPM_CMD="npm"
fi

if [ -n "$NODE_CMD" ]; then
    NODE_VERSION=$($NODE_CMD --version 2>&1)
    ok "Node.js found: $NODE_VERSION"

    NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -lt 18 ]; then
        fail "Node.js 18+ required, found $NODE_VERSION"
        ERRORS=$((ERRORS + 1))
    fi
else
    fail "Node.js not found. Install Node.js 18+ from https://nodejs.org"
    ERRORS=$((ERRORS + 1))
fi

# Check pip
if [ -n "$PYTHON_CMD" ]; then
    if $PYTHON_CMD -m pip --version &>/dev/null; then
        ok "pip available"
    else
        fail "pip not found. Run: $PYTHON_CMD -m ensurepip"
        ERRORS=$((ERRORS + 1))
    fi
fi

if [ "$ERRORS" -gt 0 ]; then
    echo ""
    fail "Missing $ERRORS prerequisite(s). Please install them and re-run this script."
    exit 1
fi

ok "All prerequisites met"

# ============================================================================
#  Step 2: Backend Setup
# ============================================================================
header "Step 2/6 — Setting Up Backend"

cd "$SCRIPT_DIR/backend"

# Create virtual environment
if [ ! -d "venv" ]; then
    log "Creating Python virtual environment..."
    $PYTHON_CMD -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# Activate venv
log "Activating virtual environment..."
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi
ok "Virtual environment activated"

# Install dependencies
log "Installing Python dependencies..."
pip install -r requirements.txt -q --disable-pip-version-check 2>&1 | tail -1
ok "Python dependencies installed"

cd "$SCRIPT_DIR"

# ============================================================================
#  Step 3: Frontend Setup
# ============================================================================
header "Step 3/6 — Setting Up Frontend"

cd "$SCRIPT_DIR/frontend"

log "Installing Node.js dependencies..."
$NPM_CMD install --loglevel=error 2>&1 | tail -3
ok "Node.js dependencies installed"

cd "$SCRIPT_DIR"

# ============================================================================
#  Step 4: Configuration
# ============================================================================
header "Step 4/6 — Configuration"

cd "$SCRIPT_DIR/backend"

if [ ! -f ".env" ]; then
    cp .env.example .env

    # Generate a secure webhook secret
    if command_exists openssl; then
        SECRET=$(openssl rand -base64 32 | tr -d '/+=' | head -c 40)
    else
        SECRET=$(date +%s%N | sha256sum | head -c 40)
    fi

    # Write the secret to .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/change-me-to-a-secure-secret/$SECRET/" .env
    else
        sed -i "s/change-me-to-a-secure-secret/$SECRET/" .env
    fi

    ok "Created .env with generated webhook secret"
    echo -e "  ${DIM}   Secret: $SECRET${NC}"
    echo -e "  ${DIM}   Edit backend/.env to customize settings${NC}"
else
    ok ".env already exists (kept existing config)"
fi

cd "$SCRIPT_DIR"

# ============================================================================
#  Step 5: Initialize Database
# ============================================================================
header "Step 5/6 — Initializing Database"

cd "$SCRIPT_DIR/backend"

# Activate venv again in case
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

if [ -f "hypertrader.db" ]; then
    ok "Database already exists (kept existing data)"
else
    log "Creating database and tables..."
    $PYTHON_CMD -c "
import asyncio
from app.database import engine, Base
from app.models import *

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Database initialized successfully')

asyncio.run(init())
" 2>&1
    ok "Database created with all tables"
fi

cd "$SCRIPT_DIR"

# ============================================================================
#  Step 6: Verify Installation
# ============================================================================
header "Step 6/6 — Verifying Installation"

# Check all critical files exist
ALL_GOOD=true

for f in \
    "backend/app/main.py" \
    "backend/app/config.py" \
    "backend/app/models.py" \
    "backend/app/routers/webhook.py" \
    "backend/app/services/paper_trader.py" \
    "backend/requirements.txt" \
    "backend/.env" \
    "frontend/package.json" \
    "frontend/src/app/page.tsx" \
    "frontend/src/app/layout.tsx" \
    "start.sh"
do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        ok "$f"
    else
        fail "$f missing!"
        ALL_GOOD=false
    fi
done

# Check venv has required packages
cd "$SCRIPT_DIR/backend"
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

$PYTHON_CMD -c "import fastapi, sqlalchemy, httpx, pydantic_settings" 2>/dev/null
if [ $? -eq 0 ]; then
    ok "Backend packages verified"
else
    fail "Some backend packages missing"
    ALL_GOOD=false
fi
cd "$SCRIPT_DIR"

# Check node_modules
if [ -d "$SCRIPT_DIR/frontend/node_modules/next" ]; then
    ok "Frontend packages verified"
else
    fail "Frontend packages missing"
    ALL_GOOD=false
fi

# ============================================================================
#  Done
# ============================================================================
echo ""
if [ "$ALL_GOOD" = true ]; then
    echo -e "${BOLD}${GREEN}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║      Installation Complete!              ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  ${BOLD}To start HyperTrader:${NC}"
    echo ""
    echo -e "    ${CYAN}./start.sh${NC}"
    echo ""
    echo -e "  ${BOLD}Or start manually:${NC}"
    echo ""
    echo -e "    ${DIM}# Terminal 1 — Backend${NC}"
    echo -e "    ${CYAN}cd backend && source venv/Scripts/activate${NC}"
    echo -e "    ${CYAN}uvicorn app.main:app --reload${NC}"
    echo ""
    echo -e "    ${DIM}# Terminal 2 — Frontend${NC}"
    echo -e "    ${CYAN}cd frontend && npm run dev${NC}"
    echo ""
    echo -e "  ${BOLD}Endpoints:${NC}"
    echo -e "    Dashboard:  ${CYAN}http://localhost:3000${NC}"
    echo -e "    API:        ${CYAN}http://localhost:8000${NC}"
    echo -e "    Webhook:    ${CYAN}http://localhost:8000/api/webhook${NC}"
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo -e "    1. Edit ${CYAN}backend/.env${NC} to set your webhook secret"
    echo -e "    2. Set up ngrok: ${CYAN}ngrok http 8000${NC}"
    echo -e "    3. Add the ngrok URL as webhook in TradingView alerts"
    echo ""
else
    echo -e "${BOLD}${RED}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║   Installation completed with errors     ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  Check the errors above and re-run ${CYAN}./install.sh${NC}"
    echo ""
fi
