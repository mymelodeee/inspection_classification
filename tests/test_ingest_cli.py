"""Ingest + CLI on SYNTHETIC KLARF (E01 core path, E03, E09 unknown bin, E13 file errors).

Expected values: tests/fixtures/f01/oracle.json and hand-stated counts. Not a tool-adapter
validation (real export is TBD, see TBD.md).
"""
import json
from pathlib import Path

import pytest

from wafer import ingest
from wafer.cli import main

HERE = Path(__file__).parent
K = HERE / "fixtures/klarf"
PROFILE = str(HERE / "profiles/f01_test_profile.yaml")
oracle = json.loads((HERE / "fixtures/f01/oracle.json").read_text(encoding="utf-8"))


def run_cli(name, tmp_path):
    out = tmp_path / "o.json"
    code = main([str(K / name), "--profile", PROFILE, "--out", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_e01_f01_end_to_end_core(tmp_path):
    code, o = run_cli("f01.klf", tmp_path)
    r = o["result"]
    assert code == 0 and o["job_status"] == "succeeded"
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (8, 8, 0)
    assert r["bin_totals"] == oracle["bin_totals"] and r["center"] == oracle["center"]
    assert r["sectors_clock"] == oracle["sectors_clock"]
    # event key is "<record order>:<DEFECTID>"; oracle uses D01.. labels (D01 = DEFECTID 1)
    D = lambda ids: [f"D{int(i.split(':')[1]):02d}" for i in ids]
    assert D(r["zones"]["E1"]) == oracle["zones"]["E1"]
    assert D(r["zones"]["E2"]) == oracle["zones"]["E2"]
    assert D(r["zones"]["band"]) == oracle["zones"]["band_100mm_pm1"]
    assert len(r["provenance"]["source_sha256"]) == 64


def test_e03_empty_list_is_success_zero(tmp_path):
    code, o = run_cli("empty_list.klf", tmp_path)
    r = o["result"]
    assert code == 0 and r["n_included"] == 0 and r["center"] == 0
    assert r["pattern_summary"] == ["no_detected_defect"]   # plan E03 / 8.1
    assert all(v == 0 for v in r["sectors_clock"].values())


def test_e03_single_and_center_only(tmp_path):
    r = run_cli("single_point.klf", tmp_path)[1]["result"]
    assert r["n_included"] == 1 and r["sectors_clock"]["3"] == 1 and r["center"] == 0
    r = run_cli("center_only.klf", tmp_path)[1]["result"]
    assert r["center"] == 1 and sum(r["sectors_clock"].values()) == 0


def test_e09_unclassified_bin_preserved(tmp_path):
    r = run_cli("e09_unclassified_bin.klf", tmp_path)[1]["result"]
    assert r["bin_totals"] == {"B1": 3, "B2": 2, "B3": 2, "unknown": 1}
    assert sum(r["bin_totals"].values()) == r["n_included"] == 8


@pytest.mark.parametrize("name", ["bad_truncated.klf", "bad_missing_coord_column.klf",
                                  "bad_number.klf", "bad_unsupported_version.klf"])
def test_e13_bad_files_fail_explicitly_not_zero(name, tmp_path):
    code, o = run_cli(name, tmp_path)
    assert code == 3 and o["job_status"] == "failed"
    assert o["data_quality_status"] == "invalid" and o["error"] == "INVALID_INPUT"
    assert "result" not in o


def test_bad_number_reports_record_location(tmp_path):
    assert "record 2" in run_cli("bad_number.klf", tmp_path)[1]["detail"]


def test_unverified_convention_is_not_guessed(tmp_path):
    p = tmp_path / "mirrored.klf"
    p.write_text((K / "f01.klf").read_text().replace("CoordinatesMirrored NO", "CoordinatesMirrored YES"))
    code, o = run_cli_path(p, tmp_path)
    assert code == 3 and o["error"] == "UNSUPPORTED_ADAPTER"


def run_cli_path(p, tmp_path):
    out = tmp_path / "o2.json"
    code = main([str(p), "--profile", PROFILE, "--out", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_duplicate_coordinates_and_ids_are_kept(tmp_path):
    p = tmp_path / "dup.klf"
    t = (K / "f01.klf").read_text().replace("2 50000.0 0.0 0 0 1 1", "1 0.0 50000.0 0 0 1 1")
    p.write_text(t)
    r = run_cli_path(p, tmp_path)[1]["result"]
    assert r["n_included"] == 8
    assert r["zone_union_unique"] == 8  # same DEFECTID twice must not merge events


def test_trailing_semicolon_on_last_record_ok(tmp_path):
    p = tmp_path / "semi.klf"
    p.write_text((K / "f01.klf").read_text().replace("100000.0 0.0 0 0 2 1\n;", "100000.0 0.0 0 0 2 1;"))
    assert run_cli_path(p, tmp_path)[1]["result"]["n_included"] == 8


@pytest.mark.parametrize("old,new", [
    ("2 50000.0 0.0 0 0 1 1", "2 50000.0 0.0 1 0 1 1"),                      # die index != 0
    ("OrientationMarkLocation DOWN", "OrientationMarkLocation UP"),          # notch != DOWN
    ("SampleCenterLocation 0 0", "SampleCenterLocation 10 0"),               # center offset
])
def test_adapter_assumption_violations_are_rejected_not_guessed(old, new, tmp_path):
    p = tmp_path / "v.klf"
    p.write_text((K / "f01.klf").read_text().replace(old, new))
    code, o = run_cli_path(p, tmp_path)
    assert code == 3 and o["error"] == "UNSUPPORTED_ADAPTER" and "result" not in o


def test_count_mismatch_in_spec_fails(tmp_path):
    p = tmp_path / "spec.klf"
    p.write_text((K / "f01.klf").read_text().replace("DefectRecordSpec 7", "DefectRecordSpec 6"))
    with pytest.raises(ingest.KlarfError):
        ingest.read_klarf(p)


def test_missing_input_files_fail_as_json_not_traceback(tmp_path):
    out = tmp_path / "o.json"
    assert main([str(tmp_path / "nope.klf"), "--profile", PROFILE, "--out", str(out)]) == 4
    o = json.loads(out.read_text(encoding="utf-8"))
    assert o["job_status"] == "failed" and o["error"] == "INPUT_NOT_FOUND"
    assert main([str(K / "f01.klf"), "--profile", str(tmp_path / "nope.yaml"), "--out", str(out)]) == 4


@pytest.mark.parametrize("old,new", [
    ("2 50000.0 0.0 0 0 1 1", "2 nan 0.0 0 0 1 1"),
    ("2 50000.0 0.0 0 0 1 1", "2 inf 0.0 0 0 1 1"),
    ("2 50000.0 0.0 0 0 1 1", "2.5 50000.0 0.0 0 0 1 1"),      # non-integer DEFECTID
    ("EndOfFile;", "EndOfFile;" + chr(10) + "DefectList" + chr(10) + "1 0 0 0 0 1 1" + chr(10) + ";" + chr(10) + "EndOfFile;"),  # content after end
])
def test_bad_numbers_and_trailing_content_fail(old, new, tmp_path):
    p = tmp_path / "x.klf"
    p.write_text((K / "f01.klf").read_text().replace(old, new))
    code, o = run_cli_path(p, tmp_path)
    assert code == 3 and o["error"] == "INVALID_INPUT" and "result" not in o


def test_non_utf8_klarf_fails_explicitly(tmp_path):
    p = tmp_path / "bin.klf"
    p.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x62]))
    assert run_cli_path(p, tmp_path)[0] == 3


def test_e01_cli_includes_stats_and_detect_with_honest_null_states(tmp_path):
    """Coverage is unknown (T-05 option a): density and Clark-Evans must be null/insufficient, never 0.
    Radial counts with 50 mm bins over R=150 (hand, F01): r in [0,50): D05(0) only -> 1 (D01..D04 are at
    exactly 50); [50,100): D01..D04 -> 4; [100,150]: D06 149, D07 148, D08 100 -> 3."""
    code, o = run_cli("f01.klf", tmp_path)
    r = o["result"]
    rd = r["radial_density"]
    assert rd["calc_status"] == "computed"
    assert rd["rows"][-1]["r_hi_mm"] == 150 and rd["rows"][-1]["closed"] == "both"
    assert [x["count"] for x in rd["rows"]] == [1, 4, 3] and rd["n_outside_edges"] == 0
    assert all(x["density_per_mm2"] is None and x["reason"] == "coverage_unknown" for x in rd["rows"])
    assert r["clark_evans"]["calc_status"] == "insufficient_data" and r["clark_evans"]["reason"] == "coverage_unknown"
    assert "detect" in r and "summary" in r["detect"]
    assert r["detect"]["summary"]["unique_union"] <= r["n_included"]
    p = r["provenance"]
    assert len(p["profile_sha256"]) == 64 and p["seed"] == 20261009


def test_cli_detect_runs_even_when_randomness_is_insufficient(tmp_path):
    """C07: the randomness result never gates candidate detection."""
    r = run_cli("f01.klf", tmp_path)[1]["result"]
    assert r["clark_evans"]["calc_status"] == "insufficient_data"
    assert r["detect"]["ring"]["feature_status"] in ("candidate", "no_match", "insufficient_data")
    assert r["detect"]["line"]["feature_status"] in ("candidate", "no_match", "insufficient_data")



def test_points_outside_wafer_never_reach_stats_or_detect(tmp_path):
    """F01 + one record at r = 151 mm (R = 150). Hand: parsed 9, included 8, excluded 1; radial counts
    stay [1, 4, 3]; the outside record is in no cluster, support or noise list."""
    p = tmp_path / "out.klf"
    p.write_text((K / "f01.klf").read_text().replace("8 100000.0 0.0 0 0 2 1", "8 100000.0 0.0 0 0 2 1\n9 151000.0 0.0 0 0 1 1"))
    code, o = run_cli_path(p, tmp_path)
    r = o["result"]
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (9, 8, 1)
    out_id = r["excluded"][0]["defect_id"]
    assert out_id == "9:9"
    assert [x["count"] for x in r["radial_density"]["rows"]] == [1, 4, 3]
    d = r["detect"]
    seen = set(d["noise"]) | {i for c in d["clusters"].values() for i in c["ids"]} | {i for v in d["signature_groups"].values() for i in v}
    assert out_id not in seen and len(set(d["noise"]) | {i for c in d["clusters"].values() for i in c["ids"]}) == 8


def test_point_exactly_on_the_wafer_edge_is_counted_in_the_closed_last_bin(tmp_path):
    p = tmp_path / "edge.klf"
    p.write_text((K / "f01.klf").read_text().replace("6 149000.0 0.0 0 0 3 1", "6 150000.0 0.0 0 0 3 1"))
    r = run_cli_path(p, tmp_path)[1]["result"]
    assert r["n_excluded"] == 0 and [x["count"] for x in r["radial_density"]["rows"]] == [1, 4, 3]
    assert r["radial_density"]["n_outside_edges"] == 0


def test_pattern_summary_no_clear_pattern_when_nothing_is_detected(tmp_path):
    r = run_cli("f01.klf", tmp_path)[1]["result"]
    assert r["pattern_summary"] == ["no_clear_pattern"]     # 8 points: all detectors insufficient, all noise


def test_unexpected_errors_become_json_failures(tmp_path, monkeypatch):
    import wafer.cli as c
    monkeypatch.setattr(c, "detect_groups", lambda *a, **k: 1 / 0)   # injected fault (mock)
    code, o = run_cli("f01.klf", tmp_path)
    assert code == 5 and o == {"job_status": "failed", "error": "INTERNAL_ERROR", "detail": "ZeroDivisionError"}


def test_lift_pin_is_disabled_unless_a_template_profile_enables_it(tmp_path):
    assert run_cli("f01.klf", tmp_path)[1]["result"]["lift_pin"] == {"feature_status": "disabled"}
