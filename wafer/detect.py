"""Candidate detectors -> support ids per group (ring / line / local), noise kept.

Ring: densest radius about the wafer center (center known; offset-ring search is TBD).
Line: deterministic RANSAC (seed from profile.randomness.seed). Local: DBSCAN clusters.
Each detector reads every included point; none consumes points another detector needs (plan 3, C08).
Supports may overlap; group totals are taken by unique id union (wafer.groups).
"""
import numpy as np

from . import geometry as g
from .clustering import dbscan
from .line import classify_line
from .ring import classify_ring


LIMITS_RING = ["offset_ring_not_searched", "multi_ring_not_searched", "densest_radius_may_be_another_shape"]
LIMITS_LINE = ["single_line_only", "densest_line_may_be_another_shape"]
# A "no_match" from these detectors means "no match within the searched scope", not "no ring/line exists".


def _ring(ids, x, y, profile):
    rule, tol = profile.shapes.ring, profile.detect.ring_radial_tol_mm
    r = g.r_mm(x, y)
    if len(r) == 0:
        return {"feature_status": "insufficient_data", "reason": "no_points"}
    counts = np.array([(np.abs(r - ri) <= tol).sum() for ri in r])
    r0 = float(np.median(r[np.abs(r - r[counts.argmax()]) <= tol]))   # argmax: first densest, deterministic
    sel = np.abs(r - r0) <= tol
    res = classify_ring(x[sel], y[sel], rule, center=(0.0, 0.0))
    out = {"feature_status": res["feature_status"], "radius_mm": r0, "n": int(sel.sum()),
           "search": "wafer_center_densest_radius_single", "limitations": LIMITS_RING}
    if res["feature_status"] in ("candidate", "matched"):
        out.update(label=res["label"], support_ids=[ids[i] for i in np.flatnonzero(sel)],
                   measurement=res["measurement"])
    else:
        out["reason"] = res.get("reason")
    return out


def _line(ids, x, y, profile):
    rule, tol = profile.shapes.line, profile.detect.line_inlier_mm
    n = len(x)
    if n < max(rule.min_points, 2):
        return {"feature_status": "insufficient_data", "reason": "fewer_than_min_points"}
    rng = np.random.default_rng(profile.randomness.seed)
    best = None
    for _ in range(profile.detect.line_ransac_trials):
        i, j = rng.choice(n, 2, replace=False)
        d = np.array([x[j] - x[i], y[j] - y[i]])
        length = np.hypot(*d)
        if length == 0:
            continue
        dist = np.abs(-d[1] * (x - x[i]) + d[0] * (y - y[i])) / length
        inl = np.flatnonzero(dist <= tol)
        if best is None or len(inl) > len(best):
            best = inl
    if best is None:
        return {"feature_status": "insufficient_data", "reason": "degenerate_points"}
    res = classify_line(x[best], y[best], rule)
    out = {"feature_status": res["feature_status"], "n": int(len(best)), "search": "ransac_max_inlier_single",
           "seed": profile.randomness.seed, "trials": profile.detect.line_ransac_trials, "limitations": LIMITS_LINE}
    if res["feature_status"] in ("candidate", "matched"):
        out.update(label=res["label"], support_ids=[ids[i] for i in best], measurement=res["measurement"])
    else:
        out["reason"] = res.get("reason")
    return out


def detect_groups(ids, x_mm, y_mm, profile):
    """Returns two different kinds of objects, never mixed (plan 5.2, C10/C11):
      clusters          - DBSCAN clusters (label -> ids), each tagged same_as=<shape name> when its id set equals a
                          shape support exactly (e.g. a dense line chain), else None
      shape_supports    - ring / line supports from the shape detectors
      signature_groups  - shape supports + clusters not identical to a shape support (local candidates)
      noise             - DBSCAN noise ids (kept in every total)
    """
    if not profile.detect.enabled:
        return {"feature_status": "disabled"}
    ids = list(ids)
    x, y = np.asarray(x_mm, float), np.asarray(y_mm, float)
    c = profile.clustering
    local = dbscan(ids, x, y, c.eps_mm, c.min_samples)
    ring = _ring(ids, x, y, profile) if profile.shapes.ring.enabled else {"feature_status": "disabled"}
    line = _line(ids, x, y, profile) if profile.shapes.line.enabled else {"feature_status": "disabled"}
    shapes = {n: r["support_ids"] for n, r in (("ring", ring), ("line", line)) if "support_ids" in r}
    clusters = {}
    for k, v in sorted(local["clusters"].items()):
        same = next((n for n, s in shapes.items() if set(s) == set(v)), None)
        clusters[k] = {"ids": v, "same_as": same}
    signature_groups = dict(shapes)
    for k, cl in clusters.items():
        if cl["same_as"] is None:
            signature_groups[f"local_{k}"] = cl["ids"]
    return {"clusters": clusters, "shape_supports": shapes, "signature_groups": signature_groups,
            "ring": ring, "line": line, "noise": local["noise"]}
