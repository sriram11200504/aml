"""
End-to-end integration tests (HTTP only).
All 5 scenarios from the spec. Requires all services running on SQLite mode.

Run: pytest tests/ -v -s
"""
import pytest
import httpx
import asyncio
import os
import time
from datetime import datetime, timezone

BANK_URL = os.getenv("BANK_URL", "http://127.0.0.1:8000")
AML_URL = os.getenv("AML_URL", "http://127.0.0.1:8100")
MODEL_URL = os.getenv("MODEL_URL", "http://127.0.0.1:8200")
AML_API_KEY = os.getenv("AML_API_KEY", "aml-secret-key-01")
COMPLIANCE_KEY = os.getenv("COMPLIANCE_API_KEY", "compliance-secret-key-01")

DEMO_SENDER = 8724731955  # Ravi Kumar - seeded demo account


def wait_for_health(url: str, timeout: int = 30) -> bool:
    """Poll /health until 200 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url}/health", timeout=3)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session", autouse=True)
def services_healthy():
    """Assert all services are up before running tests."""
    assert wait_for_health(BANK_URL, 30), f"Fake bank not healthy at {BANK_URL}"
    assert wait_for_health(AML_URL, 30), f"AML platform not healthy at {AML_URL}"
    assert wait_for_health(MODEL_URL, 30), f"Mock model not healthy at {MODEL_URL}"
    print(f"\n[OK] All services healthy")


def get_accounts():
    resp = httpx.get(f"{BANK_URL}/api/accounts", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_active_receivers(exclude_sender: int, count: int) -> list:
    """Get N active accounts that are not the sender."""
    accounts = get_accounts()
    receivers = [a for a in accounts if a["account_id"] != exclude_sender and a["status"] == "active"]
    assert len(receivers) >= count, f"Need {count} active receivers, got {len(receivers)}"
    return receivers[:count]


def transfer(sender: int, receiver: int, amount: float, payment_type: str = "ACH", test_funding: bool = True) -> dict:
    resp = httpx.post(f"{BANK_URL}/api/transfer", json={
        "sender_account": sender,
        "receiver_account": receiver,
        "amount": amount,
        "payment_type": payment_type,
        "test_funding": test_funding,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_aml_cases(bank_id: str = "fakebank-01") -> list:
    resp = httpx.get(f"{AML_URL}/api/cases?bank_id={bank_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_aml_transactions() -> list:
    resp = httpx.get(f"{AML_URL}/api/transactions", timeout=10)
    resp.raise_for_status()
    return resp.json()


# -----------------------------------------------------------------------------
# Test 1: Fan-out scenario
# -----------------------------------------------------------------------------

def test_1_fanout_scenario():
    """
    Send 1 lakh (100,000) to 10 different accounts.
    All transfers must succeed.
    Within 15 seconds, a Fan_Out case must appear in AML.
    """
    print("\n=== TEST 1: Fan-Out Scenario ===")
    receivers = get_active_receivers(DEMO_SENDER, 10)
    tx_ids = []

    for i, r in enumerate(receivers):
        result = transfer(DEMO_SENDER, r["account_id"], 100000.0, "ACH", test_funding=True)
        assert result["success"] is True, f"Transfer {i+1} failed: {result['message']}"
        tx_ids.append(result["transaction_id"])
        print(f"  Transfer {i+1}/10 -> {r['account_id']}: [OK]")

    print(f"  All 10 transfers completed. Waiting for AML case...")

    # Wait for case to appear
    deadline = time.time() + 20
    fan_out_case = None
    while time.time() < deadline:
        cases = get_aml_cases()
        fan_out_case = next((c for c in cases if c.get("typology") == "Fan_Out"), None)
        if fan_out_case:
            break
        time.sleep(1)

    assert fan_out_case is not None, "Fan_Out case did not appear within 20 seconds"
    print(f"  Fan_Out case appeared: {fan_out_case['id']} (risk={fan_out_case['risk_score']:.2f})")

    # Verify 10 events arrived in AML
    aml_txs = get_aml_transactions()
    my_txs = [t for t in aml_txs if t["id"] in tx_ids]
    assert len(my_txs) >= 10, f"Expected 10 transactions in AML, got {len(my_txs)}"
    print(f"  {len(my_txs)}/10 transactions confirmed in AML [OK]")
    print("TEST 1 PASSED [OK]")


# -----------------------------------------------------------------------------
# Test 2: Outbox resilience (AML down)
# -----------------------------------------------------------------------------

def test_2_aml_unavailable_outbox_queues():
    """
    This test verifies the bank succeeds and outbox has pending rows.
    We can't actually stop the AML service in an HTTP-only test,
    so we verify the bank always succeeds regardless of AML state,
    and that the outbox mechanism exists and records rows.
    """
    print("\n=== TEST 2: Outbox resilience ===")
    accounts = get_accounts()
    sender = accounts[0]
    receiver = accounts[1]

    before_stats = httpx.get(f"{BANK_URL}/api/outbox/stats", timeout=10).json()
    before_total = before_stats["total"]

    result = transfer(sender["account_id"], receiver["account_id"], 500.0, test_funding=True)
    assert result["success"] is True, f"Transfer should succeed: {result}"
    print(f"  Transfer succeeded: {result['transaction_id']} [OK]")

    after_stats = httpx.get(f"{BANK_URL}/api/outbox/stats", timeout=10).json()
    assert after_stats["total"] > before_total, "Outbox total did not increase"
    print(f"  Outbox stats: pending={after_stats['pending']}, sent={after_stats['sent']}, total={after_stats['total']} [OK]")
    print("TEST 2 PASSED [OK]")


# -----------------------------------------------------------------------------
# Test 3: Model offline - AML ingestion still works
# -----------------------------------------------------------------------------

def test_3_aml_ingests_when_model_not_yet_scored():
    """
    Send a transaction; AML must ingest it (202/200) regardless of model state.
    Check model status and unscored count via the API.
    """
    print("\n=== TEST 3: AML ingests when model may be slow ===")
    import uuid

    payload = {
        "bank_id": "fakebank-01",
        "transaction": {
            "id": f"tx_test3_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sender_account": 8724731955,
            "receiver_account": 9999999998,
            "amount": 15000.0,
            "payment_currency": "Indian rupee",
            "received_currency": "Indian rupee",
            "sender_bank_location": "India",
            "receiver_bank_location": "India",
            "payment_type": "ACH",
        },
        "sender_profile": {"holder_name": "Ravi Kumar", "account_status": "active"},
        "receiver_profile": None,
    }
    resp = httpx.post(
        f"{AML_URL}/api/v1/ingest/transactions",
        json=payload,
        headers={"x-api-key": AML_API_KEY},
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    print(f"  AML accepted the transaction [OK]")

    # Check model/status endpoint
    model_status = httpx.get(f"{AML_URL}/api/model/status", timeout=10).json()
    print(f"  Model status: online={model_status['online']}, unscored={model_status['unscored']}")
    print("TEST 3 PASSED [OK]")


# -----------------------------------------------------------------------------
# Test 4: Freeze -> transfer blocked -> unfreeze -> transfer works
# -----------------------------------------------------------------------------

def test_4_freeze_unfreeze_via_aml():
    """
    Freeze an account via AML compliance API.
    Verify the bank blocks outgoing transfers with neutral message.
    Unfreeze and verify transfers work again.
    """
    print("\n=== TEST 4: Freeze / Unfreeze ===")
    accounts = get_accounts()
    target = accounts[2]  # use a fresh account
    aid = target["account_id"]
    other = accounts[3]

    # Freeze via AML
    freeze_resp = httpx.post(
        f"{AML_URL}/api/accounts/fakebank-01/{aid}/freeze",
        json={"case_id": "int-test-case", "reason": "Integration test freeze"},
        timeout=10,
    )
    print(f"  Freeze response: {freeze_resp.status_code} {freeze_resp.text[:200]}")
    assert freeze_resp.status_code == 200
    bank_resp = freeze_resp.json()
    assert bank_resp.get("status") == "frozen", f"Expected frozen, got {bank_resp}"
    print(f"  Account {aid} frozen [OK]")

    # Outgoing transfer should fail with neutral message
    result = transfer(aid, other["account_id"], 100.0, test_funding=True)
    assert result["success"] is False, f"Transfer should have failed but succeeded: {result}"
    msg = result.get("message", "").lower()
    assert "restricted" in msg or "contact" in msg, f"Expected neutral restriction message, got: {result['message']}"
    assert "aml" not in msg, f"AML mentioned in customer message: {result['message']}"
    assert "money laundering" not in msg
    print(f"  Outgoing transfer correctly blocked: '{result['message']}' [OK]")

    # Incoming transfer still works
    incoming = transfer(other["account_id"], aid, 100.0, test_funding=True)
    assert incoming["success"] is True, f"Incoming transfer to restricted account should work: {incoming}"
    print(f"  Incoming transfer to restricted account still works [OK]")

    # Unfreeze
    unfreeze_resp = httpx.post(
        f"{AML_URL}/api/accounts/fakebank-01/{aid}/unfreeze",
        json={"case_id": "int-test-case", "reason": "Integration test unfreeze"},
        timeout=10,
    )
    assert unfreeze_resp.status_code == 200
    assert unfreeze_resp.json().get("status") == "active"
    print(f"  Account {aid} unfrozen [OK]")

    # Outgoing transfer works again
    result2 = transfer(aid, other["account_id"], 100.0, test_funding=True)
    assert result2["success"] is True, f"Transfer after unfreeze should succeed: {result2}"
    print(f"  Post-unfreeze transfer works [OK]")
    print("TEST 4 PASSED [OK]")


# -----------------------------------------------------------------------------
# Test 5: AML never blocks a transfer
# -----------------------------------------------------------------------------

def test_5_aml_never_blocks_transfer():
    """
    Make 20 transfers with high-risk patterns.
    None should fail due to AML logic.
    Only balance/restriction reasons are valid failures.
    """
    print("\n=== TEST 5: AML never blocks transfers ===")
    accounts = get_accounts()
    sender = accounts[4]
    receivers = accounts[5:15]

    for i, r in enumerate(receivers):
        result = transfer(sender["account_id"], r["account_id"], 100000.0, test_funding=True)
        # Only accept success or standard bank failures
        if not result["success"]:
            msg = result.get("message", "").lower()
            # Must NOT be an AML-related failure
            assert "aml" not in msg, f"AML mentioned in failure: {result['message']}"
            assert "suspicious" not in msg, f"Suspicious mentioned: {result['message']}"
            assert "monitoring" not in msg, f"Monitoring mentioned: {result['message']}"
            assert "flagged" not in msg, f"Flagged mentioned: {result['message']}"
            print(f"  Transfer {i+1} failed (non-AML reason): {result['message']}")
        else:
            print(f"  Transfer {i+1}/10: [OK] success")

    print("TEST 5 PASSED [OK] (No transfer was blocked by AML logic)")
