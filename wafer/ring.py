"""Ring/band measurement: circle fit and angular coverage.

ring thickness here = P95 - P5 (5th-95th percentile range, linear interpolation) of the point distances about the ring center (user decision 2026-10-09; robust to outliers). Extremes are reported separately as r_min/r_max. It is a
measured quantity of a ring pattern, unrelated to zone_8inch_boundary (TBD.md T-05).
Classification thresholds (ring / arc / not_ring) are NOT set here (TBD).
"""
import numpy as np

from . import geometry as g


def fit_circle(x, y):
    """Algebraic (Kasa) least-squares circle fit -> (cx, cy, radius), or None if under-determined
    (fewer than 3 points or collinear). Known limit: biased on short arcs / thick bands
    (TBD.md T-14); only full-ring fits are validated."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return None
    A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    if np.linalg.matrix_rank(A) < 3:
        return None
    b = x ** 2 + y ** 2
    (cx, cy, c), *_ = np.linalg.lstsq(A, b, rcond=None)
    return float(cx), float(cy), float(np.sqrt(c + cx ** 2 + cy ** 2))


def angular_coverage(x, y, center=(0.0, 0.0), tol_deg=0.0):
    """Clock-angle occupancy about `center`: max_gap_deg, span_deg (=360-max_gap), occupied clock hours
    (strict) and occupied_hours_tolerant (a point within +-tol_deg of a sector boundary also occupies the
    adjacent hour). max_gap_deg / span_deg are always strict (tolerance is not applied to them, T-15)."""
    dx, dy = np.asarray(x, float) - center[0], np.asarray(y, float) - center[1]
    if len(dx) == 0:
        return {"max_gap_deg": None, "span_deg": None, "occupied_hours": [], "occupied_hours_tolerant": []}
    theta = g.theta_clock_deg(dx, dy)
    th = np.sort(theta)
    gaps = np.diff(np.concatenate([th, [th[0] + 360.0]]))
    mg = float(gaps.max()) if len(th) > 1 else 360.0
    hours = sorted({int(h) for h in np.atleast_1d(g.clock_hour(theta))})
    nb = {int(h) for h in np.atleast_1d(g.neighbor_hour(theta, tol_deg)) if h > 0}
    return {"max_gap_deg": mg, "span_deg": 360.0 - mg, "occupied_hours": hours,
            "occupied_hours_tolerant": sorted(set(hours) | nb)}


def measure_ring(x, y, center=None, tol_deg=0.0):
    """Fit (or take) the center, then report radius, inner/outer radius, thickness, diameter, coverage."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if center is None:
        fit = fit_circle(x, y)
        if fit is None:
            return {"calc_status": "insufficient_data", "reason": "need >= 3 non-collinear points to fit a center"}
        cx, cy = fit[:2]
    elif len(x) == 0:
        return {"calc_status": "insufficient_data", "reason": "no points"}
    else:
        cx, cy = center
    d = np.hypot(x - cx, y - cy)
    p5, p95 = np.percentile(d, [5, 95])
    return {"calc_status": "computed", "center_x_mm": float(cx), "center_y_mm": float(cy),
            "center_radius_mm": float(d.mean()), "r_min_mm": float(d.min()), "r_max_mm": float(d.max()),
            "ring_thickness_mm": float(p95 - p5), "radial_extent_mm": float(d.max() - d.min()), "diameter_mm": float(2 * d.mean()),
            **angular_coverage(x, y, (cx, cy), tol_deg)}


def angular_occupancy(x, y, center, bin_deg):
    """Fraction of bin_deg-wide clock-angle bins about `center` that contain at least one point."""
    th = g.theta_clock_deg(np.asarray(x, float) - center[0], np.asarray(y, float) - center[1])
    n_bins = int(np.ceil(360.0 / bin_deg))
    # round away float noise (~1e-14 deg) so points exactly on a bin edge fall in a deterministic bin
    return len({int(round(float(t), 9) // bin_deg) % n_bins for t in th}) / n_bins  # 360.0 wraps to bin 0


def classify_ring(x, y, rule, center=None, tol_deg=0.0):
    """tol_deg only fills measurement["occupied_hours_tolerant"]; the label is decided by occupancy bins
    (whether tolerance should enter the decision is an open question, TBD T-15).

    Candidate ring/arc classification from profile thresholds (rule = profile.shapes.ring).

    center=None: the center is fitted and only a full ring can be reported (partial-arc fits are
    biased, TBD T-14). center given: an arc candidate is allowed. Pattern match is a shape candidate
    only, never a cause (C19); "matched" appears only when rule.calibrated is True.
    """
    if not rule.enabled:
        return {"feature_status": "disabled"}
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < rule.min_points:
        return {"feature_status": "insufficient_data", "reason": "fewer_than_min_points", "n": len(x)}
    m = measure_ring(x, y, center, tol_deg)
    if m["calc_status"] != "computed":
        return {"feature_status": "insufficient_data", "reason": m["reason"], "n": len(x)}
    c = (m["center_x_mm"], m["center_y_mm"])
    occ = angular_occupancy(x, y, c, rule.occupancy_bin_deg)
    if m["center_radius_mm"] <= 0:
        return {"feature_status": "insufficient_data", "reason": "zero_radius", "n": len(x)}
    rel = m["ring_thickness_mm"] / m["center_radius_mm"]
    out = {"n": len(x), "occupancy": occ, "relative_thickness": rel, "measurement": m,
           "center_known": center is not None}
    hit = "matched" if rule.calibrated else "candidate"
    if rel > rule.max_relative_thickness:
        return {**out, "feature_status": "no_match", "reason": "band_too_thick_for_ring"}
    if occ >= rule.ring_min_occupancy:
        return {**out, "feature_status": hit, "label": "ring"}
    if occ >= rule.arc_min_occupancy:
        if center is None:
            return {**out, "feature_status": "insufficient_data", "reason": "arc_requires_known_center"}
        return {**out, "feature_status": hit, "label": "arc"}
    if center is None:
        return {**out, "feature_status": "insufficient_data", "reason": "arc_requires_known_center"}
    return {**out, "feature_status": "no_match", "reason": "low_angular_occupancy"}
