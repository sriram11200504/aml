"""
Transfer business logic.
Commit transfer -> write outbox row -> return immediately.
AML dispatch happens in the background.
"""
import json
import uuid
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .models import Account, Transaction, Outbox
from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PAYMENT_TYPES = {
    "ACH", "Cheque", "Credit card", "Debit card",
    "Cross-border", "Cash Withdrawal", "Cash Deposit"
}


async def execute_transfer(
    session: AsyncSession,
    sender_account: int,
    receiver_account: int,
    amount: float,
    payment_type: str,
    payment_currency: str = "Indian rupee",
    received_currency: str = "Indian rupee",
    receiver_bank_location: str = "India",
    note: str = None,
    test_funding: bool = False,
) -> dict:
    """
    Execute a transfer. Returns {"success": True/False, "message": str, "transaction_id": str|None}.
    NEVER raises: all errors are returned as success=False.
    """
    # Load sender
    sender_result = await session.execute(
        select(Account).where(Account.account_id == sender_account)
    )
    sender = sender_result.scalar_one_or_none()

    if sender is None:
        return {"success": False, "message": "Sender account not found.", "transaction_id": None}

    # Check restriction (only outgoing blocked)
    if sender.status == "restricted":
        return {
            "success": False,
            "message": "Your account is restricted. Please contact your branch.",
            "transaction_id": None,
        }

    # Test funding: top up if needed
    if test_funding and sender.balance < amount:
        sender.balance = amount + 100000  # generous top-up

    # Balance check
    if sender.balance < amount:
        return {"success": False, "message": "Insufficient balance.", "transaction_id": None}

    # Load receiver (may be external / None)
    receiver_result = await session.execute(
        select(Account).where(Account.account_id == receiver_account)
    )
    receiver = receiver_result.scalar_one_or_none()

    # Determine locations/currencies from accounts if internal
    sender_bank_location = sender.bank_location
    if receiver:
        receiver_bank_loc = receiver.bank_location
        recv_currency = receiver.currency
    else:
        receiver_bank_loc = receiver_bank_location
        recv_currency = received_currency

    # Build transaction ID
    tx_id = f"tx_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()

    # Debit sender
    sender.balance -= amount

    # Credit receiver if internal
    if receiver:
        receiver.balance += amount

    # Create transaction record
    tx = Transaction(
        id=tx_id,
        timestamp=now,
        sender_account=sender_account,
        receiver_account=receiver_account,
        amount=amount,
        payment_currency=payment_currency,
        received_currency=recv_currency,
        sender_bank_location=sender_bank_location,
        receiver_bank_location=receiver_bank_loc,
        payment_type=payment_type,
        status="completed",
    )
    session.add(tx)

    # Build AML event payload
    payload = {
        "bank_id": settings.bank_id,
        "transaction": {
            "id": tx_id,
            "timestamp": now.isoformat() + "Z",
            "sender_account": sender_account,
            "receiver_account": receiver_account,
            "amount": amount,
            "payment_currency": payment_currency,
            "received_currency": recv_currency,
            "sender_bank_location": sender_bank_location,
            "receiver_bank_location": receiver_bank_loc,
            "payment_type": payment_type,
        },
        "sender_profile": {
            "holder_name": sender.holder_name,
            "account_status": sender.status,
        },
        "receiver_profile": (
            {"holder_name": receiver.holder_name, "account_status": receiver.status}
            if receiver
            else None
        ),
    }

    # Write outbox row (same transaction, commit together)
    outbox_row = Outbox(
        transaction_id=tx_id,
        payload_json=json.dumps(payload),
        status="pending",
        attempts=0,
    )
    session.add(outbox_row)

    await session.commit()
    logger.info("Transfer %s committed: %s -> %s, %.2f", tx_id, sender_account, receiver_account, amount)

    return {
        "success": True,
        "message": "Transfer successful.",
        "transaction_id": tx_id,
        "amount": amount,
        "sender_account": sender_account,
        "receiver_account": receiver_account,
    }
