#!/bin/bash
# HyperTrader Master Health Check (Linux/systemd version)
# Checks all services and optionally sends Telegram alerts for failures
# Usage: bash addons/health-check.sh [--scheduled]
#   --scheduled: suppress stdout, only alert on failures

set -uo pipefail
export PYTHONIOENCODING=utf-8

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_FILE="$DIR/hypertrader.db"
LOG_FILE="$SCRIPT_DIR/health-check.log"

SCHEDULED=false
for arg in "$@"; do
  case "$arg" in
    --scheduled) SCHEDULED=true ;;
  esac
done

# ─── Telegram ─────────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""

load_telegram_config() {
  # Try .env.addons first
  if [ -f "$SCRIPT_DIR/.env.addons" ]; then
    TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$SCRIPT_DIR/.env.addons" | cut -d= -f2- | tr -d '"' | tr -d "'")
    TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' "$SCRIPT_DIR/.env.addons" | cut -d= -f2- | tr -d '"' | tr -d "'")
  fi
  # Fallback to database
  if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -f "$DB_FILE" ]; then
    local creds
    creds=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('$DB_FILE')
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
}

send_telegram() {
  local msg="$1"
  if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -H "Content-Type: application/json" \
      -d "{\"chat_id\": \"${TELEGRAM_CHAT_ID}\", \"text\": \"${msg}\", \"parse_mode\": \"HTML\"}" \
      > /dev/null 2>&1 || true
  fi
}

# ─── Check Functions ──────────────────────────────────────────────────────────────

RESULTS=()
FAILURES=0

check_service() {
  local name="$1"
  local status="$2"
  local detail="$3"

  if [ "$status" = "UP" ]; then
    RESULTS+=("$(printf '%-22s  ✅ %-6s  %s' "$name" "$status" "$detail")")
  else
    RESULTS+=("$(printf '%-22s  ❌ %-6s  %s' "$name" "$status" "$detail")")
    FAILURES=$((FAILURES + 1))
  fi
}

check_systemd_service() {
  local svc_name="$1"
  local display_name="$2"
  local active
  active=$(systemctl is-active "$svc_name" 2>/dev/null || echo "inactive")
  if [ "$active" = "active" ]; then
    check_service "$display_name" "UP" "systemd: active"
  else
    check_service "$display_name" "DOWN" "systemd: $active"
  fi
}

check_backend() {
  local response
  response=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:8000/api/status 2>/dev/null || echo "000")
  if [ "$response" = "200" ]; then
    local mode
    mode=$(curl -s --max-time 3 http://localhost:8000/api/status 2>/dev/null | python3 -c "
import sys, json
try: print(json.load(sys.stdin).get('settings',{}).get('trading_mode','?'))
except: print('?')
" 2>/dev/null || echo "?")
    check_service "Backend (8000)" "UP" "HTTP 200, mode: $mode"
  else
    check_service "Backend (8000)" "DOWN" "HTTP $response"
  fi
}

check_frontend() {
  local response
  response=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null || echo "000")
  if [ "$response" = "200" ]; then
    check_service "Frontend (3000)" "UP" "HTTP 200"
  else
    check_service "Frontend (3000)" "DOWN" "HTTP $response"
  fi
}

check_mobile() {
  local response
  response=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:3002/mobile/welcome 2>/dev/null || echo "000")
  if [ "$response" = "200" ]; then
    check_service "Mobile App (/mobile)" "UP" "HTTP 200"
  else
    check_service "Mobile App (/mobile)" "DOWN" "HTTP $response"
  fi
}

check_reconciler() {
  check_systemd_service "hypertrader-reconciler" "State Reconciler"
}

check_hyperliquid() {
  local http_code
  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 10 -X POST \
    -H "Content-Type: application/json" \
    -d '{"type":"allMids"}' \
    https://api.hyperliquid.xyz/info 2>/dev/null || echo "000")
  if [ "$http_code" = "200" ]; then
    check_service "Hyperliquid API" "UP" "HTTP 200 — API reachable"
  elif [ "$http_code" = "403" ]; then
    check_service "Hyperliquid API" "DOWN" "HTTP 403 — blocked"
  else
    check_service "Hyperliquid API" "DOWN" "HTTP $http_code"
  fi
}

check_nginx() {
  local active
  active=$(systemctl is-active nginx 2>/dev/null || echo "inactive")
  if [ "$active" = "active" ]; then
    check_service "Nginx" "UP" "systemd: active"
  else
    check_service "Nginx" "DOWN" "systemd: $active"
  fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────────

main() {
  load_telegram_config || true

  check_backend
  check_frontend
  check_mobile
  check_reconciler
  check_nginx
  check_hyperliquid

  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"

  # Build output
  local header="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  local title="  HyperTrader Health Check — $ts"

  if [ "$SCHEDULED" = false ]; then
    echo "$header"
    echo "$title"
    echo "$header"
    printf '%-22s  %-8s  %s\n' "SERVICE" "STATUS" "DETAILS"
    echo "───────────────────────────────────────────────────"
    for line in "${RESULTS[@]}"; do
      echo "$line"
    done
    echo "$header"
    if [ "$FAILURES" -gt 0 ]; then
      echo "  ⚠️  $FAILURES service(s) DOWN"
    else
      echo "  ✅  All services healthy"
    fi
    echo "$header"
  fi

  # Log
  echo "[$ts] Failures: $FAILURES" >> "$LOG_FILE"

  # Alert on failures (scheduled mode only)
  if [ "$FAILURES" -gt 0 ] && [ "$SCHEDULED" = true ]; then
    local alert_msg="━━━━━━━━━━━━━━━━━━━━\n  ⚠️  <b>HEALTH CHECK ALERT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for line in "${RESULTS[@]}"; do
      if echo "$line" | grep -q "❌"; then
        alert_msg="${alert_msg}${line}\n"
      fi
    done
    alert_msg="${alert_msg}\n${FAILURES} service(s) down\n━━━━━━━━━━━━━━━━━━━━"
    send_telegram "$alert_msg"
  fi

  return $FAILURES
}

main "$@" || true
