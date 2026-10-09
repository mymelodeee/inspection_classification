"""E01 aggregation core on synthetic F01 (no KLARF parsing, no CLI).

Expected values come from tests/fixtures/f01/oracle.json (independently derived).
"""
import json
from pathlib import Path

from wafer.aggregate import aggregate
from wafer.profile import load_profile

HERE = Path(__file__).parent
oracle = json.loads((HERE / "fixtures/f01/oracle.json").read_text(encoding="utf-8"))


def run(profile_path="profiles/f01_test_profile.yaml"):
    d = oracle["defects"]
    p = load_profile(HERE / profile_path)
    return aggregate([x["id"] for x in d], [x["x_mm"] for x in d],
                     [x["y_mm"] for x in d], [x["bin"] for x in d], p)


def test_counts_bins_sectors_center():
    r = run()
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (8, 8, 0)
    assert r["bin_totals"] == oracle["bin_totals"]
    assert r["center"] == oracle["center"]
    assert r["sectors_clock"] == {int(k): v for k, v in oracle["sectors_clock"].items()}
    assert sum(r["sectors_clock"].values()) + r["center"] == r["n_included"]


def test_zones_match_oracle():
    z = run()["zones"]
    o = oracle["zones"]
    assert z["E1"] == o["E1"] and z["E2"] == o["E2"]
    assert sorted(z["inner"]) == o["inner_r_lt_100"]
    assert z["band"] == o["band_100mm_pm1"]
    assert run()["zone_union_unique"] == 8  # E1+E2+inner+band, no double counting


def test_outside_wafer_is_excluded_not_clipped():
    p = load_profile(HERE / "profiles/f01_test_profile.yaml")
    r = aggregate(["A", "B"], [0, 151], [50, 0], ["B1", "B1"], p)
    assert r["n_included"] == 1 and r["n_excluded"] == 1
    assert r["excluded"] == [{"defect_id": "B", "reason": "outside_wafer"}]
    assert r["n_parsed"] == r["n_included"] + r["n_excluded"]


def test_unknown_bin_preserved_in_total():
    p = load_profile(HERE / "profiles/f01_test_profile.yaml")
    r = aggregate(["A", "B"], [0, 50], [50, 0], ["B1", None], p)
    assert r["bin_totals"] == {"B1": 1, "unknown": 1}
    assert sum(r["bin_totals"].values()) == r["n_included"]
