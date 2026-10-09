"""Radial density and Clark-Evans test. Coverage unknown -> null + reason (never full-disc assumed).

`inspected_radius_mm` is the radius of a circular inspected window about the wafer center,
supplied by the caller from verified coverage. None means coverage unknown (TBD.md T-05, option a).
"""
import math

import numpy as np
from scipy.spatial import cKDTree


def radial_density(r_mm, edges_mm, inspected_radius_mm=None, close_last=False):
    """{"rows": [...], "n_outside_edges": k}. Counts per annulus [e_i, e_{i+1}) always; area/density
    only when coverage is known. Points outside all edges are counted in n_outside_edges (not lost).
    close_last=True makes the last bin [lo, hi] (closed), e.g. so that r = R is counted.

    Area is the annulus intersected with the inspected disk: pi*(min(hi,Rc)^2 - min(lo,Rc)^2).
    Zero area -> density None (not 0). Count 0 with positive area -> density 0.0.
    An annulus containing points beyond the inspected disk gets density None (window violated).
    """
    r = np.asarray(r_mm, float)
    rows = []
    last = len(edges_mm) - 2
    for k, (lo, hi) in enumerate(zip(edges_mm[:-1], edges_mm[1:])):
        closed = close_last and k == last
        inbin = (r >= lo) & ((r <= hi) if closed else (r < hi))
        n = int(inbin.sum())
        row = {"r_lo_mm": lo, "r_hi_mm": hi, "closed": "both" if closed else "left", "count": n, "area_mm2": None, "density_per_mm2": None,
               "reason": "coverage_unknown"}
        if inspected_radius_mm is not None:
            n_out = int((inbin & (r > inspected_radius_mm)).sum())
            area = math.pi * (min(hi, inspected_radius_mm) ** 2 - min(lo, inspected_radius_mm) ** 2)
            row["area_mm2"], row["reason"], row["n_outside_window"] = area, None, n_out
            if n_out:
                row["reason"] = "points_outside_inspected_window"
            elif area > 0:
                row["density_per_mm2"] = n / area
            else:
                row["reason"] = "zero_inspected_area"
        rows.append(row)
    above = (r > edges_mm[-1]) if close_last else (r >= edges_mm[-1])
    n_outside_edges = int(((r < edges_mm[0]) | above).sum())
    return {"rows": rows, "n_outside_edges": n_outside_edges}


def clark_evans(x_mm, y_mm, inspected_radius_mm=None, nsim=999, seed=None):
    """Clark-Evans index R = mean NN distance / (0.5/sqrt(lambda)), lambda = N / window area.

    Conditional Monte Carlo p-value (two-sided): N uniform points in the same disk window.
    No boundary correction is applied; R is a descriptive index for a finite window (plan 7.2).
    Returns status insufficient_data for coverage unknown or N < 2 (no p-value invented).
    """
    n = len(x_mm)
    if inspected_radius_mm is None:
        return {"calc_status": "insufficient_data", "reason": "coverage_unknown", "n": n}
    if n < 2:
        return {"calc_status": "insufficient_data", "reason": "need_at_least_2_points", "n": n}
    if seed is None:
        return {"calc_status": "insufficient_data", "reason": "seed_required_for_reproducibility", "n": n}
    if inspected_radius_mm <= 0 or nsim < 1:
        return {"calc_status": "insufficient_data", "reason": "invalid_window_or_nsim", "n": n}
    if (np.hypot(x_mm, y_mm) > inspected_radius_mm).any():
        return {"calc_status": "insufficient_data", "reason": "points_outside_inspected_window", "n": n}
    area = math.pi * inspected_radius_mm ** 2
    expected = 0.5 / math.sqrt(n / area)

    def mean_nn(pts):
        d, _ = cKDTree(pts).query(pts, k=2)
        return float(d[:, 1].mean())

    obs = mean_nn(np.column_stack([x_mm, y_mm]))
    rng = np.random.default_rng(seed)
    sims = np.empty(nsim)
    for i in range(nsim):
        rr = inspected_radius_mm * np.sqrt(rng.random(n))
        th = rng.random(n) * 2 * math.pi
        sims[i] = mean_nn(np.column_stack([rr * np.cos(th), rr * np.sin(th)]))
    lo = (1 + (sims <= obs).sum()) / (nsim + 1)
    hi = (1 + (sims >= obs).sum()) / (nsim + 1)
    return {"calc_status": "computed", "n": n, "mean_nn_mm": obs, "expected_nn_mm": expected,
            "index_R": obs / expected, "p_two_sided": min(1.0, 2 * min(lo, hi)),
            "nsim": nsim, "seed": seed, "window": f"disk r={inspected_radius_mm} mm",
            "boundary_correction": "none"}
