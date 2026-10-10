"""E16 (partial) / E19 UI path: the Streamlit screen shows the same core values as the CLI JSON, display
filters do not change counts, and reviews are stored as revisions. Headless AppTest - not a browser E2E.
"""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from wafer.cli import main

HERE = Path(__file__).parent
APP = str(HERE.parent / "wafer" / "app.py")
KLF = str(HERE / "fixtures/klarf/f01.klf")
PROFILE = str(HERE / "profiles/f01_test_profile.yaml")


def test_default_profile_and_single_file_reload(tmp_path):
    """E12-DEFAULT: default serves dummy input; path content is reread for every run."""
    from wafer.ui_inputs import DEFAULT_PROFILE
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.radio
    assert at.text_input(key="batch_profile_path").value == DEFAULT_PROFILE
    at.text_area(key="batch_paths").set_value(str(HERE.parent / "klarf_dummy_data/klarf/F01_counts.klarf"))
    analyse_and_open(at)
    assert metrics(at)["included"] == "8"
    profile = tmp_path / "profile.yaml"
    profile.write_bytes(Path(DEFAULT_PROFILE).read_bytes())
    at.button(key="back_to_batch").click().run()
    at.text_input(key="batch_profile_path").set_value(str(profile))
    analyse_and_open(at)
    before = at.session_state["job"]["out"]["result"]["provenance"]["profile_sha256"]
    profile.write_text(profile.read_text().replace("dummy_die_local_test_only", "updated_profile"), encoding="utf-8")
    at.button(key="back_to_batch").click().run()
    analyse_and_open(at)
    assert not at.exception
    provenance = at.session_state["job"]["out"]["result"]["provenance"]
    assert provenance["profile_id"] == "updated_profile"
    assert provenance["profile_sha256"] != before
    at.button(key="back_to_batch").click().run()
    assert metrics(at)["포함 결함 합"] == "8"
    assert len(at.multiselect(key="batch_selected").value) == 1


def test_profile_path_default_is_explicit_and_restored_when_cleared():
    """E12-DEFAULT: the widget itself has a default; blank sessions/edits restore it."""
    from wafer.ui_inputs import DEFAULT_PROFILE
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["batch_profile_path"] = "   "
    at.run()
    assert at.text_input(key="batch_profile_path").value == DEFAULT_PROFILE
    assert at.text_input(key="batch_profile_path").proto.default == DEFAULT_PROFILE
    at.text_input(key="batch_profile_path").set_value(PROFILE).run()
    at.run()
    assert at.text_input(key="batch_profile_path").value == PROFILE
    at.text_input(key="batch_profile_path").set_value("").run()
    assert not at.exception
    assert at.text_input(key="batch_profile_path").value == DEFAULT_PROFILE


def analyse_and_open(at):
    at.button(key="batch_scan_btn").click().run()
    at.button(key="batch_run_btn").click().run()
    at.button(key="batch_open").click().run()
    assert not at.exception, at.exception


def run_app(db="", klarf=KLF):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.text_area(key="batch_paths").set_value(klarf)
    at.text_input(key="batch_profile_path").set_value(PROFILE)
    at.text_input(key="batch_db_path").set_value(db)
    analyse_and_open(at)
    assert not at.exception, at.exception
    return at


def metrics(at):
    return {m.label: m.value for m in at.metric}


def test_ui_values_match_cli_json(tmp_path):
    out = tmp_path / "o.json"
    assert main([KLF, "--profile", PROFILE, "--out", str(out)]) == 0
    r = json.loads(out.read_text(encoding="utf-8"))["result"]
    at = run_app()
    m = metrics(at)
    assert m["job_status"] == "succeeded"
    assert (m["parsed"], m["included"], m["excluded"], m["center"]) == tuple(
        str(r[k]) for k in ("n_parsed", "n_included", "n_excluded", "center"))
    table = at.dataframe[0].value                      # bin x clock
    assert {b: int(table.loc[b, "total"]) for b in table.index} == r["bin_totals"]
    for b in table.index:
        assert {int(h): int(table.loc[b, h]) for h in table.columns if str(h).isdigit()} == \
            {int(h): v for h, v in r["bin_sector"][b].items() if h != "center"}


def test_bin_filter_changes_display_only():
    at = run_app()
    before = metrics(at)
    # E16-UP (T-04, 2026-10-09): bin label "B1" -> "1" (CLASSNUMBER as text); F01 still has 3 events of bin 1
    at.multiselect(key="bin_filter").set_value(["1"])
    at.run()
    after = metrics(at)
    assert before == after                              # counts are not overwritten by the display filter
    assert any("표시 중 3 / 포함 8" in c.value for c in at.caption)   # F01: 3 bin-1 events shown


def test_failed_job_is_shown_as_failed():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.text_area(key="batch_paths").set_value(str(HERE / "fixtures/klarf/bad_number.klf"))
    at.text_input(key="batch_profile_path").set_value(PROFILE)
    at.button(key="batch_scan_btn").click().run()
    at.button(key="batch_run_btn").click().run()
    assert metrics(at)["실패"] == "1"
    assert at.dataframe[0].value.iloc[0]["상태"] == "invalid_input"
    assert not any(b.key == "batch_open" for b in at.button)


def test_review_is_saved_as_a_revision(tmp_path):
    db = str(tmp_path / "w.db")
    at = run_app(db)
    assert any("review_status: **unreviewed**" in md.value for md in at.markdown)
    at.selectbox(key="rv_action").set_value("defer")
    at.text_area(key="rv_payload").set_value('{"reason_code": "needs_sem_review"}')
    at.button(key="rv_submit").click()
    at.run()
    assert any("revision 1" in x.value for x in at.success)
    from wafer import store
    con = store.connect(db)
    key = con.execute("SELECT analysis_key FROM runs").fetchone()[0]
    assert [r["action"] for r in store.reviews(con, key)] == ["defer"]
    assert store.review_status(con, key) == "deferred"
    con.close()


def test_ui_shows_the_independent_f01_values():
    """Plan 19.2 oracle, asserted directly (not via the CLI): included 8, B1/B2/B3 = 3/3/2, center 1,
    12h 1 / 3h 4 / 6h 1 / 9h 1."""
    at = run_app()
    m = metrics(at)
    assert (m["included"], m["excluded"], m["center"]) == ("8", "0", "1")
    t = at.dataframe[0].value
    # E16-UP (T-04, 2026-10-09): was {"B1": 3, "B2": 3, "B3": 2}; oracle "Bn" = CLASSNUMBER n -> key "n"
    assert {b: int(t.loc[b, "total"]) for b in t.index} == {"1": 3, "2": 3, "3": 2}
    col = {h: int(t[h].sum()) for h in ("12", "3", "6", "9")}
    assert col == {"12": 1, "3": 4, "6": 1, "9": 1}
    assert any("source_sha256" in c.value and "schema" in c.value for c in at.caption)


def test_failed_job_shows_no_counts_and_no_stale_result():
    at = run_app()                                     # a successful run first
    at.button(key="back_to_batch").click().run()
    at.text_area(key="batch_paths").set_value(str(HERE / "fixtures/klarf/bad_number.klf"))
    at.button(key="batch_scan_btn").click().run()
    at.button(key="batch_run_btn").click().run()
    m = metrics(at)
    assert m["실패"] == "1" and "included" not in m    # previous success not shown
    at.text_area(key="batch_paths").set_value("")
    at.button(key="batch_scan_btn").click().run()
    assert not at.metric and any("지정하세요" in e.value for e in at.error)


def test_review_payload_must_be_an_object(tmp_path):
    at = run_app(str(tmp_path / "w.db"))
    at.selectbox(key="rv_action").set_value("defer")
    at.text_area(key="rv_payload").set_value("[]")
    at.button(key="rv_submit").click()
    at.run()
    assert not at.exception and any("검토 거부" in e.value for e in at.error)


def test_e10_up_ui_says_screen_direction_is_not_physical_when_notch_is_unknown(tmp_path):
    src = (HERE / "fixtures/klarf/f01.klf").read_text(encoding="utf-8")
    assert "OrientationMarkLocation DOWN;\n" in src
    p = tmp_path / "nonotch.klf"
    p.write_text(src.replace("OrientationMarkLocation DOWN;\n", "", 1), encoding="utf-8")
    at = run_app(klarf=str(p))
    assert not at.exception
    assert metrics(at)["included"] == "8"
    assert any("노치 위치 미상" in c.value for c in at.caption)
    assert any("orientation_unknown" in w.value for w in at.warning)
