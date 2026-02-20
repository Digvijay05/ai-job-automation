"""Deploy workflow to n8n via REST API.

Reads the generated workflow JSON and imports it into the running n8n instance.
Requires N8N_API_URL and N8N_API_KEY environment variables.

Usage:
    python scripts/deploy_workflow.py [--activate]
"""
from __future__ import annotations

import json
import os
import sys
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("N8N_API_URL", "http://localhost:5678")
API_KEY = os.environ.get("N8N_API_KEY", "")
WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "src" / "workflows" / "workflow_main.json"


def _api(method: str, endpoint: str, body: dict | None = None) -> dict:
    """Make an authenticated n8n API request."""
    url = f"{BASE_URL}/api/v1{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-N8N-API-KEY": API_KEY,
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        logger.error("API %s %s -> %d: %s", method, endpoint, e.code, body_text[:500])
        raise
    except URLError as e:
        logger.error("Connection failed: %s (is n8n running at %s?)", e.reason, BASE_URL)
        raise


def deploy(activate: bool = False) -> str:
    """Deploy workflow_main.json to n8n. Returns the workflow ID."""
    if not API_KEY:
        logger.error("N8N_API_KEY not set. Export it or add to .env.")
        sys.exit(1)

    if not WORKFLOW_PATH.exists():
        logger.error("Workflow JSON not found: %s", WORKFLOW_PATH)
        logger.info("Run: python src/scripts/build_workflow.py first.")
        sys.exit(1)

    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded workflow: %d nodes, %d connection sources",
                len(workflow["nodes"]), len(workflow["connections"]))

    # Check for existing workflow with same name
    existing = _api("GET", "/workflows")
    match = next(
        (w for w in existing.get("data", [])
         if w["name"] == workflow["name"]),
        None,
    )

    if match:
        wf_id = match["id"]
        logger.info("Updating existing workflow: %s (ID: %s)", match["name"], wf_id)
        result = _api("PUT", f"/workflows/{wf_id}", workflow)
    else:
        logger.info("Creating new workflow: %s", workflow["name"])
        result = _api("POST", "/workflows", workflow)
        wf_id = result["id"]

    logger.info("Deployed workflow ID: %s", wf_id)

    if activate:
        _api("PATCH", f"/workflows/{wf_id}", {"active": True})
        logger.info("Workflow activated.")

    logger.info("Done. Open: %s/workflow/%s", BASE_URL, wf_id)
    return wf_id


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deploy workflow to n8n")
    parser.add_argument("--activate", action="store_true",
                        help="Activate the workflow after deployment")
    args = parser.parse_args()
    deploy(activate=args.activate)
