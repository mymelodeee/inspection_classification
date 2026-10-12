"""E07 lift-pin (삼발이) synthetic fixture (stdlib only, no production code, deterministic, seed=None).
Usage: python gen_e07_lift_pin.py -> e07_lift_pin.json beside this file.

Standard frame: mm, wafer-center origin, +X right, +Y up, notch DOWN (6 o'clock), R=150.
Clock angle theta = degrees(atan2(x, y)) mod 360 (0=12h, 90=3h, clockwise). Harmonics use theta in radian.

TEST-ONLY template (NOT an in-house value, plan E07 / 8.2): nominal radius 60 mm, phase 0 deg,
positions 0/120/240 deg, angular_tolerance 10 deg, radial_tolerance 5 mm, min_support_per_lobe 3.

Lobe construction (hand-derivable): a lobe at clock angle phi and radius r is built in the local
(u = radial, v = clockwise tangential) frame: point = (r+u)*(sin phi, cos phi) + v*(cos phi, -sin phi),
whose clock angle is exactly phi + atan2(v, r+u). The standard 5-point lobe uses offsets
(0,0), (+1.5,0), (-1.5,0), (0,+1.5), (0,-1.5): centroid = (r sin phi, r cos phi) exactly, all points
within 1.5 mm (< 2 mm) of the centroid, three points at angle phi and two at phi +- alpha_r,
alpha_r = atan(1.5 / r). Hence for one 5-point lobe: sum_j exp(i k theta_j) = exp(i k phi) * (3 + 2 cos(k alpha_r)).

Harmonics (plan 8.2): z_k = sum(w_j exp(i k theta_j)) / sum(w_j), A_k = |z_k|, phase_3 = angle(z_3)/3.
  equal_per_lobe: one term per lobe at the lobe-centroid clock angle, equal weight (primary, plan 9 harmonic_weighting).
  point_weighted: one term per defect (sensitivity only).
Values below are re-derived with plain math, independent of production code.
"""
import cmath
import json
import math
import os

R = 150.0
T_RADIUS, T_PHASE, T_POS = 60.0, 0.0, (0.0, 120.0, 240.0)
T_ANG_TOL, T_RAD_TOL, T_MIN_SUPPORT = 10.0, 5.0, 3
OFF5 = [(0.0, 0.0), (1.5, 0.0), (-1.5, 0.0), (0.0, 1.5), (0.0, -1.5)]
OFF15 = [(u, v) for u in (-1.5, 0.0, 1.5) for v in (-3.0, -1.5, 0.0, 1.5, 3.0)]  # 3 x 5 grid blob
r9 = lambda v: round(v, 9) + 0.0  # + 0.0 turns -0.0 into 0.0


def clock(x, y):
    return math.degrees(math.atan2(x, y)) % 360.0


def wrap(d, period):  # into (-period/2, period/2]
    w = (d + period / 2.0) % period - period / 2.0
    return period / 2.0 if w == -period / 2.0 else w


def lobe_points(phi, r, offsets):
    s, c = math.sin(math.radians(phi)), math.cos(math.radians(phi))
    return [((r + u) * s + v * c, (r + u) * c - v * s) for u, v in offsets]


def harmonics(angles_deg):
    out = {}
    for k in (1, 2, 3):
        z = sum(cmath.exp(1j * k * math.radians(a)) for a in angles_deg) / len(angles_deg)
        out["A%d" % k] = r9(abs(z))
        if k == 3:
            out["phase_3_deg"] = r9(math.degrees(cmath.phase(z)) / 3.0) if abs(z) > 1e-12 else None
    return out


def build(prefix, lobe_specs, bins_offset=0):
    """lobe_specs: list of (label, phi, r, offsets). Returns points, lobes."""
    pts, lobes, n = [], [], 0
    for label, phi, r, offs in lobe_specs:
        ids = []
        for x, y in lobe_points(phi, r, offs):
            n += 1
            assert math.hypot(x, y) <= R
            pid = "%s%02d" % (prefix, n)
            ids.append(pid)
            pts.append(dict(id=pid, x=r9(x), y=r9(y), bin="B%d" % ((n - 1 + bins_offset) % 3 + 1), lobe=label))
        xy = [(p["x"], p["y"]) for p in pts if p["lobe"] == label]
        cx, cy = sum(a for a, _ in xy) / len(xy), sum(b for _, b in xy) / len(xy)
        ca = clock(cx, cy)
        cmean = math.degrees(cmath.phase(sum(cmath.exp(1j * math.radians(clock(a, b))) for a, b in xy))) % 360
        nearest = min(T_POS, key=lambda t: abs(wrap(ca - (t + T_PHASE), 360)))
        ang_res = wrap(ca - (nearest + T_PHASE), 360)
        rad_res = math.hypot(cx, cy) - T_RADIUS
        lobes.append(dict(
            label=label, n_support=len(ids), support_ids=ids,
            centroid_xy_mm=[r9(cx), r9(cy)], centroid_clock_deg=r9(ca if abs(ca - 360) > 1e-9 else 0.0),
            centroid_radius_mm=r9(math.hypot(cx, cy)),
            mean_point_radius_mm=r9(sum(math.hypot(a, b) for a, b in xy) / len(xy)),
            circular_mean_point_clock_deg=r9(cmean if abs(cmean - 360) > 1e-9 else 0.0),
            max_point_distance_from_centroid_mm=r9(max(math.dist((a, b), (cx, cy)) for a, b in xy)),
            nearest_template_position_deg=nearest,
            angular_residual_deg=r9(ang_res), within_angular_tolerance=abs(ang_res) <= T_ANG_TOL,
            radial_residual_mm=r9(rad_res), within_radial_tolerance=abs(rad_res) <= T_RAD_TOL,
            support_ge_min=len(ids) >= T_MIN_SUPPORT))
    return pts, lobes


def features(pts, lobes):
    eq = harmonics([l["centroid_clock_deg"] for l in lobes])
    pw = harmonics([clock(p["x"], p["y"]) for p in pts])
    ph = eq["phase_3_deg"]
    angs = sorted(l["centroid_clock_deg"] for l in lobes)
    gaps = [r9((angs[(i + 1) % len(angs)] - angs[i]) % 360) for i in range(len(angs))] if len(angs) > 1 else []
    return dict(
        n_points=len(pts), n_lobes=len(lobes),
        lobe_circular_gaps_deg=gaps,
        harmonics_equal_per_lobe=eq, harmonics_point_weighted=pw,
        phase_residual_deg=(r9(wrap(ph - T_PHASE, 120.0)) if ph is not None else None),
        phase_residual_rule="wrap(phase_3 - template_phase) into (-60, 60] (120-deg periodic)")


def alpha(r):
    return math.atan(1.5 / r)


FULL = dict(known=True, inspected="full disc r<=150 (synthetic)", uncovered_regions=[])
cases = {}

# (1) LP-IDEAL
pts, lobes = build("LI", [("L000", 0, 60, OFF5), ("L120", 120, 60, OFF5), ("L240", 240, 60, OFF5)])
a = alpha(60)
assert abs(harmonics([clock(p["x"], p["y"]) for p in pts])["A3"] - (3 + 2 * math.cos(3 * a)) / 5) < 1e-9
cases["LP-IDEAL"] = dict(
    points=pts, lobes=lobes, coverage=FULL, features=features(pts, lobes),
    template_checks=dict(three_distinct_lobes=True, spacing_120_within_tol=True, radius_within_tol=True,
                         phase_within_tol=True, coverage_includes_all_positions=True),
    expected=dict(feature_status="matched", match_type="threefold_match", n_lobes_matched=3,
                  signature_group_support_ids="LI01..LI15 (union of the 3 lobes)",
                  wording="geometric 3-fold template match (TEST template); NOT a cause/equipment confirmation (C19)"),
    derivation="3 lobes x 5 pts at r=60, clock 0/120/240. Centroids exactly (0,60), (51.961524,-30), (-51.961524,-30). "
               "equal_per_lobe: z1=z2=(1+w+w^2)/3=0 (w=exp(i2pi/3)), z3=1 -> A1=A2=0, A3=1, phase_3=0. "
               "point_weighted: alpha=atan(1.5/60)=0.024994793 rad; A3=(3+2cos(3alpha))/5, A1=A2=0 (lobe sum cancels). "
               "Mean point radius=(60+61.5+58.5+2*sqrt(3600+2.25))/5=60.0075 vs centroid radius 60.")

# (2) LP-SINGLE-BLOB: 15 points as a 3x5 grid around (0,60)
pts, lobes = build("SB", [("L000", 0, 60, OFF15)])
cases["LP-SINGLE-BLOB"] = dict(
    points=pts, lobes=lobes, coverage=FULL, features=features(pts, lobes),
    template_checks=dict(three_distinct_lobes=False, spacing_120_within_tol=None, radius_within_tol=True,
                         phase_within_tol=True, coverage_includes_all_positions=True),
    expected=dict(feature_status="no_match", match_type=None, n_lobes_matched=1,
                  reason="single lobe (1 of 3 template positions); positions 120/240 inspected and empty",
                  must_not=["matched", "threefold_match", "partial_match", "verdict from A3 alone"],
                  note="A3 (equal_per_lobe) = 1 and point_weighted A3 ~ 0.99 are as large as LP-IDEAL; A1 = 1 shows "
                       "one-sided concentration. Plan 8.2: A3 threshold alone is forbidden."),
    derivation="15 pts = grid u in {-1.5,0,1.5} (radial) x v in {-3,-1.5,0,1.5,3} (tangential) around (0,60); max offset "
               "sqrt(1.5^2+3^2)=3.354 mm; symmetric in v -> centroid (0,60), clock 0. Point angle = atan2(v, 60+u). "
               "equal_per_lobe (1 lobe at 0): z1=z2=z3=1 -> A1=A2=A3=1, phase_3=0 (phase residual 0: phase alone cannot reject). "
               "point_weighted: A_k=(1/15)*sum cos(k*atan2(v,60+u)) (imaginary parts cancel by symmetry).")

# (3) LP-TWO-LOBES
pts, lobes = build("TL", [("L000", 0, 60, OFF5), ("L120", 120, 60, OFF5)])
cases["LP-TWO-LOBES"] = dict(
    points=pts, lobes=lobes, coverage=FULL, features=features(pts, lobes),
    template_checks=dict(three_distinct_lobes=False, spacing_120_within_tol=True, radius_within_tol=True,
                         phase_within_tol=True, coverage_includes_all_positions=True),
    expected=dict(feature_status="candidate", match_type="partial_match", n_lobes_matched=2,
                  matched_positions_deg=[0, 120], missing_positions_deg=[240],
                  missing_position_status="absent_in_inspected_area",
                  must_not=["matched", "threefold_match", "report as 3-position template satisfied"]),
    derivation="Lobes at 0 and 120 (10 pts). equal_per_lobe: z1=(1+exp(i2pi/3))/2 -> A1=|cos(pi/3)|=0.5; "
               "z2=(1+exp(i4pi/3))/2 -> A2=0.5; z3=(1+exp(i2pi))/2=1 -> A3=1, phase_3=0. "
               "point_weighted: A1=0.5*(3+2cos(alpha))/5, A2=0.5*(3+2cos(2alpha))/5, A3=(3+2cos(3alpha))/5, alpha=atan(1.5/60).")

# (4) LP-WRONG-RADIUS
pts, lobes = build("WR", [("L000", 0, 90, OFF5), ("L120", 120, 90, OFF5), ("L240", 240, 90, OFF5)])
cases["LP-WRONG-RADIUS"] = dict(
    points=pts, lobes=lobes, coverage=FULL, features=features(pts, lobes),
    template_checks=dict(three_distinct_lobes=True, spacing_120_within_tol=True, radius_within_tol=False,
                         phase_within_tol=True, coverage_includes_all_positions=True),
    expected=dict(feature_status="no_match", match_type=None, n_lobes_matched=0,
                  n_points_in_template_radius_band=0,
                  reason="radius mismatch: lobe radial residual +30 mm > 5 mm (no point within 60+-5 mm)",
                  must_not=["matched", "candidate"]),
    derivation="Same geometry as LP-IDEAL at r=90. Harmonics are identical to LP-IDEAL for equal_per_lobe "
               "(A1=A2=0, A3=1, phase_3=0): harmonics carry no radius information. point_weighted A3=(3+2cos(3*atan(1.5/90)))/5. "
               "Point radii in [88.5, 91.5] -> 0 points in template band [55, 65].")

# (5) LP-WRONG-PHASE: 40/160/280
pts, lobes = build("WP", [("L040", 40, 60, OFF5), ("L160", 160, 60, OFF5), ("L280", 280, 60, OFF5)])
cases["LP-WRONG-PHASE"] = dict(
    points=pts, lobes=lobes, coverage=FULL, features=features(pts, lobes),
    template_checks=dict(three_distinct_lobes=True, spacing_120_within_tol=True, radius_within_tol=True,
                         phase_within_tol=False, coverage_includes_all_positions=True),
    expected=dict(feature_status="no_match", match_type=None, n_lobes_matched=0,
                  reason="phase mismatch: phase residual 40 deg > 10 deg (3-fold shape exists, template phase not met)",
                  must_not=["matched", "threefold_match"],
                  note="Phase residual is relative to the TEST template frame (notch_down clock). Shape-only "
                       "3-fold symmetry may be reported as a descriptive feature, not as template match."),
    derivation="Lobes at 40/160/280, r=60. equal_per_lobe: z3=exp(i*3*40deg)=exp(i*120deg) -> A3=1, "
               "phase_3=120/3=40 deg; residual wrap(40-0, 120)=40. z1=z2=0 (3 equally spaced). Each lobe is 40 deg from "
               "the nearest template position (0->40, 120->160, 240->280) > 10 deg tolerance.")

# (6) LP-UNCOVERED: 240 position not inspected
UNCOV = dict(known=True, inspected="full disc r<=150 EXCEPT uncovered_regions (synthetic assumption)",
             uncovered_regions=[dict(type="annular_sector", clock_deg_interval=[220, 260], radius_mm_interval=[40, 80],
                                     closed="left", note="contains the whole template window 240+-10 deg x 60+-5 mm")],
             representation_note="fixture-local coverage description; production coverage schema is undecided (TBD T-04)")
pts, lobes = build("UC", [("L000", 0, 60, OFF5), ("L120", 120, 60, OFF5)])
cases["LP-UNCOVERED"] = dict(
    points=pts, lobes=lobes, coverage=UNCOV, features=features(pts, lobes),
    template_checks=dict(three_distinct_lobes="unknown", spacing_120_within_tol=True, radius_within_tol=True,
                         phase_within_tol=True, coverage_includes_all_positions=False),
    expected=dict(feature_status="candidate", match_type="partial_match", n_lobes_matched=2,
                  matched_positions_deg=[0, 120], unobserved_positions_deg=[240],
                  missing_position_status="not_inspected (unknown, NOT absent)",
                  coverage_flag="incomplete_coverage",
                  must_not=["matched", "no_match", "report position 240 as absent"],
                  decision_pending="candidate vs insufficient_data for a 2-observed/1-uninspected case is not fixed by "
                                   "the plan (16.2 says unknown required condition -> insufficient_data). Fixture uses "
                                   "candidate + incomplete_coverage; the hard requirements are must_not and coverage_flag."),
    derivation="Point set identical in geometry to LP-TWO-LOBES (IDs differ), so all features equal LP-TWO-LOBES. "
               "Only the coverage input differs: the 240-deg window lies in an uninspected region, so its emptiness is "
               "not evidence of absence.")

doc = dict(
    _meta=dict(fixture="E07-lift-pin", oracle_version="e07-lift-pin-1", synthetic=True, seed=None,
               generator="gen_e07_lift_pin.py", units="mm", wafer_radius_mm=R,
               frame="standard: center origin, +X right, +Y up, notch DOWN",
               clock_angle="degrees(atan2(x, y)) mod 360 (0=12h, clockwise); harmonics use radians",
               plan_links=["E07", "C09", "C19", "P2-05", "P3-01", "plan 8.2"],
               scope="synthetic template-geometry oracle; NOT a real equipment template, NOT an adapter validation, "
                     "NOT evidence of any process/equipment cause",
               bins="B1/B2/B3 cycle by point index within each case",
               template=dict(TEST_ONLY=True, not_in_house_value=True, frame="notch_down", template_id="E07-TEST",
                             nominal_radius_mm=T_RADIUS, radius_band_mm=[T_RADIUS - T_RAD_TOL, T_RADIUS + T_RAD_TOL],
                             phase_deg=T_PHASE, positions_deg=list(T_POS), expected_lobes=3, spacing_deg=120,
                             angular_tolerance_deg=T_ANG_TOL, radial_tolerance_mm=T_RAD_TOL,
                             min_support_per_lobe=T_MIN_SUPPORT, harmonic_weighting="equal_per_lobe",
                             partial_match="candidate_only",
                             profile_key_note="maps to signatures.lift_pin.* (radius_band_mm = nominal +- radial_tolerance)"),
               lobe_definition="lobes are given by construction (support_ids); the lobe-finding algorithm is not fixed here",
               a3_observation="equal_per_lobe A3 = 1 in EVERY case; A3 alone discriminates none of them (plan 8.2)",
               tolerances=dict(coordinate_mm=1e-6, angle_deg=1e-6, harmonic=1e-6),
               status_vocab="feature_status per plan 16.2; match_type per E07 (threefold_match / partial_match)"),
    cases=cases)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e07_lift_pin.json"), "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=1, ensure_ascii=False)
    f.write("\n")
