"""
Item-item collaborative filtering from implicit feedback.

Builds a user × item matrix from InteractionEvents (view=1, download=3, save=4)
and Rating entries (score as-is). Then computes item-item cosine similarity.

No external deps beyond numpy/scipy.
"""
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.preprocessing import normalize

ACTION_WEIGHTS = {"view": 1.0, "download": 3.0, "save": 4.0}


def build_user_item_matrix(db, models):
    """Return (user_ids, item_ids, matrix, id_to_row) or (None,...) if empty."""
    events = db.query(models.InteractionEvent).all()
    ratings = db.query(models.Rating).all()

    if not events and not ratings:
        return None, None, None, {}

    user_ids = sorted({e.user_id for e in events} | {r.user_id for r in ratings})
    item_ids = sorted({e.material_id for e in events} | {r.material_id for r in ratings})
    u_row = {u: i for i, u in enumerate(user_ids)}
    i_col = {m: j for j, m in enumerate(item_ids)}

    rows, cols, vals = [], [], []
    for e in events:
        rows.append(u_row[e.user_id])
        cols.append(i_col[e.material_id])
        vals.append(ACTION_WEIGHTS.get(e.action, 1.0))
    for r in ratings:
        rows.append(u_row[r.user_id])
        cols.append(i_col[r.material_id])
        vals.append(float(r.score))

    matrix = csr_matrix(
        (vals, (rows, cols)), shape=(len(user_ids), len(item_ids))
    )
    return user_ids, item_ids, matrix, {"users": u_row, "items": i_col}


def item_item_scores(matrix):
    """Return normalized item-item similarity as a dense-ish sparse matrix."""
    if matrix is None or matrix.shape[1] == 0:
        return None
    # Normalize columns → cosine between items = dot product
    normed = normalize(matrix, axis=0, norm="l2")
    item_item = (normed.T @ normed).toarray()
    np.fill_diagonal(item_item, 0.0)
    return item_item


def score_for_user(user, matrix, item_item, index_maps, by_id):
    """
    Given a user's interaction history, score every item by:
        sum over history items of item_item[history_item, candidate]
    """
    if matrix is None or item_item is None:
        return {}

    u_row = index_maps["users"].get(user.id)
    if u_row is None:
        return {}

    i_col = index_maps["items"]
    history_cols = matrix[u_row].nonzero()[1]
    if len(history_cols) == 0:
        return {}

    # Weighted sum across history
    weights = matrix[u_row].toarray().ravel()
    scores = item_item[:, history_cols] @ weights[history_cols]

    result = {}
    for item_id, col in i_col.items():
        s = float(scores[col])
        if s > 0:
            result[item_id] = s

    # Normalize to 0..1
    if result:
        mx = max(result.values())
        if mx > 0:
            result = {k: v / mx for k, v in result.items()}
    return result
    