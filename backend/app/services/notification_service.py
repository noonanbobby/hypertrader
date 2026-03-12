import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Sends Telegram notifications for trade events. Fire-and-forget — never blocks trades."""

    async def notify_trade_open(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        strategy_name: str,
        fill_type: str = "taker",
        leverage: float = 10.0,
    ):
        if not settings.notify_trade_open:
            return
        emoji = "\U0001f7e2" if side == "long" else "\U0001f534"
        ticker = symbol.replace("USDC", "").replace("USDT", "")
        notional = price * quantity
        margin = notional / leverage if leverage else notional
        text = (
            f"{emoji} {side.upper()} {symbol} @ ${price:,.2f}\n"
            f"Size: {quantity} {ticker} (${notional:,.2f})\n"
            f"Invested: ${margin:,.2f} ({leverage:.0f}x leverage)\n"
            f"Strategy: {strategy_name}\n"
            f"Fill: {fill_type}"
        )
        await self._send_telegram(text)

    async def notify_trade_close(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
        strategy_name: str,
        leverage: float = 10.0,
    ):
        if not settings.notify_trade_close:
            return
        pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
        if side == "short":
            pnl_pct = -pnl_pct
        sign = "+" if pnl >= 0 else ""
        emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
        ticker = symbol.replace("USDC", "").replace("USDT", "")
        notional_entry = entry_price * quantity
        notional_exit = exit_price * quantity
        margin = notional_entry / leverage if leverage else notional_entry
        text = (
            f"{emoji} Closed {side.upper()} {symbol} @ ${exit_price:,.2f}\n"
            f"\n"
            f"Summary:\n"
            f"  Entry: ${entry_price:,.2f} \u2192 Exit: ${exit_price:,.2f}\n"
            f"  Size: {quantity} {ticker}\n"
            f"  Notional: ${notional_entry:,.2f} \u2192 ${notional_exit:,.2f}\n"
            f"  Invested: ${margin:,.2f} ({leverage:.0f}x leverage)\n"
            f"\n"
            f"P&L: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)\n"
            f"Strategy: {strategy_name}"
        )
        await self._send_telegram(text)

    async def notify_risk_breach(
        self,
        strategy_name: str,
        symbol: str,
        reason: str,
    ):
        if not settings.notify_risk_breach:
            return
        text = (
            f"\u26d4 Trade BLOCKED: {symbol}\n"
            f"Reason: {reason}\n"
            f"Strategy: {strategy_name}"
        )
        await self._send_telegram(text)

    async def send_test_message(self) -> dict:
        """Send a test message and return success/failure info."""
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return {"success": False, "message": "Bot token and chat ID are required."}
        try:
            await self._send_telegram("\u2705 HyperTrader Telegram notifications are working!")
            return {"success": True, "message": "Test message sent successfully."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _send_telegram(self, text: str):
        if not settings.telegram_enabled:
            return
        token = settings.telegram_bot_token
        if not token:
            return
        chat_ids = [cid for cid in [settings.telegram_chat_id, settings.telegram_chat_id_2] if cid]
        if not chat_ids:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for chat_id in chat_ids:
                    resp = await client.post(url, json={"chat_id": chat_id, "text": text})
                    if resp.status_code != 200:
                        logger.warning(f"Telegram API error for {chat_id}: {resp.status_code}: {resp.text}")
        except Exception:
            logger.exception("Failed to send Telegram notification")


notifier = NotificationService()
