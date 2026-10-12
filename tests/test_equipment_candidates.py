"""Batch-level candidates (approved user request 2026-10-12): equipment repeat (equip_ring / equip_line /
equip_local) grouped by the INSPECTION tool (KLARF InspectionStationID, any StepID), defect volume
(inspection_abort_suspect / excess_defect), candidate_types column position and the gallery title link.

Sub-cases (docs/3_user_scenarios.md 2.3): E06-EQUIP (several candidate axes on one wafer, per-wafer codes kept),
E16-GALLERY-TYPES (table <-> gallery <-> summary.csv consistency, column order), E12-EQUIP-CONFIG (profile
validation), E13-VOLUME (defect volume statuses), E17-BATCH (grouping across files / old batch dicts).
C IDs: C11 (overlap kept, union not summed), C14 (same value on every channel), C15 (null vs 0 + reason),
C17 (state vocabulary separate), C20 (synthetic only).

Scope: SYNTHETIC inputs only (klarf_dummy_data, seed 20261009). The equipment / step header lines are inserted in
memory by this file (no dataset file is added). The tolerances in tests/profiles/dummy_die_local_test_profile.yaml
are TEST-ONLY; a repeat is a candidate, never a confirmed equipment cause.

Oracles (never the output of the function under test):
  * identical defect coordinates on N wafers -> every measured feature difference is exactly 0, so any per-wafer
    ring / line candidate (notch registered) and any >= local_min_points cluster MUST repeat on all N; a notch
    declared UP (180 deg) / LEFT (270 deg) rotates the same raw points (klarf_dummy_data/README), so a 3 o'clock
    cluster lands at 9 o'clock (~2r apart >> 15 mm) and a horizontal line becomes vertical (90 deg >> 10 deg);
    ring center radius is rotation invariant (r ~80 mm ring vs r ~148 mm edge ring: 68 mm >> 5 mm);
  * n_parsed = manifest count (F01_counts 8, ring 240, mixed 300, empty 0), thresholds chosen here;
  * the previous unit_rows column order is written out by hand below (from the 2026-10-11 code);
  * gallery label formatting stated by hand (', ' join, '' -> 없음, None -> -).
"""
import copy
import csv
import io
import json
import math
from pathlib import Path

import pytest
import yaml

from wafer import batch as B
from wafer import batch_ui
from wafer.profile import ConfigInvalid, parse_profile, validate_for_run

ROOT = Path(__file__).resolve().parent.parent
DD = ROOT / "klarf_dummy_data"
KL = DD / "klarf"
PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"
MANIFEST = {c["name"]: c for c in json.loads((DD / "manifest.json").read_text(encoding="utf-8"))["cases"]}
CAND = ("candidate", "matched")

STEP_LINE = '   Field StepID 1 {"DUMMY_INSPECTION"}\n'
NOTCH_LINE = '   Field OrientationMarkLocation 1 {"DOWN"}\n'
EQUIP_COLS = {"equipment_id", "step_id", "equipment_signature_status", "equipment_signature_reason",
              "equipment_signature_detail", "defect_volume_status", "defect_volume_reason"}

# unit_rows key order of an analysed row BEFORE 2026-10-12 (no con), written out from the 2026-10-11 code
OLD_ANALYSED_ORDER = [
    "index", "rel_path", "lot", "wafer", "job", "status", "reason", "duplicate_of", "reused", "analysis_key",
    "data_quality", "candidate_types", "n_included", "bins", "main_direction", "main_direction_ratio",
    "main_direction_count", "main_direction_denominator", "direction_reason", "valid_area_mm2", "density_per_mm2",
    "density_reason", "ring_radius_mm", "ring_diameter_mm", "ring_thickness_mm", "ring_radial_extent_mm",
    "line_length_mm", "line_width_mm", "line_rms_residual_mm", "line_direction_deg", "lift_pin_lobes",
    "support_union_all_types",
    "ring_status", "line_status", "local_status", "lift_pin_status",
    "ring_support", "line_support", "local_support", "lift_pin_support",
    "ring_support_ratio", "line_support_ratio", "local_support_ratio", "lift_pin_support_ratio",
    "ring_support_reason", "line_support_reason", "local_support_reason", "lift_pin_support_reason",
    "null_reasons"]
OLD_NOT_ANALYSED_ORDER = ["index", "rel_path", "lot", "wafer", "job", "status", "reason", "duplicate_of", "reused",
                          "analysis_key", "null_reasons"]


def moved(order):
    """Approved change: candidate_types right after status, everything else in its previous relative order."""
    rest = [c for c in order if c != "candidate_types"]
    i = rest.index("status") + 1
    return rest[:i] + ["candidate_types"] + rest[i:]


def variant(name, tool=None, step="DUMMY_INSPECTION", notch="DOWN", station_text=None):
    """In-memory copy of a dummy file: StepID replaced, optional InspectionStationID line, notch changed/removed."""
    t = (KL / f"{name}.klarf").read_text(encoding="utf-8")
    assert STEP_LINE in t and NOTCH_LINE in t
    new = f'   Field StepID 1 {{"{step}"}}\n'
    if station_text is None and tool:
        station_text = f'{{"KLA", "M1", "{tool}"}}'
    if station_text:
        new += f"   Field InspectionStationID 3 {station_text}\n"
    t = t.replace(STEP_LINE, new, 1)
    t = t.replace(NOTCH_LINE, "" if notch is None else f'   Field OrientationMarkLocation 1 {{"{notch}"}}\n', 1)
    return t.encode("utf-8")


def run(items, profile=PROFILE):
    s = B.scan(items, str(profile))
    return B.run_batch(items, s, str(profile))


def profile_with(tmp_path, name, **changes):
    """TEST-ONLY profile copy; changes = {"block.key": value}."""
    d = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    for k, v in changes.items():
        block, key = k.split(".")
        d[block][key] = v
    p = tmp_path / f"{name}.yaml"
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    return p


def per_wafer_codes(batch, index):
    ts = B.type_status(batch["units"][index]["result"])
    return [t for t in B.TYPES if ts[t] in CAND]


def rows_by_path(batch):
    return {r["rel_path"]: r for r in B.unit_rows(batch)}


def split(v):
    return [c for c in v.split(",") if c] if v else []


@pytest.fixture(scope="module")
def dummy13():
    return run([(f"{n}.klarf", (KL / f"{n}.klarf").read_bytes()) for n in MANIFEST])


# ---------------------------------------------------------------- A. per-wafer codes unchanged (E06-EQUIP, C14)
def test_a_per_wafer_codes_are_unchanged_and_form_the_prefix(dummy13, tmp_path):
    """The 13 dummy files carry no InspectionStationID and the dummy profile leaves defect_volume null, so no
    batch-level code can be added: candidate_types must equal the 2026-10-11 definition exactly. Hand-checked
    values: F01_counts '' (ring/line insufficient_data: 8 < min_points, local no_match, lift_pin disabled; see
    test_batch test_06) and empty '' (nothing evaluable)."""
    rows = rows_by_path(dummy13)
    for e in dummy13["entries"]:
        row = rows[e["rel_path"]]
        assert row["candidate_types"] == ",".join(per_wafer_codes(dummy13, e["index"])), e["rel_path"]
        assert row["equipment_signature_status"] == "insufficient_data"
        assert row["equipment_signature_reason"] == "no InspectionStationID in the KLARF header (equipment unknown)"
        assert row["defect_volume_status"] == "disabled"
    assert rows["F01_counts.klarf"]["candidate_types"] == "" and rows["empty.klarf"]["candidate_types"] == ""
    assert any(rows[p]["candidate_types"] for p in rows), "no per-wafer candidate in the dummy set"

    # equipment_signature disabled (and an equipment header present): still exactly the old definition
    off = profile_with(tmp_path, "off", **{"equipment_signature.enabled": False})
    names = ("ring", "line", "local_3oclock")
    b = run([(f"{n}_{s}.klarf", variant(n, "TOOL_A", s)) for n in names for s in ("S_A", "S_B", "S_C")], off)
    for e in b["entries"]:
        row = rows_by_path(b)[e["rel_path"]]
        assert row["candidate_types"] == ",".join(per_wafer_codes(b, e["index"])), e["rel_path"]
        assert (row["equipment_signature_status"], row["equipment_id"]) == ("disabled", "KLA M1 TOOL_A")
        assert json.loads(row["equipment_signature_detail"]) == {}

    # enabled: the per-wafer codes are the unchanged prefix, batch codes only from EQUIP_TYPES after it
    b = run([(f"{n}_{s}.klarf", variant(n, "TOOL_A", s)) for n in names for s in ("S_A", "S_B", "S_C")])
    added = 0
    for e in b["entries"]:
        pw = per_wafer_codes(b, e["index"])
        codes = split(rows_by_path(b)[e["rel_path"]]["candidate_types"])
        assert codes[:len(pw)] == pw, e["rel_path"]
        assert set(codes[len(pw):]) <= set(B.EQUIP_TYPES)
        assert codes[len(pw):] == [c for c in B.EQUIP_TYPES if c in codes[len(pw):]]     # fixed order
        added += len(codes) - len(pw)
    assert added > 0


# ---------------------------------------------------------------- B. column order (E16-GALLERY-TYPES, C14)
def test_b_candidate_types_follows_status_and_old_columns_keep_their_order(tmp_path):
    items = [("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes()),
             ("ring.klarf", (KL / "ring.klarf").read_bytes()),
             ("map.png", b"\x89PNG"), ("broken.klarf", b"not a klarf\n")]
    b = run(items)
    rows = rows_by_path(b)
    for p in ("F01_counts.klarf", "ring.klarf"):
        keys = list(rows[p])
        assert keys.index("candidate_types") == keys.index("status") + 1
        assert [k for k in keys if k in OLD_ANALYSED_ORDER] == moved(OLD_ANALYSED_ORDER), p
        assert set(keys) - set(OLD_ANALYSED_ORDER) == EQUIP_COLS
        assert keys[-1] == "null_reasons"
    for p in ("map.png", "broken.klarf"):                       # not analysed: same position, value None
        assert list(rows[p]) == moved(OLD_NOT_ANALYSED_ORDER + ["candidate_types"]), p
        assert rows[p]["candidate_types"] is None

    header = next(csv.reader(io.StringIO(B.summary_csv(b))))
    assert header.index("candidate_types") == header.index("status") + 1
    assert [c for c in header if c in OLD_ANALYSED_ORDER] == moved(OLD_ANALYSED_ORDER)


def test_b_summary_csv_header_when_the_first_entry_is_not_analysed():
    """The csv header is the union of row keys in first-seen order: with a non-analysed first row the
    position of candidate_types must still be right after status."""
    b = run([("map.png", b"\x89PNG"), ("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())])
    header = next(csv.reader(io.StringIO(B.summary_csv(b))))
    assert header[:8] == ["index", "rel_path", "lot", "wafer", "job", "status", "candidate_types", "reason"]
    old_seen = [c for c in header if c in OLD_ANALYSED_ORDER and c != "null_reasons"]
    assert old_seen == [c for c in moved(OLD_ANALYSED_ORDER) if c != "null_reasons"]


# ---------------------------------------------------------------- C. gallery title <-> unit table (AppTest)
def test_c_types_label_cases():
    assert batch_ui._types_label(None) == "-"
    assert batch_ui._types_label(float("nan")) == "-"
    assert batch_ui._types_label("") == "없음"
    assert batch_ui._types_label("ring") == "ring"
    assert batch_ui._types_label("ring,local,equip_local") == "ring, local, equip_local"


def _apptest_run(files):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "wafer/app.py"), default_timeout=180)
    at.run()
    at.file_uploader(key="batch_files").set_value([(n, d, "application/octet-stream") for n, d in files])
    at.text_input(key="batch_profile_path").set_value(str(PROFILE))
    at.button(key="batch_scan_btn").click().run()
    assert not at.exception, at.exception
    at.button(key="batch_run_btn").click().run()
    assert not at.exception, at.exception
    return at


def _unit_table(at):
    t = [d.value for d in at.dataframe if {"rel_path", "candidate_types", "status"} <= set(d.value.columns)]
    assert len(t) == 1
    return t[0]


def _gallery_titles(at):
    out = {}
    for el in at.get("plotly_chart"):
        title = json.loads(el.proto.spec)["layout"]["title"]["text"]
        head, label = title.split(" · 후보: ")
        idx, path = head[1:].split(" ", 1)
        out[int(idx)] = (path, label)
    return out


def _hand_label(cell):
    """Expected gallery text from the table cell (str of the dataframe): stated by hand, not via _types_label."""
    if cell == "None":
        return "-"
    return ", ".join(c for c in cell.split(",") if c) or "없음"


GALLERY_FILES = ([("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes()),
                  ("mixed.klarf", (KL / "mixed.klarf").read_bytes()),
                  ("broken.klarf", b"not a klarf\n")]
                 + [(f"loc_{s}.klarf", variant("local_3oclock", "TOOL_A", s)) for s in ("S_A", "S_B", "S_C")])


def test_c_gallery_titles_show_the_unit_table_candidate_types():
    at = _apptest_run(GALLERY_FILES)
    df = _unit_table(at)
    cols = list(df.columns)
    assert cols.index("candidate_types") == cols.index("status") + 1
    assert [c for c in cols if c in OLD_ANALYSED_ORDER] == moved(OLD_ANALYSED_ORDER)
    table = {int(i): (p, c) for i, p, c in zip(df["index"], df["rel_path"], df["candidate_types"])}
    titles = _gallery_titles(at)
    b = at.session_state["batch"]
    assert set(titles) == set(b["units"]) and len(titles) == 5       # broken.klarf: no unit, no thumbnail
    for i, (path, label) in titles.items():
        assert path == table[i][0]
        assert label == _hand_label(table[i][1]), (path, label, table[i][1])
    by = {p: lab for p, lab in titles.values()}
    assert by["F01_counts.klarf"] == "없음"                           # '' (see test A) -> 없음, not '-'
    assert ", " in by["mixed.klarf"] and "," not in by["mixed.klarf"].replace(", ", "")
    for s in ("S_A", "S_B", "S_C"):                                  # identical 3 o'clock clusters on TOOL_A
        assert by[f"loc_{s}.klarf"].split(", ")[-1] == "equip_local"
    assert table[next(i for i, v in table.items() if v[0] == "broken.klarf")][1] == "None"
    legend = [c.value for c in at.caption if c.value.startswith("후보 코드: ")]
    assert len(legend) == 1
    for code in (*B.TYPES, *B.EQUIP_TYPES):
        assert f"{code}={B.TYPE_LABELS[code]}" in legend[0]
        assert B.TYPE_LABELS[code] and B.TYPE_LABELS[code] != code
    assert "3장 이상" in legend[0]                                    # min_wafers of the frozen batch config


def test_e_apptest_old_batch_without_settings_renders_per_wafer_codes():
    """E17-BATCH (older batch in the session): config without the new blocks, entries meta without
    equipment/step -> the screen still renders; gallery labels = per-wafer codes; min_wafers shown as '?'."""
    at = _apptest_run(GALLERY_FILES)
    old = copy.deepcopy(at.session_state["batch"])
    for k in ("equipment_signature", "defect_volume"):
        old["config"].pop(k)
    for e in old["entries"]:
        e["meta"].pop("equipment")
        e["meta"].pop("step")
    at.session_state["batch"] = old
    at.run()
    assert not at.exception, at.exception
    df = _unit_table(at)
    assert set(df.loc[df["status"] == "succeeded", "equipment_signature_status"]) == {"not_configured"}
    titles = _gallery_titles(at)
    for i, (path, label) in titles.items():
        assert label == (", ".join(per_wafer_codes(old, i)) or "없음"), path
    legend = next(c.value for c in at.caption if c.value.startswith("후보 코드: "))
    assert "?장 이상" in legend


# ---------------------------------------------------------------- overview type counts (E16-OVERVIEW-TYPECOUNT, C14 C15)
# Approved 2026-10-12 ("Batch 개요에 candidate_types 별 개수, 비율(%) 함께 표시"). Denominator = analysed units
# (status succeeded); a byte-identical duplicate and failed / excluded files are not counted. Codes overlap, so
# the percents may sum above 100. Expected counts come from type_status per unit (oracle of test A), never from
# candidate_type_counts itself; percent = round(100 * c / n, 1).
ALL_CODES = (*B.TYPES, *B.EQUIP_TYPES)


def _expected_counts(batch, extra=None):
    """codes per analysed unit = per-wafer codes from type_status (+ hand-stated batch-level codes)."""
    per = {i: set(per_wafer_codes(batch, i)) | set((extra or {}).get(i, ())) for i in batch["units"]}
    c = {t: sum(t in s for s in per.values()) for t in ALL_CODES}
    c["(none)"] = sum(not s for s in per.values())
    return c


def _check_counts(cc, n, expected):
    assert cc["denominator_units"] == n and cc["reason"] is None
    got = {r["type"]: r for r in cc["rows"]}
    assert [r["type"] for r in cc["rows"]] == [*ALL_CODES, "(none)"]
    for t, c in expected.items():
        assert got[t]["units"] == c, t
        assert got[t]["percent"] == round(100 * c / n, 1), t
    assert got["(none)"]["label"] and all(got[t]["label"] == B.TYPE_LABELS[t] for t in ALL_CODES)


def test_overview_type_counts_dummy13_with_duplicate_and_broken_file(tmp_path):
    items = ([(f"{n}.klarf", (KL / f"{n}.klarf").read_bytes()) for n in MANIFEST]
             + [("copy/F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes()),     # same bytes -> duplicate
                ("broken.klarf", b"not a klarf\n")])
    b = run(items)
    st = {e["rel_path"]: e["status"] for e in b["entries"]}
    assert st["copy/F01_counts.klarf"] == "duplicate_in_batch" and st["broken.klarf"] == "invalid_input"
    assert len(b["units"]) == 13
    exp = _expected_counts(b)
    # no InspectionStationID in the dummy files and defect_volume thresholds null -> no batch-level code
    assert all(exp[t] == 0 for t in B.EQUIP_TYPES)
    # F01_counts and empty have no per-wafer candidate (hand-checked in test A) -> at least 2 in (none)
    assert exp["(none)"] >= 2 and exp["lift_pin"] == 0                    # lift_pin disabled in the profile
    cc = B.candidate_type_counts(B.unit_rows(b))
    _check_counts(cc, 13, exp)


def test_overview_type_counts_with_equipment_repeat_overlap_above_100_percent():
    """Hand-stated: 3 identical 3 o'clock local maps on TOOL_L (local + equip_local each, test_f_local) and
    F01_counts without a tool (no candidate). n = 4: local 3 (75.0), equip_local 3 (75.0), (none) 1 (25.0),
    every other code 0 (0.0) -> sum 175 % > 100 (overlap)."""
    b = run([(f"loc_{s}.klarf", variant("local_3oclock", "TOOL_L", s)) for s in ("L1", "L2", "L3")]
            + [("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())])
    cc = B.candidate_type_counts(B.unit_rows(b))
    hand = {t: 0 for t in ALL_CODES} | {"local": 3, "equip_local": 3, "(none)": 1}
    _check_counts(cc, 4, hand)
    got = {r["type"]: r["percent"] for r in cc["rows"]}
    assert (got["local"], got["equip_local"], got["(none)"], got["ring"]) == (75.0, 75.0, 25.0, 0.0)
    assert sum(got.values()) == 175.0


def test_overview_type_counts_zero_units_are_not_computable():
    b = run([("broken.klarf", b"not a klarf\n"), ("map.png", b"\x89PNG")])
    cc = B.candidate_type_counts(B.unit_rows(b))
    assert cc["denominator_units"] == 0
    assert cc["reason"] == "not computable: no analysed unit (percent denominator 0)"
    assert all(r["units"] == 0 and r["percent"] is None for r in cc["rows"])   # 0 units, percent null (not 0)


def _count_table(at):
    t = [d.value for d in at.dataframe if list(d.value.columns) == ["코드", "유형", "단위 수", "비율(%)"]]
    assert len(t) == 1
    return t[0]


def test_overview_type_counts_apptest_table_and_caption():
    """GALLERY_FILES + a byte-identical copy of F01: units F01, mixed, loc x3 = 5 (duplicate, broken not counted).
    Hand-stated: equip_local 3 (60.0), (none) 1 (F01, 20.0); every other row equals the count over the unit
    table's candidate_types cells of succeeded rows, formatted with one decimal."""
    at = _apptest_run(GALLERY_FILES + [("dup/F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())])
    t = _count_table(at)
    unit = _unit_table(at)
    cells = [set(c for c in v.split(",") if c) for v in unit.loc[unit["status"] == "succeeded", "candidate_types"]]
    assert len(cells) == 5
    rows = {r["코드"]: r for _, r in t.iterrows()}
    assert list(rows) == [*ALL_CODES, "(none)"]
    for code in ALL_CODES:
        c = sum(code in s for s in cells)
        assert int(rows[code]["단위 수"]) == c and rows[code]["비율(%)"] == f"{100 * c / 5:.1f}", code
        assert rows[code]["유형"] == B.TYPE_LABELS[code]
    assert (int(rows["equip_local"]["단위 수"]), rows["equip_local"]["비율(%)"]) == (3, "60.0")
    assert (int(rows["(none)"]["단위 수"]), rows["(none)"]["비율(%)"]) == (1, "20.0")
    cap = [c.value for c in at.caption if c.value.startswith("분모 = 분석 단위")]
    assert len(cap) == 1 and cap[0].startswith("분모 = 분석 단위 5개") and "100%를 넘을 수 있습니다" in cap[0]


def test_overview_type_counts_apptest_zero_units_show_dash_and_reason():
    at = _apptest_run([("broken.klarf", b"not a klarf\n")])
    t = _count_table(at)
    assert set(t["비율(%)"]) == {"-"} and set(int(v) for v in t["단위 수"]) == {0}
    cap = next(c.value for c in at.caption if c.value.startswith("분모 = 분석 단위"))
    assert cap.startswith("분모 = 분석 단위 0개") and "not computable: no analysed unit" in cap


# ---------------------------------------------------------------- D. several axes at once (E06-EQUIP, C11)
def test_d_per_wafer_equipment_and_volume_codes_together(tmp_path):
    """mixed.klarf on 3 wafers of one tool (steps differ), excess_defect_count 100, limit unset.
    Identical coordinates -> every per-wafer ring/line candidate repeats (difference 0); local repeats iff a
    cluster has >= 20 points; 300 >= 100 -> excess_defect (abort not verifiable: no limit)."""
    prof = profile_with(tmp_path, "excess", **{"defect_volume.excess_defect_count": 100})
    b = run([(f"m_{s}.klarf", variant("mixed", "TOOL_M", s)) for s in ("S1", "S2", "S3")], prof)
    for e in b["entries"]:
        i = e["index"]
        pw = per_wafer_codes(b, i)
        det = b["units"][i]["result"]["detect"]
        big = any(c["same_as"] is None and len(c["ids"]) >= 20 for c in det["clusters"].values())
        equip = [f"equip_{t}" for t in ("ring", "line") if t in pw] + (["equip_local"] if big else [])
        row = rows_by_path(b)[e["rel_path"]]
        assert split(row["candidate_types"]) == pw + equip + ["excess_defect"], e["rel_path"]
        assert len(pw) >= 2 and len(equip) >= 2, "mixed fixture no longer exercises several axes"
        assert row["defect_volume_status"] == "excess_abort_unconfirmed"
        assert "inspection_defect_limit not set" in row["defect_volume_reason"]
        detail = json.loads(row["equipment_signature_detail"])
        assert all(detail[t]["steps"] == ["S1", "S2", "S3"] for t in ("ring", "line") if t in pw)


# ---------------------------------------------------------------- E. missing / older data (E17-BATCH, C15)
def test_e_old_batch_dict_and_not_analysed_rows():
    b = run([(f"ring_{s}.klarf", variant("ring", "TOOL_A", s)) for s in ("S_A", "S_B", "S_C")]
            + [("broken.klarf", b"not a klarf\n"), ("map.png", b"\x89PNG")])
    old = copy.deepcopy(b)
    for k in ("equipment_signature", "defect_volume"):
        old["config"].pop(k)
    for e in old["entries"]:
        e["meta"].pop("equipment")
        e["meta"].pop("step")
    bc = B.batch_candidates(old)
    for i, v in bc.items():
        assert (v["equipment_status"], v["defect_volume_status"]) == ("not_configured", "not_configured")
        assert v["codes"] == [] and v["equipment_id"] is None and v["step_id"] is None
    rows = rows_by_path(old)
    for e in old["entries"]:
        row = rows[e["rel_path"]]
        why = json.loads(row["null_reasons"])
        if e["index"] in old["units"]:
            assert row["candidate_types"] == ",".join(per_wafer_codes(old, e["index"]))
            assert row["equipment_signature_reason"] == "no equipment_signature settings in this batch"
            assert row["defect_volume_reason"] == "no defect_volume settings in this batch"
            assert why["equipment_id"] == "not available: no InspectionStationID in the KLARF header"
            assert why["step_id"] == "not available: no StepID in the KLARF header"
        else:
            assert row["candidate_types"] is None and why["candidate_types"] == "not applicable: not analysed"
            assert why["metrics"].startswith("not applicable: not analysed")
            assert not EQUIP_COLS & set(row)
    # every export channel still works on the old dict
    B.summary_csv(old), B.type_csv(old), B.overview(old), B.export_zip(old)
    # the fresh batch, by contrast, carries the settings frozen from the profile
    assert b["config"]["equipment_signature"]["min_wafers"] == 3 and b["config"]["defect_volume"] == \
        {"excess_defect_count": None, "inspection_defect_limit": None}


# ---------------------------------------------------------------- F. grouping and position match (E06-EQUIP / E17-BATCH)
def test_f_equipment_grouping_steps_tools_notch_and_far_positions():
    items = (
        [(f"A/ring_{s}.klarf", variant("ring", "TOOL_A", s)) for s in ("S_A", "S_B")]
        # same tool, written with other spacing: normalised to the same id
        + [("A/ring_S_C.klarf", variant("ring", step="S_C", station_text='{"KLA" ,  "M1","TOOL_A"}'))]
        + [("A/ring_nonotch.klarf", variant("ring", "TOOL_A", "S_N", notch=None)),
           ("A/edge_ring.klarf", variant("edge_ring", "TOOL_A", "S_E"))]
        + [(f"B/ring_{s}.klarf", variant("ring", "TOOL_B", s)) for s in ("X1", "X2")]
        + [("C/ring_nostation.klarf", variant("ring", step="X3"))]
        + [(f"L/loc_{s}.klarf", variant("local_3oclock", "TOOL_L", s)) for s in ("L1", "L2")]
        + [("L/loc_up.klarf", variant("local_3oclock", "TOOL_L", "L3", notch="UP"))]
        + [(f"K/line_{s}.klarf", variant("line", "TOOL_K", s)) for s in ("K1", "K2")]
        + [("K/line_left.klarf", variant("line", "TOOL_K", "K3", notch="LEFT"))])
    b = run(items)
    assert all(e["status"] == "succeeded" for e in b["entries"])
    idx = {e["rel_path"]: e["index"] for e in b["entries"]}
    meta = {e["rel_path"]: e["meta"] for e in b["entries"]}
    rows = rows_by_path(b)
    det = {p: json.loads(r["equipment_signature_detail"]) for p, r in rows.items()}
    codes = {p: split(r["candidate_types"]) for p, r in rows.items()}

    # header meta: tool normalised (quotes dropped, whitespace collapsed), StepID kept
    assert meta["A/ring_S_C.klarf"]["equipment"] == meta["A/ring_S_A.klarf"]["equipment"] == "KLA M1 TOOL_A"
    assert meta["A/ring_S_A.klarf"]["step"] == "S_A" and meta["C/ring_nostation.klarf"]["equipment"] is None

    # TOOL_A: identical ring on 3 steps + the same ring without notch (ring radius is rotation invariant)
    ring_a = ["A/ring_S_A.klarf", "A/ring_S_B.klarf", "A/ring_S_C.klarf", "A/ring_nonotch.klarf"]
    for p in ring_a:
        assert "ring" in per_wafer_codes(b, idx[p]), p
        assert "equip_ring" in codes[p] and rows[p]["equipment_signature_status"] == "computed", p
        # pairwise rule (decision 2026-10-12) + maximal extension: the 4 rings are identical (all pairs match,
        # the edge ring matches none), so every row lists the same 4 peers and all 4 steps
        d = det[p]["ring"]
        assert d == {"repeat": True, "peers": sorted(idx[q] for q in ring_a), "n": 4,
                     "peers_rule": "all pairs match", "steps": ["S_A", "S_B", "S_C", "S_N"]}, p
    for t in ("line", "local"):
        assert det["A/ring_nonotch.klarf"][t] == {
            "repeat": False, "reason": "not comparable: orientation_unknown (positions are not in the notch-down frame)"}
        assert f"equip_{t}" not in codes["A/ring_nonotch.klarf"]
    # edge ring (r ~148) never joins the r ~80 rings, although on the same tool
    assert det["A/edge_ring.klarf"]["ring"]["peers"] == [idx["A/edge_ring.klarf"]]
    assert "equip_ring" not in codes["A/edge_ring.klarf"]
    assert idx["A/edge_ring.klarf"] not in det["A/ring_S_A.klarf"]["ring"]["peers"]

    # TOOL_B: identical rings but only 2 wafers -> insufficient_data, never borrowing TOOL_A wafers
    for p in ("B/ring_X1.klarf", "B/ring_X2.klarf"):
        assert rows[p]["equipment_signature_status"] == "insufficient_data"
        assert rows[p]["equipment_signature_reason"] == "2 wafer(s) on this equipment in the batch (< min_wafers 3)"
        assert not [c for c in codes[p] if c.startswith("equip_")] and det[p] == {}
        assert idx[p] not in det["A/ring_S_A.klarf"]["ring"]["peers"]
    # no InspectionStationID: insufficient_data with the reason, per-wafer codes kept
    p = "C/ring_nostation.klarf"
    assert rows[p]["equipment_signature_status"] == "insufficient_data" and rows[p]["equipment_id"] is None
    assert rows[p]["equipment_signature_reason"] == "no InspectionStationID in the KLARF header (equipment unknown)"
    assert codes[p] == per_wafer_codes(b, idx[p])

    # TOOL_L: two clusters at 3 o'clock + the same raw points declared notch UP (cluster at 9 o'clock): 2 < 3
    for p in ("L/loc_L1.klarf", "L/loc_L2.klarf", "L/loc_up.klarf"):
        assert "local" in per_wafer_codes(b, idx[p])
        assert "equip_local" not in codes[p] and rows[p]["equipment_signature_status"] == "computed"
        assert rows[p]["equipment_signature_reason"] == "no repeat on 3 wafers of this equipment (min_wafers 3)"
    assert det["L/loc_L1.klarf"]["local"]["peers"] == sorted([idx["L/loc_L1.klarf"], idx["L/loc_L2.klarf"]])
    assert det["L/loc_up.klarf"]["local"]["peers"] == [idx["L/loc_up.klarf"]]

    # TOOL_K: horizontal line on 2 wafers + the same raw line declared LEFT (vertical): no equip_line
    for p in ("K/line_K1.klarf", "K/line_K2.klarf", "K/line_left.klarf"):
        assert "line" in per_wafer_codes(b, idx[p]) and "equip_line" not in codes[p]
    assert idx["K/line_left.klarf"] not in det["K/line_K1.klarf"]["line"]["peers"]
    assert abs(rows["K/line_left.klarf"]["line_direction_deg"] % 180 - rows["K/line_K1.klarf"]["line_direction_deg"]
               % 180) == pytest.approx(90, abs=1)                     # rotation stated in the fixture README


def test_f_local_repeat_across_three_steps_lists_the_steps():
    b = run([(f"loc_{s}.klarf", variant("local_3oclock", "TOOL_L", s)) for s in ("L1", "L2", "L3")])
    rows = rows_by_path(b)
    all_idx = sorted(e["index"] for e in b["entries"])
    for r in rows.values():
        assert split(r["candidate_types"])[-1] == "equip_local"
        d = json.loads(r["equipment_signature_detail"])["local"]
        assert d == {"repeat": True, "peers": all_idx, "n": 3, "peers_rule": "all pairs match",
                     "steps": ["L1", "L2", "L3"]}
        assert r["equipment_signature_reason"] is None and r["step_id"] in ("L1", "L2", "L3")


# ---------------------------------------------------------------- F2. pairwise rule (E06-EQUIP-PAIRWISE, C14)
# Decision 2026-10-12 (spec "features match pairwise"): a wafer repeats only inside a set of >= min_wafers
# wafers of the same tool whose features ALL match pairwise. Hand expectations, ring tol 5 mm, min_wafers 3:
#   80/84/88: 80-84 = 4 ok, 84-88 = 4 ok, 80-88 = 8 > 5  -> no 3-set: nobody repeats (a star around 84 is not enough)
#   80/84/86/88: {84, 86, 88} max diff 4 -> those three repeat with identical peers; 80 (80-86 = 6) does not
ES = {"enabled": True, "equipment_field": "InspectionStationID", "min_wafers": 3, "ring_radius_tol_mm": 5,
      "line_angle_tol_deg": 10, "line_offset_tol_mm": 10, "local_distance_tol_mm": 15, "local_min_points": 20}


def _ring_batch(radii):
    """Constructed batch dict: one ring measurement per unit, no line/local, one tool (orientation unknown, so
    line/local are not compared). Index = position in `radii`."""
    def unit(r):
        return {"_points": [], "result": {
            "n_parsed": 50, "n_included": 50, "orientation_status": "orientation_unknown",
            "detect": {"ring": {"feature_status": "candidate", "measurement": {"center_radius_mm": r}},
                       "line": {"feature_status": "no_match"}, "clusters": {}},
            "lift_pin": {"feature_status": "disabled"}}}
    return {"config": {"equipment_signature": dict(ES),
                       "defect_volume": {"excess_defect_count": None, "inspection_defect_limit": None}},
            "entries": [{"index": i, "meta": {"equipment": "T", "step": f"S{i}"}} for i in range(len(radii))],
            "units": {i: unit(r) for i, r in enumerate(radii)}}


@pytest.mark.parametrize("radii,repeat", [
    ([80, 84, 88], set()),
    ([88, 80, 84], set()),                                  # order does not matter
    ([80, 84, 86, 88], {84, 86, 88}),
    ([88, 86, 84, 80], {84, 86, 88}),
    ([84, 80, 88, 86], {84, 86, 88}),
    ([80, 80, 80], {80}),                                   # identical: all repeat
])
def test_f2_pairwise_rule_on_constructed_ring_radii(radii, repeat):
    bc = B.batch_candidates(_ring_batch(radii))
    rep_idx = sorted(i for i, r in enumerate(radii) if r in repeat)
    for i, r in enumerate(radii):
        d = bc[i]["equipment_detail"]["ring"]
        if r in repeat:
            assert bc[i]["codes"] == ["equip_ring"] and d["repeat"] is True, (radii, r)
            assert d["peers"] == rep_idx and d["peers_rule"] == "all pairs match" and d["n"] == len(rep_idx)
            assert d["steps"] == sorted(f"S{j}" for j in rep_idx)
        else:
            assert bc[i]["codes"] == [] and d["repeat"] is False, (radii, r)
            assert d["peers_rule"] == "matching neighbours (not all pairs)"
            # unit + neighbours within 5 mm, stated by hand from the radii
            assert d["peers"] == sorted(j for j, q in enumerate(radii) if abs(q - r) <= 5)
            assert bc[i]["equipment_status"] == "computed" and bc[i]["equipment_reason"].startswith("no repeat")
    for i in range(len(radii)):                             # never a repeat flag whose peers do not repeat too
        d = bc[i]["equipment_detail"]["ring"]
        if d["repeat"]:
            assert all(bc[j]["equipment_detail"]["ring"]["repeat"] for j in d["peers"])


def _scaled_ring(k, step):
    """ring.klarf (r ~80 mm) with every raw wafer coordinate multiplied by k about the wafer center (synthetic
    adapter: raw = INDEX * 10000 + REL - 150000 um, README), re-split into die index / die-relative um."""
    out = []
    for line in (KL / "ring.klarf").read_text(encoding="utf-8").splitlines(keepends=True):
        f = line.split()
        if len(f) == 15 and f[-1] == ";":
            xy = [(int(f[3 + a]) * 10000 + float(f[1 + a]) - 150000) * k + 150000 for a in (0, 1)]
            idx = [math.floor(v / 10000) for v in xy]
            f[1], f[2] = (f"{xy[a] - idx[a] * 10000:.3f}" for a in (0, 1))
            f[3], f[4] = str(idx[0]), str(idx[1])
            line = line[:len(line) - len(line.lstrip())] + " ".join(f) + "\n"
        out.append(line)
    t = "".join(out)
    assert STEP_LINE in t
    return t.replace(STEP_LINE, f'   Field StepID 1 {{"{step}"}}\n   Field InspectionStationID 3 {{"KLA", "M1", "T"}}\n',
                     1).encode("utf-8")


@pytest.mark.parametrize("scales,repeat", [
    ((1.0, 1.05, 1.10), set()),                    # r ~80 / 84 / 88
    ((1.0, 1.05, 1.075, 1.10), {1.05, 1.075, 1.10}),  # r ~80 / 84 / 86 / 88
])
def test_f2_pairwise_rule_through_real_batch_runs_of_scaled_rings(scales, repeat):
    """Same hand expectations as above, through scan/run_batch. The measured radius must follow the scale
    (80 k within 0.5 mm) so the 4 / 6 / 8 mm gaps stay clear of the 5 mm tolerance."""
    b = run([(f"r{k}.klarf", _scaled_ring(k, f"S{k}")) for k in scales])
    rows = {r["rel_path"]: r for r in B.unit_rows(b)}
    rep_idx = sorted(e["index"] for e in b["entries"] if float(e["rel_path"][1:-6]) in repeat)
    for k in scales:
        r = rows[f"r{k}.klarf"]
        assert r["ring_status"] in CAND and r["ring_radius_mm"] == pytest.approx(80 * k, abs=0.5), k
        d = json.loads(r["equipment_signature_detail"])["ring"]
        assert (d["repeat"], "equip_ring" in split(r["candidate_types"])) == (k in repeat,) * 2, k
        if k in repeat:
            assert d["peers"] == rep_idx and d["peers_rule"] == "all pairs match"
            assert d["steps"] == sorted(f"S{q}" for q in repeat)


# ---------------------------------------------------------------- G. defect volume (E13-VOLUME, C17)
VOL_FILES = ("F01_counts", "ring", "mixed", "empty")      # n_parsed 8 / 240 / 300 / 0 (manifest)


@pytest.mark.parametrize("excess,limit,expect", [
    # n >= limit -> abort_suspect (limit inclusive); excess alone -> excess_abort_unconfirmed
    (100, 300, {"F01_counts": ("not_excess", None), "ring": ("excess_abort_unconfirmed", "excess_defect"),
                "mixed": ("abort_suspect", "inspection_abort_suspect"), "empty": ("not_excess", None)}),
    (100, None, {"F01_counts": ("not_excess", None), "ring": ("excess_abort_unconfirmed", "excess_defect"),
                 "mixed": ("excess_abort_unconfirmed", "excess_defect"), "empty": ("not_excess", None)}),
    (None, 240, {"F01_counts": ("below_limit", None), "ring": ("abort_suspect", "inspection_abort_suspect"),
                 "mixed": ("abort_suspect", "inspection_abort_suspect"), "empty": ("below_limit", None)}),
    (None, None, {n: ("disabled", None) for n in VOL_FILES}),
])
def test_g_defect_volume_statuses_and_codes(tmp_path, excess, limit, expect):
    assert {n: MANIFEST[n]["count"] for n in VOL_FILES} == {"F01_counts": 8, "ring": 240, "mixed": 300, "empty": 0}
    prof = profile_with(tmp_path, "vol", **{"defect_volume.excess_defect_count": excess,
                                            "defect_volume.inspection_defect_limit": limit})
    b = run([(f"{n}.klarf", (KL / f"{n}.klarf").read_bytes()) for n in VOL_FILES], prof)
    assert b["config"]["defect_volume"] == {"excess_defect_count": excess, "inspection_defect_limit": limit}
    rows = rows_by_path(b)
    for n, (status, code) in expect.items():
        r = rows[f"{n}.klarf"]
        e = next(x for x in b["entries"] if x["rel_path"] == f"{n}.klarf")
        assert b["units"][e["index"]]["result"]["n_parsed"] == MANIFEST[n]["count"]
        assert r["defect_volume_status"] == status, n
        assert r["defect_volume_reason"], n
        assert split(r["candidate_types"]) == per_wafer_codes(b, e["index"]) + ([code] if code else []), n
        if limit is None:
            assert "inspection_abort_suspect" not in split(r["candidate_types"])   # excess never implies abort


def test_g_defect_volume_from_an_edited_frozen_config_only():
    """Settings come from the frozen batch config: editing a copy of the config changes the evaluation, the
    live profile file does not (it is not read again)."""
    b = run([("ring.klarf", (KL / "ring.klarf").read_bytes())])
    c = copy.deepcopy(b)
    c["config"]["defect_volume"] = {"excess_defect_count": 240, "inspection_defect_limit": None}
    v = next(iter(B.batch_candidates(c).values()))
    assert (v["defect_volume_status"], v["codes"]) == ("excess_abort_unconfirmed", ["excess_defect"])
    v = next(iter(B.batch_candidates(b).values()))
    assert (v["defect_volume_status"], v["codes"]) == ("disabled", [])


# ---------------------------------------------------------------- H. profile validation (E12-EQUIP-CONFIG)
def _dummy_dict():
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("block,changes,key", [
    ("equipment_signature", {"ring_radius_tol_mm": None}, "equipment_signature.ring_radius_tol_mm"),
    ("equipment_signature", {"local_min_points": None}, "equipment_signature.local_min_points"),
    ("equipment_signature", {"line_offset_tol_mm": 0}, "equipment_signature.line_offset_tol_mm"),
    ("equipment_signature", {"min_wafers": 1}, "equipment_signature.min_wafers"),
    ("equipment_signature", {"line_angle_tol_deg": 90}, "equipment_signature.line_angle_tol_deg"),
    ("defect_volume", {"excess_defect_count": 500, "inspection_defect_limit": 300}, "defect_volume.excess_defect_count"),
    ("defect_volume", {"inspection_defect_limit": 0}, "defect_volume.inspection_defect_limit"),
])
def test_h_invalid_settings_are_config_invalid_with_the_key(block, changes, key):
    d = _dummy_dict()
    d[block].update(changes)
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.code == "CONFIG_INVALID" and e.value.keys == [key]


def test_h_equipment_field_is_fixed_and_disabled_nulls_are_valid(tmp_path):
    d = _dummy_dict()
    d["equipment_signature"]["equipment_field"] = "StepID"          # grouping is the inspection tool only
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["equipment_signature.equipment_field"]

    d = _dummy_dict()
    d["equipment_signature"] = {"enabled": False, "ring_radius_tol_mm": None, "line_angle_tol_deg": None,
                                "line_offset_tol_mm": None, "local_distance_tol_mm": None, "local_min_points": None}
    d["defect_volume"] = {"excess_defect_count": None, "inspection_defect_limit": None}
    validate_for_run(parse_profile(d))
    d2 = _dummy_dict()
    d2.pop("equipment_signature"), d2.pop("defect_volume")          # blocks absent -> defaults: disabled / null
    p = parse_profile(d2)
    assert p.equipment_signature.enabled is False and p.equipment_signature.min_wafers == 3
    assert (p.defect_volume.excess_defect_count, p.defect_volume.inspection_defect_limit) == (None, None)
    d3 = _dummy_dict()
    d3["defect_volume"] = {"excess_defect_count": 300, "inspection_defect_limit": 300}   # equal is allowed
    parse_profile(d3)

    # the batch refuses an invalid profile before any analysis
    bad = profile_with(tmp_path, "bad", **{"equipment_signature.ring_radius_tol_mm": None})
    with pytest.raises(ConfigInvalid) as e:
        B.scan([("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes())], str(bad))
    assert e.value.keys == ["equipment_signature.ring_radius_tol_mm"]
