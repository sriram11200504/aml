# AML Platform – Model API Contract v1.0

This document defines the HTTP API that a **model service** must implement to be compatible with the AML platform.  
The mock model service (`/aml-platform/mock-model-service`) is the reference implementation.  
My teammate building the real ML model should implement this contract exactly.

---

## OpenAPI 3.0 Schema

```yaml
openapi: "3.0.3"
info:
  title: AML Model Scoring API
  version: "1.0"
  description: >
    Score a single transaction for money-laundering risk.
    The AML platform calls this endpoint for every received transaction.

paths:
  /health:
    get:
      summary: Health check
      responses:
        "200":
          description: Service is healthy
          content:
            application/json:
              schema:
                type: object
                required: [status]
                properties:
                  status:
                    type: string
                    enum: [ok]
              example:
                status: ok

  /v1/model-info:
    get:
      summary: Model metadata
      responses:
        "200":
          description: Model version and feature list
          content:
            application/json:
              schema:
                type: object
                required: [version, features]
                properties:
                  version:
                    type: string
                  features:
                    type: array
                    items:
                      type: string
              example:
                version: "real-v2.1"
                features:
                  - distinct_receivers_24h
                  - distinct_senders_24h
                  - amount_vs_30d_avg
                  - cycle_detected
                  - structuring_score
                  - rapid_pass_through_ratio

  /v1/score:
    post:
      summary: Score a transaction
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/ScoreRequest"
      responses:
        "200":
          description: Risk score and explanation
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ScoreResponse"
        "422":
          description: Validation error

components:
  schemas:
    TransactionFields:
      type: object
      required:
        - id
        - timestamp
        - sender_account
        - receiver_account
        - amount
        - payment_currency
        - received_currency
        - sender_bank_location
        - receiver_bank_location
        - payment_type
      properties:
        id:
          type: string
          description: Unique transaction identifier
        timestamp:
          type: string
          format: date-time
          description: ISO-8601 UTC timestamp
        sender_account:
          type: integer
          description: 10-digit sender account number
        receiver_account:
          type: integer
          description: 10-digit receiver account number (0 for external)
        amount:
          type: number
          format: float
          description: Transaction amount in payment currency
        payment_currency:
          type: string
          description: Currency name (e.g. "Indian rupee")
        received_currency:
          type: string
        sender_bank_location:
          type: string
        receiver_bank_location:
          type: string
        payment_type:
          type: string
          enum:
            - ACH
            - Cheque
            - Credit card
            - Debit card
            - Cross-border
            - Cash Withdrawal
            - Cash Deposit

    ScoreRequest:
      type: object
      required: [transaction, sender_history, receiver_history]
      properties:
        transaction:
          $ref: "#/components/schemas/TransactionFields"
        sender_history:
          type: array
          maxItems: 1000
          description: >
            All transactions involving the sender account (as sender OR receiver)
            in the 7 days BEFORE the current transaction timestamp.
            Never includes the current transaction or future rows.
          items:
            $ref: "#/components/schemas/TransactionFields"
        receiver_history:
          type: array
          maxItems: 1000
          description: >
            All transactions involving the receiver account (as sender OR receiver)
            in the 7 days BEFORE the current transaction timestamp.
          items:
            $ref: "#/components/schemas/TransactionFields"

    Reason:
      type: object
      required: [text, feature, impact]
      properties:
        text:
          type: string
          description: Plain-English explanation
        feature:
          type: string
          description: Machine name of the feature
        impact:
          type: number
          format: float
          description: Contribution to the risk score (0.0 – 1.0)

    ScoreResponse:
      type: object
      required: [transaction_id, risk_score, reasons, model_version]
      properties:
        transaction_id:
          type: string
        risk_score:
          type: number
          format: float
          minimum: 0.0
          maximum: 1.0
        typology:
          type: string
          nullable: true
          enum:
            - Fan_Out
            - Fan_In
            - Structuring
            - Cycle
            - Scatter-Gather
            - Gather-Scatter
            - Rapid_Pass_Through
            - Behavioural_Change
            - Single_Large
            - Cash_Withdrawal
            - null
        reasons:
          type: array
          items:
            $ref: "#/components/schemas/Reason"
        model_version:
          type: string
```

---

## Critical Rules for Model Implementors

1. **No label leakage.** The fields `Is_laundering` and `Laundering_type` must **never** appear in any request or response payload.
2. **Stateless.** The model must not store state across calls. All context is in `sender_history` and `receiver_history`.
3. **3-second timeout.** The AML platform times out model calls after 3 seconds and queues the transaction for retry.
4. **Idempotent.** Calling `/v1/score` twice with the same payload must return the same `risk_score`.
5. **History contract.** The model may trust that history arrays contain no future rows and are capped at 1,000 entries.
6. **Score range.** `risk_score` must be in `[0.0, 1.0]` inclusive.
7. **Typology nullable.** For low-risk transactions, return `"typology": null`.

---

## Swapping In the Real Model

1. Set `MODEL_API_URL=http://<real-model-host>:<port>` in `aml-platform/.env`.
2. Run the contract test suite: `cd aml-platform && pytest tests/model_contract_tests.py --model-url http://<real-model-host>:<port>`
3. If all tests pass, restart the AML platform worker. No code changes required.

---

## Contract Test Suite

Located at `aml-platform/tests/model_contract_tests.py`. Tests verify:

- `GET /health` returns `{"status": "ok"}` with HTTP 200.
- `GET /v1/model-info` returns `version` (string) and `features` (array of strings).
- `POST /v1/score` with a minimal valid payload returns HTTP 200 with correct schema.
- `risk_score` is always in `[0.0, 1.0]`.
- `typology` is either null or one of the known enum values.
- Duplicate calls with the same payload return identical `risk_score` (idempotency).
- History arrays with 0 entries are accepted.
- History arrays with 1,000 entries are accepted without timeout.
- Future rows in history do not crash the model (graceful handling).
