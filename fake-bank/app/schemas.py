from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class PaymentType(str, Enum):
    ACH = "ACH"
    CHEQUE = "Cheque"
    CREDIT_CARD = "Credit card"
    DEBIT_CARD = "Debit card"
    CROSS_BORDER = "Cross-border"
    CASH_WITHDRAWAL = "Cash Withdrawal"
    CASH_DEPOSIT = "Cash Deposit"


class TransferRequest(BaseModel):
    sender_account: int
    receiver_account: int
    amount: float
    payment_type: PaymentType
    payment_currency: str = "Indian rupee"
    received_currency: str = "Indian rupee"
    receiver_bank_location: str = "India"
    note: Optional[str] = None
    test_funding: bool = False  # For simulator: top up if needed

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class BulkTransferItem(BaseModel):
    receiver_account: int
    amount: float
    payment_type: PaymentType
    payment_currency: str = "Indian rupee"
    received_currency: str = "Indian rupee"
    receiver_bank_location: str = "India"
    note: Optional[str] = None


class BulkTransferRequest(BaseModel):
    sender_account: int
    transfers: List[BulkTransferItem]
    test_funding: bool = False


class AccountCreate(BaseModel):
    account_id: int
    holder_name: str
    currency: str = "Indian rupee"
    bank_location: str = "India"
    balance: float = 0.0


class AccountResponse(BaseModel):
    account_id: int
    holder_name: str
    currency: str
    bank_location: str
    balance: float
    status: str
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TransactionResponse(BaseModel):
    id: str
    timestamp: datetime
    sender_account: int
    receiver_account: int
    amount: float
    payment_currency: str
    received_currency: str
    sender_bank_location: str
    receiver_bank_location: str
    payment_type: str
    status: str

    model_config = {"from_attributes": True}


class OutboxStatsResponse(BaseModel):
    pending: int
    sent: int
    failed: int
    total: int


class FreezeRequest(BaseModel):
    case_id: str
    reason: str


class ComplianceLogResponse(BaseModel):
    id: int
    timestamp: datetime
    account_id: int
    action: str
    case_id: Optional[str]
    reason: Optional[str]

    model_config = {"from_attributes": True}
