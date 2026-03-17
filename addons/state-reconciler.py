#!/usr/bin/env python3
"""
HyperTrader State Reconciler v2 — Tiered position alignment monitor.

THREE TIERS:
  Tier 1 (EMERGENCY):  Position OPPOSITE to signal.  Check every 15s, fire after 2 checks.
  Tier 2 (MISSED ENTRY): No position, signal says enter.  Check every 30s, fire after 3 checks.
  Tier 3 (MONITORING): Aligned or no signal.  Check every 60s, no action.

CRITICAL RULES:
  - NEVER close because filters are blocking.  Only act on clear OPPOSITE signals.
  - NEVER adjust position size.  Only check direction.
  - Rate limit: max 2 corrections per asset per hour, 3-minute cooldown.
  - Always re-fetch position from HL RIGHT BEFORE firing.

Usage: python addons/state-reconciler.py
"""

import json
import logging
import os
import platform
import signal as sig
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DB_FILE = PROJECT_DIR / "hypertrader.db"
ENV_FILE = PROJECT_DIR / "backend" / ".env"
LOG_FILE = PROJECT_DIR / "logs" / "reconciler.log"
LOCK_FILE = SCRIPT_DIR / ".state-reconciler.lock"

# ─── Constants ────────────────────────────────────────────────────────────────────

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
BACKEND_URL = "http://localhost:8000"

# Main loop runs every 15 seconds
MAIN_LOOP_INTERVAL = 15

# Tier check intervals (seconds since last check for this tier)
TIER1_INTERVAL = 15   # Emergency: check every 15s
TIER2_INTERVAL = 30   # Missed entry: check every 30s
TIER3_INTERVAL = 60   # Monitoring: check every 60s

# Confirmation thresholds
TIER1_CONFIRMS = 2    # Fire after 2 consecutive mismatch checks (30s)
TIER2_CONFIRMS = 3    # Fire after 3 consecutive missed-entry checks (90s)

# Rate limiting
MAX_FIRES_PER_HOUR = 2
FIRE_COOLDOWN = 180     # 3 minutes between fires per asset
AMBIGUITY_PCT = 0.3     # Price within 0.3% of ST line

# Config refresh
CONFIG_REFRESH_INTERVAL = 300  # 5 minutes

# Startup
STARTUP_GRACE_SECONDS = 30

# Circuit breaker
API_FAILURE_THRESHOLD = 3
API_RETRY_INTERVAL = 300   # 5 minutes for single asset
API_ALL_FAIL_RETRY = 120   # 2 minutes when all fail


# ─── Per-Asset State ─────────────────────────────────────────────────────────────

@dataclass
class AssetState:
    """Per-asset reconciler state."""
    tier: int = 3
    last_check_time: float = 0.0
    mismatch_count: int = 0
    mismatch_type: str = ""  # "opposite" or "missed_entry"
    last_fire_time: float = 0.0
    fires_this_hour: int = 0
    consecutive_api_failures: int = 0
    api_paused_until: float = 0.0
    last_signal: str = ""     # "long", "short", or "none"
    last_position: str = ""   # "long", "short", or "none"
    checks_this_hour: int = 0
    actions_this_hour: int = 0
    rate_limit_alerted: bool = False


# ─── Logging ──────────────────────────────────────────────────────────────────────

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("reconciler")
log.setLevel(logging.DEBUG)

_handler = RotatingFileHandler(str(LOG_FILE), maxBytes=10_000_000, backupCount=2, encoding="utf-8")
_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
log.addHandler(_handler)

# Only add console handler when running interactively (not under systemd)
if sys.stderr.isatty():
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    log.addHandler(_console)

# ─── State ────────────────────────────────────────────────────────────────────────

startup_time = time.time()
hour_started = 0
last_config_refresh = 0.0
last_summary_time = 0.0
last_hourly_report_hour = -1
cached_configs: list[dict] = []
telegram_bot_token = ""
telegram_chat_id = ""
webhook_secret = ""
shutting_down = False

asset_states: dict[str, AssetState] = {}

# ─── Helpers ──────────────────────────────────────────────────────────────────────


def db_path_for_sqlite() -> str:
    path = str(DB_FILE)
    if platform.system() == "Windows" or "MSYSTEM" in os.environ:
        try:
            result = subprocess.run(["cygpath", "-w", path], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
    return path


def load_telegram_config() -> bool:
    global telegram_bot_token, telegram_chat_id
    try:
        conn = sqlite3.connect(db_path_for_sqlite())
        row = conn.execute("SELECT telegram_bot_token, telegram_chat_id FROM app_settings WHERE id=1").fetchone()
        conn.close()
        if row and row[0] and row[1]:
            telegram_bot_token = row[0]
            telegram_chat_id = row[1]
            return True
    except Exception as e:
        log.warning("Failed to load Telegram config: %s", e)
    return False


def load_webhook_secret() -> bool:
    global webhook_secret
    try:
        text = ENV_FILE.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("WEBHOOK_SECRET="):
                webhook_secret = line.split("=", 1)[1].strip().strip("'\"")
                return bool(webhook_secret)
    except Exception as e:
        log.warning("Failed to load webhook secret: %s", e)
    return False


def send_telegram(msg: str) -> None:
    if not telegram_bot_token or not telegram_chat_id:
        return
    try:
        data = json.dumps({"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


def fmt_price(price: float) -> str:
    return f"${price:,.2f}"


# ─── API Functions ────────────────────────────────────────────────────────────────


def fetch_json(url: str, payload: dict | None = None, timeout: int = 10) -> dict | list | None:
    """Generic JSON fetch."""
    try:
        if payload:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        log.error("Fetch %s failed: %s", url, e)
        return None


def fetch_candles(coin: str = "BTC", interval: str = "15m", count: int = 200) -> list[dict] | None:
    now_ms = int(time.time() * 1000)
    if interval == "15m":
        duration_ms = count * 15 * 60 * 1000
    elif interval == "1h":
        duration_ms = count * 60 * 60 * 1000
    else:
        duration_ms = count * 15 * 60 * 1000
    start_ms = now_ms - duration_ms
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": now_ms},
    }
    result = fetch_json(HL_INFO_URL, payload)
    if result and isinstance(result, list) and len(result) > 0:
        return result
    return None


def fetch_positions() -> list[dict] | None:
    return fetch_json(f"{BACKEND_URL}/api/live/positions")


def fetch_asset_configs() -> list[dict] | None:
    result = fetch_json(f"{BACKEND_URL}/api/assets")
    if result and isinstance(result, list):
        return [a for a in result if a.get("enabled", False)]
    return None


def fetch_trading_paused() -> bool | None:
    result = fetch_json(f"{BACKEND_URL}/api/settings")
    if result:
        return bool(result.get("trading_paused", False))
    return None


# ─── Indicator Calculations ──────────────────────────────────────────────────────


def calc_supertrend(candles: list[dict], period: int = 10, multiplier: float = 2.0) -> tuple[str, float, float] | None:
    if len(candles) < period + 2:
        return None

    highs = [float(c["h"]) for c in candles]
    lows = [float(c["l"]) for c in candles]
    closes = [float(c["c"]) for c in candles]
    n = len(candles)

    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    atr = [0.0] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    upper_band = [0.0] * n
    lower_band = [0.0] * n
    direction = [1] * n

    for i in range(period - 1, n):
        hl2 = (highs[i] + lows[i]) / 2
        basic_upper = hl2 + multiplier * atr[i]
        basic_lower = hl2 - multiplier * atr[i]

        if i == period - 1:
            upper_band[i] = basic_upper
            lower_band[i] = basic_lower
        else:
            upper_band[i] = min(basic_upper, upper_band[i - 1]) if closes[i - 1] <= upper_band[i - 1] else basic_upper
            lower_band[i] = max(basic_lower, lower_band[i - 1]) if closes[i - 1] >= lower_band[i - 1] else basic_lower

        if i == period - 1:
            direction[i] = 1 if closes[i] > upper_band[i] else -1
        else:
            if direction[i - 1] == 1:
                direction[i] = -1 if closes[i] < lower_band[i] else 1
            else:
                direction[i] = 1 if closes[i] > upper_band[i] else -1

    idx = n - 2
    st_val = lower_band[idx] if direction[idx] == 1 else upper_band[idx]
    dir_str = "bullish" if direction[idx] == 1 else "bearish"
    return dir_str, st_val, closes[idx]


def calc_adx_values(candles: list[dict], period: int = 14) -> tuple[float, float] | None:
    if len(candles) < period * 2 + 3:
        return None

    highs = [float(c["h"]) for c in candles]
    lows = [float(c["l"]) for c in candles]
    closes = [float(c["c"]) for c in candles]
    n = len(candles)

    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    def rma_smooth(data, p):
        out = [0.0] * len(data)
        out[p] = sum(data[1:p + 1])
        for i in range(p + 1, len(data)):
            out[i] = out[i - 1] - out[i - 1] / p + data[i]
        return out

    s_tr = rma_smooth(tr, period)
    s_pdm = rma_smooth(plus_dm, period)
    s_mdm = rma_smooth(minus_dm, period)

    dx = [0.0] * n
    for i in range(period, n):
        if s_tr[i] > 0:
            pdi = 100 * s_pdm[i] / s_tr[i]
            mdi = 100 * s_mdm[i] / s_tr[i]
            total = pdi + mdi
            if total > 0:
                dx[i] = 100 * abs(pdi - mdi) / total

    adx = [0.0] * n
    fv = period
    while fv < n and dx[fv] == 0:
        fv += 1
    if fv + period >= n:
        return None

    adx[fv + period - 1] = sum(dx[fv:fv + period]) / period
    for i in range(fv + period, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    idx = n - 2
    idx_prev = idx - 1
    if idx_prev < 0 or adx[idx] == 0:
        return None
    return adx[idx], adx[idx_prev]


def calc_squeeze(candles: list[dict], bb_length=20, bb_mult=2.0, kc_length=20, kc_mult=1.5) -> bool | None:
    if len(candles) < max(bb_length, kc_length) + 2:
        return None

    highs = [float(c["h"]) for c in candles]
    lows = [float(c["l"]) for c in candles]
    closes = [float(c["c"]) for c in candles]
    n = len(candles)
    idx = n - 2

    bb_window = closes[idx - bb_length + 1:idx + 1]
    bb_basis = sum(bb_window) / bb_length
    bb_std = (sum((x - bb_basis) ** 2 for x in bb_window) / bb_length) ** 0.5
    upper_bb = bb_basis + bb_mult * bb_std
    lower_bb = bb_basis - bb_mult * bb_std

    tr_vals = [highs[0] - lows[0]]
    for i in range(1, n):
        tr_vals.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    kc_tr_window = tr_vals[idx - kc_length + 1:idx + 1]
    kc_atr = sum(kc_tr_window) / kc_length
    kc_basis = sum(closes[idx - kc_length + 1:idx + 1]) / kc_length
    upper_kc = kc_basis + kc_mult * kc_atr
    lower_kc = kc_basis - kc_mult * kc_atr

    return lower_bb > lower_kc and upper_bb < upper_kc


def determine_signal(coin: str, config: dict, candles_15m: list[dict], candles_1h: list[dict]) -> tuple[str, dict]:
    """
    Determine trading signal for an asset.
    Returns (signal, details) where signal is "long", "short", or "none".
    details contains indicator values for logging.
    """
    details = {"st": "N/A", "htf": "N/A", "adx": "N/A", "sqz": "N/A"}

    # 15m Supertrend
    st_result = calc_supertrend(candles_15m, config.get("st_atr_period", 10), config.get("st_multiplier", 2.0))
    if not st_result:
        return "none", details
    st_dir, st_val, close_price = st_result
    details["st"] = st_dir.upper()
    details["price"] = close_price
    details["st_val"] = st_val

    # 1H Supertrend
    htf_result = calc_supertrend(candles_1h, config.get("htf_st_atr_period", 10), config.get("htf_st_multiplier", 2.0))
    if not htf_result:
        return "none", details
    htf_dir = htf_result[0]
    details["htf"] = htf_dir.upper()

    # Both must agree
    if st_dir != htf_dir:
        return "none", details

    # ADX
    adx_result = calc_adx_values(candles_15m, config.get("adx_period", 14))
    if adx_result:
        adx_current, adx_prev = adx_result
        adx_rising = adx_current > adx_prev
        adx_str = f"{adx_current:.1f}{'↑' if adx_rising else '↓'}"
        details["adx"] = adx_str

        adx_minimum = config.get("adx_minimum", 15.0)
        adx_rising_required = config.get("adx_rising_required", False)

        if adx_current < adx_minimum:
            return "none", details
        if adx_rising_required and not adx_rising:
            return "none", details
    else:
        details["adx"] = "N/A"
        return "none", details

    # Squeeze
    squeeze_block = config.get("squeeze_block", False)
    if squeeze_block:
        sqz = calc_squeeze(candles_15m, config.get("sqz_bb_length", 20), config.get("sqz_bb_mult", 2.0),
                           config.get("sqz_kc_length", 20), config.get("sqz_kc_mult", 1.5))
        details["sqz"] = "ON" if sqz else "OFF" if sqz is not None else "N/A"
        if sqz is None or sqz:
            return "none", details
    else:
        details["sqz"] = "OFF"

    # All filters pass
    return ("long" if st_dir == "bullish" else "short"), details


# ─── Trade Firing ─────────────────────────────────────────────────────────────────


def fire_trade(action: str, coin: str, reason: str) -> bool:
    """Fire a trade via the webhook endpoint."""
    try:
        payload = json.dumps({
            "secret": webhook_secret,
            "action": action,
            "symbol": f"{coin}USDT",
            "message": f"[Reconciler] {reason}",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{BACKEND_URL}/api/webhook",
            data=payload, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        if result.get("success"):
            log.info("FIRE | %s trade accepted: %s", coin, result.get("message", ""))
            return True
        else:
            log.error("FIRE | %s trade rejected: %s", coin, result.get("message", ""))
            return False
    except Exception as e:
        log.error("FIRE | %s trade failed: %s", coin, e)
        return False


# ─── Lock File ────────────────────────────────────────────────────────────────────


def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            try:
                os.kill(old_pid, 0)
                log.error("Another reconciler is running (PID: %d)", old_pid)
                return False
            except OSError:
                pass
            log.warning("Removing stale lock (PID: %d)", old_pid)
        except Exception:
            pass
        LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock():
    LOCK_FILE.unlink(missing_ok=True)


# ─── Main Loop ────────────────────────────────────────────────────────────────────


def run_check() -> None:
    """Run a single reconciliation check for all enabled assets."""
    global last_config_refresh, cached_configs, hour_started, last_summary_time, last_hourly_report_hour

    now = time.time()
    current_hour = int(now // 3600)

    # Hour boundary reset
    if current_hour != hour_started:
        if last_hourly_report_hour >= 0:
            send_hourly_report()
        hour_started = current_hour
        last_hourly_report_hour = current_hour
        for state in asset_states.values():
            state.fires_this_hour = 0
            state.checks_this_hour = 0
            state.actions_this_hour = 0
            state.rate_limit_alerted = False

    # Startup grace
    if now - startup_time < STARTUP_GRACE_SECONDS:
        remaining = STARTUP_GRACE_SECONDS - (now - startup_time)
        log.info("Startup grace — %d seconds remaining", int(remaining))
        return

    # Check trading_paused
    paused = fetch_trading_paused()
    if paused is None:
        log.error("Cannot reach backend — skipping check")
        return
    if paused:
        log.debug("Trading paused — standing by")
        return

    # Refresh configs periodically
    if now - last_config_refresh > CONFIG_REFRESH_INTERVAL or not cached_configs:
        new_configs = fetch_asset_configs()
        if new_configs is not None:
            cached_configs = new_configs
            last_config_refresh = now
            log.info("Config refreshed: %d enabled assets", len(cached_configs))

    if not cached_configs:
        log.info("No enabled assets")
        return

    # Fetch positions once
    positions = fetch_positions()
    if positions is None:
        log.error("Cannot fetch positions — skipping check")
        # Increment API failure for all assets
        for config in cached_configs:
            coin = config["coin"]
            state = asset_states.setdefault(coin, AssetState())
            state.consecutive_api_failures += 1
            if state.consecutive_api_failures >= API_FAILURE_THRESHOLD:
                state.api_paused_until = now + API_RETRY_INTERVAL
                if state.consecutive_api_failures == API_FAILURE_THRESHOLD:
                    send_telegram(f"⚠️ Hyperliquid API failing. Reconciler paused for all assets.")
        return

    # Reset API failure counters
    for state in asset_states.values():
        if state.consecutive_api_failures >= API_FAILURE_THRESHOLD:
            state.consecutive_api_failures = 0
            state.api_paused_until = 0.0

    pos_by_coin = {}
    for p in positions:
        sym = p.get("symbol", "").upper()
        for suffix in ("USDT", "USDC", "USD", "-PERP"):
            if sym.endswith(suffix):
                sym = sym[:-len(suffix)]
                break
        pos_by_coin[sym] = p

    # Check each asset
    for config in cached_configs:
        coin = config["coin"]
        state = asset_states.setdefault(coin, AssetState())

        # API circuit breaker
        if state.api_paused_until > now:
            continue

        # Check if enough time has elapsed for this asset's current tier
        tier_interval = {1: TIER1_INTERVAL, 2: TIER2_INTERVAL, 3: TIER3_INTERVAL}.get(state.tier, TIER3_INTERVAL)
        if now - state.last_check_time < tier_interval:
            continue

        state.last_check_time = now
        state.checks_this_hour += 1

        try:
            run_asset_check(coin, config, state, pos_by_coin.get(coin), now)
        except Exception as e:
            log.exception("Error checking %s: %s", coin, e)
            state.consecutive_api_failures += 1

    # 15-minute summary
    if now - last_summary_time > 900:
        last_summary_time = now
        parts = []
        for config in cached_configs:
            coin = config["coin"]
            state = asset_states.get(coin, AssetState())
            pos = pos_by_coin.get(coin)
            pos_str = pos["side"].upper() if pos else "FLAT"
            sig_str = state.last_signal.upper() if state.last_signal else "NONE"
            status = "ALIGNED" if state.tier == 3 and state.mismatch_count == 0 else f"T{state.tier}"
            parts.append(f"{coin}={status}({pos_str})")
        fires = sum(s.actions_this_hour for s in asset_states.values())
        errors = sum(1 for s in asset_states.values() if s.consecutive_api_failures > 0)
        log.info("SUMMARY | %s | fires=%d | errors=%d", " | ".join(parts), fires, errors)


def run_asset_check(coin: str, config: dict, state: AssetState, position: dict | None, now: float):
    """Run reconciliation check for a single asset."""

    # Fetch candles
    candles_15m = fetch_candles(coin=coin, interval="15m", count=200)
    if candles_15m is None:
        state.consecutive_api_failures += 1
        log.error("CHECK | asset=%s | Cannot fetch 15m candles", coin)
        if state.consecutive_api_failures >= API_FAILURE_THRESHOLD:
            state.api_paused_until = now + API_RETRY_INTERVAL
            send_telegram(f"⚠️ Hyperliquid API failing for {coin}. Reconciler paused for {coin}.")
        return

    htf_timeframe = config.get("htf_timeframe", "1h")
    candles_htf = fetch_candles(coin=coin, interval=htf_timeframe, count=200)
    if candles_htf is None:
        log.warning("CHECK | asset=%s | Cannot fetch %s candles — using 15m only", coin, htf_timeframe)
        candles_htf = []

    state.consecutive_api_failures = 0

    # Determine signal
    signal, details = determine_signal(coin, config, candles_15m, candles_htf if candles_htf else candles_15m)

    # Current position
    actual_side = position["side"].lower() if position else "none"
    state.last_signal = signal
    state.last_position = actual_side

    # ─── Decision Matrix ──────────────────────────────────────────────────
    if actual_side == signal:
        # ALIGNED
        state.tier = 3
        state.mismatch_count = 0
        state.mismatch_type = ""
        status_tag = "ALIGNED"
    elif actual_side != "none" and signal != "none" and actual_side != signal:
        # OPPOSITE MISMATCH → Tier 1
        state.tier = 1
        state.mismatch_type = "opposite"
        state.mismatch_count += 1
        status_tag = f"MISMATCH({state.mismatch_count}/{TIER1_CONFIRMS})"
    elif actual_side == "none" and signal != "none":
        # MISSED ENTRY → Tier 2
        state.tier = 2
        state.mismatch_type = "missed_entry"
        state.mismatch_count += 1
        status_tag = f"MISSED({state.mismatch_count}/{TIER2_CONFIRMS})"
    elif signal == "none":
        # Filters blocking or no signal — HOLD, never close
        state.tier = 3
        state.mismatch_count = 0
        state.mismatch_type = ""
        if actual_side != "none":
            status_tag = "HOLD(filters)"
        else:
            status_tag = "ALIGNED"
    else:
        state.tier = 3
        state.mismatch_count = 0
        status_tag = "ALIGNED"

    next_interval = {1: TIER1_INTERVAL, 2: TIER2_INTERVAL, 3: TIER3_INTERVAL}.get(state.tier, TIER3_INTERVAL)
    log.info(
        "CHECK | asset=%s | tier=%d | ST=%s | 1H=%s | ADX=%s | SQZ=%s | pos=%s | signal=%s | status=%s | next=%ds",
        coin, state.tier, details.get("st", "N/A"), details.get("htf", "N/A"),
        details.get("adx", "N/A"), details.get("sqz", "N/A"),
        actual_side.upper(), signal.upper() if signal else "NONE", status_tag, next_interval,
    )

    # ─── Should we fire? ──────────────────────────────────────────────────

    should_fire = False
    if state.mismatch_type == "opposite" and state.mismatch_count >= TIER1_CONFIRMS:
        should_fire = True
    elif state.mismatch_type == "missed_entry" and state.mismatch_count >= TIER2_CONFIRMS:
        should_fire = True

    if not should_fire:
        return

    # ─── Pre-fire safety checks ───────────────────────────────────────────

    # Cooldown
    if state.last_fire_time > 0 and (now - state.last_fire_time) < FIRE_COOLDOWN:
        remaining = FIRE_COOLDOWN - (now - state.last_fire_time)
        log.info("[SKIP] %s cooldown active — %d seconds remaining", coin, int(remaining))
        return

    # Hourly limit
    if state.fires_this_hour >= MAX_FIRES_PER_HOUR:
        log.info("[SKIP] %s max fires per hour reached (%d/%d)", coin, state.fires_this_hour, MAX_FIRES_PER_HOUR)
        if not state.rate_limit_alerted:
            state.rate_limit_alerted = True
            send_telegram(f"🚨 <b>[{coin}] RATE LIMIT</b>\nFired {state.fires_this_hour}/{MAX_FIRES_PER_HOUR} this hour. No more fires.")
        return

    # Re-fetch position RIGHT BEFORE firing (race condition guard)
    fresh_positions = fetch_positions()
    if fresh_positions is None:
        log.warning("[ABORT] %s cannot re-fetch positions — aborting fire", coin)
        return

    fresh_pos = None
    for p in fresh_positions:
        sym = p.get("symbol", "").upper()
        for suffix in ("USDT", "USDC", "USD", "-PERP"):
            if sym.endswith(suffix):
                sym = sym[:-len(suffix)]
                break
        if sym == coin:
            fresh_pos = p
            break

    fresh_side = fresh_pos["side"].lower() if fresh_pos else "none"

    # If position changed since mismatch detected, abort
    if fresh_side != actual_side:
        log.info("[ABORT] %s position changed since check (%s → %s) — resetting", coin, actual_side, fresh_side)
        state.mismatch_count = 0
        state.mismatch_type = ""
        return

    # Check trading_paused one more time
    paused = fetch_trading_paused()
    if paused:
        expected = signal.upper()
        current = actual_side.upper()
        send_telegram(
            f"⚠️ RECONCILER: {coin} should be {expected} but is {current}. "
            f"Trading is paused. Manual intervention needed."
        )
        return

    # ─── FIRE ─────────────────────────────────────────────────────────────

    action = "buy" if signal == "long" else "sell"
    reason = f"{state.mismatch_type.upper()} — signal={signal.upper()}, pos={actual_side.upper()}"

    state.fires_this_hour += 1
    state.last_fire_time = now
    state.actions_this_hour += 1

    latency = state.mismatch_count * ({1: TIER1_INTERVAL, 2: TIER2_INTERVAL}.get(state.tier, 30))

    log.info(
        "FIRE | asset=%s | action=%s | reason=%s | checks=%d | latency=%ds",
        coin, action.upper(), reason, state.mismatch_count, latency,
    )

    if state.mismatch_type == "opposite":
        send_telegram(
            f"🔄 <b>RECONCILER: {coin}</b>\n"
            f"Corrected {actual_side.upper()} → {signal.upper()}\n"
            f"Webhook missed. Caught in {latency}s."
        )
    else:
        send_telegram(
            f"🔄 <b>RECONCILER: {coin}</b>\n"
            f"Missed entry — opening {signal.upper()}\n"
            f"Caught in {latency}s."
        )

    success = fire_trade(action, coin, reason)

    if success:
        # Reset mismatch after successful fire
        state.mismatch_count = 0
        state.mismatch_type = ""
    else:
        log.error("FIRE | %s trade rejected — attempt still counted", coin)


def send_hourly_report():
    """Send hourly Telegram report."""
    if not cached_configs:
        return

    positions = fetch_positions()
    pos_by_coin = {}
    if positions:
        for p in positions:
            sym = p.get("symbol", "").upper()
            for suffix in ("USDT", "USDC", "USD", "-PERP"):
                if sym.endswith(suffix):
                    sym = sym[:-len(suffix)]
                    break
            pos_by_coin[sym] = p

    lines = []
    total_checks = 0
    total_actions = 0

    for config in cached_configs:
        coin = config["coin"]
        state = asset_states.get(coin, AssetState())
        total_checks += state.checks_this_hour
        total_actions += state.actions_this_hour

        pos = pos_by_coin.get(coin)
        pos_str = pos["side"].upper() if pos else "FLAT"
        sig_str = state.last_signal.upper() if state.last_signal else "NONE"

        mismatches = state.actions_this_hour
        status = "ALIGNED" if sig_str in (pos_str, "NONE") or pos_str == sig_str else "WATCH"

        if pos:
            pnl = pos.get("unrealized_pnl", 0)
            pnl_sign = "+" if pnl >= 0 else ""
            lines.append(f"{coin}: {pos_str} {status} | {state.checks_this_hour} checks, {mismatches} mismatches | {pnl_sign}${pnl:,.2f}")
        else:
            lines.append(f"{coin}: {pos_str}, {sig_str} signal | {state.checks_this_hour} checks, {mismatches} mismatches")

    total_fires = sum(s.actions_this_hour for s in asset_states.values())
    api_errors = sum(1 for s in asset_states.values() if s.consecutive_api_failures > 0)

    send_telegram(
        "🕐 <b>Reconciler Hourly</b>\n"
        + "\n".join(lines) + "\n"
        f"\nCorrections: {total_fires} | API errors: {api_errors}"
    )


# ─── Signal Handlers ─────────────────────────────────────────────────────────────


def handle_shutdown(signum, frame):
    global shutting_down
    shutting_down = True
    log.info("Reconciler shutting down gracefully (signal %d)", signum)
    send_telegram("🔴 Reconciler stopped. Positions UNMONITORED until restart.")
    release_lock()
    sys.exit(0)


# ─── Main ─────────────────────────────────────────────────────────────────────────


def main():
    if not acquire_lock():
        sys.exit(1)

    sig.signal(sig.SIGTERM, handle_shutdown)
    sig.signal(sig.SIGINT, handle_shutdown)

    try:
        log.info("=" * 60)
        log.info("State Reconciler v2 starting (tiered)")
        log.info("Tiers: T1=%ds/%d confirms, T2=%ds/%d confirms, T3=%ds",
                 TIER1_INTERVAL, TIER1_CONFIRMS, TIER2_INTERVAL, TIER2_CONFIRMS, TIER3_INTERVAL)

        if not load_telegram_config():
            log.warning("Telegram not configured")
        if not load_webhook_secret():
            log.error("WEBHOOK_SECRET not found — cannot fire trades")
            release_lock()
            sys.exit(1)

        # Fetch initial state
        positions = fetch_positions()
        configs = fetch_asset_configs()

        startup_parts = []
        if configs:
            pos_by_coin = {}
            if positions:
                for p in positions:
                    sym = p.get("symbol", "").upper()
                    for suffix in ("USDT", "USDC", "USD", "-PERP"):
                        if sym.endswith(suffix):
                            sym = sym[:-len(suffix)]
                            break
                    pos_by_coin[sym] = p

            for config in configs:
                coin = config["coin"]
                pos = pos_by_coin.get(coin)
                pos_str = pos["side"].upper() if pos else "FLAT"
                startup_parts.append(f"{coin}: {pos_str}")

        send_telegram(
            f"🟢 <b>Reconciler started (v2)</b>\n"
            + " | ".join(startup_parts) if startup_parts else "No assets"
        )

        global hour_started, last_summary_time
        hour_started = int(time.time() // 3600)
        last_summary_time = time.time()

        while not shutting_down:
            try:
                run_check()
            except Exception as e:
                log.exception("Unhandled error: %s", e)
            time.sleep(MAIN_LOOP_INTERVAL)

    except KeyboardInterrupt:
        log.info("Shutting down (keyboard interrupt)")
    finally:
        send_telegram("🔴 Reconciler stopped. Positions UNMONITORED until restart.")
        release_lock()
        log.info("State Reconciler stopped")


if __name__ == "__main__":
    main()
