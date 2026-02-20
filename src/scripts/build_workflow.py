"""
Workflow Builder - Generates workflow_main.json programmatically.

Produces a single production n8n workflow with:
  - Multi-user webhook auth (x-automation-secret + x-user-api-key)
  - Resume ingestion module
  - Job analysis module (scrape → normalize → fit → tailor → humanize → email draft)
  - Gmail-only email dispatch (OAuth2 via native Gmail node)
  - AI Agent node for reply classification and generation
  - Inbound email handling via Gmail Trigger
  - Interview scheduling with Google Calendar
  - Audit logging on every module boundary

Usage:
    python scripts/build_workflow.py > n8n_workflows/workflow_main.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────
# Credential Loading
# ──────────────────────────────────────────────────
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "credentials.json"
_creds_data: dict[str, dict] = {}
if _CONFIG_PATH.exists():
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _raw = json.load(_f)
        for _k, _v in _raw.items():
            if isinstance(_v, dict) and "id" in _v:
                _creds_data[_k] = _v
else:
    print(f"WARNING: {_CONFIG_PATH} not found. Using CONFIGURE_ME placeholders.",
          file=sys.stderr)
    print("  Run: python scripts/provision_credentials.py", file=sys.stderr)

# Validate: warn about placeholder IDs
_placeholder_keys = [k for k, v in _creds_data.items() if v.get("id") == "CONFIGURE_ME"]
if _placeholder_keys:
    print(f"WARNING: Credential IDs still placeholder: {_placeholder_keys}",
          file=sys.stderr)
    print("  Run: python scripts/provision_credentials.py", file=sys.stderr)
    if "--strict" in sys.argv:
        print("ERROR: --strict mode: aborting due to placeholder credentials.",
              file=sys.stderr)
        sys.exit(1)

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

def _langchain_node(nid: str, name: str, ntype: str, params: dict,
                    pos: list[int], version: int = 1,
                    creds: dict | None = None) -> dict:
    """Build a @n8n/n8n-nodes-langchain node (AI nodes use a different prefix)."""
    n: dict[str, Any] = {
        "parameters": params,
        "id": nid,
        "name": name,
        "type": f"@n8n/n8n-nodes-langchain.{ntype}",
        "typeVersion": version,
        "position": pos,
    }
    if creds:
        n["credentials"] = creds
    return n

PG = {"postgres": _creds_data.get("postgres", {"id": "CONFIGURE_ME", "name": "Postgres"})}
GMAIL_CREDS = {"gmailOAuth2": _creds_data.get("gmailOAuth2", {"id": "CONFIGURE_ME", "name": "Gmail OAuth2"})}
CAL_CREDS = {"googleCalendarOAuth2Api": _creds_data.get("googleCalendarOAuth2Api", {"id": "CONFIGURE_ME", "name": "Google Calendar"})}
OLLAMA_CREDS = {"ollamaApi": _creds_data.get("ollamaApi", {"id": "CONFIGURE_ME", "name": "Ollama"})}

# ─── AI Connection Tracking ──────────────────────
# These are collected separately from `main` connections because n8n
# uses different port types (ai_languageModel, ai_tool, ai_memory).
ai_connections: list[dict] = []

def add_ai_conn(source: str, target: str, source_output: str = "ai_languageModel") -> None:
    """Register an AI connection (language model → agent, tool → agent, etc.)."""
    ai_connections.append({
        "source": source,
        "target": target,
        "sourceOutput": source_output,
    })

def ollama_model_node(nid: str, name: str, pos: list[int],
                      temp: float = 0.1) -> dict:
    """Build native Ollama Chat Model node (@n8n/n8n-nodes-langchain.lmChatOllama)."""
    return _langchain_node(nid, name, "lmChatOllama", {
        "model": "={{ $env.OLLAMA_MODEL || 'llama3' }}",
        "options": {
            "temperature": temp,
        },
    }, pos, version=1, creds=OLLAMA_CREDS)

def agent_node(nid: str, name: str, system_prompt: str, user_expr: str,
               pos: list[int]) -> dict:
    """Build an AI Agent node (@n8n/n8n-nodes-langchain.agent)."""
    return _langchain_node(nid, name, "agent", {
        "promptType": "define",
        "text": user_expr,
        "options": {
            "systemMessage": system_prompt,
            "returnIntermediateSteps": False,
        },
    }, pos, version=2)

def llm_pair(agent_id: str, agent_name: str, system_prompt: str,
             user_expr: str, pos: list[int], temp: float = 0.1) -> list[dict]:
    """Create an Ollama Chat Model + AI Agent pair and auto-register AI connection.

    Returns a list of 2 nodes: [chat_model, agent].
    The chat model is positioned 40px above the agent.
    """
    model_id = f"{agent_id}_lm"
    model_name = f"LM - {agent_name.replace('AI Agent - ', '')}"
    model_pos = [pos[0], pos[1] - 120]

    model = ollama_model_node(model_id, model_name, model_pos, temp=temp)
    agent = agent_node(agent_id, agent_name, system_prompt, user_expr, pos)

    # Auto-register the ai_languageModel connection
    add_ai_conn(model_name, agent_name, "ai_languageModel")

    return [model, agent]

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

def gmail_node(nid: str, name: str, operation: str, params: dict,
              pos: list[int]) -> dict:
    """Build a Gmail node (n8n-nodes-base.gmail, typeVersion 2.2)."""
    base = {"operation": operation, **params}
    return node(nid, name, "gmail", base, pos, version=2, creds=GMAIL_CREDS)

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
        {"conditions": {"conditions": [{"leftValue": "={{ $json._request_body.action }}", "rightValue": "process_inbound", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 3},
    ]},
    "fallbackOutput": "extra",
}, _pos(1200, 600), version=3))

nodes.append(set_node("w011", "Set - 400 Bad Action", {"statusCode": 400, "status": "error",
    "message": "Unknown action. Use resume_upload, analyze_job, dispatch_email, or process_inbound."}, _pos(1460, 1300)))

# ═══════════════════════════════════════════════════
# SECTION 1: RESUME INGESTION
# ═══════════════════════════════════════════════════
Y_R = 200

nodes.append(pg_query("r000", "Log - Resume Start",
    "=INSERT INTO workflow_logs (request_id, user_id, module_name, execution_id, status, input_summary) "
    "VALUES (gen_random_uuid(), '{{ $json.user_id }}'::uuid, 'resume_ingestion', '={{ $execution.id }}', "
    "'STARTED', '{\"file_path\": \"{{ $json._request_body.data.file_path }}\"}'::jsonb);",
    _pos(1460, Y_R)))

nodes.append(node("r100", "HTTP - Extract Resume", "httpRequest", {
    "method": "POST",
    "url": "http://selenium-worker:8000/extract-resume",
    "sendBody": True, "specifyBody": "json",
    "jsonBody": '={"file_path": "{{ $("Validate - User Auth").first().json._request_body.data.file_path }}"}',
    "options": {"timeout": 30000},
}, _pos(1700, Y_R), version=4))

nodes.append(validate_node("r101", "Validate - Resume Text",
    'const resp = $input.first().json;\n'
    'if (!resp.success) throw new Error("Resume extraction failed: " + (resp.error || "unknown"));\n'
    'const parsed = resp.data;\n'
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
nodes.extend(llm_pair("r102", "AI Agent - Structure Resume", RESUME_SCHEMA_PROMPT,
    '{{ JSON.stringify($json.raw_text) }}', _pos(2180, Y_R)))

nodes.append(validate_node("r103", "Validate - Resume Schema",
    'const resp = $input.first().json;\n'
    'const content = resp.output;\n'
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

nodes.append(node("j100", "HTTP - Scrape Job", "httpRequest", {
    "method": "POST",
    "url": "http://selenium-worker:8000/scrape-job",
    "sendBody": True, "specifyBody": "json",
    "jsonBody": '={"url": "{{ $("Validate - User Auth").first().json._request_body.data.job_url }}", "scrape_type": "job"}',
    "options": {"timeout": 60000},
}, _pos(1700, Y_J), version=4))

nodes.append(validate_node("j101", "Validate - Scrape",
    'const resp = $input.first().json;\n'
    'if (!resp.success) throw new Error("Scraper error: " + (resp.error || "unknown"));\n'
    'const parsed = resp.data;\n'
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
nodes.extend(llm_pair("j102", "AI Agent - Normalize Job", JOB_SCHEMA_PROMPT,
    '{{ JSON.stringify($json.raw_text) }}', _pos(2180, Y_J)))

nodes.append(validate_node("j103", "Validate - Job Schema",
    'const resp = $input.first().json;\n'
    'const content = resp.output;\n'
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
nodes.extend(llm_pair("j108", "AI Agent - Analyze Fit", FIT_PROMPT,
    '{{ JSON.stringify("CANDIDATE:\\n" + JSON.stringify($json.user) + "\\n\\nJOB:\\n" + JSON.stringify($json.job)) }}',
    _pos(3380, Y_J), temp=0.2))

nodes.append(validate_node("j109", "Validate - Fit",
    'const resp = $input.first().json;\n'
    'const content = resp.output;\n'
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
nodes.extend(llm_pair("h100", "AI Agent - Tailor Resume", TAILOR_PROMPT,
    '{{ JSON.stringify("Resume: " + JSON.stringify($("Validate - Fit").first().json.user) + "\\nJob: " + JSON.stringify($("Validate - Fit").first().json.job) + "\\nAngle: " + $("Validate - Fit").first().json.strategic_angle) }}',
    _pos(4340, Y_H), temp=0.3))

nodes.append(validate_node("h101", "Validate - Tailor",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.output); } catch(e) { throw new Error("Tailor invalid JSON"); }\n'
    'if (!p.tailored_summary) throw new Error("Missing tailored_summary");\n'
    'if (!Array.isArray(p.tailored_experience)) throw new Error("tailored_experience must be array");\n'
    'p._raw = resp.output;\n'
    'return [{ json: p }];',
    _pos(4580, Y_H)))

HUMANIZE_RESUME_PROMPT = (
    "You are an AI content humanizer. Rewrite to sound naturally human: vary sentence length, use contractions, remove buzzword stacking.\\n"
    'Return STRICT JSON: {"ai_detection_score":integer 0-100,"humanized_text":string(REQUIRED),"changes_made":[string]}\\n'
    "Return ONLY valid JSON."
)
nodes.extend(llm_pair("h102", "AI Agent - Humanize Resume", HUMANIZE_RESUME_PROMPT,
    '{{ JSON.stringify($json._raw) }}', _pos(4820, Y_H), temp=0.7))

nodes.append(validate_node("h103", "Validate - Humanized Resume",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.output); } catch(e) { throw new Error("Humanize invalid JSON"); }\n'
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
nodes.extend(llm_pair("h105", "AI Agent - Draft Email", EMAIL_DRAFT_PROMPT,
    '{{ JSON.stringify("To: " + $("Validate - Humanized Resume").first().json.hr_contact_name + " at " + $("Validate - Humanized Resume").first().json.company_name + "\\nRole: " + $("Validate - Humanized Resume").first().json.job_title + "\\nAngle: " + $("Validate - Humanized Resume").first().json.strategic_angle) }}',
    _pos(5540, Y_H), temp=0.6))

HUMANIZE_EMAIL_PROMPT = (
    "You are a human authenticity editor. Make this cold email sound like a real person. "
    "Vary sentence length, use contractions, add one subtle personal touch.\\n"
    'Return STRICT JSON: {"ai_detection_score":integer 0-100,"humanized_subject":string(REQUIRED),'
    '"humanized_body":string(REQUIRED),"changes_made":[string]}\\nReturn ONLY valid JSON.'
)
nodes.extend(llm_pair("h106", "AI Agent - Humanize Email", HUMANIZE_EMAIL_PROMPT,
    '{{ JSON.stringify($input.first().json.choices[0].message.content) }}',
    _pos(5780, Y_H), temp=0.8))

nodes.append(validate_node("h107", "Validate - Email",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.output); } catch(e) { throw new Error("Email humanize invalid JSON"); }\n'
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

# Not sent yet → Send via Gmail (OAuth2 handled by n8n Gmail credential)
nodes.append(gmail_node("e010", "Gmail - Send Email", "send", {
    "sendTo": '={{ $("Compute - Email Hash").first().json.recipient_email }}',
    "subject": '={{ $("Compute - Email Hash").first().json.subject }}',
    "message": '={{ $("Compute - Email Hash").first().json.body }}',
    "options": {
        "appendAttribution": False,
    },
}, _pos(8180, Y_E)))

# Log send result
nodes.append(pg_query("e015", "Postgres - Log Send",
    "=INSERT INTO email_dispatch_log (execution_uuid, user_id, job_id, application_id, company_id, recipient_email, subject, email_body_hash, "
    "provider_message_id, thread_id, sent_status) VALUES ('={{ $execution.id }}'::uuid, "
    "'{{ $(\"Check - Rate Limit\").first().json.user_id }}'::uuid, '{{ $(\"Compute - Email Hash\").first().json.job_id }}'::uuid, "
    "'{{ $(\"Compute - Email Hash\").first().json.application_id }}'::uuid, "
    "{{ $(\"Compute - Email Hash\").first().json.company_id ? \"'\" + $(\"Compute - Email Hash\").first().json.company_id + \"'::uuid\" : \"NULL\" }}, "
    "'{{ $(\"Compute - Email Hash\").first().json.recipient_email }}', "
    "'{{ $(\"Compute - Email Hash\").first().json.subject }}', "
    "'{{ $(\"Compute - Email Hash\").first().json.email_body_hash }}', "
    "'{{ $json.id || \"\" }}', '{{ $json.threadId || \"\" }}', 'SENT') "
    "ON CONFLICT (user_id, job_id, email_body_hash) DO NOTHING;",
    _pos(8420, Y_E)))

nodes.append(pg_query("e016", "Postgres - Mark App Sent",
    "=UPDATE applications SET status='SENT', sent_at=NOW() "
    "WHERE application_id='{{ $(\"Compute - Email Hash\").first().json.application_id }}'::uuid;",
    _pos(8660, Y_E)))

nodes.append(pg_query("e017", "Log - Dispatch Success",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Check - Rate Limit\").first().json.user_id }}'::uuid, 'email_dispatch', '={{ $execution.id }}', "
    "'SUCCESS', '{\"recipient\": \"{{ $(\"Compute - Email Hash\").first().json.recipient_email }}\"}'::jsonb);",
    _pos(8900, Y_E)))

nodes.append(set_node("e018", "Set - Dispatch OK", {"status": "success", "module": "email_dispatch"}, _pos(9140, Y_E)))

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
# SECTION 5A: GMAIL TRIGGER (INBOUND ENTRY POINT)
# ═══════════════════════════════════════════════════
# This is a standalone trigger that polls Gmail for new emails.
# It feeds into the same classification pipeline as the webhook-based flow.
Y_GT = 1800

# Gmail Trigger - poll for unread replies
nodes.append(node("gt000", "Gmail Trigger", "gmailTrigger", {
    "event": "messageReceived",
    "simple": True,
    "filters": {
        "readStatus": "unread",
        "q": "is:reply OR in:inbox -category:promotions -category:social",
    },
    "options": {},
}, _pos(200, Y_GT), version=1, creds=GMAIL_CREDS))

# Normalize Gmail Trigger output → standard inbound schema
nodes.append(validate_node("gt001", "Normalize - Gmail Input",
    'const msg = $input.first().json;\n'
    '// Gmail Trigger simplified output fields\n'
    'const threadId = msg.threadId || msg.id || "";\n'
    'const messageId = msg.id || msg.messageId || "";\n'
    'const from = msg.from || msg.sender || "";\n'
    '// Extract email address from "Name <email@example.com>" format\n'
    'const emailMatch = from.match(/<(.+?)>/);\n'
    'const senderEmail = emailMatch ? emailMatch[1] : from;\n'
    'const subject = msg.subject || msg.Subject || "";\n'
    'const body = msg.textPlain || msg.snippet || msg.text || "";\n'
    'return [{ json: {\n'
    '  thread_id: threadId,\n'
    '  message_id: messageId,\n'
    '  sender_email: senderEmail,\n'
    '  email_body: body,\n'
    '  subject: subject,\n'
    '  _source: "gmail_trigger",\n'
    '} }];',
    _pos(500, Y_GT)))

# Look up user by the Gmail account that received the email
nodes.append(pg_query("gt002", "Postgres - Lookup User By Email",
    "=SELECT u.user_id, u.email_mode FROM users u "
    "JOIN user_email_credentials uec ON u.user_id = uec.user_id "
    "WHERE uec.provider_email = '{{ $json.sender_email }}' "
    "OR u.email = '{{ $json.sender_email }}' "
    "AND uec.is_active = TRUE LIMIT 1;",
    _pos(800, Y_GT)))

# Merge user context into the normalized payload
nodes.append(validate_node("gt003", "Validate - Gmail User",
    'const user = $input.first().json;\n'
    'if (!user || !user.user_id) {\n'
    '  // Unknown sender — no matching user in DB, skip\n'
    '  throw new Error("No active user found for incoming email");\n'
    '}\n'
    'const normalized = $("Normalize - Gmail Input").first().json;\n'
    'normalized.user_id = user.user_id;\n'
    'normalized.email_mode = user.email_mode || "DRAFT";\n'
    'return [{ json: normalized }];',
    _pos(1100, Y_GT)))

# ═══════════════════════════════════════════════════
# SECTION 5B: INBOUND EMAIL HANDLING (SHARED PIPELINE)
# ═══════════════════════════════════════════════════
Y_I = 1400

nodes.append(pg_query("i000", "Log - Inbound Start",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, input_summary) "
    "VALUES ('{{ $json.user_id }}'::uuid, 'inbound_email', '={{ $execution.id }}', "
    "'STARTED', '{\"thread_id\": \"{{ $json._request_body.data.thread_id }}\"}'::jsonb);",
    _pos(1460, Y_I)))

# Check if this message was already processed (idempotency)
nodes.append(pg_query("i001", "Postgres - Check Inbound Dup",
    "=SELECT inbound_id FROM inbound_email_log WHERE user_id='{{ $json.user_id }}'::uuid "
    "AND message_id='{{ $json._request_body.data.message_id }}' LIMIT 1;",
    _pos(1700, Y_I)))

nodes.append(node("i002", "IF - Inbound Already Processed", "if", {
    "conditions": {"string": [{
        "value1": "={{ $json.inbound_id }}",
        "operation": "isNotEmpty",
    }]}
}, _pos(1940, Y_I)))

nodes.append(set_node("i003", "Set - Inbound Skipped",
    {"status": "skipped", "reason": "already_processed"}, _pos(2180, Y_I + 200)))

# Validate inbound payload
nodes.append(validate_node("i010", "Validate - Inbound Payload",
    'const body = $("Validate - User Auth").first().json._request_body.data;\n'
    'if (!body.thread_id) throw new Error("Missing thread_id");\n'
    'if (!body.message_id) throw new Error("Missing message_id");\n'
    'if (!body.sender_email) throw new Error("Missing sender_email");\n'
    'if (!body.email_body) throw new Error("Missing email_body");\n'
    'const user = $("Validate - User Auth").first().json;\n'
    'return [{ json: { ...body, user_id: user.user_id, email_mode: user.email_mode } }];',
    _pos(2180, Y_I)))

# Match to original dispatch
nodes.append(pg_query("i011", "Postgres - Match Thread",
    "=SELECT edl.log_id AS dispatch_log_id, edl.job_id, edl.company_id, edl.recipient_email, edl.subject "
    "FROM email_dispatch_log edl WHERE edl.user_id='{{ $json.user_id }}'::uuid "
    "AND edl.sent_status='SENT' "
    "AND (edl.provider_message_id='{{ $json.thread_id }}' OR edl.provider_message_id='{{ $json.message_id }}') "
    "LIMIT 1;",
    _pos(2420, Y_I)))

# Classify reply via AI Agent (LLM_CLASSIFY — centralized reasoning)
CLASSIFY_AGENT_PROMPT = (
    "You are an intelligent email reply classifier for job applications. "
    "Analyze the incoming reply and classify it. "
    "Return STRICT JSON matching this schema exactly:\\n"
    '{"reply_type":string(REQUIRED, one of: INTERVIEW_INVITE, FOLLOW_UP_REQUIRED, REJECTION, INFORMATION_REQUEST, OTHER),'
    '"tone":string(REQUIRED, e.g. positive, neutral, negative, formal),'
    '"urgency_level":string(REQUIRED, one of: HIGH, MEDIUM, LOW),'
    '"requires_user_action":boolean(REQUIRED),'
    '"summary":string(1-2 sentences summarizing the reply)}\\n'
    "Return ONLY valid JSON. No markdown fences."
)
nodes.extend(llm_pair("i012", "AI Agent - Classify Reply", CLASSIFY_AGENT_PROMPT,
    '={{ JSON.stringify($json.email_body || $("Validate - Inbound Payload").first().json.email_body) }}',
    _pos(2660, Y_I)))

nodes.append(validate_node("i013", "Validate - Classification",
    'const resp = $input.first().json;\n'
    '// AI Agent returns { output: "..." }, fallback to Ollama format for compatibility\n'
    'const content = resp.output || (resp.choices && resp.choices[0] && resp.choices[0].message && resp.output) || JSON.stringify(resp);\n'
    'let p; try { p = JSON.parse(content); } catch(e) { throw new Error("Classification invalid JSON: " + String(content).substring(0,500)); }\n'
    'const validTypes = ["INTERVIEW_INVITE","FOLLOW_UP_REQUIRED","REJECTION","INFORMATION_REQUEST","OTHER"];\n'
    'if (!validTypes.includes(p.reply_type)) throw new Error("Invalid reply_type: " + p.reply_type);\n'
    'if (typeof p.requires_user_action !== "boolean") p.requires_user_action = false;\n'
    'const ctx = $("Validate - Inbound Payload").first().json;\n'
    'const thread = $("Postgres - Match Thread").first().json;\n'
    'p.user_id = ctx.user_id; p.thread_id = ctx.thread_id; p.message_id = ctx.message_id;\n'
    'p.sender_email = ctx.sender_email; p.email_body = ctx.email_body; p.email_mode = ctx.email_mode;\n'
    'p.dispatch_log_id = thread.dispatch_log_id || null; p.job_id = thread.job_id || null;\n'
    'p.company_id = thread.company_id || null; p.subject = ctx.subject || thread.subject || "";\n'
    'p._classification_json = JSON.stringify(p);\n'
    'p._llm_model = "ai-agent"; p._llm_tokens = null;\n'
    'return [{ json: p }];',
    _pos(2900, Y_I)))

# Log inbound to DB
nodes.append(pg_query("i014", "Postgres - Log Inbound",
    "=INSERT INTO inbound_email_log (execution_uuid, user_id, thread_id, message_id, sender_email, subject, "
    "raw_email, reply_type, classification_json, dispatch_log_id, job_id, company_id, processed_at) "
    "VALUES ('={{ $execution.id }}'::uuid, '{{ $json.user_id }}'::uuid, '{{ $json.thread_id }}', "
    "'{{ $json.message_id }}', '{{ $json.sender_email }}', '{{ $json.subject }}', "
    "'{{ $json.email_body }}', '{{ $json.reply_type }}', '{{ $json._classification_json }}'::jsonb, "
    "{{ $json.dispatch_log_id ? \"'\" + $json.dispatch_log_id + \"'::uuid\" : \"NULL\" }}, "
    "{{ $json.job_id ? \"'\" + $json.job_id + \"'::uuid\" : \"NULL\" }}, "
    "{{ $json.company_id ? \"'\" + $json.company_id + \"'::uuid\" : \"NULL\" }}, NOW()) "
    "ON CONFLICT (user_id, message_id) DO NOTHING RETURNING inbound_id;",
    _pos(3140, Y_I)))

# Route by reply type
nodes.append(node("i015", "Switch - Reply Type", "switch", {
    "rules": {"values": [
        {"conditions": {"conditions": [{"leftValue": "={{ $(\"Validate - Classification\").first().json.reply_type }}", "rightValue": "INTERVIEW_INVITE", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 0},
        {"conditions": {"conditions": [{"leftValue": "={{ $(\"Validate - Classification\").first().json.reply_type }}", "rightValue": "FOLLOW_UP_REQUIRED", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 1},
        {"conditions": {"conditions": [{"leftValue": "={{ $(\"Validate - Classification\").first().json.reply_type }}", "rightValue": "INFORMATION_REQUEST", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 1},
        {"conditions": {"conditions": [{"leftValue": "={{ $(\"Validate - Classification\").first().json.reply_type }}", "rightValue": "REJECTION", "operator": {"type": "string", "operation": "equals"}}]}, "outputIndex": 2},
    ]},
    "fallbackOutput": "extra",
}, _pos(3380, Y_I), version=3))

# ── Branch: FOLLOW_UP / INFORMATION_REQUEST → Generate auto-reply ──
Y_AR = Y_I + 200

AUTO_REPLY_PROMPT = (
    "You are a professional job applicant writing a follow-up reply. "
    "Context: You previously applied for a role and received a response. "
    "Generate a contextual, professional reply. Keep it concise (80-120 words). "
    "Be helpful, enthusiastic, and specific.\\n"
    'Return STRICT JSON: {"reply_subject":string(REQUIRED),"reply_body":string(REQUIRED)}\\n'
    "Return ONLY valid JSON."
)
nodes.extend(llm_pair("i020", "AI Agent - Generate Reply", AUTO_REPLY_PROMPT,
    '={{ JSON.stringify("Original subject: " + $("Validate - Classification").first().json.subject + "\\nReply type: " + $("Validate - Classification").first().json.reply_type + "\\nIncoming email: " + $("Validate - Classification").first().json.email_body) }}',
    _pos(3620, Y_AR), temp=0.5))

# Reuse the shared humanization prompt (LLM REUSE STRATEGY)
HUMANIZE_REPLY_PROMPT = (
    "You are a human authenticity editor. Make this reply email sound like a real person. "
    "Vary sentence length, use contractions, add one subtle personal touch.\\n"
    'Return STRICT JSON: {"ai_detection_score":integer 0-100,"humanized_subject":string(REQUIRED),'
    '"humanized_body":string(REQUIRED),"changes_made":[string]}\\nReturn ONLY valid JSON.'
)
nodes.extend(llm_pair("i021", "AI Agent - Humanize Reply", HUMANIZE_REPLY_PROMPT,
    '={{ JSON.stringify($input.first().json.choices[0].message.content) }}',
    _pos(3860, Y_AR), temp=0.8))

nodes.append(validate_node("i022", "Validate - Reply",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.output); } catch(e) { throw new Error("Reply humanize invalid JSON"); }\n'
    'if (!p.humanized_subject) throw new Error("Missing humanized_subject");\n'
    'if (!p.humanized_body) throw new Error("Missing humanized_body");\n'
    'const ctx = $("Validate - Classification").first().json;\n'
    'p.user_id = ctx.user_id; p.job_id = ctx.job_id; p.company_id = ctx.company_id;\n'
    'p.recipient_email = ctx.sender_email; p.email_mode = ctx.email_mode;\n'
    'p.subject = p.humanized_subject; p.body = p.humanized_body;\n'
    'return [{ json: p }];',
    _pos(4100, Y_AR)))

# Check AUTO/DRAFT mode before sending reply
nodes.append(node("i023", "IF - Auto Reply Send", "if", {
    "conditions": {"string": [{
        "value1": '={{ $json.email_mode }}',
        "operation": "equals", "value2": "AUTO",
    }]}
}, _pos(4340, Y_AR)))

# Auto reply → feed into shared dispatch chain (reuses rate limit + idempotency + OAuth + send)
# Connection: i023 true → e000 (Check - Rate Limit)

nodes.append(set_node("i024", "Set - Reply Pending Review",
    {"status": "pending_review", "module": "inbound_auto_reply",
     "reply_type": "={{ $(\"Validate - Classification\").first().json.reply_type }}"}, _pos(4580, Y_AR + 200)))

# ── Branch: REJECTION → polite acknowledgment ──
Y_RJ = Y_I + 400

REJECTION_ACK_PROMPT = (
    "You are a professional job applicant. Write a brief, polite acknowledgment to a rejection email. "
    "Express gratitude for their time, wish them well, and leave the door open. Keep it under 60 words.\\n"
    'Return STRICT JSON: {"reply_subject":string(REQUIRED),"reply_body":string(REQUIRED)}\\n'
    "Return ONLY valid JSON."
)
nodes.extend(llm_pair("i030", "AI Agent - Rejection Ack", REJECTION_ACK_PROMPT,
    '={{ JSON.stringify("Subject: " + $("Validate - Classification").first().json.subject + "\\nRejection email: " + $("Validate - Classification").first().json.email_body) }}',
    _pos(3620, Y_RJ), temp=0.4))

nodes.append(validate_node("i031", "Validate - Rejection Ack",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.output); } catch(e) { throw new Error("Rejection ack invalid JSON"); }\n'
    'if (!p.reply_body) throw new Error("Missing reply_body");\n'
    'const ctx = $("Validate - Classification").first().json;\n'
    'p.user_id = ctx.user_id; p.job_id = ctx.job_id; p.recipient_email = ctx.sender_email;\n'
    'p.subject = p.reply_subject || "Re: " + ctx.subject; p.body = p.reply_body;\n'
    'return [{ json: p }];',
    _pos(3860, Y_RJ)))

nodes.append(pg_query("i032", "Log - Rejection Processed",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Validate - Classification\").first().json.user_id }}'::uuid, 'inbound_rejection', '={{ $execution.id }}', "
    "'SUCCESS', '{\"reply_type\": \"REJECTION\", \"sender\": \"{{ $(\"Validate - Classification\").first().json.sender_email }}\"}'::jsonb);",
    _pos(4100, Y_RJ)))

nodes.append(set_node("i033", "Set - Rejection OK",
    {"status": "rejection_acknowledged", "module": "inbound_email"}, _pos(4340, Y_RJ)))

# ── Branch: OTHER → route to manual review ──
Y_OT = Y_I + 600
nodes.append(pg_query("i040", "Log - Other Inbound",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Validate - Classification\").first().json.user_id }}'::uuid, 'inbound_other', '={{ $execution.id }}', "
    "'SUCCESS', '{\"reply_type\": \"OTHER\", \"requires_user_action\": true}'::jsonb);",
    _pos(3620, Y_OT)))

nodes.append(set_node("i041", "Set - Manual Review Required",
    {"status": "manual_review", "module": "inbound_email",
     "message": "Reply classified as OTHER - requires manual review"}, _pos(3860, Y_OT)))

# ═══════════════════════════════════════════════════
# SECTION 6: INTERVIEW SCHEDULING (GOOGLE CALENDAR)
# ═══════════════════════════════════════════════════
Y_IV = Y_I - 200

INTERVIEW_EXTRACT_PROMPT = (
    "You are an interview details extractor. Extract scheduling information from the email.\\n"
    'Return STRICT JSON matching this schema exactly:\\n'
    '{"interview_date":string(REQUIRED, ISO 8601 format YYYY-MM-DD),'
    '"interview_time":string(REQUIRED, HH:MM 24h format),'
    '"timezone":string(default "UTC"),'
    '"interview_mode":string(REQUIRED, one of: VIRTUAL, IN_PERSON, PHONE),'
    '"meeting_link":string|null,'
    '"interviewer_name":string|null,'
    '"interviewer_email":string|null,'
    '"location":string|null,'
    '"duration_minutes":integer(default 60),'
    '"additional_notes":string|null}\\n'
    "Return ONLY valid JSON. No markdown fences."
)
nodes.extend(llm_pair("iv000", "AI Agent - Extract Interview", INTERVIEW_EXTRACT_PROMPT,
    '={{ JSON.stringify($("Validate - Classification").first().json.email_body) }}',
    _pos(3620, Y_IV), temp=0.1))

nodes.append(validate_node("iv001", "Validate - Interview Details",
    'const resp = $input.first().json;\n'
    'const content = resp.output;\n'
    'let p; try { p = JSON.parse(content); } catch(e) { throw new Error("Interview extract invalid JSON: " + content.substring(0,500)); }\n'
    'if (!p.interview_date || !p.interview_time) throw new Error("Missing interview_date or interview_time");\n'
    'const validModes = ["VIRTUAL","IN_PERSON","PHONE"];\n'
    'if (!validModes.includes(p.interview_mode)) p.interview_mode = "VIRTUAL";\n'
    'p.duration_minutes = p.duration_minutes || 60;\n'
    'p.timezone = p.timezone || "UTC";\n'
    'const ctx = $("Validate - Classification").first().json;\n'
    'p.user_id = ctx.user_id; p.job_id = ctx.job_id; p.company_id = ctx.company_id;\n'
    'p.sender_email = ctx.sender_email; p.email_mode = ctx.email_mode;\n'
    'p.subject = ctx.subject;\n'
    'p.interviewer_email = p.interviewer_email || ctx.sender_email;\n'
    'p._llm_model = resp.model || "";\n'
    'return [{ json: p }];',
    _pos(3860, Y_IV)))

# Check for duplicate interview (idempotency)
nodes.append(pg_query("iv002", "Postgres - Check Dup Interview",
    "=SELECT interview_id FROM interview_log WHERE user_id='{{ $json.user_id }}'::uuid "
    "AND job_id='{{ $json.job_id }}'::uuid "
    "AND interview_datetime='{{ $json.interview_date }}T{{ $json.interview_time }}:00'::timestamptz LIMIT 1;",
    _pos(4100, Y_IV)))

nodes.append(node("iv003", "IF - Interview Exists", "if", {
    "conditions": {"string": [{
        "value1": "={{ $json.interview_id }}",
        "operation": "isNotEmpty",
    }]}
}, _pos(4340, Y_IV)))

nodes.append(set_node("iv004", "Set - Interview Dup Skipped",
    {"status": "skipped", "reason": "duplicate_interview"}, _pos(4580, Y_IV - 200)))

# Create Google Calendar Event (uses CAL_CREDS defined in helpers)

nodes.append(node("iv005", "Google Calendar - Create Event", "googleCalendar", {
    "operation": "create",
    "calendar": {"__rl": True, "value": "primary", "mode": "list"},
    "start": '={{ $("Validate - Interview Details").first().json.interview_date + "T" + $("Validate - Interview Details").first().json.interview_time + ":00" }}',
    "end": '={{ (function() { const d = new Date($("Validate - Interview Details").first().json.interview_date + "T" + $("Validate - Interview Details").first().json.interview_time + ":00"); d.setMinutes(d.getMinutes() + ($("Validate - Interview Details").first().json.duration_minutes || 60)); return d.toISOString(); })() }}',
    "additionalFields": {
        "summary": '=Interview: {{ $("Validate - Classification").first().json.subject }}',
        "description": '=Interview Details\\n'
            'Company: {{ $("Validate - Classification").first().json.company_id }}\\n'
            'Interviewer: {{ $("Validate - Interview Details").first().json.interviewer_name || "TBD" }}\\n'
            'Contact: {{ $("Validate - Interview Details").first().json.interviewer_email }}\\n'
            'Mode: {{ $("Validate - Interview Details").first().json.interview_mode }}\\n'
            'Link: {{ $("Validate - Interview Details").first().json.meeting_link || "N/A" }}\\n'
            'Location: {{ $("Validate - Interview Details").first().json.location || "N/A" }}\\n'
            'Notes: {{ $("Validate - Interview Details").first().json.additional_notes || "None" }}',
        "attendees": '={{ $("Validate - Interview Details").first().json.interviewer_email }}',
        "visibility": "private",
        "reminders": {"reminderValues": [{"method": "popup", "minutes": 30}]},
        "timeZone": '={{ $("Validate - Interview Details").first().json.timezone || "UTC" }}',
    },
}, _pos(4580, Y_IV), version=3, creds=CAL_CREDS))

# Log interview to DB
nodes.append(pg_query("iv006", "Postgres - Log Interview",
    "=INSERT INTO interview_log (user_id, job_id, company_id, inbound_id, calendar_event_id, "
    "interview_datetime, end_datetime, timezone, interview_mode, meeting_link, location, "
    "interviewer_name, interviewer_email, status, notes) "
    "VALUES ('{{ $(\"Validate - Interview Details\").first().json.user_id }}'::uuid, "
    "'{{ $(\"Validate - Interview Details\").first().json.job_id }}'::uuid, "
    "{{ $(\"Validate - Interview Details\").first().json.company_id ? \"'\" + $(\"Validate - Interview Details\").first().json.company_id + \"'::uuid\" : \"NULL\" }}, "
    "{{ $(\"Postgres - Log Inbound\").first().json.inbound_id ? \"'\" + $(\"Postgres - Log Inbound\").first().json.inbound_id + \"'::uuid\" : \"NULL\" }}, "
    "'{{ $json.id || $json.iCalUID || \"\" }}', "
    "'{{ $(\"Validate - Interview Details\").first().json.interview_date }}T{{ $(\"Validate - Interview Details\").first().json.interview_time }}:00'::timestamptz, "
    "'{{ $(\"Validate - Interview Details\").first().json.interview_date }}T{{ $(\"Validate - Interview Details\").first().json.interview_time }}:00'::timestamptz + INTERVAL '{{ $(\"Validate - Interview Details\").first().json.duration_minutes || 60 }} minutes', "
    "'{{ $(\"Validate - Interview Details\").first().json.timezone }}', "
    "'{{ $(\"Validate - Interview Details\").first().json.interview_mode }}', "
    "'{{ $(\"Validate - Interview Details\").first().json.meeting_link || \"\" }}', "
    "'{{ $(\"Validate - Interview Details\").first().json.location || \"\" }}', "
    "'{{ $(\"Validate - Interview Details\").first().json.interviewer_name || \"\" }}', "
    "'{{ $(\"Validate - Interview Details\").first().json.interviewer_email }}', "
    "'SCHEDULED', '{{ $(\"Validate - Interview Details\").first().json.additional_notes || \"\" }}') "
    "ON CONFLICT (user_id, job_id, interview_datetime) DO NOTHING RETURNING interview_id;",
    _pos(4820, Y_IV)))

# Update job status to INTERVIEW
nodes.append(pg_query("iv007", "Postgres - Update Job Status",
    "=UPDATE jobs SET status='INTERVIEW', updated_at=NOW() "
    "WHERE job_id='{{ $(\"Validate - Interview Details\").first().json.job_id }}'::uuid;",
    _pos(5060, Y_IV)))

# Generate interview confirmation email
CONFIRM_PROMPT = (
    "You are a professional job applicant. Write a concise interview confirmation email (80-120 words). "
    "Confirm date, time, and mode. Express enthusiasm. Ask if anything needs to be prepared.\\n"
    'Return STRICT JSON: {"reply_subject":string(REQUIRED),"reply_body":string(REQUIRED)}\\n'
    "Return ONLY valid JSON."
)
nodes.extend(llm_pair("iv008", "AI Agent - Confirmation Email", CONFIRM_PROMPT,
    '={{ JSON.stringify("Interview date: " + $("Validate - Interview Details").first().json.interview_date + " " + $("Validate - Interview Details").first().json.interview_time + "\\nMode: " + $("Validate - Interview Details").first().json.interview_mode + "\\nInterviewer: " + ($("Validate - Interview Details").first().json.interviewer_name || "Hiring Manager") + "\\nOriginal email: " + $("Validate - Classification").first().json.email_body) }}',
    _pos(5300, Y_IV), temp=0.5))

# Humanize confirmation (REUSES shared humanization pattern)
nodes.extend(llm_pair("iv009", "AI Agent - Humanize Confirmation", HUMANIZE_REPLY_PROMPT,
    '={{ JSON.stringify($input.first().json.choices[0].message.content) }}',
    _pos(5540, Y_IV), temp=0.8))

nodes.append(validate_node("iv010", "Validate - Confirmation",
    'const resp = $input.first().json;\n'
    'let p; try { p = JSON.parse(resp.output); } catch(e) { throw new Error("Confirmation humanize invalid JSON"); }\n'
    'if (!p.humanized_body) throw new Error("Missing humanized_body");\n'
    'const ctx = $("Validate - Interview Details").first().json;\n'
    'p.user_id = ctx.user_id; p.job_id = ctx.job_id;\n'
    'p.recipient_email = ctx.interviewer_email;\n'
    'p.subject = p.humanized_subject || "Re: " + ctx.subject; p.body = p.humanized_body;\n'
    'p.email_mode = ctx.email_mode;\n'
    'return [{ json: p }];',
    _pos(5780, Y_IV)))

# Check AUTO mode for confirmation send
nodes.append(node("iv011", "IF - Auto Confirm Send", "if", {
    "conditions": {"string": [{
        "value1": '={{ $json.email_mode }}',
        "operation": "equals", "value2": "AUTO",
    }]}
}, _pos(6020, Y_IV)))

nodes.append(set_node("iv012", "Set - Confirm Pending Review",
    {"status": "pending_review", "module": "interview_confirmation"}, _pos(6260, Y_IV - 200)))

nodes.append(pg_query("iv013", "Log - Interview Success",
    "=INSERT INTO workflow_logs (user_id, module_name, execution_id, status, output_summary) "
    "VALUES ('{{ $(\"Validate - Interview Details\").first().json.user_id }}'::uuid, 'interview_scheduling', '={{ $execution.id }}', "
    "'SUCCESS', '{\"interview_date\": \"{{ $(\"Validate - Interview Details\").first().json.interview_date }}\", "
    "\"mode\": \"{{ $(\"Validate - Interview Details\").first().json.interview_mode }}\"}'::jsonb);",
    _pos(6260, Y_IV)))

nodes.append(set_node("iv014", "Set - Interview Scheduled OK",
    {"status": "interview_scheduled", "module": "interview_scheduling"}, _pos(6500, Y_IV)))

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
add_conn("Switch - Router", ["Log - Resume Start"], ["Log - Job Start"], ["Postgres - Fetch Application"], ["Log - Inbound Start"], ["Set - 400 Bad Action"])

# Resume branch
add_conn("Log - Resume Start", ["Exec - Extract Resume"])
add_conn("Exec - Extract Resume", ["Validate - Resume Text"])
add_conn("Validate - Resume Text", ["AI Agent - Structure Resume"])
add_conn("AI Agent - Structure Resume", ["Validate - Resume Schema"])
add_conn("Validate - Resume Schema", ["Postgres - Upsert User Resume"])
add_conn("Postgres - Upsert User Resume", ["Log - Resume Success"])
add_conn("Log - Resume Success", ["Set - Resume OK"])

# Job branch
add_conn("Log - Job Start", ["Exec - Scrape Job"])
add_conn("Exec - Scrape Job", ["Validate - Scrape"])
add_conn("Validate - Scrape", ["AI Agent - Normalize Job"])
add_conn("AI Agent - Normalize Job", ["Validate - Job Schema"])
add_conn("Validate - Job Schema", ["Postgres - Upsert Company"])
add_conn("Postgres - Upsert Company", ["Postgres - Upsert Job"])
add_conn("Postgres - Upsert Job", ["Merge - Context"])
add_conn("Merge - Context", ["AI Agent - Analyze Fit"])
add_conn("AI Agent - Analyze Fit", ["Validate - Fit"])
add_conn("Validate - Fit", ["Postgres - Save Fit"])
add_conn("Postgres - Save Fit", ["IF - High Fit"])
add_conn("IF - High Fit", ["AI Agent - Tailor Resume"], ["Log - Low Fit"])

# High fit branch
add_conn("AI Agent - Tailor Resume", ["Validate - Tailor"])
add_conn("Validate - Tailor", ["AI Agent - Humanize Resume"])
add_conn("AI Agent - Humanize Resume", ["Validate - Humanized Resume"])
add_conn("Validate - Humanized Resume", ["Postgres - Upsert Application"])
add_conn("Postgres - Upsert Application", ["AI Agent - Draft Email"])
add_conn("AI Agent - Draft Email", ["AI Agent - Humanize Email"])
add_conn("AI Agent - Humanize Email", ["Validate - Email"])
add_conn("Validate - Email", ["Postgres - Save Email Draft"])
add_conn("Postgres - Save Email Draft", ["IF - Auto Send"])
add_conn("IF - Auto Send", ["Check - Rate Limit"], ["Log - Draft Saved"])

# Email dispatch chain (Gmail-only, shared by auto-send, manual dispatch, auto-reply, and confirmations)
add_conn("Check - Rate Limit", ["Postgres - Count Recent Sends"])
add_conn("Postgres - Count Recent Sends", ["Validate - Rate Limit"])
add_conn("Validate - Rate Limit", ["Compute - Email Hash"])
add_conn("Compute - Email Hash", ["Postgres - Check Duplicate"])
add_conn("Postgres - Check Duplicate", ["IF - Already Sent"])
add_conn("IF - Already Sent", ["Log - Skipped Duplicate"], ["Gmail - Send Email"])
add_conn("Log - Skipped Duplicate", ["Set - Skipped"])
add_conn("Gmail - Send Email", ["Postgres - Log Send"])
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

# Gmail Trigger inbound entry (parallel to webhook-based inbound)
add_conn("Gmail Trigger", ["Normalize - Gmail Input"])
add_conn("Normalize - Gmail Input", ["Postgres - Lookup User By Email"])
add_conn("Postgres - Lookup User By Email", ["Validate - Gmail User"])
add_conn("Validate - Gmail User", ["Postgres - Check Inbound Dup"])

# Webhook-based inbound email branch
add_conn("Log - Inbound Start", ["Postgres - Check Inbound Dup"])
add_conn("Postgres - Check Inbound Dup", ["IF - Inbound Already Processed"])
add_conn("IF - Inbound Already Processed", ["Set - Inbound Skipped"], ["Validate - Inbound Payload"])
add_conn("Validate - Inbound Payload", ["Postgres - Match Thread"])
add_conn("Postgres - Match Thread", ["AI Agent - Classify Reply"])
add_conn("AI Agent - Classify Reply", ["Validate - Classification"])
add_conn("Validate - Classification", ["Postgres - Log Inbound"])
add_conn("Postgres - Log Inbound", ["Switch - Reply Type"])
add_conn("Switch - Reply Type",
    ["AI Agent - Extract Interview"],       # INTERVIEW_INVITE
    ["AI Agent - Generate Reply"],           # FOLLOW_UP / INFO_REQUEST
    ["AI Agent - Rejection Ack"],            # REJECTION
    ["Log - Other Inbound"],               # OTHER (fallback)
)

# Auto-reply chain (FOLLOW_UP / INFO_REQUEST)
add_conn("AI Agent - Generate Reply", ["AI Agent - Humanize Reply"])
add_conn("AI Agent - Humanize Reply", ["Validate - Reply"])
add_conn("Validate - Reply", ["IF - Auto Reply Send"])
add_conn("IF - Auto Reply Send", ["Check - Rate Limit"], ["Set - Reply Pending Review"])

# Rejection branch
add_conn("AI Agent - Rejection Ack", ["Validate - Rejection Ack"])
add_conn("Validate - Rejection Ack", ["Log - Rejection Processed"])
add_conn("Log - Rejection Processed", ["Set - Rejection OK"])

# Other branch
add_conn("Log - Other Inbound", ["Set - Manual Review Required"])

# Interview scheduling branch
add_conn("AI Agent - Extract Interview", ["Validate - Interview Details"])
add_conn("Validate - Interview Details", ["Postgres - Check Dup Interview"])
add_conn("Postgres - Check Dup Interview", ["IF - Interview Exists"])
add_conn("IF - Interview Exists", ["Set - Interview Dup Skipped"], ["Google Calendar - Create Event"])
add_conn("Google Calendar - Create Event", ["Postgres - Log Interview"])
add_conn("Postgres - Log Interview", ["Postgres - Update Job Status"])
add_conn("Postgres - Update Job Status", ["AI Agent - Confirmation Email"])
add_conn("AI Agent - Confirmation Email", ["AI Agent - Humanize Confirmation"])
add_conn("AI Agent - Humanize Confirmation", ["Validate - Confirmation"])
add_conn("Validate - Confirmation", ["IF - Auto Confirm Send"])
add_conn("IF - Auto Confirm Send", ["Check - Rate Limit"], ["Set - Confirm Pending Review"])
add_conn("Set - Confirm Pending Review", ["Log - Interview Success"])
add_conn("Log - Interview Success", ["Set - Interview Scheduled OK"])

# ═══════════════════════════════════════════════════
# ASSEMBLE & OUTPUT
# ═══════════════════════════════════════════════════
import argparse

# Merge AI connections (ai_languageModel, ai_tool, ai_memory) into connections dict
for ai_conn in ai_connections:
    src = ai_conn["source"]
    tgt = ai_conn["target"]
    port = ai_conn["sourceOutput"]
    entry = connections.setdefault(src, {"main": [[]]})
    if port not in entry:
        entry[port] = [[]]
    entry[port][0].append({"node": tgt, "type": port, "index": 0})

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
        {"name": "ai-agent"},
    ],
}

out_path = Path(args.output)
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(
    json.dumps(workflow, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(f"Wrote {len(nodes)} nodes, {len(connections)} connections "
      f"({len(ai_connections)} AI) -> {out_path}")

