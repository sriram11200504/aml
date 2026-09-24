"""
Mock Model Service – deterministic rule-based AML scoring.
Implements /v1/score, /health, /v1/model-info exactly per the integration contract.

This is a reference implementation. The real model service built by a teammate
must satisfy the same HTTP contract (verified by tests/model_contract_tests.py).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import math

app = FastAPI(title="Mock AML Model Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_VERSION = "mock-v1.0"
FEATURES = [
    "distinct_receivers_24h",
    "distinct_senders_24h",
    "amount_vs_30d_avg",
    "cycle_detected",
    "structuring_score",
    "rapid_pass_through_ratio",
    "cash_concentration",
    "cross_border_flag",
]


class TransactionFields(BaseModel):
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


class ScoreRequest(BaseModel):
    transaction: TransactionFields
    sender_history: List[TransactionFields] = []
    receiver_history: List[TransactionFields] = []


class Reason(BaseModel):
    text: str
    feature: str
    impact: float


class ScoreResponse(BaseModel):
    transaction_id: str
    risk_score: float
    typology: Optional[str] = None
    reasons: List[Reason] = []
    model_version: str = MODEL_VERSION


@app.get("/health")
def health():
    return {"status": "ok", "service": "mock-model-service", "version": MODEL_VERSION}


@app.get("/v1/model-info")
def model_info():
    return {"version": MODEL_VERSION, "features": FEATURES}


def _parse_dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    return datetime.fromisoformat(str(ts).replace("Z", ""))


@app.post("/v1/score", response_model=ScoreResponse)
def score(req: ScoreRequest):
    tx = req.transaction
    tx_time = _parse_dt(tx.timestamp)
    reasons: List[Reason] = []
    scores: List[float] = [0.0]

    sender_hist = req.sender_history
    receiver_hist = req.receiver_history

    # ── Rule 1: Fan-Out – sender pays ≥8 distinct receivers in 24h ─────────────
    cutoff_24h = tx_time - timedelta(hours=24)
    sent_24h = [h for h in sender_hist if _parse_dt(h.timestamp) >= cutoff_24h and h.sender_account == tx.sender_account]
    distinct_receivers_24h = len(set(h.receiver_account for h in sent_24h)) + 1  # +1 for current tx
    if distinct_receivers_24h >= 8:
        impact = min(0.9, 0.4 + (distinct_receivers_24h - 8) * 0.05)
        scores.append(impact)
        reasons.append(Reason(
            text=f"Sender paid {distinct_receivers_24h} distinct accounts within 24 hours (Fan-Out threshold: 8)",
            feature="distinct_receivers_24h",
            impact=impact,
        ))
        return ScoreResponse(
            transaction_id=tx.id,
            risk_score=round(min(1.0, max(scores)), 3),
            typology="Fan_Out",
            reasons=reasons,
            model_version=MODEL_VERSION,
        )

    # ── Rule 2: Fan-In – ≥8 distinct senders pay same receiver in 24h ──────────
    received_24h = [h for h in receiver_hist if _parse_dt(h.timestamp) >= cutoff_24h and h.receiver_account == tx.receiver_account]
    distinct_senders_24h = len(set(h.sender_account for h in received_24h)) + 1
    if distinct_senders_24h >= 8:
        impact = min(0.9, 0.4 + (distinct_senders_24h - 8) * 0.05)
        scores.append(impact)
        reasons.append(Reason(
            text=f"Receiver received from {distinct_senders_24h} distinct senders within 24 hours (Fan-In)",
            feature="distinct_senders_24h",
            impact=impact,
        ))
        return ScoreResponse(
            transaction_id=tx.id,
            risk_score=round(min(1.0, max(scores)), 3),
            typology="Fan_In",
            reasons=reasons,
            model_version=MODEL_VERSION,
        )

    # ── Rule 3: Structuring – ≥5 cash transactions just under a threshold ────────
    cash_types = {"Cash Withdrawal", "Cash Deposit"}
    if tx.payment_type in cash_types:
        cutoff_48h = tx_time - timedelta(hours=48)
        threshold = 100000.0  # configurable
        margin = 0.15  # within 15% below threshold
        lower = threshold * (1 - margin)
        cash_48h = [
            h for h in sender_hist
            if _parse_dt(h.timestamp) >= cutoff_48h
            and h.payment_type in cash_types
            and lower <= h.amount < threshold
        ]
        if tx.amount >= lower and tx.amount < threshold:
            count = len(cash_48h) + 1
            if count >= 5:
                impact = min(0.88, 0.5 + count * 0.04)
                scores.append(impact)
                reasons.append(Reason(
                    text=f"{count} cash transactions just under ₹{threshold:,.0f} threshold within 48h (Structuring)",
                    feature="structuring_score",
                    impact=impact,
                ))
                return ScoreResponse(
                    transaction_id=tx.id,
                    risk_score=round(min(1.0, impact), 3),
                    typology="Structuring",
                    reasons=reasons,
                    model_version=MODEL_VERSION,
                )

    # ── Rule 4: Cycle – A -> B -> ... -> A within 7 days ────────────────────────
    cutoff_7d = tx_time - timedelta(days=7)
    # Look for a path back: current receiver sent to current sender at some point
    cycle_candidates = [
        h for h in receiver_hist
        if _parse_dt(h.timestamp) >= cutoff_7d
        and h.sender_account == tx.receiver_account
        and h.receiver_account == tx.sender_account
    ]
    if cycle_candidates:
        impact = 0.85
        scores.append(impact)
        reasons.append(Reason(
            text=f"Cycle detected: funds returned from receiver back to original sender within 7 days",
            feature="cycle_detected",
            impact=impact,
        ))
        return ScoreResponse(
            transaction_id=tx.id,
            risk_score=round(min(1.0, impact), 3),
            typology="Cycle",
            reasons=reasons,
            model_version=MODEL_VERSION,
        )

    # ── Rule 5: Rapid Pass-Through – received large amount, forwarded >80% ───────
    received_24h_amounts = [h for h in receiver_hist if _parse_dt(h.timestamp) >= cutoff_24h and h.receiver_account == tx.sender_account]
    sent_24h_amounts = [h for h in sender_hist if _parse_dt(h.timestamp) >= cutoff_24h and h.sender_account == tx.sender_account]
    total_received = sum(h.amount for h in received_24h_amounts)
    total_sent = sum(h.amount for h in sent_24h_amounts) + tx.amount
    if total_received > 50000 and total_sent / max(total_received, 1) > 0.80:
        ratio = total_sent / max(total_received, 1)
        impact = min(0.87, 0.5 + ratio * 0.3)
        scores.append(impact)
        reasons.append(Reason(
            text=f"Account forwarded {ratio:.0%} of received funds within 24h (Rapid Pass-Through)",
            feature="rapid_pass_through_ratio",
            impact=impact,
        ))
        return ScoreResponse(
            transaction_id=tx.id,
            risk_score=round(min(1.0, impact), 3),
            typology="Rapid_Pass_Through",
            reasons=reasons,
            model_version=MODEL_VERSION,
        )

    # ── Rule 6: Behavioural Change – amount >5x sender's 30-day average ─────────
    cutoff_30d = tx_time - timedelta(days=30)
    past_30d = [h for h in sender_hist if _parse_dt(h.timestamp) >= cutoff_30d and h.sender_account == tx.sender_account]
    if len(past_30d) >= 3:
        avg_amount = sum(h.amount for h in past_30d) / len(past_30d)
        ratio = tx.amount / max(avg_amount, 1)
        if ratio >= 5.0:
            impact = min(0.82, 0.45 + math.log(ratio) * 0.08)
            scores.append(impact)
            reasons.append(Reason(
                text=f"Transaction amount is {ratio:.1f}x the sender's 30-day average (Behavioural Change)",
                feature="amount_vs_30d_avg",
                impact=impact,
            ))
            return ScoreResponse(
                transaction_id=tx.id,
                risk_score=round(min(1.0, impact), 3),
                typology="Behavioural_Change",
                reasons=reasons,
                model_version=MODEL_VERSION,
            )

    # ── Rule 7: Single Large transaction ─────────────────────────────────────────
    if tx.amount >= 500000:
        impact = min(0.6, 0.3 + tx.amount / 5000000)
        scores.append(impact)
        reasons.append(Reason(
            text=f"Single large transaction of {tx.amount:,.0f} {tx.payment_currency}",
            feature="single_large_amount",
            impact=impact,
        ))
        if impact >= 0.4:
            return ScoreResponse(
                transaction_id=tx.id,
                risk_score=round(impact, 3),
                typology="Single_Large",
                reasons=reasons,
                model_version=MODEL_VERSION,
            )

    # ── Rule 8: Cross-border burst ────────────────────────────────────────────────
    if tx.sender_bank_location != tx.receiver_bank_location:
        cross_border_24h = [
            h for h in sender_hist
            if _parse_dt(h.timestamp) >= cutoff_24h
            and h.sender_bank_location != h.receiver_bank_location
        ]
        if len(cross_border_24h) >= 3:
            impact = 0.45
            scores.append(impact)
            reasons.append(Reason(
                text=f"Multiple cross-border transactions ({len(cross_border_24h)+1}) in 24h",
                feature="cross_border_flag",
                impact=impact,
            ))

    final_score = round(min(1.0, max(scores)), 3)
    return ScoreResponse(
        transaction_id=tx.id,
        risk_score=final_score,
        typology=None,
        reasons=reasons,
        model_version=MODEL_VERSION,
    )
