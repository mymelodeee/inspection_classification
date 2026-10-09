"""Line measurement (PCA) and candidate classification from profile thresholds (TBD T-21).

Eigenvalue ratio alone never decides "line": two distant blobs are elongated too, so continuity
(largest gap along the axis relative to length) and width are part of the rule.
"""
import numpy as np


def measure_line(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return {"calc_status": "insufficient_data", "reason": "need >= 3 points", "n": len(x)}
    pts = np.column_stack([x, y])
    c = pts.mean(axis=0)
    u, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    if s[0] == 0:
        return {"calc_status": "insufficient_data", "reason": "all points identical", "n": len(x)}
    d = vt[0]
    if d[0] < 0 or (d[0] == 0 and d[1] < 0):
        d = -d
    along = (pts - c) @ d
    across = (pts - c) @ np.array([-d[1], d[0]])
    srt = np.sort(along)
    length = float(srt[-1] - srt[0])
    p5, p95 = np.percentile(across, [5, 95])
    return {"calc_status": "computed", "n": len(x), "direction_deg": float(np.degrees(np.arctan2(d[1], d[0])) % 180.0),
            "length_mm": length, "width_mm": float(p95 - p5),            # P95-P5 of normal distance (as ring)
            "rms_residual_mm": float(np.sqrt((across ** 2).mean())),
            "max_gap_mm": float(np.diff(srt).max()),
            "eigen_ratio": float(s[1] ** 2 / s[0] ** 2),                 # minor/major variance, descriptive only
            "centroid_mm": [float(c[0]), float(c[1])]}


def classify_line(x, y, rule):
    """rule = profile.shapes.line. Shape candidate only; "matched" appears only when calibrated."""
    if not rule.enabled:
        return {"feature_status": "disabled"}
    x = np.asarray(x, float)
    if len(x) < rule.min_points:
        return {"feature_status": "insufficient_data", "reason": "fewer_than_min_points", "n": len(x)}
    m = measure_line(x, y)
    if m["calc_status"] != "computed":
        return {"feature_status": "insufficient_data", "reason": m["reason"], "n": len(x)}
    if m["length_mm"] <= 0:
        return {"feature_status": "insufficient_data", "reason": "zero_length", "n": len(x)}
    rel_w, gap_r = m["width_mm"] / m["length_mm"], m["max_gap_mm"] / m["length_mm"]
    out = {"n": len(x), "relative_width": rel_w, "gap_ratio": gap_r, "measurement": m}
    if gap_r > rule.max_gap_ratio:
        return {**out, "feature_status": "no_match", "reason": "not_continuous"}
    if rel_w > rule.max_relative_width:
        return {**out, "feature_status": "no_match", "reason": "too_wide_for_line"}
    return {**out, "feature_status": "matched" if rule.calibrated else "candidate", "label": "linear"}
