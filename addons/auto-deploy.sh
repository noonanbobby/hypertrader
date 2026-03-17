#!/bin/bash
# HyperTrader Auto-Deploy — Upstream Sync System
# Keeps local fork synced with upstream hpombo1337/hypertrader
# Auto-deploys when safe (no open positions), rolls back on failure
# Usage: bash addons/auto-deploy.sh [--check|--dry-run|--force]

set -euo pipefail
export PYTHONIOENCODING=utf-8

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/auto-deploy.log"
LOCK_FILE="$SCRIPT_DIR/.auto-deploy.lock"
DB_FILE="$DIR/backend/hypertrader.db"
LOG_MAX_BYTES=10485760  # 10MB
UPSTREAM_URL="https://github.com/hpombo1337/hypertrader.git"
UPSTREAM_BRANCH="master"

# Flags
FLAG_FORCE=false
FLAG_DRY_RUN=false
FLAG_CHECK=false

# State
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
ORIGINAL_HEAD=""
STASH_CREATED=false
DEPLOY_STARTED=false

# ─── Argument Parsing ────────────────────────────────────────────────────────────

for arg in "$@"; do
  case "$arg" in
    --force)   FLAG_FORCE=true ;;
    --dry-run) FLAG_DRY_RUN=true ;;
    --check)   FLAG_CHECK=true ;;
    *) echo "Unknown flag: $arg"; echo "Usage: auto-deploy.sh [--check|--dry-run|--force]"; exit 1 ;;
  esac
done

# ─── Logging ──────────────────────────────────────────────────────────────────────

log() {
  local level="$1"
  shift
  local msg="$*"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] [$level] $msg"
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

# ─── Telegram ─────────────────────────────────────────────────────────────────────

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
    log WARN "Telegram not configured — notifications disabled"
    return 1
  fi
  return 0
}

send_telegram() {
  local msg="$1"
  if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    python -c "
import urllib.request, json
text = '''$msg'''
data = json.dumps({'chat_id': '$TELEGRAM_CHAT_ID', 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
req = urllib.request.Request('https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage', data=data, headers={'Content-Type': 'application/json'})
try: urllib.request.urlopen(req, timeout=10)
except: pass
" > /dev/null 2>&1 || true
  fi
}

# ─── Lock File ─────────────────────────────────────────────────────────────────────

acquire_lock() {
  if [ -f "$LOCK_FILE" ]; then
    local lock_pid
    lock_pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
      log INFO "Another deploy is running (PID: $lock_pid) — exiting"
      exit 0
    fi
    log WARN "Removing stale lock (PID: $lock_pid)"
    rm -f "$LOCK_FILE"
  fi
  echo $$ > "$LOCK_FILE"
}

release_lock() {
  rm -f "$LOCK_FILE"
}

trap release_lock EXIT

# ─── Port Kill (matches watchdog.sh pattern) ──────────────────────────────────────

kill_port() {
  local port="$1"
  local pids=""
  pids=$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTEN | awk '{print $5}' | sort -u || true)
  if [ -z "$pids" ]; then
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

# ─── Rollback ──────────────────────────────────────────────────────────────────────

rollback() {
  local error_msg="${1:-Unknown error}"
  log ERROR "Rolling back to $ORIGINAL_HEAD — $error_msg"

  cd "$DIR"
  git merge --abort 2>/dev/null || true
  git reset --hard "$ORIGINAL_HEAD" 2>/dev/null || true

  if $STASH_CREATED; then
    git stash pop 2>/dev/null || true
    STASH_CREATED=false
  fi

  send_telegram "$(cat <<EOF
━━━━━━━━━━━━━━━━━━━━
  🚨  DEPLOY FAILED
━━━━━━━━━━━━━━━━━━━━
Error during deployment
Rolled back to previous state

❌  Error: ${error_msg}

Action: check auto-deploy.log
━━━━━━━━━━━━━━━━━━━━
EOF
)"
}

# ─── Upstream Remote ───────────────────────────────────────────────────────────────

ensure_upstream_remote() {
  cd "$DIR"
  if ! git remote get-url upstream > /dev/null 2>&1; then
    log INFO "Adding upstream remote: $UPSTREAM_URL"
    git remote add upstream "$UPSTREAM_URL"
  fi
}

# ─── Position Check ───────────────────────────────────────────────────────────────

get_open_positions() {
  # Returns JSON array of positions, or empty string if backend is down
  curl -s --max-time 10 http://localhost:8000/api/live/positions 2>/dev/null || echo ""
}

count_positions() {
  local positions_json="$1"
  if [ -z "$positions_json" ]; then
    echo "0"
    return
  fi
  python -c "
import sys, json
try:
    positions = json.loads('''$positions_json''')
    print(len(positions))
except:
    print('0')
" 2>/dev/null || echo "0"
}

format_positions_for_telegram() {
  local positions_json="$1"
  python -c "
import sys, json
try:
    positions = json.loads('''$positions_json''')
    for p in positions:
        symbol = p.get('symbol', '?')
        side = p.get('side', '?').upper()
        mark = p.get('mark_price', 0)
        pnl = p.get('unrealized_pnl', 0)
        sign = '+' if pnl >= 0 else ''
        print(f'{symbol} {side}  ·  \${mark:,.0f}  ·  {sign}\${pnl:,.2f}')
except:
    pass
" 2>/dev/null || echo ""
}

# ─── Service Restart ──────────────────────────────────────────────────────────────

restart_services() {
  log INFO "Restarting services (watchdog will auto-recover)..."
  kill_port 8000
  kill_port 3000
  # Watchdog detects services are down and auto-restarts within ~40 seconds
}

# ─── Main Deploy Logic ────────────────────────────────────────────────────────────

main() {
  rotate_log
  acquire_lock

  log INFO "Auto-deploy starting (force=$FLAG_FORCE dry-run=$FLAG_DRY_RUN check=$FLAG_CHECK)"

  # Load Telegram (non-fatal)
  load_telegram_config || true

  # Ensure upstream remote exists
  ensure_upstream_remote

  # Fetch upstream
  log INFO "Fetching upstream/$UPSTREAM_BRANCH..."
  cd "$DIR"
  if ! git fetch upstream "$UPSTREAM_BRANCH" 2>&1; then
    log ERROR "Failed to fetch upstream"
    exit 1
  fi

  # Compare HEAD vs upstream
  local local_head upstream_head
  local_head=$(git rev-parse HEAD)
  upstream_head=$(git rev-parse "upstream/$UPSTREAM_BRANCH")

  if [ "$local_head" = "$upstream_head" ]; then
    log INFO "Up to date with upstream — nothing to do"
    exit 0
  fi

  # Extract pending commits
  local pending_commits
  pending_commits=$(git log --oneline HEAD.."upstream/$UPSTREAM_BRANCH" 2>/dev/null || echo "")
  local commit_count
  commit_count=$(echo "$pending_commits" | grep -c . || echo "0")

  log INFO "$commit_count new commit(s) available from upstream"

  # Format commits for Telegram
  local commits_formatted=""
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    commits_formatted="${commits_formatted}
- ${line}"
  done <<< "$pending_commits"

  # ── Check mode: report and exit ──
  if $FLAG_CHECK; then
    log INFO "Check mode — reporting available updates"
    send_telegram "$(cat <<EOF
━━━━━━━━━━━━━━━━━━━━
  📦  UPDATE AVAILABLE
━━━━━━━━━━━━━━━━━━━━
${commit_count} new commit(s) from upstream

📦  Changes pending:${commits_formatted}
━━━━━━━━━━━━━━━━━━━━
EOF
)"
    exit 0
  fi

  # ── Position check ──
  if ! $FLAG_FORCE; then
    local positions_json
    positions_json=$(get_open_positions)
    local pos_count
    pos_count=$(count_positions "$positions_json")

    if [ "$pos_count" -gt 0 ]; then
      log INFO "Deploy deferred — $pos_count open position(s)"
      local positions_display
      positions_display=$(format_positions_for_telegram "$positions_json")
      send_telegram "$(cat <<EOF
━━━━━━━━━━━━━━━━━━━━
  ⏸  DEPLOY DEFERRED
━━━━━━━━━━━━━━━━━━━━
Upstream update available
Waiting for ${pos_count} open position(s) to close

📦  Changes pending:${commits_formatted}

💰  Open positions:
${positions_display}
━━━━━━━━━━━━━━━━━━━━
EOF
)"
      exit 0
    fi
    # Backend down = no positions = safe to deploy
    if [ -z "$positions_json" ]; then
      log INFO "Backend not responding — treating as no open positions"
    fi
  fi

  # ── Dry-run mode ──
  if $FLAG_DRY_RUN; then
    log INFO "Dry-run mode — would deploy the following:"
    log INFO "Commits: $pending_commits"
    log INFO "Would stash local changes, merge upstream, restart services"
    exit 0
  fi

  # ── Begin deployment ──
  DEPLOY_STARTED=true
  ORIGINAL_HEAD="$local_head"
  log INFO "Deploying upstream changes (from ${local_head:0:7} to ${upstream_head:0:7})..."

  # Check which files will change (for post-deploy dependency install)
  local changed_files
  changed_files=$(git diff --name-only HEAD.."upstream/$UPSTREAM_BRANCH" 2>/dev/null || echo "")
  local needs_pip=false
  local needs_npm=false
  if echo "$changed_files" | grep -q "backend/requirements.txt"; then
    needs_pip=true
  fi
  if echo "$changed_files" | grep -q "frontend/package.json"; then
    needs_npm=true
  fi

  # Protected files check — block if upstream touches locally modified files
  PROTECTED_FILES="backend/app/services/live_trader.py backend/app/services/risk_manager.py backend/app/routers/webhook.py backend/app/models.py backend/app/main.py backend/app/services/notification_service.py backend/app/services/trade_executor.py"

  local conflicting=""
  for f in $PROTECTED_FILES; do
    if echo "$changed_files" | grep -q "$f"; then
      conflicting="${conflicting}${f}\n"
    fi
  done

  if [ -n "$conflicting" ] && ! $FLAG_FORCE; then
    log WARN "Protected file conflict detected"
    send_telegram "$(cat <<EOF
━━━━━━━━━━━━━━━━━━━━
  ⚠️  PROTECTED FILE CONFLICT
━━━━━━━━━━━━━━━━━━━━
Upstream changes touch locally modified files:
$(echo -e "$conflicting")
Auto-deploy BLOCKED.
Review manually then run --force
━━━━━━━━━━━━━━━━━━━━
EOF
)"
    exit 1
  fi

  # Stash local changes (only if working tree is dirty)
  local is_dirty=false
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    is_dirty=true
    log INFO "Stashing local changes..."
    if git stash push -m "auto-deploy-$(date +%s)" 2>&1; then
      STASH_CREATED=true
    else
      rollback "Failed to stash local changes"
      exit 1
    fi
  fi

  # Merge upstream
  log INFO "Merging upstream/$UPSTREAM_BRANCH..."
  if ! git merge "upstream/$UPSTREAM_BRANCH" --no-edit 2>&1; then
    # Merge conflict
    log ERROR "Merge conflict detected"
    git merge --abort 2>/dev/null || true
    git reset --hard "$ORIGINAL_HEAD" 2>/dev/null || true

    if $STASH_CREATED; then
      git stash pop 2>/dev/null || true
      STASH_CREATED=false
    fi

    send_telegram "$(cat <<EOF
━━━━━━━━━━━━━━━━━━━━
  ⚠️  MERGE CONFLICT
━━━━━━━━━━━━━━━━━━━━
Manual intervention required
Repo rolled back to clean state

📦  Conflicting changes:${commits_formatted}

Action: resolve manually then
run auto-deploy.sh --force
━━━━━━━━━━━━━━━━━━━━
EOF
)"
    exit 1
  fi

  # Pop stash
  if $STASH_CREATED; then
    log INFO "Restoring local changes from stash..."
    if ! git stash pop 2>&1; then
      rollback "Failed to restore stashed changes (stash conflict)"
      exit 1
    fi
    STASH_CREATED=false
  fi

  # Push to origin (non-fatal)
  log INFO "Pushing to origin..."
  if ! git push origin "$UPSTREAM_BRANCH" 2>&1; then
    log WARN "Push to origin failed (non-fatal — may not have write access)"
  fi

  # Install dependencies if needed
  local deps_reinstalled="No"

  if $needs_pip; then
    log INFO "requirements.txt changed — reinstalling Python dependencies..."
    cd "$DIR/backend"
    source venv/Scripts/activate 2>/dev/null || source venv/bin/activate 2>/dev/null || true
    pip install -r requirements.txt >> "$LOG_FILE" 2>&1 || log WARN "pip install failed"
    deps_reinstalled="Yes (pip)"
    cd "$DIR"
  fi

  if $needs_npm; then
    log INFO "package.json changed — reinstalling Node dependencies..."
    cd "$DIR/frontend"
    npm install >> "$LOG_FILE" 2>&1 || log WARN "npm install failed"
    deps_reinstalled="Yes (npm)"
    cd "$DIR"
  fi

  if $needs_pip && $needs_npm; then
    deps_reinstalled="Yes (pip + npm)"
  fi

  # Restart services
  restart_services

  log INFO "Deploy complete! Services restarting via watchdog."

  send_telegram "$(cat <<EOF
━━━━━━━━━━━━━━━━━━━━
  ✅  UPDATE DEPLOYED
━━━━━━━━━━━━━━━━━━━━
Upstream merged and live

📦  Changes:${commits_formatted}

🔧  Deps reinstalled: ${deps_reinstalled}
🔄  Services restarted: Yes
━━━━━━━━━━━━━━━━━━━━
EOF
)"
}

main
