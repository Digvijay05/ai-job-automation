# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-18

### Added
- Initial project structure with `src/` layout.
- Docker configuration (`Dockerfile.selenium`, `docker-compose.yml`) for n8n, Postgres, Selenium, Ngrok.
- Database migrations for multi-user schema (`src/db/migrations/01_init_schema.sql`).
- Python scripts for resume parsing and scraping (`src/scripts/`).
- Master n8n workflow builder (`src/scripts/build_workflow.py`).
- Standard repository documentation (README, LICENSE, etc.).
- Multi-user authentication and OAuth integration.
