"""E08 boundary fixture generator (stdlib only, no production code). Usage: python gen_e08_boundary.py
Writes e08_boundary.json next to this file. Deterministic (no randomness; seed=None).

Test-only profile = tests/profiles/f01_test_profile.yaml (R=150, E1 [0,2) edge, E2 [2,5) edge,
inner r<100, band |r-100|<=1 closed both ends, center r<1.0, sector [center-15, center+15)).
Oracle method: every expected label is computed with exact rational arithmetic (fractions.Fraction
on the decimal strings below), never with floats or production functions.
"""
import json, math, os
from fractions import Fraction as F

R, CEN, BAND_HALF = F(150), F(1), F(1)   # BAND_HALF = band_width_mm(2)/2


def sector_hour(theta):            # theta: Fraction degrees in [0,360); half-open [lo,hi)
    h = int(((theta + 15) % 360) // 30)
    return h or 12


def zones(r):                      # r: Fraction mm (distance from wafer center)
    e = R - r
    tags = []
    if 0 <= e < 2: tags.append("E1")            # [0,2)  edge distance
    if 2 <= e < 5: tags.append("E2")            # [2,5)
    if r < 100: tags.append("zone_8inch_inside")  # [0,100)
    if abs(r - 100) <= BAND_HALF: tags.append("zone_8inch_boundary")  # [99,101] closed
    return tags


pts = []

# Group 1: edge distance on +X axis (theta=90 deg -> 3 o'clock). r = 150 - e.
# e<2 ->E1; 2<=e<5 ->E2; e>=5 -> none. e=0 means r=R which is INCLUDED (plan 6.4/16.3-8).
for e in ["0", "1.999", "2.0", "2.001", "4.999", "5.0", "5.001"]:
    r = R - F(e)
    pts.append(dict(id="EDGE_" + e, group="edge", x=float(r), y=0.0, r_mm=float(r), edge_mm=e,
                    exact=(float(r) == r), expected=dict(zones=zones(r), center=False, sector=3)))

# Group 2: radius on +X axis (3 o'clock). Band [99,101] closed; inner r<100.
for rs in ["98.9", "99", "99.1", "100", "101", "101.1"]:
    r = F(rs)
    pts.append(dict(id="R_" + rs, group="radius", x=float(r), y=0.0, r_mm=float(r), edge_mm=str(R - r),
                    exact=(float(r) == r), expected=dict(zones=zones(r), center=False, sector=3)))

# Group 3: center exclusion r<1.0 on -Y axis (theta=180 deg). 1.0 is NOT center (center is r<radius).
for rs, ctr in [("0.999", True), ("1.0", False)]:
    r = F(rs)
    pts.append(dict(id="CEN_" + rs, group="center", x=0.0, y=-float(r), r_mm=float(r), edge_mm=str(R - r),
                    exact=(float(r) == r),
                    expected=dict(zones=zones(r), center=ctr, sector=None if ctr else 6)))

# Group 4: clock-angle boundary at radius 50. x=50*sin(t), y=50*cos(t) (theta=atan2(x,y), 0=12 o'clock).
# Expected sector from the NOMINAL angle (exact Fraction). 15 and 345 are NOT float-representable
# in x,y (tan 15 deg irrational): flagged float_ambiguous; asserting them needs a tolerance/snap
# policy (TBD T-08). 14.9/15.1/344.9/345.1 have 0.1 deg margin (>> 1e-9 rounding).
for ts in ["14.9", "15", "15.1", "344.9", "345", "345.1"]:
    t = F(ts); rad = math.radians(float(t))
    x, y = round(50 * math.sin(rad), 12), round(50 * math.cos(rad), 12)
    pts.append(dict(id="TH_" + ts, group="angle", x=x, y=y, r_mm=50.0, theta_nominal_deg=ts,
                    float_ambiguous=(ts in ("15", "345")),
                    expected=dict(zones=zones(F(50)), center=False, sector=sector_hour(t))))

# Group 5: float-exact surrogates of the half-open sector rule (atan2 of exact x,y gives exactly 45/135/225/315).
for ts, x, y in [("45", 50, 50), ("135", 50, -50), ("225", -50, -50), ("315", -50, 50)]:
    t = F(ts)
    pts.append(dict(id="THX_" + ts, group="angle_exact", x=float(x), y=float(y), r_mm=math.hypot(x, y),
                    theta_nominal_deg=ts, float_ambiguous=False,
                    expected=dict(zones=zones(F(70)),  # r=70.71: only inner (edge 79.3, far from band)
                                  center=False, sector=sector_hour(t))))

# Group 6: contract NOT defined by the plan (do not assert): r slightly > R.
pts.append(dict(id="OUT_150.001", group="undefined", x=150.001, y=0.0, r_mm=150.001,
                expected=dict(zones=None, center=False, sector=None,
                              note="outside wafer; plan only states r=R is included. No expected value.")))

out = dict(
    _meta=dict(fixture="E08-boundary", oracle_version="e08-boundary-1", synthetic=True, seed=None,
               generator="gen_e08_boundary.py", units="mm",
               frame="standard: center origin, +X right, +Y up, notch 6 o'clock",
               profile="tests/profiles/f01_test_profile.yaml (TEST-ONLY, not operating values)",
               R_mm=150, center_exclusion_mm=1, band="|r-100|<=1 closed",
               plan_links=["E08", "C10", "C11", "C12", "C13", "C14", "P0-05"],
               notes=["Axis points (EDGE/R/CEN/THX) have exact float coordinates when exact=true/ float_ambiguous=false.",
                      "Decimal-edge points (e.g. 1.999, 98.9) are exact only to double precision; margin >= 0.001 mm >> eps.",
                      "Points with float_ambiguous=true: expected sector is for the ideal angle; assertion requires a snap/tolerance policy (TBD T-08).",
                      "zones lists tags expected from profile; E1/E2 are distance_from_edge_mm, inside/boundary are radius_mm."]),
    points=pts)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e08_boundary.json"), "w") as f:
    json.dump(out, f, indent=1)
print(len(pts), "points")
