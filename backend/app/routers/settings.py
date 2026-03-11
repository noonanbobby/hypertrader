import datetime as dt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings, RUNTIME_FIELDS, _env_settings
from app.models import AppSettings
from app.schemas import SettingsResponse, SettingsUpdate

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
