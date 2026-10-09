"""Ring/band fixtures (stdlib only, no production code, deterministic, seed=None).
Usage: python gen_ring_band.py  -> writes ring_band.json beside this file.

Construction: clock convention x = r*sin(t), y = r*cos(t) (t = clock angle, 0 = 12 oclock), plus center offset.
Radius pattern by point index k: [78, 80, 82, 80][k % 4]  -> ring centerline 80 mm, thickness 4 mm (r 78..82).
Definitions used by the oracle:
  center_radius_mm = arithmetic mean of point radii about the TRUE center
  band_width_mm    = r_max - r_min about the TRUE center (ring thickness, independent of the 100 mm zone)
  diameter_mm      = 2 * center_radius_mm
  max_gap_deg / span_deg = largest empty angular gap about the true center / 360 - gap
  occupied_hours   = clock sectors [h*30-15, h*30+15) containing >= 1 point
Expected values are derived from the construction analytically (hand derivations in comments); the
generator asserts them against values recomputed from the rounded coordinates (tol 1e-6) as a cross-check.
"""
import json
import math
import os

PAT = [78.0, 80.0, 82.0, 80.0]


def ring(angles, cx=0.0, cy=0.0, prefix="P"):
    pts = []
    for k, t in enumerate(angles):
        r = PAT[k % 4]
        rad = math.radians(t)
        pts.append(dict(id="%s%03d" % (prefix, k + 1), x=round(cx + r * math.sin(rad), 9),
                        y=round(cy + r * math.cos(rad), 9), construct_r_mm=r, construct_theta_deg=t))
    return pts


def measure(pts, cx, cy):
    rs, ts = [], []
    for p in pts:
        dx, dy = p["x"] - cx, p["y"] - cy
        rs.append(math.hypot(dx, dy))
        ts.append(math.degrees(math.atan2(dx, dy)) % 360)
    ts.sort()
    gaps = [((ts[(i + 1) % len(ts)] - ts[i]) % 360) or 360 for i in range(len(ts))]
    hours = sorted({(int(((t + 15) % 360) // 30) or 12) for t in ts})
    return dict(mean_r=sum(rs) / len(rs), width=max(rs) - min(rs),
                max_gap_deg=max(gaps), occupied_hours=hours)


def case(cid, desc, pts, cx, cy, exp):
    m = measure(pts, cx, cy)
    assert abs(m["mean_r"] - exp["center_radius_mm"]) < 1e-6, cid
    assert abs(m["width"] - exp["band_width_mm"]) < 1e-6, cid
    assert abs(m["max_gap_deg"] - exp["max_gap_deg"]) < 1e-6, cid
    assert m["occupied_hours"] == exp["occupied_hours"], cid
    return dict(case_id=cid, description=desc, n_points=len(pts), points=pts, expected=exp)


cases = []
# RB-FULL: 120 pts, 3 deg step 0..357. Each residue k%4 has 30 pts -> mean r = (78+80+82+80)/4 = 80 exactly.
# Residue classes are spaced 12 deg (divides 360) -> centroid of points is (0,0) by symmetry.
full = ring([3 * k for k in range(120)])
cases.append(case("RB-FULL", "complete ring, center (0,0)", full, 0, 0, dict(
    classification="ring", center_x_mm=0.0, center_y_mm=0.0, center_radius_mm=80.0, band_width_mm=4.0,
    r_min_mm=78.0, r_max_mm=82.0, diameter_mm=160.0, max_gap_deg=3.0, span_deg=357.0,
    occupied_hours=list(range(1, 13)), full_ring=True)))

# RB-ARC: angles 0..90 step 3 inclusive = 31 pts. Residue counts 8/8/8/7 for r=78/80/82/80 ->
# mean = (8*78+8*80+8*82+7*80)/31 = 2480/31 = 80 exactly. Gap = 360-90 = 270.
# Hours: 0-14 -> 12, 15-44 -> 1, 45-74 -> 2, 75-90 -> 3.
arc = ring([3 * k for k in range(31)], prefix="A")
cases.append(case("RB-ARC", "partial ring, one arc 0..90 deg only", arc, 0, 0, dict(
    classification="partial_ring_or_arc_candidate", center_x_mm=0.0, center_y_mm=0.0,
    center_radius_mm=80.0, band_width_mm=4.0, r_min_mm=78.0, r_max_mm=82.0, diameter_mm=160.0,
    max_gap_deg=270.0, span_deg=90.0, occupied_hours=[1, 2, 3, 12], full_ring=False,
    note="center is only recoverable by circle fit (not point centroid); fit tolerance undecided (TBD)")))

# RB-OFFSET: RB-FULL shifted by (+10, 0). True center (10,0); r/width/diameter unchanged.
# About the wafer center (0,0) the radii span ~70..90 (width ~20): checks center is fitted, not assumed.
off = ring([3 * k for k in range(120)], cx=10.0, prefix="O")
cases.append(case("RB-OFFSET", "complete ring offset to (10,0)", off, 10.0, 0.0, dict(
    classification="ring", center_x_mm=10.0, center_y_mm=0.0, center_radius_mm=80.0, band_width_mm=4.0,
    r_min_mm=78.0, r_max_mm=82.0, diameter_mm=160.0, max_gap_deg=3.0, span_deg=357.0,
    occupied_hours=list(range(1, 13)), full_ring=True,
    wrong_if_centered_at_wafer_origin=dict(approx_band_width_mm=20.0, note="r about (0,0) spans ~70..90"))))

# RB-BLOB: counterexample, 30 pts within 3 mm of (80,0) (3 oclock). Radius ~80 but tiny angular span.
offs = [(0.0, 0.0)]
offs += [(math.cos(math.radians(45 * i)), math.sin(math.radians(45 * i))) for i in range(8)]
offs += [(2 * math.cos(math.radians(36 * i)), 2 * math.sin(math.radians(36 * i))) for i in range(10)]
offs += [(3 * math.cos(2 * math.pi * i / 11), 3 * math.sin(2 * math.pi * i / 11)) for i in range(11)]
assert len(offs) == 30
blob = [dict(id="B%03d" % (i + 1), x=round(80.0 + dx, 9), y=round(dy, 9)) for i, (dx, dy) in enumerate(offs)]
m = measure(blob, 0.0, 0.0)
# Analytical bound: all pts within 3 mm of (80,0) -> angular half-extent <= asin(3/80) = 2.15 deg.
assert 2 * math.degrees(math.asin(3 / 80)) < 4.4 and m["max_gap_deg"] > 355
assert m["occupied_hours"] == [3]
cases.append(dict(case_id="RB-BLOB", description="single blob at 3 oclock, radius ~80, counterexample (not a ring)",
                  n_points=30, points=blob,
                  expected=dict(classification="not_ring", full_ring=False, max_gap_deg_min=355.0,
                                angular_span_deg_max=4.4, occupied_hours=[3],
                                note="Same radius as a ring but angular span < 4.4 deg; must not be reported as ring.")))

out = dict(_meta=dict(
    fixture="ring_band", oracle_version="ring-band-1", synthetic=True, seed=None, generator="gen_ring_band.py",
    units="mm", frame="standard: center origin, +X right, +Y up, notch 6 oclock",
    plan_links=["E05", "E06", "C08", "C10", "C19", "P2-01"],
    definitions="band_width_mm here = ring thickness (r_max-r_min about ring center); NOT zone_8inch_boundary "
                "band_width_mm. Coordinates rounded to 1e-9 mm. Tolerances for fitted values are NOT set (TBD)."),
    cases=cases)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ring_band.json"), "w") as f:
    json.dump(out, f, indent=1)
print([(c["case_id"], c["n_points"]) for c in cases])
