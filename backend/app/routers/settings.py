import asyncio
import logging
import datetime as dt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings, RUNTIME_FIELDS, _env_settings
from app.models import AppSettings
from app.schemas import SettingsResponse, SettingsUpdate
from app.services.notification_service import notifier

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_or_create_row(db: AsyncSession) -> AppSettings:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppSettings(
            id=1,
            **{field: getattr(_env_settings, field) for field in RUNTIME_FIELDS},
            updated_at=dt.datetime.utcnow(),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_row(db)
    return SettingsResponse.from_row(row)


@router.patch("/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_row(db)
    updates = body.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(row, field, value)
    row.updated_at = dt.datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    # Sync in-memory singleton immediately
    settings.update_from_db_row(row)
    return SettingsResponse.from_row(row)


@router.post("/settings/test-telegram")
async def test_telegram():
    """Send a test Telegram message to verify bot token + chat ID."""
    return await notifier.send_test_message()


@router.get("/settings/test-connection")
async def test_connection():
    """Verify Hyperliquid API credentials by fetching account state."""
    if not settings.hl_api_secret or not settings.hl_api_key:
        return {
            "success": False,
            "message": "API credentials not configured. Set hl_api_key and hl_api_secret in settings.",
        }

    try:
        import eth_account
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        # Validate the private key
        eth_account.Account.from_key(settings.hl_api_secret)

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        state = await asyncio.to_thread(info.user_state, settings.hl_api_key)

        balance = float(state["marginSummary"]["accountValue"])
        return {
            "success": True,
            "message": f"Connected. Account equity: ${balance:,.2f}",
            "balance": balance,
        }
    except Exception as e:
        logger.exception("Connection test failed")
        return {"success": False, "message": str(e)}
