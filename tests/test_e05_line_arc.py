"""E05 line / arc measurement and candidate rules (synthetic; oracle e05-line-arc-1, independent stdlib generator).

Thresholds in the classification tests are TEST-ONLY provisional profile values (TBD T-21).
"""
import json
from pathlib import Path

import pytest

from wafer.line import classify_line, measure_line
from wafer.profile import load_profile
from wafer.ring import angular_coverage, measure_ring

FX = json.loads((Path(__file__).parent / "fixtures/e05_line_arc/e05_line_arc.json").read_text(encoding="utf-8"))["cases"]
RULE = load_profile(Path(__file__).parent / "profiles/f01_test_profile.yaml").shapes.line


def xy(case):
    p = FX[case]["points"]
    return [q["x"] for q in p], [q["y"] for q in p]


def test_clean_line_measurements():
    e, m = FX["LINE-CLEAN"]["expected"], measure_line(*xy("LINE-CLEAN"))
    assert m["direction_deg"] == pytest.approx(e["direction_deg_from_plus_x_mod180"], abs=1e-6)
    assert m["length_mm"] == pytest.approx(e["length_mm"], abs=1e-6)
    assert m["rms_residual_mm"] == pytest.approx(0.0, abs=1e-6) and m["width_mm"] == pytest.approx(0.0, abs=1e-6)


def test_noisy_line_measurements():
    e, m = FX["LINE-NOISY"]["expected"], measure_line(*xy("LINE-NOISY"))
    assert m["direction_deg"] == pytest.approx(e["direction_deg_from_plus_x_mod180"], abs=e["direction_tolerance_deg"])
    assert m["length_mm"] == pytest.approx(e["length_along_axis_mm"], abs=e["length_tolerance_mm"])
    # E05-UP: the fixture's width 2.0 (tol 0.1) holds in the GENERATING-line frame. measure_line uses the
    # fitted PCA axis, which tilts by the regression slope s of the +-1 pattern on the along-axis
    # coordinate (independent stdlib calc below, s ~ -8.2e-4), so normal distances change by up to
    # |s| * L/2 at each end: 2.0 <= width <= 2.0 + |s| * L. (Observed 2.11; the fixture tolerance was
    # written for the generating frame, not for the fitted axis.)
    import math
    ux, uy = 1 / math.sqrt(1.25), 0.5 / math.sqrt(1.25)
    pts = FX["LINE-NOISY"]["points"]
    a = [p["x"] * ux + (p["y"] - 10) * uy for p in pts]
    nn = [-p["x"] * uy + (p["y"] - 10) * ux for p in pts]
    ma = sum(a) / len(a)
    slope = sum((ai - ma) * ni for ai, ni in zip(a, nn)) / sum((ai - ma) ** 2 for ai in a)
    assert 2.0 <= m["width_mm"] <= 2.0 + abs(slope) * e["length_along_axis_mm"]
    assert m["rms_residual_mm"] == pytest.approx(1.0, abs=0.05)  # generator: exactly 1.0 about the true line


def test_two_blobs_are_elongated_but_not_continuous():
    e, m = FX["LINE-TWO-BLOBS"]["expected"], measure_line(*xy("LINE-TWO-BLOBS"))
    assert 1.0 / m["eigen_ratio"] == pytest.approx(e["pca_eigenvalue_ratio_l1_over_l2"], rel=0.01)  # looks like a line to PCA
    assert m["max_gap_mm"] == pytest.approx(e["max_adjacent_gap_along_axis_mm"], abs=1e-3)
    assert m["max_gap_mm"] / m["length_mm"] == pytest.approx(e["max_adjacent_gap_along_axis_mm"] / e["axis_extent_mm"], abs=1e-3)


@pytest.mark.parametrize("case,status", [("LINE-CLEAN", "candidate"), ("LINE-NOISY", "candidate")])
def test_line_candidates(case, status):
    r = classify_line(*xy(case), RULE)
    assert r["feature_status"] == status and r["label"] == "linear"


def test_two_blobs_and_scatter_are_not_lines():
    r = classify_line(*xy("LINE-TWO-BLOBS"), RULE)
    assert r["feature_status"] == "no_match" and r["reason"] == "not_continuous"
    assert classify_line(*xy("SCATTER-SPARSE"), RULE)["feature_status"] == "no_match"


def test_sparse_line_is_insufficient_data_and_never_matched_before_calibration():
    assert classify_line(*xy("LINE-SPARSE"), RULE)["feature_status"] == "insufficient_data"
    assert classify_line(*xy("LINE-CLEAN"), RULE.model_copy(update={"calibrated": True}))["feature_status"] == "matched"
    assert classify_line(*xy("LINE-CLEAN"), RULE.model_copy(update={"enabled": False}))["feature_status"] == "disabled"


def test_arc_with_known_center():
    e = FX["ARC-KNOWN"]["expected"]
    xs, ys = xy("ARC-KNOWN")
    m = measure_ring(xs, ys, center=tuple(e["center_xy_mm"]))
    assert m["center_radius_mm"] == pytest.approx(e["radius_mm"], abs=e["center_radius_tolerance_mm"])
    assert m["ring_thickness_mm"] == pytest.approx(0.0, abs=0.01)
    assert m["span_deg"] == pytest.approx(e["span_deg"], abs=e["angle_tolerance_deg"])
    assert m["max_gap_deg"] == pytest.approx(360 - e["span_deg"], abs=e["angle_tolerance_deg"])
    # Tolerance flows through the coverage function (T-18). Clock angles about the arc center run
    # 30..150 deg in 4 deg steps; sectors are 1:[15,45) 2:[45,75) 3:[75,105) 4:[105,135) 5:[135,165).
    # Both arc ends sit at offset 15 (sector centers), i.e. 15 deg from every boundary, so no valid
    # tolerance (< 15) can extend the occupied hours there; interior boundary points only touch hours
    # that are already occupied. (30 deg is a sector CENTER, not a boundary.)
    for tol in (0.0, 5.0, 14.9):
        cov = angular_coverage(xs, ys, tuple(e["center_xy_mm"]), tol_deg=tol)
        assert cov["occupied_hours"] == [1, 2, 3, 4, 5] == cov["occupied_hours_tolerant"], tol
    # contrast: a single point 12 deg into sector 1 (3 deg from the 15 deg boundary) does extend at tol 5
    one = angular_coverage([50 * 0.2079], [50 * 0.9781], (0.0, 0.0), tol_deg=5.0)   # sin/cos(12 deg)
    assert one["occupied_hours"] == [12] and one["occupied_hours_tolerant"] == [1, 12]


def test_degenerate_line_inputs():
    assert measure_line([1, 2], [1, 2])["calc_status"] == "insufficient_data"
    assert measure_line([5, 5, 5], [7, 7, 7])["calc_status"] == "insufficient_data"
    assert classify_line([], [], RULE)["feature_status"] == "insufficient_data"
