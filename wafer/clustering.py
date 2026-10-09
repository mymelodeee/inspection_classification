"""DBSCAN candidate clusters in mm. Noise points are returned, never dropped (C08)."""
import numpy as np
from sklearn.cluster import DBSCAN


def dbscan(ids, x_mm, y_mm, eps_mm, min_samples):
    ids = list(ids)
    if not ids:
        return {"clusters": {}, "noise": [], "n_clusters": 0}
    pts = np.column_stack([x_mm, y_mm]).astype(float)
    labels = DBSCAN(eps=eps_mm, min_samples=min_samples).fit_predict(pts)
    clusters = {}
    for i, lab in zip(ids, labels):
        if lab >= 0:
            clusters.setdefault(int(lab), []).append(i)
    noise = [i for i, lab in zip(ids, labels) if lab < 0]
    assert sum(map(len, clusters.values())) + len(noise) == len(ids)
    return {"clusters": clusters, "noise": noise, "n_clusters": len(clusters)}
