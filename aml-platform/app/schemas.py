from pydantic import BaseModel, field_validator
from typing import Optional, List, Any
from datetime import datetime


class TransactionPayload(BaseModel):
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


class ProfilePayload(BaseModel):
    holder_name: str
    account_status: str


class IngestSingle(BaseModel):
    bank_id: str
    transaction: TransactionPayload
    sender_profile: Optional[ProfilePayload] = None
    receiver_profile: Optional[ProfilePayload] = None


class BatchItem(BaseModel):
    transaction: TransactionPayload
    sender_profile: Optional[ProfilePayload] = None
    receiver_profile: Optional[ProfilePayload] = None


class IngestBatch(BaseModel):
    bank_id: str
    transactions: List[BatchItem]


class CasePatch(BaseModel):
    status: Optional[str] = None
    analyst_note: Optional[str] = None
    risk_level: Optional[str] = None


class FreezeRequest(BaseModel):
    case_id: str
    reason: str


class SARRequest(BaseModel):
    analyst_note: Optional[str] = None


class CaseResponse(BaseModel):
    id: str
    bank_id: str
    account_id: int
    typology: Optional[str]
    risk_level: str
    risk_score: float
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    analyst_note: Optional[str]
    transaction_count: int = 0

    model_config = {"from_attributes": True}


class TransactionResponse(BaseModel):
    id: str
    bank_id: str
    timestamp: datetime
    sender: int
    receiver: int
    amount: float
    payment_currency: str
    received_currency: str
    sender_bank_location: str
    receiver_bank_location: str
    payment_type: str
    scored: bool
    risk_score: Optional[float]
    risk_level: Optional[str]
    typology: Optional[str]
    model_version: Optional[str]
    source: str

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    threshold_medium: Optional[float] = None
    threshold_high: Optional[float] = None
    threshold_critical: Optional[float] = None
    model_api_url: Optional[str] = None
