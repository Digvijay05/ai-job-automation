# Implementation Plan - AI Job Automation

## 1. System Architecture Design

The system is a microservices-inspired automation platform designed to streamline the job application process. It leverages a low-code orchestrator (n8n) backed by robust persistence (PostgreSQL) and specialized worker nodes (Python/Selenium).

### Core Components

*   **Orchestrator (n8n)**:
    *   Central interaction hub.
    *   Manages workflows for resume parsing, job analysis, email dispatch, **and inbound email handling**.
    *   integrates with external APIs (Ollama, Gmail, Outlook, **Google Calendar**).
    *   Runs in a Docker container with access to shared volumes.

*   **Database (PostgreSQL 16)**:
    *   Relational storage for:
        *   User profiles & authentication (`users`, `user_email_credentials`).
        *   Job market intelligence (`companies`, `jobs`).
        *   Application lifecycle (`applications`, `resume_versions`).
        *   Audit logs (`workflow_logs`, `email_dispatch_log`, `inbound_email_log`, `interview_log`).
    *   Features `pgcrypto` for at-rest encryption of sensitive OAuth tokens.

*   **Worker Node (Python/Selenium)**:
    *   Headless browser service for job scraping.
    *   Resume PDF text extraction.
    *   Exposes functionality via CLI scripts invoked by n8n.

*   **AI Inference (Ollama)**:
    *   Local/Cloud LLM integration for text analysis, summarization, and humanization.
    *   Connected via standard HTTP requests from n8n.
    *   **Enforces strict LLM Reuse Strategy via multiplexed nodes.**

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
    *   **[NEW] Inbound**: Reply detection, classification, and auto-response.
    *   **[NEW] Scheduling**: Interview extraction and Google Calendar integration.

### `src/scripts`
*   `selenium_scraper.py`: Robust scraping logic with retry mechanisms.
*   `resume_text.py`: PDF-to-text conversion.
*   `build_workflow.py`: programmatic generator for the n8n JSON.

### `src/db`
*   SQL migrations for schema initialization and versioning.

## 3. Databases Extensions (New)

| Table | Purpose | Key Fields |
| :--- | :--- | :--- |
| **`inbound_email_log`** | Track incoming replies | `reply_type`, `classification_json`, `thread_id` |
| **`interview_log`** | Track scheduled events | `interview_datetime`, `calendar_event_id`, `meeting_link` |

## 4. New Logic Modules

### A. Inbound Email Handling
*   **Trigger**: Gmail/IMAP Trigger (filtered by subject/thread).
*   **Classification**: Ollama classifies reply into `INTERVIEW_INVITE`, `REJECTION`, `FOLLOW_UP_REQUIRED`, etc.
*   **Action**: 
    *   *Interview* -> Scheduling Module.
    *   *Follow-up* -> Generate Reply -> **Reuse Humanizer** -> Send.
    *   *Rejection* -> Log & Archive.

### B. LLM Reuse Strategy (Multiplexed)
*   **Concept**: Do not duplicate "Humanizer" or "Persona" nodes.
*   **Implementation**: 
    *   Centralized "Humanize & Send" chain.
    *   Multiple inputs (Cold Email Draft, Auto-Reply Draft, Interview Confirmation).
    *   Context injected via workflow data (e.g., `{{ $json.email_context }}`).
    *   Ensures consistent tone and reduces maintenance.

### C. Interview Scheduling
*   **Extraction**: Ollama extracts Date, Time, Link, Interviewer from email body.
*   **Calendar**: Google Calendar Node creates private event with detailed dossier.
*   **Confirmation**: Auto-send confirmation email (via reused Dispatch chain).

## 5. Risk Analysis

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| **OAuth Token Expiry** | High (Email failure) | Implemented auto-refresh logic in `dispatch` module. |
| **Scraper Blocking** | Medium | Implemented random delays and user-agent rotation. |
| **Database Data Loss** | High | Volume persistence; recommended regular backups (pg_dump). |
| **LLM Hallucinations** | Medium | Strict JSON schema validation after every LLM call. |
| **Calendar Conflicts** | Medium | Idempotency checks on `thread_id` + `interview_datetime`. |
| **Spam Loops** | High | Filter auto-replies; Rate limit inbound processing. |

## 6. Testing Strategy

*   **Unit Testing**:
    *   Python scripts: `pytest` suite for parsers and scrapers.
*   **Integration Testing**:
    *   n8n Workflow: Manual execution of mock payloads via `curl`.
    *   Database: Schema validation scripts.
*   **End-to-End**:
    *   Full flow test: `Webhook -> Scrape -> Analyze -> Email Draft`.
    *   Inbound test: `Mock Reply -> Classification -> Auto-Response`.

## 7. Deployment Strategy

*   **Containerized**:
    *   `docker-compose up -d --build`.
*   **Configuration**:
    *   Environment variables in `.env` (not committed).
*   **Versioning**:
    *   Semantic versioning via git tags.
