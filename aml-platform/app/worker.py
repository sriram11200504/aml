"""
Monitor worker: scores transactions and creates/updates cases.
Runs as a background asyncio task.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import httpx
from sqlalchemy import select, and_, or_

from .database import AsyncSessionLocal
from .models import AMLTransaction, Case, CaseTransaction, AuditLog
from .config import get_settings
from .ws_manager import manager

logger = logging.getLogger(__name__)

# In-memory state
_model_online = True
_unscored_count = 0

SCORE_TIMEOUT = 3.0
WORKER_POLL_INTERVAL = 1.0
HISTORY_DAYS = 7
HISTORY_MAX = 1000


def get_model_status():
    return {"online": _model_online, "unscored": _unscored_count}


async def build_history(session, account_id: int, before: datetime) -> List[dict]:
    """Build transaction history for an account: last 7 days BEFORE `before`, max 1000."""
    cutoff = before - timedelta(days=HISTORY_DAYS)
    result = await session.execute(
        select(AMLTransaction)
        .where(
            and_(
                or_(
                    AMLTransaction.sender == account_id,
                    AMLTransaction.receiver == account_id,
                ),
                AMLTransaction.timestamp < before,
                AMLTransaction.timestamp >= cutoff,
            )
        )
        .order_by(AMLTransaction.timestamp.desc())
        .limit(HISTORY_MAX)
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() + "Z",
            "sender_account": r.sender,
            "receiver_account": r.receiver,
            "amount": r.amount,
            "payment_currency": r.payment_currency,
            "received_currency": r.received_currency,
            "sender_bank_location": r.sender_bank_location,
            "receiver_bank_location": r.receiver_bank_location,
            "payment_type": r.payment_type,
        }
        for r in rows
    ]


async def call_model(tx: AMLTransaction, sender_history: list, receiver_history: list) -> Optional[dict]:
    global _model_online
    settings = get_settings()
    payload = {
        "transaction": {
            "id": tx.id,
            "timestamp": tx.timestamp.isoformat() + "Z",
            "sender_account": tx.sender,
            "receiver_account": tx.receiver,
            "amount": tx.amount,
            "payment_currency": tx.payment_currency,
            "received_currency": tx.received_currency,
            "sender_bank_location": tx.sender_bank_location,
            "receiver_bank_location": tx.receiver_bank_location,
            "payment_type": tx.payment_type,
        },
        "sender_history": sender_history,
        "receiver_history": receiver_history,
    }
    try:
        async with httpx.AsyncClient(timeout=SCORE_TIMEOUT) as client:
            resp = await client.post(f"{settings.model_api_url}/v1/score", json=payload)
        resp.raise_for_status()
        _model_online = True
        return resp.json()
    except Exception as exc:
        _model_online = False
        logger.warning("Model API unavailable for tx %s: %s", tx.id, exc)
        return None


async def process_transaction(tx_id: str):
    """Score one transaction and create/update case."""
    global _unscored_count
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AMLTransaction).where(AMLTransaction.id == tx_id)
        )
        tx = result.scalar_one_or_none()
        if not tx or tx.scored:
            return

        sender_hist = await build_history(session, tx.sender, tx.timestamp)
        receiver_hist = await build_history(session, tx.receiver, tx.timestamp)

        model_result = await call_model(tx, sender_hist, receiver_hist)
        if model_result is None:
            _unscored_count += 1
            return  # Will retry later

        risk_score = model_result.get("risk_score", 0.0)
        typology = model_result.get("typology")
        reasons = model_result.get("reasons", [])
        model_version = model_result.get("model_version", "unknown")
        risk_level = settings.risk_level(risk_score)

        tx.scored = True
        tx.risk_score = risk_score
        tx.risk_level = risk_level
        tx.typology = typology
        tx.reasons_json = json.dumps(reasons)
        tx.model_version = model_version
        tx.scored_at = datetime.utcnow()

        if _unscored_count > 0:
            _unscored_count -= 1

        await session.commit()

        # Broadcast transaction update
        await manager.broadcast_transaction({
            "type": "transaction_scored",
            "transaction_id": tx.id,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "typology": typology,
        })

        # Case management
        if risk_level != "Low":
            await create_or_update_case(session, tx, risk_score, risk_level, typology, reasons)


async def create_or_update_case(session, tx: AMLTransaction, risk_score: float, risk_level: str, typology: Optional[str], reasons: list):
    """Create a new case or update an existing one for (account, typology)."""
    # Focus on sender account as primary subject
    account_id = tx.sender

    # Look for an existing open/investigating case for this account + typology
    result = await session.execute(
        select(Case).where(
            and_(
                Case.bank_id == tx.bank_id,
                Case.account_id == account_id,
                Case.typology == typology,
                Case.status.in_(["open", "investigating"]),
            )
        ).limit(1)
    )
    existing_case = result.scalar_one_or_none()

    if existing_case:
        # Update if new score is higher
        if risk_score > existing_case.risk_score:
            existing_case.risk_score = risk_score
            existing_case.risk_level = risk_level
        existing_case.updated_at = datetime.utcnow()

        # Add this transaction to the case if not already there
        ct_check = await session.execute(
            select(CaseTransaction).where(
                and_(
                    CaseTransaction.case_id == existing_case.id,
                    CaseTransaction.transaction_id == tx.id,
                )
            )
        )
        if not ct_check.scalar_one_or_none():
            session.add(CaseTransaction(case_id=existing_case.id, transaction_id=tx.id))

        await session.commit()
        case_id = existing_case.id
        is_new = False
    else:
        case_id = f"case_{uuid.uuid4().hex[:12]}"
        new_case = Case(
            id=case_id,
            bank_id=tx.bank_id,
            account_id=account_id,
            typology=typology,
            risk_level=risk_level,
            risk_score=risk_score,
            status="open",
        )
        session.add(new_case)
        session.add(CaseTransaction(case_id=case_id, transaction_id=tx.id))

        # If it's a fan-out/fan-in pattern, add earlier related transactions to the case
        if typology in ("Fan_Out", "Fan_In", "Structuring", "Cycle", "Rapid_Pass_Through"):
            await add_related_transactions(session, case_id, tx, typology)

        await session.commit()
        is_new = True

    # Broadcast alert
    await manager.broadcast_alert({
        "type": "case_created" if is_new else "case_updated",
        "case_id": case_id,
        "account_id": account_id,
        "bank_id": tx.bank_id,
        "typology": typology,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "transaction_id": tx.id,
        "reasons": reasons,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })

    logger.info(
        "Case %s (%s): %s account=%s score=%.2f",
        case_id, "NEW" if is_new else "UPD", typology, account_id, risk_score
    )


async def add_related_transactions(session, case_id: str, tx: AMLTransaction, typology: str):
    """Add earlier transactions to the case that are part of the same pattern."""
    cutoff = tx.timestamp - timedelta(days=7)

    if typology in ("Fan_Out",):
        # All outgoing transfers from the same sender in last 24h
        result = await session.execute(
            select(AMLTransaction).where(
                and_(
                    AMLTransaction.sender == tx.sender,
                    AMLTransaction.timestamp >= tx.timestamp - timedelta(hours=24),
                    AMLTransaction.timestamp <= tx.timestamp,
                    AMLTransaction.id != tx.id,
                )
            )
        )
    elif typology in ("Fan_In",):
        result = await session.execute(
            select(AMLTransaction).where(
                and_(
                    AMLTransaction.receiver == tx.receiver,
                    AMLTransaction.timestamp >= tx.timestamp - timedelta(hours=24),
                    AMLTransaction.timestamp <= tx.timestamp,
                    AMLTransaction.id != tx.id,
                )
            )
        )
    else:
        result = await session.execute(
            select(AMLTransaction).where(
                and_(
                    or_(
                        AMLTransaction.sender == tx.sender,
                        AMLTransaction.receiver == tx.sender,
                    ),
                    AMLTransaction.timestamp >= cutoff,
                    AMLTransaction.timestamp <= tx.timestamp,
                    AMLTransaction.id != tx.id,
                )
            ).limit(50)
        )

    related = result.scalars().all()
    for r in related:
        ct_check = await session.execute(
            select(CaseTransaction).where(
                and_(
                    CaseTransaction.case_id == case_id,
                    CaseTransaction.transaction_id == r.id,
                )
            )
        )
        if not ct_check.scalar_one_or_none():
            session.add(CaseTransaction(case_id=case_id, transaction_id=r.id))


async def retry_unscored():
    """Retry all unscored transactions."""
    global _unscored_count
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AMLTransaction).where(AMLTransaction.scored == False).limit(50)
        )
        rows = result.scalars().all()
        _unscored_count = len(rows)
        for row in rows:
            await process_transaction(row.id)


async def monitor_worker():
    """Main worker loop."""
    logger.info("Monitor worker started")
    retry_counter = 0
    while True:
        try:
            await asyncio.sleep(WORKER_POLL_INTERVAL)
            retry_counter += 1
            # Every 10 seconds, retry unscored
            if retry_counter % 10 == 0:
                await retry_unscored()
        except Exception as exc:
            logger.error("Monitor worker error: %s", exc)
            await asyncio.sleep(5)


# Queue for new transactions to score immediately
_score_queue: asyncio.Queue = None


def get_score_queue() -> asyncio.Queue:
    global _score_queue
    if _score_queue is None:
        _score_queue = asyncio.Queue()
    return _score_queue


async def score_worker():
    """Consume score queue immediately."""
    logger.info("Score worker started")
    q = get_score_queue()
    while True:
        try:
            tx_id = await asyncio.wait_for(q.get(), timeout=5.0)
            await process_transaction(tx_id)
            q.task_done()
        except asyncio.TimeoutError:
            pass
        except Exception as exc:
            logger.error("Score worker error: %s", exc)
            await asyncio.sleep(1)
