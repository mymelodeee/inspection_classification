"""E05 line/arc/counter-example fixture (stdlib only, no production code, deterministic, seed=None).
Usage: python gen_e05_line_arc.py -> e05_line_arc.json beside this file.
Standard frame: mm, center origin, +X right, +Y up, R=150. Clock angle = degrees(atan2(x, y)) mod 360 (0=12h, 90=3h).
Expected values are hand-derivable from the construction; this script re-derives them with plain math
(independent of production code) and records the derivation text next to each value.
"""
import json
import math
import os

R = 150.0
S5 = math.sqrt(1.25)           # |(1, 0.5)|
UX, UY = 1 / S5, 0.5 / S5      # unit direction of y = 0.5x + 10
NX, NY = -UY, UX               # unit normal
r9 = lambda v: round(v, 9)


def pca_ratio(p):
    n = len(p)
    mx = sum(a for a, _ in p) / n
    my = sum(b for _, b in p) / n
    sxx = sum((a - mx) ** 2 for a, _ in p) / n
    syy = sum((b - my) ** 2 for _, b in p) / n
    sxy = sum((a - mx) * (b - my) for a, b in p) / n
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    d = math.sqrt(max(tr * tr / 4 - det, 0))
    l1, l2 = tr / 2 + d, tr / 2 - d
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return l1, l2, (l1 / l2 if l2 > 1e-12 else None), ang


def max_gap_along(p, ang):
    t = sorted(a * math.cos(ang) + b * math.sin(ang) for a, b in p)
    return max(t[i + 1] - t[i] for i in range(len(t) - 1)), t[-1] - t[0]


def pctl(v, q):  # linear-interpolation percentile
    s = sorted(v)
    k = (len(s) - 1) * q / 100
    f = int(math.floor(k))
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def ls_resid_rms(p):
    n = len(p)
    mx = sum(a for a, _ in p) / n
    my = sum(b for _, b in p) / n
    sxx = sum((a - mx) ** 2 for a, _ in p)
    sxy = sum((a - mx) * (b - my) for a, b in p)
    m = sxy / sxx
    c = my - m * mx
    return math.sqrt(sum(((b - (m * a + c)) / math.sqrt(1 + m * m)) ** 2 for a, b in p) / n)


def mk(prefix, pts, role):
    out = []
    for i, (x, y) in enumerate(pts):
        assert math.hypot(x, y) <= R
        out.append(dict(id="%s%02d" % (prefix, i + 1), x=r9(x), y=r9(y), bin="B%d" % (i % 3 + 1), role=role))
    return out


cases = {}
ANG_LINE = math.degrees(math.atan2(0.5, 1))  # direction angle from +X, mod 180

# (1) LINE-CLEAN
p = [(x, 0.5 * x + 10) for x in (-80 + 160 * i / 39 for i in range(40))]
cases["LINE-CLEAN"] = dict(
    points=mk("LC", p, "line"),
    expected=dict(label="line", n_support=40, support_ids="LC01..LC40 (all)",
                  direction_deg_from_plus_x_mod180=r9(ANG_LINE), length_mm=r9(160 * S5),
                  residual_rms_mm=0.0, width_p95_minus_p5_mm=0.0, tolerance_mm=1e-6),
    derivation="y=0.5x+10, x=-80..80 uniform (step 160/39). direction=atan2(0.5,1)=26.565051 deg. "
               "length=|P40-P1|=160*sqrt(1+0.25)=178.885438. All points exactly on the line -> residual 0, width 0.")

# (2) LINE-NOISY: normal displacement +1,-1,... (even index +1)
pn = []
for i, (x, y) in enumerate(p):
    s = 1.0 if i % 2 == 0 else -1.0
    pn.append((x + s * NX, y + s * NY))
nd = [a * NX + (b - 10) * NY for a, b in pn]  # signed normal distance to y=0.5x+10 (origin-side point (0,10))
assert all(abs(abs(v) - 1) < 1e-9 for v in nd)
cases["LINE-NOISY"] = dict(
    points=mk("LN", pn, "line_noisy"),
    expected=dict(label="line", n_support=40, support_ids="LN01..LN40 (all)",
                  direction_deg_from_plus_x_mod180=r9(ANG_LINE), direction_tolerance_deg=1.0,
                  length_along_axis_mm=r9(160 * S5), length_endpoint_distance_mm=r9(math.dist(pn[0], pn[-1])),
                  length_tolerance_mm=1.0,
                  residual_rms_vs_generating_line_mm=1.0,
                  residual_rms_vs_least_squares_fit_mm=r9(ls_resid_rms(pn)), residual_tolerance_mm=0.05,
                  width_p95_minus_p5_mm=r9(pctl(nd, 95) - pctl(nd, 5)), width_tolerance_mm=0.1),
    derivation="Each LINE-CLEAN point displaced exactly +1 (even index) / -1 (odd index) mm along unit normal "
               "(-0.5,1)/sqrt(1.25): 20 at +1, 20 at -1. RMS to the generating line = 1.0 exactly; a refit LS line is slightly "
               "smaller (<1). Normal distances are only +-1 so P95=+1, P5=-1 -> width 2.0. Along-axis extent unchanged = "
               "160*sqrt(1.25); end-to-end distance = sqrt(L^2+2^2) because first/last points sit at +1/-1.")

# (3) LINE-TWO-BLOBS


def blob(cx, cy):
    q = [(cx, cy)] + [(cx + 2 * math.cos(2 * math.pi * i / 11), cy + 2 * math.sin(2 * math.pi * i / 11))
                      for i in range(11)]
    assert len(q) == 12 and all(math.dist(a, (cx, cy)) <= 3 for a in q)
    return q


pb = blob(-60, 0) + blob(60, 0)
l1, l2, ratio, ang = pca_ratio(pb)
gap, extent = max_gap_along(pb, ang)
cases["LINE-TWO-BLOBS"] = dict(
    points=mk("TB", pb, "blob"),
    expected=dict(label="not_line", n_support=24,
                  pca_axis_deg_from_plus_x=r9(math.degrees(ang)),
                  pca_eigenvalue_ratio_l1_over_l2=r9(ratio), pca_ratio_note="elongated (>>1) yet NOT a line",
                  max_adjacent_gap_along_axis_mm=r9(gap), axis_extent_mm=r9(extent),
                  gap_over_extent=r9(gap / extent), gap_tolerance_mm=0.01,
                  continuity_requirement="large max-gap/extent must prevent a line verdict regardless of PCA ratio"),
    derivation="Two blobs of 12 pts (center + 11 at radius 2mm, angle 2*pi*i/11) around (-60,0) and (60,0). "
               "Axis is the x axis; gap = (60 + 2*cos(2*pi*5/11)) - (-60 + 2) = 116.081 (min cos = -0.9595), "
               "extent = 123.919 (= 62 + 61.919). PCA ratio is huge (elongated) but the gap shows no continuity. The gap threshold itself is "
               "a rule parameter not fixed here.")

# (4) ARC-KNOWN
CX, CY, RAD = 20.0, -10.0, 70.0
clocks = [30 + 4 * i for i in range(31)]
pa = [(CX + RAD * math.sin(math.radians(c)), CY + RAD * math.cos(math.radians(c))) for c in clocks]
cases["ARC-KNOWN"] = dict(
    points=mk("AR", pa, "arc"),
    expected=dict(label="arc", n_support=31, support_ids="AR01..AR31 (all)",
                  center_xy_mm=[CX, CY], radius_mm=RAD, center_radius_tolerance_mm=0.01,
                  clock_angle_range_deg_about_arc_center=[30, 150], angle_tolerance_deg=0.5, span_deg=120,
                  chord_length_mm=r9(2 * RAD * math.sin(math.radians(60))),
                  arc_length_mm=r9(RAD * math.radians(120)),
                  circle_fit_residual_rms_mm=0.0, residual_tolerance_mm=1e-6),
    derivation="x=20+70*sin(c), y=-10+70*cos(c), c=30,34,...,150 deg (31 pts); clock angle = atan2(dx,dy) about the ARC "
               "center, not the wafer center. chord=2*70*sin(60deg)=121.244; arc length=70*(2*pi/3)=146.608; exact radius "
               "-> residual 0. Center is off the wafer center, so this is not a wafer-centered ring.")

# (5) LINE-SPARSE
sx, sy = -60.0, -20.0  # on y=0.5x+10
ps = [(sx + 30 * k * UX, sy + 30 * k * UY) for k in range(6)]
cases["LINE-SPARSE"] = dict(
    points=mk("LS", ps, "line_sparse"),
    expected=dict(label="insufficient_data_candidate", n_points=6, spacing_mm=30,
                  direction_deg_from_plus_x_mod180=r9(ANG_LINE), length_mm=150.0, residual_rms_mm=0.0,
                  note="6 collinear points only; the min-support threshold is a rule parameter not fixed by this fixture. "
                       "Expected: not a confirmed line match; candidate / insufficient_data. Geometry itself is exact."),
    derivation="6 points on y=0.5x+10 starting (-60,-20), step 30mm along (2,1)/sqrt5; length=5*30=150.")

# (6) SCATTER: Vogel (golden-angle) spiral, 30 pts, r=25*sqrt(k)
GA = math.pi * (3 - math.sqrt(5))
psc = [(25 * math.sqrt(k) * math.sin(k * GA), 25 * math.sqrt(k) * math.cos(k * GA)) for k in range(1, 31)]
mind = min(math.dist(a, b) for i, a in enumerate(psc) for b in psc[i + 1:])
assert mind >= 20, mind
l1, l2, ratio, ang = pca_ratio(psc)
gap, extent = max_gap_along(psc, ang)
cases["SCATTER-SPARSE"] = dict(
    points=mk("SC", psc, "scatter"),
    expected=dict(label="not_line", n_points=30, min_mutual_distance_mm=r9(mind), min_mutual_distance_required_mm=20,
                  pca_eigenvalue_ratio_l1_over_l2=r9(ratio), pca_ratio_note="not strongly elongated",
                  max_adjacent_gap_along_axis_mm=r9(gap), axis_extent_mm=r9(extent)),
    derivation="Vogel spiral: r_k=25*sqrt(k), azimuth k*137.5078deg (k=1..30), max r=136.9<150. Asserted min mutual "
               "distance >= 20mm. Roughly isotropic disc -> no linear structure; not_line.")

doc = dict(_meta=dict(fixture="E05-line-arc", oracle_version="e05-line-arc-1", synthetic=True, seed=None,
                      generator="gen_e05_line_arc.py", units="mm", wafer_radius_mm=R,
                      frame="standard: center origin, +X right, +Y up",
                      clock_angle="degrees(atan2(x, y)) mod 360",
                      plan_links=["E05", "C08", "C19", "P2-04"],
                      scope="geometry/count oracle for line/arc/counter-example features; not a real-equipment coordinate validation",
                      bins="B1/B2/B3 cycle by index within each case"),
           cases=cases)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e05_line_arc.json"), "w") as f:
    json.dump(doc, f, indent=1)
    f.write("\n")
