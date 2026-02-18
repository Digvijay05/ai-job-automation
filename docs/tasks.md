# Project Tasks

## Phase 1: Foundation & Structure (Completed)

- [x] **Initialize Repository**: Create `ai-job-automation` with git. (Priority: P0)
- [x] **Structure Codebase**: Organize into `src/`, `docs/`, `tests/`. (Priority: P0)
- [x] **Standardize Docs**: Create README, LICENSE, CONTRIBUTING. (Priority: P1)
- [x] **Docker Config**: Update `docker-compose.yml` paths. (Priority: P0)
- [x] **Build Script**: Update `build_workflow.py` output path. (Priority: P1)

## Phase 2: Implementation Validation (Pending)

- [ ] **Verify Docker Build**: Run `docker-compose build` to ensure paths are correct. (Priority: P0, Effort: 1h)
- [ ] **Generate Workflow**: Run `python src/scripts/build_workflow.py` and verify JSON. (Priority: P0, Effort: 30m)
- [ ] **Unit Tests**: Create basic tests for `src/scripts`. (Priority: P2, Effort: 2h)

## Phase 3: Deployment & Operations

- [ ] **Push to GitHub**: Push to `main` branch. (Priority: P0)
- [ ] **CI/CD Pipeline**: Setup GitHub Actions for linting/testing. (Priority: P2, Effort: 4h)
- [ ] **Production Launch**: Deploy to persistent server. (Priority: P1)

## Phase 4: Inbound & Intelligent Scheduling (New)

- [ ] **Database Expansion**: Add `inbound_email_log` and `interview_log` tables. (Priority: P0)
- [ ] **Workflow: Inbound Trigger**: Configure Gmail/IMAP trigger with `thread_id` filtering. (Priority: P0)
- [ ] **Workflow: Classification**: Implement Ollama node with strict JSON schema for reply types. (Priority: P0)
- [ ] **Workflow: LLM Reuse**: Refactor Workflow to multiplex inputs into a shared "Humanize & Send" chain. (Priority: P1)
- [ ] **Workflow: Scheduling**: Implement Google Calendar node + event generation logic. (Priority: P1)
- [ ] **Testing**: Validate Inbound -> Classification -> Auto-Reply flow. (Priority: P0)
- [ ] **Testing**: Validate Interview Invite -> Calendar Event flow. (Priority: P0)
