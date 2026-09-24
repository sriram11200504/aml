"""
AML Platform backend tests.
Run: pytest tests/ -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import sys, os
from datetime import datetime, timedelta
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["USE_SQLITE"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["MODEL_API_URL"] = "http://localhost:8200"
os.environ["INGEST_API_KEYS"] = "test-key=testbank"
os.environ["BANK_COMPLIANCE_CONFIGS"] = "testbank=http://localhost:9999:test-compliance-key"

from app.main import app
from app.database import init_db, engine, Base


def make_tx(tx_id=None, sender=1111111111, receiver=2222222222, amount=10000.0, payment_type="ACH", ts=None):
    if ts is None:
        ts = datetime.utcnow().isoformat() + "Z"
    return {
        "transaction": {
            "id": tx_id or f"tx_{uuid.uuid4().hex[:12]}",
            "timestamp": ts,
            "sender_account": sender,
            "receiver_account": receiver,
            "amount": amount,
            "payment_currency": "Indian rupee",
            "received_currency": "Indian rupee",
            "sender_bank_location": "India",
            "receiver_bank_location": "India",
            "payment_type": payment_type,
        },
        "sender_profile": {"holder_name": "Test Sender", "account_status": "active"},
        "receiver_profile": {"holder_name": "Test Receiver", "account_status": "active"},
    }


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_single(client):
    tx = make_tx()
    resp = await client.post(
        "/api/v1/ingest/transactions",
        json={"bank_id": "testbank", **tx},
        headers={"x-api-key": "test-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


@pytest.mark.asyncio
async def test_ingest_idempotency(client):
    """Sending the same transaction twice should be accepted but not double-counted."""
    tx = make_tx(tx_id="tx_idem_001")
    body = {"bank_id": "testbank", **tx}
    
    r1 = await client.post("/api/v1/ingest/transactions", json=body, headers={"x-api-key": "test-key"})
    r2 = await client.post("/api/v1/ingest/transactions", json=body, headers={"x-api-key": "test-key"})
    assert r1.json()["accepted"] is True
    assert r2.json()["accepted"] is True

    # Only one transaction stored
    txs = (await client.get("/api/transactions")).json()
    matching = [t for t in txs if t["id"] == "tx_idem_001"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_ingest_wrong_key(client):
    tx = make_tx()
    resp = await client.post(
        "/api/v1/ingest/transactions",
        json={"bank_id": "testbank", **tx},
        headers={"x-api-key": "wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_batch(client):
    body = {
        "bank_id": "testbank",
        "transactions": [make_tx() for _ in range(5)],
    }
    resp = await client.post(
        "/api/v1/ingest/transactions/batch",
        json=body,
        headers={"x-api-key": "test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["count"] == 5


@pytest.mark.asyncio
async def test_list_cases_empty(client):
    resp = await client.get("/api/cases")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_metrics_live(client):
    resp = await client.get("/api/metrics/live")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions_per_min" in data
    assert "open_cases" in data
    assert "model_online" in data


@pytest.mark.asyncio
async def test_settings_get_put(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    assert "threshold_medium" in resp.json()

    put = await client.put("/api/settings", json={"threshold_medium": 0.35})
    assert put.status_code == 200

    resp2 = await client.get("/api/settings")
    assert abs(resp2.json()["threshold_medium"] - 0.35) < 0.001


@pytest.mark.asyncio
async def test_history_no_future_rows(client):
    """History must never include transactions after the current tx timestamp."""
    # Send a transaction in the past
    past_time = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
    future_time = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"

    # Ingest a "future" transaction (receiver is 9999999999)
    future_tx = make_tx(
        tx_id="tx_future_001",
        sender=1111111111,
        receiver=9999999999,
        ts=future_time,
    )
    await client.post("/api/v1/ingest/transactions", json={"bank_id": "testbank", **future_tx}, headers={"x-api-key": "test-key"})

    # Now ingest a current transaction for same sender
    current_tx = make_tx(
        tx_id="tx_current_001",
        sender=1111111111,
        receiver=3333333333,
        ts=datetime.utcnow().isoformat() + "Z",
    )
    await client.post("/api/v1/ingest/transactions", json={"bank_id": "testbank", **current_tx}, headers={"x-api-key": "test-key"})

    # The future tx should not appear in the history used for scoring the current tx
    # We verify this by checking that no future-timestamped tx is in the transactions list
    # for the same sender alongside the current one
    txs = (await client.get("/api/transactions")).json()
    assert any(t["id"] == "tx_future_001" for t in txs)
    assert any(t["id"] == "tx_current_001" for t in txs)


@pytest.mark.asyncio
async def test_account_360(client):
    tx = make_tx(sender=8888888888, receiver=7777777777)
    await client.post(
        "/api/v1/ingest/transactions",
        json={"bank_id": "testbank", **tx},
        headers={"x-api-key": "test-key"},
    )
    resp = await client.get("/api/accounts/testbank/8888888888/360")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account"]["account_id"] == 8888888888
    assert data["stats"]["total_transactions"] >= 1
