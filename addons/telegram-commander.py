#!/usr/bin/env python3
"""
HyperTrader Telegram Commander v2 — Full trading control via Telegram.

Commands: /status, /assets, /trades, /pause, /help
Inline buttons for: Close, Add, Reduce, Size, Leverage, Kill Switch, Pause/Resume.

Position management: ONE position per asset, strategy manages all exits/flips.
User can add/reduce/close freely — strategy handles the rest.
"""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── Paths & Config ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DB_FILE = PROJECT_DIR / "hypertrader.db"
LOG_FILE = PROJECT_DIR / "logs" / "telegram-commander.log"
API_BASE = "http://localhost:8000"

_last_action_time = 0.0
ACTION_COOLDOWN = 5.0

# ─── Logging ──────────────────────────────────────────────────────────────────────

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("commander")
log.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3)
handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
log.addHandler(handler)
log.addHandler(logging.StreamHandler())

# ─── Config ───────────────────────────────────────────────────────────────────────

BOT_TOKEN = ""
CHAT_ID = ""


def load_config():
    global BOT_TOKEN, CHAT_ID
    try:
        conn = sqlite3.connect(str(DB_FILE))
        row = conn.execute("SELECT telegram_bot_token, telegram_chat_id FROM app_settings WHERE id=1").fetchone()
        conn.close()
        if row and row[0] and row[1]:
            BOT_TOKEN = row[0]
            CHAT_ID = str(row[1])
            return True
    except Exception as e:
        log.error("Failed to load config: %s", e)
    return False


# ─── API Helpers ──────────────────────────────────────────────────────────────────


async def api_get(path: str) -> dict | list | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(f"{API_BASE}{path}") as r:
                if r.status == 200:
                    return await r.json()
                log.warning("API GET %s → %s", path, r.status)
    except Exception as e:
        log.error("API GET %s failed: %s", path, e)
    return None


async def api_post(path: str, data: dict = None) -> dict | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(f"{API_BASE}{path}", json=data or {}) as r:
                return await r.json()
    except Exception as e:
        log.error("API POST %s failed: %s", path, e)
    return None


async def api_patch(path: str, data: dict) -> dict | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.patch(f"{API_BASE}{path}", json=data, headers={"Content-Type": "application/json"}) as r:
                return await r.json()
    except Exception as e:
        log.error("API PATCH %s failed: %s", path, e)
    return None


def authorized(update: Update) -> bool:
    uid = str(update.effective_chat.id)
    if uid == CHAT_ID:
        return True
    log.warning("Unauthorized: chat_id=%s, user=%s", uid, update.effective_user)
    return False


def rate_limited() -> bool:
    global _last_action_time
    now = time.time()
    if now - _last_action_time < ACTION_COOLDOWN:
        return True
    _last_action_time = now
    return False


def fmt_usd(v: float) -> str:
    return f"${v:,.2f}" if abs(v) >= 1 else f"${v:.4f}"


def fmt_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def fmt_duration(opened_at_str: str | None) -> str:
    if not opened_at_str:
        return ""
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(opened_at_str.replace("Z", ""), fmt)
                break
            except ValueError:
                continue
        else:
            return ""
        delta = datetime.utcnow() - dt
        hours = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return ""


# ─── /status ──────────────────────────────────────────────────────────────────────


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    log.info("Command: /status")

    portfolio = await api_get("/api/live/portfolio")
    positions = await api_get("/api/positions")  # Uses new position tracking
    assets = await api_get("/api/assets")

    if not portfolio:
        await update.message.reply_text("⚠️ Backend unreachable")
        return

    acct = portfolio.get("account_value", 0)
    margin = portfolio.get("total_margin_used", 0)
    margin_pct = (margin / acct * 100) if acct > 0 else 0

    lines = [f"💰 {fmt_usd(acct)} | Margin: {margin_pct:.1f}%\n"]
    buttons = []
    asset_map = {a["coin"]: a for a in (assets or [])}
    positioned_coins = set()

    for p in (positions or []):
        if not p.get("direction"):
            continue
        coin = p["coin"]
        positioned_coins.add(coin)
        side = p["direction"].upper()
        emoji = "📈" if p["direction"] == "long" else "📉"
        pnl = p.get("unrealized_pnl") or 0
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_pct_val = p.get("pnl_pct") or 0
        entry = p.get("entry_price") or 0
        current = p.get("current_price") or 0
        notional = p.get("notional") or p.get("total_size", 0)
        lev = p.get("leverage") or 10
        held = fmt_duration(p.get("opened_at"))

        sig_size = p.get("signal_size", 0)
        man_size = p.get("manual_size", 0)
        size_detail = ""
        if sig_size > 0 and man_size > 0:
            size_detail = f" (signal: {fmt_usd(sig_size)} + manual: {fmt_usd(man_size)})"
        elif man_size > 0 and sig_size == 0:
            size_detail = " (manual open)"

        origin_badge = ""
        if p.get("origin") == "manual":
            origin_badge = " 👤"
        elif p.get("origin") == "reconciler":
            origin_badge = " 🔄"

        lines.append(
            f"{emoji} {coin} {side} {pnl_sign}{fmt_usd(pnl)} ({fmt_pct(pnl_pct_val)}){origin_badge}\n"
            f"   Entry {fmt_usd(entry)} → {fmt_usd(current)} | {fmt_usd(notional)}{size_detail} | {lev}x"
            + (f" | {held}" if held else "")
        )
        buttons.append([
            InlineKeyboardButton(f"Close {coin}", callback_data=f"cc:{coin}"),
            InlineKeyboardButton("Add ▼", callback_data=f"ad:{coin}"),
            InlineKeyboardButton("Reduce ▼", callback_data=f"rd:{coin}"),
        ])

    # Flat assets
    for a in (assets or []):
        if a["coin"] not in positioned_coins:
            status = "✅ enabled" if a["enabled"] else "❌ disabled"
            lines.append(f"\n{a['coin']} — Flat ({status})")

    buttons.append([
        InlineKeyboardButton("🔴 Kill All", callback_data="kill:ask"),
        InlineKeyboardButton("⏸ Pause All", callback_data="pause_all"),
    ])

    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


# ─── /assets ──────────────────────────────────────────────────────────────────────


async def cmd_assets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    log.info("Command: /assets")

    assets = await api_get("/api/assets")
    portfolio = await api_get("/api/live/portfolio")

    if not assets:
        await update.message.reply_text("⚠️ Backend unreachable")
        return

    acct = portfolio.get("account_value", 0) if portfolio else 0
    lines = ["🪙 Asset Configuration\n"]
    buttons = []

    for a in assets:
        status = "✅ ON" if a["enabled"] else "❌ OFF"
        pnl = a.get("total_pnl", 0)
        pnl_str = f"{'+' if pnl >= 0 else ''}{fmt_usd(pnl)}" if pnl != 0 else "$0"
        lines.append(
            f"{a['coin']} {status} | ${a['fixed_trade_amount_usd']:.0f} | "
            f"{a['leverage']}x | {a['total_trades']} trades | {pnl_str}"
        )
        toggle = "dis" if a["enabled"] else "ena"
        toggle_label = "Disable" if a["enabled"] else "Enable"
        buttons.append([
            InlineKeyboardButton(toggle_label, callback_data=f"{toggle}:{a['coin']}"),
            InlineKeyboardButton("Size ▼", callback_data=f"sz:{a['coin']}:{acct:.0f}"),
            InlineKeyboardButton("Lev ▼", callback_data=f"lv:{a['coin']}:{a['max_leverage']}:{a['leverage']}"),
        ])

    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


# ─── /trades ──────────────────────────────────────────────────────────────────────


async def cmd_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    log.info("Command: /trades")

    # Try new trades endpoint first, fall back to HL fills
    trades = await api_get("/api/trades?limit=10")
    if trades:
        lines = ["📋 Recent Trades\n"]
        wins = 0
        losses = 0
        total_wins = 0.0
        total_losses = 0.0
        today_pnl = 0.0
        for i, t in enumerate(trades, 1):
            action = t.get("action", "")
            origin = t.get("origin", "")
            pnl = t.get("pnl")
            coin = t.get("coin", "")

            # Origin badge
            if "signal" in origin:
                badge = "🤖"
            elif "manual" in origin:
                badge = "👤"
            elif "reconciler" in origin:
                badge = "🔄"
            else:
                badge = "📌"

            # Action emoji
            if "close" in action or "reduce" in action:
                if pnl is not None and pnl >= 0:
                    emoji = "🟢"
                    wins += 1
                    total_wins += pnl
                elif pnl is not None:
                    emoji = "🔴"
                    losses += 1
                    total_losses += abs(pnl)
                else:
                    emoji = "⚪"
            elif "add" in action:
                emoji = "📈"
            elif "open" in action or "flip" in action:
                emoji = "🟢" if "long" in action else "🔴"
            else:
                emoji = "⚪"

            pnl_str = ""
            if pnl is not None:
                pnl_sign = "+" if pnl >= 0 else ""
                pnl_str = f" | P&L: {pnl_sign}{fmt_usd(pnl)}"
                today_pnl += pnl

            # Time ago
            ts = t.get("timestamp", "")
            time_ago = ""
            if ts:
                try:
                    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                        try:
                            dt = datetime.strptime(ts.replace("Z", ""), fmt)
                            break
                        except ValueError:
                            continue
                    delta = (datetime.utcnow() - dt).total_seconds()
                    if delta < 3600:
                        time_ago = f"{int(delta / 60)}m ago"
                    elif delta < 86400:
                        time_ago = f"{int(delta / 3600)}h ago"
                    else:
                        time_ago = f"{int(delta / 86400)}d ago"
                except Exception:
                    pass

            notes = t.get("notes", "") or ""
            if len(notes) > 30:
                notes = notes[:30] + "..."

            lines.append(f"{i}. {emoji} {coin} {action}{pnl_str} | {badge} {origin} | {time_ago}")

        # Stats
        total = wins + losses
        if total > 0:
            win_rate = wins / total * 100
            avg_win = total_wins / wins if wins > 0 else 0
            avg_loss = total_losses / losses if losses > 0 else 0
            lines.append(f"\nWin Rate: {win_rate:.0f}% | Avg Win: +{fmt_usd(avg_win)} | Avg Loss: -{fmt_usd(avg_loss)}")
            lines.append(f"Recent P&L: {'+' if today_pnl >= 0 else ''}{fmt_usd(today_pnl)}")

        await update.message.reply_text("\n".join(lines))
    else:
        # Fallback to HL fills
        fills = await api_get("/api/live/fills")
        if not fills:
            await update.message.reply_text("📋 No trades yet")
            return
        lines = ["📋 Recent Fills\n"]
        for i, f in enumerate(fills[:10], 1):
            emoji = "🟢" if f["side"] == "buy" else "🔴"
            pnl = f.get("closed_pnl", 0)
            pnl_str = f" P&L: {'+' if pnl >= 0 else ''}{fmt_usd(pnl)}" if pnl != 0 else ""
            lines.append(f"{i}. {emoji} {f['symbol']} {f['side'].upper()} {f['size']} @ {fmt_usd(f['price'])}{pnl_str}")
        await update.message.reply_text("\n".join(lines))


# ─── /pause ───────────────────────────────────────────────────────────────────────


async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    log.info("Command: /pause")

    assets = await api_get("/api/assets")
    settings = await api_get("/api/settings")

    if not assets or not settings:
        await update.message.reply_text("⚠️ Backend unreachable")
        return

    paused = settings.get("trading_paused", False)
    lines = ["⏸ Trading Control\n"]
    lines.append(f"Global: {'⏸ Paused' if paused else '▶️ Active'}")

    buttons = []
    for a in assets:
        status = "▶️ Active" if a["enabled"] else "⏸ Paused"
        lines.append(f"{a['coin']}: {status}")
        if a["enabled"]:
            buttons.append([InlineKeyboardButton(f"Pause {a['coin']}", callback_data=f"dis:{a['coin']}")])
        else:
            buttons.append([InlineKeyboardButton(f"Resume {a['coin']}", callback_data=f"ena:{a['coin']}")])

    bottom = [InlineKeyboardButton("⏸ Pause ALL", callback_data="pause_all")]
    if paused or any(not a["enabled"] for a in assets):
        bottom.append(InlineKeyboardButton("▶️ Resume ALL", callback_data="resume_all"))
    buttons.append(bottom)

    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


# ─── /help ────────────────────────────────────────────────────────────────────────


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    text = (
        "❓ HyperTrader Commands\n\n"
        "/status — Positions, P&L, balance, trade buttons\n"
        "/assets — Enable/disable, sizing, leverage per asset\n"
        "/trades — Last 10 trades with P&L and origin\n"
        "/pause — Pause/resume trading per asset or globally\n"
        "/help — This message\n\n"
        "All positions are strategy-managed regardless of how they were opened.\n"
        "Add or reduce freely — the strategy handles exits and flips.\n"
        "Kill switch closes everything and pauses trading."
    )
    await update.message.reply_text(text)


# ─── Callback Handler ─────────────────────────────────────────────────────────────


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.message.chat_id) != CHAT_ID:
        await query.answer("Unauthorized")
        return

    data = query.data
    await query.answer()
    log.info("Callback: %s", data)

    # ── Close confirmation ──
    if data.startswith("cc:"):
        coin = data[3:]
        positions = await api_get("/api/positions")
        pos = next((p for p in (positions or []) if p["coin"] == coin and p.get("direction")), None)
        if not pos:
            await query.edit_message_text(f"No open position for {coin}")
            return
        pnl = pos.get("unrealized_pnl") or 0
        side = pos["direction"].upper()
        pnl_sign = "+" if pnl >= 0 else ""
        text = f"⚠️ Close {coin} {side}? Current P&L: {pnl_sign}{fmt_usd(pnl)}"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Yes, Close {coin}", callback_data=f"cx:{coin}"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ]])
        await query.edit_message_text(text, reply_markup=kb)

    # ── Execute close ──
    elif data.startswith("cx:"):
        if rate_limited():
            await query.edit_message_text("⏳ Please wait...")
            return
        coin = data[3:]
        result = await api_post(f"/api/positions/{coin}/close")
        if result and result.get("success"):
            pnl = result.get("pnl")
            held = result.get("held_duration", "")
            msg = f"✅ {coin} closed"
            if pnl is not None:
                pnl_sign = "+" if pnl >= 0 else ""
                msg += f" | P&L: {pnl_sign}{fmt_usd(pnl)}"
            if held:
                msg += f" | Held: {held}"
            await query.edit_message_text(msg)
        else:
            msg = result.get("message", "Unknown error") if result else "Backend unreachable"
            await query.edit_message_text(f"❌ Close failed: {msg}")

    # ── Add to position ──
    elif data.startswith("ad:"):
        coin = data[3:]
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("+25%", callback_data=f"ax:{coin}:25"),
                InlineKeyboardButton("+50%", callback_data=f"ax:{coin}:50"),
                InlineKeyboardButton("+100%", callback_data=f"ax:{coin}:100"),
            ],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ])
        await query.edit_message_text(f"Add to {coin} position — choose amount:", reply_markup=kb)

    elif data.startswith("ax:"):
        if rate_limited():
            await query.edit_message_text("⏳ Please wait...")
            return
        parts = data.split(":")
        coin, pct = parts[1], int(parts[2])
        result = await api_post(f"/api/positions/{coin}/add", {"add_pct": pct})
        if result and result.get("success"):
            await query.edit_message_text(f"✅ {result['message']}")
        else:
            msg = result.get("message", "Unknown error") if result else "Backend unreachable"
            await query.edit_message_text(f"❌ Add failed: {msg}")

    # ── Reduce position ──
    elif data.startswith("rd:"):
        coin = data[3:]
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("25%", callback_data=f"rx:{coin}:25"),
                InlineKeyboardButton("50%", callback_data=f"rx:{coin}:50"),
                InlineKeyboardButton("75%", callback_data=f"rx:{coin}:75"),
            ],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ])
        await query.edit_message_text(f"Reduce {coin} position — choose amount:", reply_markup=kb)

    elif data.startswith("rx:"):
        if rate_limited():
            await query.edit_message_text("⏳ Please wait...")
            return
        parts = data.split(":")
        coin, pct = parts[1], int(parts[2])
        result = await api_post(f"/api/positions/{coin}/reduce", {"reduce_pct": pct})
        if result and result.get("success"):
            pnl = result.get("pnl")
            pnl_str = ""
            if pnl is not None:
                pnl_sign = "+" if pnl >= 0 else ""
                pnl_str = f" | P&L: {pnl_sign}{fmt_usd(pnl)}"
            await query.edit_message_text(f"✅ {result['message']}{pnl_str}")
        else:
            msg = result.get("message", "Unknown error") if result else "Backend unreachable"
            await query.edit_message_text(f"❌ Reduce failed: {msg}")

    # ── Kill all ──
    elif data == "kill:ask":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Yes, Close Everything", callback_data="kill:yes"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ]])
        await query.edit_message_text(
            "⚠️ Close ALL positions across ALL assets?\nThis also PAUSES trading.",
            reply_markup=kb
        )

    elif data == "kill:yes":
        if rate_limited():
            await query.edit_message_text("⏳ Please wait...")
            return
        result = await api_post("/api/positions/close-all")
        if result and result.get("success"):
            await query.edit_message_text(f"🔴 {result['message']}")
        else:
            msg = result.get("message", "Unknown error") if result else "Backend unreachable"
            await query.edit_message_text(f"❌ Kill switch failed: {msg}")

    # ── Pause/Resume all ──
    elif data == "pause_all":
        await api_patch("/api/settings", {"trading_paused": True})
        assets = await api_get("/api/assets")
        for a in (assets or []):
            await api_patch(f"/api/assets/{a['coin']}", {"enabled": False})
        await query.edit_message_text("⏸ All trading paused. Use /pause to resume.")

    elif data == "resume_all":
        await api_patch("/api/settings", {"trading_paused": False})
        assets = await api_get("/api/assets")
        for a in (assets or []):
            await api_patch(f"/api/assets/{a['coin']}", {"enabled": True})
        await query.edit_message_text("▶️ All trading resumed.")

    # ── Enable/Disable asset ──
    elif data.startswith("ena:"):
        coin = data[4:]
        await api_patch(f"/api/assets/{coin}", {"enabled": True})
        await query.edit_message_text(f"✅ {coin} enabled. Strategy signals will execute.")

    elif data.startswith("dis:"):
        coin = data[4:]
        # Check if position exists
        positions = await api_get("/api/positions")
        pos = next((p for p in (positions or []) if p["coin"] == coin and p.get("direction")), None)
        if pos:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Disable Anyway", callback_data=f"dx:{coin}"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
            ]])
            await query.edit_message_text(
                f"⚠️ {coin} has an open {pos['direction'].upper()}.\n"
                f"Disabling won't close it, but no new trades will execute.",
                reply_markup=kb,
            )
        else:
            await api_patch(f"/api/assets/{coin}", {"enabled": False})
            await query.edit_message_text(f"⏸ {coin} disabled (existing positions kept)")

    elif data.startswith("dx:"):
        coin = data[3:]
        await api_patch(f"/api/assets/{coin}", {"enabled": False})
        await query.edit_message_text(f"⏸ {coin} disabled (existing positions kept)")

    # ── Size picker ──
    elif data.startswith("sz:"):
        parts = data.split(":")
        coin = parts[1]
        acct = float(parts[2]) if len(parts) > 2 else 500
        pcts = [25, 50, 75, 100]
        row1 = [InlineKeyboardButton(f"${a}", callback_data=f"ss:{coin}:{a}") for a in [42, 85, 125, 250]]
        row2 = [InlineKeyboardButton(f"{p}%=${int(acct * p / 100)}", callback_data=f"ss:{coin}:{int(acct * p / 100)}") for p in pcts]
        kb = InlineKeyboardMarkup([row1, row2, [InlineKeyboardButton("Cancel", callback_data="cancel")]])
        await query.edit_message_text(f"{coin} trade size (account: {fmt_usd(acct)}):", reply_markup=kb)

    elif data.startswith("ss:"):
        parts = data.split(":")
        coin, amount = parts[1], int(parts[2])
        await api_patch(f"/api/assets/{coin}", {"fixed_trade_amount_usd": amount})
        await query.edit_message_text(f"✅ {coin} trade size set to ${amount} (fixed)")

    # ── Leverage picker ──
    elif data.startswith("lv:"):
        parts = data.split(":")
        coin = parts[1]
        max_lev = int(parts[2]) if len(parts) > 2 else 40
        current_lev = int(parts[3]) if len(parts) > 3 else 10

        # Check if position exists for leverage warning
        positions = await api_get("/api/positions")
        has_position = any(p["coin"] == coin and p.get("direction") for p in (positions or []))

        levs = [l for l in [3, 5, 10, 15, 20, 25, 30, 40] if l <= max_lev]
        row = [InlineKeyboardButton(f"{l}x", callback_data=f"sl:{coin}:{l}:{current_lev}") for l in levs]
        rows = [row[i:i + 4] for i in range(0, len(row), 4)]
        rows.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
        kb = InlineKeyboardMarkup(rows)

        extra = ""
        if has_position:
            extra = "\n⚠️ Active position will be updated on Hyperliquid."
        await query.edit_message_text(f"{coin} leverage (current: {current_lev}x, max {max_lev}x):{extra}", reply_markup=kb)

    elif data.startswith("sl:"):
        parts = data.split(":")
        coin = parts[1]
        new_lev = int(parts[2])
        current_lev = int(parts[3]) if len(parts) > 3 else 10

        # Check if increasing leverage with open position — warn
        if new_lev > current_lev:
            positions = await api_get("/api/positions")
            pos = next((p for p in (positions or []) if p["coin"] == coin and p.get("direction")), None)
            if pos:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"Yes, Change to {new_lev}x", callback_data=f"lc:{coin}:{new_lev}"),
                    InlineKeyboardButton("Cancel", callback_data="cancel"),
                ]])
                await query.edit_message_text(
                    f"⚠️ Increasing {coin} leverage from {current_lev}x to {new_lev}x "
                    f"with an open {pos['direction'].upper()}.\n"
                    f"This increases your risk on the current position. Proceed?",
                    reply_markup=kb,
                )
                return

        # Decreasing or no position — apply directly
        result = await api_patch(f"/api/assets/{coin}", {"leverage": new_lev})
        if result:
            # Check if position was active to give correct message
            positions = await api_get("/api/positions")
            has_pos = any(p["coin"] == coin and p.get("direction") for p in (positions or []))
            if has_pos:
                await query.edit_message_text(f"✅ {coin} leverage changed to {new_lev}x. Active position updated.")
            else:
                await query.edit_message_text(f"✅ {coin} leverage set to {new_lev}x. Applied on next trade.")
        else:
            await query.edit_message_text(f"❌ Failed to update leverage")

    # ── Leverage confirm (increase with position) ──
    elif data.startswith("lc:"):
        parts = data.split(":")
        coin = parts[1]
        new_lev = int(parts[2])
        result = await api_patch(f"/api/assets/{coin}", {"leverage": new_lev})
        if result:
            await query.edit_message_text(f"✅ {coin} leverage changed to {new_lev}x. Active position updated.")
        else:
            await query.edit_message_text(f"❌ Failed to update leverage")

    # ── Cancel ──
    elif data == "cancel":
        await query.edit_message_text("Cancelled.")


# ─── Main ─────────────────────────────────────────────────────────────────────────


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("status", "📊 Positions, P&L, account balance"),
        BotCommand("assets", "🪙 Enable/disable, sizing, leverage"),
        BotCommand("trades", "📋 Recent trades with P&L"),
        BotCommand("pause", "⏸ Pause/resume trading per asset"),
        BotCommand("help", "❓ List all commands"),
    ])
    log.info("Bot commands registered")


def main():
    if not load_config():
        log.error("Failed to load Telegram config — exiting")
        return

    log.info("Starting Telegram Commander v2 (token=%s...)", BOT_TOKEN[:15])

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("assets", cmd_assets))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_pause))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Telegram Commander v2 running — polling for commands")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
