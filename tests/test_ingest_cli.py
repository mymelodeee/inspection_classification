"""Ingest + CLI on SYNTHETIC KLARF (E01 core path, E03, E09 unknown bin, E13 file errors).

Expected values: tests/fixtures/f01/oracle.json and hand-stated counts. Not a tool-adapter
validation (real export is TBD, see docs/9_TBD.md).
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


def oracle_bin(label):
    """Approved spec change T-03 (2026-10-09): every adapter reports CLASSNUMBER as text ("1","2","3"), 0 -> unknown.
    The F01 oracle (f01-oracle-1, unchanged) writes "Bn"; "Bn" means CLASSNUMBER n. Explicit mapping, not production."""
    assert label[0] == "B" and label[1:].isdigit(), label
    return label[1:]


def oracle_bins(d):
    return {oracle_bin(b): n for b, n in d.items()}


def run_cli(name, tmp_path):
    out = tmp_path / "o.json"
    code = main([str(K / name), "--profile", PROFILE, "--out", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_e01_f01_end_to_end_core(tmp_path):
    code, o = run_cli("f01.klf", tmp_path)
    r = o["result"]
    assert code == 0 and o["job_status"] == "succeeded"
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (8, 8, 0)
    # E01-UP (T-03, 2026-10-09): was r["bin_totals"] == {"B1": 3, "B2": 3, "B3": 2}; now {"1": 3, "2": 3, "3": 2}
    assert r["bin_totals"] == oracle_bins(oracle["bin_totals"]) == {"1": 3, "2": 3, "3": 2}
    assert r["center"] == oracle["center"]
    assert r["sectors_clock"] == oracle["sectors_clock"]
    assert r["orientation_status"] == "notch_registered" and r["clock_status"]["status"] == "computed"
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
    # E09-UP (T-03, 2026-10-09): was {"B1": 3, "B2": 2, "B3": 2, "unknown": 1}; CLASSNUMBER kept as text, 0 -> unknown
    assert r["bin_totals"] == {"1": 3, "2": 2, "3": 2, "unknown": 1}
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
    """Coverage is unknown (T-04 option a): density and Clark-Evans must be null/insufficient, never 0.
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


# ---- E16 preparation: bin x clock table and CSV export consistency (CLI only; no UI/API yet) ----
import csv  # noqa: E402


def test_bin_sector_table_f01_hand_values(tmp_path):
    """F01 (plan 19.2): B1 = D01 12h, D02 3h, D05 center; B2 = D03 6h, D04 9h, D08 3h; B3 = D06, D07 3h."""
    bs = run_cli("f01.klf", tmp_path)[1]["result"]["bin_sector"]
    nz = {b: {h: n for h, n in row.items() if n} for b, row in bs.items()}
    # E16-UP (T-03, 2026-10-09): bin keys "B1"/"B2"/"B3" -> "1"/"2"/"3" (same hand values; oracle "Bn" = CLASSNUMBER n)
    assert nz == {"1": {"12": 1, "3": 1, "center": 1}, "2": {"6": 1, "9": 1, "3": 1}, "3": {"3": 2}}


def test_csv_export_matches_json(tmp_path):
    out = tmp_path / "o.json"
    csvd = tmp_path / "csv"
    assert main([str(K / "f01.klf"), "--profile", PROFILE, "--out", str(out), "--csv-dir", str(csvd)]) == 0
    r = json.loads(out.read_text(encoding="utf-8"))["result"]
    defects = list(csv.DictReader(open(csvd / "defects.csv", encoding="utf-8")))
    assert len(defects) == r["n_parsed"] == 8
    clocks = [d["clock"] for d in defects if d["included"] == "True"]
    assert {h: clocks.count(str(h)) for h in range(1, 13)} == {int(k): v for k, v in r["sectors_clock"].items()}
    assert clocks.count("center") == r["center"]
    spatial = list(csv.DictReader(open(csvd / "spatial_counts.csv", encoding="utf-8")))
    bt = {s["key"]: int(s["count"]) for s in spatial if s["table"] == "bin_total"}
    assert bt == r["bin_totals"]
    radial = [s for s in spatial if s["table"] == "radial"]
    assert [int(s["count"]) for s in radial] == [1, 4, 3]
    assert all(s["density_per_mm2"] == "" and s["reason"] == "coverage_unknown" for s in radial)  # null, not 0
    assert radial[-1]["key"] == "100-150]"
    rows = list(csv.DictReader(open(csvd / "bin_sector.csv", encoding="utf-8")))
    assert sum(int(row["total"]) for row in rows) == r["n_included"]
    assert {row["bin"]: int(row["total"]) for row in rows} == r["bin_totals"]


def test_csv_lists_excluded_records_with_reason(tmp_path):
    p = tmp_path / "out.klf"
    p.write_text((K / "f01.klf").read_text().replace("8 100000.0 0.0 0 0 2 1", "8 100000.0 0.0 0 0 2 1\n9 151000.0 0.0 0 0 1 1"))
    out, csvd = tmp_path / "o.json", tmp_path / "csv"
    main([str(p), "--profile", PROFILE, "--out", str(out), "--csv-dir", str(csvd)])
    d = list(csv.DictReader(open(csvd / "defects.csv", encoding="utf-8")))
    ex = [x for x in d if x["included"] == "False"]
    assert len(d) == 9 and len(ex) == 1 and ex[0]["excluded_reason"] == "outside_wafer" and ex[0]["clock"] == ""


def test_result_schema_check_rejects_missing_keys_and_broken_counts():
    from wafer.report import check_result
    with pytest.raises(ValueError):
        check_result({"n_parsed": 1})


def _profile_without_clock_zone_radial(tmp_path):
    import yaml
    d = yaml.safe_load(open(PROFILE, encoding="utf-8"))
    d["clock"]["center_exclusion_radius_mm"] = None
    for z in ("E1", "E2", "zone_8inch_inside", "zone_8inch_boundary"):
        d["zones"][z]["enabled"] = False
    d["stats"]["radial_bin_mm"] = None
    p = tmp_path / "off.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    return str(p)


def test_csv_distinguishes_disabled_features_from_real_zero(tmp_path):
    """Disabled clock/zones/radial on F01 vs. an empty input with everything enabled: the CSVs must differ
    and the disabled case must carry status rows with empty counts (not 0)."""
    off, csv_off, csv_empty = _profile_without_clock_zone_radial(tmp_path), tmp_path / "off", tmp_path / "empty"
    assert main([str(K / "f01.klf"), "--profile", off, "--out", str(tmp_path / "a.json"), "--csv-dir", str(csv_off)]) == 0
    assert main([str(K / "empty_list.klf"), "--profile", PROFILE, "--out", str(tmp_path / "b.json"), "--csv-dir", str(csv_empty)]) == 0
    s_off = list(csv.DictReader(open(csv_off / "spatial_counts.csv", encoding="utf-8")))
    st = {(r["table"], r["key"]): r for r in s_off}
    # E16-NULLWHY (approved spec change 2026-10-11, null reasons): reasons were startswith("disabled") / == "disabled";
    # now prefixed "not computable: " and the zone reason names the profile as the cause.
    assert st[("sector_strict", "*")]["count"] == "" and \
        st[("sector_strict", "*")]["reason"].startswith("not computable: disabled")
    assert st[("zone", "E1")]["count"] == "" and st[("zone", "E1")]["reason"] == "not computable: zone disabled in profile"
    assert st[("zone_union", "unique")]["count"] == "" and st[("radial", "*")]["count"] == ""
    s_empty = list(csv.DictReader(open(csv_empty / "spatial_counts.csv", encoding="utf-8")))
    se = {(r["table"], r["key"]): r for r in s_empty}
    assert se[("zone_union", "unique")]["count"] == "0" and se[("sector_strict", "3")]["count"] == "0"
    b_off = open(csv_off / "bin_sector.csv", encoding="utf-8").read()
    b_empty = open(csv_empty / "bin_sector.csv", encoding="utf-8").read()
    assert b_off != b_empty and "disabled" in b_off
    d_off = list(csv.DictReader(open(csv_off / "defects.csv", encoding="utf-8")))
    assert all(r["zones"] == "" and r["clock"] == "" for r in d_off)       # not evaluated, not "[]"
    r_off = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))["result"]
    assert r_off["zone_union_unique"] is None and r_off["zones_status"]["E1"] == "disabled"
    m = json.loads((csv_off / "manifest.json").read_text(encoding="utf-8"))
    assert m["provenance"]["source_sha256"] == r_off["provenance"]["source_sha256"]


def test_invariant_violation_is_reported_by_name(tmp_path, monkeypatch):
    import wafer.cli as c
    real = c.aggregate

    def broken(*a, **k):                      # injected fault (mock): corrupt one bin_sector cell
        res, pts = real(*a, **k)
        res["bin_sector"]["1"][12] += 1      # T-03 (2026-10-09): bin key "B1" -> "1" (fault injection target only)
        return res, pts
    monkeypatch.setattr(c, "aggregate", broken)
    code, o = run_cli("f01.klf", tmp_path)
    assert code == 5 and o["error"] == "RESULT_INVARIANT_VIOLATED" and "bin_sector" in o["detail"]


def test_unwritable_csv_dir_is_output_write_failed(tmp_path):
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x")
    code, o = run_cli_path_csv(K / "f01.klf", tmp_path, blocker / "sub")
    assert code == 6 and o["error"] == "OUTPUT_WRITE_FAILED"


def run_cli_path_csv(p, tmp_path, csv_dir):
    out = tmp_path / "o3.json"
    code = main([str(p), "--profile", PROFILE, "--out", str(out), "--csv-dir", str(csv_dir)])
    return code, json.loads(out.read_text(encoding="utf-8"))


# ---- T-01 (2026-10-09): explicit adapter_id is required to run (E12-UP, C13/C17) ----
@pytest.mark.parametrize("how", ["null", "absent"])
def test_e12_up_cli_without_adapter_id_is_config_invalid(how, tmp_path):
    import yaml
    d = yaml.safe_load(open(PROFILE, encoding="utf-8"))
    if how == "null":
        d["coordinates"]["adapter_id"] = None
    else:
        del d["coordinates"]["adapter_id"]
    p = tmp_path / "no_adapter.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    out = tmp_path / "o.json"
    code = main([str(K / "f01.klf"), "--profile", str(p), "--out", str(out)])
    o = json.loads(out.read_text(encoding="utf-8"))
    assert code == 2 and o["job_status"] == "failed" and o["error"] == "CONFIG_INVALID"
    assert "coordinates.adapter_id" in o["keys"] and "result" not in o


# ---- Notch position missing (approved 2026-10-09, T-02): partial result, clock withheld (E10-UP, C03/C04/C15) ----
def _drop_line(text, needle):
    lines = text.splitlines(keepends=True)
    kept = [ln for ln in lines if needle not in ln]
    assert len(lines) - len(kept) == 1, needle      # exactly one header line removed (no silent no-op)
    return "".join(kept)


def test_e10_up_legacy_f01_without_notch_gives_partial_result(tmp_path):
    """f01.klf minus its OrientationMarkLocation line. Independent oracle (f01-oracle-1): counts, bins, center and
    zones depend on r only, so they equal the F01 values; radial counts [1, 4, 3] (hand, see stats test above).
    Physical clock and anything phase-dependent are withheld (null + status), never 0."""
    p = tmp_path / "nonotch.klf"
    p.write_bytes(_drop_line((K / "f01.klf").read_bytes().decode("utf-8"), "OrientationMarkLocation").encode("utf-8"))
    csvd = tmp_path / "csv"
    out = tmp_path / "o.json"
    code = main([str(p), "--profile", PROFILE, "--out", str(out), "--csv-dir", str(csvd)])
    o = json.loads(out.read_text(encoding="utf-8"))
    r = o["result"]
    assert code == 0 and o["job_status"] == "succeeded"
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (8, 8, 0)
    assert r["bin_totals"] == oracle_bins(oracle["bin_totals"])
    assert r["center"] == oracle["center"] == 1
    D = lambda ids: [f"D{int(i.split(':')[1]):02d}" for i in ids]
    assert D(r["zones"]["E1"]) == oracle["zones"]["E1"] and D(r["zones"]["E2"]) == oracle["zones"]["E2"]
    assert D(r["zones"]["inner"]) == oracle["zones"]["inner_r_lt_100"]
    assert D(r["zones"]["band"]) == oracle["zones"]["band_100mm_pm1"]
    assert [x["count"] for x in r["radial_density"]["rows"]] == [1, 4, 3]
    assert r["orientation_status"] == "unknown"
    assert r["clock_status"] == {"status": "insufficient_data", "reason": "orientation_unknown"}
    for k in ("sectors_clock", "sectors_clock_tolerant", "bin_sector", "boundary_ambiguous"):
        assert r[k] is None, k
    assert r["detect"]["frame"] == "unregistered"
    d = list(csv.DictReader(open(csvd / "defects.csv", encoding="utf-8")))
    assert len(d) == 8 and all(x["clock"] == "" for x in d)
    sp = {(s["table"], s["key"]): s for s in csv.DictReader(open(csvd / "spatial_counts.csv", encoding="utf-8"))}
    assert sp[("sector_strict", "*")]["count"] == "" and "orientation_unknown" in sp[("sector_strict", "*")]["reason"]
    assert sp[("center", "center")]["count"] == "1"
