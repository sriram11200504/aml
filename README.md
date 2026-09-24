# AML Demo Monorepo

An end-to-end, production-grade demonstration repository containing a **Fake Bank** financial application and a bank-agnostic **Anti-Money Laundering (AML) Platform**, complete with mock ML model scoring service, integration documentation, and end-to-end HTTP integration tests.

---

## Architecture Overview

```
/aml-demo
├── /fake-bank             # Core Banking API & Customer Portal UI (Port 8000)
├── /aml-platform          # AML Monitoring System, Rule Engine, Dashboard & Mock Model (Port 8100/8200)
├── /docs                  # Contracts and Demo Walkthrough
│   ├── integration_contract.md
│   ├── model_api_contract.md
│   └── demo_script.md
├── /integration-tests     # E2E Test Suite (Pytest HTTP)
├── docker-compose.yml     # Containerized deployment stack
├── run_all.ps1 / .sh      # Local multi-process runner (SQLite)
└── stop_all.ps1 / .sh     # Local cleanup runner
```

---

## How to Run the Project

### Option 1: Local Development (SQLite Mode - Recommended)

Requires Python 3.10+.

1. **Start all 5 services:**
   - **Windows (PowerShell):**
     ```powershell
     .\run_all.ps1
     ```
   - **Linux / macOS (Bash):**
     ```bash
     chmod +x run_all.sh stop_all.sh
     ./run_all.sh
     ```

2. **Access Applications:**
   - **Fake Bank Portal:** `http://localhost:8000` (Use this to create accounts and initiate transactions).
   - **AML Dashboard:** `http://localhost:8100/dashboard` (Use this to view real-time transaction streams, manage compliance alerts, and unfreeze accounts).
   - **AML API Documentation:** `http://localhost:8100/docs`
   - **Mock Model Service:** `http://localhost:8200/docs`

3. **Stop all services:**
   - **Windows:** `.\stop_all.ps1`
   - **Linux/macOS:** `./stop_all.sh`

---

### Option 2: Docker Compose (PostgreSQL Mode)

Requires Docker Desktop or Docker Engine.

```bash
# Build and start all 7 services (2 DBs, 2 backends, 2 frontends, 1 model service)
docker-compose up --build -d

# Check status
docker-compose ps

# Tear down
docker-compose down -v
```

---

## Running Integration Tests

The integration test suite executes HTTP-only E2E tests covering all 5 core AML operational scenarios:
1. Normal transaction processing & asynchronous webhook ingestion.
2. Outbox pattern & resilient retry queue.
3. Rule-based alert generation (Large single transaction > $10,000).
4. Machine Learning model evaluation & fan-out topology scoring (> 0.85).
5. Account freeze / unfreeze lifecycle enforced by bank transaction routing.

```bash
cd integration-tests
pip install -r requirements.txt
pytest tests/ -v -s
```

---

## Model Contract Testing

To test model service compliance against the model API specification (for both the mock model service and future production ML models):

```bash
cd aml-platform
pip install -r requirements.txt
pytest tests/model_contract_tests.py --model-url http://localhost:8200 -v
```

---

## Documentation Links

- [Bank-to-AML Integration Contract](docs/integration_contract.md)
- [AML-to-Model API Contract](docs/model_api_contract.md)
- [Step-by-Step Demo Script](docs/demo_script.md)

---

## Integrating the Trained ML Model

The AML platform is designed to allow a seamless swap between the included **Mock Model Service** and your **Trained ML Model API**. The model service integration is completely decoupled using standard HTTP REST contracts.

### Step-by-Step Integration

1. **Expose your ML Model as a REST API:**
   Your production model must expose a `POST /predict` endpoint (or similar) that accepts a standard JSON payload containing a transaction node and returns a float `risk_score` (between 0 and 1) along with an optional list of `flagged_rules`.
   *See `docs/model_api_contract.md` for the exact input/output JSON schema.*

2. **Test your ML API against the Contract:**
   Before swapping, ensure your ML model complies with the AML platform expectations by running the contract tests against your model's URL:
   ```bash
   cd aml-platform
   pytest tests/model_contract_tests.py --model-url <YOUR_MODEL_API_URL> -v
   ```

3. **Update the Environment Variable:**
   The AML Platform locates the scoring service via the `MODEL_API_URL` environment variable.
   - **If running locally (run_all.ps1):**
     Edit `run_all.ps1` (or `run_all.sh`) and modify the `MODEL_API_URL` variable to point to your new ML model's host instead of `http://127.0.0.1:8200`.
   - **If using Docker Compose:**
     Edit `docker-compose.yml`, locate the `aml-platform` service, and change the `MODEL_API_URL` environment variable under `environment`.

4. **Restart the Platform:**
   Stop the services using `.\stop_all.ps1` and start them again with `.\run_all.ps1`. The AML Background Worker will immediately start routing all new transactions to your custom machine learning model for real-time risk scoring!
