"""Lift-pin (3-fold) template match (plan 8.2, E07). Shape/template evidence only, never a cause (C19).

Uses the verified profile template (signatures.lift_pin). A lobe counts only when its window
[pos +- angular_tolerance] x [radius band) holds >= min_support_per_lobe points, is denser than the
rest of the band by >= min_lobe_contrast, and its mean radius is within radial_tolerance_mm of the
band center. The 3rd harmonic A3 is reported as a feature only and never decides the label.
Absence is only concluded where coverage is known (plan 16.2: unknown -> insufficient_data).
"""
import numpy as np

from . import geometry as g


def _circ_diff(a, b, period=360.0):
    """Signed smallest difference a - b, in (-period/2, period/2]."""
    d = (np.asarray(a, float) - b + period / 2.0) % period - period / 2.0
    return np.where(d == -period / 2.0, period / 2.0, d)


def _harmonics(theta_deg):
    t = np.radians(np.asarray(theta_deg, float))
    z = {k: complex(np.exp(1j * k * t).mean()) for k in (1, 2, 3)}
    out = {f"A{k}": float(abs(v)) for k, v in z.items()}
    out["phase_3_deg"] = float(np.degrees(np.angle(z[3])) / 3.0 % 120.0) if abs(z[3]) > 1e-9 else None
    return out


def _arc_overlap(a0, a1, b0, b1):
    """Do clock arcs [a0, a1] and [b0, b1) (degrees, may wrap) overlap?"""
    la, lb = (a1 - a0) % 360.0, (b1 - b0) % 360.0 or 360.0
    return (b0 - a0) % 360.0 <= la or (a0 - b0) % 360.0 < lb


def _window_coverage(pos, tol, lo, hi, uncovered):
    if uncovered is None:
        return "unknown"
    for reg in uncovered:
        b0, b1 = reg["clock_deg_interval"]
        ra, rb = reg["radius_mm_interval"]
        if _arc_overlap(pos - tol, pos + tol, b0, b1) and ra < hi and lo < rb:
            return "not_inspected"   # any overlap with an uninspected region makes the window unreliable
    return "inspected"


def _lobes(th, r, band, positions, tmpl):
    lo, hi = tmpl.radius_band_mm
    tol, n_band = tmpl.angular_tolerance_deg, int(band.sum())
    in_any = np.zeros_like(band)
    wins = []
    for pos in positions:
        w = band & (np.abs(_circ_diff(th, pos)) <= tol)
        in_any |= w
        wins.append(w)
    bg_deg = 360.0 - 2 * tol * len(positions)
    bg_density = (n_band - int(in_any.sum())) / bg_deg if bg_deg > 0 else 0.0
    lobes = []
    for pos, w in zip(positions, wins):
        n = int(w.sum())
        dens = n / (2 * tol) if tol > 0 else float("inf")
        contrast = float("inf") if bg_density == 0 else dens / bg_density
        lb = {"position_deg": pos, "n": n, "contrast": contrast, "window": w}
        if n >= tmpl.min_support_per_lobe:
            mean_dir = float(np.degrees(np.arctan2(np.sin(np.radians(th[w])).mean(),
                                                   np.cos(np.radians(th[w])).mean())) % 360.0)
            lb.update(mean_deg=mean_dir, phase_residual_deg=float(_circ_diff(mean_dir, pos)),
                      mean_radius_mm=float(r[w].mean()))
            radius_ok = abs(lb["mean_radius_mm"] - (lo + hi) / 2.0) <= tmpl.radial_tolerance_mm
            lb["present"] = bool(contrast >= tmpl.min_lobe_contrast and radius_ok)
            if not lb["present"]:
                lb["reason"] = "low_contrast_vs_band" if contrast < tmpl.min_lobe_contrast else "lobe_radius_off"
        else:
            lb["present"] = False
        lobes.append(lb)
    return lobes


def match_lift_pin(ids, x_mm, y_mm, tmpl, uncovered=None):
    """tmpl = profile.signatures.lift_pin. uncovered: list of not-inspected annular sectors
    [{"clock_deg_interval": [lo, hi], "radius_mm_interval": [lo, hi]}]; [] = full coverage known;
    None = coverage unknown.

    feature_status: disabled / insufficient_data / no_match / candidate / matched (matched only when
    tmpl.calibrated). match_type: threefold_match (every position) / partial_match (all but one).
    """
    if not tmpl.enabled:
        return {"feature_status": "disabled"}
    ids = list(ids)
    x, y = np.asarray(x_mm, float), np.asarray(y_mm, float)
    r, th = g.r_mm(x, y), g.theta_clock_deg(x, y)
    lo, hi = tmpl.radius_band_mm
    band = (r >= lo) & (r < hi)                      # default half-open rule [lo, hi) (CLAUDE.md 4.9)
    positions = [(tmpl.phase_deg + k * tmpl.spacing_deg) % 360.0 for k in range(tmpl.expected_lobes)]
    out = {"template_id": tmpl.template_id, "frame": tmpl.frame, "n_in_band": int(band.sum()),
           "positions_deg": positions, "lobes": [], "point_weighted": None}
    lobes = _lobes(th, r, band, positions, tmpl) if band.any() else [
        {"position_deg": p, "n": 0, "present": False, "window": band} for p in positions]
    for lb in lobes:
        w = lb.pop("window")
        lb["support_ids"] = [ids[i] for i in np.flatnonzero(w)]
        if not lb["present"]:
            lb["coverage"] = _window_coverage(lb["position_deg"], tmpl.angular_tolerance_deg, lo, hi, uncovered)
    out["lobes"] = lobes
    present = [lb for lb in lobes if lb["present"]]
    missing = [lb for lb in lobes if not lb["present"]]
    if band.any():
        out["point_weighted"] = _harmonics(th[band])        # descriptive only (plan 8.2)
    if present:
        out["lobe_weighted"] = _harmonics([lb["mean_deg"] for lb in present])   # equal weight per lobe

    if not missing:
        hit = "matched" if tmpl.calibrated else "candidate"
        return {**out, "feature_status": hit, "match_type": "threefold_match",
                "wording": "lift-pin template shape observed (not a cause)"}
    unknown = [lb for lb in missing if lb["coverage"] != "inspected"]
    if len(present) == len(positions) - 1:
        flag = {"not_inspected": "incomplete_coverage", "unknown": "coverage_unknown",
                "inspected": "inspected_empty"}[missing[0]["coverage"]]
        return {**out, "feature_status": "candidate", "match_type": "partial_match", "coverage_flag": flag}
    if unknown:   # cannot conclude absence where the window was not (known to be) inspected
        return {**out, "feature_status": "insufficient_data",
                "reason": "coverage_unknown" if any(lb["coverage"] == "unknown" for lb in unknown)
                else "template_positions_not_inspected"}
    if not band.any():
        return {**out, "feature_status": "no_match", "reason": "no_points_in_radius_band"}
    # inspected and not matched: is there a 3-fold structure at another phase? (reuse the lobe test)
    p3 = out["point_weighted"]["phase_3_deg"]
    reason = "fewer_than_two_template_lobes"
    if p3 is not None and len(present) == 0:
        shifted = [(p3 + k * tmpl.spacing_deg) % 360.0 for k in range(tmpl.expected_lobes)]
        if all(lb["present"] for lb in _lobes(th, r, band, shifted, tmpl)):
            reason = "phase_mismatch"
            out["phase_residual_deg"] = float(_circ_diff(p3, tmpl.phase_deg % 120.0, 120.0))
    return {**out, "feature_status": "no_match", "reason": reason}
