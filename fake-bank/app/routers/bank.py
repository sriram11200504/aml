from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from ..database import get_db
from ..models import Account, Transaction, Outbox
from ..schemas import AccountResponse, TransactionResponse, OutboxStatsResponse
from ..transfers import execute_transfer
from ..schemas import TransferRequest, BulkTransferRequest

router = APIRouter(prefix="/api", tags=["bank"])


@router.get("/accounts", response_model=List[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).order_by(Account.account_id))
    return result.scalars().all()


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.account_id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/accounts/{account_id}/transactions", response_model=List[TransactionResponse])
async def get_account_transactions(
    account_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction)
        .where(
            (Transaction.sender_account == account_id)
            | (Transaction.receiver_account == account_id)
        )
        .order_by(Transaction.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/transfer")
async def transfer(req: TransferRequest, db: AsyncSession = Depends(get_db)):
    result = await execute_transfer(
        session=db,
        sender_account=req.sender_account,
        receiver_account=req.receiver_account,
        amount=req.amount,
        payment_type=req.payment_type.value,
        payment_currency=req.payment_currency,
        received_currency=req.received_currency,
        receiver_bank_location=req.receiver_bank_location,
        note=req.note,
        test_funding=req.test_funding,
    )
    if not result["success"]:
        return {"success": False, "message": result["message"]}
    return result


@router.post("/transfer/bulk")
async def bulk_transfer(req: BulkTransferRequest, db: AsyncSession = Depends(get_db)):
    results = []
    for item in req.transfers:
        r = await execute_transfer(
            session=db,
            sender_account=req.sender_account,
            receiver_account=item.receiver_account,
            amount=item.amount,
            payment_type=item.payment_type.value,
            payment_currency=item.payment_currency,
            received_currency=item.received_currency,
            receiver_bank_location=item.receiver_bank_location,
            note=item.note,
            test_funding=req.test_funding,
        )
        results.append(r)
    return {"results": results, "total": len(results)}


@router.get("/outbox/stats", response_model=OutboxStatsResponse)
async def outbox_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Outbox.status, func.count(Outbox.id).label("cnt")).group_by(Outbox.status)
    )
    rows = result.all()
    counts = {row.status: row.cnt for row in rows}
    total = sum(counts.values())
    return {
        "pending": counts.get("pending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "total": total,
    }


@router.get("/transactions", response_model=List[TransactionResponse])
async def list_transactions(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Transaction).order_by(Transaction.timestamp.desc()).limit(limit)
    )
    return result.scalars().all()
