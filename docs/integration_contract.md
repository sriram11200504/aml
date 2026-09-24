# AML Platform – Integration Contract v1.0

This document is the **single source of truth** for all HTTP calls between the fake-bank, the AML platform, and the model service.  
Copies live in `fake-bank/docs/` and `aml-platform/docs/`. Run `scripts/verify_contract_copies.sh` (or `.ps1`) to assert all copies are byte-identical.

---

## 1. Bank → AML: Transaction Event

After a bank transfer is **committed** to the bank database, the bank dispatcher posts the event asynchronously.

### Single transaction
```
POST {AML_URL}/api/v1/ingest/transactions
Header: X-API-Key: <api_key>
Content-Type: application/json
```

**Request body:**
```json
{
  "bank_id": "fakebank-01",
  "transaction": {
    "id": "tx_000123",
    "timestamp": "2026-09-24T14:05:11Z",
    "sender_account": 8724731955,
    "receiver_account": 2769355426,
    "amount": 100000.0,
    "payment_currency": "Indian rupee",
    "received_currency": "Indian rupee",
    "sender_bank_location": "India",
    "receiver_bank_location": "India",
    "payment_type": "ACH"
  },
  "sender_profile": {
    "holder_name": "Ravi Kumar",
    "account_status": "active"
  },
  "receiver_profile": {
    "holder_name": "Priya Sharma",
    "account_status": "active"
  }
}
```

> `receiver_profile` may be `null` if the receiver is an external account.

**Payment type enum:** `ACH | Cheque | Credit card | Debit card | Cross-border | Cash Withdrawal | Cash Deposit`

**Response:** `202 Accepted`
```json
{ "accepted": true }
```

The AML platform **must** treat duplicate `transaction.id` values as idempotent (accept, do not double-process).

### Batch transactions
```
POST {AML_URL}/api/v1/ingest/transactions/batch
Header: X-API-Key: <api_key>
```

**Request body:**
```json
{
  "bank_id": "fakebank-01",
  "transactions": [
    { "transaction": { ... }, "sender_profile": { ... }, "receiver_profile": { ... } },
    ...
  ]
}
```

**Response:** `202 Accepted`
```json
{ "accepted": true, "count": 5 }
```

---

## 2. AML → Bank: Compliance Callback

These calls are **admin-initiated only** from the AML dashboard. The bank must never block or delay a transfer pending AML action.

### Freeze account
```
POST {BANK_COMPLIANCE_URL}/compliance/accounts/{account_id}/freeze
Header: X-API-Key: <compliance_api_key>
Content-Type: application/json
```

**Request body:**
```json
{
  "case_id": "case_abc123",
  "reason": "Suspected Fan-out pattern"
}
```

**Response:** `200 OK`
```json
{ "account_id": 8724731955, "status": "frozen" }
```

### Unfreeze account
```
POST {BANK_COMPLIANCE_URL}/compliance/accounts/{account_id}/unfreeze
Header: X-API-Key: <compliance_api_key>
Content-Type: application/json
```

**Request body:**
```json
{
  "case_id": "case_abc123",
  "reason": "Investigation concluded – false positive"
}
```

**Response:** `200 OK`
```json
{ "account_id": 8724731955, "status": "active" }
```

**Bank behaviour:** A frozen/restricted account blocks outgoing transfers only (incoming transfers are allowed). The account status returned is `"frozen"` (shown as `"restricted"` internally). The customer sees a neutral message: *"Your account is restricted. Please contact your branch."* — **no mention of AML or money laundering anywhere in the customer UI.**

---

## 3. AML → Model API

### Score a transaction
```
POST {MODEL_API_URL}/v1/score
Content-Type: application/json
```

**Request body:**
```json
{
  "transaction": {
    "id": "tx_000123",
    "timestamp": "2026-09-24T14:05:11Z",
    "sender_account": 8724731955,
    "receiver_account": 2769355426,
    "amount": 100000.0,
    "payment_currency": "Indian rupee",
    "received_currency": "Indian rupee",
    "sender_bank_location": "India",
    "receiver_bank_location": "India",
    "payment_type": "ACH"
  },
  "sender_history": [
    { ... same transaction fields ... }
  ],
  "receiver_history": [
    { ... same transaction fields ... }
  ]
}
```

> **History rules (enforced by AML, not the model):**
> - All transactions involving the account (as sender OR receiver) in the **last 7 days BEFORE** the current transaction timestamp.
> - Maximum 1,000 rows per history array.
> - **No future rows** – history must never include transactions timestamped after the current transaction.

**Response:**
```json
{
  "transaction_id": "tx_000123",
  "risk_score": 0.87,
  "typology": "Fan_Out",
  "reasons": [
    {
      "text": "Sender paid 10 distinct receivers within 24 hours",
      "feature": "distinct_receivers_24h",
      "impact": 0.42
    }
  ],
  "model_version": "mock-v1.0"
}
```

> `typology` may be `null` for low-risk transactions.
> `risk_score` is in `[0.0, 1.0]`.
> The labels `Is_laundering` and `Laundering_type` **never appear in any payload**.

**Known typologies:** `Fan_Out | Fan_In | Structuring | Cycle | Scatter-Gather | Gather-Scatter | Rapid_Pass_Through | Behavioural_Change | Single_Large | Cash_Withdrawal`

### Health check
```
GET {MODEL_API_URL}/health
Response 200: { "status": "ok" }
```

### Model info
```
GET {MODEL_API_URL}/v1/model-info
Response 200: { "version": "mock-v1.0", "features": ["distinct_receivers_24h", ...] }
```

---

## 4. Health Endpoints (All Components)

Every service must expose:
```
GET /health
Response 200: { "status": "ok", "service": "<name>", "version": "1.0.0" }
```

| Service | Port | URL |
|---|---|---|
| fake-bank API | 8000 | http://localhost:8000/health |
| fake-bank frontend | 3000 | http://localhost:3000 |
| AML platform API | 8100 | http://localhost:8100/health |
| AML platform dashboard | 4000 | http://localhost:4000 |
| Mock model service | 8200 | http://localhost:8200/health |
| fake-bank Postgres | 5433 | (TCP) |
| AML Postgres | 5434 | (TCP) |

---

## 5. Idempotency & Ordering

- The bank outbox retries with exponential back-off. The AML ingest endpoint must be safe to call multiple times with the same `transaction.id`.
- AML must tolerate out-of-order delivery.
- If the AML platform is down, the bank must queue the event and retry indefinitely.
- If the model service is down, AML must queue unscored transactions and retry when the model returns.

---

## 6. Security

- All bank→AML calls carry `X-API-Key` (configured per bank in AML `banks` table).
- All AML→Bank compliance calls carry `X-API-Key` (configured in `COMPLIANCE_API_KEY` env var).
- API keys are never logged or returned in API responses.
