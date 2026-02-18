# AI Job Application Automation

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-grade, multi-user automation system for job applications, powered by n8n, Python (Selenium), PostgreSQL, and Ollama. This system automates the entire pipeline from job scraping to resume tailoring, email drafting, and dispatch.

## 🏗 Architecture

The system follows a microservices-inspired architecture managed via Docker Compose:

-   **n8n**: Orchestrator for all workflows.
-   **PostgreSQL**: Persistent storage for users, jobs, applications, and logs.
-   **Selenium Worker**: Headless Python scraper service.
-   **Ollama**: Local LLM inference (external service integration).
-   **Ngrok**: Secure webhook tunneling.

### Directory Structure

```
ai-job-automation/
├── src/
│   ├── scripts/      # Python utilities (scraper, parser, builder)
│   ├── db/           # Database migrations
│   ├── workflows/    # Generated n8n workflow JSONs
│   └── docker/       # Dockerfile(s) (if moved, currently root)
├── docs/             # Implementation plans and documentation
├── tests/            # Test suite
├── .github/          # GitHub Workflows
├── docker-compose.yml
└── .env.example
```

## 🚀 Setup

### Prerequisites

-   Docker & Docker Compose
-   Git
-   Ollama (running locally or remotely)
-   Ngrok account

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/[YOUR_USERNAME]/ai-job-automation.git
    cd ai-job-automation
    ```

2.  **Configure Environment:**
    Copy `.env.example` to `.env` and fill in your secrets.
    ```bash
    cp .env.example .env
    ```
    *Required: `WEBHOOK_SECRET`, `DB_ENCRYPTION_KEY`, `OLLAMA_API_URL`, OAuth credentials.*

3.  **Generate Workflow:**
    Build the master workflow JSON.
    ```bash
    python src/scripts/build_workflow.py
    ```

4.  **Start Services:**
    ```bash
    docker-compose up -d --build
    ```

5.  **Initialize n8n:**
    -   Access n8n at `http://localhost:5678`.
    -   Import `src/workflows/workflow_main.json`.
    -   Configure Credentials (Postgres, Ollama).

## 📖 Usage

### Webhook API

The system exposes a secured webhook endpoint.

**Headers:**
-   `x-automation-secret`: Your configured webhook secret.
-   `x-user-id`: Target user UUID.
-   `x-user-api-key`: User API key (hash validated).

**Actions:**
-   `resume_upload`: Upload and parse resume PDF.
-   `analyze_job`: Internal job scraping and analysis.
-   `dispatch_email`: Trigger email sending flow.

### Monitoring

-   Check `docker logs n8n-automation` or Postgres `workflow_logs` table for execution details.

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and development process.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
