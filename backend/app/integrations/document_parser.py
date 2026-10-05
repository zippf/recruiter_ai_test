import io

from fastapi import HTTPException

from app.core.logging import logger


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext == "pdf":
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            if text.strip():
                return text.strip()
        except Exception as exc:
            logger.error(f"PDF extraction error with pdfplumber: {exc}")
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                return text.strip()
        except Exception as exc:
            logger.debug(
                f"PDF extraction fallback pypdf not available or failed: {exc}"
            )
        return _decode_printable_text(file_bytes)
    if ext in ["docx", "doc"]:
        try:
            import docx

            document = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            if text.strip():
                return text.strip()
        except Exception as exc:
            logger.error(f"DOCX extraction error: {exc}")
        return _decode_printable_text(file_bytes)
    try:
        return file_bytes.decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to read file as text: {exc}"
        )


def _decode_printable_text(file_bytes: bytes) -> str:
    raw_text = file_bytes.decode("utf-8", errors="ignore")
    return "".join(
        char if (32 <= ord(char) <= 126 or char in "\n\r\t") else " "
        for char in raw_text
    ).strip()
