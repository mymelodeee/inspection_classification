"""Gallery pager, detail-screen candidate_types and candidate-type map colouring (approved user request
2026-10-12). Headless Streamlit AppTest - not a browser E2E.

Sub-cases (docs/3_user_scenarios.md 2.3): E16-GALLERY-PAGER, E16-DETAIL-TYPES, E16-MAP-TYPECOLOR; C14 (same
value on every channel), C11 (overlaps kept, not merged), E16 (display filters never change counts).

Oracles (hand-stated, never the function under test):
  * pager windows for 20 pages / window 9 worked out by hand from "at most 9 numbers around the current page";
  * gallery page size 12 (batch_ui.GALLERY_PAGE) -> 13 units = 2 pages, page 2 holds unit #12 only;
  * detail candidate_types text = the unit-table cell of the opened index, formatted by hand (', ' join,
    '' -> 없음, missing -> -) with the Korean labels written out here;
  * point membership recomputed in this file from the result's STORED supports (detect.shape_supports,
    detect.signature_groups local_*; lift_pin disabled in the dummy profile); counts from
    klarf_dummy_data/manifest.json (mixed: 300 = bin 1 120 / bin 2 120 / bin 3 60).
SYNTHETIC inputs only (klarf_dummy_data, seed 20261009); TEST-ONLY profile.
"""
import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from wafer import batch as B
from wafer import batch_ui

ROOT = Path(__file__).resolve().parent.parent
DD = ROOT / "klarf_dummy_data"
KL = DD / "klarf"
PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"
MANIFEST = {c["name"]: c for c in json.loads((DD / "manifest.json").read_text(encoding="utf-8"))["cases"]}
STEP_LINE = '   Field StepID 1 {"DUMMY_INSPECTION"}\n'
PAGER_KEYS = ("first", "prev", "next", "last")


def tool_variant(name, tool, step):
    t = (KL / f"{name}.klarf").read_text(encoding="utf-8")
    assert STEP_LINE in t
    return t.replace(STEP_LINE, f'   Field StepID 1 {{"{step}"}}\n   Field InspectionStationID 3 {{"KLA", "M1", "{tool}"}}\n',
                     1).encode("utf-8")


def run_batch_app(files):
    at = AppTest.from_file(str(ROOT / "wafer/app.py"), default_timeout=180)
    at.run()
    at.file_uploader(key="batch_files").set_value([(n, d, "application/octet-stream") for n, d in files])
    at.text_input(key="batch_profile_path").set_value(str(PROFILE))
    at.button(key="batch_scan_btn").click().run()
    assert not at.exception, at.exception
    at.button(key="batch_run_btn").click().run()
    assert not at.exception, at.exception
    return at


def thumb_indices(at):
    """Unit indices of the gallery thumbnails (sorted: the 3-column grid is walked column by column)."""
    return sorted(int(json.loads(c.proto.spec)["layout"]["title"]["text"].split(" ", 1)[0][1:]) for c in at.get("plotly_chart"))


def page_caption(at):
    cap = [c.value for c in at.caption if c.value.startswith("페이지 ")]
    assert len(cap) == 1
    return cap[0]


def number_buttons(at, key="gallery_page"):
    pat = re.compile(rf"^{key}_n(\d+)$")
    return sorted(int(m.group(1)) for b in at.button if b.key and (m := pat.match(b.key)))


# ---------------------------------------------------------------- pager unit (tiny script)
def _pager_script():
    import streamlit as st
    from wafer.batch_ui import _pager
    st.write(f"cur={_pager(st.session_state.get('pages_total', 20))}")


def _pager_app(pages):
    at = AppTest.from_function(_pager_script, default_timeout=30)
    at.session_state["pages_total"] = pages
    at.run()
    assert not at.exception, at.exception
    return at


def _state(at):
    btn = {b.key: b for b in at.button}
    cur = int(next(m.value for m in at.markdown if m.value.startswith("cur=")).split("=")[1])
    return cur, number_buttons(at), {k: btn[f"gallery_page_{k}"].disabled for k in PAGER_KEYS}, btn


def test_pager_labels_keys_window_disabled_states_and_moves():
    at = _pager_app(20)
    cur, nums, dis, btn = _state(at)
    labels = {f"gallery_page_{k}": lab for k, lab in zip(PAGER_KEYS, ("<<", "<", ">", ">>"))}
    assert {k: btn[k].label for k in labels} == labels
    assert all(btn[f"gallery_page_n{n}"].label == str(n) for n in nums)
    # page 1 of 20: numbers 1..9, << and < disabled, current page primary + disabled
    assert (cur, nums, dis) == (1, list(range(1, 10)), {"first": True, "prev": True, "next": False, "last": False})
    assert btn["gallery_page_n1"].disabled and btn["gallery_page_n1"].proto.type == "primary"
    assert not btn["gallery_page_n2"].disabled and btn["gallery_page_n2"].proto.type == "secondary"
    assert page_caption(at) == "페이지 1 / 20"

    at.button(key="gallery_page_n9").click().run()          # window centred: 9 - 4 = 5 .. 13
    cur, nums, dis, btn = _state(at)
    assert (cur, nums) == (9, list(range(5, 14))) and not any(dis.values())
    assert btn["gallery_page_n9"].proto.type == "primary" and btn["gallery_page_n9"].disabled
    at.button(key="gallery_page_next").click().run()        # 10: 6 .. 14
    assert _state(at)[:2] == (10, list(range(6, 15)))
    at.button(key="gallery_page_last").click().run()        # 20: last window 12 .. 20, > and >> disabled
    cur, nums, dis, _ = _state(at)
    assert (cur, nums, dis) == (20, list(range(12, 21)), {"first": False, "prev": False, "next": True, "last": True})
    assert page_caption(at) == "페이지 20 / 20"
    at.button(key="gallery_page_prev").click().run()        # 19: still 12 .. 20 (clamped at the end)
    assert _state(at)[:2] == (19, list(range(12, 21)))
    at.button(key="gallery_page_first").click().run()
    assert _state(at)[:2] == (1, list(range(1, 10)))

    # pages shrink below the current page -> clamped to the last page, window fits the smaller range
    at.button(key="gallery_page_last").click().run()
    at.session_state["pages_total"] = 5
    at.run()
    cur, nums, dis, _ = _state(at)
    assert (cur, nums, dis) == (5, [1, 2, 3, 4, 5], {"first": False, "prev": False, "next": True, "last": True})
    assert at.session_state["gallery_page"] == 5 and page_caption(at) == "페이지 5 / 5"


def test_pager_single_page_has_every_arrow_disabled():
    at = _pager_app(1)
    cur, nums, dis, btn = _state(at)
    assert (cur, nums) == (1, [1]) and all(dis.values()) and btn["gallery_page_n1"].disabled


# ---------------------------------------------------------------- pager in the real gallery
def test_gallery_pages_show_the_right_thumbnails_and_clamp():
    """13 dummy units, 12 per page (hand): page 1 = #0..#11, page 2 = #12."""
    names = list(MANIFEST)
    at = run_batch_app([(f"{n}.klarf", (KL / f"{n}.klarf").read_bytes()) for n in names])
    assert batch_ui.GALLERY_PAGE == 12
    assert thumb_indices(at) == list(range(12)) and number_buttons(at) == [1, 2]
    assert page_caption(at) == "페이지 1 / 2"
    at.button(key="gallery_page_n2").click().run()
    assert thumb_indices(at) == [12] and page_caption(at) == "페이지 2 / 2"
    assert at.button(key="gallery_page_next").disabled and at.button(key="gallery_page_last").disabled
    at.button(key="gallery_page_prev").click().run()
    assert thumb_indices(at) == list(range(12))
    at.button(key="gallery_page_last").click().run()
    assert thumb_indices(at) == [12]
    at.session_state["gallery_page"] = 7                     # stale page beyond the range -> clamped to 2
    at.run()
    assert not at.exception and thumb_indices(at) == [12] and at.session_state["gallery_page"] == 2
    # overview counts are not touched by paging
    assert {m.label: m.value for m in at.metric}["분석 단위"] == "13"


# ---------------------------------------------------------------- detail candidate_types (E16-DETAIL-TYPES)
DETAIL_FILES = ([("F01_counts.klarf", (KL / "F01_counts.klarf").read_bytes()),
                 ("mixed.klarf", (KL / "mixed.klarf").read_bytes())]
                + [(f"loc_{s}.klarf", tool_variant("local_3oclock", "TOOL_A", s)) for s in ("S_A", "S_B", "S_C")])
KO = {"ring": "환형", "line": "일자형", "local": "몰림형", "lift_pin": "삼발이", "equip_local": "설비 반복 몰림형",
      "equip_ring": "설비 반복 환형", "equip_line": "설비 반복 일자형"}


def unit_cells(at):
    t = [d.value for d in at.dataframe if {"index", "rel_path", "candidate_types"} <= set(d.value.columns)]
    assert len(t) == 1
    return {p: c for p, c in zip(t[0]["rel_path"], t[0]["candidate_types"])}


def open_detail(at, index):
    at.selectbox(key="batch_pick").set_value(index).run()     # the button's args are bound at render time
    at.button(key="batch_open").click().run()
    assert not at.exception, at.exception


def detail_types_text(at):
    m = [x.value for x in at.markdown if x.value.startswith("**candidate_types:** ")]
    assert len(m) == 1
    return m[0][len("**candidate_types:** "):]


def test_detail_shows_the_unit_table_candidate_types_for_the_opened_index():
    at = run_batch_app(DETAIL_FILES)
    cells = unit_cells(at)
    idx = {e["rel_path"]: e["index"] for e in at.session_state["batch"]["entries"]}
    assert cells["F01_counts.klarf"] == ""                    # hand-checked in test_equipment_candidates test A
    assert cells["loc_S_A.klarf"] == "local,equip_local"      # identical 3 o'clock clusters on one tool
    for path, cell in cells.items():
        open_detail(at, idx[path])
        assert at.session_state["job"]["candidate_types"] == cell and at.session_state["job"]["source"] == path
        codes = [c for c in cell.split(",") if c]
        hand = (", ".join(codes) + " (" + ", ".join(KO[c] for c in codes) + ")") if codes else "없음"
        assert detail_types_text(at) == hand, path
        at.button(key="back_to_batch").click().run()
    open_detail(at, idx["loc_S_B.klarf"])
    assert detail_types_text(at) == "local, equip_local (몰림형, 설비 반복 몰림형)"
    # an older session without the key -> "-"
    job = dict(at.session_state["job"])
    job.pop("candidate_types")
    at.session_state["job"] = job
    at.run()
    assert not at.exception and detail_types_text(at) == "-"


# ---------------------------------------------------------------- candidate-type map colours (E16-MAP-TYPECOLOR)
def detail_traces(at):
    charts = [json.loads(c.proto.spec)["data"] for c in at.get("plotly_chart")]
    charts = [d for d in charts if d and d[0].get("name") == "wafer"]
    assert len(charts) == 1
    return [t for t in charts[0] if t.get("name") not in ("wafer",) and not t["name"].startswith("notch")
            and not t["name"].startswith("group ")]


def hand_membership(res):
    """defect_id -> '+'-joined types in TYPES order from the stored supports (independent of app.support_groups)."""
    det = res["detect"]
    sup = {"ring": set(det["shape_supports"].get("ring", [])), "line": set(det["shape_supports"].get("line", [])),
           "local": {i for k, ids in det["signature_groups"].items() if k.startswith("local_") for i in ids}}
    assert res["lift_pin"]["feature_status"] == "disabled"   # dummy profile: no lift_pin support to add
    return {str(p): "+".join(t for t in ("ring", "line", "local") if p in sup[t]) or "(후보 아님)"
            for p in {i for s in sup.values() for i in s}}


def metric_values(at):
    return {m.label: m.value for m in at.metric if m.label in ("parsed", "included", "excluded", "center")}


def test_candidate_colour_mode_labels_overlaps_counts_and_bin_filter():
    at = run_batch_app(DETAIL_FILES)
    b = at.session_state["batch"]
    i = next(e["index"] for e in b["entries"] if e["rel_path"] == "mixed.klarf")
    res = b["units"][i]["result"]
    included = {str(p["defect_id"]): p["bin"] for p in b["units"][i]["_points"] if p["included"]}
    assert len(included) == MANIFEST["mixed"]["count"] == 300
    open_detail(at, i)
    assert at.radio(key="map_color").value == "bin"
    before = metric_values(at)
    bin_total = sum(len(t["x"]) for t in detail_traces(at))
    assert bin_total == 300

    at.radio(key="map_color").set_value("후보 유형(candidate_types)").run()
    assert not at.exception and metric_values(at) == before       # colour mode never changes counts
    hand = hand_membership(res)
    traces = detail_traces(at)
    seen = {}
    for t in traces:
        labs = {s.split(" · ")[2] for s in t["text"]}
        assert len(labs) == 1, t["name"]                           # one trace per label
        lab = labs.pop()
        assert t["name"].endswith(f"({len(t['x'])})")
        assert ("(겹침)" in t["name"]) == ("+" in lab)
        if "+" in lab:
            assert t["marker"]["symbol"] == "diamond" and t["marker"]["color"] == "#ff7f0e"
        if lab == "(후보 아님)":
            assert t["marker"]["color"] == "#bbbbbb"
        for s in t["text"]:
            did = s.split(" · ")[0]
            assert hand.get(did, "(후보 아님)") == lab, did
            seen[did] = lab
    assert set(seen) == set(included) and sum(len(t["x"]) for t in traces) == 300     # every point once
    labels = set(seen.values())
    assert {"ring+local", "line+local", "ring+line+local"} <= labels                  # overlaps kept (C11)
    assert {lab: sum(v == lab for v in seen.values()) for lab in labels} == \
        {lab: sum(hand.get(d, "(후보 아님)") == lab for d in included) for lab in labels}

    # bin filter still applies in candidate mode: bins 1 and 3 -> 120 + 60 (manifest)
    assert MANIFEST["mixed"]["bin_counts"]["1"] == 120 and MANIFEST["mixed"]["bin_counts"]["3"] == 60
    at.multiselect(key="bin_filter").set_value(["1", "3"]).run()
    traces = detail_traces(at)
    assert sum(len(t["x"]) for t in traces) == 180
    assert {s.split(" · ")[1] for t in traces for s in t["text"]} == {"bin 1", "bin 3"}
    assert any(c.value.startswith("표시 중 180 / 포함 300") for c in at.caption)
    assert metric_values(at) == before
    at.radio(key="map_color").set_value("bin").run()
    assert sum(len(t["x"]) for t in detail_traces(at)) == 180 and metric_values(at) == before

    # equipment repeat marked in the legend; colour mode reset when another detail is opened
    at.radio(key="map_color").set_value("후보 유형(candidate_types)").run()
    at.button(key="back_to_batch").click().run()
    j = next(e["index"] for e in b["entries"] if e["rel_path"] == "loc_S_A.klarf")
    open_detail(at, j)
    assert at.radio(key="map_color").value == "bin"
    at.radio(key="map_color").set_value("후보 유형(candidate_types)").run()
    names = [t["name"] for t in detail_traces(at)]
    assert any(n.startswith("local 몰림형 ·설비 반복") for n in names), names
