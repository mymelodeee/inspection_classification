"""Radial density and Clark-Evans (E11, E03, E23-lite, C06/C07). Hand-derived oracles; synthetic only."""
import math

import pytest

from wafer.stats import clark_evans, radial_density

PI = math.pi


def test_counts_without_coverage_have_null_density_and_reason():
    rows = radial_density([10, 20, 120], [0, 50, 100, 150])["rows"]
    assert [r["count"] for r in rows] == [2, 0, 1]
    assert all(r["area_mm2"] is None and r["density_per_mm2"] is None for r in rows)
    assert rows[0]["reason"] == "coverage_unknown"


def test_density_uses_annulus_area_intersected_with_inspected_disk():
    # Rc=120: [0,50) area pi*2500; [50,100) pi*(10000-2500); [100,150) pi*(14400-10000) = pi*4400
    rows = radial_density([10, 20, 120], [0, 50, 100, 150], inspected_radius_mm=120)["rows"]
    assert rows[0]["area_mm2"] == pytest.approx(PI * 2500)
    assert rows[1]["area_mm2"] == pytest.approx(PI * 7500)
    assert rows[2]["area_mm2"] == pytest.approx(PI * 4400)
    assert rows[0]["density_per_mm2"] == pytest.approx(2 / (PI * 2500))
    assert rows[1]["density_per_mm2"] == 0.0 and rows[1]["reason"] is None  # count 0, area > 0 -> real 0


def test_annulus_fully_outside_inspected_disk_is_not_zero_density():
    rows = radial_density([10], [0, 50, 100], inspected_radius_mm=50)["rows"]
    assert rows[1]["area_mm2"] == 0.0
    assert rows[1]["density_per_mm2"] is None and rows[1]["reason"] == "zero_inspected_area"


def test_clark_evans_hand_computed_index():
    # 4 points (+-1,+-1): NN distance 2 each. Window disk r=2: area 4*pi, lambda = 1/pi,
    # expected NN = 0.5/sqrt(1/pi) = 0.5*sqrt(pi) = 0.88623, R = 2/0.88623 = 2.25676
    r = clark_evans([1, -1, 1, -1], [1, 1, -1, -1], inspected_radius_mm=2.0, nsim=99, seed=1)
    assert r["calc_status"] == "computed"
    assert r["mean_nn_mm"] == pytest.approx(2.0)
    assert r["expected_nn_mm"] == pytest.approx(0.5 * math.sqrt(PI))
    assert r["index_R"] == pytest.approx(2.0 / (0.5 * math.sqrt(PI)))


def test_clark_evans_reproducible_for_same_seed_and_seed_required():
    pts = ([0, 10, 25, -30, 40, 5], [0, 12, -8, 20, 3, -35])
    a = clark_evans(*pts, inspected_radius_mm=50, nsim=199, seed=7)
    b = clark_evans(*pts, inspected_radius_mm=50, nsim=199, seed=7)
    assert a == b and 0 < a["p_two_sided"] <= 1
    assert clark_evans(*pts, inspected_radius_mm=50)["reason"] == "seed_required_for_reproducibility"


def test_clark_evans_not_computed_without_coverage_or_with_few_points():
    assert clark_evans([0, 5], [0, 5])["reason"] == "coverage_unknown"
    r = clark_evans([0], [0], inspected_radius_mm=50, seed=1)
    assert r["calc_status"] == "insufficient_data" and "p_two_sided" not in r
    assert clark_evans([], [], inspected_radius_mm=50, seed=1)["calc_status"] == "insufficient_data"


def test_clustered_points_give_small_index_and_small_p():
    # 12 points inside a 3 mm circle in a 100 mm window: strongly clustered
    th = [i * 2 * PI / 12 for i in range(12)]
    r = clark_evans([3 * math.cos(t) for t in th], [3 * math.sin(t) for t in th],
                    inspected_radius_mm=100, nsim=499, seed=3)
    assert r["index_R"] < 0.2 and r["p_two_sided"] < 0.05


def test_points_outside_edges_are_counted_not_lost():
    d = radial_density([10, 20, 200, -1.0], [0, 50, 100])
    assert sum(r["count"] for r in d["rows"]) + d["n_outside_edges"] == 4
    assert d["n_outside_edges"] == 2


def test_points_beyond_inspected_window_do_not_inflate_density():
    d = radial_density([130], [100, 150], inspected_radius_mm=120)["rows"][0]
    assert d["count"] == 1 and d["density_per_mm2"] is None
    assert d["reason"] == "points_outside_inspected_window" and d["n_outside_window"] == 1


def test_clark_evans_rejects_invalid_window_or_points():
    assert clark_evans([0, 5], [0, 5], inspected_radius_mm=0, seed=1)["calc_status"] == "insufficient_data"
    assert clark_evans([0, 5], [0, 5], inspected_radius_mm=10, seed=1, nsim=0)["calc_status"] == "insufficient_data"
    r = clark_evans([0, 50], [0, 0], inspected_radius_mm=10, seed=1)
    assert r["reason"] == "points_outside_inspected_window" and "p_two_sided" not in r
