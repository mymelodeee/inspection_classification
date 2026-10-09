"""Geometry tests. All expected values are hand-derived from plan 19.2 (F01), 8.3, 16.3
and E08; none is produced by calling the production functions."""
import numpy as np
import pytest

from wafer import geometry as g

# F01 (plan 19.2): id, x, y, expected clock label (12 / 3 / 6 / 9 / 'center')
F01 = [
    ("D01", 0, 50, 12), ("D02", 50, 0, 3), ("D03", 0, -50, 6), ("D04", -50, 0, 9),
    ("D05", 0, 0, "center"), ("D06", 149, 0, 3), ("D07", 148, 0, 3), ("D08", 100, 0, 3),
]
R = 150.0


def test_f01_clock_and_center():
    x = np.array([d[1] for d in F01], float)
    y = np.array([d[2] for d in F01], float)
    r = g.r_mm(x, y)
    center = g.is_center(r, 1.0)
    hour = g.clock_hour(g.theta_clock_deg(x, y))
    labels = ["center" if c else int(h) for c, h in zip(center, hour)]
    assert labels == [d[3] for d in F01]
    # counts: center=1, 12h=1, 3h=4, 6h=1, 9h=1, sum = included 8
    assert labels.count("center") == 1 and labels.count(12) == 1 and labels.count(3) == 4
    assert labels.count(6) == 1 and labels.count(9) == 1


def test_theta_cardinal_values():
    th = g.theta_clock_deg([0, 50, 0, -50], [50, 0, -50, 0])
    assert th.tolist() == [0.0, 90.0, 180.0, 270.0]


def test_theta_never_360():
    # tiny negative x gives atan2 ~ -0 deg; must map to 0, not 360
    th = g.theta_clock_deg([-1e-300, -0.0], [1.0, 1.0])
    assert np.all(th >= 0) and np.all(th < 360)


def test_r():
    assert g.r_mm(3, 4) == 5.0
    assert g.r_mm(np.array([0, 100]), np.array([0, 0])).tolist() == [0.0, 100.0]


@pytest.mark.parametrize("theta, hour", [
    (0, 12), (14.999, 12), (15, 1), (15.001, 1), (44.999, 1), (45, 2), (90, 3),
    (180, 6), (270, 9), (344.999, 11), (345, 12), (345.001, 12), (359.999, 12),
    (314.999, 10), (315, 11),
])
def test_sector_boundaries_left_closed(theta, hour):
    assert int(g.clock_hour(theta)) == hour


def test_sector_index_zero_is_12h_and_all_twelve_covered():
    th = np.arange(0, 360, 30.0)  # exact centers of 12h,1h,...,11h
    assert g.sector_index(th).tolist() == list(range(12))
    assert g.clock_hour(th).tolist() == [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]


def test_center_strict_less_than():
    r = np.array([0.0, 0.999, 1.0, 1.001])
    assert g.is_center(r, 1.0).tolist() == [True, True, False, False]


def test_edge_distance_and_zone_intervals_e08():
    # R=150: edge distance 0/2/5 and both sides
    r = np.array([150.0, 149.0, 148.0, 147.999, 146.0, 145.0, 144.999, 145.001])
    d = g.edge_distance_mm(r, R)
    assert d == pytest.approx([0.0, 1.0, 2.0, 2.001, 4.0, 5.0, 5.001, 4.999], abs=1e-9)
    e1 = g.in_interval(d, 0, 2)
    e2 = g.in_interval(d, 2, 5)
    assert e1.tolist() == [True, True, False, False, False, False, False, False]
    assert e2.tolist() == [False, False, True, True, True, False, False, True]


def test_f01_zones():
    ids = [d[0] for d in F01]
    r = g.r_mm([d[1] for d in F01], [d[2] for d in F01])
    d = g.edge_distance_mm(r, R)
    pick = lambda m: {i for i, f in zip(ids, m) if f}
    assert pick(g.in_interval(d, 0, 2)) == {"D06"}
    assert pick(g.in_interval(d, 2, 5)) == {"D07"}
    assert pick(g.in_interval(r, 0, 100)) == {"D01", "D02", "D03", "D04", "D05"}
    assert pick(g.in_band(r, 100, 2)) == {"D08"}


def test_inside_100_boundaries():
    r = np.array([99.0, 99.999, 100.0, 101.0])
    assert g.in_interval(r, 0, 100).tolist() == [True, True, False, False]


def test_band_both_ends_inclusive_E08():
    # width 2 -> band [99, 101]; 100mm is NOT converted to 101.6
    r = np.array([98.999, 99.0, 100.0, 101.0, 101.001, 101.6])
    assert g.in_band(r, 100, 2).tolist() == [False, True, True, True, False, False]


def test_in_wafer_r_equals_R_included_no_clip():
    r = np.array([149.9, 150.0, 150.001])
    assert g.in_wafer(r, 150.0).tolist() == [True, True, False]
    assert g.in_wafer(r, 150.0, tol_mm=0.01).tolist() == [True, True, True]
    assert r.tolist() == [149.9, 150.0, 150.001]  # input untouched


def test_to_mm():
    assert g.to_mm([50000, 0], "um").tolist() == [50.0, 0.0]
    assert g.to_mm([50.0], "mm").tolist() == [50.0]
    with pytest.raises(ValueError):
        g.to_mm([1], "inch")


# Standard F01 point D02 = (50, 0). The same physical wafer exported with the notch at
# another side has the point at the position below (hand-derived rotations).
@pytest.mark.parametrize("notch, src_xy", [
    ("DOWN", (50, 0)),
    ("UP", (-50, 0)),     # source frame is std rotated 180
    ("LEFT", (0, -50)),   # notch (-1,0)->(0,-1) is +90 CCW; source = std rotated -90
    ("RIGHT", (0, 50)),   # notch (1,0)->(0,-1) is -90; source = std rotated +90
])
def test_notch_rotation_back_to_standard(notch, src_xy):
    x, y = g.rotate_notch_to_down(src_xy[0], src_xy[1], notch)
    assert (float(x), float(y)) == (50.0, 0.0)


def test_notch_vector_goes_to_down():
    cases = {"UP": (0, 150), "LEFT": (-150, 0), "RIGHT": (150, 0), "DOWN": (0, -150)}
    for notch, (nx, ny) in cases.items():
        x, y = g.rotate_notch_to_down(nx, ny, notch)
        assert (float(x), float(y)) == (0.0, -150.0), notch


def test_no_double_rotation_when_already_normalized():
    xs, ys = g.rotate_notch_to_down(np.array([50.0, 0.0]), np.array([0.0, 50.0]), "UP",
                                    already_normalized=True)
    assert xs.tolist() == [50.0, 0.0] and ys.tolist() == [0.0, 50.0]


def test_unknown_notch_not_guessed():
    with pytest.raises(ValueError):
        g.rotate_notch_to_down(1, 1, "UNKNOWN")


# ---- sector boundary tolerance (user: +-5 deg, configurable) ----
from wafer.geometry import boundary_distance_deg, near_sector_boundary  # noqa: E402


def test_boundary_distance_hand_values():
    assert float(boundary_distance_deg(10)) == pytest.approx(5)
    assert float(boundary_distance_deg(350)) == pytest.approx(5)
    assert float(boundary_distance_deg(0)) == pytest.approx(15)
    assert float(boundary_distance_deg(359.9)) == pytest.approx(14.9)


def test_near_boundary_flag_follows_the_tolerance_parameter():
    th = [9.9, 10.0, 15.0, 20.0, 20.1, 345.0, 349.9, 355.0]
    assert list(near_sector_boundary(th, 5.0)) == [False, True, True, True, False, True, True, False]
    assert list(near_sector_boundary(th, 0.0)) == [False, False, True, False, False, True, False, False]
    assert list(near_sector_boundary(th, 10.0)) == [True, True, True, True, True, True, True, True]


from wafer.geometry import neighbor_hour  # noqa: E402


def test_neighbor_hour_hand_values_tol5():
    # sector 12 = [345,15), 1 = [15,45), 11 = [315,345). offset = position inside the sector.
    cases = {14.0: 1, 10.0: 1, 9.9: 0, 0.0: 0, 15.0: 12, 16.0: 12, 20.0: 12, 20.1: 0,
             350.0: 11, 345.0: 11, 355.0: 0, 44.0: 2, 46.0: 1, 359.0: 0}
    for th, want in cases.items():
        assert int(neighbor_hour(th, 5.0)) == want, th


def test_neighbor_hour_depends_on_the_tolerance_argument():
    assert int(neighbor_hour(12.0, 5.0)) == 1       # 15-12 = 3 deg <= 5
    assert int(neighbor_hour(12.0, 3.0)) == 1       # 15-12 = 3 deg from the boundary
    assert int(neighbor_hour(12.0, 2.9)) == 0
