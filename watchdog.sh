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

  # Check trading pause state
  local pause_status="▶️ TRADING"
  local db_win_path
  db_win_path=$(cygpath -w "$DB_FILE" 2>/dev/null || echo "$DB_FILE")
  local paused_val
  paused_val=$(python -c "
import sqlite3
try:
    conn = sqlite3.connect(r'$db_win_path')
    row = conn.execute('SELECT trading_paused FROM app_settings WHERE id=1').fetchone()
    conn.close()
    print(row[0] if row else 0)
except:
    print(0)
" 2>/dev/null || echo "0")
  if [ "$paused_val" = "1" ] || [ "$paused_val" = "True" ]; then
    pause_status="⏸ PAUSED"
  fi

  local uptime_str
  uptime_str=$(format_uptime "$uptime")

  echo "📊 <b>HyperTrader Status</b>%0A%0A"\
"Backend:  ${be_status}%0A"\
"Frontend: ${fe_status}%0A"\
"ngrok:    ${ng_status}%0A"\
"Trading:  ${pause_status}%0A%0A"\
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

now = datetime.now(timezone.utc)

portfolio = fetch('/live/portfolio')
positions = fetch('/live/positions') or []
fills = fetch('/live/fills') or []

if portfolio is None:
    send('📋 <b>HyperTrader Live</b>\n\n⚠️ Cannot reach Hyperliquid')
    exit()

lines = ['📋 <b>HyperTrader Live Snapshot</b>']
lines.append(f'🕐 {now.strftime(\"%b %d, %H:%M\")} UTC')
lines.append('')

# ── Portfolio ──
acct = portfolio.get('account_value', 0)
perps = portfolio.get('perps_balance', 0)
spot = portfolio.get('spot_balance', 0)
available = portfolio.get('available_balance', 0)
margin_used = portfolio.get('total_margin_used', 0)
total_upnl = portfolio.get('total_unrealized_pnl', 0)

lines.append(f'💼 <b>Portfolio</b> (LIVE)')
lines.append(f'   Total Value: \${acct:,.2f}')
lines.append(f'   Perps: \${perps:,.2f} | Spot: \${spot:,.2f}')
lines.append(f'   Available: \${available:,.2f}')
lines.append(f'   Margin Used: \${margin_used:,.2f}')
upnl_emoji = '🟢' if total_upnl >= 0 else '🔴'
lines.append(f'   {upnl_emoji} Unrealized: {fmt(total_upnl)}')
lines.append('')

# ── Recent Fills (last 24h) ──
cutoff = int((now - timedelta(hours=24)).timestamp() * 1000)
recent = [f for f in fills if f.get('time', 0) >= cutoff]
if recent:
    total_closed = sum(f.get('closed_pnl', 0) for f in recent)
    total_fees = sum(f.get('fee', 0) for f in recent)
    lines.append(f'📊 <b>24h Fills</b> ({len(recent)})')
    lines.append(f'   Closed P&L: {fmt(total_closed)}')
    lines.append(f'   Fees: \${total_fees:,.2f}')
    lines.append('')
else:
    lines.append(f'📊 <b>24h Fills</b>: None')
    lines.append('')

# ── Open Positions ──
if positions:
    lines.append(f'🔓 <b>Open Positions</b> ({len(positions)})')
    lines.append('')

    for p in positions:
        symbol = p.get('symbol', '?')
        side = p.get('side', '?').upper()
        entry = p.get('entry_price', 0)
        mark = p.get('mark_price', 0)
        size = p.get('size', 0)
        pnl = p.get('unrealized_pnl', 0)
        margin = p.get('margin_used', 0)
        leverage = p.get('leverage', 1)
        notional = p.get('notional', 0)
        pnl_pct = (pnl / margin * 100) if margin > 0 else 0

        emoji = '🟢' if pnl >= 0 else '🔴'
        side_emoji = '📈' if side == 'LONG' else '📉'

        lines.append(f'{side_emoji} <b>{symbol}</b> {side} {leverage:.0f}x')
        lines.append(f'   Entry: \${entry:,.2f} → Mark: \${mark:,.2f}')
        lines.append(f'   Size: {size} | Margin: \${margin:,.2f}')
        lines.append(f'   {emoji} P&L: {fmt(pnl)} ({sign(pnl_pct)}{pnl_pct:.2f}%)')
        lines.append('')

    lines.append(f'━━━━━━━━━━━━━━━━━━━━')
    u_emoji = '🟢' if total_upnl >= 0 else '🔴'
    lines.append(f'{u_emoji} <b>Unrealized: {fmt(total_upnl)}</b>')
    total_notional = sum(p.get('notional', 0) for p in positions)
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
    /pause)
      log INFO "Telegram command: /pause from $chat_id"
      local pause_result
      pause_result=$(curl -s -X PATCH http://localhost:8000/api/settings \
        -H "Content-Type: application/json" \
        -d '{"trading_paused": true}' 2>/dev/null || echo "")
      if [ -n "$pause_result" ]; then
        send_telegram "⏸ <b>Trading PAUSED</b>%0A%0AAll incoming webhook signals will be blocked until you /unpause"
      else
        send_telegram "⚠️ Failed to pause — backend may be down"
      fi
      ;;
    /unpause)
      log INFO "Telegram command: /unpause from $chat_id"
      local unpause_result
      unpause_result=$(curl -s -X PATCH http://localhost:8000/api/settings \
        -H "Content-Type: application/json" \
        -d '{"trading_paused": false}' 2>/dev/null || echo "")
      if [ -n "$unpause_result" ]; then
        send_telegram "▶️ <b>Trading RESUMED</b>%0A%0AWebhook signals will be processed normally"
      else
        send_telegram "⚠️ Failed to unpause — backend may be down"
      fi
      ;;
    /close*)
      log INFO "Telegram command: $cmd from $chat_id"
      # Extract symbol argument (e.g. /close BTC or /close all)
      local close_arg
      close_arg=$(echo "$cmd" | sed 's|^/close[[:space:]]*||' | tr '[:lower:]' '[:upper:]' | xargs)
      if [ -z "$close_arg" ]; then
        send_telegram "⚠️ <b>Usage:</b> /close BTC or /close ALL"
      elif [ "$close_arg" = "ALL" ]; then
        log INFO "Closing ALL live positions via Telegram"
        # Fetch all positions and close each
        local positions_json
        positions_json=$(curl -s --max-time 10 http://localhost:8000/api/live/positions 2>/dev/null || echo "[]")
        local count
        count=$(echo "$positions_json" | python -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
        if [ "$count" = "0" ]; then
          send_telegram "ℹ️ No open positions to close"
        else
          send_telegram "🔄 Closing $count position(s)..."
          local close_results=""
          for symbol in $(echo "$positions_json" | python -c "import sys,json; [print(p['symbol']) for p in json.load(sys.stdin)]" 2>/dev/null); do
            local result
            result=$(curl -s --max-time 30 -X POST "http://localhost:8000/api/live/positions/${symbol}/close" 2>/dev/null || echo '{"success":false,"message":"Request failed"}')
            local success
            success=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('success',False))" 2>/dev/null || echo "False")
            local msg
            msg=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('message',''))" 2>/dev/null || echo "Unknown error")
            if [ "$success" = "True" ]; then
              close_results="${close_results}✅ ${symbol}: ${msg}%0A"
            else
              close_results="${close_results}❌ ${symbol}: ${msg}%0A"
            fi
          done
          send_telegram "📊 <b>Close Results</b>%0A%0A${close_results}"
        fi
      else
        log INFO "Closing $close_arg position via Telegram"
        local result
        result=$(curl -s --max-time 30 -X POST "http://localhost:8000/api/live/positions/${close_arg}/close" 2>/dev/null || echo '{"success":false,"message":"Request failed"}')
        local success
        success=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('success',False))" 2>/dev/null || echo "False")
        local msg
        msg=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('message',''))" 2>/dev/null || echo "Unknown error")
        if [ "$success" = "True" ]; then
          send_telegram "✅ <b>Position Closed</b>%0A%0A${msg}"
        else
          send_telegram "❌ <b>Close Failed</b>%0A%0A${msg}"
        fi
      fi
      ;;
    /help)
      log INFO "Telegram command: /help from $chat_id"
      send_telegram "🤖 <b>HyperTrader Commands</b>%0A%0A/status — Service status & uptime%0A/trades — Open positions & P&L%0A/close BTC — Close a specific position%0A/close all — Close all positions%0A/pause — Pause all trading (block webhooks)%0A/unpause — Resume trading%0A/restart — Restart all services%0A/stop — Stop watchdog & all services%0A/help — Show this message"
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
        raw = msg.get('text', '').strip() if msg.get('text') else ''
        cmd = raw.split()[0].split('@')[0] if raw else ''
        text = raw if raw else ''
        if chat_id and cmd.startswith('/'):
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
  kill_pid "backend"
  sleep 2
  start_backend
}

restart_frontend() {
  log ERROR "Frontend is DOWN — restarting..."
  kill_pid "frontend"
  sleep 2
  start_frontend
}

restart_ngrok() {
  log ERROR "ngrok is DOWN — restarting..."
  kill_pid "ngrok"
  sleep 2
  start_ngrok
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

    # Check and restart services, collect results for a single alert
    local restarted=""

    if ! check_backend; then
      restart_backend
      restarted="${restarted}Backend "
    fi

    if ! check_frontend; then
      restart_frontend
      restarted="${restarted}Frontend "
    fi

    if ! check_ngrok; then
      restart_ngrok
      fetch_ngrok_url
      restarted="${restarted}ngrok "
    fi

    # Send one combined alert if anything restarted
    if [ -n "$restarted" ]; then
      send_telegram "🔄 <b>HyperTrader Watchdog</b>%0A%0ARestarted: ${restarted}%0AWebhook: ${NGROK_URL}/api/webhook"
    fi

    # Poll for Telegram bot commands
    poll_telegram_commands
  done
}

main "$@"
