"""klarf_dummy_data (13 SYNTHETIC KLARF 1.8 Record/Field/List files) through the real CLI path.

Input: only klarf_dummy_data/klarf/*.klarf (+ the coverage sidecar where stated).
Oracle: only klarf_dummy_data/manifest.json and klarf_dummy_data/expected/*.csv|json (generated independently
of this code base, seed 20261009; see klarf_dummy_data/README.md). No production function is used to build an
expected value. generation_group (expected CSV) is never fed to the program and never used as an oracle here.
Profile: tests/profiles/dummy_die_local_test_profile.yaml (adapter synthetic-die-local-v1, TEST-ONLY values).
Variant profiles / sidecars / damaged files are written to tmp_path only; repository fixtures are untouched.

Scope (CLAUDE.md 6-9, C20): synthetic adapter + aggregation checks. Not a real tool-adapter validation, not a
shape-classification evaluation, not a UI/E2E run.

N/A here, by design: shape labels (ring / line / local / mixed). manifest "generation_intent" is a pattern
authoring intent, explicitly "not the classifier's prediction" (README: classifier_output_validated=false), and
the ring/line thresholds are uncalibrated (TBD T-17/T-21/T-22). Asserting a label would turn an intent into a
golden answer, so only count / partition invariants of the detectors are checked (T8).

Links: E01 E02 E03 E04 E06(partition only) E07 E08 E09 E11 E13 E16(CLI JSON<->CSV only);
C01 C02 C03 C04 C06 C08 C09 C10 C11 C14 C15 C19 C20; P1-01 P1-02 P1-03 P2-05.
"""
import csv
import hashlib
import json
import math
from pathlib import Path

import pytest
import yaml

from wafer.cli import main

ROOT = Path(__file__).resolve().parent.parent
DD = ROOT / "klarf_dummy_data"
KL = DD / "klarf"
EXP = DD / "expected"
SIDECAR = DD / "synthetic_profile.json"
PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"
F01_KLF = ROOT / "tests/fixtures/klarf/f01.klf"
F01_PROFILE = ROOT / "tests/profiles/f01_test_profile.yaml"
E07 = json.loads((ROOT / "tests/fixtures/e07_lift_pin/e07_lift_pin.json").read_text(encoding="utf-8"))

MANIFEST = {c["name"]: c for c in json.loads((DD / "manifest.json").read_text(encoding="utf-8"))["cases"]}
CASES = list(MANIFEST)
NONEMPTY = [c for c in CASES if MANIFEST[c]["count"] > 0]
F01_FAMILY = ["F01_counts", "F01_up", "F01_left", "F01_right"]
ZONE_KEY = {"E1": "E1", "E2": "E2", "inner_100mm": "inner", "boundary_100mm": "band"}   # oracle -> result key


def expected_rows(case):
    with open(EXP / f"{case}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def event_keys(case):
    """Contract: event key = '<record order, 1-based>:<DEFECTID>' (ingest); built here from the oracle CSV."""
    return [f"{k}:{int(r['defect_id'])}" for k, r in enumerate(expected_rows(case), start=1)]


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cli(klarf, tmp, profile=PROFILE, coverage=None, csv_dir=True):
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / "o.json"
    argv = [str(klarf), "--profile", str(profile), "--out", str(out)]
    if csv_dir:
        argv += ["--csv-dir", str(tmp / "csv")]
    if coverage is not None:
        argv += ["--coverage", str(coverage)]
    code = main(argv)
    return code, json.loads(out.read_text(encoding="utf-8")), tmp / "csv"


_RUNS = {}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Cached default runs: dummy profile, CSV export, coverage omitted (unknown) unless cov=True (sidecar)."""
    def _run(case, cov=False):
        key = (case, cov)
        if key not in _RUNS:
            tmp = tmp_path_factory.mktemp(f"{case}_{'cov' if cov else 'nocov'}")
            _RUNS[key] = cli(KL / f"{case}.klarf", tmp, coverage=SIDECAR if cov else None)
        return _RUNS[key]
    return _run


def variant_profile(tmp_path, mutate, name="variant.yaml"):
    d = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    mutate(d)
    p = tmp_path / name
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    return p


def variant_klarf(tmp_path, case, old, new, name="variant.klarf"):
    text = (KL / f"{case}.klarf").read_bytes().decode("utf-8")
    assert old in text, f"variant anchor not found: {old!r}"   # guards against a silent no-op variant
    p = tmp_path / name
    p.write_bytes(text.replace(old, new, 1).encode("utf-8"))
    return p


# ---------------------------------------------------------------- T1: counts, order, hash, bins, clock (E01/E09)
@pytest.mark.parametrize("case", CASES)
def test_t1_counts_order_hash_bins_clock_match_manifest(case, run):
    """Per file: n_parsed = n_included = manifest count (no exclusions in this set), DEFECTID order kept, input
    sha256 = manifest file_sha256, bin totals, center, strict 12-sector clock, and the per-defect clock in
    defects.csv equal the oracle CSV clock_hour (half-open sectors [c-15, c+15), center r < 1 mm).

    sectors_clock_tolerant is deliberately NOT compared: it counts points within +-tol of a boundary in both
    neighbouring sectors (T-18) and is not a partition; manifest clock_counts is the strict partition only."""
    m, rows = MANIFEST[case], expected_rows(case)
    code, o, csvd = run(case)
    assert code == 0 and o["job_status"] == "succeeded"
    r = o["result"]
    # oracle self-consistency (manifest vs expected/<case>.json vs CSV rows); no program output involved
    ej = json.loads((EXP / f"{case}.json").read_text(encoding="utf-8"))
    for k in ("count", "bin_counts", "center_count", "clock_counts", "zone_support_ids", "file_sha256"):
        assert ej[k] == m[k], k
    assert len(rows) == m["count"]
    assert hashlib.sha256((KL / f"{case}.klarf").read_bytes()).hexdigest() == m["file_sha256"]

    assert r["provenance"]["source_sha256"] == m["file_sha256"]
    assert r["provenance"]["adapter"] == "synthetic-die-local-v1"
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (m["count"], m["count"], 0)
    assert r["bin_totals"] == m["bin_counts"]                 # die-local adapter keeps "1"/"2"/"3" (T-04)
    assert r["center"] == m["center_count"]
    assert r["sectors_clock"] == m["clock_counts"]
    d = read_csv(csvd / "defects.csv")
    assert [x["defect_id"] for x in d] == event_keys(case)    # record order + DEFECTID, nothing merged/reordered
    assert all(x["included"] == "True" for x in d)
    assert [x["clock"] for x in d] == [e["clock_hour"] for e in rows]
    assert [x["bin"] for x in d] == [e["classification_bin"] for e in rows]


# ---------------------------------------------------------------- T2: coordinates, notch variants (E02, C03)
@pytest.mark.parametrize("case", CASES)
def test_t2_standard_coordinates_match_oracle(case, run):
    """Standard frame (mm, center origin, +X right, +Y up, notch 6 o'clock) within 1e-7 mm of the oracle CSV.
    Oracle CSV and .klarf both carry 1e-3 um resolution, so 1e-7 mm only absorbs float arithmetic."""
    d = read_csv(run(case)[2] / "defects.csv")
    for got, exp in zip(d, expected_rows(case), strict=True):
        assert float(got["x_mm"]) == pytest.approx(float(exp["x_mm"]), abs=1e-7), got["defect_id"]
        assert float(got["y_mm"]) == pytest.approx(float(exp["y_mm"]), abs=1e-7), got["defect_id"]


def test_t2_f01_notch_variants_aggregate_identically_without_double_rotation(run):
    """F01_up/left/right are F01 rotated in the file (notch UP/LEFT/RIGHT); one rotation to notch DOWN must give
    the F01 aggregates (plan 19.2: 8 / B1..3 = 3,3,2 / center 1 / 12h 1, 3h 4, 6h 1, 9h 1) and D01 at (0, 50).
    A second rotation would put D01 at (0,-50) for UP, (+-50, 0) for LEFT/RIGHT."""
    plan_f01 = {"count": 8, "bins": {"1": 3, "2": 3, "3": 2}, "center": 1,
                "clock": {**{str(h): 0 for h in range(1, 13)}, "12": 1, "3": 4, "6": 1, "9": 1}}
    ref = None
    for case in F01_FAMILY:
        assert MANIFEST[case]["count"] == plan_f01["count"]
        code, o, csvd = run(case)
        r = o["result"]
        assert code == 0 and r["n_included"] == plan_f01["count"]
        assert r["bin_totals"] == plan_f01["bins"] and r["center"] == plan_f01["center"]
        assert r["sectors_clock"] == plan_f01["clock"]
        d1 = read_csv(csvd / "defects.csv")[0]
        assert d1["defect_id"] == "1:1"
        assert (float(d1["x_mm"]), float(d1["y_mm"])) == pytest.approx((0.0, 50.0), abs=1e-7), case
        agg = (r["bin_totals"], r["center"], r["sectors_clock"], r["bin_sector"], r["zones"])
        ref = ref or agg
        assert agg == ref, case


# ---------------------------------------------------------------- T3: rejected conventions (C03 C04 C20, E02/E10)
def _dummy_variants():
    f = "F01_counts"
    return [
        pytest.param(f, "Field DieOrigin 2 {0, 0}", "Field DieOrigin 2 {10, 0}", id="die_origin_nonzero"),
        pytest.param(f, 'Field OrientationMarkLocation 1 {"DOWN"}', 'Field OrientationMarkLocation 1 {"FLAT"}',
                     id="notch_location_FLAT"),
        pytest.param(f, "6 9000.0 0.0 29 15", "6 10000.0 0.0 29 15", id="xrel_equals_pitch"),
        pytest.param(f, "7 8000.0 0.0 29 15", "7 8000.0 10000.5 29 15", id="yrel_above_pitch"),
        pytest.param(f, "6 9000.0 0.0 29 15", "6 -1.0 0.0 29 15", id="xrel_negative"),
        pytest.param(f, "Field DiePitch 2 {10000, 10000}", "Field DiePitch 2 {0, 10000}", id="pitch_zero"),
        pytest.param(f, 'Field SampleOrientationMarkType 1 {"NOTCH"}', 'Field SampleOrientationMarkType 1 {"FLAT"}',
                     id="marktype_FLAT"),   # mark type not guessed (CLAUDE.md 4.2/4.3, T-03)
    ]


@pytest.mark.parametrize("case,old,new", _dummy_variants())
def test_t3_unverified_header_or_offsets_are_rejected_not_guessed(case, old, new, tmp_path):
    code, o, _ = cli(variant_klarf(tmp_path, case, old, new), tmp_path, csv_dir=False)
    assert code == 3 and o["job_status"] == "failed" and o["error"] == "UNSUPPORTED_ADAPTER"
    assert "result" not in o


def test_t3_side_other_than_front_profile_is_rejected(tmp_path):
    p = variant_profile(tmp_path, lambda d: d["coordinates"].update(side_convention="back"))
    code, o, _ = cli(KL / "F01_counts.klarf", tmp_path, profile=p, csv_dir=False)
    assert code == 3 and o["error"] == "UNSUPPORTED_ADAPTER" and "result" not in o


def test_t3_dummy_file_with_f01_profile_adapter_is_rejected(tmp_path):
    """f01_test_profile selects the single-die adapter (adapter_id "synthetic-um-die00-notch-down", explicit since
    T-02 2026-10-09; was null); a 1.8 die-local file has no
    CoordinatesMirrored, multi-die indices and center 150000 um -> must not be silently mis-mapped."""
    code, o, _ = cli(KL / "F01_counts.klarf", tmp_path, profile=F01_PROFILE, csv_dir=False)
    assert code == 3 and o["error"] == "UNSUPPORTED_ADAPTER" and "result" not in o


def test_t3_flat_f01_file_with_die_local_profile_is_rejected(tmp_path):
    """tests/fixtures/klarf/f01.klf is wafer-centred um (negative XREL); die-local needs XREL/YREL in [0, pitch)."""
    code, o, _ = cli(F01_KLF, tmp_path, profile=PROFILE, csv_dir=False)
    assert code == 3 and o["error"] == "UNSUPPORTED_ADAPTER" and "result" not in o


# ---------------------------------------------------------------- T4: boundary points per ID (E08, C10/C12)
def _boundary_ids():
    """Oracle-side selection: records whose oracle-CSV angle is within 0.5 deg of a sector boundary
    (15 + 30k deg) - includes the points generated exactly on 15/45/.../345."""
    out = []
    for case in NONEMPTY:
        for k, e in enumerate(expected_rows(case), start=1):
            x, y = float(e["x_mm"]), float(e["y_mm"])
            if math.hypot(x, y) < 1:
                continue
            t = math.degrees(math.atan2(x, y)) % 360.0
            if min((t - 15) % 30, 30 - (t - 15) % 30) < 0.5:
                out.append((case, f"{k}:{int(e['defect_id'])}", e["clock_hour"]))
    return out


BOUNDARY = _boundary_ids()


def test_t4_boundary_points_get_the_oracle_clock_hour(run):
    assert len(BOUNDARY) >= 50                     # ring/edge_ring/mixed each carry 12 exact-boundary points
    for case, key, hour in BOUNDARY:
        d = {x["defect_id"]: x for x in read_csv(run(case)[2] / "defects.csv")}
        assert d[key]["clock"] == hour, (case, key)


def test_t4_f01_ids_6_7_8_zones(run):
    """README / plan 19.2: ID6 (r 149, edge 1) in E1 [0,2); ID7 (r 148, edge 2) in E2 [2,5), not E1;
    ID8 (r 100) in the closed 100 mm band [99, 101] and not in inner [0, 100)."""
    zid = MANIFEST["F01_counts"]["zone_support_ids"]
    assert (zid["E1"], zid["E2"], zid["boundary_100mm"]) == ([6], [7], [8]) and 8 not in zid["inner_100mm"]
    for case in F01_FAMILY:
        z = run(case)[1]["result"]["zones"]
        assert z["E1"] == ["6:6"] and z["E2"] == ["7:7"] and z["band"] == ["8:8"], case
        assert "8:8" not in z["inner"] and "7:7" not in z["E1"], case


# ---------------------------------------------------------------- T5: zone ID sets and union (E08, C11)
@pytest.mark.parametrize("case", CASES)
def test_t5_zone_ids_equal_oracle_and_union_is_unique(case, run):
    r = run(case)[1]["result"]
    oracle = MANIFEST[case]["zone_support_ids"]
    assert set(r["zones"]) == set(ZONE_KEY.values())
    for ok, rk in ZONE_KEY.items():
        assert sorted(int(i.split(":")[1]) for i in r["zones"][rk]) == sorted(oracle[ok]), (case, rk)
    assert r["zone_union_unique"] == len({i for ids in oracle.values() for i in ids})


# ---------------------------------------------------------------- T6: empty vs damaged 1.8 (E03, E13, C15)
def test_t6_empty_list_is_a_successful_zero(run):
    code, o, _ = run("empty")
    r = o["result"]
    assert code == 0 and o["job_status"] == "succeeded"
    assert (r["n_parsed"], r["n_included"], r["center"], r["zone_union_unique"]) == (0, 0, 0, 0)
    assert r["bin_totals"] == {} and all(v == 0 for v in r["sectors_clock"].values())
    assert r["pattern_summary"] == ["no_detected_defect"]


_EOF_TAIL = "    }\n   }\n  }\n }\n}\nEndOfFile;\n"


@pytest.mark.parametrize("case,old,new", [
    pytest.param("F01_counts", "Data 8", "Data 9", id="data_count_too_high"),
    pytest.param("F01_counts", "Data 8", "Data 7", id="data_count_too_low"),
    pytest.param("F01_counts", "Columns 14 {", "Columns 13 {", id="columns_count_mismatch"),
    pytest.param("F01_counts", "1 1 0 1 1 ;\n     2", "1 1 0 1 1\n     2", id="row_without_semicolon"),
    pytest.param("F01_counts", "4.0 2.0 1 1 0 1 1 ;\n     2", "4.0 1 1 0 1 1 ;\n     2", id="row_missing_field"),
    pytest.param("F01_counts", "6 9000.0 0.0", "6 9OOO.0 0.0", id="non_numeric"),
    pytest.param("F01_counts", 'Record FileRecord "1.8"', 'Record FileRecord "1.9"', id="unsupported_version"),
    pytest.param("F01_counts", _EOF_TAIL, "    }\n   }\n", id="truncated_no_eof"),
    pytest.param("F01_counts", "  }\n }\n}\nEndOfFile;", " }\n}\nEndOfFile;", id="unbalanced_braces"),
    pytest.param("empty", "Data 0", "Data 1", id="empty_declares_one_row"),
])
def test_t6_damaged_18_files_are_invalid_input_not_zero(case, old, new, tmp_path):
    code, o, _ = cli(variant_klarf(tmp_path, case, old, new), tmp_path, csv_dir=False)
    assert code == 3 and o["job_status"] == "failed"
    assert o["error"] == "INVALID_INPUT" and o["data_quality_status"] == "invalid"
    assert "result" not in o


# ---------------------------------------------------------------- T7: coverage (E11, C06)
def _radial_oracle(case, R=150.0, step=50.0):
    """Independent: counts per [0,50), [50,100), [100,150] from oracle CSV radii; area = pi(hi^2 - lo^2)."""
    rs = [math.hypot(float(e["x_mm"]), float(e["y_mm"])) for e in expected_rows(case)]
    edges = [0.0, step, 2 * step, R]
    out = []
    for k, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        last = k == len(edges) - 2
        n = sum(1 for v in rs if lo <= v and (v <= hi if last else v < hi))
        out.append((n, math.pi * (hi * hi - lo * lo)))
    return out


@pytest.mark.parametrize("case", ["F01_counts", "uniform_random"])
def test_t7_density_null_without_coverage_and_independent_with_sidecar(case, run):
    exp = _radial_oracle(case)
    r = run(case)[1]["result"]
    assert r["provenance"]["coverage"]["status"] == "unknown"
    assert [x["count"] for x in r["radial_density"]["rows"]] == [n for n, _ in exp]
    assert all(x["density_per_mm2"] is None and x["area_mm2"] is None for x in r["radial_density"]["rows"])
    assert r["clark_evans"]["calc_status"] == "insufficient_data"

    rc = run(case, cov=True)[1]["result"]
    cov = rc["provenance"]["coverage"]
    assert cov["status"] == "declared_by_sidecar" and cov["inspected_radius_mm"] == 150
    assert cov["sidecar_sha256"] == hashlib.sha256(SIDECAR.read_bytes()).hexdigest()
    rows = rc["radial_density"]["rows"]
    for row, (n, area) in zip(rows, exp, strict=True):
        assert row["count"] == n
        assert row["area_mm2"] == pytest.approx(area, rel=1e-12)
        assert row["density_per_mm2"] == pytest.approx(n / area, rel=1e-12)
    assert rc["clark_evans"]["calc_status"] == "computed"


def _write_sidecar(tmp_path, radius):
    p = tmp_path / f"cov_{radius}.json"
    p.write_text(json.dumps({"coverage": {"shape": "full_disk", "radius_mm": radius,
                                          "source": "TEST-ONLY partial coverage"}}), encoding="utf-8")
    return p


_EDGE_TEMPLATE = {"enabled": True, "template_id": "T7-EDGE-TEST-ONLY", "radius_band_mm": [142, 148],
                  "phase_deg": 0, "angular_tolerance_deg": 10, "radial_tolerance_mm": 3,
                  "min_support_per_lobe": 3, "min_lobe_contrast": 3.0}


def test_t7_partial_coverage_marks_the_outer_annulus_uninspected(tmp_path):
    """Sidecar radius 140 -> (140, 150] uninspected. A TEST-ONLY lift-pin template whose band [142,148) lies
    there cannot conclude absence: insufficient_data with not_inspected lobes, while the same input with a
    full-disk sidecar (150) gives no_match. threefold.klarf has no point beyond r 63, so only coverage differs.
    F01 under radius 140: the [100,150] annulus holds r 148/149 outside the window -> density null, not 0."""
    p = variant_profile(tmp_path, lambda d: d["signatures"].update(lift_pin=dict(_EDGE_TEMPLATE)))
    code, o, _ = cli(KL / "threefold.klarf", tmp_path / "a", profile=p, coverage=_write_sidecar(tmp_path, 140),
                     csv_dir=False)
    lp = o["result"]["lift_pin"]
    assert code == 0 and lp["feature_status"] == "insufficient_data"
    assert [lb["coverage"] for lb in lp["lobes"]] == ["not_inspected"] * 3
    assert o["result"]["provenance"]["coverage"]["inspected_radius_mm"] == 140
    code, o, _ = cli(KL / "threefold.klarf", tmp_path / "b", profile=p, coverage=SIDECAR, csv_dir=False)
    assert code == 0 and o["result"]["lift_pin"]["feature_status"] == "no_match"

    code, o, _ = cli(KL / "F01_counts.klarf", tmp_path / "c", coverage=_write_sidecar(tmp_path, 140), csv_dir=False)
    last = o["result"]["radial_density"]["rows"][-1]
    assert code == 0 and last["count"] == 3 and last["density_per_mm2"] is None and last["reason"]


# ---------------------------------------------------------------- T8: noise / cluster partition (E04, C08, C11)
@pytest.mark.parametrize("case", CASES)
def test_t8_noise_and_clusters_partition_the_included_events(case, run):
    r = run(case)[1]["result"]
    det, keys = r["detect"], set(event_keys(case))
    noise = det["noise"]
    clustered = [i for c in det["clusters"].values() for i in c["ids"]]
    assert len(noise) + len(clustered) == len(set(noise) | set(clustered))   # pairwise disjoint
    assert set(noise) | set(clustered) == keys and len(keys) == r["n_included"]
    assert det["summary"]["unique_union"] <= r["n_included"]
    assert set(det["summary"]["membership"]) <= keys


# ---------------------------------------------------------------- T9: lift-pin template (E07, C09, C19)
def _e07_profile(tmp_path):
    t = E07["_meta"]["template"]   # TEST-ONLY template (T-08/T-25), same values as tests/test_e07_lift_pin.py
    lp = {"enabled": True, "template_id": t["template_id"], "frame": t["frame"], "expected_lobes": t["expected_lobes"],
          "spacing_deg": t["spacing_deg"], "radius_band_mm": t["radius_band_mm"], "phase_deg": t["phase_deg"],
          "angular_tolerance_deg": t["angular_tolerance_deg"], "radial_tolerance_mm": t["radial_tolerance_mm"],
          "min_support_per_lobe": t["min_support_per_lobe"], "min_lobe_contrast": 3.0}
    return variant_profile(tmp_path, lambda d: d["signatures"].update(lift_pin=lp), name="e07.yaml")


def test_t9_threefold_is_candidate_never_matched(tmp_path):
    p = _e07_profile(tmp_path)
    for sub, cov in (("full", SIDECAR), ("unknown", None)):
        code, o, _ = cli(KL / "threefold.klarf", tmp_path / sub, profile=p, coverage=cov, csv_dir=False)
        lp = o["result"]["lift_pin"]
        assert code == 0 and lp["feature_status"] == "candidate" and lp["match_type"] == "threefold_match", sub
        assert [lb["n"] for lb in lp["lobes"]] == [40, 40, 40]   # oracle: 40 points within +-3 deg of 0/120/240


def test_t9_single_lobe_is_no_match_with_coverage_and_insufficient_without(tmp_path):
    p = _e07_profile(tmp_path)
    code, o, _ = cli(KL / "single_lobe_counterexample.klarf", tmp_path / "full", profile=p, coverage=SIDECAR,
                     csv_dir=False)
    assert code == 0 and o["result"]["lift_pin"]["feature_status"] == "no_match"
    code, o, _ = cli(KL / "single_lobe_counterexample.klarf", tmp_path / "unk", profile=p, csv_dir=False)
    assert code == 0 and o["result"]["lift_pin"]["feature_status"] == "insufficient_data"


# ---------------------------------------------------------------- JSON <-> CSV (E16 CLI part only, C14)
@pytest.mark.parametrize("case", ["F01_counts", "F01_left", "mixed", "uniform_random"])
def test_csv_exports_equal_json_and_independent_bin_by_clock(case, run):
    _, o, csvd = run(case)
    r = o["result"]
    d = read_csv(csvd / "defects.csv")
    assert len(d) == r["n_parsed"]
    clocks = [x["clock"] for x in d]
    assert {str(h): clocks.count(str(h)) for h in range(1, 13)} == r["sectors_clock"]
    assert clocks.count("center") == r["center"]
    bins = [x["bin"] for x in d]
    assert {b: bins.count(b) for b in set(bins)} == r["bin_totals"]
    zones_csv = {z: [] for z in r["zones"]}
    for x in d:
        for z in json.loads(x["zones"]):
            zones_csv[z].append(x["defect_id"])
    assert zones_csv == r["zones"]

    sp = read_csv(csvd / "spatial_counts.csv")
    get = lambda t: {s["key"]: int(s["count"]) for s in sp if s["table"] == t}
    assert get("bin_total") == r["bin_totals"]
    assert get("sector_strict") == r["sectors_clock"] and get("center") == {"center": r["center"]}
    assert get("zone") == {z: len(v) for z, v in r["zones"].items()}
    assert get("zone_union") == {"unique": r["zone_union_unique"]}

    bs = {row["bin"]: row for row in read_csv(csvd / "bin_sector.csv")}
    cols = [str(h) for h in range(1, 13)] + ["center"]
    assert {b: {c: int(row[c]) for c in cols} for b, row in bs.items()} == r["bin_sector"]
    # independent bin x clock from the oracle CSV (classification_bin, clock_hour)
    oracle = {}
    for e in expected_rows(case):
        row = oracle.setdefault(e["classification_bin"], {c: 0 for c in cols})
        row[e["clock_hour"]] += 1
    assert {b: {c: int(row[c]) for c in cols} for b, row in bs.items()} == oracle
    assert all(int(row["total"]) == sum(oracle[b].values()) for b, row in bs.items())


# ---------------------------------------------------------------- reviewer follow-ups (C03 C05 C17, E12/E13)
PROFILE_DL, DUMMY = PROFILE, DD
@pytest.mark.parametrize("old,new,label", [
    ('   Field DeviceID 1 {"SYNTHETIC_ONLY"}', '   Field DeviceID 1 {"SYNTHETIC_ONLY"}\n   Field DiePitch 2 {20000, 20000}', "dup_field"),
    ("    Data 8", "    Columns 14 {int32 DEFECTID, float XREL, float YREL, int32 XINDEX, int32 YINDEX, float XSIZE, float YSIZE, float DEFECTAREA, float DSIZE, int32 CLASSNUMBER, int32 TEST, int32 CLUSTERNUMBER, int32 ROUGHBINNUMBER, int32 FINEBINNUMBER}\n    Data 8", "second_columns"),
])
def test_ambiguous_18_structures_are_invalid_input(old, new, label, tmp_path):
    from wafer import ingest
    src = (DUMMY / "klarf" / "F01_counts.klarf").read_text(encoding="utf-8")
    assert old in src, label
    p = tmp_path / f"{label}.klarf"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ingest.KlarfError):
        ingest.read_klarf(p)


def test_second_data_block_is_invalid_input(tmp_path):
    from wafer import ingest
    src = (DUMMY / "klarf" / "F01_counts.klarf").read_text(encoding="utf-8")
    lines = src.split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.strip().startswith("Data "))
    j = next(k for k in range(i, len(lines)) if lines[k].strip() == "}")
    block = lines[i:j + 1]
    p = tmp_path / "two_data.klarf"
    p.write_text("\n".join(lines[:j + 1] + block + lines[j + 1:]), encoding="utf-8")
    with pytest.raises(ingest.KlarfError):
        ingest.read_klarf(p)


# E11-UP (T-05, approved 2026-10-09): exit 2 / CONFIG_INVALID unchanged; out["reason"] now names the cause.
@pytest.mark.parametrize("label,payload,reason", [
    ("not_json", "{", "coverage_syntax_error"),
    ("no_coverage_key", "{}", "coverage_syntax_error"),
    ("coverage_not_object", '{"coverage": 5}', "coverage_syntax_error"),
    ("shape_partial", '{"coverage": {"shape": "annulus", "radius_mm": 150}}', "coverage_unsupported_shape"),
    ("radius_above_R", '{"coverage": {"shape": "full_disk", "radius_mm": 151}}', "coverage_invalid_value"),
    ("radius_zero", '{"coverage": {"shape": "full_disk", "radius_mm": 0}}', "coverage_invalid_value"),
    ("radius_nan", '{"coverage": {"shape": "full_disk", "radius_mm": NaN}}', "coverage_invalid_value"),
])
def test_bad_coverage_sidecar_is_config_invalid_not_a_guess(label, payload, reason, tmp_path):
    from wafer.cli import main
    side = tmp_path / f"{label}.json"
    side.write_text(payload, encoding="utf-8")
    out = tmp_path / "o.json"
    code = main([str(DUMMY / "klarf" / "F01_counts.klarf"), "--profile", str(PROFILE_DL), "--out", str(out),
                 "--coverage", str(side)])
    o = json.loads(out.read_text(encoding="utf-8"))
    assert code == 2 and o["error"] == "CONFIG_INVALID" and "result" not in o
    assert o["reason"] == reason


def test_unknown_adapter_id_is_config_invalid(tmp_path):
    import yaml
    from wafer.profile import ConfigInvalid, parse_profile
    d = yaml.safe_load(open(PROFILE_DL, encoding="utf-8"))
    d["coordinates"]["adapter_id"] = "made-up"
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "coordinates.adapter_id" in e.value.keys


def test_mirror_flag_other_than_no_is_rejected(tmp_path):
    from wafer.cli import main
    src = (DUMMY / "klarf" / "F01_counts.klarf").read_text(encoding="utf-8")
    old = '   Field DeviceID 1 {"SYNTHETIC_ONLY"}'
    assert old in src
    p = tmp_path / "mirror.klarf"
    p.write_text(src.replace(old, old + '\n   Field CoordinatesMirrored 1 {"YES"}', 1), encoding="utf-8")
    out = tmp_path / "o.json"
    assert main([str(p), "--profile", str(PROFILE_DL), "--out", str(out)]) == 3
    assert json.loads(out.read_text(encoding="utf-8"))["error"] == "UNSUPPORTED_ADAPTER"


def test_sidecar_file_name_does_not_change_the_analysis_key(tmp_path):
    import shutil
    from wafer.cli import main
    a, b = tmp_path / "a.json", tmp_path / "renamed_sidecar.json"
    shutil.copy(DUMMY / "synthetic_profile.json", a)
    shutil.copy(DUMMY / "synthetic_profile.json", b)
    db, keys = tmp_path / "w.db", []
    for side in (a, b):
        out = tmp_path / f"o_{side.stem}.json"
        assert main([str(DUMMY / "klarf" / "F01_counts.klarf"), "--profile", str(PROFILE_DL), "--out", str(out),
                     "--coverage", str(side), "--db", str(db)]) == 0
        keys.append(json.loads(out.read_text(encoding="utf-8"))["store"])
    assert keys[0]["analysis_key"] == keys[1]["analysis_key"] and keys[1]["created"] is False


# ---------------------------------------------------------------- notch position missing (approved 2026-10-09, T-03)
# E10-UP / E02-NONOTCH, C03 C04 C15: no OrientationMarkLocation -> succeeded with a partial result. Radius-only
# quantities (counts, bins, center, zones, radial counts) are rotation invariant, so the oracle of the same file
# applies; physical clock / phase are withheld (null + status), never 0 and never a guessed rotation.
def _drop_notch(tmp_path, case):
    text = (KL / f"{case}.klarf").read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    kept = [ln for ln in lines if "Field OrientationMarkLocation" not in ln]
    assert len(lines) - len(kept) == 1, case          # exactly the notch line removed; mark type NOTCH stays
    p = tmp_path / f"{case}_nonotch.klarf"
    p.write_bytes("".join(kept).encode("utf-8"))
    return p


@pytest.mark.parametrize("case", ["F01_counts", "F01_up"])
def test_e10_up_missing_notch_returns_radial_partial_result(case, tmp_path):
    """Independent oracle: plan 19.2 F01 (8 / bins 1,2,3 = 3,3,2 / center 1 / E1={6} E2={7} inner={1..5} band={8}),
    cross-checked with manifest zone_support_ids; per-defect r_mm equals hypot of the oracle CSV x/y (rotation
    invariant, so it holds for F01_up kept in its raw unrotated frame)."""
    m = MANIFEST[case]
    zid = m["zone_support_ids"]
    assert (sorted(zid["E1"]), sorted(zid["E2"]), sorted(zid["inner_100mm"]), sorted(zid["boundary_100mm"])) ==         ([6], [7], [1, 2, 3, 4, 5], [8])
    code, o, csvd = cli(_drop_notch(tmp_path, case), tmp_path)
    r = o["result"]
    assert code == 0 and o["job_status"] == "succeeded"
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (8, 8, 0)
    assert r["bin_totals"] == {"1": 3, "2": 3, "3": 2} == m["bin_counts"]
    assert r["center"] == 1 == m["center_count"]
    for ok, rk in ZONE_KEY.items():
        assert sorted(int(i.split(":")[1]) for i in r["zones"][rk]) == sorted(zid[ok]), (case, rk)
    assert [x["count"] for x in r["radial_density"]["rows"]] == [n for n, _ in _radial_oracle(case)]
    assert r["orientation_status"] == "unknown"
    assert r["clock_status"] == {"status": "insufficient_data", "reason": "orientation_unknown"}
    for k in ("sectors_clock", "sectors_clock_tolerant", "bin_sector", "boundary_ambiguous"):
        assert r[k] is None, (case, k)
    assert r["detect"]["frame"] == "unregistered"
    assert r["provenance"]["source_sha256"] != m["file_sha256"]        # a variant, not the manifest file
    d = read_csv(csvd / "defects.csv")
    assert [x["defect_id"] for x in d] == event_keys(case)
    assert all(x["clock"] == "" for x in d)                            # withheld, not "center"/0
    for got, exp in zip(d, expected_rows(case), strict=True):
        assert float(got["r_mm"]) == pytest.approx(math.hypot(float(exp["x_mm"]), float(exp["y_mm"])), abs=1e-7)
    sp = {(s["table"], s["key"]): s for s in read_csv(csvd / "spatial_counts.csv")}
    for t in ("sector_strict", "sector_tolerant"):
        assert sp[(t, "*")]["count"] == "" and sp[(t, "*")]["reason"] == "insufficient_data: orientation_unknown"
    assert sp[("center", "center")]["count"] == "1"
    bs = read_csv(csvd / "bin_sector.csv")
    assert len(bs) == 1 and bs[0]["bin"] == "" and bs[0]["status"] == "insufficient_data: orientation_unknown"


def test_e10_up_notch_present_run_reports_registered_orientation(run):
    r = run("F01_counts")[1]["result"]
    assert r["orientation_status"] == "notch_registered" and r["clock_status"]["status"] == "computed"
    assert r["detect"]["frame"] != "unregistered"


def test_e07_up_lift_pin_is_insufficient_without_notch(tmp_path):
    """Lift-pin phase is defined relative to the notch: enabled template + missing notch -> insufficient_data /
    orientation_unknown (the same file with the notch is 'candidate', test_t9 above)."""
    code, o, _ = cli(_drop_notch(tmp_path, "threefold"), tmp_path, profile=_e07_profile(tmp_path), csv_dir=False)
    assert code == 0 and o["result"]["lift_pin"] == {"feature_status": "insufficient_data",
                                                     "reason": "orientation_unknown"}


# ---------------------------------------------------------------- review follow-ups (2026-10-09, T-03 / E10)
@pytest.mark.parametrize("case", ["ring", "line"])
def test_e10_up_no_direction_leaks_from_measurements_when_notch_is_unknown(case, tmp_path):
    """Notch line removed from a file whose ring/line is a candidate: rotation-invariant values (label, radius,
    thickness, length, support ids) stay; direction / position keys are null with a reason (plan 16.1, E10)."""
    from wafer.cli import main
    from wafer.cli import ORIENTATION_KEYS
    src = (DD / "klarf" / f"{case}.klarf").read_text(encoding="utf-8")
    old = '   Field OrientationMarkLocation 1 {"DOWN"}\n'
    assert old in src
    p = tmp_path / f"{case}_nonotch.klarf"
    p.write_text(src.replace(old, "", 1), encoding="utf-8")
    outs = {}
    for name, f in (("ref", DD / "klarf" / f"{case}.klarf"), ("nonotch", p)):
        o = tmp_path / f"{name}.json"
        assert main([str(f), "--profile", str(PROFILE), "--out", str(o)]) == 0
        outs[name] = json.loads(o.read_text(encoding="utf-8"))["result"]["detect"]
    ref, nn = outs["ref"][case], outs["nonotch"][case]
    assert nn["feature_status"] == ref["feature_status"] == "candidate"
    assert sorted(nn["support_ids"]) == sorted(ref["support_ids"])
    m = nn["measurement"]
    for k in ORIENTATION_KEYS:
        if k in m:
            assert m[k] is None, k
            assert ref["measurement"][k] is not None, k
    assert m["withheld"]["reason"] == "orientation_unknown"
    assert outs["nonotch"]["frame"] == "unregistered"


def test_e10_up_csv_manifest_records_the_frame(tmp_path):
    from wafer.cli import main
    src = (DD / "klarf" / "F01_counts.klarf").read_text(encoding="utf-8")
    p = tmp_path / "nonotch.klarf"
    p.write_text(src.replace('   Field OrientationMarkLocation 1 {"DOWN"}\n', "", 1), encoding="utf-8")
    assert main([str(p), "--profile", str(PROFILE), "--out", str(tmp_path / "o.json"), "--csv-dir", str(tmp_path / "c")]) == 0
    m = json.loads((tmp_path / "c" / "manifest.json").read_text(encoding="utf-8"))
    assert m["orientation_status"] == "unknown" and m["coordinate_frame"] == "unregistered"


@pytest.mark.parametrize("key,value,expect", [
    ("source_units", None, "coordinates.source_units"),
    ("side_convention", None, "coordinates.side_convention"),
])
def test_e12_up_adapter_required_coordinate_keys_are_config_invalid(key, value, expect, tmp_path):
    import yaml
    from wafer.cli import main
    d = yaml.safe_load(open(PROFILE, encoding="utf-8"))
    d["coordinates"][key] = value
    prof = tmp_path / "p.yaml"
    prof.write_text(yaml.safe_dump(d), encoding="utf-8")
    out = tmp_path / "o.json"
    assert main([str(DD / "klarf" / "F01_counts.klarf"), "--profile", str(prof), "--out", str(out)]) == 2
    o = json.loads(out.read_text(encoding="utf-8"))
    assert o["error"] == "CONFIG_INVALID" and expect in o["keys"]


def test_legacy_adapter_checks_the_declared_unit(tmp_path):
    import yaml
    from wafer.cli import main
    f01p = ROOT / "tests/profiles/f01_test_profile.yaml"
    d = yaml.safe_load(open(f01p, encoding="utf-8"))
    d["coordinates"]["source_units"] = "mm"
    prof = tmp_path / "p.yaml"
    prof.write_text(yaml.safe_dump(d), encoding="utf-8")
    out = tmp_path / "o.json"
    assert main([str(ROOT / "tests/fixtures/klarf/f01.klf"), "--profile", str(prof), "--out", str(out)]) == 3
    assert json.loads(out.read_text(encoding="utf-8"))["error"] == "UNSUPPORTED_ADAPTER"
