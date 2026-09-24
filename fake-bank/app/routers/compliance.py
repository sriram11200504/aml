from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from ..database import get_db
from ..models import Account, ComplianceLog
from ..schemas import FreezeRequest, ComplianceLogResponse
from ..config import get_settings

router = APIRouter(prefix="/compliance", tags=["compliance"])
settings = get_settings()


def verify_compliance_key(x_api_key: str = Header(...)):
    if x_api_key != settings.compliance_api_key:
        raise HTTPException(status_code=401, detail="Invalid compliance API key")


@router.post("/accounts/{account_id}/freeze")
async def freeze_account(
    account_id: int,
    req: FreezeRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_compliance_key),
):
    result = await db.execute(select(Account).where(Account.account_id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.status = "restricted"

    log = ComplianceLog(
        account_id=account_id,
        action="freeze",
        case_id=req.case_id,
        reason=req.reason,
    )
    db.add(log)
    await db.commit()

    return {"account_id": account_id, "status": "frozen"}


@router.post("/accounts/{account_id}/unfreeze")
async def unfreeze_account(
    account_id: int,
    req: FreezeRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_compliance_key),
):
    result = await db.execute(select(Account).where(Account.account_id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.status = "active"

    log = ComplianceLog(
        account_id=account_id,
        action="unfreeze",
        case_id=req.case_id,
        reason=req.reason,
    )
    db.add(log)
    await db.commit()

    return {"account_id": account_id, "status": "active"}


@router.get("/log", response_model=List[ComplianceLogResponse])
async def compliance_log(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_compliance_key),
):
    result = await db.execute(
        select(ComplianceLog).order_by(ComplianceLog.timestamp.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/log/public", response_model=List[ComplianceLogResponse])
async def compliance_log_public(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Public compliance log for admin dashboard (no key required)."""
    result = await db.execute(
        select(ComplianceLog).order_by(ComplianceLog.timestamp.desc()).limit(limit)
    )
    return result.scalars().all()
