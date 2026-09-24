"""
Outbox dispatcher – runs as a background asyncio task.
Polls the outbox table for pending rows and POSTs them to the AML platform.
Uses exponential backoff. Never blocks transfers.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, update

from .database import AsyncSessionLocal
from .models import Outbox
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_ATTEMPTS = 20
BASE_DELAY = 2  # seconds
MAX_DELAY = 300  # 5 minutes


async def dispatch_one(session, row: Outbox) -> bool:
    """Try to dispatch a single outbox row. Returns True on success."""
    try:
        payload = json.loads(row.payload_json)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.aml_url}/api/v1/ingest/transactions",
                json=payload,
                headers={"X-API-Key": settings.aml_api_key},
            )
        if resp.status_code in (200, 202):
            await session.execute(
                update(Outbox)
                .where(Outbox.id == row.id)
                .values(status="sent", last_error=None)
            )
            await session.commit()
            logger.info("Outbox row %s dispatched successfully", row.id)
            return True
        else:
            raise ValueError(f"AML returned {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        attempts = row.attempts + 1
        delay = min(BASE_DELAY * (2 ** attempts), MAX_DELAY)
        next_retry = datetime.utcnow() + timedelta(seconds=delay)
        new_status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        await session.execute(
            update(Outbox)
            .where(Outbox.id == row.id)
            .values(
                attempts=attempts,
                status=new_status,
                next_retry_at=next_retry,
                last_error=str(exc)[:500],
            )
        )
        await session.commit()
        logger.warning("Outbox row %s failed (attempt %d): %s", row.id, attempts, exc)
        return False


async def outbox_dispatcher():
    """Main dispatcher loop. Runs forever in the background."""
    logger.info("Outbox dispatcher started")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.utcnow()
                result = await session.execute(
                    select(Outbox)
                    .where(Outbox.status == "pending")
                    .where((Outbox.next_retry_at == None) | (Outbox.next_retry_at <= now))
                    .order_by(Outbox.id)
                    .limit(20)
                )
                rows = result.scalars().all()

            if rows:
                for row in rows:
                    await dispatch_one(session, row)
                    await asyncio.sleep(0.1)  # small gap between dispatches
            else:
                await asyncio.sleep(2)  # nothing to do, poll again in 2s
        except Exception as exc:
            logger.error("Dispatcher loop error: %s", exc)
            await asyncio.sleep(5)
