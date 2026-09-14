import os, uuid, re
from pathlib import Path
from fastapi import UploadFile
from pypdf import PdfReader

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_SIZE = 25 * 1024 * 1024  # 25 MB


def save_file(file: UploadFile) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    safe = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / safe
    size = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SIZE:
                out.close()
                dest.unlink(missing_ok=True)
                raise ValueError("File too large")
            out.write(chunk)
    return f"/uploads/{safe}"


def extract_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages[:10]]
        return "\n".join(pages)[:5000]
    except Exception:
        return ""


def auto_tags(text: str, title: str, max_tags: int = 6) -> str:
    """Crude keyword extraction — swap for an LLM call later."""
    stop = {"the","and","for","with","this","that","from","into","are","was",
            "you","your","have","has","will","can","not","but","its","our"}
    words = re.findall(r"[a-zA-Z]{4,}", (title + " " + text).lower())
    freq = {}
    for w in words:
        if w in stop: continue
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq, key=freq.get, reverse=True)[:max_tags]
    return ", ".join(top)
    