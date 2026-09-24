# AML Monitoring System Demo Script

This demo script walks through testing and showcasing all core capabilities of the AML Monitoring Platform paired with the Fake Bank simulation.

---

## 1. Environment Setup

### Option A: Local Run (SQLite Mode)
Run the automated startup script:
- **Windows (PowerShell):**
  ```powershell
  .\run_all.ps1
  ```
- **Linux/macOS (Bash):**
  ```bash
  chmod +x run_all.sh stop_all.sh
  ./run_all.sh
  ```

### Option B: Docker Compose (PostgreSQL Mode)
```bash
docker-compose up --build -d
```

---

## 2. Interface Endpoints

| Component | URL | Credentials / Notes |
| :--- | :--- | :--- |
| **Fake Bank Web App** | `http://localhost:8000` | Account Portal & Manual Transfer Interface |
| **AML Platform Dashboard** | `http://localhost:8100/dashboard` | Alert Queue, Rule Config, Account Freeze Management |
| **AML Platform API Docs** | `http://localhost:8100/docs` | FastAPI Swagger UI |
| **Mock Model Service** | `http://localhost:8200/docs` | Risk Scoring API |

---

## 3. Step-by-Step Demo Scenarios

### Scenario 1: Normal Low-Risk Transactions
1. Navigate to **Fake Bank Web UI** at `http://localhost:8000`.
2. Transfer **$150.00** from Account `ACC-1001` to `ACC-1002`.
3. **Observed Behavior:**
   - Transfer succeeds instantly in Fake Bank.
   - Bank asynchronously emits webhooks to the AML Platform.
   - In **AML Dashboard** (`http://localhost:8100/dashboard`), inspect recent transactions. The transaction shows status `PROCESSED` with a low ML risk score (e.g. `0.05`). No alert is raised.

---

### Scenario 2: High Value Transaction (Rule-Based Alert)
1. Transfer **$15,000.00** from Account `ACC-1001` to `ACC-1003`.
2. **Observed Behavior:**
   - Bank completes transaction without interruption (AML monitoring is asynchronous and never blocks bank performance).
   - In **AML Dashboard**, navigate to the **Alerts** tab.
   - A new alert is visible triggered by Rule `RUL-001: Large Single Transaction (> $10,000)`.
   - Alert status is set to `NEW`.

---

### Scenario 3: Rapid Fan-Out Structuring (ML + Rule Alert)
1. Execute a series of 5 rapid transfers of **$9,500.00** each from `ACC-1001` to 5 distinct destination accounts (`ACC-2001`, `ACC-2002`, `ACC-2003`, `ACC-2004`, `ACC-2005`) within 60 seconds.
2. **Observed Behavior:**
   - Mock Model Service identifies rapid fan-out topology and computes an elevated risk score (e.g. `0.92`).
   - AML Platform flags the transaction set under both ML Model Score threshold (> 0.85) and Structuring Rule (`RUL-002`).
   - High-severity Alert is created in the AML Dashboard.

---

### Scenario 4: Compliance Investigation & Account Freeze
1. In the **AML Dashboard** (`http://localhost:8100/dashboard`), click on the high-severity alert from Scenario 3.
2. Review transaction history and graph visualization for `ACC-1001`.
3. Click **Freeze Account**. Select reason: `Suspicious Structuring & Velocity`.
4. Return to **Fake Bank Web UI** (`http://localhost:8000`) and attempt any transfer from `ACC-1001`.
5. **Observed Behavior:**
   - Fake Bank rejects the transaction with error: `403 Account ACC-1001 is frozen by compliance order`.

---

### Scenario 5: Resolution & Account Unfreeze
1. In **AML Dashboard**, update the alert status to `RESOLVED - FALSE POSITIVE` or complete compliance review.
2. Click **Unfreeze Account** for `ACC-1001`.
3. Return to **Fake Bank Web UI** and attempt transfer from `ACC-1001`.
4. **Observed Behavior:**
   - Transaction completes successfully.

---

## 4. Teardown

To stop all services:
- **Windows (PowerShell):**
  ```powershell
  .\stop_all.ps1
  ```
- **Linux/macOS (Bash):**
  ```bash
  ./stop_all.sh
  ```
- **Docker Compose:**
  ```bash
  docker-compose down -v
  ```
