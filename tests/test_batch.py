"""Batch analysis (wafer.batch, wafer.store batch tables, '일괄 분석' UI mode) - function level + headless AppTest.

Scope: SYNTHETIC inputs only (klarf_dummy_data 13 files, tests/fixtures/klarf). Not a real tool-adapter validation,
not a shape-classification evaluation (CLAUDE.md 6-9, C20). Browser E2E for the same flow lives in
tests/test_e2e_browser.py (test_batch_edge_*); the tests here simulate folder upload as (relative path, bytes)
lists (wafer.batch.folder_items / AppTest file_uploader), they do not exercise a browser directory picker.

Oracles (never a production output of the function under test):
  - klarf_dummy_data/manifest.json + expected/*.json (count, bin_counts, center_count, clock_counts, lot_id/wafer_id)
  - plan 19.2 F01 (8 / bins 3,3,2 / center 1 / 12h 1, 3h 4, 6h 1, 9h 1) and hand derivations stated per test
  - tests/fixtures/e06_mixed/e06_mixed.json (support counts / unique union, oracle e06-mixed-1)
  - areas pi*R^2 computed here with math.pi
Shape labels of the dummy files are N/A (generation intent is not a classifier answer, see test_dummy_klarf18 T8);
only status vocabulary / null-vs-0 invariants are asserted for them.

Contract decisions fixed here (main agent, 2026-10-10; defaults pending user decision, documented):
  support/ratio null + support_reason "type_status=<s>" for non-evaluable types; n=0 -> ratio null
  "no_included_defects (denominator 0)"; unit density only with coverage sidecar + radial rows + no point outside
  the window; local status derived from DBSCAN (not a rule); export_zip unit result.json carries a review block;
  run_batch rejects a profile changed since scan; batch rows stored before the first run; DB stores basename only;
  extension filter .klf/.klarf/.txt on the server (content must still parse); summaries are prediction-based.
Links: E01 E03 E09 E11 E13 E16(function/AppTest part) E17 E19; C06 C08 C11 C14 C15 C17 C19 C20.
Plan 19.4 sub-cases added 2026-10-10 (tests 16-20): E01-BATCH1, E17-BATCH (same name / other folder),
E09-MULTI-BATCH, E06-BATCH (same DEFECTID across files), E18/E19-BATCH (batch isolation, rerun keeps reviews).
"""
import csv
import hashlib
import io
import json
import math
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest
import yaml

from wafer import batch as B
from wafer import store
from wafer.profile import ConfigInvalid

ROOT = Path(__file__).resolve().parent.parent
DD = ROOT / "klarf_dummy_data"
KL = DD / "klarf"
EXP = DD / "expected"
SIDECAR = DD / "synthetic_profile.json"                 # full disk R=150 (synthetic declaration)
PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"
FLAT_F01 = ROOT / "tests/fixtures/klarf/f01.klf"
E06 = json.loads((ROOT / "tests/fixtures/e06_mixed/e06_mixed.json").read_text(encoding="utf-8"))

MANIFEST = {c["name"]: c for c in json.loads((DD / "manifest.json").read_text(encoding="utf-8"))["cases"]}
EXPECTED = {n: json.loads((EXP / f"{n}.json").read_text(encoding="utf-8")) for n in MANIFEST}
TOTAL_DUMMY = 1412          # README table: 8+240+240+120+120+120+40+300+200+0+8+8+8
DISK = math.pi * 150.0 ** 2
PARSER_18 = "wafer.ingest-strict-2 (KLARF 1.8 record)"
PARSER_FLAT = "wafer.ingest-strict-2 (flat list)"
NON_EVALUABLE = ("disabled", "insufficient_data")


def dummy_items():
    return [(f"{n}.klarf", (KL / f"{n}.klarf").read_bytes()) for n in MANIFEST]


def damaged_bytes():
    """F01_counts with 'Data 8' -> 'Data 9' (declared rows != parsed rows): INVALID_INPUT, not 0 (T6 variant)."""
    t = (KL / "F01_counts.klarf").read_bytes().decode("utf-8")
    assert "Data 8" in t
    return t.replace("Data 8", "Data 9", 1).encode("utf-8")


def drop_notch(data):
    t = data.decode("utf-8")
    old = '   Field OrientationMarkLocation 1 {"DOWN"}\n'
    assert old in t
    return t.replace(old, "", 1).encode("utf-8")


def mixed_folder(root):
    """Folder with valid / duplicate / damaged / non-KLARF text / unsupported extensions / flat (other adapter)."""
    (root / "lotA" / "w1").mkdir(parents=True)
    (root / "lotA" / "w2").mkdir(parents=True)
    shutil.copy(KL / "F01_counts.klarf", root / "lotA/w1/F01_counts.klarf")
    shutil.copy(KL / "F01_counts.klarf", root / "lotA/w2/F01_counts.klarf")    # same bytes, same basename
    shutil.copy(KL / "empty.klarf", root / "empty.klarf")
    (root / "broken.klarf").write_bytes(damaged_bytes())
    (root / "notes.txt").write_text("not a klarf file\n", encoding="utf-8")       # allowed ext, bad content
    (root / "overview.png").write_bytes((DD / "maps/overview.png").read_bytes())
    (root / "export.001").write_bytes((KL / "F01_counts.klarf").read_bytes())    # T-29: ext not in contract
    shutil.copy(FLAT_F01, root / "flat_f01.klf")                                 # flat syntax, die-local profile
    return root


# expected status per relative path, derived from the folder built above (not from a scan output)
MIXED_STATUS = {
    "broken.klarf": "invalid_input", "empty.klarf": "succeeded", "export.001": "excluded",
    "flat_f01.klf": "held", "lotA/w1/F01_counts.klarf": "succeeded",
    "lotA/w2/F01_counts.klarf": "duplicate_in_batch", "notes.txt": "invalid_input", "overview.png": "excluded",
}


def run(items, db=None, coverage=None, profile=PROFILE, progress=None):
    cov = str(coverage) if coverage else None
    s = B.scan(items, str(profile), coverage_path=cov)       # M1: the sidecar is frozen at scan time too
    return s, B.run_batch(items, s, str(profile), coverage_path=cov, db=str(db) if db else None, progress=progress)


def sk(d):
    """In-process results keep int hour keys; JSON / the oracle use strings. Compare on string keys."""
    return None if d is None else {str(k): v for k, v in d.items()}


def by_name(batch):
    return {Path(e["rel_path"]).stem: e for e in batch["entries"]}


@pytest.fixture(scope="module")
def dummy_cov():
    """13 dummy files with the full-disk sidecar, no DB."""
    return run(dummy_items(), coverage=SIDECAR)[1]


# ---------------------------------------------------------------- 1. preflight list (E13, C17, C20)
def test_01_scan_statuses_reasons_parser_labels_and_header_meta(tmp_path):
    items = B.folder_items(mixed_folder(tmp_path / "in"))
    assert sorted(r for r, _ in items) == sorted(MIXED_STATUS)          # subfolders kept as relative paths
    s = B.scan(items, str(PROFILE))
    e = {x["rel_path"]: x for x in s["entries"]}
    pre = {k: ("ready" if v == "succeeded" else v) for k, v in MIXED_STATUS.items()}
    assert {k: v["status"] for k, v in e.items()} == pre
    for k in ("overview.png", "export.001"):
        assert e[k]["reason"] == "extension_not_in_input_contract" and e[k]["parser"] is None
    assert e["notes.txt"]["reason"] and e["broken.klarf"]["reason"]       # parse failure stated, not 0 defects
    assert e["lotA/w1/F01_counts.klarf"]["parser"] == PARSER_18
    assert e["flat_f01.klf"]["parser"] == PARSER_FLAT
    assert e["flat_f01.klf"]["reason"].startswith("adapter synthetic-die-local-v1")
    dup, src = e["lotA/w2/F01_counts.klarf"], e["lotA/w1/F01_counts.klarf"]
    assert dup["duplicate_of"] == src["index"] and dup["sha256"] == src["sha256"]
    assert src["sha256"] == MANIFEST["F01_counts"]["file_sha256"]
    # lot / wafer come from the KLARF header (expected/*.json lot_id / wafer_id), flagged unverified
    ex = EXPECTED["F01_counts"]
    assert (src["meta"]["lot"], src["meta"]["wafer"]) == (ex["lot_id"], ex["wafer_id"])
    assert "unverified" in src["meta"]["source"] and src["meta"]["job"] is None
    assert s["status_counts"] == {"ready": 2, "duplicate_in_batch": 1, "invalid_input": 2, "excluded": 2, "held": 1}
    assert s["profile_sha256"] == hashlib.sha256(PROFILE.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 2. input limits
def test_02_limits_exclude_with_reason_and_count_only_contract_files():
    f01, emp = (KL / "F01_counts.klarf").read_bytes(), (KL / "empty.klarf").read_bytes()
    ring = (KL / "ring.klarf").read_bytes()
    items = [("a.png", b"x" * 10), ("F01.klarf", f01), ("empty.klarf", emp), ("ring.klarf", ring)]
    st = lambda s: [(x["status"], x["reason"]) for x in s["entries"]]      # noqa: E731
    s = B.scan(items, str(PROFILE), {"max_files": 2})                     # png is not a targeted file
    assert st(s)[1:] == [("ready", None), ("ready", None), ("excluded", "over_max_files (2)")]
    s = B.scan(items, str(PROFILE), {"max_file_bytes": len(f01)})         # limit is inclusive
    assert [x["status"] for x in s["entries"]][1:3] == ["ready", "ready"]
    assert len(ring) > len(f01) and len(emp) <= len(f01)
    assert st(s)[3] == ("excluded", f"over_max_file_bytes ({len(f01)})")
    s = B.scan(items, str(PROFILE), {"max_total_bytes": len(f01) + len(emp)})
    assert st(s)[3] == ("excluded", f"over_max_total_bytes ({len(f01) + len(emp)})")
    assert s["accepted_bytes"] == len(f01) + len(emp)
    # m10 (2026-10-10): an oversize file is excluded for its size and does NOT take a max_files slot.
    # Old behaviour: ring (oversize) consumed slot 1 -> empty became over_max_files. New: F01 + empty ready.
    line = (KL / "line.klarf").read_bytes()
    s = B.scan([("ring.klarf", ring), ("F01.klarf", f01), ("empty.klarf", emp), ("line.klarf", line)], str(PROFILE),
               {"max_files": 2, "max_file_bytes": len(f01)})
    assert st(s) == [("excluded", f"over_max_file_bytes ({len(f01)})"), ("ready", None), ("ready", None),
                     ("excluded", "over_max_files (2)")]
    assert B.DEFAULT_LIMITS == {"max_files": 500, "max_file_bytes": 50 * 2**20, "max_total_bytes": 300 * 2**20}


# ---------------------------------------------------------------- 3. 13 dummy files (E01 E03 E09, C15)
def test_03_dummy_batch_counts_bins_clock_equal_manifest(dummy_cov):
    b = dummy_cov
    ov = B.overview(b)
    assert sum(m["count"] for m in MANIFEST.values()) == TOTAL_DUMMY
    assert ov["files_uploaded"] == ov["analysis_units"] == ov["succeeded"] == len(MANIFEST) == 13
    assert (ov["failed"], ov["held"], ov["excluded"], ov["duplicates_in_batch"]) == (0, 0, 0, 0)
    assert ov["total_included_defects"] == TOTAL_DUMMY
    assert ov["unique_wafers_from_header_unverified"] == len({(x["lot_id"], x["wafer_id"]) for x in EXPECTED.values()})
    for name, e in by_name(b).items():
        r, m = b["units"][e["index"]]["result"], MANIFEST[name]
        assert e["status"] == "succeeded" and e["parser"] == PARSER_18, name
        assert (r["n_parsed"], r["n_included"]) == (m["count"], m["count"]), name
        assert r["bin_totals"] == m["bin_counts"] and r["center"] == m["center_count"], name
        assert sk(r["sectors_clock"]) == m["clock_counts"], name
    empty = b["units"][by_name(b)["empty"]["index"]]["result"]
    assert empty["n_included"] == 0 and empty["bin_totals"] == {}           # successful zero, not a failure
    # original bins summed per profile/adapter group = sum of manifest bin_counts
    exp_bins = {}
    for m in MANIFEST.values():
        for k, v in m["bin_counts"].items():
            exp_bins[k] = exp_bins.get(k, 0) + v
    g = B.bin_totals_by_group(b)
    assert len(g) == 1 and g[0]["bin_totals"] == exp_bins and sum(exp_bins.values()) == TOTAL_DUMMY
    assert g[0]["adapter"] == "synthetic-die-local-v1"
    # m8: groups are keyed by profile_id + profile content hash + adapter
    assert (g[0]["profile_id"], g[0]["profile_sha256"]) == \
        ("dummy_die_local_test_only", hashlib.sha256(PROFILE.read_bytes()).hexdigest())


# ---------------------------------------------------------------- 4. folder vs file list (function simulation)
def test_04_folder_items_and_flat_file_list_give_the_same_batch(tmp_path):
    root = tmp_path / "upload_root"
    for k, n in enumerate(MANIFEST):                                 # nested folders, original names kept
        d = root / f"g{k % 3}" / "deep"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(KL / f"{n}.klarf", d / f"{n}.klarf")
    folder = B.folder_items(root)
    assert all("/" in r for r, _ in folder) and len(folder) == 13
    files = list(reversed(dummy_items()))                            # browser multi-select: basenames, any order
    _, bf = run(folder, db=tmp_path / "f.db")
    _, bl = run(files, db=tmp_path / "l.db")
    assert B.overview(bf) == B.overview(bl)
    kf = {e["sha256"]: e["analysis_key"] for e in bf["entries"]}
    kl = {e["sha256"]: e["analysis_key"] for e in bl["entries"]}
    assert kf == kl and len(set(kf.values())) == 13 and None not in kf.values()
    assert {e["sha256"] for e in bf["entries"]} == {m["file_sha256"] for m in MANIFEST.values()}


# ---------------------------------------------------------------- 5. mixed folder runs the valid inputs (E13)
def test_05_mixed_folder_completes_valid_inputs_and_keeps_every_entry(tmp_path):
    items = B.folder_items(mixed_folder(tmp_path / "in"))
    seen = []
    _, b = run(items, db=tmp_path / "w.db", progress=lambda n, t, name: seen.append((n, t, name)))
    assert {e["rel_path"]: e["status"] for e in b["entries"]} == MIXED_STATUS
    assert [x[2] for x in seen] == ["empty.klarf", "lotA/w1/F01_counts.klarf"] and seen[-1][:2] == (2, 2)
    ov = B.overview(b)
    assert ov == {"files_uploaded": 8, "files_targeted": 6, "excluded": 2, "analysis_units": 2, "succeeded": 2,
                  "failed": 2, "held": 1, "duplicates_in_batch": 1, "reused_from_store": 0,
                  "unique_wafers_from_header_unverified": 2, "units_with_unknown_wafer_id": 0,
                  "total_included_defects": MANIFEST["F01_counts"]["count"] + MANIFEST["empty"]["count"]}
    e = {x["rel_path"]: x for x in b["entries"]}
    dup, src = e["lotA/w2/F01_counts.klarf"], e["lotA/w1/F01_counts.klarf"]
    assert dup["analysis_key"] == src["analysis_key"] is not None            # analysed once, pointed to
    con = sqlite3.connect(tmp_path / "w.db")
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2       # F01 + empty, never twice
    con.close()
    rows = {r["rel_path"]: r for r in B.unit_rows(b)}
    assert rows["lotA/w2/F01_counts.klarf"]["n_included"] == 8                # duplicate row shows its source
    assert "n_included" not in rows["broken.klarf"] and rows["broken.klarf"]["status"] == "invalid_input"


# ---------------------------------------------------------------- 6. type status + support null/0 (contract 1, 3)
def test_06_type_status_and_support_for_f01_and_empty(dummy_cov):
    """Hand derivation, dummy profile (TEST-ONLY): F01 has 8 points < ring.min_points 20 and < line.min_points 10
    -> ring/line insufficient_data; DBSCAN eps 10 / min_samples 3: the only pair closer than 10 mm is ID6-ID7
    (r 149 / 148, 1 mm apart), 2 < 3 -> no cluster -> local no_match with a real support 0 (ratio 0/8 = 0.0).
    lift_pin disabled in the profile. Empty map: every implemented type insufficient_data, lift_pin disabled."""
    u = {n: dummy_cov["units"][e["index"]]["result"] for n, e in by_name(dummy_cov).items()}
    assert B.type_status(u["F01_counts"]) == {"ring": "insufficient_data", "line": "insufficient_data",
                                              "local": "no_match", "lift_pin": "disabled"}
    m = B.unit_metrics(u["F01_counts"])
    assert m["support"] == {"ring": None, "line": None, "local": 0, "lift_pin": None}
    assert m["support_ratio"] == {"ring": None, "line": None, "local": 0.0, "lift_pin": None}
    assert m["support_ratio"]["local"] is not None
    assert m["support_reason"] == {"ring": "type_status=insufficient_data", "line": "type_status=insufficient_data",
                                   "local": None, "lift_pin": "type_status=disabled"}
    assert B.type_status(u["empty"]) == {"ring": "insufficient_data", "line": "insufficient_data",
                                         "local": "insufficient_data", "lift_pin": "disabled"}
    me = B.unit_metrics(u["empty"])
    assert set(me["support"].values()) == {None} and set(me["support_ratio"].values()) == {None}
    # m7 (2026-10-10): no type evaluable on the empty map -> union is null (not computed), was 0 before
    assert me["support_union_all_types"] is None
    # every dummy unit: vocabulary closed, null exactly when not evaluable
    for name, r in u.items():
        ts, mm = B.type_status(r), B.unit_metrics(r)
        for t in B.TYPES:
            assert ts[t] in ("candidate", "matched", "no_match", *NON_EVALUABLE), (name, t)
            assert (mm["support"][t] is None) == (ts[t] in NON_EVALUABLE), (name, t)
            if ts[t] not in NON_EVALUABLE:
                assert 0 <= mm["support"][t] <= MANIFEST[name]["count"], (name, t)
        if any(ts[t] not in NON_EVALUABLE for t in B.TYPES):
            assert 0 <= mm["support_union_all_types"] <= MANIFEST[name]["count"], name
        else:                                                            # m7: nothing evaluable -> null
            assert mm["support_union_all_types"] is None, name


def _hand_result(n, detect, lift_pin=None):
    """Minimal result dict (hand-built input) for unit_metrics contract checks: coverage unknown, no notch."""
    return {"n_included": n, "detect": detect, "lift_pin": lift_pin or {"feature_status": "disabled"},
            "radial_density": {"calc_status": "computed", "rows": []}, "center": None, "sectors_clock": None,
            "clock_status": {"status": "insufficient_data", "reason": "orientation_unknown"},
            "provenance": {"coverage": {"status": "unknown"}}}


# ---------------------------------------------------------------- 7. overlap union (E06 oracle, C11) + n=0
def test_07_type_supports_overlap_and_union_follow_the_e06_oracle():
    ex = E06["cases"]["intact"]["expected"]
    sid = ex["support_ids"]
    det = {"shape_supports": {"ring": sid["ring"], "line": sid["line"]},
           "signature_groups": {"ring": sid["ring"], "line": sid["line"], "local_0": sid["local"]},
           "clusters": {"0": {"ids": sid["local"], "same_as": None}},
           "ring": {"feature_status": "candidate"}, "line": {"feature_status": "candidate"}}
    n = ex["wafer_unique_defect_count"]
    m = B.unit_metrics(_hand_result(n, det))
    assert m["support"] == {**ex["support_count"], "lift_pin": None}                    # 26 / 15 / 12
    assert m["support_union_all_types"] == ex["unique_union_size"] == 48                 # not naive 53
    assert sum(m["support"][t] for t in ("ring", "line", "local")) == ex["naive_sum"]    # overlap is visible
    assert m["support_ratio"]["ring"] == pytest.approx(26 / 48, rel=1e-12)
    assert m["density_per_mm2"] is None and m["density_reason"] == "coverage_unknown"
    assert m["main_direction"] is None and m["direction_reason"] == "orientation_unknown"

    # evaluable type on an empty map: support is a real 0, the ratio has no denominator
    det0 = {"shape_supports": {}, "signature_groups": {}, "clusters": {},
            "ring": {"feature_status": "no_match"}, "line": {"feature_status": "no_match"}}
    m0 = B.unit_metrics(_hand_result(0, det0, {"feature_status": "no_match", "lobes": []}))
    assert m0["support"]["ring"] == 0 and m0["support_ratio"]["ring"] is None
    assert m0["support_reason"]["ring"] == "no_included_defects (denominator 0)"
    assert m0["support"]["local"] is None and m0["support_reason"]["local"] == "type_status=insufficient_data"
    assert m0["support"]["lift_pin"] == 0 and m0["support_ratio"]["lift_pin"] is None


# ---------------------------------------------------------------- 8. unit density (contract 2, E11, C06)
def _f01_with(tmp_path, coverage=None, profile=PROFILE):
    items = [("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())]
    _, b = run(items, coverage=coverage, profile=profile)
    return B.unit_metrics(b["units"][0]["result"])


def test_08_unit_density_only_with_coverage_rows_and_no_point_outside(tmp_path):
    m = _f01_with(tmp_path, coverage=SIDECAR)                            # 8 / (pi * 150^2)
    assert m["valid_area_mm2"] == pytest.approx(DISK, rel=1e-12)
    assert m["density_per_mm2"] == pytest.approx(8 / DISK, rel=1e-12) and m["density_reason"] is None

    m = _f01_with(tmp_path)
    assert (m["density_per_mm2"], m["valid_area_mm2"], m["density_reason"]) == (None, None, "coverage_unknown")

    r140 = tmp_path / "cov140.json"                                       # F01 IDs 6/7 (r 149/148) outside
    r140.write_text(json.dumps({"coverage": {"shape": "full_disk", "radius_mm": 140,
                                             "source": "TEST-ONLY partial"}}), encoding="utf-8")
    m = _f01_with(tmp_path, coverage=r140)
    assert m["density_per_mm2"] is None and m["density_reason"] == "points_outside_inspected_window"

    d = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    d["stats"].pop("radial_bin_mm")
    p = tmp_path / "no_radial.yaml"
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    m = _f01_with(tmp_path, coverage=SIDECAR, profile=p)
    assert m["density_per_mm2"] is None and m["density_reason"].startswith("radial_density disabled")


# ---------------------------------------------------------------- 9. main direction (C04, E10)
def test_09_main_direction_denominator_excludes_center_and_is_withheld_without_notch(dummy_cov):
    """F01 plan 19.2: 3h holds 4 of the 7 non-center defects -> hours [3], ratio 4/7."""
    u = {n: dummy_cov["units"][e["index"]]["result"] for n, e in by_name(dummy_cov).items()}
    for case in ("F01_counts", "F01_up", "F01_left", "F01_right"):
        md = B.unit_metrics(u[case])["main_direction"]
        assert md == {"hours": [3], "count": 4, "ratio": pytest.approx(4 / 7, rel=1e-12),
                      "denominator": "n_included - center", "denominator_value": 7}, case
    me = B.unit_metrics(u["empty"])
    assert me["main_direction"]["ratio"] is None and me["direction_reason"] == "no_non_center_defects"
    _, b = run([("nonotch.klarf", drop_notch((KL / "F01_counts.klarf").read_bytes()))])
    m = B.unit_metrics(b["units"][0]["result"])
    assert m["main_direction"] is None and m["direction_reason"] == "orientation_unknown"
    assert b["units"][0]["result"]["n_included"] == 8                    # counts still delivered


# ---------------------------------------------------------------- 10. type summary (prediction basis)
def test_10_type_summary_counts_not_evaluated_files_separately(tmp_path):
    _, b = run(B.folder_items(mixed_folder(tmp_path / "in")))
    ts = {r["type"]: r for r in B.type_summary(b)}
    # units: F01 (ring/line insufficient, local no_match) and empty (all insufficient); lift_pin disabled for both
    assert {t: (r["candidate"], r["matched"], r["no_match"], r["insufficient_data"], r["disabled"])
            for t, r in ts.items()} == {"ring": (0, 0, 0, 2, 0), "line": (0, 0, 0, 2, 0),
                                        "local": (0, 0, 1, 1, 0), "lift_pin": (0, 0, 0, 0, 2)}
    assert ts["local"]["evaluable_units"] == 1 and ts["local"]["not_evaluable_units"] == 1
    assert ts["local"]["unique_support_defects"] == 0
    assert all(r["files_not_evaluated"] == 3 for r in ts.values())       # 2 invalid_input + 1 held, not "no pattern"
    assert all(r["basis"] == "initial predictions (reviews not applied)" for r in ts.values())
    assert "derived" in ts["local"]["note"] and ts["ring"]["note"] is None
    rows = list(csv.DictReader(io.StringIO(B.type_csv(b))))
    assert [r["type"] for r in rows] == list(B.TYPES) and rows[0]["note"] == ""


# ---------------------------------------------------------------- 11. batch density per group (C06, C15)
def test_11_batch_density_sums_count_and_area_and_never_averages_in_zero(dummy_cov):
    g = B.batch_density(dummy_cov)
    assert len(g) == 1
    assert (g[0]["units_in_density"], g[0]["units_excluded_no_valid_area"], g[0]["sum_count"]) == (13, 0, TOTAL_DUMMY)
    assert g[0]["sum_area_mm2"] == pytest.approx(13 * DISK, rel=1e-12)
    assert g[0]["density_per_mm2"] == pytest.approx(TOTAL_DUMMY / (13 * DISK), rel=1e-12)
    _, b = run(dummy_items())                                            # no sidecar: coverage unknown
    g = B.batch_density(b)
    assert len(g) == 1 and g[0]["coverage_status"] == "unknown"
    assert (g[0]["units_in_density"], g[0]["units_excluded_no_valid_area"], g[0]["sum_count"]) == (0, 13, 0)
    assert g[0]["sum_area_mm2"] is None and g[0]["density_per_mm2"] is None


# ---------------------------------------------------------------- 12. frozen inputs (E12, C17)
def test_12_profile_changed_after_scan_and_bad_sidecar_stop_the_batch_before_any_run(tmp_path):
    prof = tmp_path / "p.yaml"
    prof.write_bytes(PROFILE.read_bytes())
    items = [("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())]
    s = B.scan(items, str(prof))
    prof.write_bytes(PROFILE.read_bytes() + b"\n# edited after the preflight list\n")
    db = tmp_path / "w.db"
    with pytest.raises(ConfigInvalid) as e:
        B.run_batch(items, s, str(prof), db=str(db))
    assert e.value.keys == ["profile"]
    assert not db.exists()                                               # nothing stored, nothing run

    # M1 (2026-10-10): the bad sidecar is now part of the preflight list (scan hashes it), so the batch gets past
    # the hash check and stops at load_coverage (CoverageInvalid) - still before any run and before any DB write.
    # Old: scanned without the sidecar, then run with it (that now fails earlier with keys ["coverage"], see below).
    from wafer.cli import CoverageInvalid
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    s = B.scan(items, str(PROFILE), coverage_path=str(bad))
    assert s["coverage_sha256"] == hashlib.sha256(b"{").hexdigest()
    calls = []
    with pytest.raises(CoverageInvalid):
        B.run_batch(items, s, str(PROFILE), coverage_path=str(bad), db=str(db), progress=lambda *a: calls.append(a))
    assert calls == [] and not db.exists()


def test_12b_coverage_or_inputs_changed_after_scan_stop_the_batch(tmp_path):
    """M1: sidecar bytes changed, sidecar added/removed (None vs path) and listed item bytes changed are all
    refused with CONFIG_INVALID before any run / DB write. Expected keys from the approved contract."""
    f01 = (KL / "F01_counts.klarf").read_bytes()
    items = [("F01_counts.klarf", f01), ("ring.klarf", (KL / "ring.klarf").read_bytes())]
    cov = tmp_path / "cov.json"
    cov.write_bytes(SIDECAR.read_bytes())
    db = tmp_path / "w.db"
    calls = []

    def refused(keys, items_run, s, cov_run):
        with pytest.raises(ConfigInvalid) as e:
            B.run_batch(items_run, s, str(PROFILE), coverage_path=cov_run, db=str(db),
                        progress=lambda *a: calls.append(a))
        assert e.value.keys == keys
        assert calls == [] and not db.exists()

    s = B.scan(items, str(PROFILE), coverage_path=str(cov))
    assert s["coverage_sha256"] == hashlib.sha256(SIDECAR.read_bytes()).hexdigest()
    cov.write_bytes(SIDECAR.read_bytes() + b"\n")                      # same meaning, other bytes
    refused(["coverage"], items, s, str(cov))
    refused(["coverage"], items, s, None)                              # sidecar dropped after the scan
    s0 = B.scan(items, str(PROFILE))
    assert s0["coverage_sha256"] is None
    refused(["coverage"], items, s0, str(SIDECAR))                     # sidecar added after the scan
    changed = [items[0], ("ring.klarf", (KL / "line.klarf").read_bytes())]
    refused(["inputs"], changed, s0, None)                             # listed bytes != bytes to run


def test_12c_profile_edited_during_the_run_does_not_reach_later_units(tmp_path):
    """M1: run_batch reads the profile once and runs every unit on a frozen copy. The progress callback edits the
    file before the first unit; every unit (and config) must carry the sha256 of the ORIGINAL bytes (hashlib)."""
    prof = tmp_path / "p.yaml"
    original = PROFILE.read_bytes()
    prof.write_bytes(original)
    want = hashlib.sha256(original).hexdigest()
    items = [(f"{c}.klarf", (KL / f"{c}.klarf").read_bytes()) for c in ("F01_counts", "ring", "line")]

    def progress(n, total, name):
        if n == 1:
            edited = original.replace(b"eps_mm: 10", b"eps_mm: 25") + b"\n# edited during the batch\n"
            assert edited != original
            prof.write_bytes(edited)
    s = B.scan(items, str(prof))
    b = B.run_batch(items, s, str(prof), progress=progress)
    assert prof.read_bytes() != original                               # the edit really happened
    assert [e["status"] for e in b["entries"]] == ["succeeded"] * 3
    assert b["config"]["profile_sha256"] == want
    assert [b["units"][i]["result"]["provenance"]["profile_sha256"] for i in range(3)] == [want] * 3


# ---------------------------------------------------------------- 13. store: batch rows (E17, T-27)
def test_13_batch_rows_stored_before_first_run_basename_only_and_rerun_reuses(tmp_path):
    items = B.folder_items(mixed_folder(tmp_path / "in"))
    db = tmp_path / "w.db"
    snap = []

    def progress(n, total, name):
        if n == 1:   # before the first run: every member is already recorded with its preflight status
            con = store.connect(str(db))
            bid = con.execute("SELECT batch_id FROM batches").fetchone()[0]
            snap.extend(store.batch_members(con, bid))
            con.close()
    _, b = run(items, db=db, progress=progress)
    pre = {k: ("ready" if v == "succeeded" else v) for k, v in MIXED_STATUS.items()}
    order = [e["rel_path"] for e in b["entries"]]
    assert [m["status"] for m in snap] == [pre[r] for r in order]
    assert [m["rel_path"] for m in snap] == [Path(r).name for r in order]   # basename only in the DB
    assert all(m["analysis_key"] is None for m in snap)

    con = store.connect(str(db))
    after = store.batch_members(con, b["config"]["batch_id"])
    assert [m["status"] for m in after] == [MIXED_STATUS[r] for r in order]
    keys = {r: m["analysis_key"] for r, m in zip(order, after)}
    assert keys["lotA/w2/F01_counts.klarf"] == keys["lotA/w1/F01_counts.klarf"] is not None
    assert keys["broken.klarf"] is None and keys["overview.png"] is None
    assert after[order.index("lotA/w2/F01_counts.klarf")]["duplicate_of"] == order.index("lotA/w1/F01_counts.klarf")
    con.close()

    _, b2 = run(items, db=db)                                            # same inputs again
    assert B.overview(b2)["reused_from_store"] == 2
    assert {e["rel_path"]: e.get("analysis_key") for e in b2["entries"]} == \
        {e["rel_path"]: e.get("analysis_key") for e in b["entries"]}
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 2  # both batches kept, nothing overwritten
    con.close()


# ---------------------------------------------------------------- 14. exports (E16 function part, E19, C14)
def test_14_export_zip_and_summary_csv_against_independent_values(tmp_path):
    items = dummy_items() + [("../escape dir/evil name.klarf", (KL / "F01_counts.klarf").read_bytes()),
                             ("bad.png", b"\x89PNG")]
    db = tmp_path / "w.db"
    _, b = run(items, db=db, coverage=SIDECAR)
    z = zipfile.ZipFile(io.BytesIO(B.export_zip(b)))
    names = z.namelist()
    assert {"batch_manifest.json", "summary.csv", "type_summary.csv"} <= set(names)
    assert not [n for n in names if ".." in n.split("/") or n.startswith("/") or ":" in n]
    unit_dirs = sorted({n.split("/")[1] for n in names if n.startswith("units/")})
    assert len(unit_dirs) == 13                                          # duplicate and png have no own folder
    man = json.loads(z.read("batch_manifest.json"))
    assert man["overview"]["total_included_defects"] == TOTAL_DUMMY
    assert man["config"]["coverage_sidecar_sha256"] == hashlib.sha256(SIDECAR.read_bytes()).hexdigest()
    assert man["config"]["profile_sha256"] == hashlib.sha256(PROFILE.read_bytes()).hexdigest()
    assert [e["rel_path"] for e in man["entries"]][-2:] == ["../escape dir/evil name.klarf", "bad.png"]
    for d in unit_dirs:
        doc = json.loads(z.read(f"units/{d}/result.json"))
        assert not [k for k in doc if k.startswith("_")] and doc["review"] is None     # con not given
        r = doc["result"]
        name = next(n for n in MANIFEST if MANIFEST[n]["file_sha256"] == r["provenance"]["source_sha256"])
        m = MANIFEST[name]
        assert (r["n_included"], r["bin_totals"], r["center"], r["sectors_clock"]) == \
            (m["count"], m["bin_counts"], m["center_count"], m["clock_counts"]), d
        assert {"defects.csv", "spatial_counts.csv", "bin_sector.csv"} <= \
            {n.split("/")[-1] for n in names if n.startswith(f"units/{d}/")}

    rows = {r["rel_path"]: r for r in csv.DictReader(io.StringIO(B.summary_csv(b)))}
    for name, m in MANIFEST.items():
        r = rows[f"{name}.klarf"]
        assert r["status"] == "succeeded" and int(r["n_included"]) == m["count"]
        assert json.loads(r["bins"]) == m["bin_counts"]
    f01 = rows["F01_counts.klarf"]
    assert float(f01["density_per_mm2"]) == pytest.approx(8 / DISK, rel=1e-12)
    assert f01["ring_support"] == "" and f01["local_support"] == "0"      # null -> empty cell, real 0 -> "0"
    assert rows["empty.klarf"]["n_included"] == "0" and rows["empty.klarf"]["status"] == "succeeded"
    assert rows["bad.png"]["status"] == "excluded" and rows["bad.png"]["n_included"] == ""
    assert sum(int(r["n_included"]) for r in rows.values() if r["status"] == "succeeded") == TOTAL_DUMMY

    # review block: read at export time from the store; the prediction is unchanged
    con = store.connect(str(db))
    key = by_name(b)["F01_counts"]["analysis_key"]
    z1 = zipfile.ZipFile(io.BytesIO(B.export_zip(b, con)))
    d01 = next(d for d in unit_dirs if d.endswith("_F01_counts.klarf"))
    before = json.loads(z1.read(f"units/{d01}/result.json"))
    assert before["review"] == {"analysis_key": key, "review_status": "unreviewed", "latest_revision": None}
    assert store.add_review(con, key, "defer", {"reason_code": "needs_sem_review"}) == 1
    after = json.loads(zipfile.ZipFile(io.BytesIO(B.export_zip(b, con))).read(f"units/{d01}/result.json"))
    assert after["review"] == {"analysis_key": key, "review_status": "deferred", "latest_revision": 1}
    assert after["result"] == before["result"]
    srow = {r["rel_path"]: r for r in csv.DictReader(io.StringIO(B.summary_csv(b, con)))}["F01_counts.klarf"]
    assert srow["review_status_now"] == "deferred" and srow["review_latest_revision"] == "1"
    con.close()


# ---------------------------------------------------------------- 15. headless AppTest: uploaders (not a browser)
def _apptest_batch(uploader_key, files):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "wafer/app.py"), default_timeout=120)
    at.run()
    at.file_uploader(key=uploader_key).set_value(files)
    at.text_input(key="batch_profile_path").set_value(str(PROFILE))
    at.button(key="batch_scan_btn").click().run()
    assert not at.exception, at.exception
    at.button(key="batch_run_btn").click().run()
    assert not at.exception, at.exception
    return {m.label: m.value for m in at.metric}


def test_15_apptest_folder_and_multi_file_uploaders_give_the_same_overview():
    """AppTest file_uploader.set_value feeds (name, bytes, mime) - a simulation of the upload; the real browser
    directory picker is covered by test_e2e_browser.py::test_batch_edge_*."""
    folder = [(f"root/sub{k % 2}/{n}.klarf", (KL / f"{n}.klarf").read_bytes(), "application/octet-stream")
              for k, n in enumerate(MANIFEST)] + [("root/map.png", b"\x89PNG", "image/png")]
    flat = [(f"{n}.klarf", (KL / f"{n}.klarf").read_bytes(), "application/octet-stream") for n in MANIFEST]
    mf, ml = _apptest_batch("batch_folder", folder), _apptest_batch("batch_files", flat)
    expect = {"업로드 파일": "13", "분석 단위": "13", "성공": "13", "실패": "0", "보류": "0",
              "포함 결함 합": str(TOTAL_DUMMY)}
    assert ml == expect
    assert mf == {**expect, "업로드 파일": "14"}                          # the png is listed, excluded, not analysed


# ---------------------------------------------------------------- 16. one-file batch == single analysis (E01-BATCH1, C02)
@pytest.mark.parametrize("case", ["F01_counts", "mixed"])
def test_16_one_file_batch_equals_single_run_job(tmp_path, case):
    """Same bytes / profile / coverage through run_batch and through cli.run_job (separate DBs) must give the
    same result dict and the same analysis key. The result carries no source name/path (provenance holds
    only source_sha256), so nothing is excluded from the comparison. Counts checked against the manifest."""
    from wafer.cli import run_job
    data = (KL / f"{case}.klarf").read_bytes()
    _, b = run([(f"{case}.klarf", data)], db=tmp_path / "batch.db", coverage=SIDECAR)
    single, code = run_job(str(KL / f"{case}.klarf"), str(PROFILE), db=str(tmp_path / "single.db"),
                           coverage_path=str(SIDECAR))
    assert code == 0 and b["entries"][0]["status"] == "succeeded" and b["entries"][0]["exit_code"] == 0
    unit = b["units"][0]
    assert unit["result"] == single["result"]
    assert unit["data_quality_status"] == single["data_quality_status"] == "valid"
    assert b["entries"][0]["analysis_key"] == single["store"]["analysis_key"] is not None
    assert unit["store"]["created"] is True and single["store"]["created"] is True     # separate DBs
    r, m = unit["result"], MANIFEST[case]                                # independent oracle
    assert (r["n_parsed"], r["n_included"], r["bin_totals"], r["center"]) == \
        (m["count"], m["count"], m["bin_counts"], m["center_count"])
    assert sk(r["sectors_clock"]) == m["clock_counts"]
    assert B.type_status(r) == B.type_status(single["result"])
    assert r["provenance"]["source_sha256"] == m["file_sha256"]


# ---------------------------------------------------------------- 17. same name, different subfolders (E17-BATCH, C17)
def test_17_same_basename_in_different_subfolders_are_two_units(tmp_path):
    f01, ring = (KL / "F01_counts.klarf").read_bytes(), (KL / "ring.klarf").read_bytes()
    items = [("a/x.klf", f01), ("b/x.klf", ring)]
    s = B.scan(items, str(PROFILE))
    assert [e["status"] for e in s["entries"]] == ["ready", "ready"]
    assert [e["duplicate_of"] for e in s["entries"]] == [None, None]
    assert [e["sha256"] for e in s["entries"]] == [MANIFEST["F01_counts"]["file_sha256"],
                                                   MANIFEST["ring"]["file_sha256"]]
    _, b = run(items, db=tmp_path / "w.db")
    assert [e["status"] for e in b["entries"]] == ["succeeded", "succeeded"]
    assert sorted(b["units"]) == [0, 1]
    assert [b["units"][i]["result"]["n_included"] for i in (0, 1)] == \
        [MANIFEST["F01_counts"]["count"], MANIFEST["ring"]["count"]]           # 8 / 240
    assert b["entries"][0]["analysis_key"] != b["entries"][1]["analysis_key"]
    ov = B.overview(b)
    assert (ov["analysis_units"], ov["duplicates_in_batch"]) == (2, 0)
    assert ov["total_included_defects"] == MANIFEST["F01_counts"]["count"] + MANIFEST["ring"]["count"]
    rows = {r["rel_path"]: r for r in B.unit_rows(b)}
    assert (rows["a/x.klf"]["n_included"], rows["b/x.klf"]["n_included"]) == (8, 240)
    z = zipfile.ZipFile(io.BytesIO(B.export_zip(b)))
    unit_dirs = sorted({n.split("/")[1] for n in z.namelist() if n.startswith("units/")})
    assert len(unit_dirs) == 2
    got = {json.loads(z.read(f"units/{d}/result.json"))["result"]["provenance"]["source_sha256"] for d in unit_dirs}
    assert got == {MANIFEST["F01_counts"]["file_sha256"], MANIFEST["ring"]["file_sha256"]}
    man = json.loads(z.read("batch_manifest.json"))
    assert [e["rel_path"] for e in man["entries"]] == ["a/x.klf", "b/x.klf"]   # full relative path kept


# ---------------------------------------------------------------- 18. multi-wafer file (E09-MULTI-BATCH, C02, C15)
def _two_wafer_bytes():
    """F01_counts with its WaferRecord block repeated under the same LotRecord (second record renamed).
    Plan 19.3 E09-MULTI / 19.4 E09-MULTI-BATCH, README 6: unsupported -> invalid_input (TBD T-12)."""
    lines = (KL / "F01_counts.klarf").read_bytes().decode("utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("Record WaferRecord"))
    end = max(i for i, ln in enumerate(lines) if ln.strip() == "}") - 2      # closes WaferRecord (file, lot after)
    assert lines[end].strip() == "}" and lines[end + 1].strip() == "}" and lines[end + 2].strip() == "}"
    block = "".join(lines[start:end + 1]).replace('"F01_counts"', '"F01_counts_second"', 1)
    text = "".join(lines[:end + 1]) + block + "".join(lines[end + 1:])
    assert text.count("Record WaferRecord") == 2
    return text.encode("utf-8")


def test_18_multi_wafer_file_is_invalid_input_one_file_no_unit_never_zero(tmp_path):
    multi = _two_wafer_bytes()
    items = [("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes()), ("multi.klarf", multi),
             ("ring.klarf", (KL / "ring.klarf").read_bytes())]
    db = tmp_path / "w.db"
    s, b = run(items, db=db)
    assert s["entries"][1]["status"] == "invalid_input" and "WaferRecord" in s["entries"][1]["reason"]
    e = b["entries"][1]
    assert e["status"] == "invalid_input" and e.get("analysis_key") is None and 1 not in b["units"]
    ov = B.overview(b)
    assert ov["files_uploaded"] == 3 and ov["files_targeted"] == 3
    assert ov["analysis_units"] == ov["succeeded"] == 2 and ov["failed"] == 1   # file count != unit count
    assert ov["total_included_defects"] == MANIFEST["F01_counts"]["count"] + MANIFEST["ring"]["count"]
    row = {r["rel_path"]: r for r in B.unit_rows(b)}["multi.klarf"]
    assert row["status"] == "invalid_input" and "n_included" not in row        # not shown as 0 defects
    csvrow = {r["rel_path"]: r for r in csv.DictReader(io.StringIO(B.summary_csv(b)))}["multi.klarf"]
    assert csvrow["n_included"] == "" and csvrow["status"] == "invalid_input"
    con = store.connect(str(db))
    mem = store.batch_members(con, b["config"]["batch_id"])
    assert (mem[1]["status"], mem[1]["analysis_key"]) == ("invalid_input", None)
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2         # nothing stored for the multi file
    assert con.execute("SELECT COUNT(*) FROM runs WHERE source_sha256 = ?",
                       (hashlib.sha256(multi).hexdigest(),)).fetchone()[0] == 0
    con.close()
    for t in B.type_summary(b):
        assert t["files_not_evaluated"] == 1


# ---------------------------------------------------------------- 19. same DEFECTIDs in different files (E06-BATCH, C11)
def test_19_same_defect_ids_in_different_files_are_not_merged(tmp_path):
    """Every dummy file numbers its defects from DEFECTID 1 (checked below on the raw text); per-unit counts
    must equal each file's own manifest values and the batch total must be the plain sum."""
    cases = ["F01_counts", "ring", "line", "local_3oclock"]
    for c in cases:
        txt = (KL / f"{c}.klarf").read_text(encoding="utf-8")
        first_row = txt.split("Data ", 1)[1].split("{", 1)[1].strip().split()[0]
        assert first_row == "1", c
    items = [(f"{c}.klarf", (KL / f"{c}.klarf").read_bytes()) for c in cases]
    _, b = run(items, coverage=SIDECAR)
    for name, e in by_name(b).items():
        r, m = b["units"][e["index"]]["result"], MANIFEST[name]
        assert (r["n_included"], r["bin_totals"], r["center"]) == (m["count"], m["bin_counts"], m["center_count"]), name
        assert sk(r["sectors_clock"]) == m["clock_counts"], name
        mm = B.unit_metrics(r)
        assert mm["support_union_all_types"] <= m["count"], name               # no ids borrowed from another file
    expected_total = sum(MANIFEST[c]["count"] for c in cases)                   # 8 + 240 + 120 + 120 = 488
    assert expected_total == 488 and B.overview(b)["total_included_defects"] == expected_total
    exp_bins = {}
    for c in cases:
        for k, v in MANIFEST[c]["bin_counts"].items():
            exp_bins[k] = exp_bins.get(k, 0) + v
    assert B.bin_totals_by_group(b)[0]["bin_totals"] == exp_bins
    assert B.batch_density(b)[0]["sum_count"] == expected_total


# ---------------------------------------------------------------- 20. batch isolation + rerun keeps reviews (E18/E19-BATCH, C17)
def test_20_batches_in_one_db_are_isolated_and_rerun_reuses_without_touching_reviews(tmp_path):
    db = tmp_path / "w.db"
    one = [(f"{c}.klarf", (KL / f"{c}.klarf").read_bytes()) for c in ("F01_counts", "ring")]
    two = [(f"{c}.klarf", (KL / f"{c}.klarf").read_bytes()) for c in ("line", "empty")]
    _, b1 = run(one, db=db)
    _, b2 = run(two, db=db)
    con = store.connect(str(db))
    m1 = store.batch_members(con, b1["config"]["batch_id"])
    m2 = store.batch_members(con, b2["config"]["batch_id"])
    assert [m["rel_path"] for m in m1] == ["F01_counts.klarf", "ring.klarf"]
    assert [m["rel_path"] for m in m2] == ["line.klarf", "empty.klarf"]
    assert {r["rel_path"] for r in B.unit_rows(b2)} == {"line.klarf", "empty.klarf"}
    assert B.overview(b2)["total_included_defects"] == MANIFEST["line"]["count"] + MANIFEST["empty"]["count"]
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 4

    key = by_name(b1)["F01_counts"]["analysis_key"]
    assert store.add_review(con, key, "defer", {"reason_code": "needs_sem_review"}) == 1
    revs_before = store.reviews(con, key)
    stored_before = store.get_run(con, key)
    m1_before = store.batch_members(con, b1["config"]["batch_id"])
    con.close()

    _, b3 = run(one, db=db)                                              # same inputs, new batch
    assert [e["status"] for e in b3["entries"]] == ["succeeded", "succeeded"]
    assert all(e["reused"] for e in b3["entries"]) and B.overview(b3)["reused_from_store"] == 2
    assert [e["analysis_key"] for e in b3["entries"]] == [e["analysis_key"] for e in b1["entries"]]
    assert b3["config"]["batch_id"] != b1["config"]["batch_id"]
    con = store.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 4                  # no new run rows
    assert con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1               # no new reviews
    assert store.reviews(con, key) == revs_before and store.review_status(con, key) == "deferred"
    assert store.get_run(con, key) == stored_before                                      # prediction untouched
    assert store.batch_members(con, b1["config"]["batch_id"]) == m1_before               # old batch untouched
    assert [m["rel_path"] for m in store.batch_members(con, b3["config"]["batch_id"])] == \
        ["F01_counts.klarf", "ring.klarf"]
    assert con.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 3
    rows = {r["rel_path"]: r for r in B.unit_rows(b3, con)}
    assert rows["F01_counts.klarf"]["review_status_now"] == "deferred"
    assert rows["F01_counts.klarf"]["review_latest_revision"] == 1
    con.close()


# ---------------------------------------------------------------- 21. unknown wafer id counts units (M2, C15)
def _blank_names(name, lot=True):
    """1.8 dummy file with the WaferRecord name (and optionally the LotRecord name) set to "" - the only header
    sources of batch meta for 1.8 files (wafer.batch._meta: LotID/WaferID fields absent, record names used)."""
    t = (KL / f"{name}.klarf").read_text(encoding="utf-8")
    old_w = f'Record WaferRecord "{name}"'
    assert old_w in t and "LotID" not in t and "WaferID" not in t
    t = t.replace(old_w, 'Record WaferRecord ""', 1)
    if lot:
        assert 'Record LotRecord "DUMMY_LOT"' in t
        t = t.replace('Record LotRecord "DUMMY_LOT"', 'Record LotRecord ""', 1)
    return t.encode("utf-8")


def test_21_units_with_unknown_wafer_id_counts_units_not_distinct_tuples():
    """Three analysed units without a usable header id (F01, line: lot+wafer blank; ring: wafer blank, lot kept)
    + one unit with a header id (F01_up) + a byte-identical duplicate entry of the blank F01 (an entry, not a
    unit). Expected by construction: unknown = 3 units. The old distinct-tuple count would give 2
    ((None, None), ("DUMMY_LOT", None)), so this case separates the two definitions."""
    f01_blank = _blank_names("F01_counts")
    items = [("a.klarf", f01_blank), ("b.klarf", _blank_names("ring", lot=False)), ("c.klarf", _blank_names("line")),
             ("F01_up.klarf", (KL / "F01_up.klarf").read_bytes()), ("dup.klarf", f01_blank)]
    _, b = run(items)
    assert [e["status"] for e in b["entries"]] == ["succeeded"] * 4 + ["duplicate_in_batch"]
    assert [(e["meta"]["lot"], e["meta"]["wafer"]) for e in b["entries"][:3]] ==         [(None, None), ("DUMMY_LOT", None), (None, None)]
    ov = B.overview(b)
    assert ov["analysis_units"] == 4
    assert ov["units_with_unknown_wafer_id"] == 3          # a, b, c (units, not 2 distinct tuples)
    assert ov["unique_wafers_from_header_unverified"] == 1  # (DUMMY_LOT, F01_up) only
    for i, n in ((0, "F01_counts"), (1, "ring"), (2, "line")):  # counts unaffected by the missing names
        assert b["units"][i]["result"]["n_included"] == MANIFEST[n]["count"]


# ---------------------------------------------------------------- 22. new unit_rows / summary.csv columns (M3, m7, C14)
def test_22_summary_columns_direction_area_shape_measurements_and_nulls(dummy_cov):
    rows = {r["rel_path"]: r for r in B.unit_rows(dummy_cov)}
    f01 = rows["F01_counts.klarf"]
    # plan 19.2 F01: 3h = 4, center = 1, n = 8 -> count 4, denominator 8 - 1 = 7
    assert (f01["main_direction_count"], f01["main_direction_denominator"]) == (4, 8 - 1)
    assert f01["valid_area_mm2"] == pytest.approx(DISK, rel=1e-12)     # full-disk sidecar R=150
    assert f01["lift_pin_lobes"] is None                                # lift_pin disabled in the profile
    assert f01["support_union_all_types"] == 0                          # local evaluable, no support: real 0
    assert (f01["ring_support_reason"], f01["local_support_reason"], f01["lift_pin_support_reason"]) == \
        ("type_status=insufficient_data", None, "type_status=disabled")
    assert rows["empty.klarf"]["support_union_all_types"] is None       # m7: nothing evaluable
    # ring/line measurement columns: filled exactly when the type is candidate/matched, and then equal to the
    # same unit's result.json detect.<type>.measurement (cross-channel consistency; oracle for values elsewhere)
    filled = 0
    for name, e in by_name(dummy_cov).items():
        r, row = dummy_cov["units"][e["index"]]["result"], rows[f"{name}.klarf"]
        assert row["lift_pin_lobes"] is None, name
        for t, cols in (("ring", {"ring_radius_mm": "center_radius_mm", "ring_radial_extent_mm": "radial_extent_mm",
                                  "ring_diameter_mm": "diameter_mm", "ring_thickness_mm": "ring_thickness_mm"}),
                        ("line", {"line_rms_residual_mm": "rms_residual_mm", "line_direction_deg": "direction_deg",
                                  "line_length_mm": "length_mm", "line_width_mm": "width_mm"})):
            if row[f"{t}_status"] in ("candidate", "matched"):
                meas = r["detect"][t]["measurement"]
                assert {c: row[c] for c in cols} == {c: meas[k] for c, k in cols.items()}, (name, t)
                assert all(row[c] is not None for c in cols), (name, t)
                filled += 1
            else:
                assert all(row[c] is None for c in cols), (name, t)
    assert filled > 0, "no candidate ring/line in the dummy set: the fill branch was not exercised"

    c = {r["rel_path"]: r for r in csv.DictReader(io.StringIO(B.summary_csv(dummy_cov)))}
    cf = c["F01_counts.klarf"]
    assert (cf["main_direction_count"], cf["main_direction_denominator"]) == ("4", "7")
    assert float(cf["valid_area_mm2"]) == pytest.approx(DISK, rel=1e-12)
    assert (cf["lift_pin_lobes"], cf["ring_radius_mm"], cf["support_union_all_types"]) == ("", "", "0")
    assert c["empty.klarf"]["support_union_all_types"] == ""           # null -> empty cell, not "0"

    _, b = run([("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())])   # no sidecar
    cn = next(csv.DictReader(io.StringIO(B.summary_csv(b))))
    assert (cn["valid_area_mm2"], cn["density_per_mm2"], cn["density_reason"]) == ("", "", "coverage_unknown")
    assert (cn["main_direction_count"], cn["main_direction_denominator"]) == ("4", "7")


# ---------------------------------------------------------------- 23. nothing analysed -> total null (m2, C15)
def test_23_total_included_is_null_when_nothing_was_analysed_and_zero_for_a_real_empty_map(tmp_path):
    items = [("broken.klarf", damaged_bytes()), ("notes.txt", b"not a klarf file\n"), ("a.png", b"\x89PNG")]
    _, b = run(items)
    ov = B.overview(b)
    assert (ov["analysis_units"], ov["failed"], ov["excluded"]) == (0, 2, 1)
    assert ov["total_included_defects"] is None
    man = json.loads(zipfile.ZipFile(io.BytesIO(B.export_zip(b))).read("batch_manifest.json"))
    assert man["overview"]["total_included_defects"] is None
    _, b0 = run([("empty.klarf", (KL / "empty.klarf").read_bytes())])
    assert MANIFEST["empty"]["count"] == 0
    assert B.overview(b0)["total_included_defects"] == 0 and B.overview(b0)["analysis_units"] == 1
