"""
AML cases, accounts, metrics, settings, SAR routes.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
import json
import uuid
from datetime import datetime, timedelta

import httpx

from ..database import get_db
from ..models import Case, CaseTransaction, AMLTransaction, AMLAccount, AuditLog, Settings
from ..schemas import CasePatch, FreezeRequest, CaseResponse, TransactionResponse, SettingsUpdate, SARRequest
from ..config import get_settings
from ..worker import get_model_status

router = APIRouter(prefix="/api", tags=["aml"])
settings = get_settings()


# ── Cases ─────────────────────────────────────────────────────────────────────

@router.get("/cases")
async def list_cases(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    bank_id: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    q = select(Case)
    if status:
        q = q.where(Case.status == status)
    if risk_level:
        q = q.where(Case.risk_level == risk_level)
    if bank_id:
        q = q.where(Case.bank_id == bank_id)
    q = q.order_by(Case.created_at.desc()).limit(limit)
    result = await db.execute(q)
    cases = result.scalars().all()

    out = []
    for c in cases:
        ct_count = await db.execute(
            select(func.count(CaseTransaction.id)).where(CaseTransaction.case_id == c.id)
        )
        count = ct_count.scalar() or 0
        out.append({
            "id": c.id,
            "bank_id": c.bank_id,
            "account_id": c.account_id,
            "typology": c.typology,
            "risk_level": c.risk_level,
            "risk_score": c.risk_score,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "analyst_note": c.analyst_note,
            "transaction_count": count,
        })
    return out


@router.get("/cases/{case_id}")
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Linked transactions
    ct_result = await db.execute(
        select(CaseTransaction.transaction_id).where(CaseTransaction.case_id == case_id)
    )
    tx_ids = [r[0] for r in ct_result.all()]

    txs = []
    if tx_ids:
        tx_result = await db.execute(
            select(AMLTransaction).where(AMLTransaction.id.in_(tx_ids))
            .order_by(AMLTransaction.timestamp)
        )
        for tx in tx_result.scalars().all():
            txs.append({
                "id": tx.id,
                "timestamp": tx.timestamp.isoformat(),
                "sender": tx.sender,
                "receiver": tx.receiver,
                "amount": tx.amount,
                "payment_type": tx.payment_type,
                "risk_score": tx.risk_score,
            })

    # Graph nodes/edges
    nodes = {}
    edges = []
    for tx in txs:
        nodes[tx["sender"]] = {"id": str(tx["sender"]), "label": str(tx["sender"])}
        nodes[tx["receiver"]] = {"id": str(tx["receiver"]), "label": str(tx["receiver"])}
        edges.append({
            "source": str(tx["sender"]),
            "target": str(tx["receiver"]),
            "amount": tx["amount"],
            "payment_type": tx["payment_type"],
        })

    # Parse reasons from the latest scored transaction
    reasons = []
    if tx_ids:
        latest = await db.execute(
            select(AMLTransaction).where(
                AMLTransaction.id.in_(tx_ids),
                AMLTransaction.scored == True,
            ).order_by(AMLTransaction.scored_at.desc()).limit(1)
        )
        latest_tx = latest.scalar_one_or_none()
        if latest_tx and latest_tx.reasons_json:
            reasons = json.loads(latest_tx.reasons_json)

    return {
        "id": case.id,
        "bank_id": case.bank_id,
        "account_id": case.account_id,
        "typology": case.typology,
        "risk_level": case.risk_level,
        "risk_score": case.risk_score,
        "status": case.status,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "analyst_note": case.analyst_note,
        "transactions": txs,
        "graph": {"nodes": list(nodes.values()), "edges": edges},
        "reasons": reasons,
    }


@router.patch("/cases/{case_id}")
async def update_case(case_id: str, patch: CasePatch, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if patch.status is not None:
        case.status = patch.status
    if patch.analyst_note is not None:
        case.analyst_note = patch.analyst_note
    if patch.risk_level is not None:
        case.risk_level = patch.risk_level
    case.updated_at = datetime.utcnow()

    db.add(AuditLog(actor="analyst", action=f"case_updated_{patch.status or 'note'}", target=case_id))
    await db.commit()
    return {"id": case_id, "status": case.status}


# ── Account compliance ─────────────────────────────────────────────────────────

@router.post("/accounts/{bank_id}/{account_id}/freeze")
async def freeze_account(
    bank_id: str,
    account_id: int,
    req: FreezeRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _compliance_action(bank_id, account_id, "freeze", req, db)


@router.post("/accounts/{bank_id}/{account_id}/unfreeze")
async def unfreeze_account(
    bank_id: str,
    account_id: int,
    req: FreezeRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _compliance_action(bank_id, account_id, "unfreeze", req, db)


async def _compliance_action(bank_id: str, account_id: int, action: str, req: FreezeRequest, db: AsyncSession):
    bank_config = settings.parse_bank_compliance()
    if bank_id not in bank_config:
        raise HTTPException(status_code=404, detail=f"No compliance config for bank {bank_id}")

    cfg = bank_config[bank_id]
    url = f"{cfg['url']}/compliance/accounts/{account_id}/{action}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"case_id": req.case_id, "reason": req.reason},
                headers={"x-api-key": cfg["key"]},
            )
        resp.raise_for_status()
        bank_response = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Bank returned {exc.response.status_code}: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Bank unreachable: {str(exc)}")

    db.add(AuditLog(
        actor="analyst",
        action=f"account_{action}",
        target=f"{bank_id}/{account_id}",
        detail=json.dumps({"case_id": req.case_id, "reason": req.reason}),
    ))
    await db.commit()
    return bank_response


# ── Account 360 ────────────────────────────────────────────────────────────────

@router.get("/accounts/{bank_id}/{account_id}/360")
async def account_360(bank_id: str, account_id: int, db: AsyncSession = Depends(get_db)):
    acc_result = await db.execute(
        select(AMLAccount).where(
            AMLAccount.bank_id == bank_id,
            AMLAccount.account_id == account_id,
        )
    )
    acc = acc_result.scalar_one_or_none()

    tx_result = await db.execute(
        select(AMLTransaction).where(
            and_(
                AMLTransaction.bank_id == bank_id,
                (AMLTransaction.sender == account_id) | (AMLTransaction.receiver == account_id),
            )
        ).order_by(AMLTransaction.timestamp.desc()).limit(100)
    )
    txs = tx_result.scalars().all()

    cases_result = await db.execute(
        select(Case).where(Case.bank_id == bank_id, Case.account_id == account_id)
        .order_by(Case.created_at.desc()).limit(10)
    )
    cases = cases_result.scalars().all()

    total_sent = sum(t.amount for t in txs if t.sender == account_id)
    total_received = sum(t.amount for t in txs if t.receiver == account_id)

    return {
        "account": {
            "bank_id": bank_id,
            "account_id": account_id,
            "holder_name": acc.holder_name if acc else None,
            "status": acc.status if acc else "unknown",
        },
        "stats": {
            "total_transactions": len(txs),
            "total_sent": total_sent,
            "total_received": total_received,
        },
        "recent_transactions": [
            {"id": t.id, "timestamp": t.timestamp.isoformat(), "sender": t.sender,
             "receiver": t.receiver, "amount": t.amount, "risk_score": t.risk_score}
            for t in txs[:20]
        ],
        "cases": [
            {"id": c.id, "typology": c.typology, "risk_level": c.risk_level, "status": c.status}
            for c in cases
        ],
    }


# ── Metrics ────────────────────────────────────────────────────────────────────

@router.get("/metrics/live")
async def live_metrics(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    one_min_ago = now - timedelta(minutes=1)
    one_hour_ago = now - timedelta(hours=1)

    tx_last_min = await db.execute(
        select(func.count(AMLTransaction.id)).where(AMLTransaction.received_at >= one_min_ago)
    )
    open_cases = await db.execute(
        select(func.count(Case.id)).where(Case.status == "open")
    )
    flagged_amount = await db.execute(
        select(func.sum(AMLTransaction.amount)).where(AMLTransaction.risk_level != "Low")
    )
    total_txs = await db.execute(select(func.count(AMLTransaction.id)))
    unscored = await db.execute(
        select(func.count(AMLTransaction.id)).where(AMLTransaction.scored == False)
    )

    model_status = get_model_status()

    return {
        "transactions_per_min": tx_last_min.scalar() or 0,
        "open_cases": open_cases.scalar() or 0,
        "total_flagged_amount": flagged_amount.scalar() or 0,
        "total_transactions": total_txs.scalar() or 0,
        "model_online": model_status["online"],
        "unscored_count": unscored.scalar() or 0,
        "timestamp": now.isoformat() + "Z",
    }


# ── Settings ────────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings_api(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Settings))
    rows = result.scalars().all()
    cfg = {r.key: r.value for r in rows}
    return {
        "threshold_medium": float(cfg.get("threshold_medium", settings.threshold_medium)),
        "threshold_high": float(cfg.get("threshold_high", settings.threshold_high)),
        "threshold_critical": float(cfg.get("threshold_critical", settings.threshold_critical)),
        "model_api_url": cfg.get("model_api_url", settings.model_api_url),
    }


@router.put("/settings")
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = {}
    if body.threshold_medium is not None:
        updates["threshold_medium"] = str(body.threshold_medium)
    if body.threshold_high is not None:
        updates["threshold_high"] = str(body.threshold_high)
    if body.threshold_critical is not None:
        updates["threshold_critical"] = str(body.threshold_critical)
    if body.model_api_url is not None:
        updates["model_api_url"] = body.model_api_url

    for key, value in updates.items():
        existing = await db.execute(select(Settings).where(Settings.key == key))
        row = existing.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(Settings(key=key, value=value))
    await db.commit()
    return {"updated": list(updates.keys())}


# ── Model status ───────────────────────────────────────────────────────────────

@router.get("/model/status")
async def model_status():
    return get_model_status()


# ── SAR ────────────────────────────────────────────────────────────────────────

@router.post("/sar/{case_id}")
async def generate_sar(case_id: str, req: SARRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    ct_result = await db.execute(
        select(CaseTransaction.transaction_id).where(CaseTransaction.case_id == case_id)
    )
    tx_ids = [r[0] for r in ct_result.all()]

    sar_text = f"""
SUSPICIOUS ACTIVITY REPORT (DRAFT)
====================================
Case ID:       {case.id}
Bank:          {case.bank_id}
Account:       {case.account_id}
Typology:      {case.typology or 'Unknown'}
Risk Level:    {case.risk_level}
Risk Score:    {case.risk_score:.2f}
Status:        {case.status}
Generated At:  {datetime.utcnow().isoformat()}Z

SUMMARY
-------
This SAR is filed in connection with {case.typology or 'suspicious'} activity detected on account {case.account_id}.
A total of {len(tx_ids)} transactions were flagged with a combined risk score of {case.risk_score:.2f}.

ANALYST NOTE
------------
{req.analyst_note or case.analyst_note or "No analyst note provided."}

TRANSACTIONS INVOLVED
---------------------
{chr(10).join(tx_ids[:20])}
{"... and more" if len(tx_ids) > 20 else ""}

[THIS IS AN AUTO-GENERATED DRAFT. REVIEW AND COMPLETE BEFORE SUBMISSION.]
"""
    db.add(AuditLog(actor="analyst", action="sar_generated", target=case_id))
    await db.commit()
    return {"case_id": case_id, "sar_draft": sar_text.strip()}


# ── Audit log ──────────────────────────────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {"id": l.id, "actor": l.actor, "action": l.action, "target": l.target,
         "detail": l.detail, "timestamp": l.timestamp.isoformat()}
        for l in logs
    ]


# ── Transactions ───────────────────────────────────────────────────────────────

@router.get("/transactions")
async def list_transactions(limit: int = 200, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AMLTransaction).order_by(AMLTransaction.received_at.desc()).limit(limit)
    )
    return [
        {
            "id": t.id,
            "bank_id": t.bank_id,
            "timestamp": t.timestamp.isoformat(),
            "sender": t.sender,
            "receiver": t.receiver,
            "amount": t.amount,
            "payment_type": t.payment_type,
            "scored": t.scored,
            "risk_score": t.risk_score,
            "risk_level": t.risk_level,
            "typology": t.typology,
        }
        for t in result.scalars().all()
    ]
