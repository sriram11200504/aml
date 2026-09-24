"""
AML ingest router. Validates API key, deduplicates, stores, queues for scoring.
"""
from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import AMLTransaction, AMLAccount, BankRegistration
from ..schemas import IngestSingle, IngestBatch
from ..config import get_settings
from ..worker import get_score_queue

import logging
from datetime import datetime

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])
logger = logging.getLogger(__name__)
settings = get_settings()
_key_map = settings.parse_ingest_keys()  # {api_key: bank_id}


def verify_bank_key(x_api_key: str = Header(...)):
    if x_api_key not in _key_map:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return _key_map[x_api_key]


async def store_transaction(session: AsyncSession, bank_id: str, item, source: str = "live") -> bool:
    """Store a transaction. Returns True if new, False if duplicate."""
    tx = item.transaction

    # Idempotency check
    existing = await session.execute(
        select(AMLTransaction).where(AMLTransaction.id == tx.id)
    )
    if existing.scalar_one_or_none():
        return False

    aml_tx = AMLTransaction(
        id=tx.id,
        bank_id=bank_id,
        timestamp=tx.timestamp.replace(tzinfo=None),
        sender=tx.sender_account,
        receiver=tx.receiver_account,
        amount=tx.amount,
        payment_currency=tx.payment_currency,
        received_currency=tx.received_currency,
        sender_bank_location=tx.sender_bank_location,
        receiver_bank_location=tx.receiver_bank_location,
        payment_type=tx.payment_type,
        scored=False,
        source=source,
    )
    session.add(aml_tx)

    # Upsert accounts
    for acc_id, profile in [
        (tx.sender_account, item.sender_profile),
        (tx.receiver_account, item.receiver_profile),
    ]:
        if acc_id == 0:
            continue
        existing_acc = await session.execute(
            select(AMLAccount).where(
                AMLAccount.bank_id == bank_id,
                AMLAccount.account_id == acc_id,
            )
        )
        acc_row = existing_acc.scalar_one_or_none()
        if acc_row:
            acc_row.last_seen = datetime.utcnow()
            if profile:
                acc_row.holder_name = profile.holder_name
                acc_row.status = profile.account_status
        else:
            session.add(AMLAccount(
                bank_id=bank_id,
                account_id=acc_id,
                holder_name=profile.holder_name if profile else None,
                status=profile.account_status if profile else "unknown",
            ))

    await session.commit()
    return True


@router.post("/transactions")
async def ingest_single(
    body: IngestSingle,
    bank_id: str = Depends(verify_bank_key),
    db: AsyncSession = Depends(get_db),
):
    is_new = await store_transaction(db, bank_id, body)
    if is_new:
        q = get_score_queue()
        await q.put(body.transaction.id)
        logger.info("Ingested transaction %s from bank %s", body.transaction.id, bank_id)
    else:
        logger.info("Duplicate transaction %s, ignored", body.transaction.id)
    return {"accepted": True}


@router.post("/transactions/batch")
async def ingest_batch(
    body: IngestBatch,
    bank_id: str = Depends(verify_bank_key),
    db: AsyncSession = Depends(get_db),
):
    count = 0
    q = get_score_queue()
    for item in body.transactions:
        is_new = await store_transaction(db, bank_id, item)
        if is_new:
            await q.put(item.transaction.id)
            count += 1
    return {"accepted": True, "count": count}
