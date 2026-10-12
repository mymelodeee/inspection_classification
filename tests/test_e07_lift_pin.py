"""E07 lift-pin template match (synthetic; oracle e07-lift-pin-1, independent stdlib generator).

The template (r 60, phase 0, 0/120/240, tol 10 deg / 5 mm, min 3 per lobe) is TEST-ONLY, not an
in-house value (TBD T-07). min_lobe_contrast 3.0 is a TEST-ONLY provisional value (T-22).
Policies (T-22): "matched" only when the template is calibrated; absence is concluded only where
coverage is known - FULL-coverage fixture cases therefore run with uncovered=[] and the same inputs
with coverage unknown (uncovered=None) must give insufficient_data (plan 16.2).
"""
import json
import math
from pathlib import Path

import pytest

from wafer.lift_pin import match_lift_pin
from wafer.profile import ConfigInvalid, parse_profile

D = json.loads((Path(__file__).parent / "fixtures/e07_lift_pin/e07_lift_pin.json").read_text(encoding="utf-8"))
T = D["_meta"]["template"]
FULL = []   # coverage known, nothing uninspected


def tmpl(**upd):
    lp = {"enabled": True, "template_id": T["template_id"], "frame": T["frame"],
          "expected_lobes": T["expected_lobes"], "spacing_deg": T["spacing_deg"],
          "radius_band_mm": T["radius_band_mm"], "phase_deg": T["phase_deg"],
          "angular_tolerance_deg": T["angular_tolerance_deg"], "radial_tolerance_mm": T["radial_tolerance_mm"],
          "min_support_per_lobe": T["min_support_per_lobe"], "min_lobe_contrast": 3.0} | upd
    return parse_profile({"profile_id": "e07_test_only", "wafer_radius_mm": 150,
                          "signatures": {"lift_pin": lp}}).signatures.lift_pin


def run(case, uncovered=FULL, **upd):
    p = D["cases"][case]["points"]
    return match_lift_pin([q["id"] for q in p], [q["x"] for q in p], [q["y"] for q in p], tmpl(**upd), uncovered)


def test_ideal_three_lobes():
    c = D["cases"]["LP-IDEAL"]
    r = run("LP-IDEAL")
    assert r["feature_status"] == "candidate" and r["match_type"] == "threefold_match"   # uncalibrated
    assert run("LP-IDEAL", calibrated=True)["feature_status"] == c["expected"]["feature_status"] == "matched"
    assert run("LP-IDEAL", uncovered=None)["match_type"] == "threefold_match"   # all observed: coverage irrelevant
    assert [sorted(lb["support_ids"]) for lb in r["lobes"]] == [sorted(lb["support_ids"]) for lb in c["lobes"]]
    for lb, e in zip(r["lobes"], c["lobes"]):
        assert lb["phase_residual_deg"] == pytest.approx(e["angular_residual_deg"], abs=1e-6)
        assert lb["mean_radius_mm"] == pytest.approx(e["mean_point_radius_mm"], abs=1e-6)
    f = c["features"]
    assert r["lobe_weighted"]["A3"] == pytest.approx(f["harmonics_equal_per_lobe"]["A3"], abs=1e-9)
    assert r["point_weighted"]["A3"] == pytest.approx(f["harmonics_point_weighted"]["A3"], abs=1e-6)
    assert "not a cause" in r["wording"]


def test_single_blob_is_not_a_lift_pin_even_with_high_a3():
    c = D["cases"]["LP-SINGLE-BLOB"]
    r = run("LP-SINGLE-BLOB")
    assert r["feature_status"] == "no_match" and r["reason"] == "fewer_than_two_template_lobes"
    assert sum(lb["present"] for lb in r["lobes"]) == 1
    assert r["point_weighted"]["A3"] == pytest.approx(c["features"]["harmonics_point_weighted"]["A3"], abs=1e-6)
    assert r["point_weighted"]["A3"] > 0.99          # A3 alone would have said "3-fold" (plan 8.2)
    assert run("LP-SINGLE-BLOB", uncovered=None)["feature_status"] == "insufficient_data"   # 16.2


def test_two_lobes_are_partial_candidates_never_matched():
    r = run("LP-TWO-LOBES", calibrated=True)
    assert r["feature_status"] == "candidate" and r["match_type"] == "partial_match"
    assert r["coverage_flag"] == "inspected_empty"
    assert run("LP-TWO-LOBES", uncovered=None)["coverage_flag"] == "coverage_unknown"


def test_wrong_radius_and_wrong_phase():
    r = run("LP-WRONG-RADIUS")
    assert r["feature_status"] == "no_match" and r["reason"] == "no_points_in_radius_band"
    p = run("LP-WRONG-PHASE")
    assert p["feature_status"] == "no_match" and p["reason"] == "phase_mismatch"
    e = D["cases"]["LP-WRONG-PHASE"]["features"]
    assert p["point_weighted"]["phase_3_deg"] == pytest.approx(e["harmonics_point_weighted"]["phase_3_deg"], abs=1e-6)
    assert p["phase_residual_deg"] == pytest.approx(e["phase_residual_deg"], abs=1e-6)   # wrapped with period 120
    for case in ("LP-WRONG-RADIUS", "LP-WRONG-PHASE"):
        assert run(case, uncovered=None)["feature_status"] == "insufficient_data"


def test_uninspected_position_is_not_reported_as_absent():
    c = D["cases"]["LP-UNCOVERED"]
    r = run("LP-UNCOVERED", uncovered=c["coverage"]["uncovered_regions"], calibrated=True)
    e = c["expected"]
    assert r["feature_status"] == e["feature_status"] == "candidate"
    assert r["match_type"] == e["match_type"] and r["coverage_flag"] == e["coverage_flag"]
    missing = [lb for lb in r["lobes"] if not lb["present"]]
    assert [lb["position_deg"] for lb in missing] == e["unobserved_positions_deg"]
    assert missing[0]["coverage"] == "not_inspected"


def test_partially_uninspected_window_and_wraparound_region():
    # window of 240 is [230, 250]; an uninspected region [245, 260) overlaps only part of it -> not_inspected
    r = run("LP-TWO-LOBES", uncovered=[{"clock_deg_interval": [245, 260], "radius_mm_interval": [40, 80]}])
    assert r["coverage_flag"] == "incomplete_coverage"
    # region wrapping through 0: [350, 5) touches the 0-deg window; the 240 window is still inspected
    r2 = run("LP-TWO-LOBES", uncovered=[{"clock_deg_interval": [350, 5], "radius_mm_interval": [40, 80]}])
    assert [lb["coverage"] for lb in r2["lobes"] if not lb["present"]] == ["inspected"]


def test_uniform_ring_is_not_a_lift_pin():
    """E07-RING counterexample: 72 points every 5 deg at r = 60. Each +-10 deg window holds 5 points
    (0, +-5, +-10 deg) -> 5/20 = 0.25 per deg; the rest of the band holds 72 - 15 = 57 points over
    300 deg -> 0.19 per deg; contrast 1.32 < 3.0 -> no lobe; coverage known -> no_match."""
    th = [math.radians(5 * k) for k in range(72)]
    r = match_lift_pin(list(range(72)), [60 * math.sin(t) for t in th], [60 * math.cos(t) for t in th],
                       tmpl(calibrated=True), FULL)
    assert r["feature_status"] == "no_match"
    assert all(lb["n"] == 5 and lb["contrast"] == pytest.approx((5 / 20) / (57 / 300)) for lb in r["lobes"])


@pytest.mark.parametrize("upd,key", [({"phase_deg": None}, "phase_deg"),
                                      ({"min_support_per_lobe": 0}, "min_support_per_lobe"),
                                      ({"expected_lobes": 2}, "expected_lobes"),
                                      ({"angular_tolerance_deg": 60}, "angular_tolerance_deg"),
                                      ({"min_lobe_contrast": None}, "min_lobe_contrast")])
def test_template_validation(upd, key):
    with pytest.raises(ConfigInvalid) as e:
        tmpl(**upd)
    assert f"signatures.lift_pin.{key}" in e.value.keys


def test_disabled():
    assert run("LP-IDEAL", enabled=False)["feature_status"] == "disabled"
