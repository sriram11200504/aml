from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean,
    DateTime, Text, ForeignKey, func, Index
)
from .database import Base


class BankRegistration(Base):
    __tablename__ = "banks"

    bank_id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    compliance_url = Column(String(500), nullable=True)
    api_key = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AMLAccount(Base):
    __tablename__ = "aml_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bank_id = Column(String(50), nullable=False)
    account_id = Column(BigInteger, nullable=False)
    holder_name = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    first_seen = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_aml_accounts_bank_account", "bank_id", "account_id", unique=True),
    )


class AMLTransaction(Base):
    __tablename__ = "aml_transactions"

    id = Column(String(50), primary_key=True)
    bank_id = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    sender = Column(BigInteger, nullable=False)
    receiver = Column(BigInteger, nullable=False)
    amount = Column(Float, nullable=False)
    payment_currency = Column(String(50), nullable=False)
    received_currency = Column(String(50), nullable=False)
    sender_bank_location = Column(String(100), nullable=False)
    receiver_bank_location = Column(String(100), nullable=False)
    payment_type = Column(String(50), nullable=False)
    received_at = Column(DateTime, server_default=func.now())
    scored = Column(Boolean, nullable=False, default=False)
    risk_score = Column(Float, nullable=True)
    risk_level = Column(String(20), nullable=True)
    typology = Column(String(100), nullable=True)
    reasons_json = Column(Text, nullable=True)
    model_version = Column(String(100), nullable=True)
    scored_at = Column(DateTime, nullable=True)
    source = Column(String(20), nullable=False, default="live")  # live | replay

    __table_args__ = (
        Index("ix_aml_tx_sender_ts", "sender", "timestamp"),
        Index("ix_aml_tx_receiver_ts", "receiver", "timestamp"),
    )


class Case(Base):
    __tablename__ = "cases"

    id = Column(String(50), primary_key=True)
    bank_id = Column(String(50), nullable=False)
    account_id = Column(BigInteger, nullable=False)
    typology = Column(String(100), nullable=True)
    risk_level = Column(String(20), nullable=False)
    risk_score = Column(Float, nullable=False)
    status = Column(String(30), nullable=False, default="open")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    analyst_note = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_cases_bank_account_typology", "bank_id", "account_id", "typology"),
    )


class CaseTransaction(Base):
    __tablename__ = "case_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), nullable=False, index=True)
    transaction_id = Column(String(50), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String(100), nullable=False, default="system")
    action = Column(String(100), nullable=False)
    target = Column(String(200), nullable=True)
    detail = Column(Text, nullable=True)
    timestamp = Column(DateTime, server_default=func.now())


class Settings(Base):
    __tablename__ = "aml_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
