"""
Model API contract tests.
Run against ANY model service: pytest tests/model_contract_tests.py --model-url http://localhost:8200
"""
import pytest
import httpx
from datetime import datetime, timedelta, timezone
import uuid


def make_tx(tx_id=None, sender=1111111111, receiver=2222222222, amount=10000.0, ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "id": tx_id or f"tx_{uuid.uuid4().hex[:8]}",
        "timestamp": ts,
        "sender_account": sender,
        "receiver_account": receiver,
        "amount": amount,
        "payment_currency": "Indian rupee",
        "received_currency": "Indian rupee",
        "sender_bank_location": "India",
        "receiver_bank_location": "India",
        "payment_type": "ACH",
    }


def test_health(model_url):
    resp = httpx.get(f"{model_url}/health", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


def test_model_info(model_url):
    resp = httpx.get(f"{model_url}/v1/model-info", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("version"), str)
    assert isinstance(data.get("features"), list)


def test_score_minimal(model_url):
    """Minimal payload – empty histories."""
    resp = httpx.post(f"{model_url}/v1/score", json={
        "transaction": make_tx(),
        "sender_history": [],
        "receiver_history": [],
    }, timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert "risk_score" in data
    assert "transaction_id" in data
    assert "reasons" in data
    assert "model_version" in data


def test_score_range(model_url):
    """Risk score must be in [0.0, 1.0]."""
    for _ in range(5):
        resp = httpx.post(f"{model_url}/v1/score", json={
            "transaction": make_tx(amount=100000.0),
            "sender_history": [],
            "receiver_history": [],
        }, timeout=5)
        score = resp.json()["risk_score"]
        assert 0.0 <= score <= 1.0, f"Score out of range: {score}"


def test_score_typology_enum(model_url):
    """Typology must be null or one of the known values."""
    KNOWN = {
        "Fan_Out", "Fan_In", "Structuring", "Cycle", "Scatter-Gather",
        "Gather-Scatter", "Rapid_Pass_Through", "Behavioural_Change",
        "Single_Large", "Cash_Withdrawal", None,
    }
    resp = httpx.post(f"{model_url}/v1/score", json={
        "transaction": make_tx(),
        "sender_history": [],
        "receiver_history": [],
    }, timeout=5)
    typology = resp.json().get("typology")
    assert typology in KNOWN, f"Unknown typology: {typology}"


def test_score_idempotent(model_url):
    """Same payload → same risk_score."""
    payload = {
        "transaction": make_tx(tx_id="tx_idem_test"),
        "sender_history": [],
        "receiver_history": [],
    }
    r1 = httpx.post(f"{model_url}/v1/score", json=payload, timeout=5).json()
    r2 = httpx.post(f"{model_url}/v1/score", json=payload, timeout=5).json()
    assert r1["risk_score"] == r2["risk_score"]


def test_score_empty_histories(model_url):
    """Both histories empty is valid."""
    resp = httpx.post(f"{model_url}/v1/score", json={
        "transaction": make_tx(),
        "sender_history": [],
        "receiver_history": [],
    }, timeout=5)
    assert resp.status_code == 200


def test_score_large_histories(model_url):
    """1000 history items must not crash or timeout."""
    now = datetime.now(timezone.utc)
    history = [
        make_tx(
            tx_id=f"hist_{i}",
            ts=(now - timedelta(hours=i)).isoformat(),
        )
        for i in range(1, 1001)
    ]
    resp = httpx.post(f"{model_url}/v1/score", json={
        "transaction": make_tx(),
        "sender_history": history[:500],
        "receiver_history": history[500:],
    }, timeout=10)
    assert resp.status_code == 200


def test_score_fan_out_trigger(model_url):
    """8 distinct receivers in 24h should trigger Fan_Out."""
    now = datetime.now(timezone.utc)
    sender = 8888888888
    history = [
        make_tx(
            tx_id=f"fo_{i}",
            sender=sender,
            receiver=1000000000 + i,
            ts=(now - timedelta(minutes=i * 10)).isoformat(),
        )
        for i in range(1, 8)
    ]
    # Current tx is the 8th distinct receiver
    tx = make_tx(sender=sender, receiver=9000000001, amount=100000.0)
    resp = httpx.post(f"{model_url}/v1/score", json={
        "transaction": tx,
        "sender_history": history,
        "receiver_history": [],
    }, timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_score"] >= 0.4
    assert data["typology"] == "Fan_Out", f"Expected Fan_Out but got {data['typology']}"


def test_no_label_leakage(model_url):
    """Response must not contain Is_laundering or Laundering_type."""
    resp = httpx.post(f"{model_url}/v1/score", json={
        "transaction": make_tx(),
        "sender_history": [],
        "receiver_history": [],
    }, timeout=5)
    text = resp.text
    assert "Is_laundering" not in text
    assert "Laundering_type" not in text
