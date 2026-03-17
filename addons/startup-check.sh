#!/bin/bash
# HyperTrader Startup Health Check
# Runs after reboot, checks all services, retries failures, sends Telegram status.

set -uo pipefail

DB_FILE="/opt/hypertrader/hypertrader.db"
SERVICES=(
    "hypertrader-backend:Backend"
    "hypertrader-frontend:Frontend"
    "hypertrader-mobile:Mobile App"
    "hypertrader-reconciler:Reconciler"
    "hypertrader-telegram-commander:Telegram Commander"
    "nginx:Nginx"
    "hypertrader-health-check.timer:Health Check Timer"
    "hypertrader-hourly-report.timer:Hourly Report Timer"
    "hypertrader-auto-deploy.timer:Auto Deploy Timer"
)

# Load Telegram creds from DB
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
if [ -f "$DB_FILE" ]; then
    creds=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('$DB_FILE')
    row = conn.execute('SELECT telegram_bot_token, telegram_chat_id FROM app_settings WHERE id=1').fetchone()
    conn.close()
    if row and row[0] and row[1]: print(f'{row[0]}|{row[1]}')
except: pass
" 2>/dev/null || echo "")
    if [ -n "$creds" ]; then
        TELEGRAM_BOT_TOKEN="${creds%%|*}"
        TELEGRAM_CHAT_ID="${creds##*|}"
    fi
fi

send_telegram() {
    local msg="$1"
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -H "Content-Type: application/json" \
            -d "{\"chat_id\": \"${TELEGRAM_CHAT_ID}\", \"text\": \"${msg}\"}" \
            > /dev/null 2>&1 || true
    fi
}

FAILURES=0
RESULTS=()

for entry in "${SERVICES[@]}"; do
    svc="${entry%%:*}"
    label="${entry##*:}"
    status=$(systemctl is-active "$svc" 2>/dev/null)

    if [ "$status" = "active" ]; then
        RESULTS+=("✅ $label")
    else
        # Attempt restart
        sudo systemctl restart "$svc" 2>/dev/null
        sleep 3
        status=$(systemctl is-active "$svc" 2>/dev/null)
        if [ "$status" = "active" ]; then
            RESULTS+=("✅ $label (restarted)")
        else
            RESULTS+=("❌ $label — $status")
            FAILURES=$((FAILURES + 1))
        fi
    fi
done

# Build message
BOOT_TIME=$(uptime -s 2>/dev/null || date)
if [ "$FAILURES" -eq 0 ]; then
    MSG="🔄 Server rebooted (${BOOT_TIME})\n\nService status:\n"
    for r in "${RESULTS[@]}"; do
        MSG="${MSG}${r}\n"
    done
    MSG="${MSG}\nAll systems operational."
else
    MSG="⚠️ Server rebooted (${BOOT_TIME})\nIssues detected:\n\n"
    for r in "${RESULTS[@]}"; do
        MSG="${MSG}${r}\n"
    done
    MSG="${MSG}\n${FAILURES} service(s) failed."
fi

send_telegram "$MSG"
echo "$MSG"
