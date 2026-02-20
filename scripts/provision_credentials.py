"""Auto-provision n8n credentials via Public API.

Reads credential definitions from config/credentials.template.json,
resolves secrets from .env / environment variables, and creates or
updates credentials in the running n8n instance.

Writes resolved credential IDs to config/credentials.json for use
by build_workflow.py.

Usage:
    python scripts/provision_credentials.py [--dry-run]

Requires:
    N8N_API_KEY  — n8n Public API key (env var or .env)
    N8N_API_URL  — n8n base URL (default: http://localhost:5678)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ──────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("provision_credentials")

# ──────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "config" / "credentials.template.json"
OUTPUT_PATH = PROJECT_ROOT / "config" / "credentials.json"
DOTENV_PATH = PROJECT_ROOT / ".env"

# ──────────────────────────────────────────────────
# .env loader (no external dependency)
# ──────────────────────────────────────────────────
def _load_dotenv(dotenv_path: Path) -> None:
    """Load .env file into os.environ (simple key=value parser)."""
    if not dotenv_path.exists():
        logger.warning(".env not found at %s — relying on system env vars", dotenv_path)
        return
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Don't overwrite existing env vars
            if key not in os.environ:
                os.environ[key] = value


# ──────────────────────────────────────────────────
# n8n API Client
# ──────────────────────────────────────────────────
class N8nApiClient:
    """Minimal n8n Public API client for credential management."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _request(self, method: str, endpoint: str,
                 body: dict | None = None) -> dict:
        url = f"{self.base_url}/api/v1{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-N8N-API-KEY": self.api_key,
        }
        data = json.dumps(body).encode("utf-8") if body else None
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            logger.error("API %s %s -> %d: %s",
                         method, endpoint, e.code, body_text[:500])
            raise
        except URLError as e:
            logger.error("Connection failed: %s (is n8n at %s?)",
                         e.reason, self.base_url)
            raise

    def list_credentials(self) -> list[dict]:
        """List all existing credentials."""
        result = self._request("GET", "/credentials")
        return result.get("data", [])

    def create_credential(self, name: str, cred_type: str,
                          data: dict) -> dict:
        """Create a new credential. Returns the created credential."""
        return self._request("POST", "/credentials", {
            "name": name,
            "type": cred_type,
            "data": data,
        })

    def delete_credential(self, cred_id: str) -> None:
        """Delete a credential by ID."""
        self._request("DELETE", f"/credentials/{cred_id}")

    def get_credential_schema(self, cred_type: str) -> dict:
        """Get the data schema for a credential type."""
        return self._request("GET", f"/credentials/schema/{cred_type}")


# ──────────────────────────────────────────────────
# Credential Resolver
# ──────────────────────────────────────────────────
def _resolve_data(data_env_map: dict[str, dict], cred_name: str) -> dict:
    """Resolve credential data fields from env vars or literal values.

    Each field is either:
        {"value": <literal>}  — used directly
        {"env": "VAR_NAME"}   — resolved from os.environ
    """
    resolved: dict = {}
    for field, source in data_env_map.items():
        if "value" in source:
            resolved[field] = source["value"]
        elif "env" in source:
            env_var = source["env"]
            value = os.environ.get(env_var)
            if value is None:
                logger.error("Missing env var %s for credential '%s' field '%s'",
                             env_var, cred_name, field)
                sys.exit(1)
            resolved[field] = value
        else:
            logger.error("Invalid source for field '%s' in '%s': %s",
                         field, cred_name, source)
            sys.exit(1)
    return resolved


def _find_existing(existing: list[dict], name: str,
                   cred_type: str) -> dict | None:
    """Find an existing credential by name and type."""
    for cred in existing:
        if cred.get("name") == name and cred.get("type") == cred_type:
            return cred
    return None


# ──────────────────────────────────────────────────
# Main Provisioning Logic
# ──────────────────────────────────────────────────
def provision(dry_run: bool = False) -> None:
    """Provision all credentials defined in the template."""
    # Load .env
    _load_dotenv(DOTENV_PATH)

    # Validate API key
    api_key = os.environ.get("N8N_API_KEY", "")
    if not api_key:
        logger.error("N8N_API_KEY not set. Export it or add to .env.")
        sys.exit(1)

    base_url = os.environ.get("N8N_API_URL", "http://localhost:5678")
    client = N8nApiClient(base_url, api_key)

    # Load template
    if not TEMPLATE_PATH.exists():
        logger.error("Template not found: %s", TEMPLATE_PATH)
        sys.exit(1)

    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    definitions = template.get("credentials", [])
    logger.info("Loaded %d credential definitions from template", len(definitions))

    # Get existing credentials from n8n
    existing = client.list_credentials()
    logger.info("Found %d existing credentials in n8n", len(existing))

    # Output mapping: workflow_key -> {id, name}
    output: dict[str, dict] = {}
    oauth_pending: list[str] = []

    for defn in definitions:
        name = defn["name"]
        cred_type = defn["type"]
        workflow_key = defn["workflow_key"]
        requires_oauth = defn.get("requires_oauth_flow", False)

        # Resolve data from env
        data = _resolve_data(defn["data_env_map"], name)

        # Check if credential already exists
        match = _find_existing(existing, name, cred_type)

        if match:
            cred_id = match["id"]
            logger.info("EXISTS: '%s' (type=%s, id=%s) — skipping creation",
                        name, cred_type, cred_id)
        elif dry_run:
            cred_id = "DRY_RUN_ID"
            logger.info("DRY RUN: would create '%s' (type=%s)", name, cred_type)
        else:
            logger.info("CREATING: '%s' (type=%s)", name, cred_type)
            result = client.create_credential(name, cred_type, data)
            cred_id = result.get("id", "UNKNOWN")
            logger.info("CREATED: '%s' -> id=%s", name, cred_id)

        output[workflow_key] = {"id": str(cred_id), "name": name}

        if requires_oauth and not match:
            oauth_pending.append(name)

    # Write output
    if dry_run:
        logger.info("DRY RUN — not writing credentials.json")
        logger.info("Would write: %s", json.dumps(output, indent=2))
    else:
        OUTPUT_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote %d credential IDs -> %s", len(output), OUTPUT_PATH)

    # Warn about OAuth
    if oauth_pending:
        logger.warning("")
        logger.warning("═══════════════════════════════════════════")
        logger.warning("  OAuth credentials require manual setup:")
        for name in oauth_pending:
            logger.warning("    → %s", name)
        logger.warning("")
        logger.warning("  Open n8n UI → Credentials → click each")
        logger.warning("  → 'Sign in with Google' to complete OAuth")
        logger.warning("═══════════════════════════════════════════")

    # Validate no CONFIGURE_ME
    bad = [k for k, v in output.items() if v["id"] == "CONFIGURE_ME"]
    if bad:
        logger.error("Credential IDs still placeholder: %s", bad)
        sys.exit(1)

    logger.info("Provisioning complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Provision n8n credentials")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be created without making changes")
    args = parser.parse_args()
    provision(dry_run=args.dry_run)
