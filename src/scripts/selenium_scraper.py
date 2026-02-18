"""
Selenium + BeautifulSoup Web Scraper — Production Hardened.

Uses headless Chromium to render dynamic pages, then parses with BS4.
Outputs structured JSON to stdout for n8n Execute Command consumption.
All diagnostics go to stderr only.

Usage:
    python3 -m scripts.selenium_scraper --url https://example.com --type company
    python3 -m scripts.selenium_scraper --url https://example.com/jobs/123 --type job

Exit Codes:
    0 — Success (JSON on stdout)
    1 — Recoverable error (JSON with error field on stdout)
    2 — Fatal / invalid arguments
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ──────────────────────────────────────────────────
# Logging — STDERR ONLY (stdout reserved for JSON)
# ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("selenium_scraper")

# ──────────────────────────────────────────────────
# Configuration (from environment)
# ──────────────────────────────────────────────────
DELAY_MIN = float(os.getenv("SCRAPER_REQUEST_DELAY_MIN", "2"))
DELAY_MAX = float(os.getenv("SCRAPER_REQUEST_DELAY_MAX", "5"))
PAGE_LOAD_TIMEOUT = int(os.getenv("SCRAPER_PAGE_LOAD_TIMEOUT", "30"))
SCRIPT_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_S", "45"))
CHROME_BIN = os.getenv("CHROME_BIN", "/usr/bin/chromium")
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
MAX_TEXT_PER_PAGE = 15000
MAX_AGGREGATED_TEXT = 50000

COMPANY_PATHS = [
    "/about", "/about-us", "/careers", "/jobs",
    "/internships", "/team", "/our-team",
    "/mission", "/culture", "/values",
]


# ──────────────────────────────────────────────────
# Timeout Signal Handler
# ──────────────────────────────────────────────────
class ScriptTimeoutError(Exception):
    """Raised when the script exceeds SCRIPT_TIMEOUT."""


def _timeout_handler(signum: int, frame: object) -> None:
    raise ScriptTimeoutError(f"Script exceeded {SCRIPT_TIMEOUT}s hard limit")


# ──────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────
@dataclass
class PageResult:
    """Result of scraping a single page."""
    url: str
    status: str = "ok"
    title: str = ""
    clean_text: str = ""
    error: Optional[str] = None


@dataclass
class CompanyIntelligence:
    """Aggregated company scrape result."""
    company_domain: str
    pages_scraped: int = 0
    pages_failed: int = 0
    page_results: list[PageResult] = field(default_factory=list)
    aggregated_text: str = ""
    career_links: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class JobScrapeResult:
    """Result of scraping a single job posting page."""
    job_url: str
    title: str = ""
    raw_text: str = ""
    error: Optional[str] = None


# ──────────────────────────────────────────────────
# Driver Factory
# ──────────────────────────────────────────────────
def _create_driver() -> webdriver.Chrome:
    """Create a headless Chrome WebDriver with strict timeouts."""
    opts = Options()
    opts.binary_location = CHROME_BIN
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    service = Service(executable_path=CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(PAGE_LOAD_TIMEOUT)
    return driver


# ──────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────
def _polite_delay() -> None:
    """Random delay between requests."""
    delay = random.uniform(DELAY_MIN, DELAY_MAX)  # noqa: S311
    logger.info("Waiting %.1fs", delay)
    time.sleep(delay)


def _parse_page_source(page_source: str) -> tuple[str, str]:
    """Parse HTML with BS4, return (title, clean_text)."""
    soup = BeautifulSoup(page_source, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    lines = [line.strip() for line in soup.get_text(separator="\n", strip=True).splitlines() if line.strip()]
    clean_text = "\n".join(lines)[:MAX_TEXT_PER_PAGE]
    return title, clean_text


def _extract_career_links(page_source: str, base_url: str) -> list[str]:
    """Find links that look like job/career sub-pages."""
    soup = BeautifulSoup(page_source, "lxml")
    keywords = {"career", "job", "opening", "position", "apply", "intern", "hiring"}
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].lower()
        if any(kw in href for kw in keywords):
            full = urljoin(base_url, anchor["href"])
            if full not in links:
                links.append(full)
    return links[:30]


def _fetch_page(driver: webdriver.Chrome, url: str) -> PageResult:
    """Navigate to URL and extract clean text."""
    try:
        logger.info("Loading: %s", url)
        driver.get(url)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(1)  # JS settle
        title, clean_text = _parse_page_source(driver.page_source)
        if len(clean_text) < 50:
            return PageResult(url=url, status="empty", error="Page yielded minimal content")
        return PageResult(url=url, title=title, clean_text=clean_text)
    except TimeoutException:
        logger.warning("Timeout on %s", url)
        return PageResult(url=url, status="timeout", error=f"Page load timeout ({PAGE_LOAD_TIMEOUT}s)")
    except WebDriverException as exc:
        logger.warning("WebDriver error %s: %s", url, exc.msg)
        return PageResult(url=url, status="error", error=str(exc.msg)[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error %s: %s", url, exc)
        return PageResult(url=url, status="error", error=str(exc)[:500])


# ──────────────────────────────────────────────────
# Scraping Functions
# ──────────────────────────────────────────────────
def scrape_company(base_url: str) -> CompanyIntelligence:
    """Scrape a company across multiple known paths."""
    parsed = urlparse(base_url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    result = CompanyIntelligence(company_domain=domain)

    driver = _create_driver()
    try:
        for path in COMPANY_PATHS:
            target_url = urljoin(domain, path)
            page = _fetch_page(driver, target_url)
            if page.error:
                result.pages_failed += 1
            else:
                result.pages_scraped += 1
            result.page_results.append(page)
            _polite_delay()

        # Career sub-links
        careers_page = next(
            (p for p in result.page_results if "/careers" in p.url and not p.error), None
        )
        if careers_page:
            try:
                driver.get(careers_page.url)
                WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                result.career_links = _extract_career_links(driver.page_source, domain)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Career link extraction failed: %s", exc)
    finally:
        driver.quit()

    texts = [p.clean_text for p in result.page_results if p.clean_text]
    result.aggregated_text = "\n\n---\n\n".join(texts)[:MAX_AGGREGATED_TEXT]
    return result


def scrape_job(job_url: str) -> JobScrapeResult:
    """Scrape a single job posting page."""
    driver = _create_driver()
    try:
        page = _fetch_page(driver, job_url)
        return JobScrapeResult(
            job_url=job_url,
            title=page.title,
            raw_text=page.clean_text,
            error=page.error,
        )
    finally:
        driver.quit()


# ──────────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────────
def main() -> None:
    """Parse arguments, enforce timeout, and run the appropriate scraper."""
    # Set hard timeout (Unix only; no-op on Windows)
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(SCRIPT_TIMEOUT)

    parser = argparse.ArgumentParser(description="Selenium + BS4 Scraper")
    parser.add_argument("--url", required=True, help="Target URL")
    parser.add_argument("--type", required=True, choices=["company", "job"], help="Scrape type")
    args = parser.parse_args()

    try:
        if args.type == "company":
            result = scrape_company(args.url)
        else:
            result = scrape_job(args.url)

        # JSON to stdout — the ONLY stdout output
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        sys.exit(0)

    except ScriptTimeoutError as exc:
        error_result = {"error": str(exc), "url": args.url, "type": args.type}
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001
        error_result = {"error": str(exc)[:1000], "url": args.url, "type": args.type}
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
