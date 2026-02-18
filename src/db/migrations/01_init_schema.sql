-- ============================================================
-- Job Automation System — Multi-User Production Schema
-- Run order: Applied automatically via Postgres initdb.d mount
-- ============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ──────────────────────────────────────────────────
-- 1. Users (Multi-User Candidate Profiles)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name          VARCHAR(255) NOT NULL,
    email              VARCHAR(255) UNIQUE NOT NULL,
    phone              VARCHAR(50),
    linkedin_url       VARCHAR(500),
    github_url         VARCHAR(500),
    portfolio_url      VARCHAR(500),
    skills             JSONB NOT NULL DEFAULT '[]'::jsonb,
    experience         JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects           JSONB NOT NULL DEFAULT '[]'::jsonb,
    education          JSONB NOT NULL DEFAULT '[]'::jsonb,
    certifications     JSONB NOT NULL DEFAULT '[]'::jsonb,
    preferred_roles    JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_resume_text    TEXT NOT NULL DEFAULT '',

    -- Multi-User Auth & Preferences
    api_key_hash       VARCHAR(128),
    email_mode         VARCHAR(10)  NOT NULL DEFAULT 'DRAFT'
                         CHECK (email_mode IN ('AUTO', 'DRAFT')),
    hourly_email_limit INT          NOT NULL DEFAULT 10
                         CHECK (hourly_email_limit >= 0 AND hourly_email_limit <= 100),
    daily_email_limit  INT          NOT NULL DEFAULT 50
                         CHECK (daily_email_limit >= 0 AND daily_email_limit <= 500),

    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key_hash);

-- ──────────────────────────────────────────────────
-- 2. User Email Credentials (Per-User OAuth Storage)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_email_credentials (
    credential_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    provider           VARCHAR(20) NOT NULL
                         CHECK (provider IN ('GMAIL', 'OUTLOOK', 'SMTP')),
    sender_email       VARCHAR(255) NOT NULL,

    -- OAuth2 tokens (encrypted at rest via pgcrypto)
    refresh_token_enc  BYTEA,
    access_token_enc   BYTEA,
    token_expires_at   TIMESTAMP WITH TIME ZONE,

    -- SMTP fallback (encrypted)
    smtp_host_enc      BYTEA,
    smtp_port          INT,
    smtp_password_enc  BYTEA,

    -- Client credentials (encrypted; can also be global env)
    client_id_enc      BYTEA,
    client_secret_enc  BYTEA,

    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    last_refreshed_at  TIMESTAMP WITH TIME ZONE,
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, provider, sender_email)
);

CREATE INDEX IF NOT EXISTS idx_user_creds_user ON user_email_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_creds_active ON user_email_credentials(user_id, is_active)
  WHERE is_active = TRUE;

-- ──────────────────────────────────────────────────
-- 3. Companies (Scraped Intelligence — Shared Global)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    company_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name     VARCHAR(255) UNIQUE NOT NULL,
    website_url      VARCHAR(500),
    base_url         VARCHAR(500),
    scrape_urls      JSONB DEFAULT '[]'::jsonb,
    career_page_url  VARCHAR(500),
    industry         VARCHAR(100),
    location         VARCHAR(255),
    mission_statement TEXT,
    vision_statement  TEXT,
    values_culture    TEXT,
    tech_stack        JSONB DEFAULT '[]'::jsonb,
    hiring_patterns   TEXT,
    keywords          JSONB DEFAULT '[]'::jsonb,
    hr_contact_name   VARCHAR(255),
    hr_email          VARCHAR(255),
    hr_linkedin       VARCHAR(500),
    raw_scraped_text  TEXT,
    last_scraped_at   TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name);
CREATE INDEX IF NOT EXISTS idx_companies_website ON companies(website_url);

-- ──────────────────────────────────────────────────
-- 4. Jobs (Individual Listings + Analysis)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    job_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        UUID NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    title             VARCHAR(255) NOT NULL,
    job_url           VARCHAR(500) UNIQUE NOT NULL,
    description_raw   TEXT,
    description_summary TEXT,
    required_skills   JSONB DEFAULT '[]'::jsonb,
    experience_level  VARCHAR(50),
    location          VARCHAR(255),
    employment_type   VARCHAR(50),
    salary_range      VARCHAR(100),
    posted_date       DATE,
    scraped_date      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- LLM Analysis Results
    fit_score         DECIMAL(5,2) CHECK (fit_score >= 0 AND fit_score <= 100),
    gap_analysis      TEXT,
    alignment_report  TEXT,
    strategic_angle   TEXT,

    status            VARCHAR(50) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','ANALYZED','LOW_FIT','APPLIED','REJECTED','INTERVIEW','OFFER')),
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(job_url);

-- ──────────────────────────────────────────────────
-- 5. Applications (Tailored Assets per Job)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS applications (
    application_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    job_id                 UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,

    -- Tailored Resume
    tailored_resume_text   TEXT,
    tailored_resume_pdf    VARCHAR(500),
    resume_version         INT NOT NULL DEFAULT 1,

    -- Cold Email
    email_subject          VARCHAR(500),
    email_body_short       TEXT,
    email_body_long        TEXT,

    -- AI QA Metadata
    ai_detection_score     DECIMAL(5,2) CHECK (ai_detection_score >= 0 AND ai_detection_score <= 100),
    humanization_pass      BOOLEAN NOT NULL DEFAULT FALSE,
    generation_model       VARCHAR(100),

    status                 VARCHAR(50) NOT NULL DEFAULT 'DRAFT'
                             CHECK (status IN ('DRAFT','READY','PENDING_REVIEW','SENT','REPLIED')),
    sent_at                TIMESTAMP WITH TIME ZONE,
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, job_id, resume_version)
);

CREATE INDEX IF NOT EXISTS idx_applications_user ON applications(user_id);
CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

-- ──────────────────────────────────────────────────
-- 6. Email Dispatch Log (Send Tracking + Idempotency)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_dispatch_log (
    log_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_uuid      UUID NOT NULL,
    user_id             UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    job_id              UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    application_id      UUID     REFERENCES applications(application_id) ON DELETE SET NULL,
    company_id          UUID     REFERENCES companies(company_id) ON DELETE SET NULL,
    recipient_email     VARCHAR(255) NOT NULL,
    subject             VARCHAR(500) NOT NULL,
    email_body_hash     VARCHAR(128) NOT NULL,
    provider_message_id VARCHAR(255),
    sent_status         VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                          CHECK (sent_status IN ('PENDING','SENT','FAILED','SKIPPED','BOUNCED')),
    retry_count         INT NOT NULL DEFAULT 0
                          CHECK (retry_count >= 0 AND retry_count <= 3),
    error_message       TEXT,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Idempotency: one successful send per user+job+hash combo
    UNIQUE(user_id, job_id, email_body_hash)
);

CREATE INDEX IF NOT EXISTS idx_email_log_user ON email_dispatch_log(user_id);
CREATE INDEX IF NOT EXISTS idx_email_log_status ON email_dispatch_log(sent_status);
CREATE INDEX IF NOT EXISTS idx_email_log_created ON email_dispatch_log(created_at);
-- Rate limit query helper: count recent sends per user
CREATE INDEX IF NOT EXISTS idx_email_log_user_time ON email_dispatch_log(user_id, created_at)
  WHERE sent_status = 'SENT';

-- ──────────────────────────────────────────────────
-- 7. Resume Versions (Version History)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS resume_versions (
    version_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    content_text   TEXT NOT NULL,
    pdf_path       VARCHAR(500),
    source         VARCHAR(50) NOT NULL DEFAULT 'ORIGINAL'
                     CHECK (source IN ('ORIGINAL','TAILORED')),
    job_id         UUID REFERENCES jobs(job_id) ON DELETE SET NULL,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_resume_versions_user ON resume_versions(user_id);

-- ──────────────────────────────────────────────────
-- 8. Workflow Execution Logs (Production Audit Trail)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_logs (
    log_id         SERIAL PRIMARY KEY,
    request_id     UUID NOT NULL DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(user_id) ON DELETE SET NULL,
    workflow_name  VARCHAR(100) NOT NULL DEFAULT 'master_workflow',
    module_name    VARCHAR(100) NOT NULL,
    execution_id   VARCHAR(100),
    status         VARCHAR(50) NOT NULL
                     CHECK (status IN ('STARTED','SUCCESS','FAILED','RETRYING','VALIDATION_ERROR','RATE_LIMITED','SKIPPED')),
    error_message  TEXT,
    input_summary  JSONB,
    output_summary JSONB,
    llm_model_used VARCHAR(100),
    token_usage    JSONB,
    duration_ms    INT,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_request_id ON workflow_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_logs_user ON workflow_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_module ON workflow_logs(module_name);
CREATE INDEX IF NOT EXISTS idx_logs_status ON workflow_logs(status);
CREATE INDEX IF NOT EXISTS idx_logs_created ON workflow_logs(created_at);

-- ──────────────────────────────────────────────────
-- 9. Inbound Email Log (Reply Classification & Tracking)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS inbound_email_log (
    inbound_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_uuid     UUID NOT NULL,
    user_id            UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    thread_id          VARCHAR(255) NOT NULL,
    message_id         VARCHAR(255) NOT NULL,
    sender_email       VARCHAR(255) NOT NULL,
    subject            VARCHAR(500),
    raw_email          TEXT,

    -- LLM Classification Result
    reply_type         VARCHAR(30) NOT NULL
                         CHECK (reply_type IN (
                           'INTERVIEW_INVITE','FOLLOW_UP_REQUIRED','REJECTION',
                           'INFORMATION_REQUEST','OTHER'
                         )),
    classification_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Linkage to original dispatch
    dispatch_log_id    UUID REFERENCES email_dispatch_log(log_id) ON DELETE SET NULL,
    job_id             UUID REFERENCES jobs(job_id) ON DELETE SET NULL,
    company_id         UUID REFERENCES companies(company_id) ON DELETE SET NULL,

    -- Response tracking
    auto_reply_sent    BOOLEAN NOT NULL DEFAULT FALSE,
    auto_reply_body    TEXT,
    processed_at       TIMESTAMP WITH TIME ZONE,
    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Idempotency: one classification per message
    UNIQUE(user_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_inbound_user ON inbound_email_log(user_id);
CREATE INDEX IF NOT EXISTS idx_inbound_thread ON inbound_email_log(thread_id);
CREATE INDEX IF NOT EXISTS idx_inbound_reply_type ON inbound_email_log(reply_type);
CREATE INDEX IF NOT EXISTS idx_inbound_created ON inbound_email_log(created_at);

-- ──────────────────────────────────────────────────
-- 10. Interview Log (Calendar Events & Scheduling)
-- ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS interview_log (
    interview_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    job_id             UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    company_id         UUID REFERENCES companies(company_id) ON DELETE SET NULL,
    inbound_id         UUID REFERENCES inbound_email_log(inbound_id) ON DELETE SET NULL,

    -- Calendar Event Details
    calendar_event_id  VARCHAR(255),
    interview_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    end_datetime       TIMESTAMP WITH TIME ZONE,
    timezone           VARCHAR(50) NOT NULL DEFAULT 'UTC',
    interview_mode     VARCHAR(20) NOT NULL DEFAULT 'VIRTUAL'
                         CHECK (interview_mode IN ('VIRTUAL','IN_PERSON','PHONE')),
    meeting_link       VARCHAR(500),
    location           VARCHAR(500),

    -- Interviewer Info
    interviewer_name   VARCHAR(255),
    interviewer_email  VARCHAR(255),

    -- Status
    status             VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED'
                         CHECK (status IN ('SCHEDULED','CONFIRMED','CANCELLED','COMPLETED','NO_SHOW')),
    confirmation_sent  BOOLEAN NOT NULL DEFAULT FALSE,
    notes              TEXT,

    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Idempotency: prevent duplicate events for same user+job+time
    UNIQUE(user_id, job_id, interview_datetime)
);

CREATE INDEX IF NOT EXISTS idx_interview_user ON interview_log(user_id);
CREATE INDEX IF NOT EXISTS idx_interview_job ON interview_log(job_id);
CREATE INDEX IF NOT EXISTS idx_interview_status ON interview_log(status);
CREATE INDEX IF NOT EXISTS idx_interview_datetime ON interview_log(interview_datetime);
