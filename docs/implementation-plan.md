# Implementation Plan - AI Job Automation

## 1. System Architecture Design

The system is a microservices-inspired automation platform designed to streamline the job application process. It leverages a low-code orchestrator (n8n) backed by robust persistence (PostgreSQL) and specialized worker nodes (Python/Selenium).

### Core Components

*   **Orchestrator (n8n)**:
    *   Central interaction hub.
    *   Manages workflows for resume parsing, job analysis, and email dispatch.
    *   integrates with external APIs (Ollama, Gmail, Outlook).
    *   Runs in a Docker container with access to shared volumes.

*   **Database (PostgreSQL 16)**:
    *   Relational storage for:
        *   User profiles & authentication (`users`, `user_email_credentials`).
        *   Job market intelligence (`companies`, `jobs`).
        *   Application lifecycle (`applications`, `resume_versions`).
        *   Audit logs (`workflow_logs`, `email_dispatch_log`).
    *   Features `pgcrypto` for at-rest encryption of sensitive OAuth tokens.

*   **Worker Node (Python/Selenium)**:
    *   Headless browser service for job scraping.
    *   Resume PDF text extraction.
    *   Exposes functionality via CLI scripts invoked by n8n.

*   **AI Inference (Ollama)**:
    *   Local/Cloud LLM integration for text analysis, summarization, and humanization.
    *   Connected via standard HTTP requests from n8n.

*   **Ingress (Ngrok)**:
    *   Secure tunneling for webhook callbacks.
    *   Enforces `x-automation-secret` authentication.

## 2. Module Breakdown

### `src/workflows`
*   **Master Workflow**: A consolidated DAG handling:
    *   **Auth**: Header validation & DB lookup.
    *   **Resume**: Conversion & structured data extraction.
    *   **Job**: Scrape, normalize, fit score analysis.
    *   **Dispatch**: Rate-limited, idempotent email sending with OAuth refresh.

### `src/scripts`
*   `selenium_scraper.py`: Robust scraping logic with retry mechanisms.
*   `resume_text.py`: PDF-to-text conversion.
*   `build_workflow.py`: programmatic generator for the n8n JSON.

### `src/db`
*   SQL migrations for schema initialization and versioning.

## 3. Milestones

1.  **Repository Initialization** (Completed):
    *   Git init, directory structure, standard docs.
2.  **Containerization** (Completed):
    *   Docker Compose setup with volume mapping and networking.
3.  **Database Hardening** (Completed):
    *   Multi-user schema with encryption.
4.  **Workflow Finalization** (In Progress):
    *   Testing the generated workflow JSON.
5.  **Production Deployment**:
    *   CI/CD setup (future).
    *   Monitoring dashboard (future).

## 4. Risk Analysis

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| **OAuth Token Expiry** | High (Email failure) | Implemented auto-refresh logic in `dispatch` module. |
| **Scraper Blocking** | Medium | Implemented random delays and user-agent rotation. |
| **Database Data Loss** | High | Volume persistence; recommended regular backups (pg_dump). |
| **LLM Hallucinations** | Medium | Strict JSON schema validation after every LLM call. |

## 5. Testing Strategy

*   **Unit Testing**:
    *   Python scripts: `pytest` suite for parsers and scrapers.
*   **Integration Testing**:
    *   n8n Workflow: Manual execution of mock payloads via `curl`.
    *   Database: Schema validation scripts.
*   **End-to-End**:
    *   Full flow test: `Webhook -> Scrape -> Analyze -> Email Draft`.

## 6. Deployment Strategy

*   **Containerized**:
    *   `docker-compose up -d --build`.
*   **Configuration**:
    *   Environment variables in `.env` (not committed).
*   **Versioning**:
    *   Semantic versioning via git tags.
