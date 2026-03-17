#!/usr/bin/env python3
"""
HyperTrader Hourly Market Intelligence Report
Standalone addon — gathers account/market/news data, generates Claude narrative, sends to Telegram.
"""

import json
import os
import sqlite3
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import anthropic

# ─── Paths ───────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
DB_PATH = REPO_DIR / "backend" / "hypertrader.db"
ENV_PATH = SCRIPT_DIR / ".env.addons"
LOG_PATH = SCRIPT_DIR / "hourly-reports.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB

# ─── Logging ─────────────────────────────────────────────────────────────────────

def setup_logging():
    """Set up logging with manual rotation."""
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
        old = LOG_PATH.with_suffix(".log.old")
        LOG_PATH.replace(old)

    # StreamHandler with UTF-8 to avoid Windows cp1252 encoding errors
    stdout_handler = logging.StreamHandler(
        open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
    )

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            stdout_handler,
        ],
    )

log = logging.getLogger(__name__)

# ─── Config Loading ──────────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    """Parse a simple KEY=VALUE .env file."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def load_telegram_creds() -> tuple[str, str]:
    """Read Telegram bot_token and chat_id from the SQLite database."""
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT telegram_bot_token, telegram_chat_id FROM app_settings WHERE id=1"
        ).fetchone()
        if not row or not row[0] or not row[1]:
            raise RuntimeError("Telegram credentials not configured in app_settings")
        return row[0], str(row[1])
    finally:
        conn.close()

# ─── Data Fetchers (all gracefully degrading) ────────────────────────────────────

TIMEOUT = 10.0
LOCAL_API = "http://localhost:8000/api"


def fetch_portfolio(client: httpx.Client) -> dict | None:
    try:
        r = client.get(f"{LOCAL_API}/live/portfolio", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Portfolio fetch failed: {e}")
        return None


def fetch_positions(client: httpx.Client) -> list | None:
    try:
        r = client.get(f"{LOCAL_API}/live/positions", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Positions fetch failed: {e}")
        return None


def fetch_recent_trades(client: httpx.Client) -> list | None:
    try:
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        r = client.get(
            f"{LOCAL_API}/trades",
            params={"start_date": one_hour_ago, "limit": 100},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        # API may return {"trades": [...]} or just [...]
        if isinstance(data, dict):
            return data.get("trades", [])
        return data
    except Exception as e:
        log.warning(f"Trades fetch failed: {e}")
        return None


def fetch_dashboard(client: httpx.Client) -> dict | None:
    try:
        r = client.get(f"{LOCAL_API}/dashboard", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Dashboard fetch failed: {e}")
        return None


def fetch_btc_candles(client: httpx.Client) -> list | None:
    """Fetch 24h of 1h BTC candles from Hyperliquid."""
    try:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - 24 * 60 * 60 * 1000
        r = client.post(
            "https://api.hyperliquid.xyz/info",
            json={
                "type": "candleSnapshot",
                "req": {
                    "coin": "BTC",
                    "interval": "1h",
                    "startTime": start_ms,
                    "endTime": now_ms,
                },
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"BTC candles fetch failed: {e}")
        return None


def fetch_btc_price(client: httpx.Client) -> float | None:
    """Fetch current BTC mid price from Hyperliquid."""
    try:
        r = client.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "allMids"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mids = r.json()
        if "BTC" in mids:
            return float(mids["BTC"])
        return None
    except Exception as e:
        log.warning(f"BTC price fetch failed: {e}")
        return None


def fetch_news(client: httpx.Client, api_key: str) -> list | None:
    """Fetch important BTC news from CryptoPanic."""
    if not api_key or api_key == "your_key_here":
        return None
    try:
        r = client.get(
            "https://cryptopanic.com/api/developer/v2/posts/",
            params={
                "auth_token": api_key,
                "currencies": "BTC",
                "filter": "important",
                "public": "true",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        # Return just the titles (last 5)
        return [r.get("title", "") for r in results[:5] if r.get("title")]
    except Exception as e:
        log.warning(f"News fetch failed: {e}")
        return None

# ─── Market Metrics ──────────────────────────────────────────────────────────────

def calculate_market_metrics(candles: list, current_price: float | None) -> dict:
    """Derive volatility, volume, and trend from candle data."""
    metrics = {}

    if not candles or len(candles) < 2:
        return metrics

    # Parse candle values
    closes = [float(c["c"]) for c in candles]
    highs = [float(c["h"]) for c in candles]
    lows = [float(c["l"]) for c in candles]
    volumes = [float(c["v"]) for c in candles]

    price = current_price or closes[-1]
    metrics["current_price"] = price

    # Hourly change
    if len(closes) >= 2:
        prev = closes[-2]
        metrics["hourly_change_pct"] = ((price - prev) / prev) * 100

    # ATR-based volatility
    true_ranges = [h - l for h, l in zip(highs, lows)]
    atr = sum(true_ranges) / len(true_ranges)
    atr_pct = (atr / price) * 100
    metrics["atr"] = atr
    metrics["atr_pct"] = atr_pct
    if atr_pct < 0.5:
        metrics["volatility"] = "Low"
    elif atr_pct < 1.5:
        metrics["volatility"] = "Medium"
    else:
        metrics["volatility"] = "High"

    # Volume classification
    if volumes:
        last_vol = volumes[-1]
        avg_vol = sum(volumes) / len(volumes)
        if avg_vol > 0:
            vol_ratio = last_vol / avg_vol
            metrics["volume_ratio"] = vol_ratio
            if vol_ratio < 0.6:
                metrics["volume"] = "Low"
            elif vol_ratio < 1.4:
                metrics["volume"] = "Normal"
            else:
                metrics["volume"] = "High"

    # Regime detection
    if len(closes) >= 12:
        sma4 = sum(closes[-4:]) / 4
        sma12 = sum(closes[-12:]) / 12
        metrics["sma4"] = sma4
        metrics["sma12"] = sma12
        if price > sma4 > sma12:
            metrics["regime"] = "Trending Up"
        elif price < sma4 < sma12:
            metrics["regime"] = "Trending Down"
        else:
            metrics["regime"] = "Flat"
    elif len(closes) >= 4:
        sma4 = sum(closes[-4:]) / 4
        metrics["sma4"] = sma4
        metrics["regime"] = "Trending Up" if price > sma4 else "Trending Down" if price < sma4 else "Flat"

    return metrics


def extract_supertrend_direction(trades: list | None) -> str | None:
    """Try to infer Supertrend direction from recent trade messages."""
    if not trades:
        return None
    for trade in reversed(trades):
        msg = trade.get("message", "") or ""
        msg_lower = msg.lower()
        if "supertrend" in msg_lower:
            if "buy" in msg_lower or "long" in msg_lower:
                return "Bullish"
            elif "sell" in msg_lower or "short" in msg_lower:
                return "Bearish"
        # Also check side as fallback
        side = trade.get("side", "")
        if side:
            return "Bullish" if side.lower() == "buy" else "Bearish"
    return None

# ─── Claude Narrative ────────────────────────────────────────────────────────────

CLAUDE_SYSTEM_PROMPT = """You are a concise crypto market analyst for a trader running an automated BTC strategy on Hyperliquid.
Given the current market data, account status, and news, write a 2-3 sentence market intelligence brief.
Be direct and actionable. Focus on what matters for the trader's positions and risk.
Use plain text, no markdown, no bullet points."""


def generate_narrative(
    anthropic_key: str,
    portfolio: dict | None,
    positions: list | None,
    trades: list | None,
    dashboard: dict | None,
    metrics: dict,
    news: list | None,
    supertrend: str | None,
) -> str:
    """Call Claude API to generate a narrative summary."""
    if not anthropic_key or anthropic_key == "your_key_here":
        return "Market context unavailable (Anthropic API key not configured)"

    # Build context for Claude
    context_parts = []

    if metrics:
        price = metrics.get("current_price", "N/A")
        change = metrics.get("hourly_change_pct")
        change_str = f"{change:+.2f}%" if change is not None else "N/A"
        context_parts.append(
            f"BTC Price: ${price:,.2f} ({change_str} 1h) | "
            f"Volatility: {metrics.get('volatility', 'N/A')} | "
            f"Volume: {metrics.get('volume', 'N/A')} | "
            f"Regime: {metrics.get('regime', 'N/A')}"
        )

    if supertrend:
        context_parts.append(f"Supertrend Signal: {supertrend}")

    if portfolio:
        acct_val = portfolio.get("account_value", 0)
        upnl = portfolio.get("total_unrealized_pnl", 0)
        context_parts.append(f"Account: ${acct_val:,.2f} | Unrealized P&L: ${upnl:+,.2f}")

    if positions:
        pos_strs = []
        for p in positions:
            sym = p.get("symbol", "?")
            side = p.get("side", "?")
            pnl = p.get("unrealized_pnl", 0)
            leverage = p.get("leverage", 1)
            pos_strs.append(f"{sym} {side} {leverage}x (P&L: ${pnl:+,.2f})")
        context_parts.append(f"Positions: {', '.join(pos_strs)}")

    if trades:
        context_parts.append(f"Trades this hour: {len(trades)}")

    if dashboard:
        daily_pnl = dashboard.get("daily_pnl") or dashboard.get("today_pnl")
        if daily_pnl is not None:
            context_parts.append(f"Daily P&L: ${daily_pnl:+,.2f}")

    if news:
        context_parts.append(f"Recent headlines: {'; '.join(news)}")

    user_content = "\n".join(context_parts) if context_parts else "No data available"

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=CLAUDE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text.strip()
    except anthropic.BadRequestError as e:
        log.error(f"Claude API 400 error (likely billing): {e}")
        return "AI analysis unavailable — check Anthropic billing"
    except anthropic.AuthenticationError as e:
        log.error(f"Claude API auth failed (bad key?): {e}")
        return "AI analysis unavailable — invalid API key"
    except anthropic.RateLimitError as e:
        log.error(f"Claude API rate limited: {e}")
        return "AI analysis unavailable — rate limited"
    except Exception as e:
        log.error(f"Claude API call failed ({type(e).__name__}): {e}")
        return "AI analysis unavailable"

# ─── Telegram ────────────────────────────────────────────────────────────────────

def send_telegram(bot_token: str, chat_id: str, html_message: str) -> bool:
    """Send an HTML-formatted message via Telegram Bot API."""
    try:
        with httpx.Client() as client:
            r = client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": html_message,
                    "parse_mode": "HTML",
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False

# ─── Report Formatting ───────────────────────────────────────────────────────────

def format_sign(v: float) -> str:
    return "+" if v >= 0 else ""


def format_report(
    portfolio: dict | None,
    positions: list | None,
    trades: list | None,
    dashboard: dict | None,
    metrics: dict,
    news: list | None,
    narrative: str,
    supertrend: str | None,
) -> str:
    """Build the HTML-formatted Telegram report."""
    now = datetime.now(timezone.utc)
    # Use local time for display (ET)
    try:
        from zoneinfo import ZoneInfo
        local_now = now.astimezone(ZoneInfo("America/New_York"))
        # %#I is Windows no-pad; %-I is Unix no-pad
        hour = local_now.hour % 12 or 12
        time_str = f"{hour}:{local_now.strftime('%M %p')}"
    except Exception:
        time_str = now.strftime("%H:%M") + " UTC"

    SEP = "\u2501" * 20  # ━━━━━━━━━━━━━━━━━━━━

    lines = []

    # ── Header ──
    lines.append(SEP)
    lines.append(f"  \U0001f4ca  <b>HYPERTRADER</b>  \u00b7  {time_str}")
    lines.append(SEP)

    # ── 1. BTC Market ──
    lines.append("")
    lines.append("<b>BTC Market</b>")
    if metrics:
        price = metrics.get("current_price")
        change = metrics.get("hourly_change_pct")
        if price:
            change_arrow = "\u25bc" if (change is not None and change < 0) else "\u25b2"
            change_str = f"{abs(change):.2f}%" if change is not None else "0.00%"
            lines.append(f"\u20bf  ${price:,.0f}  {change_arrow} {change_str}")

        regime = metrics.get("regime", "Flat")
        volume = metrics.get("volume", "Normal")
        volatility = metrics.get("volatility", "Medium")

        regime_emoji = "\U0001f4c8" if regime == "Trending Up" else "\U0001f4c9" if regime == "Trending Down" else "\u27a1\ufe0f"
        lines.append(f"{regime_emoji}  {regime}  \u00b7  {volume} volume  \u00b7  {volatility} volatility")
    else:
        lines.append("\u20bf  Market data unavailable")

    # ── 2. Account ──
    lines.append("")
    lines.append(SEP)
    lines.append("")
    lines.append("<b>Account</b>")

    if portfolio:
        acct_val = portfolio.get("account_value", 0)
        upnl = portfolio.get("total_unrealized_pnl", 0)
        upnl_arrow = "\u25b2" if upnl >= 0 else "\u25bc"
        upnl_str = f"{format_sign(upnl)}${abs(upnl):,.2f}"
        margin = portfolio.get("total_margin_used", 0)
        if acct_val > 0 and margin > 0:
            pnl_pct = (upnl / (acct_val - upnl)) * 100 if (acct_val - upnl) > 0 else 0
            pnl_pct_str = f" ({format_sign(pnl_pct)}{abs(pnl_pct):.2f}%)"
        else:
            pnl_pct_str = f" ({0:.2f}%)"
        lines.append(f"\U0001f4b0  ${acct_val:,.2f}  {upnl_arrow} {upnl_str}{pnl_pct_str}")

        if dashboard:
            daily_pnl = dashboard.get("daily_pnl") or dashboard.get("today_pnl")
            if daily_pnl is not None:
                daily_arrow = "\u25b2" if daily_pnl >= 0 else "\u25bc"
                lines.append(f"     Daily P&L: {daily_arrow} {format_sign(daily_pnl)}${abs(daily_pnl):,.2f}")

        if margin > 0:
            available = portfolio.get("available_balance", 0)
            lines.append(f"     Margin: ${margin:,.2f}  \u00b7  Free: ${available:,.2f}")
    else:
        lines.append("\U0001f4b0  Portfolio unavailable")

    # ── Positions ──
    if positions:
        lines.append("")
        for p in positions:
            sym = p.get("symbol", "?")
            side = p.get("side", "?").upper()
            leverage = p.get("leverage", 1)
            entry = p.get("entry_price", 0)
            pnl = p.get("unrealized_pnl", 0)
            margin_used = p.get("margin_used", 0)
            pnl_pct = (pnl / margin_used * 100) if margin_used > 0 else 0
            side_emoji = "\U0001f4c8" if side == "LONG" else "\U0001f4c9"
            pnl_sign = format_sign(pnl)
            lines.append(
                f"{side_emoji}  {sym} {side} {leverage:.0f}x @ ${entry:,.2f}"
            )
            lines.append(
                f"     P&L: {pnl_sign}${abs(pnl):,.2f} ({pnl_sign}{abs(pnl_pct):.1f}%)"
            )
    else:
        lines.append("No open positions")

    # ── 3. Headlines ──
    if news:
        lines.append("")
        lines.append(SEP)
        lines.append("")
        lines.append("<b>Headlines</b>")
        for headline in news[:3]:
            lines.append(f"\U0001f4f0  {headline}")

    # ── 4. Market Context (Claude narrative) ──
    lines.append("")
    lines.append(SEP)
    lines.append("")
    lines.append("<b>Market Context</b>")
    lines.append(f"<i>{narrative}</i>")

    # ── 5. Trading Activity ──
    lines.append("")
    lines.append(SEP)
    lines.append("")
    lines.append("<b>Trading</b>")
    if trades and len(trades) > 0:
        lines.append(f"\U0001f916  {len(trades)} trade{'s' if len(trades) != 1 else ''} this hour")
    else:
        lines.append("\U0001f916  No trades this hour")

    if supertrend:
        signal_emoji = "\U0001f7e2" if supertrend == "Bullish" else "\U0001f534"
        lines.append(f"Last signal: {signal_emoji} {supertrend}")
    else:
        lines.append("Last signal: None")

    # ── 6. System Health Footer ──
    lines.append("")
    lines.append("<b>System</b>")

    failed = []
    if portfolio is None:
        failed.append("API")
    if not metrics:
        failed.append("Market")
    if news is None:
        failed.append("News")

    if not failed:
        lines.append(f"\u2705 All systems healthy")
    else:
        lines.append(f"\u26a0\ufe0f Unavailable: {', '.join(failed)}")

    lines.append(SEP)

    return "\n".join(lines)

# ─── Main ────────────────────────────────────────────────────────────────────────

def main():
    setup_logging()
    log.info("=" * 60)
    log.info("Hourly Market Intelligence Report starting")

    # Load config
    env = load_env(ENV_PATH)
    cryptopanic_key = env.get("CRYPTOPANIC_API_KEY", "")
    anthropic_key = env.get("ANTHROPIC_API_KEY", "")

    try:
        bot_token, chat_id = load_telegram_creds()
    except Exception as e:
        log.error(f"Cannot load Telegram credentials: {e}")
        sys.exit(1)

    # Gather data in parallel
    results = {}
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(fetch_portfolio, client): "portfolio",
                pool.submit(fetch_positions, client): "positions",
                pool.submit(fetch_recent_trades, client): "trades",
                pool.submit(fetch_dashboard, client): "dashboard",
                pool.submit(fetch_btc_candles, client): "candles",
                pool.submit(fetch_btc_price, client): "btc_price",
                pool.submit(fetch_news, client, cryptopanic_key): "news",
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    log.warning(f"Data fetch '{key}' raised: {e}")
                    results[key] = None

    # Calculate derived metrics
    candles = results.get("candles")
    btc_price = results.get("btc_price")
    metrics = calculate_market_metrics(candles, btc_price) if candles else {}

    # Extract supertrend direction from trades
    supertrend = extract_supertrend_direction(results.get("trades"))

    # Generate Claude narrative
    narrative = generate_narrative(
        anthropic_key,
        results.get("portfolio"),
        results.get("positions"),
        results.get("trades"),
        results.get("dashboard"),
        metrics,
        results.get("news"),
        supertrend,
    )

    # Format report
    report = format_report(
        results.get("portfolio"),
        results.get("positions"),
        results.get("trades"),
        results.get("dashboard"),
        metrics,
        results.get("news"),
        narrative,
        supertrend,
    )

    log.info("Report generated:")
    log.info(report)

    # Send to Telegram
    if send_telegram(bot_token, chat_id, report):
        log.info("Report sent to Telegram successfully")
    else:
        log.error("Failed to send report to Telegram — report logged above")

    log.info("Done")


if __name__ == "__main__":
    main()
