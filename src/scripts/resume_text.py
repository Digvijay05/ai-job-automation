"""
Resume PDF Text Extractor — Production Hardened.

Extracts raw text from a PDF file, validates output,
and emits structured JSON to stdout for n8n consumption.
All diagnostics go to stderr only.

Usage:
    python3 -m scripts.resume_text --file /path/to/resume.pdf

Exit Codes:
    0 — Success (JSON on stdout)
    1 — Recoverable error (JSON with error field on stdout)
    2 — Fatal / invalid arguments
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pdfplumber

# ──────────────────────────────────────────────────
# Logging — STDERR ONLY
# ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("resume_text")

MIN_CHARS = 100  # Minimum chars to consider extraction valid


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file, page by page.

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        Concatenated text from all pages.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If the PDF yields insufficient text.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if not pdf_path.suffix.lower() == ".pdf":
        raise ValueError(f"Not a PDF file: {pdf_path}")

    pages_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) == 0:
            raise ValueError(f"PDF has zero pages: {pdf_path}")

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                pages_text.append(text.strip())
                logger.info("Page %d: %d chars", i + 1, len(text))
            else:
                logger.warning("Page %d: no text extracted", i + 1)

    full_text = "\n\n".join(pages_text)

    if len(full_text) < MIN_CHARS:
        raise ValueError(
            f"Extracted text too short ({len(full_text)} chars < {MIN_CHARS}). "
            f"PDF may be image-based or corrupted."
        )

    return full_text


def main() -> None:
    """CLI entry point for resume text extraction."""
    parser = argparse.ArgumentParser(description="Resume PDF Text Extractor")
    parser.add_argument("--file", required=True, help="Absolute path to the resume PDF")
    args = parser.parse_args()

    pdf_path = Path(args.file).resolve()

    try:
        raw_text = extract_text_from_pdf(pdf_path)

        output = {
            "source_file": str(pdf_path),
            "page_count": raw_text.count("\n\n") + 1,
            "char_count": len(raw_text),
            "raw_text": raw_text,
            "error": None,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        sys.exit(0)

    except (FileNotFoundError, ValueError) as exc:
        error_output = {
            "source_file": str(pdf_path),
            "page_count": 0,
            "char_count": 0,
            "raw_text": "",
            "error": str(exc),
        }
        print(json.dumps(error_output, ensure_ascii=False, indent=2))
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001
        error_output = {
            "source_file": str(pdf_path),
            "page_count": 0,
            "char_count": 0,
            "raw_text": "",
            "error": f"Unexpected error: {exc!s}",
        }
        print(json.dumps(error_output, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
