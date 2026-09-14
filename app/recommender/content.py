"""
Content-based similarity.

Uses sentence-transformers if available (better synonyms + multilingual),
otherwise falls back to TF-IDF char n-grams (works offline, zero download).
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from .text import normalize

_model = None
_use_embeddings = False

try:
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    _use_embeddings = True
except Exception:
    _use_embeddings = False


def is_using_embeddings() -> bool:
    return _use_embeddings


def doc_text(material) -> str:
    course = f"{material.course.code} {material.course.title}" if material.course else ""
    return normalize(" ".join([
        material.title or "",
        material.description or "",
        material.tags or "",
        material.kind or "",
        course,
    ]))


def build_matrix(materials):
    """Return (ids, matrix). matrix shape: (n_items, n_features)."""
    ids = [m.id for m in materials]
    if not materials:
        return ids, None

    docs = [doc_text(m) for m in materials]

    if _use_embeddings:
        # Normalized embeddings → cosine == dot product
        vecs = _model.encode(docs, normalize_embeddings=True, show_progress_bar=False)
        return ids, np.asarray(vecs, dtype="float32")

    # Fallback: character n-grams handle spelling variants across languages well
    vectorizer = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True
    )
    matrix = vectorizer.fit_transform(docs)
    return ids, matrix


def similarity_to_profile(matrix, index_row, profile_vec):
    """Cosine similarity between one item row and a profile vector."""
    if matrix is None or profile_vec is None:
        return 0.0
    row = matrix[index_row]
    try:
        from sklearn.preprocessing import normalize as sk_normalize
        a = sk_normalize(row)
        b = profile_vec.reshape(1, -1)
        b = sk_normalize(b)
        return float((a @ b.T).toarray()[0][0]) if hasattr(a, "toarray") else float(a @ b.T)
    except Exception:
        return 0.0
        