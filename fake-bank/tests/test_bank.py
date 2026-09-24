"""
Fake Bank backend tests.
Run: pytest tests/ -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import sys, os

# Ensure we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use in-memory SQLite for tests
os.environ["USE_SQLITE"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.main import app
from app.database import init_db, engine, Base


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.seed import seed_database
    await seed_database()
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
async def test_list_accounts(client):
    resp = await client.get("/api/accounts")
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) >= 5


@pytest.mark.asyncio
async def test_transfer_success(client):
    """Successful transfer between two seeded accounts."""
    accounts = (await client.get("/api/accounts")).json()
    sender = next(a for a in accounts if a["balance"] >= 1000)
    receiver = next(a for a in accounts if a["account_id"] != sender["account_id"])

    resp = await client.post("/api/transfer", json={
        "sender_account": sender["account_id"],
        "receiver_account": receiver["account_id"],
        "amount": 1000.0,
        "payment_type": "ACH",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["transaction_id"] is not None

    # Balance updated
    updated = (await client.get(f"/api/accounts/{sender['account_id']}")).json()
    assert abs(updated["balance"] - (sender["balance"] - 1000.0)) < 0.01


@pytest.mark.asyncio
async def test_transfer_insufficient_balance(client):
    """Transfer should fail with insufficient balance."""
    accounts = (await client.get("/api/accounts")).json()
    sender = accounts[0]
    receiver = accounts[1]

    resp = await client.post("/api/transfer", json={
        "sender_account": sender["account_id"],
        "receiver_account": receiver["account_id"],
        "amount": sender["balance"] + 9999999.0,
        "payment_type": "ACH",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "Insufficient" in data["message"]


@pytest.mark.asyncio
async def test_transfer_restricted_account(client):
    """Restricted account cannot send."""
    # Freeze an account via compliance endpoint
    accounts = (await client.get("/api/accounts")).json()
    sender = accounts[0]

    freeze_resp = await client.post(
        f"/compliance/accounts/{sender['account_id']}/freeze",
        json={"case_id": "test-case-1", "reason": "test"},
        headers={"x-api-key": "compliance-secret-key-01"},
    )
    assert freeze_resp.status_code == 200

    # Try to send
    receiver = accounts[1]
    resp = await client.post("/api/transfer", json={
        "sender_account": sender["account_id"],
        "receiver_account": receiver["account_id"],
        "amount": 100.0,
        "payment_type": "ACH",
    })
    data = resp.json()
    assert data["success"] is False
    assert "restricted" in data["message"].lower()
    # Neutral message – no mention of AML
    assert "aml" not in data["message"].lower()
    assert "money laundering" not in data["message"].lower()


@pytest.mark.asyncio
async def test_restricted_account_can_receive(client):
    """Restricted account can still receive incoming transfers."""
    accounts = (await client.get("/api/accounts")).json()
    receiver = accounts[0]

    await client.post(
        f"/compliance/accounts/{receiver['account_id']}/freeze",
        json={"case_id": "test-case-2", "reason": "test"},
        headers={"x-api-key": "compliance-secret-key-01"},
    )

    # Another account sends TO the restricted one
    sender = accounts[1]
    resp = await client.post("/api/transfer", json={
        "sender_account": sender["account_id"],
        "receiver_account": receiver["account_id"],
        "amount": 100.0,
        "payment_type": "ACH",
    })
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_compliance_freeze_unfreeze(client):
    """Freeze then unfreeze an account."""
    accounts = (await client.get("/api/accounts")).json()
    account = accounts[0]
    aid = account["account_id"]

    freeze = await client.post(
        f"/compliance/accounts/{aid}/freeze",
        json={"case_id": "case-xyz", "reason": "test freeze"},
        headers={"x-api-key": "compliance-secret-key-01"},
    )
    assert freeze.status_code == 200
    assert freeze.json()["status"] == "frozen"

    acc_after_freeze = (await client.get(f"/api/accounts/{aid}")).json()
    assert acc_after_freeze["status"] == "restricted"

    unfreeze = await client.post(
        f"/compliance/accounts/{aid}/unfreeze",
        json={"case_id": "case-xyz", "reason": "cleared"},
        headers={"x-api-key": "compliance-secret-key-01"},
    )
    assert unfreeze.status_code == 200
    assert unfreeze.json()["status"] == "active"


@pytest.mark.asyncio
async def test_compliance_wrong_key(client):
    """Wrong compliance key returns 401."""
    accounts = (await client.get("/api/accounts")).json()
    aid = accounts[0]["account_id"]
    resp = await client.post(
        f"/compliance/accounts/{aid}/freeze",
        json={"case_id": "x", "reason": "x"},
        headers={"x-api-key": "wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_outbox_stats(client):
    """After a transfer, outbox has a pending row."""
    accounts = (await client.get("/api/accounts")).json()
    sender = accounts[0]
    receiver = accounts[1]

    await client.post("/api/transfer", json={
        "sender_account": sender["account_id"],
        "receiver_account": receiver["account_id"],
        "amount": 500.0,
        "payment_type": "ACH",
    })

    stats = (await client.get("/api/outbox/stats")).json()
    assert stats["total"] >= 1


@pytest.mark.asyncio
async def test_test_funding(client):
    """Test funding flag tops up balance and allows transfer."""
    accounts = (await client.get("/api/accounts")).json()
    sender = accounts[0]
    receiver = accounts[1]

    # Transfer more than balance using test_funding
    resp = await client.post("/api/transfer", json={
        "sender_account": sender["account_id"],
        "receiver_account": receiver["account_id"],
        "amount": sender["balance"] + 1_000_000.0,
        "payment_type": "ACH",
        "test_funding": True,
    })
    assert resp.json()["success"] is True
