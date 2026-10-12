"""E06 mixed ring/line/local support accounting + broken-ring handling (synthetic, C08/C10/C11).

Expected values: tests/fixtures/e06_mixed (independent stdlib generator, oracle e06-mixed-1).
SCOPE: E06 is PARTIAL - detectors (wafer.detect) produce the supports from the fixture points, but only
single wafer-centered ring / single line are searched, nothing is wired into the CLI, thresholds are
provisional (TBD T-17, T-19).
Ring thresholds come from the TEST-ONLY profile and are provisional (TBD T-14).
"""
import json
from pathlib import Path

import pytest

from wafer.clustering import dbscan
from wafer.groups import summarize_groups
from wafer.profile import load_profile
from wafer.ring import classify_ring

FX = json.loads((Path(__file__).parent / "fixtures/e06_mixed/e06_mixed.json").read_text(encoding="utf-8"))
RULE = load_profile(Path(__file__).parent / "profiles/f01_test_profile.yaml").shapes.ring


def pts(case):
    return {p["id"]: p for p in FX["cases"][case]["points"]}


@pytest.mark.parametrize("case", ["intact", "broken_ring"])
def test_group_support_and_unique_union(case):
    e = FX["cases"][case]["expected"]
    P = pts(case)
    r = summarize_groups(e["support_ids"], {i: p["bin"] for i, p in P.items()})
    assert r["support_counts"] == e["support_count"]
    assert r["naive_sum"] == e["naive_sum"]
    assert r["unique_union"] == e["unique_union_size"] == e["wafer_unique_defect_count"] == len(P)
    assert r["naive_sum"] - r["unique_union"] == e["naive_minus_union"] == 5
    assert r["overlap_ids"] == sorted(e["overlap_ids"])
    assert r["union_bin_counts"] == e["bin_unique_totals"]
    assert sum(r["union_bin_counts"].values()) == r["unique_union"]  # no double counting by bin


def test_unknown_support_id_is_an_error_not_silently_counted():
    with pytest.raises(ValueError):
        summarize_groups({"ring": ["A", "ZZ"]}, {"A": "B1"})


def test_broken_ring_is_two_dbscan_pieces_but_one_ring_support():
    e = FX["cases"]["broken_ring"]["expected"]
    P = pts("broken_ring")
    fr = e["ring_fragments_expected"]
    ring_ids = e["support_ids"]["ring"]
    assert len(ring_ids) == e["support_count"]["ring"] == 21
    # (1) base ring only (fixture oracle): fragments A (6 pts) and B (13 pts)
    base = fr["fragment_A_th120_195"] + fr["fragment_B_th240_60"]
    d = dbscan(base, [P[i]["x"] for i in base], [P[i]["y"] for i in base], 25, 2)
    assert d["n_clusters"] == fr["n_fragments"] == 2 and d["noise"] == []
    assert sorted(map(sorted, d["clusters"].values())) == sorted([sorted(fr["fragment_A_th120_195"]), sorted(fr["fragment_B_th240_60"])])
    # (2) full ring support = base + extras BR01/BR02 (on-ring, between R03 neighbours): piece B grows 13 -> 15
    d2 = dbscan(ring_ids, [P[i]["x"] for i in ring_ids], [P[i]["y"] for i in ring_ids], 25, 2)
    assert sorted(len(v) for v in d2["clusters"].values()) == [6, 15] and d2["noise"] == []


def _classify(case, bin_deg):
    P = pts(case)
    ids = FX["cases"][case]["expected"]["support_ids"]["ring"]
    rule = RULE.model_copy(update={"occupancy_bin_deg": bin_deg})
    return classify_ring([P[i]["x"] for i in ids], [P[i]["y"] for i in ids], rule, center=(0.0, 0.0))


def test_ring_support_classification_depends_on_the_occupancy_bin_size():
    """Finding for TBD T-14: points are 15 deg apart, so 10 deg bins leave empty bins.
    Intact ring (24 pts at 15 deg + 2 on-ring extras in occupied bins): 24 of 36 bins = 0.667
    with 10 deg bins; with 30 deg bins all 12 bins are hit. Broken ring with
    30 deg bins: empty bins are [90,120) and [210,240) -> 10/12 = 0.833.
    The test thresholds are not tuned to make this pass; they are provisional."""
    # Occupancy values are threshold-free hand counts; labels are NOT asserted because they depend
    # on the provisional test thresholds (they will change after calibration, TBD T-14/T-16).
    assert _classify("intact", 10)["occupancy"] == pytest.approx(24 / 36)
    assert _classify("intact", 30)["occupancy"] == pytest.approx(1.0)
    c = _classify("broken_ring", 30)
    assert c["occupancy"] == pytest.approx(10 / 12)
    assert c["feature_status"] == "candidate"   # never "matched" while calibrated is False


# ---- detectors -> supports -> summary (E06 full flow on the fixture points; still synthetic) ----
from wafer.detect import detect_groups  # noqa: E402

PROFILE = load_profile(Path(__file__).parent / "profiles/f01_test_profile.yaml")


@pytest.mark.parametrize("case", ["intact", "broken_ring"])
def test_detectors_reproduce_the_fixture_supports_and_totals(case):
    e = FX["cases"][case]["expected"]
    P = pts(case)
    ids = list(P)
    r = detect_groups(ids, [P[i]["x"] for i in ids], [P[i]["y"] for i in ids], PROFILE)
    sup = r["shape_supports"]
    assert sorted(sup["ring"]) == sorted(e["support_ids"]["ring"])
    assert sorted(sup["line"]) == sorted(e["support_ids"]["line"])
    # clusters are not signatures: the dense line chain is a cluster identical to the line support and
    # is tagged by the production code (no fixture-driven selection); the other cluster is the local blob.
    tags = sorted((c["same_as"] or "none") for c in r["clusters"].values())
    assert tags == ["line", "none"]
    sg = r["signature_groups"]
    assert set(sg) == {"ring", "line", "local_" + str(next(k for k, c in r["clusters"].items() if c["same_as"] is None))}
    local = next(v for k, v in sg.items() if k.startswith("local_"))
    assert sorted(local) == sorted(e["support_ids"]["local"])
    s = summarize_groups(sg, {i: P[i]["bin"] for i in ids})
    assert s["unique_union"] == e["unique_union_size"] and s["naive_sum"] == e["naive_sum"]
    assert s["overlap_ids"] == sorted(e["overlap_ids"])
    assert s["union_bin_counts"] == e["bin_unique_totals"]
    # noise is exactly the fixture's brute-force DBSCAN(eps 10, min 3) noise, and stays accounted for
    assert sorted(r["noise"]) == sorted(e["dbscan_whole_wafer_informational"]["eps10_min3"]["noise_ids"])
    assert set(ids) <= {i for v in sg.values() for i in v} | set(r["noise"])
    assert r["ring"]["feature_status"] == "candidate"        # never matched while calibrated is False
    assert r["line"]["feature_status"] == "candidate"
    assert "offset_ring_not_searched" in r["ring"]["limitations"] and r["line"]["trials"] == 300


def test_negative_and_degenerate_inputs_report_scope_not_absence():
    # regular sparse grid: no ring/line support; any "no_match" carries its search scope
    pts_ = [(25 * (i % 6) - 60, 25 * (i // 6) - 40) for i in range(24)]
    r = detect_groups(list(range(24)), [p[0] for p in pts_], [p[1] for p in pts_], PROFILE)
    assert r["ring"]["feature_status"] in ("no_match", "insufficient_data", "candidate")
    assert r["ring"]["search"] == "wafer_center_densest_radius_single" and r["ring"]["limitations"]
    assert set(r["noise"]) | {i for c in r["clusters"].values() for i in c["ids"]} == set(range(24))
    empty = detect_groups([], [], [], PROFILE)
    assert empty["noise"] == [] and empty["clusters"] == {}


def test_detect_is_disabled_by_default_and_reproducible():
    off = PROFILE.model_copy(update={"detect": PROFILE.detect.model_copy(update={"enabled": False})})
    assert detect_groups(["a"], [0.0], [0.0], off) == {"feature_status": "disabled"}
    P = pts("intact")
    ids = list(P)
    a = detect_groups(ids, [P[i]["x"] for i in ids], [P[i]["y"] for i in ids], PROFILE)
    b = detect_groups(ids, [P[i]["x"] for i in ids], [P[i]["y"] for i in ids], PROFILE)
    assert a == b


def _status_keys(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if "status" in str(k) or "state" in str(k):
                yield k
            yield from _status_keys(v, f"{path}/{k}")
    elif isinstance(o, list):
        for v in o:
            yield from _status_keys(v, path)


@pytest.mark.parametrize("case", ["intact", "broken_ring"])
def test_only_contract_status_keys_appear_c15(case):
    P = pts(case)
    ids = list(P)
    r = detect_groups(ids, [P[i]["x"] for i in ids], [P[i]["y"] for i in ids], PROFILE)
    assert r["ring"]["feature_status"] == "candidate"     # the candidate path that used to leak "status"
    assert set(_status_keys(r)) <= {"feature_status", "calc_status"}
