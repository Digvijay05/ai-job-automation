"""
Workflow Builder - Generates workflow_main.json programmatically.

Produces a single production n8n workflow with:
  - Multi-user webhook auth (x-automation-secret + x-user-api-key)
  - Resume ingestion module
  - Job analysis module (scrape → normalize → fit → tailor → humanize → email draft)
  - Email dispatch module (OAuth refresh → rate limit → idempotency → send)
  - Audit logging on every module boundary

Usage:
    python scripts/build_workflow.py > n8n_workflows/workflow_main.json
"""
from __future__ import annotations

import json
import sys
from typing import Any

# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────
_x = 0  # auto-increment x position tracker

def _pos(x: int, y: int) -> list[int]:
    return [x, y]

def node(nid: str, name: str, ntype: str, params: dict, pos: list[int],
         version: int = 1, creds: dict | None = None) -> dict:
    n: dict[str, Any] = {
        "parameters": params,
        "id": nid,
        "name": name,
        "type": f"n8n-nodes-base.{ntype}",
        "typeVersion": version,
        "position": pos,
    }
    if creds:
        n["credentials"] = creds
    return n

PG = {"postgres": {"id": "CONFIGURE_ME", "name": "Postgres"}}
OLLAMA = {"httpHeaderAuth": {"id": "CONFIGURE_ME", "name": "Ollama API Key"}}

def ollama_call(nid: str, name: str, system_prompt: str, user_expr: str,
                pos: list[int], temp: float = 0.1) -> dict:
    body = (
        '={"model":"{{ $env.OLLAMA_MODEL }}",'
        '"max_tokens":{{ $env.OLLAMA_MAX_TOKENS || 4096 }},'
        f'"temperature":{temp},'
        '"messages":[{"role":"system","content":' + json.dumps(system_prompt) + '},'
        '{"role":"user","content":' + user_expr + '}]}'
    )
    return node(nid, name, "httpRequest", {
        "method": "POST",
        "url": "={{ $env.OLLAMA_API_URL }}/chat/completions",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True, "specifyBody": "json", "jsonBody": body,
        "options": {"timeout": "={{ Number($env.OLLAMA_TIMEOUT_MS) || 120000 }}"},
    }, pos, version=4, creds=OLLAMA)

def validate_node(nid: str, name: str, js: str, pos: list[int]) -> dict:
    return node(nid, name, "code", {"jsCode": js}, pos, version=2)

def pg_query(nid: str, name: str, query: str, pos: list[int]) -> dict:
    return node(nid, name, "postgres", {
        "operation": "executeQuery", "query": query,
    }, pos, version=2, creds=PG)

def set_node(nid: str, name: str, values: dict, pos: list[int]) -> dict:
    v: dict[str, list] = {"string": [], "number": []}
    for k, val in values.items():
        if isinstance(val, (int, float)):
            v["number"].append({"name": k, "value": val})
        else:
            v["string"].append({"name": k, "value": str(val)})
    return node(nid, name, "set", {"values": v, "options": {}}, pos, version=3)

def conn(src: str, *targets: str | tuple[str, ...]) -> dict:
    """Build connection entry. Each target is a string or tuple of strings (for branches)."""
    branches: list[list[dict]] = []
    for t in targets:
        if isinstance(t, tuple):
            branches.append([{"node": n, "type": "main", "index": 0} for n in t])
        else:
            branches.append([{"node": t, "type": "main", "index": 0}])
    return {src: {"main": branches}}

# ──────────────────────────────────────────────────
# NODE DEFINITIONS
# ──────────────────────────────────────────────────
nodes: list[dict] = []
connections: dict = {}

# ═══════════════════════════════════════════════════
# SECTION 0: WEBHOOK + GLOBAL AUTH
# ═══════════════════════════════════════════════════

nodes.append(node("w001", "Webhook", "webhook", {
    "httpMethod": "POST", "path": "process",
    "responseMode": "lastNode", "options": {"rawBody": True},
}, _pos(200, 600), version=2))

# Auth: check x-automation-secret
nodes.append(node("w002", "IF - Auth Secret", "if", {
    "conditions": {"string": [{
        "value1": '={{ $json.headers["x-automation-secret"] }}',
        "operation": "equals",
        "value2": "={{ $env.WEBHOOK_SECRET }}",
    }]}
}, _pos(440, 600)))

nodes.append(set_node("w003", "Set - 401", {"statusCode": 401, "status": "error",
    "message": "Unauthorized: invalid x-automation-secret"}, _pos(700, 900)))

# Multi-user: validate user via DB
nodes.append(pg_query("w004", "Postgres - Validate User",
    '=SELECT user_id, full_name, email, email_mode, hourly_email_limit, daily_email_limit, api_key_hash '
    'FROM users WHERE user_id = \'{{ $json.headers["x-user-id"] }}\'::uuid LIMIT 1;',
    _pos(700, 600)))

nodes.append(validate_node("w005", "Validate - User Auth",
    'const user = $input.first().json;\n'
    'if (!user || !user.user_id) throw new Error("User not found: " + $("Webhook").first().json.headers["x-user-id"]);\n'
    'const apiKey = $("Webhook").first().json.headers["x-user-api-key"] || "";\n'
    'if (!user.api_key_hash) { /* first-time user, skip key check */ }\n'
    'else if (apiKey !== user.api_key_hash) throw new Error("Invalid API key for user " + user.user_id);\n'
    'return [{ json: { ...user, _request_body: $("Webhook").first().json.body } }];',
    _pos(960, 600)))

# Router
nodes.append(node("w010", "Switch - Router", "switch", {
    "rules": {"values": [
        {"conditions": {"conditions": [{"leftValue": "={{ $json._request_body.action }}", "rightValue": "resume_upload", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 0},
        {"conditions": {"conditions": [{"leftValue": "={{ $json._request_body.action }}", "rightValue": "analyze_job", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 1},
        {"conditions": {"conditions": [{"leftValue": "={{ $json._request_body.action }}", "rightValue": "dispatch_email", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 2},
    ]},
    "fallbackOutput": "extra",
}, _pos(1200, 600), version=3))

nodes.append(set_node("w011", "Set - 400 Bad Action", {"statusCode": 400, "status": "error",
    "message": "Unknown action. Use resume_upload, analyze_job, or dispatch_email."}, _pos(1460, 1100)))

# ═══════════════════════════════════════════════════
# SECTION 1: RESUME INGESTION
# ═══════════════════════════════════════════════════
Y_R = 200

nodes.append(pg_query("r000", "Log - Resume Start",
    "=INSERT INTO workflow_logs (request_id, user_id, module_name, execution_id, status, input_summary) "
    "VALUES (gen_random_uuid(), '{{ $json.user_id }}'::uuid, 'resume_ingestion', '={{ $execution.id }}', "
    "'STARTED', '{\"file_path\": \"{{ $json._request_body.data.file_path }}\"}'::jsonb);",
    _pos(1460, Y_R)))

nodes.append(node("r100", "Exec - Extract Resume", "executeCommand", {
    "command": '=python3 /app/scripts/resume_text.py --file "{{ $("Validate - User Auth").first().json._request_body.data.file_path }}"',
}, _pos(1700, Y_R)))

nodes.append(validate_node("r101", "Validate - Resume Text",
    'const raw = $input.first().json.stdout;\n'
    'const parsed = JSON.parse(raw);\n'
    'if (parsed.error) throw new Error("Resume extraction failed: " + parsed.error);\n'
    'if (!parsed.raw_text || parsed.char_count < 100) throw new Error("Resume text too short: " + parsed.char_count);\n'
    'return [{ json: parsed }];',
    _pos(1940, Y_R)))

RESUME_SCHEMA_PROMPT = (
    "You are a resume data extractor. Extract STRICT JSON matching this schema exactly:\\n"
    '{"full_name":string(REQUIRED),"email":string(REQUIRED),"phone":string|null,'
    '"skills":[string](REQUIRED,non-empty),"experience":[{"title":string,"company":string,"description":string}],'
    '"projects":[{"name":string,"description":string,"technologies":[string]}],'
    '"education":[{"degree":string,"institution":string,"year":string}],'
    '"certifications":[string],"preferred_roles":[string]}\\n'
    "Return ONLY valid JSON. No markdown fences."
)
nodes.append(ollama_call("r102", "Ollama - Structure Resume", RESUME_SCHEMA_PROMPT,
    '{{ JSON.stringify($json.raw_text) }}', _pos(2180, Y_R)))

nodes.append(validate_node("r103", "Validate - Resume Schema",
    'const resp = $input.first().json;\n'
    'const content = resp.choices[0].message.content;\n'
    'let parsed; try { parsed = JSON.parse(content); } catch(e) { throw new Error("LLM invalid JSON: " + content.substring(0,500)); }\n'
    'if (!parsed.full_name) throw new Error("Missing full_name");\n'
    'if (!parsed.email || !parsed.email.includes("@")) throw new Error("Missing/invalid email");\n'
    'if (!Array.isArray(parsed.skills) || parsed.skills.length === 0) throw new Error("skills must be non-empty array");\n'
    'parsed.raw_resume_text = $("Validate - Resume Text").first().json.raw_text;\n'
    'parsed._llm_model = resp.model || "";\n'
    'parsed._llm_tokens = resp.usage || null;\n'
    'parsed._user_id = $("Validate - User Auth").first().json.user_id;\n'
    'return [{ json: parsed }];',
    _pos(2420, Y_R)))

nodes.append(pg_query("r104", "Postgres - Upsert User Resume",
    "=UPDATE users SET full_name='{{ $json.full_name }}', phone='{{ $json.phone }}', "
    "skills='{{ JSON.stringify($json.skills) }}'::jsonb, experience='{{ JSON.stringify($json.experience) }}'::jsonb, "
    "projects='{{ JSON.stringify($json.projects) }}'::jsonb, education='{{ JSON.stringify($json.education) }}'::jsonb, "
    "certifications='{{ JSON.stringify($json.certifications) }}'::jsonb, preferred_roles='{{ JSON.stringify($json.preferred_roles) }}'::jsonb, "
    "raw_resume_text='{{ $json.raw_resume_text }}', updated_at=NOW() "
    "WHERE user_id='{{ $json._user_id }}'::uuid RETURNING user_id;",
    _pos(2660, Y_R)))

nodes.append(pg_query("r105", "Log - Resume Success",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, llm_model_used, token_usage) "
    "VALUES ('{{ $json.user_id }}'::uuid, 'resume_ingestion', '={{ $execution.id }}', 'SUCCESS', "
    "'={{ $(\"Validate - Resume Schema\").first().json._llm_model }}', "
    "'={{ JSON.stringify($(\"Validate - Resume Schema\").first().json._llm_tokens) }}'::jsonb);",
    _pos(2900, Y_R)))

nodes.append(set_node("r106", "Set - Resume OK",
    {"status": "success", "module": "resume_ingestion",
     "user_id": "={{ $json.user_id }}"}, _pos(3140, Y_R)))

# ═══════════════════════════════════════════════════
# SECTION 2: JOB ANALYSIS PIPELINE
# ═══════════════════════════════════════════════════
Y_J = 600

nodes.append(pg_query("j000", "Log - Job Start",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, input_summary) "
    "VALUES ('{{ $json.user_id }}'::uuid, 'job_pipeline', '={{ $execution.id }}', 'STARTED', "
    "'{\"job_url\": \"{{ $json._request_body.data.job_url }}\"}'::jsonb);",
    _pos(1460, Y_J)))

nodes.append(node("j100", "Exec - Scrape Job", "executeCommand", {
    "command": '=python3 /app/scripts/selenium_scraper.py --url "{{ $("Validate - User Auth").first().json._request_body.data.job_url }}" --type job',
}, _pos(1700, Y_J)))

nodes.append(validate_node("j101", "Validate - Scrape",
    'const raw = $input.first().json.stdout;\n'
    'const parsed = JSON.parse(raw);\n'
    'if (parsed.error) throw new Error("Scraper error: " + parsed.error);\n'
    'if (!parsed.raw_text || parsed.raw_text.length < 50) throw new Error("Scraped text too short");\n'
    'return [{ json: parsed }];',
    _pos(1940, Y_J)))

JOB_SCHEMA_PROMPT = (
    "You are a job posting normalizer. Extract STRICT JSON:\\n"
    '{"company_name":string(REQUIRED),"industry":string|null,"location":string|null,'
    '"job_title":string(REQUIRED),"required_skills":[string](REQUIRED),'
    '"experience_level":string|null,"employment_type":string|null,'
    '"description_summary":string(2-3 sentences,REQUIRED),"tech_stack":[string],'
    '"hr_contact_name":string|null,"hr_email":string|null}\\n'
    "Return ONLY valid JSON."
)
nodes.append(ollama_call("j102", "Ollama - Normalize Job", JOB_SCHEMA_PROMPT,
    '{{ JSON.stringify($json.raw_text) }}', _pos(2180, Y_J)))

nodes.append(validate_node("j103", "Validate - Job Schema",
    'const resp = $input.first().json;\n'
    'const content = resp.choices[0].message.content;\n'
    'let parsed; try { parsed = JSON.parse(content); } catch(e) { throw new Error("LLM normalize invalid JSON: " + content.substring(0,500)); }\n'
    'if (!parsed.company_name) throw new Error("Missing company_name");\n'
    'if (!parsed.job_title) throw new Error("Missing job_title");\n'
    'if (!Array.isArray(parsed.required_skills)) parsed.required_skills = [];\n'
    'parsed.job_url = $("Validate - Scrape").first().json.job_url;\n'
    'parsed.raw_text = $("Validate - Scrape").first().json.raw_text;\n'
    'parsed._llm_model = resp.model || "";\n'
    'return [{ json: parsed }];',
    _pos(2420, Y_J)))

nodes.append(pg_query("j104", "Postgres - Upsert Company",
    "=INSERT INTO companies (company_name, industry, location, hr_contact_name, hr_email, tech_stack, last_scraped_at) "
    "VALUES ('{{ $json.company_name }}','{{ $json.industry }}','{{ $json.location }}',"
    "'{{ $json.hr_contact_name }}','{{ $json.hr_email }}','{{ JSON.stringify($json.tech_stack) }}'::jsonb, NOW()) "
    "ON CONFLICT (company_name) DO UPDATE SET industry=EXCLUDED.industry, hr_contact_name=EXCLUDED.hr_contact_name, "
    "hr_email=EXCLUDED.hr_email, tech_stack=EXCLUDED.tech_stack, last_scraped_at=NOW() RETURNING company_id;",
    _pos(2660, Y_J)))

nodes.append(pg_query("j105", "Postgres - Upsert Job",
    "=INSERT INTO jobs (company_id, title, job_url, description_raw, description_summary, required_skills, "
    "experience_level, employment_type, location) VALUES ('{{ $json.company_id }}'::uuid, "
    "'{{ $(\"Validate - Job Schema\").first().json.job_title }}', '{{ $(\"Validate - Job Schema\").first().json.job_url }}', "
    "'{{ $(\"Validate - Job Schema\").first().json.raw_text }}', '{{ $(\"Validate - Job Schema\").first().json.description_summary }}', "
    "'{{ JSON.stringify($(\"Validate - Job Schema\").first().json.required_skills) }}'::jsonb, "
    "'{{ $(\"Validate - Job Schema\").first().json.experience_level }}', "
    "'{{ $(\"Validate - Job Schema\").first().json.employment_type }}', "
    "'{{ $(\"Validate - Job Schema\").first().json.location }}') "
    "ON CONFLICT (job_url) DO UPDATE SET description_raw=EXCLUDED.description_raw, "
    "description_summary=EXCLUDED.description_summary, required_skills=EXCLUDED.required_skills, updated_at=NOW() "
    "RETURNING job_id;",
    _pos(2900, Y_J)))

# Merge user + job context
nodes.append(validate_node("j107", "Merge - Context",
    'const user = $("Validate - User Auth").first().json;\n'
    'const job = $("Validate - Job Schema").first().json;\n'
    'const job_id = $("Postgres - Upsert Job").first().json.job_id;\n'
    'const company_id = $("Postgres - Upsert Company").first().json.company_id;\n'
    'return [{ json: { user, job, job_id, company_id } }];',
    _pos(3140, Y_J)))

FIT_PROMPT = (
    "You are a career strategist. Analyze candidate-job fit. Return STRICT JSON:\\n"
    '{"fit_score":integer 0-100(REQUIRED),"gap_analysis":string(REQUIRED),'
    '"alignment_report":string(REQUIRED),"strategic_angle":string(2-3 sentences,REQUIRED),'
    '"recommended_keywords":[string]}\\nReturn ONLY valid JSON.'
)
nodes.append(ollama_call("j108", "Ollama - Analyze Fit", FIT_PROMPT,
    '{{ JSON.stringify("CANDIDATE:\\n" + JSON.stringify($json.user) + "\\n\\nJOB:\\n" + JSON.stringify($json.job)) }}',
    _pos(3380, Y_J), temp=0.2))

nodes.append(validate_node("j109", "Validate - Fit",
    'const resp = $input.first().json;\n'
    'const content = resp.choices[0].message.content;\n'
    'let p; try { p = JSON.parse(content); } catch(e) { throw new Error("LLM fit invalid JSON"); }\n'
    'if (typeof p.fit_score !== "number" || p.fit_score < 0 || p.fit_score > 100) throw new Error("fit_score must be 0-100");\n'
    'p.fit_score = Math.round(p.fit_score);\n'
    'if (!p.gap_analysis) throw new Error("Missing gap_analysis");\n'
    'const ctx = $("Merge - Context").first().json;\n'
    'p.job_id = ctx.job_id; p.company_id = ctx.company_id; p.user = ctx.user; p.job = ctx.job;\n'
    'p._llm_model = resp.model || ""; p._llm_tokens = resp.usage || null;\n'
    'return [{ json: p }];',
    _pos(3620, Y_J)))

nodes.append(pg_query("j110", "Postgres - Save Fit",
    "=UPDATE jobs SET fit_score={{ $json.fit_score }}, gap_analysis='{{ $json.gap_analysis }}', "
    "alignment_report='{{ $json.alignment_report }}', strategic_angle='{{ $json.strategic_angle }}', "
    "status=CASE WHEN {{ $json.fit_score }} >= 75 THEN 'ANALYZED' ELSE 'LOW_FIT' END, updated_at=NOW() "
    "WHERE job_id='{{ $json.job_id }}'::uuid;",
    _pos(3860, Y_J)))

# IF High Fit
nodes.append(node("j111", "IF - High Fit", "if", {
    "conditions": {"number": [{
        "value1": '={{ $("Validate - Fit").first().json.fit_score }}',
        "operation": "largerEqual", "value2": 75,
    }]}
}, _pos(4100, Y_J)))

# ── High Fit Branch: Tailor → Humanize Resume → Upsert App → Email Draft → Humanize Email ──
Y_H = 420

TAILOR_PROMPT = (
    "You are an ATS resume optimizer. Rewrite the resume for the target job. "
    "Rules: 1) Rewrite summary. 2) Reword experience with JD keywords. 3) Reorder skills. "
    "4) Quantify achievements. 5) Do NOT fabricate.\\n"
    'Return STRICT JSON: {"tailored_summary":string(REQUIRED),"tailored_experience":[{"title":string,"company":string,"bullets":[string]}](REQUIRED),'
    '"tailored_skills":[string](REQUIRED),"ats_score_estimate":integer 0-100}\\nReturn ONLY valid JSON.'
)
nodes.append(ollama_call("h100", "Ollama - Tailor Resume", TAILOR_PROMPT,
    '{{ JSON.stringify("Resume: " + JSON.stringify($("Validate - Fit").first().json.user) + "\\nJob: " + JSON.stringify($("Validate - Fit").first().json.job) + "\\nAngle: " + $("Validate - Fit").first().json.strategic_angle) }}',
    _pos(4340, Y_H), temp=0.3))

nodes.append(validate_node("h101", "Validate - Tailor",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.choices[0].message.content); } catch(e) { throw new Error("Tailor invalid JSON"); }\n'
    'if (!p.tailored_summary) throw new Error("Missing tailored_summary");\n'
    'if (!Array.isArray(p.tailored_experience)) throw new Error("tailored_experience must be array");\n'
    'p._raw = resp.choices[0].message.content;\n'
    'return [{ json: p }];',
    _pos(4580, Y_H)))

HUMANIZE_RESUME_PROMPT = (
    "You are an AI content humanizer. Rewrite to sound naturally human: vary sentence length, use contractions, remove buzzword stacking.\\n"
    'Return STRICT JSON: {"ai_detection_score":integer 0-100,"humanized_text":string(REQUIRED),"changes_made":[string]}\\n'
    "Return ONLY valid JSON."
)
nodes.append(ollama_call("h102", "Ollama - Humanize Resume", HUMANIZE_RESUME_PROMPT,
    '{{ JSON.stringify($json._raw) }}', _pos(4820, Y_H), temp=0.7))

nodes.append(validate_node("h103", "Validate - Humanized Resume",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.choices[0].message.content); } catch(e) { throw new Error("Humanize invalid JSON"); }\n'
    'if (!p.humanized_text) throw new Error("Missing humanized_text");\n'
    'const ctx = $("Validate - Fit").first().json;\n'
    'p.user_id = ctx.user.user_id; p.job_id = ctx.job_id; p.company_id = ctx.company_id;\n'
    'p.strategic_angle = ctx.strategic_angle;\n'
    'p.company_name = ctx.job.company_name; p.job_title = ctx.job.job_title;\n'
    'p.hr_contact_name = ctx.job.hr_contact_name || "Hiring Manager";\n'
    'p.hr_email = ctx.job.hr_email;\n'
    'return [{ json: p }];',
    _pos(5060, Y_H)))

nodes.append(pg_query("h104", "Postgres - Upsert Application",
    "=INSERT INTO applications (user_id, job_id, tailored_resume_text, ai_detection_score, humanization_pass, generation_model, status) "
    "VALUES ('{{ $json.user_id }}'::uuid, '{{ $json.job_id }}'::uuid, '{{ $json.humanized_text }}', "
    "{{ $json.ai_detection_score || 50 }}, TRUE, '{{ $env.OLLAMA_MODEL }}', "
    "CASE WHEN '{{ $(\"Validate - User Auth\").first().json.email_mode }}' = 'AUTO' THEN 'READY' ELSE 'PENDING_REVIEW' END) "
    "ON CONFLICT (user_id, job_id, resume_version) DO UPDATE SET tailored_resume_text=EXCLUDED.tailored_resume_text, "
    "ai_detection_score=EXCLUDED.ai_detection_score, humanization_pass=TRUE, "
    "status=EXCLUDED.status RETURNING application_id;",
    _pos(5300, Y_H)))

EMAIL_DRAFT_PROMPT = (
    "You are a cold outreach email specialist. Write a personalized job application email. "
    "Reference specific company details, genuine interest, value proposition, clear CTA.\\n"
    'Return STRICT JSON: {"subject_line":string(REQUIRED),"email_body":string(150-200 words,REQUIRED),"cta":string}\\n'
    "Return ONLY valid JSON."
)
nodes.append(ollama_call("h105", "Ollama - Draft Email", EMAIL_DRAFT_PROMPT,
    '{{ JSON.stringify("To: " + $("Validate - Humanized Resume").first().json.hr_contact_name + " at " + $("Validate - Humanized Resume").first().json.company_name + "\\nRole: " + $("Validate - Humanized Resume").first().json.job_title + "\\nAngle: " + $("Validate - Humanized Resume").first().json.strategic_angle) }}',
    _pos(5540, Y_H), temp=0.6))

HUMANIZE_EMAIL_PROMPT = (
    "You are a human authenticity editor. Make this cold email sound like a real person. "
    "Vary sentence length, use contractions, add one subtle personal touch.\\n"
    'Return STRICT JSON: {"ai_detection_score":integer 0-100,"humanized_subject":string(REQUIRED),'
    '"humanized_body":string(REQUIRED),"changes_made":[string]}\\nReturn ONLY valid JSON.'
)
nodes.append(ollama_call("h106", "Ollama - Humanize Email", HUMANIZE_EMAIL_PROMPT,
    '{{ JSON.stringify($input.first().json.choices[0].message.content) }}',
    _pos(5780, Y_H), temp=0.8))

nodes.append(validate_node("h107", "Validate - Email",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.choices[0].message.content); } catch(e) { throw new Error("Email humanize invalid JSON"); }\n'
    'if (!p.humanized_subject) throw new Error("Missing humanized_subject");\n'
    'if (!p.humanized_body) throw new Error("Missing humanized_body");\n'
    'p.application_id = $("Postgres - Upsert Application").first().json.application_id;\n'
    'return [{ json: p }];',
    _pos(6020, Y_H)))

nodes.append(pg_query("h108", "Postgres - Save Email Draft",
    "=UPDATE applications SET email_subject='{{ $json.humanized_subject }}', "
    "email_body_long='{{ $json.humanized_body }}', "
    "ai_detection_score={{ $json.ai_detection_score || 50 }}, humanization_pass=TRUE "
    "WHERE application_id='{{ $json.application_id }}'::uuid;",
    _pos(6260, Y_H)))

# Check if AUTO mode → dispatch immediately
nodes.append(node("h109", "IF - Auto Send", "if", {
    "conditions": {"string": [{
        "value1": '={{ $("Validate - User Auth").first().json.email_mode }}',
        "operation": "equals", "value2": "AUTO",
    }]}
}, _pos(6500, Y_H)))

# ═══════════════════════════════════════════════════
# SECTION 3: EMAIL DISPATCH MODULE
# ═══════════════════════════════════════════════════
Y_E = 200

# --- Shared email dispatch logic (used by both auto-send and manual dispatch_email action) ---

# Rate limit check
nodes.append(validate_node("e000", "Check - Rate Limit",
    'const userId = $("Validate - User Auth").first().json.user_id;\n'
    'const hourlyLimit = $("Validate - User Auth").first().json.hourly_email_limit || 10;\n'
    'const dailyLimit = $("Validate - User Auth").first().json.daily_email_limit || 50;\n'
    '// These will be checked by DB query in next node\n'
    'return [{ json: { user_id: userId, hourly_limit: hourlyLimit, daily_limit: dailyLimit, ...$input.first().json } }];',
    _pos(6740, Y_E)))

nodes.append(pg_query("e001", "Postgres - Count Recent Sends",
    "=SELECT "
    "(SELECT COUNT(*) FROM email_dispatch_log WHERE user_id='{{ $json.user_id }}'::uuid AND sent_status='SENT' AND created_at > NOW() - INTERVAL '1 hour') AS hourly_count, "
    "(SELECT COUNT(*) FROM email_dispatch_log WHERE user_id='{{ $json.user_id }}'::uuid AND sent_status='SENT' AND created_at > NOW() - INTERVAL '1 day') AS daily_count;",
    _pos(6980, Y_E)))

nodes.append(validate_node("e002", "Validate - Rate Limit",
    'const counts = $input.first().json;\n'
    'const prev = $("Check - Rate Limit").first().json;\n'
    'if (Number(counts.hourly_count) >= prev.hourly_limit) throw new Error("RATE_LIMITED: hourly limit " + prev.hourly_limit + " reached (" + counts.hourly_count + " sent)");\n'
    'if (Number(counts.daily_count) >= prev.daily_limit) throw new Error("RATE_LIMITED: daily limit " + prev.daily_limit + " reached (" + counts.daily_count + " sent)");\n'
    'return [{ json: prev }];',
    _pos(7220, Y_E)))

# Idempotency check
nodes.append(validate_node("e003", "Compute - Email Hash",
    'const crypto = require("crypto");\n'
    'const subj = $json.humanized_subject || $json.email_subject || "";\n'
    'const body = $json.humanized_body || $json.email_body_long || "";\n'
    'const hash = crypto.createHash("sha256").update(subj + body).digest("hex");\n'
    'const appId = $json.application_id;\n'
    'const userId = $("Validate - User Auth").first().json.user_id;\n'
    'const jobId = $json.job_id || $("Validate - Fit").first().json.job_id;\n'
    'const hrEmail = $json.hr_email || $("Validate - Humanized Resume").first().json.hr_email;\n'
    'return [{ json: { ...($json), email_body_hash: hash, application_id: appId, user_id: userId, job_id: jobId, recipient_email: hrEmail, subject: subj, body: body } }];',
    _pos(7460, Y_E)))

nodes.append(pg_query("e004", "Postgres - Check Duplicate",
    "=SELECT log_id FROM email_dispatch_log WHERE user_id='{{ $json.user_id }}'::uuid "
    "AND job_id='{{ $json.job_id }}'::uuid AND email_body_hash='{{ $json.email_body_hash }}' "
    "AND sent_status='SENT' LIMIT 1;",
    _pos(7700, Y_E)))

nodes.append(node("e005", "IF - Already Sent", "if", {
    "conditions": {"string": [{
        "value1": "={{ $json.log_id }}",
        "operation": "isNotEmpty",
    }]}
}, _pos(7940, Y_E)))

# Already sent → skip
nodes.append(pg_query("e006", "Log - Skipped Duplicate",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Check - Rate Limit\").first().json.user_id }}'::uuid, 'email_dispatch', '={{ $execution.id }}', "
    "'SKIPPED', '{\"reason\": \"duplicate_email\"}'::jsonb);",
    _pos(8180, 400)))

nodes.append(set_node("e007", "Set - Skipped", {"status": "skipped", "reason": "duplicate_email"}, _pos(8420, 400)))

# Not sent yet → fetch OAuth credentials and send
nodes.append(pg_query("e010", "Postgres - Fetch Credentials",
    "=SELECT credential_id, provider, sender_email, "
    "pgp_sym_decrypt(refresh_token_enc, '{{ $env.DB_ENCRYPTION_KEY }}') AS refresh_token, "
    "pgp_sym_decrypt(client_id_enc, '{{ $env.DB_ENCRYPTION_KEY }}') AS client_id_override, "
    "pgp_sym_decrypt(client_secret_enc, '{{ $env.DB_ENCRYPTION_KEY }}') AS client_secret_override "
    "FROM user_email_credentials WHERE user_id='{{ $(\"Check - Rate Limit\").first().json.user_id }}'::uuid "
    "AND is_active=TRUE LIMIT 1;",
    _pos(8180, Y_E)))

nodes.append(validate_node("e011", "Validate - Credentials",
    'const cred = $input.first().json;\n'
    'if (!cred || !cred.refresh_token) throw new Error("No active email credentials for user");\n'
    'const email = $("Compute - Email Hash").first().json;\n'
    'return [{ json: { ...cred, ...email } }];',
    _pos(8420, Y_E)))

# OAuth2 Token Refresh
nodes.append(node("e012", "HTTP - Refresh Token", "httpRequest", {
    "method": "POST",
    "url": '={{ $json.provider === "GMAIL" ? "https://oauth2.googleapis.com/token" : "https://login.microsoftonline.com/" + ($env.OUTLOOK_TENANT_ID || "common") + "/oauth2/v2.0/token" }}',
    "sendBody": True, "specifyBody": "keypair",
    "bodyParameters": {"parameters": [
        {"name": "grant_type", "value": "refresh_token"},
        {"name": "refresh_token", "value": "={{ $json.refresh_token }}"},
        {"name": "client_id", "value": '={{ $json.client_id_override || ($json.provider === "GMAIL" ? $env.GMAIL_CLIENT_ID : $env.OUTLOOK_CLIENT_ID) }}'},
        {"name": "client_secret", "value": '={{ $json.client_secret_override || ($json.provider === "GMAIL" ? $env.GMAIL_CLIENT_SECRET : $env.OUTLOOK_CLIENT_SECRET) }}'},
    ]},
    "options": {"timeout": 15000},
}, _pos(8660, Y_E), version=4))

nodes.append(validate_node("e013", "Validate - Token",
    'const resp = $input.first().json;\n'
    'if (!resp.access_token) throw new Error("OAuth refresh failed: " + JSON.stringify(resp).substring(0,500));\n'
    'const prev = $("Validate - Credentials").first().json;\n'
    'return [{ json: { access_token: resp.access_token, ...prev } }];',
    _pos(8900, Y_E)))

# Send Email via API
nodes.append(node("e014", "HTTP - Send Email", "httpRequest", {
    "method": "POST",
    "url": '={{ $json.provider === "GMAIL" ? "https://gmail.googleapis.com/gmail/v1/users/me/messages/send" : "https://graph.microsoft.com/v1.0/me/sendMail" }}',
    "authentication": "predefinedCredentialType",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "Authorization", "value": "=Bearer {{ $json.access_token }}"},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True, "specifyBody": "json",
    "jsonBody": '={{ $json.provider === "GMAIL" ? JSON.stringify({ raw: Buffer.from("From: " + $json.sender_email + "\\r\\nTo: " + $json.recipient_email + "\\r\\nSubject: " + $json.subject + "\\r\\nContent-Type: text/plain; charset=utf-8\\r\\n\\r\\n" + $json.body).toString("base64url") }) : JSON.stringify({ message: { subject: $json.subject, body: { contentType: "Text", content: $json.body }, toRecipients: [{ emailAddress: { address: $json.recipient_email } }] } }) }}',
    "options": {"timeout": 30000},
}, _pos(9140, Y_E), version=4))

# Log send result
nodes.append(pg_query("e015", "Postgres - Log Send",
    "=INSERT INTO email_dispatch_log (execution_uuid, user_id, job_id, application_id, company_id, recipient_email, subject, email_body_hash, "
    "provider_message_id, sent_status) VALUES ('={{ $execution.id }}'::uuid, "
    "'{{ $(\"Check - Rate Limit\").first().json.user_id }}'::uuid, '{{ $(\"Compute - Email Hash\").first().json.job_id }}'::uuid, "
    "'{{ $(\"Compute - Email Hash\").first().json.application_id }}'::uuid, "
    "'{{ $(\"Validate - Fit\").first().json.company_id }}'::uuid, "
    "'{{ $(\"Compute - Email Hash\").first().json.recipient_email }}', "
    "'{{ $(\"Compute - Email Hash\").first().json.subject }}', "
    "'{{ $(\"Compute - Email Hash\").first().json.email_body_hash }}', "
    "'{{ $json.id || $json.messageId || \"\" }}', 'SENT') "
    "ON CONFLICT (user_id, job_id, email_body_hash) DO NOTHING;",
    _pos(9380, Y_E)))

nodes.append(pg_query("e016", "Postgres - Mark App Sent",
    "=UPDATE applications SET status='SENT', sent_at=NOW() "
    "WHERE application_id='{{ $(\"Compute - Email Hash\").first().json.application_id }}'::uuid;",
    _pos(9620, Y_E)))

nodes.append(pg_query("e017", "Log - Dispatch Success",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Check - Rate Limit\").first().json.user_id }}'::uuid, 'email_dispatch', '={{ $execution.id }}', "
    "'SUCCESS', '{\"recipient\": \"{{ $(\"Compute - Email Hash\").first().json.recipient_email }}\"}'::jsonb);",
    _pos(9860, Y_E)))

nodes.append(set_node("e018", "Set - Dispatch OK", {"status": "success", "module": "email_dispatch"}, _pos(10100, Y_E)))

# ── Low Fit Branch ──
Y_L = 840

nodes.append(pg_query("l100", "Log - Low Fit",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Validate - User Auth\").first().json.user_id }}'::uuid, 'job_analysis', '={{ $execution.id }}', "
    "'SUCCESS', '{\"fit_score\": {{ $(\"Validate - Fit\").first().json.fit_score }}, \"result\": \"low_fit\"}'::jsonb);",
    _pos(4340, Y_L)))

nodes.append(set_node("l101", "Set - Low Fit OK",
    {"status": "low_fit", "fit_score": "={{ $(\"Validate - Fit\").first().json.fit_score }}"}, _pos(4580, Y_L)))

# ── Draft Mode (no auto-send) ──
Y_D = 640
nodes.append(pg_query("d100", "Log - Draft Saved",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Validate - User Auth\").first().json.user_id }}'::uuid, 'email_draft', '={{ $execution.id }}', "
    "'SUCCESS', '{\"mode\": \"draft\", \"application_id\": \"{{ $(\"Postgres - Upsert Application\").first().json.application_id }}\"}'::jsonb);",
    _pos(6740, Y_D)))

nodes.append(set_node("d101", "Set - Draft OK",
    {"status": "draft_saved", "module": "email_draft",
     "application_id": "={{ $(\"Postgres - Upsert Application\").first().json.application_id }}"}, _pos(6980, Y_D)))

# ═══════════════════════════════════════════════════
# SECTION 4: MANUAL DISPATCH_EMAIL ACTION
# ═══════════════════════════════════════════════════
Y_M = 1000

nodes.append(pg_query("m000", "Postgres - Fetch Application",
    "=SELECT a.*, j.job_id, c.company_id, c.hr_email FROM applications a "
    "JOIN jobs j ON j.job_id = a.job_id "
    "JOIN companies c ON c.company_id = j.company_id "
    "WHERE a.application_id = '{{ $json._request_body.data.application_id }}'::uuid "
    "AND a.user_id = '{{ $json.user_id }}'::uuid LIMIT 1;",
    _pos(1460, Y_M)))

nodes.append(validate_node("m001", "Validate - Application",
    'const app = $input.first().json;\n'
    'if (!app || !app.application_id) throw new Error("Application not found or access denied");\n'
    'if (!app.email_subject || !app.email_body_long) throw new Error("Email not yet generated for this application");\n'
    'return [{ json: { ...app, humanized_subject: app.email_subject, humanized_body: app.email_body_long, recipient_email: app.hr_email } }];',
    _pos(1700, Y_M)))

# This connects to the shared email dispatch chain starting at e000

# ═══════════════════════════════════════════════════
# CONNECTIONS
# ═══════════════════════════════════════════════════

connections = {}

def add_conn(src: str, *branches: list[str]) -> None:
    connections[src] = {"main": [[{"node": t, "type": "main", "index": 0} for t in branch] for branch in branches]}

# Global auth flow
add_conn("Webhook", ["IF - Auth Secret"])
add_conn("IF - Auth Secret", ["Postgres - Validate User"], ["Set - 401"])
add_conn("Postgres - Validate User", ["Validate - User Auth"])
add_conn("Validate - User Auth", ["Switch - Router"])
add_conn("Switch - Router", ["Log - Resume Start"], ["Log - Job Start"], ["Postgres - Fetch Application"], ["Set - 400 Bad Action"])

# Resume branch
add_conn("Log - Resume Start", ["Exec - Extract Resume"])
add_conn("Exec - Extract Resume", ["Validate - Resume Text"])
add_conn("Validate - Resume Text", ["Ollama - Structure Resume"])
add_conn("Ollama - Structure Resume", ["Validate - Resume Schema"])
add_conn("Validate - Resume Schema", ["Postgres - Upsert User Resume"])
add_conn("Postgres - Upsert User Resume", ["Log - Resume Success"])
add_conn("Log - Resume Success", ["Set - Resume OK"])

# Job branch
add_conn("Log - Job Start", ["Exec - Scrape Job"])
add_conn("Exec - Scrape Job", ["Validate - Scrape"])
add_conn("Validate - Scrape", ["Ollama - Normalize Job"])
add_conn("Ollama - Normalize Job", ["Validate - Job Schema"])
add_conn("Validate - Job Schema", ["Postgres - Upsert Company"])
add_conn("Postgres - Upsert Company", ["Postgres - Upsert Job"])
add_conn("Postgres - Upsert Job", ["Merge - Context"])
add_conn("Merge - Context", ["Ollama - Analyze Fit"])
add_conn("Ollama - Analyze Fit", ["Validate - Fit"])
add_conn("Validate - Fit", ["Postgres - Save Fit"])
add_conn("Postgres - Save Fit", ["IF - High Fit"])
add_conn("IF - High Fit", ["Ollama - Tailor Resume"], ["Log - Low Fit"])

# High fit branch
add_conn("Ollama - Tailor Resume", ["Validate - Tailor"])
add_conn("Validate - Tailor", ["Ollama - Humanize Resume"])
add_conn("Ollama - Humanize Resume", ["Validate - Humanized Resume"])
add_conn("Validate - Humanized Resume", ["Postgres - Upsert Application"])
add_conn("Postgres - Upsert Application", ["Ollama - Draft Email"])
add_conn("Ollama - Draft Email", ["Ollama - Humanize Email"])
add_conn("Ollama - Humanize Email", ["Validate - Email"])
add_conn("Validate - Email", ["Postgres - Save Email Draft"])
add_conn("Postgres - Save Email Draft", ["IF - Auto Send"])
add_conn("IF - Auto Send", ["Check - Rate Limit"], ["Log - Draft Saved"])

# Email dispatch chain (shared by auto-send and manual dispatch)
add_conn("Check - Rate Limit", ["Postgres - Count Recent Sends"])
add_conn("Postgres - Count Recent Sends", ["Validate - Rate Limit"])
add_conn("Validate - Rate Limit", ["Compute - Email Hash"])
add_conn("Compute - Email Hash", ["Postgres - Check Duplicate"])
add_conn("Postgres - Check Duplicate", ["IF - Already Sent"])
add_conn("IF - Already Sent", ["Log - Skipped Duplicate"], ["Postgres - Fetch Credentials"])
add_conn("Log - Skipped Duplicate", ["Set - Skipped"])
add_conn("Postgres - Fetch Credentials", ["Validate - Credentials"])
add_conn("Validate - Credentials", ["HTTP - Refresh Token"])
add_conn("HTTP - Refresh Token", ["Validate - Token"])
add_conn("Validate - Token", ["HTTP - Send Email"])
add_conn("HTTP - Send Email", ["Postgres - Log Send"])
add_conn("Postgres - Log Send", ["Postgres - Mark App Sent"])
add_conn("Postgres - Mark App Sent", ["Log - Dispatch Success"])
add_conn("Log - Dispatch Success", ["Set - Dispatch OK"])

# Low fit
add_conn("Log - Low Fit", ["Set - Low Fit OK"])

# Draft saved
add_conn("Log - Draft Saved", ["Set - Draft OK"])

# Manual dispatch branch
add_conn("Postgres - Fetch Application", ["Validate - Application"])
add_conn("Validate - Application", ["Check - Rate Limit"])

# ═══════════════════════════════════════════════════
# ASSEMBLE & OUTPUT
# ═══════════════════════════════════════════════════
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Build n8n workflow JSON")
parser.add_argument(
    "--output", "-o",
    type=str,
    default=str(Path(__file__).resolve().parent.parent / "workflows" / "workflow_main.json"),
    help="Output file path (default: workflows/workflow_main.json)",
)
args = parser.parse_args()

workflow = {
    "name": "Master Workflow - Multi-User Job Automation (Production)",
    "nodes": nodes,
    "connections": connections,
    "settings": {
        "executionOrder": "v1",
        "saveManualExecutions": True,
        "saveDataErrorExecution": "all",
        "saveDataSuccessExecution": "all",
        "callerPolicy": "workflowsFromSameOwner",
    },
    "tags": [
        {"name": "production"},
        {"name": "multi-user"},
        {"name": "email-dispatch"},
        {"name": "ollama"},
    ],
}

out_path = Path(args.output)
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(
    json.dumps(workflow, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(f"Wrote {len(nodes)} nodes, {len(connections)} connections -> {out_path}")
