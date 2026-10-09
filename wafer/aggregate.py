"""Count / bin / clock-sector / zone aggregation on a standardized defect table.

Input: parallel sequences defect_id, x_mm, y_mm, bin (standard frame, mm).
Points outside the wafer (r > R) are excluded with a reason, never clipped.
"""
import numpy as np

from . import geometry as g


def included_mask(x_mm, y_mm, profile):
    """Single definition of an included point: r <= R (r = R included, plan 16.3-8), no clipping."""
    r = g.r_mm(x_mm, y_mm)
    R = profile.wafer_radius_mm
    return g.in_wafer(r, R) if R is not None else np.ones(np.shape(r), bool)


def aggregate(defect_id, x_mm, y_mm, bins, profile, n_parsed=None):
    ids = np.asarray(defect_id, dtype=object)
    x = np.asarray(x_mm, dtype=float)
    y = np.asarray(y_mm, dtype=float)
    bins = np.asarray([b if b else "unknown" for b in bins], dtype=object)
    n_parsed = len(ids) if n_parsed is None else n_parsed

    R = profile.wafer_radius_mm
    r = g.r_mm(x, y)
    inside = included_mask(x, y, profile)
    excluded = [{"defect_id": i, "reason": "outside_wafer"} for i in ids[~inside]]
    ids, x, y, bins, r = ids[inside], x[inside], y[inside], bins[inside], r[inside]
    out = {
        "n_parsed": n_parsed,
        "n_included": int(len(ids)),
        "n_excluded": len(excluded),
        "excluded": excluded,
        "bin_totals": {b: int((bins == b).sum()) for b in sorted(set(bins))},
    }

    # Clock sectors need a verified center exclusion radius; otherwise None (not 0).
    cx = profile.clock.center_exclusion_radius_mm
    out["boundary_tolerance_deg"] = profile.clock.boundary_tolerance_deg
    if cx is None:
        out["center"], out["sectors_clock"], out["boundary_ambiguous"] = None, None, None
        out["sectors_clock_tolerant"], out["n_multi_sector"] = None, None
    else:
        center = g.is_center(r, cx)
        theta = g.theta_clock_deg(x, y)
        hour = g.clock_hour(theta)
        out["center"] = int(center.sum())
        out["sectors_clock"] = {h: int(((hour == h) & ~center).sum()) for h in range(1, 13)}
        tol = profile.clock.boundary_tolerance_deg
        near = g.near_sector_boundary(theta, tol) & ~center
        nb = g.neighbor_hour(theta, tol)
        tolerant = dict(out["sectors_clock"])
        for h in nb[~center & (nb > 0)]:
            tolerant[int(h)] += 1
        # tolerant counts: a point within +-tol of a boundary is also counted in the adjacent sector
        # sum(tolerant) = N_included - center + n_multi_sector; it is NOT a partition (unique points: N_included)
        out["sectors_clock_tolerant"] = tolerant
        out["n_multi_sector"] = int(((nb > 0) & ~center).sum())
        out["boundary_ambiguous"] = {  # flag only; sector counts above are unchanged
            "count": int(near.sum()), "ids": ids[near].tolist(),
            "by_hour": {h: int(((hour == h) & near).sum()) for h in range(1, 13)}}

    # Zones: only enabled ones; sets of IDs so overlaps never inflate totals.
    z, zones = profile.zones, {}
    for name in ("E1", "E2"):
        zc = getattr(z, name)
        if zc.enabled:
            v = g.edge_distance_mm(r, R)  # E1/E2 are edge-distance zones (profile enforces the metric)
            zones[name] = ids[g.in_interval(v, *zc.interval_mm)].tolist()
    if z.zone_8inch_inside.enabled:
        zones["inner"] = ids[g.in_interval(r, *z.zone_8inch_inside.interval_mm)].tolist()
    if z.zone_8inch_boundary.enabled:
        b = z.zone_8inch_boundary
        zones["band"] = ids[g.in_band(r, b.center_radius_mm, b.band_width_mm)].tolist()
    out["zones"] = zones
    out["zone_union_unique"] = len({i for s in zones.values() for i in s})
    return out
