"""klarf_dummy_data_mixed (38 messy SYNTHETIC KLARF 1.8 files, MixedWM38-style class list) through cli.run_job.

Fixture: user request 2026-10-12 ("더 지저분한 MixedWM38 스타일 dummy KLARF 데이터셋"). Generator
klarf_dummy_data_mixed/generate_mixed.py (stdlib only, seed 20261012) writes klarf/*.klarf, expected/<name>.json|csv
and manifest.json. Oracle = the generator's own stdlib computation (never imports wafer/*), i.e. independent of the
code under test. Same file contract as klarf_dummy_data: adapter synthetic-die-local-v1, notch DOWN, TEST-ONLY
profile tests/profiles/dummy_die_local_test_profile.yaml, coverage sidecar klarf_dummy_data/synthetic_profile.json.
Messy features checked here: events just outside r=150 (excluded outside_wafer), distinct events at an identical
position, CLASSNUMBER 0 (-> bin "unknown"), dense background / nuisance clumps / gaps (counts only).

Scope (CLAUDE.md 6-5, 6-9, C20): synthetic adapter + aggregation checks only. Not a real tool-adapter validation,
not a MixedWM38 (EDS) evaluation, not a shape-classification evaluation, not a UI/E2E run.
N/A by design: shape labels (ring / line / local / mixed). class_label / generation_groups are the generator's
pattern intent ("generation_intent_only": true, "classifier_output_validated": false); asserting a detector label
against them would turn an intent into a golden answer. generation_groups is used only to locate the
duplicate-position records (an input property), never as a classification oracle.

Links: E01-MIXED38 (counts / bins / center / clock / exclusions), E06 (mixed classes: counts preserved per file,
no shape label), E09-MIXED (unknown bin, identical-position events kept), E01-BATCH-MIXED (folder batch subset),
E16-NULLWHY (null_reasons contract); C01 C02 C04 C10 C14 C15 C20; P1-01 P1-02 P1-03.
"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from wafer import batch as B
from wafer.cli import run_job

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "klarf_dummy_data_mixed"
KL = MD / "klarf"
EXP = MD / "expected"
SIDECAR = ROOT / "klarf_dummy_data/synthetic_profile.json"
PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"

MANIFEST_DOC = json.loads((MD / "manifest.json").read_text(encoding="utf-8"))
MANIFEST = {c["name"]: c for c in MANIFEST_DOC["cases"]}
CASES = list(MANIFEST)
DIE = {"affected_die_count", "inspected_die_count"}       # no die rule / inspected-die list (T-13), hand-stated

# MixedWM38 class list, stated by hand (Normal + 8 single + 13 two-mixed + 12 three-mixed + 4 four-mixed = 38)
MIXEDWM38 = (
    ["Normal"]
    + ["C", "D", "EL", "ER", "L", "NF", "S", "R"]
    + ["C+EL", "C+ER", "C+L", "C+S", "D+EL", "D+ER", "D+L", "D+S", "EL+L", "EL+S", "ER+L", "ER+S", "L+S"]
    + ["C+EL+L", "C+EL+S", "C+ER+L", "C+ER+S", "C+L+S", "D+EL+L", "D+EL+S", "D+ER+L", "D+ER+S", "D+L+S",
       "EL+L+S", "ER+L+S"]
    + ["C+L+EL+S", "C+L+ER+S", "D+L+EL+S", "D+L+ER+S"]
)
COMPONENT_NAMES = {"C": "Center", "D": "Donut", "EL": "Edge-Loc", "ER": "Edge-Ring", "L": "Loc", "NF": "Near-full",
                   "S": "Scratch", "R": "Random"}
BATCH_SUBSET = ["N00_normal", "S03_EL", "S06_NF", "M2_13_L+S", "M3_07_D+EL+S", "M4_04_D+L+ER+S"]


def expected_json(case):
    return json.loads((EXP / f"{case}.json").read_text(encoding="utf-8"))


def expected_rows(case):
    with open(EXP / f"{case}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sk(d):
    """In-process results keep int hour keys; the oracle uses strings."""
    return None if d is None else {str(k): v for k, v in d.items()}


_RUNS = {}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """One cached run_job per file: TEST-ONLY dummy profile + full-disk sidecar + CSV export (no DB)."""
    def _run(case):
        if case not in _RUNS:
            csvd = tmp_path_factory.mktemp(case.replace("+", "_")) / "csv"
            out, code = run_job(str(KL / f"{case}.klarf"), str(PROFILE), csv_dir=str(csvd),
                                coverage_path=str(SIDECAR))
            _RUNS[case] = (code, out, csvd)
        return _RUNS[case]
    return _run


# ---------------------------------------------------------------- 1. class list, names, hashes (oracle integrity)
def test_01_class_list_is_the_mixedwm38_38_and_hashes_match():
    assert len(MIXEDWM38) == len(set(MIXEDWM38)) == 38
    assert [MANIFEST[c]["class_label"] for c in CASES] == MIXEDWM38          # manifest order = class list order
    order = [0] + [1] * 8 + [2] * 13 + [3] * 12 + [4] * 4
    assert [MANIFEST[c]["mixed_order"] for c in CASES] == order
    prefix = ["N00"] + [f"S{i:02d}" for i in range(1, 9)] + [f"M2_{i:02d}" for i in range(1, 14)] + \
        [f"M3_{i:02d}" for i in range(1, 13)] + [f"M4_{i:02d}" for i in range(1, 5)]
    for case, p, label in zip(CASES, prefix, MIXEDWM38, strict=True):
        assert case.startswith(p + "_"), case
        assert case.endswith("normal" if label == "Normal" else label), case
    assert MANIFEST_DOC["seed"] == 20261012 and MANIFEST_DOC["synthetic_only"] is True
    assert MANIFEST_DOC["adapter"] == "synthetic-die-local-v1"
    assert sorted(p.name for p in KL.glob("*.klarf")) == sorted(f"{c}.klarf" for c in CASES)
    for case in CASES:
        m, ej = MANIFEST[case], expected_json(case)
        sha = hashlib.sha256((KL / f"{case}.klarf").read_bytes()).hexdigest()
        assert sha == m["file_sha256"] == ej["file_sha256"], case
        for k in ("class_label", "mixed_order", "count", "n_included", "n_excluded"):
            assert ej[k] == m[k], (case, k)
        comps = [] if ej["class_label"] == "Normal" else ej["class_label"].split("+")
        assert ej["components"] == [{"code": c, "name": COMPONENT_NAMES[c]} for c in comps], case
        assert ej["generation_intent_only"] is True and ej["classifier_output_validated"] is False, case
        # oracle self-consistency (no program output involved)
        rows = expected_rows(case)
        assert len(rows) == ej["count"] == ej["n_included"] + ej["n_excluded"], case
        assert sum(ej["bin_counts"].values()) == ej["n_included"], case
        assert sum(ej["clock_counts"].values()) + ej["center_count"] == ej["n_included"], case
        assert sorted(int(r["defect_id"]) for r in rows if r["included"] == "False") == ej["excluded_ids"], case


# ---------------------------------------------------------------- 2. generator determinism
def test_02_generator_reproduces_byte_identical_files(tmp_path):
    spec = importlib.util.spec_from_file_location("generate_mixed_under_test", MD / "generate_mixed.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.main(["--out", str(tmp_path)])
    assert (tmp_path / "manifest.json").read_bytes() == (MD / "manifest.json").read_bytes()
    for case in CASES:
        assert (tmp_path / "klarf" / f"{case}.klarf").read_bytes() == (KL / f"{case}.klarf").read_bytes(), case
        for ext in ("json", "csv"):
            assert (tmp_path / "expected" / f"{case}.{ext}").read_bytes() == \
                (EXP / f"{case}.{ext}").read_bytes(), (case, ext)
    assert not (tmp_path / "maps").exists()                                  # no --png -> no image written


# ---------------------------------------------------------------- 3. per-file counts / bins / clock (E01-MIXED38, E09-MIXED)
@pytest.mark.parametrize("case", CASES)
def test_03_counts_bins_center_clock_exclusions_equal_oracle(case, run):
    ej, rows = expected_json(case), expected_rows(case)
    code, out, csvd = run(case)
    assert code == 0 and out["job_status"] == "succeeded" and out["data_quality_status"] == "valid"
    r = out["result"]
    assert r["provenance"]["source_sha256"] == ej["file_sha256"]
    assert r["provenance"]["adapter"] == "synthetic-die-local-v1"
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == (ej["count"], ej["n_included"], ej["n_excluded"])
    assert r["bin_totals"] == ej["bin_counts"]                               # incl. "unknown" (CLASSNUMBER 0)
    assert r["center"] == ej["center_count"]
    assert sk(r["sectors_clock"]) == ej["clock_counts"]
    # exclusions: event key "<record order>:<DEFECTID>" -> DEFECTID; reason outside_wafer (r > 150)
    assert sorted(int(e["defect_id"].split(":")[1]) for e in r["excluded"]) == ej["excluded_ids"]
    assert {e["reason"] for e in r["excluded"]} <= {"outside_wafer"}

    # defects.csv row order is not asserted: the export lists included rows (record order) and then the excluded
    # rows; no approved contract fixes the row order when exclusions exist, so rows are matched by event key.
    d = read_csv(csvd / "defects.csv")
    keys = [f"{k}:{int(e['defect_id'])}" for k, e in enumerate(rows, start=1)]
    assert len(d) == len({x["defect_id"] for x in d}) == len(rows)         # one row per event, none merged
    by_key = {x["defect_id"]: x for x in d}
    assert set(by_key) == set(keys)
    for key, exp in zip(keys, rows, strict=True):
        got = by_key[key]
        assert got["included"] == exp["included"], got["defect_id"]
        assert got["bin"] == exp["classification_bin"], got["defect_id"]
        if exp["included"] == "True":
            assert got["clock"] == exp["clock_hour"], got["defect_id"]
        else:
            assert got["excluded_reason"] == "outside_wafer" and got["clock"] == "", got["defect_id"]

    # null_reasons contract (result-0.2, C15): with notch + sidecar only the die counts are null (hand-stated)
    nulls = {k for k, v in r.items() if v is None}
    assert nulls == DIE and set(r["null_reasons"]) == DIE
    assert all(isinstance(v, str) and v.startswith("not computable") for v in r["null_reasons"].values())
    assert r["clark_evans"]["calc_status"] == "computed"                     # coverage declared -> computable


@pytest.mark.parametrize("case", CASES)
def test_03b_identical_position_events_are_kept_as_separate_events(case, run):
    """E09-MIXED: the generator appends 1-3 copies of an existing in-wafer record (new DEFECTID, same
    XINDEX/XREL/YINDEX/YREL). Each copy and its source must both be present, included and distinct events."""
    ej, rows = expected_json(case), expected_rows(case)
    dup_ids = [i for g, ids in ej["generation_groups"].items() if g.startswith("duplicate_position(") for i in ids]
    assert 1 <= len(dup_ids) <= 3, case
    by_id = {int(e["defect_id"]): e for e in rows}
    d = {x["defect_id"]: x for x in read_csv(run(case)[2] / "defects.csv")}
    for i in dup_ids:
        pos = (by_id[i]["x_mm"], by_id[i]["y_mm"])
        same = [k for k, e in by_id.items() if (e["x_mm"], e["y_mm"]) == pos]
        assert len(same) >= 2, (case, i)                                    # source + copy in the oracle
        got = [x for x in d.values() if int(x["defect_id"].split(":")[1]) in same]
        assert len(got) == len(same) and len({x["defect_id"] for x in got}) == len(same), (case, i)
        assert all(x["included"] == "True" for x in got), (case, i)
        assert len({(x["x_mm"], x["y_mm"]) for x in got}) == 1, (case, i)    # truly the same position


def test_03c_messy_features_are_present_in_the_set():
    """Guards the fixture itself: the set really carries exclusions and unknown bins (else 3/3b prove little)."""
    ejs = [expected_json(c) for c in CASES]
    assert sum(e["n_excluded"] for e in ejs) > 0
    assert sum(1 for e in ejs if e["n_excluded"] > 0) >= 10
    assert all(e["bin_counts"].get("unknown", 0) > 0 for e in ejs)


# ---------------------------------------------------------------- 4. folder batch subset (E01-BATCH-MIXED)
def test_04_folder_batch_subset_totals_equal_the_oracle_sum(tmp_path):
    root = tmp_path / "upload"
    for k, case in enumerate(BATCH_SUBSET):
        sub = root / f"lot{k % 2}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"{case}.klarf").write_bytes((KL / f"{case}.klarf").read_bytes())
    items = B.folder_items(root)
    assert len(items) == len(BATCH_SUBSET)
    s = B.scan(items, str(PROFILE), coverage_path=str(SIDECAR))
    b = B.run_batch(items, s, str(PROFILE), coverage_path=str(SIDECAR))
    want = sum(MANIFEST[c]["n_included"] for c in BATCH_SUBSET)
    ov = B.overview(b)
    assert ov["files_uploaded"] == ov["analysis_units"] == ov["succeeded"] == len(BATCH_SUBSET)
    assert (ov["failed"], ov["held"], ov["excluded"], ov["duplicates_in_batch"]) == (0, 0, 0, 0)
    assert ov["total_included_defects"] == want
    for e in b["entries"]:
        name = Path(e["rel_path"]).stem
        r = b["units"][e["index"]]["result"]
        assert e["status"] == "succeeded", name
        assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == \
            (MANIFEST[name]["count"], MANIFEST[name]["n_included"], MANIFEST[name]["n_excluded"]), name
    exp_bins = {}
    for c in BATCH_SUBSET:
        for k, v in expected_json(c)["bin_counts"].items():
            exp_bins[k] = exp_bins.get(k, 0) + v
    g = B.bin_totals_by_group(b)
    assert len(g) == 1 and g[0]["bin_totals"] == exp_bins
    dens = B.batch_density(b)
    assert len(dens) == 1 and dens[0]["sum_count"] == want
    assert dens[0]["units_in_density"] == len(BATCH_SUBSET)                 # no event left outside after exclusion
