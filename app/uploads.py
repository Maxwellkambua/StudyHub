"""
File upload pipeline for StudyHub.

Responsibilities:
  • Save uploaded files to disk with safe unique names
  • Enforce a size limit
  • Extract text from PDFs (first 10 pages)
  • Auto-generate tags from title + extracted text
"""
import os
import re
import uuid
from pathlib import Path

from fastapi import UploadFile


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_SIZE = 25 * 1024 * 1024  # 25 MB
CHUNK = 1024 * 1024          # 1 MB read chunks


def save_file(file: UploadFile) -> str:
    """
    Persist an UploadFile to disk under uploads/.
    Returns the public URL path, e.g. "/uploads/ab12...pdf".
    Raises ValueError if the file exceeds MAX_SIZE.
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    safe = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / safe

    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = file.file.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_SIZE:
                out.close()
                dest.unlink(missing_ok=True)
                raise ValueError("File too large (max 25 MB)")
            out.write(chunk)

    return f"/uploads/{safe}"


def extract_text(path: Path) -> str:
    """
    Extract text from the first 10 pages of a PDF.
    Returns "" for non-PDFs or on any failure.
    """
    if path.suffix.lower() != ".pdf":
        return ""

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:10]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(pages)[:5000]
    except Exception:
        return ""


def auto_tags(text: str, title: str, max_tags: int = 6) -> str:
    """
    Crude keyword extraction from title + PDF text.
    Swap for an LLM call later if you want smarter tags.
    """
    stop = {
        "the", "and", "for", "with", "this", "that", "from", "into",
        "are", "was", "were", "you", "your", "have", "has", "had",
        "will", "would", "can", "could", "not", "but", "its", "our",
        "all", "any", "use", "used", "using", "one", "two", "also",
        "may", "more", "most", "some", "such", "than", "then", "them",
        "they", "what", "when", "where", "which", "while", "who", "why",
    }

    words = re.findall(r"[a-zA-Z]{4,}", f"{title} {text}".lower())

    freq: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1

    top = sorted(freq, key=freq.get, reverse=True)[:max_tags]
    return ", ".join(top)
    