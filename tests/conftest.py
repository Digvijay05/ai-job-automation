"""
Pytest configuration and shared fixtures for E2E testing.
"""
import os
import time
import pytest
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from pathlib import Path

# Load env paths manually since dotenv might not be available in all envs yet
def load_env():
    root_env = Path(__file__).resolve().parent.parent / ".env"
    if root_env.exists():
        with open(root_env, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k, v)

load_env()

@pytest.fixture(scope="session")
def n8n_url():
    """Base URL for the n8n instance."""
    return os.environ.get("N8N_API_URL", "http://localhost:5678").rstrip("/")

@pytest.fixture(scope="session")
def webhook_url(n8n_url):
    """URL for the main job automation webhook."""
    return f"{n8n_url}/webhook/process"

@pytest.fixture(scope="session")
def api_headers():
    """Headers required to trigger the webhook."""
    secret = os.environ.get("N8N_API_KEY", "") # Using API key as fallback or actual header
    # The workflow checks: $json.headers["x-automation-secret"]
    # So we need to provide x-automation-secret.
    automation_secret = os.environ.get("AUTOMATION_SECRET", "test-secret-123")
    return {
        "x-automation-secret": automation_secret,
        "Content-Type": "application/json"
    }

@pytest.fixture(scope="session")
def db_conn():
    """PostgreSQL database connection fixture."""
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "job_automation"),
        user=os.environ.get("POSTGRES_USER", "automation_user"),
        password=os.environ.get("POSTGRES_PASSWORD", "auto123")
    )
    conn.autocommit = True
    yield conn
    conn.close()

@pytest.fixture
def db(db_conn):
    """Returns a cursor that yields dictionaries."""
    with db_conn.cursor(cursor_factory=RealDictCursor) as cur:
        yield cur

@pytest.fixture(scope="session")
def mock_data_dir():
    """Path to the generated mock data."""
    return Path(__file__).resolve().parent / "mock_data"

@pytest.fixture
def api_client():
    """Requests session for API calls."""
    session = requests.Session()
    yield session
    session.close()

@pytest.fixture
def wait_for_workflow():
    """Helper to wait for async workflow processing."""
    def _wait(seconds=5):
        time.sleep(seconds)
    return _wait
