"""E04 noise preservation, E05/E06-style ring measurement, E08 boundary labels.

All expectations come from the independent fixtures in tests/fixtures (stdlib generators).
Synthetic only. Classification thresholds for ring/arc/blob are TBD and not asserted here.
"""
import json
from pathlib import Path

import pytest

from wafer import geometry as g
from wafer.aggregate import aggregate
from wafer.clustering import dbscan
from wafer.profile import load_profile
from wafer.ring import angular_coverage, measure_ring

FX = Path(__file__).parent / "fixtures"
PROFILE = load_profile(Path(__file__).parent / "profiles/f01_test_profile.yaml")


def load(p):
    return json.loads((FX / p).read_text(encoding="utf-8"))


# ---- E04 ----
e04 = load("e04_noise/e04_noise.json")


@pytest.mark.parametrize("key", ["eps5_min5", "f01_profile_eps10_min3"])
def test_e04_noise_preserved_and_matches_oracle(key):
    ex = e04["expected"][key]
    pts = e04["points"]
    r = dbscan([p["id"] for p in pts], [p["x"] for p in pts], [p["y"] for p in pts],
               ex["eps_mm"], ex["min_samples"])
    assert sorted(r["noise"]) == sorted(ex["noise_ids"])
    assert sorted(i for v in r["clusters"].values() for i in v) == sorted(ex["cluster_ids"])
    assert r["n_clusters"] == ex["n_clusters"]


def test_e04_noise_stays_in_totals_and_bins():
    pts = e04["points"]
    a = aggregate([p["id"] for p in pts], [p["x"] for p in pts], [p["y"] for p in pts],
                  [p["bin"] for p in pts], PROFILE)
    assert a["n_included"] == e04["_meta"]["n_total"] == 70
    assert a["bin_totals"] == e04["_meta"]["bins"]
    assert sum(a["sectors_clock"].values()) + a["center"] == 70


def test_dbscan_empty_input():
    assert dbscan([], [], [], 5, 5)["n_clusters"] == 0


# ---- ring / band ----
rb = {c["case_id"]: c for c in load("ring_band/ring_band.json")["cases"]}


def xy(case):
    return [p["x"] for p in rb[case]["points"]], [p["y"] for p in rb[case]["points"]]


@pytest.mark.parametrize("case", ["RB-FULL", "RB-OFFSET"])
def test_full_ring_center_radius_width_diameter(case):
    e = rb[case]["expected"]
    m = measure_ring(*xy(case))
    assert m["center_x_mm"] == pytest.approx(e["center_x_mm"], abs=0.05)
    assert m["center_y_mm"] == pytest.approx(e["center_y_mm"], abs=0.05)
    assert m["center_radius_mm"] == pytest.approx(e["center_radius_mm"], abs=0.05)
    # E05-UP (thickness = P95-P5, user decision): radii 78 x30, 80 x60, 82 x30 (n=120, linear quantiles)
    # P5 at pos 5.95 -> idx5 = 78; P95 at pos 113.05 -> idx113 = 82 -> thickness 4.0.
    assert m["ring_thickness_mm"] == pytest.approx(4.0, abs=0.1)
    assert m["radial_extent_mm"] == pytest.approx(e["band_width_mm"], abs=0.1)  # old oracle = max-min
    assert m["diameter_mm"] == pytest.approx(e["diameter_mm"], abs=0.1)
    assert m["max_gap_deg"] == pytest.approx(e["max_gap_deg"], abs=0.1)
    assert m["occupied_hours"] == e["occupied_hours"]


def test_offset_ring_measured_about_wafer_origin_would_be_wrong():
    """Assuming the wafer center inflates the thickness: independent math.hypot reference on the
    fixture points, and the analytic upper bound 4 + 2*10 = 24 (triangle inequality)."""
    import math
    xs, ys = xy("RB-OFFSET")
    d = [math.hypot(a, b) for a, b in zip(xs, ys)]
    m = measure_ring(xs, ys, center=(0.0, 0.0))
    assert m["radial_extent_mm"] == pytest.approx(max(d) - min(d), abs=1e-9)
    assert 4.0 < m["radial_extent_mm"] <= 24.0  # the percentile thickness is deliberately not used for this bound


def test_under_determined_inputs_report_insufficient_data_not_numbers():
    assert measure_ring([1.0, 2.0], [0.0, 0.0])["calc_status"] == "insufficient_data"
    assert measure_ring([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])["calc_status"] == "insufficient_data"  # collinear
    assert measure_ring([], [])["calc_status"] == "insufficient_data"
    assert angular_coverage([], [])["occupied_hours"] == []


def test_arc_known_center_coverage_and_width():
    e = rb["RB-ARC"]["expected"]
    m = measure_ring(*xy("RB-ARC"), center=(0.0, 0.0))
    # radii 78 x8, 80 x15, 82 x8 (sorted idx 0-7, 8-22, 23-30), n=31: P5 pos 1.5 -> 78; P95 pos 28.5 -> 82
    assert m["ring_thickness_mm"] == pytest.approx(4.0, abs=0.01)
    assert m["radial_extent_mm"] == pytest.approx(e["band_width_mm"], abs=0.01)
    assert m["center_radius_mm"] == pytest.approx(e["center_radius_mm"], abs=0.01)
    assert m["max_gap_deg"] == pytest.approx(e["max_gap_deg"], abs=0.01)
    assert m["span_deg"] == pytest.approx(e["span_deg"], abs=0.01)
    assert m["occupied_hours"] == e["occupied_hours"]


def test_blob_has_tiny_angular_span():
    e = rb["RB-BLOB"]["expected"]
    c = angular_coverage(*xy("RB-BLOB"))
    assert c["span_deg"] < e["angular_span_deg_max"] and c["max_gap_deg"] > e["max_gap_deg_min"]
    assert c["occupied_hours"] == e["occupied_hours"]


# ---- E08 ----
e08 = load("e08_boundary/e08_boundary.json")


def e08_points(include_ambiguous=False):
    return [p for p in e08["points"]
            if p["expected"]["sector"] is not None and (include_ambiguous or not p.get("float_ambiguous"))
            and p["expected"].get("zones") is not None]


def test_e08_zone_membership_matches_oracle():
    pts = e08_points(include_ambiguous=True)  # zones do not depend on angle, so 15/345 deg points count
    a = aggregate([p["id"] for p in pts], [p["x"] for p in pts], [p["y"] for p in pts],
                  ["B1"] * len(pts), PROFILE)
    zone_key = {"E1": "E1", "E2": "E2", "zone_8inch_inside": "inner", "zone_8inch_boundary": "band"}
    for p in pts:
        got = {zk for zk, name in zone_key.items() if p["id"] in a["zones"][name]}
        assert got == set(p["expected"]["zones"]), p["id"]


def test_e08_sectors_and_center_match_oracle():
    for p in e08_points():
        r = g.r_mm(p["x"], p["y"])
        is_c = bool(g.is_center(r, 1.0))
        assert is_c == p["expected"]["center"], p["id"]
        if not is_c:
            hour = int(g.clock_hour(g.theta_clock_deg(p["x"], p["y"])))
            assert hour == p["expected"]["sector"], p["id"]


def test_thickness_is_outlier_robust_but_extent_is_not():
    """50 points at r=78, 50 at r=82, one outlier at r=95 (center known = origin).
    n=101 sorted: idx0-49=78, 50-99=82, 100=95. Linear quantiles: P5 pos 5 -> 78; P95 pos 95 -> 82.
    Thickness = 4.0 (unaffected); extent = 95 - 78 = 17 (inflated by the outlier)."""
    xs = [78.0] * 50 + [-82.0] * 50 + [0.0]
    ys = [0.0] * 50 + [0.0] * 50 + [95.0]
    m = measure_ring(xs, ys, center=(0.0, 0.0))
    assert m["ring_thickness_mm"] == pytest.approx(4.0)
    assert m["radial_extent_mm"] == pytest.approx(17.0)


def test_e08_15_and_345_deg_points_are_flagged_ambiguous_and_counts_conserved():
    """Exact 15/345 deg points cannot be represented in float xy (T-15). They are flagged via the
    +-5 deg tolerance (flag only); their sector may be either neighbour but the total is conserved."""
    amb = [p for p in e08["points"] if p.get("float_ambiguous")]
    assert amb
    a = aggregate([p["id"] for p in amb], [p["x"] for p in amb], [p["y"] for p in amb],
                  ["B1"] * len(amb), PROFILE)
    assert a["boundary_tolerance_deg"] == 5.0
    assert set(a["boundary_ambiguous"]["ids"]) >= {p["id"] for p in amb}
    assert sum(a["sectors_clock"].values()) + a["center"] == len(amb)


def test_tolerance_is_configurable_through_profile():
    import yaml
    from wafer.profile import parse_profile
    d = yaml.safe_load(open(Path(__file__).parent / "profiles/f01_test_profile.yaml", encoding="utf-8"))
    d["clock"]["boundary_tolerance_deg"] = 0.0
    p0 = parse_profile(d)
    pts = [p for p in e08["points"] if p.get("float_ambiguous")]
    a = aggregate([p["id"] for p in pts], [p["x"] for p in pts], [p["y"] for p in pts], ["B1"] * len(pts), p0)
    assert a["boundary_tolerance_deg"] == 0.0
    # hand: the points are exactly at 15 / 345 deg (boundaries), so even tol 0 flags every one of them
    assert a["boundary_ambiguous"]["count"] == len(pts)


# ---- ring/arc classification (TBD T-14; thresholds are TEST-ONLY profile values) ----
from wafer.ring import classify_ring  # noqa: E402

RULE = PROFILE.shapes.ring


def test_full_ring_is_a_candidate_not_matched_until_calibrated():
    for case in ("RB-FULL", "RB-OFFSET"):
        r = classify_ring(*xy(case), RULE)
        assert r["feature_status"] == "candidate" and r["label"] == "ring", case
        assert r["occupancy"] == pytest.approx(1.0)          # 3 deg spacing -> all 36 bins hit
        assert r["relative_thickness"] == pytest.approx(4.0 / 80.0, abs=0.005)


def test_calibrated_flag_is_the_only_way_to_matched():
    rule = RULE.model_copy(update={"calibrated": True})
    assert classify_ring(*xy("RB-FULL"), rule)["feature_status"] == "matched"


def test_arc_needs_known_center():
    known = classify_ring(*xy("RB-ARC"), RULE, center=(0.0, 0.0))
    assert known["feature_status"] == "candidate" and known["label"] == "arc"
    assert known["occupancy"] == pytest.approx(10 / 36)       # 0..90 deg at 3 deg: bins 0..9
    unknown = classify_ring(*xy("RB-ARC"), RULE)
    assert unknown["feature_status"] == "insufficient_data"
    assert unknown["reason"] == "arc_requires_known_center"


def test_blob_is_not_a_ring():
    r = classify_ring(*xy("RB-BLOB"), RULE, center=(0.0, 0.0))
    assert r["feature_status"] == "no_match" and r["reason"] == "low_angular_occupancy"
    # blob at (80,0) is centered on theta=90 deg with half-width asin(3/80)=2.15 deg: it straddles the
    # 90 deg bin edge, so exactly 2 of 36 bins (80-90, 90-100) are occupied.
    assert r["occupancy"] == pytest.approx(2 / 36)


def test_too_few_points_and_disabled():
    assert classify_ring([0, 1, 2], [5, 6, 7], RULE)["reason"] == "fewer_than_min_points"
    off = RULE.model_copy(update={"enabled": False})
    assert classify_ring(*xy("RB-FULL"), off)["feature_status"] == "disabled"


def test_thick_band_is_rejected_even_if_it_spans_all_angles():
    # same 36 angles, radii alternate 40 / 120 about origin -> relative thickness (P95-P5)/mean ~ 1.0
    import math
    th = [i * 10 for i in range(36)] * 2
    rad = [40.0] * 36 + [120.0] * 36
    xs = [r * math.sin(math.radians(t)) for r, t in zip(rad, th)]
    ys = [r * math.cos(math.radians(t)) for r, t in zip(rad, th)]
    r = classify_ring(xs, ys, RULE, center=(0.0, 0.0))
    assert r["feature_status"] == "no_match" and r["reason"] == "band_too_thick_for_ring"


def test_occupancy_wraps_angles_that_round_to_360_into_bin_zero():
    """theta = 359.9999999996 deg rounds to 360.0 at 1e-9; it must land in bin 0, never in a 37th bin."""
    import math
    from wafer.ring import angular_occupancy
    t = math.radians(359.9999999996)
    pts = [(math.sin(t) * 50, math.cos(t) * 50), (0.0, 50.0)]  # both belong to the 12 o'clock bin
    assert angular_occupancy([p[0] for p in pts], [p[1] for p in pts], (0.0, 0.0), 10.0) == pytest.approx(1 / 36)


def test_zero_radius_ring_input_is_insufficient_data_not_a_crash():
    r = classify_ring([0.0] * 25, [0.0] * 25, RULE, center=(0.0, 0.0))
    assert r["feature_status"] == "insufficient_data" and r["reason"] == "zero_radius"


def test_tolerant_sector_counts_follow_the_tolerance_and_conserve_unique_points():
    import yaml
    from wafer.profile import parse_profile
    # hand-built angles about origin at r=50: 14 deg (12h, 1 deg from the 15 deg boundary), 10 deg
    # (exactly 5 from it), 20 deg (1h, 5 from it), 30 deg (1h, 15 away), 355 deg (12h, 10 away)
    import math
    angs = [14, 10, 20, 30, 355]
    xs = [50 * math.sin(math.radians(a)) for a in angs]
    ys = [50 * math.cos(math.radians(a)) for a in angs]
    d = yaml.safe_load(open(Path(__file__).parent / "profiles/f01_test_profile.yaml", encoding="utf-8"))
    out = {}
    for tol in (0.0, 5.0, 6.0):
        d["clock"]["boundary_tolerance_deg"] = tol
        out[tol] = aggregate(list("abcde"), xs, ys, ["B1"] * 5, parse_profile(d))
    strict = out[5.0]["sectors_clock"]
    assert strict[12] == 3 and strict[1] == 2 and sum(strict.values()) == 5     # partition, tol-independent
    assert out[0.0]["sectors_clock"] == out[5.0]["sectors_clock"] == out[6.0]["sectors_clock"]
    # tol 5: a(14)->+1h, b(10)->+1h, c(20)->+12h ; d, e unaffected
    t5 = out[5.0]["sectors_clock_tolerant"]
    assert t5[12] == 4 and t5[1] == 4 and out[5.0]["n_multi_sector"] == 3
    assert sum(t5.values()) == 5 + 3 == 5 - 0 + out[5.0]["n_multi_sector"]   # N - center + n_multi
    # tol 0: no point is exactly on a boundary in this input (exact-boundary points would be flagged, see
    # test_tolerance_is_configurable_through_profile)
    assert out[0.0]["sectors_clock_tolerant"] == out[0.0]["sectors_clock"] and out[0.0]["n_multi_sector"] == 0
    assert out[6.0]["n_multi_sector"] == 3                                      # 355 is 10 away, 30 is 15 away
    # coverage/occupancy follow the same tolerance
    cov = angular_coverage(xs, ys, (0.0, 0.0), tol_deg=5.0)
    assert cov["occupied_hours"] == [1, 12] and cov["occupied_hours_tolerant"] == [1, 12]
    assert angular_coverage([50 * math.sin(math.radians(14))], [50 * math.cos(math.radians(14))],
                            (0.0, 0.0), tol_deg=5.0)["occupied_hours_tolerant"] == [1, 12]
    assert angular_coverage([50 * math.sin(math.radians(14))], [50 * math.cos(math.radians(14))],
                            (0.0, 0.0), tol_deg=0.0)["occupied_hours_tolerant"] == [12]
