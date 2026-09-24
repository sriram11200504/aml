from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Text, func
from .database import Base


class Account(Base):
    __tablename__ = "accounts"

    account_id = Column(BigInteger, primary_key=True, index=True)
    holder_name = Column(String(200), nullable=False)
    currency = Column(String(50), nullable=False, default="Indian rupee")
    bank_location = Column(String(100), nullable=False, default="India")
    balance = Column(Float, nullable=False, default=0.0)
    status = Column(String(20), nullable=False, default="active")  # active | restricted
    created_at = Column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(50), primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    sender_account = Column(BigInteger, nullable=False, index=True)
    receiver_account = Column(BigInteger, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    payment_currency = Column(String(50), nullable=False)
    received_currency = Column(String(50), nullable=False)
    sender_bank_location = Column(String(100), nullable=False)
    receiver_bank_location = Column(String(100), nullable=False)
    payment_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="completed")  # completed | failed


class Outbox(Base):
    __tablename__ = "outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(50), nullable=False, index=True)
    payload_json = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending | sent | failed
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ComplianceLog(Base):
    __tablename__ = "compliance_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now())
    account_id = Column(BigInteger, nullable=False)
    action = Column(String(20), nullable=False)  # freeze | unfreeze
    case_id = Column(String(100), nullable=True)
    reason = Column(Text, nullable=True)
