"""Null values carry a reason (approved spec change 2026-10-11, user: "계산 불가 값은 None으로 두어도 됨. 계산 불가
comment와 사유를 streamlit과 결과파일에 표기할 수 있게"). Result schema result-0.2.

Contract checked here (E16-NULLWHY, E10-UP-NULLWHY, E11-NULLWHY; C15):
  * result["null_reasons"] has a non-empty reason for EXACTLY the top-level fields whose value is None;
  * check_result rejects a result whose null_reasons misses a null field, explains a non-null field, or is empty;
  * spatial_counts.csv: every row with an empty count/area/density cell has a non-empty reason;
  * CSV manifest.json: null_reasons.result == result null_reasons, defects.csv per-column reasons cover every
    column that has an empty cell.
Expected null sets are stated by hand from the profile/input (die rule never configured -> T-13; notch line
removed -> clock withheld, T-02/E10; clock/zones/radial switched off -> those fields), not copied from output.
Inputs: klarf_dummy_data (synthetic, seed 20261009), tests/fixtures/klarf/f01.klf (f01-oracle-1). TEST-ONLY profiles.
"""
import copy
import csv
import json
from pathlib import Path

import pytest
import yaml

from wafer.cli import analyze_file, main
from wafer.profile import load_profile
from wafer.report import ResultInvariantError, check_result

ROOT = Path(__file__).resolve().parent.parent
DD = ROOT / "klarf_dummy_data"
KL = DD / "klarf"
SIDECAR = DD / "synthetic_profile.json"
DUMMY_PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"
F01_KLF = ROOT / "tests/fixtures/klarf/f01.klf"
F01_PROFILE = ROOT / "tests/profiles/f01_test_profile.yaml"
CASES = [c["name"] for c in json.loads((DD / "manifest.json").read_text(encoding="utf-8"))["cases"]]

DIE = {"affected_die_count", "inspected_die_count"}          # no die rule / inspected-die list (T-13)
CLOCK = {"sectors_clock", "sectors_clock_tolerant", "n_multi_sector", "boundary_ambiguous", "bin_sector"}


def _no_notch(tmp, src, needle):
    lines = src.read_bytes().decode("utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if needle not in ln]
    assert len(lines) - len(kept) == 1, needle                 # exactly the notch line removed
    p = tmp / f"{src.stem}_nonotch{src.suffix}"
    p.write_bytes("".join(kept).encode("utf-8"))
    return p


def _off_profile(tmp):
    d = yaml.safe_load(F01_PROFILE.read_text(encoding="utf-8"))
    d["clock"]["center_exclusion_radius_mm"] = None
    for z in ("E1", "E2", "zone_8inch_inside", "zone_8inch_boundary"):
        d["zones"][z]["enabled"] = False
    d["stats"]["radial_bin_mm"] = None
    p = tmp / "off.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    return p


def _cli(tmp, klarf, profile, coverage=None):
    tmp.mkdir(parents=True, exist_ok=True)
    argv = [str(klarf), "--profile", str(profile), "--out", str(tmp / "o.json"), "--csv-dir", str(tmp / "csv")]
    if coverage:
        argv += ["--coverage", str(coverage)]
    assert main(argv) == 0
    return json.loads((tmp / "o.json").read_text(encoding="utf-8")), tmp / "csv"


def _runs(tmp):
    """(label, output doc, csv dir, expected null set). Expected sets are hand-stated (see module docstring)."""
    out = []
    for case in CASES:
        for cov in (None, SIDECAR):
            doc, d = _cli(tmp / f"{case}_{bool(cov)}", KL / f"{case}.klarf", DUMMY_PROFILE, cov)
            out.append((f"{case}/cov={bool(cov)}", doc, d, DIE))
    for cov in (None, SIDECAR):
        doc, d = _cli(tmp / f"f01_{bool(cov)}", F01_KLF, F01_PROFILE, cov)
        out.append((f"f01/cov={bool(cov)}", doc, d, DIE))
    nn = _no_notch(tmp, KL / "F01_counts.klarf", "Field OrientationMarkLocation")
    doc, d = _cli(tmp / "F01_counts_nonotch", nn, DUMMY_PROFILE)
    out.append(("F01_counts/nonotch", doc, d, DIE | CLOCK))
    nn = _no_notch(tmp, F01_KLF, "OrientationMarkLocation")
    doc, d = _cli(tmp / "f01_nonotch", nn, F01_PROFILE, SIDECAR)
    out.append(("f01/nonotch/cov", doc, d, DIE | CLOCK))
    doc, d = _cli(tmp / "f01_off", F01_KLF, _off_profile(tmp))
    # clock disabled -> no center region either; no zone enabled -> no union
    out.append(("f01/off", doc, d, DIE | CLOCK | {"center", "zone_union_unique"}))
    return out


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return _runs(tmp_path_factory.mktemp("nullwhy"))


def _top_nulls(r):
    return {k for k, v in r.items() if v is None}


# ---------------------------------------------------------------- A. result null_reasons (E16/E10/E11, C15)
def test_a_result_null_reasons_explain_exactly_the_null_fields(runs):
    assert len(runs) == 2 * len(CASES) + 5
    for label, doc, _, expect in runs:
        r = doc["result"]
        assert r["provenance"]["schema_version"] == "result-0.2", label
        assert _top_nulls(r) == expect, label                      # hand-stated null set
        nr = r["null_reasons"]
        assert set(nr) == expect, label
        assert all(isinstance(v, str) and v.startswith("not computable") for v in nr.values()), label
        assert "T-13" in nr["affected_die_count"] and "T-13" in nr["inspected_die_count"], label


def test_a_notch_removed_clock_reasons_name_orientation_and_center_stays_a_number(runs):
    by = {label: doc["result"] for label, doc, _, _ in runs}
    for label in ("F01_counts/nonotch", "f01/nonotch/cov"):
        r = by[label]
        assert r["center"] == 1                                    # plan 19.2: rotation invariant, not withheld
        assert all("orientation_unknown" in r["null_reasons"][k] for k in CLOCK), label
    off = by["f01/off"]["null_reasons"]
    assert "center_exclusion_radius_mm" in off["center"] and "zone" in off["zone_union_unique"]


# ---------------------------------------------------------------- B. check_result gate (C15)
@pytest.fixture(scope="module")
def good():
    return analyze_file(str(F01_KLF), load_profile(str(F01_PROFILE)))


@pytest.mark.parametrize("label,mutate", [
    ("null_field_missing_reason", lambda r: r["null_reasons"].pop("affected_die_count")),
    ("new_null_without_reason", lambda r: r.update(zone_union_unique=None)),
    ("reason_for_non_null_field", lambda r: r["null_reasons"].update(center="not computable: invented")),
    ("empty_reason", lambda r: r["null_reasons"].update(inspected_die_count="")),
    ("null_reasons_absent", lambda r: r.pop("null_reasons")),
])
def test_b_check_result_rejects_unexplained_or_extra_null_reasons(good, label, mutate):
    check_result(copy.deepcopy(good))                              # the unmodified result passes
    bad = copy.deepcopy(good)
    mutate(bad)
    with pytest.raises(ResultInvariantError):
        check_result(bad)


# ---------------------------------------------------------------- C. spatial_counts.csv reasons (C15)
def test_c_every_spatial_row_with_an_empty_cell_has_a_reason(runs):
    for label, _, d, _ in runs:
        rows = list(csv.DictReader(open(d / "spatial_counts.csv", encoding="utf-8", newline="")))
        assert rows, label
        for row in rows:
            if "" in (row["count"], row["area_mm2"], row["density_per_mm2"]):
                assert row["reason"].strip(), (label, row["table"], row["key"])


def test_c_disabled_rows_are_not_computable_and_count_only_rows_say_so(runs):
    by = {label: d for label, _, d, _ in runs}
    off = {(r["table"], r["key"]): r for r in csv.DictReader(open(by["f01/off"] / "spatial_counts.csv", encoding="utf-8"))}
    for k in (("sector_strict", "*"), ("sector_tolerant", "*"), ("center", "center"), ("zone", "E1"),
              ("zone_union", "unique"), ("radial", "*")):
        assert off[k]["count"] == "" and off[k]["reason"].startswith("not computable: "), k
    on = {(r["table"], r["key"]): r for r in csv.DictReader(open(by["f01/cov=True"] / "spatial_counts.csv", encoding="utf-8"))}
    assert on[("sector_strict", "1")]["count"] == "0"              # real zero, not null
    assert "count-only" in on[("sector_strict", "1")]["reason"] and "count-only" in on[("bin_total", "1")]["reason"]
    assert all(r["reason"] == "" for k, r in on.items() if k[0] == "radial")   # density computed -> no null cell


# ---------------------------------------------------------------- E. CSV manifest null_reasons (E16, C14/C15)
def test_e_csv_manifest_carries_result_and_defect_column_reasons(runs):
    for label, doc, d, _ in runs:
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        assert m["null_convention"].startswith("empty cell = null"), label
        nr = m["null_reasons"]
        assert nr["result"] == doc["result"]["null_reasons"], label
        assert nr["spatial_counts.csv"] and nr["bin_sector.csv"], label
        cols = nr["defects.csv"]
        assert all(isinstance(v, str) and v for v in cols.values()), label
        rows = list(csv.DictReader(open(d / "defects.csv", encoding="utf-8", newline="")))
        empty_cols = {c for row in rows for c, v in row.items() if v == ""}
        assert empty_cols <= set(cols), (label, empty_cols - set(cols))
    by = {label: (doc, d) for label, doc, d, _ in runs}
    cols = json.loads((by["F01_counts/nonotch"][1] / "manifest.json").read_text(encoding="utf-8"))["null_reasons"]["defects.csv"]
    assert "orientation_unknown" in cols["clock"]
    cols = json.loads((by["f01/off"][1] / "manifest.json").read_text(encoding="utf-8"))["null_reasons"]["defects.csv"]
    assert "no zone enabled" in cols["zones"]
