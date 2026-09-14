"""
Language-aware text normalization for StudyHub.

Handles English, Swahili, French, and Pidgin by:
  1. Lowercasing + stripping accents
  2. Expanding a domain synonym map (study-material vocabulary)
  3. Collapsing punctuation and whitespace
  4. Preserving course codes like "csc301" and "mat201"
"""
import re
import unicodedata


# ------------------------------------------------------------------
# Domain synonym map — study-material vocabulary across languages.
# Extend this as you observe real queries in production.
# ------------------------------------------------------------------
SYNONYMS = {
    # ---- English variants ----
    "past paper": "past_paper",
    "past papers": "past_paper",
    "pastpaper": "past_paper",
    "pastpapers": "past_paper",
    "exam": "past_paper",
    "exams": "past_paper",
    "test": "past_paper",
    "tests": "past_paper",
    "quiz": "past_paper",
    "revision": "study",
    "revise": "study",
    "revising": "study",
    "reading": "study",
    "read": "study",

    # ---- Swahili ----
    "mitihani": "past_paper",     # exams
    "mtihani": "past_paper",      # exam
    "maswali": "past_paper",      # questions
    "kujifunza": "study",         # to study
    "kusoma": "study",            # to read/study
    "masomo": "study",            # studies
    "vitabu": "notes",            # books
    "kitabu": "notes",            # book
    "mada": "notes",              # topic
    "mihadhara": "slides",        # lectures

    # ---- French ----
    "examen": "past_paper",
    "examens": "past_paper",
    "etudier": "study",
    "etude": "study",
    "reviser": "study",
    "cours": "notes",
    "notes de cours": "notes",
    "livres": "notes",
    "livre": "notes",
    "sujets": "past_paper",

    # ---- Pidgin ----
    "book": "notes",
    "books": "notes",
    "note": "notes",
    "class": "notes",
    "lessons": "notes",
    "lesson": "notes",
}


# Words to drop entirely — too generic to carry signal
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into",
    "are", "was", "were", "you", "your", "have", "has", "had",
    "will", "would", "can", "could", "not", "but", "its", "our",
    "all", "any", "use", "used", "using", "one", "two", "also",
    "may", "more", "most", "some", "such", "than", "then", "them",
    "they", "what", "when", "where", "which", "while", "who", "why",
}


def strip_accents(s: str) -> str:
    """é → e, ñ → n, ç → c. Keeps 'café' and 'cafe' equivalent."""
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _expand_synonyms(text: str) -> str:
    """
    Apply the synonym map. Longest phrases first so 'past papers'
    is matched before 'past paper' before 'papers'.
    """
    for src in sorted(SYNONYMS, key=len, reverse=True):
        dst = SYNONYMS[src]
        pattern = r"\b" + re.escape(src) + r"\b"
        text = re.sub(pattern, dst, text)
    return text


def _normalize_course_codes(text: str) -> str:
    """
    Collapse 'csc 301' and 'csc-301' and 'csc301' into 'csc301'
    so course-code queries are robust to formatting.
    """
    # Letter-block + optional space/dash + digits
    return re.sub(
        r"\b([a-z]{2,4})[\s\-_]*(\d{3,4})\b",
        lambda m: f"{m.group(1)}{m.group(2)}",
        text,
    )


def normalize(text: str) -> str:
    """
    Full pipeline:
      lowercase → strip accents → normalize course codes
      → expand synonyms → strip punctuation
      → collapse whitespace → drop stopwords
    """
    if not text:
        return ""

    t = text.lower()
    t = strip_accents(t)
    t = _normalize_course_codes(t)
    t = _expand_synonyms(t)

    # Replace separators with spaces (tags often use commas/underscores)
    t = re.sub(r"[_\-/,;|#]+", " ", t)

    # Drop non-word characters except spaces
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)

    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()

    # Drop stopwords (preserve short tokens that might be course codes)
    tokens = [
        w for w in t.split()
        if w not in STOPWORDS or re.match(r"^[a-z]{2,4}\d{3,4}$", w)
    ]
    return " ".join(tokens)


def tokenize(text: str) -> list[str]:
    """Convenience: normalize then split into tokens."""
    return normalize(text).split()


def tags_to_list(raw: str) -> list[str]:
    """Split a 'tags' field into clean individual tags."""
    if not raw:
        return []
    parts = re.split(r"[,\|;]+", raw)
    return [p.strip().lower() for p in parts if p.strip()]
    