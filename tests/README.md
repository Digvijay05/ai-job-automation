# Automated E2E Workflow Testing

This directory contains the automated end-to-end testing suite for the AI Job Automation workflow. The tests are built using `pytest` and automatically validate the n8n API, webhook triggers, AI execution, and PostgreSQL data persistence.

## Architecture

* **Runner:** `pytest` (configured via `pytest.ini`)
* **Environment:** `python-dotenv` loads from the root `.env`
* **Fixtures (`conftest.py`):**
  * `db_conn` / `db`: PostgreSQL direct connection for data persistence verification.
  * `api_client`: Requests session for triggering the n8n Webhook.
  * `api_headers`: Automatically fetches `AUTOMATION_SECRET` and constructs required headers.
  * `mock_data_dir`: Loads the generated WeasyPrint/ReportLab PDFs and JSON entities.
* **Test Cases (`test_e2e.py`):**
  * `TC-01`: API Health Validation
  * `TC-02`: Webhook Auth & Security Rejection
  * `TC-03`: E2E Workflow Execution & DB Verification (Nominal)
  * `TC-04`: Missing Fields & Error Handling
  * `TC-05`: Idempotency / Duplicate Detection
  * `TC-06`: Database Schema Integrity

## Local Execution

To run the tests locally:

```bash
# 1. Install dependencies
pip install -r tests/requirements-test.txt

# 2. Ensure n8n and Postgres containers are running
docker compose up -d

# 3. Generate mock data (if not already generated)
python tests/mock_data/generate_resumes.py

# 4. Run the suite
pytest tests/ -v
```

### Viewing the Report
A self-contained HTML report is automatically generated at `report.html` via `pytest-html`. Open it in any browser for a detailed breakdown of passes, failures, execution times, and tracebacks.

## CI/CD Execution (GitHub Actions)

The test suite is fully deterministic and runs headlessly. It returns a standard `0` exit code on success and `1` on failure, making it ideal for CI pipes.

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r tests/requirements-test.txt
      - name: Start Services
        run: docker compose up -d
      - name: Run E2E Tests
        run: pytest tests/ -v --html=report.html
      - name: Upload Test Report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: pytest-report
          path: report.html
```
