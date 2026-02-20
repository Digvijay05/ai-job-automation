"""Worker API — FastAPI wrapper for selenium_scraper and resume_text.

Runs inside the selenium-worker container, exposing HTTP endpoints
that n8n calls instead of using executeCommand nodes.

Endpoints:
    POST /extract-resume  — Extract text from a PDF resume
    POST /scrape-job      — Scrape a job posting page
    GET  /health          — Health check
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────
# Ensure scripts are importable
# ──────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.resume_text import extract_text_from_pdf
from scripts.selenium_scraper import scrape_job

# ──────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker_api")

# ──────────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────────
app = FastAPI(
    title="Selenium Worker API",
    description="HTTP wrapper for resume extraction and job scraping",
    version="1.0.0",
)


# ──────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────
class ResumeRequest(BaseModel):
    """Request body for resume text extraction."""
    file_path: str = Field(..., description="Absolute path to the PDF file inside the container")


class ScrapeRequest(BaseModel):
    """Request body for job page scraping."""
    url: str = Field(..., description="URL of the job posting to scrape")
    scrape_type: str = Field(default="job", description="Type of scrape: 'job' or 'company'")


class WorkerResponse(BaseModel):
    """Standard response envelope."""
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ──────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "selenium-worker"}


@app.post("/extract-resume", response_model=WorkerResponse)
async def extract_resume(req: ResumeRequest) -> WorkerResponse:
    """Extract text from a PDF resume file.

    The file must be accessible inside the container (mounted via volumes).
    """
    logger.info("Resume extraction requested: %s", req.file_path)
    pdf_path = Path(req.file_path)

    try:
        raw_text = extract_text_from_pdf(pdf_path)
        return WorkerResponse(
            success=True,
            data={
                "source_file": str(pdf_path),
                "page_count": raw_text.count("\n\n") + 1,
                "char_count": len(raw_text),
                "raw_text": raw_text,
            },
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Resume extraction failed: %s", exc)
        return WorkerResponse(
            success=False,
            data={
                "source_file": str(pdf_path),
                "page_count": 0,
                "char_count": 0,
                "raw_text": "",
            },
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error during resume extraction")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/scrape-job", response_model=WorkerResponse)
async def scrape_job_endpoint(req: ScrapeRequest) -> WorkerResponse:
    """Scrape a job posting page using headless Chromium.

    Renders the page with Selenium and extracts clean text with BeautifulSoup.
    """
    logger.info("Job scrape requested: %s (type=%s)", req.url, req.scrape_type)

    try:
        from dataclasses import asdict
        result = scrape_job(req.url)
        result_dict = asdict(result)

        if result.error:
            return WorkerResponse(
                success=False,
                data=result_dict,
                error=result.error,
            )

        return WorkerResponse(success=True, data=result_dict)

    except Exception as exc:
        logger.exception("Unexpected error during job scrape")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
