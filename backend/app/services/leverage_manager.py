"""
Leverage Manager — Production leverage and margin mode management.

- On startup: set leverage + isolated margin for all configured assets.
- Post-trade: verify leverage matches config, warn on mismatch.
- Daily: reconcile leverage for all assets, auto-correct mismatches.
"""

import asyncio
import logging

from app.config import settings
from app.database import async_session
from app.models import AssetConfig
from app.services.notification_service import notifier

from sqlalchemy import select

logger = logging.getLogger(__name__)

DAILY_CHECK_INTERVAL = 86400  # 24 hours


async def _get_exchange():
    """Get the Hyperliquid Exchange SDK client."""
    import eth_account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants

    if not settings.hl_api_key or not settings.hl_api_secret:
        return None

    wallet = eth_account.Account.from_key(settings.hl_api_secret)
    vault = settings.hl_vault_address or None
    return Exchange(
        wallet,
        constants.MAINNET_API_URL,
        account_address=settings.hl_api_key,
        vault_address=vault,
    )


async def _set_leverage(exchange, coin: str, leverage: int, has_position: bool = False) -> tuple[bool, str]:
    """Set leverage for a single asset. Uses isolated margin when no position, keeps current mode if position open."""
    try:
        # HL won't switch margin mode (cross↔isolated) with an open position.
        # If there's a position, just change the leverage value (keep current mode).
        # If flat, set isolated margin.
        is_cross = has_position  # keep cross if position open, use isolated if flat
        result = await asyncio.to_thread(
            exchange.update_leverage, leverage, coin, is_cross
        )
        if isinstance(result, dict) and result.get("status") == "err":
            return False, result.get("response", str(result))
        mode = "cross (position open)" if has_position else "isolated"
        return True, f"{coin} → {leverage}x {mode}"
    except Exception as e:
        return False, f"{coin} error: {e}"


async def sync_leverage_on_startup():
    """Called once at startup. Sets leverage + isolated margin for all configured assets."""
    exchange = await _get_exchange()
    if exchange is None:
        logger.warning("Leverage sync skipped — HL credentials not configured")
        return

    async with async_session() as db:
        result = await db.execute(select(AssetConfig).where(AssetConfig.enabled == True))
        assets = result.scalars().all()

    if not assets:
        logger.info("No enabled assets for leverage sync")
        return

    # Check which assets have open positions (can't switch margin mode)
    from app.services.hl_account import hl_account
    try:
        hl_positions = await hl_account.get_open_positions()
    except Exception:
        hl_positions = []
    positioned_coins = {p["symbol"] for p in hl_positions}

    logger.info("Setting leverage on startup for %d assets...", len(assets))
    results = []

    for asset in assets:
        has_pos = asset.coin in positioned_coins
        ok, msg = await _set_leverage(exchange, asset.coin, asset.leverage, has_position=has_pos)
        status = "✓" if ok else "✗"
        results.append(f"{status} {msg}")
        if ok:
            logger.info("Leverage set: %s", msg)
        else:
            logger.warning("Leverage set FAILED: %s", msg)

    # Send Telegram summary
    summary = "🔧 Leverage sync on startup:\n" + "\n".join(results)
    asyncio.create_task(notifier._send_telegram(summary))


async def verify_leverage_post_trade(coin: str):
    """Called after every successful trade. Checks leverage matches config."""
    try:
        from app.services.hl_account import hl_account
        positions = await hl_account.get_open_positions()
        hl_pos = next((p for p in positions if p["symbol"] == coin), None)
        if not hl_pos:
            return  # no position to check

        async with async_session() as db:
            result = await db.execute(select(AssetConfig).where(AssetConfig.coin == coin))
            asset = result.scalar_one_or_none()

        if not asset:
            return

        hl_lev = int(hl_pos["leverage"])
        db_lev = asset.leverage

        if hl_lev != db_lev:
            logger.warning(
                "LEVERAGE MISMATCH: %s — HL=%dx, config=%dx",
                coin, hl_lev, db_lev,
            )
            asyncio.create_task(notifier._send_telegram(
                f"⚠️ Leverage mismatch on {coin}\n"
                f"Hyperliquid: {hl_lev}x | Config: {db_lev}x\n"
                f"Will be corrected on next daily check."
            ))
    except Exception as e:
        logger.warning("Post-trade leverage check failed for %s: %s", coin, e)


async def daily_leverage_check_loop():
    """Background loop — every 24 hours, verify and correct leverage for all assets."""
    # Wait 5 minutes after startup before first check (startup sync already ran)
    await asyncio.sleep(300)

    while True:
        try:
            await _run_daily_check()
        except Exception:
            logger.exception("Daily leverage check failed")
        await asyncio.sleep(DAILY_CHECK_INTERVAL)


async def _run_daily_check():
    """Single daily check — verify and correct leverage for all assets."""
    exchange = await _get_exchange()
    if exchange is None:
        return

    from app.services.hl_account import hl_account

    async with async_session() as db:
        result = await db.execute(select(AssetConfig).where(AssetConfig.enabled == True))
        assets = result.scalars().all()

    if not assets:
        return

    corrections = []

    for asset in assets:
        # Check if there's a position with wrong leverage
        try:
            positions = await hl_account.get_open_positions()
            hl_pos = next((p for p in positions if p["symbol"] == asset.coin), None)

            if hl_pos:
                hl_lev = int(hl_pos["leverage"])
                if hl_lev != asset.leverage:
                    ok, msg = await _set_leverage(exchange, asset.coin, asset.leverage, has_position=True)
                    if ok:
                        corrections.append(f"✓ {asset.coin}: corrected {hl_lev}x → {asset.leverage}x")
                        logger.info("Daily check corrected %s: %dx → %dx", asset.coin, hl_lev, asset.leverage)
                    else:
                        corrections.append(f"✗ {asset.coin}: correction failed — {msg}")
                        logger.warning("Daily check correction failed for %s: %s", asset.coin, msg)
            else:
                # No position — set isolated margin for next trade
                ok, msg = await _set_leverage(exchange, asset.coin, asset.leverage, has_position=False)
                if ok:
                    logger.debug("Daily check: %s leverage confirmed %dx isolated", asset.coin, asset.leverage)
        except Exception as e:
            logger.warning("Daily check error for %s: %s", asset.coin, e)

    if corrections:
        asyncio.create_task(notifier._send_telegram(
            "🔧 Daily leverage check:\n" + "\n".join(corrections)
        ))
    else:
        logger.info("Daily leverage check — all assets correct")
