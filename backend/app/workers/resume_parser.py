"""
Resume parser utility.

Extracts plain text from resume file bytes in PDF, DOCX/DOC, or plain-text
format. Uses multiple libraries with graceful fallbacks.

Extraction priority:
  PDF   → pdfplumber → pypdf → raw printable characters
  DOCX  → python-docx → raw printable characters
  other → raw UTF-8 decode

Extracted from main_commented (1).py lines 1312–1370.
"""
import io
from typing import Optional

from app.core.logging import logger


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """
    Extract readable text from a resume file.

    Args:
        file_bytes: Raw bytes of the file.
        filename:   Original filename — used to detect the extension.

    Returns:
        Extracted plain-text string (may be empty if all methods fail).
    """
    ext = filename.split(".")[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _extract_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return _extract_docx(file_bytes)
    else:
        try:
            return file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            logger.error(f"Failed to decode file as UTF-8 text: {exc}")
            return ""


def extract_text_from_bytes(file_bytes: bytes, content_type: str) -> str:
    """
    Extract text by guessing the format from the HTTP Content-Type header.

    Convenience wrapper used by the Google Drive resume download flow,
    where the filename may not always be available.
    """
    if "pdf" in content_type:
        filename = "resume.pdf"
    elif "word" in content_type or "docx" in content_type or "openxml" in content_type:
        filename = "resume.docx"
    else:
        filename = "resume.txt"
    return extract_text_from_file(file_bytes, filename)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_pdf(file_bytes: bytes) -> str:
    """Try pdfplumber → pypdf → brute-force printable chars."""
    # 1. pdfplumber (best quality)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if text and text.strip():
            return text.strip()
    except Exception as exc:
        logger.error(f"PDF extraction error with pdfplumber: {exc}")

    # 2. pypdf fallback
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text and text.strip():
            return text.strip()
    except Exception as exc:
        logger.debug(f"PDF pypdf fallback failed: {exc}")

    # 3. Last resort: brute-force printable characters
    try:
        raw_str = file_bytes.decode("utf-8", errors="ignore")
        return "".join(
            c if (32 <= ord(c) <= 126 or c in "\n\r\t") else " " for c in raw_str
        ).strip()
    except Exception:
        return ""


def _extract_docx(file_bytes: bytes) -> str:
    """Try python-docx → brute-force printable chars."""
    try:
        import docx

        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs)
        if text and text.strip():
            return text.strip()
    except Exception as exc:
        logger.error(f"DOCX extraction error: {exc}")

    # Fallback
    try:
        raw_str = file_bytes.decode("utf-8", errors="ignore")
        return "".join(
            c if (32 <= ord(c) <= 126 or c in "\n\r\t") else " " for c in raw_str
        ).strip()
    except Exception:
        return ""
