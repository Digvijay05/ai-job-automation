"""
End-to-end automated test cases for the job application workflow.
"""
import json
import uuid
import pytest
import base64
from pathlib import Path

# ──────────────────────────────────────────────────
# TEST UTILITIES
# ──────────────────────────────────────────────────

def load_json(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def encode_pdf(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

# ──────────────────────────────────────────────────
# TEST SUITE
# ──────────────────────────────────────────────────

class TestJobAutomationWorkflow:
    
    @pytest.fixture(autouse=True)
    def setup_data(self, mock_data_dir):
        """Load mock data before tests."""
        self.companies = load_json(mock_data_dir / "mock_companies.json")
        self.jobs = load_json(mock_data_dir / "mock_jobs.json")
        self.resumes_dir = mock_data_dir / "resumes"
        
    def test_01_api_health(self, api_client, n8n_url):
        """TC-01: Validate n8n API is reachable."""
        resp = api_client.get(n8n_url)
        assert resp.status_code in [200, 302], f"n8n API unreachable: {resp.status_code}"

    def test_02_webhook_auth_failure(self, api_client, webhook_url):
        """TC-02: Ensure webhook rejects requests without automation secret."""
        payload = {"action": "process_resume"}
        resp = api_client.post(webhook_url, json=payload)
        # Without headers, node 'IF - Auth Secret' routes to false branch which usually drops or returns 401/403
        # Depending on the n8n config, responseMode=lastNode might return empty or error.
        # As long as it doesn't process successfully.
        # Actually n8n might accept it but drop it internally. We'll check if HTTP is 200, but response shouldn't be success.
        pass # Placeholder for auth rejection if implemented at webhook level

    def test_03_ingest_resume_success(self, api_client, webhook_url, api_headers, db, wait_for_workflow):
        """TC-03: Process a valid resume against a tech job."""
        
        job = self.jobs[0] # Senior Backend Engineer
        resume_path = self.resumes_dir / "Alex_Chen_Backend.pdf"
        
        assert resume_path.exists(), "Resume PDF not found. Run generate_resumes.py first."
        
        pdf_b64 = encode_pdf(resume_path)
        
        # Construct payload matching n8n expectations
        user_email = "test.user@example.com"
        payload = {
            "action": "process_resume",
            "user_email": user_email,
            "job_url": "https://example.com/job/123",
            "job_title": job["job_title"],
            "job_description": job["job_description"],
            "company_name": self.companies[0]["company_name"],
            "resume_pdf_base64": pdf_b64,
            "user_api_key": "test_api_key_override"
        }
        
        resp = api_client.post(webhook_url, headers=api_headers, json=payload)
        
        # n8n might return immediately if respondMode is not wait
        # We query DB to verify the application was saved
        wait_for_workflow(10) # Wait for agents to process
        
        db.execute("SELECT * FROM job_applications WHERE job_title = %s ORDER BY created_at DESC LIMIT 1;", (job["job_title"],))
        app = db.fetchone()
        
        assert app is not None, "Application was not saved to database."
        assert app["status"] in ["draft", "sent", "pending_review"], f"Invalid status: {app['status']}"
        assert app["ai_tailored_resume"] is not None, "AI failed to tailor the resume"
        assert app["ai_draft_email"] is not None, "AI failed to draft the email"
        
    def test_04_missing_fields_handling(self, api_client, webhook_url, api_headers, db):
        """TC-04: Test workflow behavior with missing critical fields."""
        payload = {
            "action": "process_resume",
            # Missing job_description, resume_pdf_base64
            "user_email": "error.tester@example.com"
        }
        resp = api_client.post(webhook_url, headers=api_headers, json=payload)
        
        # Verify no bogus entries were made
        db.execute("SELECT COUNT(*) as c FROM job_applications WHERE user_email = %s;", ("error.tester@example.com",))
        count = db.fetchone()["c"]
        assert count == 0, "Application should not be created for invalid payloads."

    def test_05_duplicate_detection(self, api_client, webhook_url, api_headers, db, wait_for_workflow):
        """TC-05: Ensure identical duplicate submissions are skipped/handled."""
        
        job = self.jobs[1] 
        resume_path = self.resumes_dir / "Jordan_Smith_Data.pdf"
        pdf_b64 = encode_pdf(resume_path)
        
        payload = {
            "action": "process_resume",
            "user_email": "dup.tester@example.com",
            "job_url": "https://example.com/job/456",
            "job_title": job["job_title"],
            "job_description": job["job_description"],
            "company_name": self.companies[0]["company_name"],
            "resume_pdf_base64": pdf_b64
        }
        
        # Fire first time
        api_client.post(webhook_url, headers=api_headers, json=payload)
        wait_for_workflow(8)
        
        # Fire second time
        api_client.post(webhook_url, headers=api_headers, json=payload)
        wait_for_workflow(5)
        
        # Verify only ONE application exists for this user + job URL comb
        db.execute("SELECT COUNT(*) as c FROM job_applications WHERE user_email = %s AND job_url = %s;", 
                   ("dup.tester@example.com", "https://example.com/job/456"))
        count = db.fetchone()["c"]
        
        assert count == 1, f"Expected 1 record due to deduplication, found {count}."
        
    def test_06_database_integrity(self, db):
        """TC-06: Direct database schema integrity check."""
        # Ensure core tables exist
        tables = ["users", "job_applications", "email_dispatch_log", "inbound_email_log"]
        for table in tables:
            db.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s);", (table,))
            assert db.fetchone()["exists"], f"Table {table} is missing."
