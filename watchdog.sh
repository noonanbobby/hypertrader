#!/bin/bash
# HyperTrader Watchdog — Auto-restart service monitor
# Replaces start.sh with continuous health checks and Telegram alerts
# Usage: bash watchdog.sh

set -euo pipefail
export PYTHONIOENCODING=utf-8

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDS_DIR="$DIR/.pids"
LOG_FILE="$DIR/watchdog.log"
DB_FILE="$DIR/backend/hypertrader.db"
CHECK_INTERVAL=20
FAIL_THRESHOLD=2
GRACE_PERIOD=30
LOG_MAX_BYTES=10485760  # 10MB

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Failure counters
BACKEND_FAILS=0
FRONTEND_FAILS=0
NGROK_FAILS=0

# Start timestamps (epoch seconds) — used for grace period
BACKEND_STARTED=0
FRONTEND_STARTED=0
NGROK_STARTED=0

# Track ngrok URL
NGROK_URL="unavailable"

# Telegram command polling state
TELEGRAM_OFFSET_FILE="$PIDS_DIR/telegram_offset"
WATCHDOG_START_TIME=$(date +%s)

# ─── Logging ────────────────────────────────────────────────────────────────────

log() {
  local level="$1"
  shift
  local msg="$*"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  local color="$NC"
  case "$level" in
    INFO)  color="$GREEN" ;;
    WARN)  color="$YELLOW" ;;
    ERROR) color="$RED" ;;
    START) color="$CYAN" ;;
  esac
  echo -e "${color}[$ts] [$level] $msg${NC}"
  echo "[$ts] [$level] $msg" >> "$LOG_FILE"
}

rotate_log() {
  if [ -f "$LOG_FILE" ]; then
    local size
    size=$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$size" -gt "$LOG_MAX_BYTES" ]; then
      mv "$LOG_FILE" "${LOG_FILE}.old"
      log INFO "Log rotated (was ${size} bytes)"
    fi
  fi
}

# ─── Telegram ───────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""

load_telegram_config() {
  if [ -f "$DB_FILE" ]; then
    local creds
    local db_win_path
    db_win_path=$(cygpath -w "$DB_FILE" 2>/dev/null || echo "$DB_FILE")
    creds=$(python -c "
import sqlite3
try:
    conn = sqlite3.connect(r'$db_win_path')
    row = conn.execute('SELECT telegram_bot_token, telegram_chat_id FROM app_settings WHERE id=1').fetchone()
    conn.close()
    if row and row[0] and row[1]:
        print(f'{row[0]}|{row[1]}')
except:
    pass
" 2>/dev/null || echo "")
    if [ -n "$creds" ]; then
      TELEGRAM_BOT_TOKEN="${creds%%|*}"
      TELEGRAM_CHAT_ID="${creds##*|}"
    fi
  fi
  if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    log WARN "Telegram not configured — alerts disabled (set credentials in dashboard Settings)"
    return 1
  fi
  return 0
}

send_telegram() {
  local msg="$1"
  if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    python -c "
import urllib.request, json
text = '''$msg'''.replace('%0A', '\n')
data = json.dumps({'chat_id': '$TELEGRAM_CHAT_ID', 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
req = urllib.request.Request('https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage', data=data, headers={'Content-Type': 'application/json'})
try: urllib.request.urlopen(req, timeout=10)
except: pass
" > /dev/null 2>&1 &
  fi
}

# ─── Telegram Bot Commands ─────────────────────────────────────────────────────

format_uptime() {
  local seconds="$1"
  local days=$((seconds / 86400))
  local hours=$(( (seconds % 86400) / 3600 ))
  local mins=$(( (seconds % 3600) / 60 ))
  if [ "$days" -gt 0 ]; then
    echo "${days}d ${hours}h ${mins}m"
  elif [ "$hours" -gt 0 ]; then
    echo "${hours}h ${mins}m"
  else
    echo "${mins}m"
  fi
}

build_status_message() {
  local now
  now=$(date +%s)
  local uptime=$((now - WATCHDOG_START_TIME))

  # Check each service
  local be_status="🔴 DOWN"
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    be_status="🟢 UP"
  fi

  local fe_status="🔴 DOWN"
  if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    fe_status="🟢 UP"
  fi

  local ng_status="🔴 DOWN"
  local tunnels
  tunnels=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null || echo "")
  if [ -n "$tunnels" ] && echo "$tunnels" | python -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); exit(0 if t else 1)" 2>/dev/null; then
    ng_status="🟢 UP"
  fi

  # Refresh ngrok URL
  fetch_ngrok_url

  local uptime_str
  uptime_str=$(format_uptime "$uptime")

  echo "📊 <b>HyperTrader Status</b>%0A%0A"\
"Backend:  ${be_status}%0A"\
"Frontend: ${fe_status}%0A"\
"ngrok:    ${ng_status}%0A%0A"\
"⏱ Uptime: ${uptime_str}%0A"\
"🔗 Webhook: ${NGROK_URL}/api/webhook"
}

send_trades_snapshot() {
  python -c "
import urllib.request, json
from datetime import datetime, timedelta, timezone

API = 'http://localhost:8000/api'
TOKEN = '$TELEGRAM_BOT_TOKEN'
CHAT = '$TELEGRAM_CHAT_ID'

def fetch(path):
    try:
        resp = urllib.request.urlopen(f'{API}{path}', timeout=10)
        return json.loads(resp.read())
    except:
        return None

def sign(v):
    return '+' if v >= 0 else ''

def fmt(v):
    return f'{sign(v)}\${v:,.2f}'

def send(text):
    data = json.dumps({'chat_id': CHAT, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
    req = urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/sendMessage', data=data, headers={'Content-Type': 'application/json'})
    try: urllib.request.urlopen(req, timeout=10)
    except: pass

# Fetch all data
dash = fetch('/dashboard')
if dash is None:
    send('📋 <b>HyperTrader Snapshot</b>\n\n⚠️ Backend unavailable')
    exit()

now = datetime.now(timezone.utc)
start_24h = (now - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
closed = fetch(f'/trades?status=closed&start_date={start_24h}&limit=1000') or []
positions = fetch('/positions') or []
analytics = fetch('/analytics')

lines = ['📋 <b>HyperTrader 24h Snapshot</b>']
lines.append(f'🕐 {now.strftime(\"%b %d, %H:%M\")} UTC')
lines.append('')

# ── Wallet Overview ──
mode = dash.get('trading_mode', 'paper').upper()
equity = dash.get('total_equity', 0)
total_pnl = dash.get('total_pnl', 0)
daily_pnl = dash.get('daily_pnl', 0)
weekly_pnl = dash.get('weekly_pnl', 0)

lines.append(f'💼 <b>Wallet</b> ({mode})')
lines.append(f'   Equity: \${equity:,.2f}')
lines.append(f'   Total P&L: {fmt(total_pnl)}')
lines.append(f'   24h P&L: {fmt(daily_pnl)}')
lines.append(f'   7d P&L: {fmt(weekly_pnl)}')
lines.append('')

# ── 24h Trading Activity ──
wins_24h = sum(1 for t in closed if t.get('realized_pnl', 0) > 0)
losses_24h = len(closed) - wins_24h
realized_24h = sum(t.get('realized_pnl', 0) for t in closed)
fees_24h = sum(t.get('fees', 0) for t in closed)
wr_24h = (wins_24h / len(closed) * 100) if closed else 0

lines.append(f'📊 <b>24h Activity</b>')
lines.append(f'   Trades: {len(closed)} ({wins_24h}W / {losses_24h}L)')
if closed:
    lines.append(f'   Win Rate: {wr_24h:.1f}%')
    lines.append(f'   Realized: {fmt(realized_24h)}')
    lines.append(f'   Fees: \${fees_24h:,.2f}')
    best = max(closed, key=lambda t: t.get('realized_pnl', 0))
    worst = min(closed, key=lambda t: t.get('realized_pnl', 0))
    lines.append(f'   Best: {best[\"symbol\"]} {fmt(best[\"realized_pnl\"])}')
    lines.append(f'   Worst: {worst[\"symbol\"]} {fmt(worst[\"realized_pnl\"])}')
lines.append('')

# ── Performance Metrics ──
if analytics:
    pf = analytics.get('profit_factor', 0)
    md = analytics.get('max_drawdown', 0)
    sr = analytics.get('sharpe_ratio', 0)
    aw = analytics.get('avg_win', 0)
    al = analytics.get('avg_loss', 0)
    wr = analytics.get('win_rate', 0)
    lines.append(f'📈 <b>Performance</b>')
    lines.append(f'   Win Rate: {wr:.1f}% | PF: {pf:.2f}')
    lines.append(f'   Avg Win: {fmt(aw)} | Avg Loss: {fmt(al)}')
    lines.append(f'   Max DD: {md:.2f}% | Sharpe: {sr:.2f}')
    lines.append('')

# ── Open Positions ──
if positions:
    total_unrealized = sum(p.get('unrealized_pnl', 0) for p in positions)
    total_notional = sum(p.get('notional_value', 0) for p in positions)

    lines.append(f'🔓 <b>Open Positions</b> ({len(positions)})')
    lines.append('')

    for p in positions:
        symbol = p.get('symbol', '?')
        side = p.get('side', '?').upper()
        entry = p.get('entry_price', 0)
        current = p.get('current_price', 0)
        qty = p.get('quantity', 0)
        pnl = p.get('unrealized_pnl', 0)
        pnl_pct = p.get('pnl_pct', 0)
        notional = p.get('notional_value', 0)
        margin = p.get('margin_used', 0)
        leverage = p.get('leverage', 1)
        strategy = p.get('strategy_name', '')

        emoji = '🟢' if pnl >= 0 else '🔴'
        side_emoji = '📈' if side == 'LONG' else '📉'

        lines.append(f'{side_emoji} <b>{symbol}</b> {side} {leverage}x')
        lines.append(f'   Entry: \${entry:,.2f} → Now: \${current:,.2f}')
        lines.append(f'   Qty: {qty:.4f} | Margin: \${margin:,.2f}')
        lines.append(f'   {emoji} P&L: {fmt(pnl)} ({sign(pnl_pct)}{pnl_pct:.2f}%)')
        if strategy:
            lines.append(f'   Strategy: {strategy}')
        lines.append('')

    u_emoji = '🟢' if total_unrealized >= 0 else '🔴'
    lines.append(f'━━━━━━━━━━━━━━━━━━━━')
    lines.append(f'{u_emoji} <b>Unrealized: {fmt(total_unrealized)}</b>')
    lines.append(f'💰 Notional: \${total_notional:,.2f}')
else:
    lines.append('🔓 <b>Open Positions</b>: None')

send('\n'.join(lines))
" > /dev/null 2>&1 &
}

restart_all_services() {
  log INFO "Telegram /restart — restarting all services..."

  kill_pid "backend"
  kill_pid "frontend"
  kill_pid "ngrok"
  sleep 2

  start_backend
  start_frontend
  start_ngrok
}

handle_telegram_command() {
  local cmd="$1"
  local chat_id="$2"

  case "$cmd" in
    /status)
      log INFO "Telegram command: /status from $chat_id"
      local status_msg
      status_msg=$(build_status_message)
      send_telegram "$status_msg"
      ;;
    /stop)
      log INFO "Telegram command: /stop from $chat_id"
      send_telegram "🛑 <b>HyperTrader Watchdog</b>%0A%0AStopping all services..."
      # Small delay so the message sends before shutdown
      sleep 2
      shutdown
      ;;
    /restart)
      log INFO "Telegram command: /restart from $chat_id"
      send_telegram "🔄 <b>HyperTrader Watchdog</b>%0A%0ARestarting all services..."
      restart_all_services
      send_telegram "✅ <b>HyperTrader Watchdog</b>%0A%0AAll services restarted%0AWebhook: ${NGROK_URL}/api/webhook"
      ;;
    /trades)
      log INFO "Telegram command: /trades from $chat_id"
      send_trades_snapshot
      ;;
    /help)
      log INFO "Telegram command: /help from $chat_id"
      send_telegram "🤖 <b>HyperTrader Commands</b>%0A%0A/status — Service status & uptime%0A/trades — Open positions & P&L%0A/restart — Restart all services%0A/stop — Stop watchdog & all services%0A/help — Show this message"
      ;;
    *)
      # Ignore unknown commands silently
      ;;
  esac
}

poll_telegram_commands() {
  # Skip if Telegram not configured
  if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    return 0
  fi

  # Read current offset
  local offset=0
  if [ -f "$TELEGRAM_OFFSET_FILE" ]; then
    offset=$(cat "$TELEGRAM_OFFSET_FILE" 2>/dev/null || echo 0)
  fi

  # Poll getUpdates (non-blocking, timeout=0)
  local response
  response=$(curl -s --max-time 5 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?offset=${offset}&timeout=0" \
    2>/dev/null || echo "")

  if [ -z "$response" ]; then
    return 0
  fi

  # Parse updates with python — extract (update_id, chat_id, command) tuples
  local updates
  updates=$(echo "$response" | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if not data.get('ok'):
        sys.exit(0)
    for u in data.get('result', []):
        uid = u['update_id']
        msg = u.get('message', {})
        chat_id = str(msg.get('chat', {}).get('id', ''))
        text = msg.get('text', '').strip().split()[0].split('@')[0] if msg.get('text') else ''
        if chat_id and text.startswith('/'):
            print(f'{uid}|{chat_id}|{text}')
        else:
            print(f'{uid}||')
except:
    pass
" 2>/dev/null || echo "")

  if [ -z "$updates" ]; then
    return 0
  fi

  local max_uid="$offset"

  while IFS='|' read -r uid chat_id cmd; do
    [ -z "$uid" ] && continue

    # Track highest update_id
    local next_uid=$((uid + 1))
    if [ "$next_uid" -gt "$max_uid" ]; then
      max_uid="$next_uid"
    fi

    # Skip if no command or wrong chat
    [ -z "$cmd" ] && continue

    # Security: only process commands from authorized chat_id
    if [ "$chat_id" != "$TELEGRAM_CHAT_ID" ]; then
      log WARN "Telegram command from unauthorized chat_id: $chat_id (ignored)"
      continue
    fi

    handle_telegram_command "$cmd" "$chat_id"
  done <<< "$updates"

  # Save new offset
  if [ "$max_uid" -gt "$offset" ]; then
    echo "$max_uid" > "$TELEGRAM_OFFSET_FILE"
  fi
}

# ─── PID Management ─────────────────────────────────────────────────────────────

mkdir -p "$PIDS_DIR"

save_pid() {
  local name="$1" pid="$2"
  echo "$pid" > "$PIDS_DIR/${name}.pid"
}

read_pid() {
  local name="$1"
  local pidfile="$PIDS_DIR/${name}.pid"
  if [ -f "$pidfile" ]; then
    cat "$pidfile"
  else
    echo ""
  fi
}

is_running() {
  local pid="$1"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  return 1
}

kill_pid() {
  local name="$1"
  local pid
  pid=$(read_pid "$name")
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    # Also kill child processes
    pkill -P "$pid" 2>/dev/null || true
    sleep 1
    # Force kill if still running
    kill -9 "$pid" 2>/dev/null || true
    pkill -9 -P "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDS_DIR/${name}.pid"
}

# ─── Port cleanup ───────────────────────────────────────────────────────────────

kill_port() {
  local port="$1"
  local pids=""
  # Use netstat on Windows (lsof unreliable under MSYS2)
  pids=$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTEN | awk '{print $5}' | sort -u || true)
  if [ -z "$pids" ]; then
    # Fallback to lsof for non-Windows
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
  fi
  if [ -n "$pids" ]; then
    for pid in $pids; do
      (taskkill //PID "$pid" //F > /dev/null 2>&1 || kill -9 "$pid" 2>/dev/null) || true
      log INFO "Killed process on port $port (PID: $pid)"
    done
    sleep 1
  fi
  return 0
}

# ─── Service Start Functions ────────────────────────────────────────────────────

start_backend() {
  log START "Starting backend..."
  kill_port 8000

  cd "$DIR/backend"
  if [ ! -f .env ]; then
    cp .env.example .env
    log INFO "Created backend .env from .env.example"
  fi

  if [ ! -d "venv" ]; then
    log INFO "Creating virtual environment..."
    python -m venv venv
  fi

  source venv/Scripts/activate 2>/dev/null || source venv/bin/activate 2>/dev/null

  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload >> "$LOG_FILE" 2>&1 &
  local pid=$!
  save_pid "backend" "$pid"
  BACKEND_STARTED=$(date +%s)
  BACKEND_FAILS=0

  # Wait for backend to respond
  log INFO "Waiting for backend health check..."
  local ready=false
  for i in $(seq 1 20); do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done

  if $ready; then
    log INFO "Backend ready on http://localhost:8000 (PID: $pid)"
  else
    log WARN "Backend started but health check not responding yet (PID: $pid)"
  fi

  cd "$DIR"
}

start_frontend() {
  log START "Starting frontend..."
  kill_port 3000

  cd "$DIR/frontend"
  if [ ! -d "node_modules" ]; then
    log INFO "Installing frontend dependencies..."
    npm install
  fi

  npm run dev >> "$LOG_FILE" 2>&1 &
  local pid=$!
  save_pid "frontend" "$pid"
  FRONTEND_STARTED=$(date +%s)
  FRONTEND_FAILS=0

  log INFO "Frontend starting on http://localhost:3000 (PID: $pid)"
  cd "$DIR"
}

start_ngrok() {
  log START "Starting ngrok..."
  kill_port 4040

  if ! command -v ngrok &> /dev/null; then
    log ERROR "ngrok not found — install it from https://ngrok.com"
    return 1
  fi

  ngrok http 8000 --log=stdout >> "$LOG_FILE" 2>&1 &
  local pid=$!
  save_pid "ngrok" "$pid"
  NGROK_STARTED=$(date +%s)
  NGROK_FAILS=0

  # Wait for ngrok API to be available
  sleep 3
  fetch_ngrok_url

  log INFO "ngrok running (PID: $pid) — tunnel: $NGROK_URL"
}

fetch_ngrok_url() {
  NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python -c "import sys,json; tunnels=json.load(sys.stdin).get('tunnels',[]); print(tunnels[0]['public_url'] if tunnels else 'unavailable')" 2>/dev/null \
    || echo "unavailable")
}

# ─── Health Checks ──────────────────────────────────────────────────────────────

check_backend() {
  local now
  now=$(date +%s)
  local elapsed=$((now - BACKEND_STARTED))
  if [ "$elapsed" -lt "$GRACE_PERIOD" ]; then
    return 0
  fi

  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    BACKEND_FAILS=0
    return 0
  else
    BACKEND_FAILS=$((BACKEND_FAILS + 1))
    log WARN "Backend health check failed ($BACKEND_FAILS/$FAIL_THRESHOLD)"
    if [ "$BACKEND_FAILS" -ge "$FAIL_THRESHOLD" ]; then
      return 1
    fi
    return 0
  fi
}

check_frontend() {
  local now
  now=$(date +%s)
  local elapsed=$((now - FRONTEND_STARTED))
  if [ "$elapsed" -lt "$GRACE_PERIOD" ]; then
    return 0
  fi

  if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    FRONTEND_FAILS=0
    return 0
  else
    FRONTEND_FAILS=$((FRONTEND_FAILS + 1))
    log WARN "Frontend health check failed ($FRONTEND_FAILS/$FAIL_THRESHOLD)"
    if [ "$FRONTEND_FAILS" -ge "$FAIL_THRESHOLD" ]; then
      return 1
    fi
    return 0
  fi
}

check_ngrok() {
  local now
  now=$(date +%s)
  local elapsed=$((now - NGROK_STARTED))
  if [ "$elapsed" -lt "$GRACE_PERIOD" ]; then
    return 0
  fi

  local tunnels
  tunnels=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null || echo "")
  if [ -n "$tunnels" ] && echo "$tunnels" | python -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); exit(0 if t else 1)" 2>/dev/null; then
    NGROK_FAILS=0
    return 0
  else
    NGROK_FAILS=$((NGROK_FAILS + 1))
    log WARN "ngrok health check failed ($NGROK_FAILS/$FAIL_THRESHOLD)"
    if [ "$NGROK_FAILS" -ge "$FAIL_THRESHOLD" ]; then
      return 1
    fi
    return 0
  fi
}

# ─── Restart Logic ──────────────────────────────────────────────────────────────

restart_backend() {
  log ERROR "Backend is DOWN — restarting..."
  send_telegram "⚠️ <b>HyperTrader Watchdog</b>%0A%0ABackend is DOWN — auto-restarting..."
  kill_pid "backend"
  sleep 2
  start_backend
  send_telegram "✅ <b>HyperTrader Watchdog</b>%0A%0ABackend restarted successfully"
}

restart_frontend() {
  log ERROR "Frontend is DOWN — restarting..."
  send_telegram "⚠️ <b>HyperTrader Watchdog</b>%0A%0AFrontend is DOWN — auto-restarting..."
  kill_pid "frontend"
  sleep 2
  start_frontend
  send_telegram "✅ <b>HyperTrader Watchdog</b>%0A%0AFrontend restarted successfully"
}

restart_ngrok() {
  log ERROR "ngrok is DOWN — restarting..."
  send_telegram "⚠️ <b>HyperTrader Watchdog</b>%0A%0Angrok is DOWN — auto-restarting..."
  kill_pid "ngrok"
  sleep 2
  start_ngrok
  send_telegram "✅ <b>HyperTrader Watchdog</b>%0A%0Angrok restarted — new URL: $NGROK_URL"
}

# ─── Shutdown ────────────────────────────────────────────────────────────────────

shutdown() {
  echo ""
  log INFO "Shutting down HyperTrader..."
  send_telegram "🛑 <b>HyperTrader Watchdog</b>%0A%0AWatchdog stopped — all services shutting down"

  kill_pid "ngrok"
  kill_pid "frontend"
  kill_pid "backend"

  # Clean up PID files
  rm -rf "$PIDS_DIR"

  log INFO "All services stopped. Goodbye!"
  exit 0
}

trap shutdown INT TERM

# ─── Main ────────────────────────────────────────────────────────────────────────

main() {
  echo ""
  echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${CYAN}║    HyperTrader Watchdog v1.0             ║${NC}"
  echo -e "${BOLD}${CYAN}║    Auto-restart service monitor           ║${NC}"
  echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${NC}"
  echo ""

  rotate_log
  log INFO "Watchdog starting..."

  # Load Telegram config from backend/.env (non-fatal if missing)
  load_telegram_config || true

  # Clean up stale processes
  log INFO "Cleaning up stale processes..."
  for port in 8000 3000 4040; do
    kill_port "$port"
  done
  sleep 1

  # Start all services
  start_backend
  start_frontend
  start_ngrok

  # Print status banner
  echo ""
  echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${GREEN}║    HyperTrader is running!               ║${NC}"
  echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║${NC}  Dashboard:  ${CYAN}http://localhost:3000${NC}"
  echo -e "${GREEN}║${NC}  API:        ${CYAN}http://localhost:8000${NC}"
  echo -e "${GREEN}║${NC}  API Docs:   ${CYAN}http://localhost:8000/docs${NC}"
  echo -e "${GREEN}║${NC}  Webhook:    ${CYAN}${NGROK_URL}/api/webhook${NC}"
  echo -e "${GREEN}║${NC}  ngrok UI:   ${CYAN}http://127.0.0.1:4040${NC}"
  echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════╣${NC}"
  echo -e "${GREEN}║${NC}  ${YELLOW}Watchdog active — checking every ${CHECK_INTERVAL}s${NC}"
  echo -e "${GREEN}║${NC}  ${YELLOW}Press Ctrl+C to stop all services${NC}"
  echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${NC}"
  echo ""

  # Send startup Telegram alert
  send_telegram "🚀 <b>HyperTrader Watchdog</b>%0A%0AAll services started%0AWebhook: ${NGROK_URL}/api/webhook%0AMonitoring every ${CHECK_INTERVAL}s"

  # ─── Health check loop ──────────────────────────────────────────────────────

  while true; do
    sleep "$CHECK_INTERVAL"
    rotate_log

    # Check and restart each service
    if ! check_backend; then
      restart_backend
    fi

    if ! check_frontend; then
      restart_frontend
    fi

    if ! check_ngrok; then
      restart_ngrok
    fi

    # Poll for Telegram bot commands
    poll_telegram_commands
  done
}

main "$@"
