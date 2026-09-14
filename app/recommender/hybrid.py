"""
Hybrid recommender: content + collaborative + popularity + freshness + enrollment.

Adaptive weighting:
  - Cold-start users (no history)   → rely on content + popularity
  - Warm users (1-4 interactions)   → blend content + collab
  - Hot users (5+ interactions)     → collab dominates

Enrollment boost:
  - Courses the user is enrolled in get +0.35
  - Courses from the same university get +0.15
"""
from datetime import datetime, timezone
from typing import List, Dict

import numpy as np
from sqlalchemy.orm import Session

from .. import models
from . import content, collab


_state = {
    "content_ids": [],
    "content_matrix": None,
    "collab_matrix": None,
    "item_item": None,
    "index_maps": {},
}


def build_index(db: Session) -> None:
    """Rebuild all indexes. Call after inserts or on a schedule."""
    materials = db.query(models.Material).filter(models.Material.hidden == False).all()

    ids, matrix = content.build_matrix(materials)
    _state["content_ids"] = ids
    _state["content_matrix"] = matrix

    u_ids, i_ids, ui_matrix, maps = collab.build_user_item_matrix(db, models)
    _state["collab_matrix"] = ui_matrix
    _state["index_maps"] = maps
    _state["item_item"] = collab.item_item_scores(ui_matrix)


def _ensure_index(db: Session) -> None:
    if _state["content_matrix"] is None:
        build_index(db)


def _content_profile(user, by_id):
    liked = {r.material_id for r in user.ratings if r.score >= 4}
    liked |= {e.material_id for e in user.events if e.action == "download"}
    if not liked or _state["content_matrix"] is None:
        return None

    id_to_row = {mid: i for i, mid in enumerate(_state["content_ids"])}
    rows = [id_to_row[i] for i in liked if i in id_to_row]
    if not rows:
        return None

    m = _state["content_matrix"]
    sub = m[rows].toarray() if hasattr(m, "toarray") else np.asarray(m[rows])
    return sub.mean(axis=0)


def _popularity(material) -> float:
    downloads = sum(1 for e in material.events if e.action == "download")
    saves = sum(1 for e in material.events if e.action == "save")
    views = sum(1 for e in material.events if e.action == "view")
    raw = downloads * 3 + saves * 4 + views
    return min(1.0, raw / 40.0)


def _freshness(material) -> float:
    if not material.created_at:
        return 0.0
    now = datetime.now(timezone.utc)
    created = material.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = (now - created).days
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.6
    if age_days <= 90:
        return 0.3
    return 0.0


def recommend_for_user(db: Session, user, limit: int = 10) -> List[Dict]:
    _ensure_index(db)

    materials = db.query(models.Material).filter(models.Material.hidden == False).all()
    if not materials:
        return []
    by_id = {m.id: m for m in materials}

    history_ids = {e.material_id for e in user.events} | {r.material_id for r in user.ratings}
    n_history = len(history_ids)

    if n_history == 0:
        w_content, w_collab, w_pop, w_fresh = 0.0, 0.0, 0.7, 0.3
    elif n_history < 5:
        w_content, w_collab, w_pop, w_fresh = 0.5, 0.3, 0.15, 0.05
    else:
        w_content, w_collab, w_pop, w_fresh = 0.35, 0.55, 0.08, 0.02

    profile = _content_profile(user, by_id)
    id_to_row = {mid: i for i, mid in enumerate(_state["content_ids"])}
    collab_scores = collab.score_for_user(
        user, _state["collab_matrix"], _state["item_item"],
        _state["index_maps"], by_id,
    )

    # Enrollment set — user's enrolled course IDs
    enrolled_ids = {e.course_id for e in getattr(user, "enrollments", [])}

    results = []
    for m in materials:
        if m.id in history_ids:
            continue

        parts = {}
        reasons = []

        c_sim = 0.0
        if profile is not None and m.id in id_to_row:
            c_sim = content.similarity_to_profile(
                _state["content_matrix"], id_to_row[m.id], profile
            )
        parts["content"] = c_sim
        if c_sim > 0.15:
            reasons.append("similar to what you liked")

        cf = collab_scores.get(m.id, 0.0)
        parts["collab"] = cf
        if cf > 0.3:
            reasons.append("students like you studied this")

        pop = _popularity(m)
        parts["popularity"] = pop
        if pop > 0.4:
            reasons.append("popular with peers")

        fresh = _freshness(m)
        parts["freshness"] = fresh
        if fresh > 0.8:
            reasons.append("newly added")

        if m.avg_rating >= 4.0:
            reasons.append(f"rated {m.avg_rating}/5")

        score = (
            w_content * parts["content"]
            + w_collab * parts["collab"]
            + w_pop * parts["popularity"]
            + w_fresh * parts["freshness"]
            + 0.1 * (m.avg_rating / 5.0)
        )

        # Course affinity — enrollment beats university
        if m.course_id and m.course_id in enrolled_ids:
            score += 0.35
            reasons.insert(0, f"enrolled in {m.course.code if m.course else 'this course'}")
        elif m.course and user.university_id and m.course.university_id == user.university_id:
            score += 0.15
            reasons.insert(0, f"matches {m.course.code}")

        if score > 0.01:
            unique = list(dict.fromkeys(reasons))[:2]
            results.append({
                "material": m,
                "score": round(score, 4),
                "reason": ", ".join(unique) or "recommended for you",
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def is_using_embeddings() -> bool:
    return content.is_using_embeddings()
