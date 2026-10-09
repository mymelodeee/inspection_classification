"""Browser E2E (E16 UI channel, E19 review via UI) - real Streamlit server + real browser (system Edge via
Playwright, no browser download). Synthetic KLARF only; not an equipment-adapter validation.
If no browser can be launched the tests are skipped with the reason (status BLOCKED, not PASS).
"""
import csv
import hashlib
import io
import json
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[1]
K = ROOT / "tests/fixtures/klarf"
PROFILE = ROOT / "tests/profiles/f01_test_profile.yaml"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "wafer/app.py"),
                             "--server.headless", "true", "--server.port", str(port),
                             "--browser.gatherUsageStats", "false"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if urlopen(url + "/_stcore/health", timeout=1).read() == b"ok":
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("streamlit server did not become healthy")
    yield url
    proc.kill()


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    pw = sync_playwright().start()
    try:
        b = pw.chromium.launch(channel="msedge")
    except Exception as e:     # environment, not product: report as BLOCKED
        pw.stop()
        pytest.skip(f"BLOCKED: no browser available for E2E ({type(e).__name__})")
    yield b
    b.close()
    pw.stop()


def _run(page, url, klarf=None, upload=None, db="", coverage=""):
    page.goto(url)
    page.get_by_label("또는 KLARF 경로").wait_for(timeout=60000)
    if upload:
        page.locator("input[type=file]").first.set_input_files(str(upload))
    else:
        page.get_by_label("또는 KLARF 경로").fill(str(klarf))
    page.get_by_label("또는 profile 경로").fill(str(PROFILE))
    if coverage:
        page.get_by_role("textbox", name="coverage sidecar 경로 (선택, 없으면 coverage 미상)").fill(str(coverage))
    page.get_by_label("SQLite 저장 경로 (선택)").fill(db)
    page.get_by_label("SQLite 저장 경로 (선택)").press("Enter")
    page.get_by_role("button", name="분석 실행").click()
    page.get_by_text("job_status").first.wait_for(timeout=60000)


def _select(page, label, option):
    """Pick a value in a Streamlit selectbox. The first click right after a download is swallowed by the
    rerun the download triggers, so the open is retried (test-harness timing, not a product behaviour)."""
    for _ in range(5):
        page.get_by_label(label).click()
        try:
            page.get_by_role("option", name=option).click(timeout=3000)
            return
        except Exception:   # only the open timed out; a real failure still fails below
            time.sleep(1)
    raise AssertionError(f"selectbox {label!r} did not open for option {option!r}")


def _metric(page, label):
    m = page.locator('[data-testid="stMetric"]').filter(has_text=label).first
    return m.locator('[data-testid="stMetricValue"]').inner_text().strip()


def test_e16_browser_values_match_the_f01_oracle(server, browser):
    page = browser.new_page()
    _run(page, server, klarf=K / "f01.klf")
    page.get_by_text("included").first.wait_for(timeout=60000)
    assert _metric(page, "job_status") == "succeeded"
    assert (_metric(page, "parsed"), _metric(page, "included"), _metric(page, "excluded"), _metric(page, "center")) == \
        ("8", "8", "0", "1")
    page.get_by_text("bin × 시계방향").wait_for()
    page.close()


def test_e16_upload_path_gives_the_same_counts(server, browser):
    page = browser.new_page()
    _run(page, server, upload=K / "f01.klf")
    page.get_by_text("included").first.wait_for(timeout=60000)
    assert _metric(page, "included") == "8" and _metric(page, "center") == "1"
    assert page.get_by_text("입력: f01.klf").count() >= 1      # upload name shown, no temp path
    page.close()


def test_e13_bad_file_is_shown_as_failed(server, browser):
    page = browser.new_page()
    _run(page, server, klarf=K / "bad_number.klf")
    assert _metric(page, "job_status") == "failed"
    assert page.get_by_text("INVALID_INPUT").count() >= 1
    assert page.locator('[data-testid="stMetric"]').filter(has_text="included").count() == 0
    page.close()


def test_e19_review_through_the_browser(server, browser, tmp_path):
    db = tmp_path / "w.db"
    page = browser.new_page()
    _run(page, server, klarf=K / "f01.klf", db=str(db))
    page.get_by_text("review_status").first.wait_for(timeout=60000)
    page.get_by_role("textbox", name="payload (JSON)").fill(json.dumps({"reason_code": "needs_sem_review"}))
    _select(page, "action", "defer")
    page.get_by_role("button", name="검토 저장").click()
    page.get_by_text("revision 1 저장").wait_for(timeout=60000)
    page.close()
    from wafer import store
    con = store.connect(db)
    key = con.execute("SELECT analysis_key FROM runs").fetchone()[0]
    assert store.review_status(con, key) == "deferred"
    con.close()


# ---- E16 download contents (added 2026-10-09): the files the browser actually downloads are opened and
# compared against independently derived expectations, not against the screen. Oracle source: plan 19.2
# F01 table + the fixture text itself (XREL/YREL um / 1000 = mm, event key "record:DEFECTID",
# CLASSNUMBER as the bin label per T-04); provenance hashes are recomputed here with hashlib.
F01 = {
    "counts": (8, 8, 0),
    "bin_totals": {"1": 3, "2": 3, "3": 2},
    "center": 1,
    "sectors_clock": {"1": 0, "2": 0, "3": 4, "4": 0, "5": 0, "6": 1,
                      "7": 0, "8": 0, "9": 1, "10": 0, "11": 0, "12": 1},
    # defect_id -> (x_mm, y_mm, r_mm, bin, clock, zones); theta = atan2(x, y): (0,+)=12h, (+,0)=3h
    "defects": {
        "1:1": (0.0, 50.0, 50.0, "1", "12", ["inner"]),
        "2:2": (50.0, 0.0, 50.0, "1", "3", ["inner"]),
        "3:3": (0.0, -50.0, 50.0, "2", "6", ["inner"]),
        "4:4": (-50.0, 0.0, 50.0, "2", "9", ["inner"]),
        "5:5": (0.0, 0.0, 0.0, "1", "center", ["inner"]),      # r < center_exclusion 1 mm
        "6:6": (149.0, 0.0, 149.0, "3", "3", ["E1"]),          # edge distance 1 -> E1 [0,2)
        "7:7": (148.0, 0.0, 148.0, "3", "3", ["E2"]),          # edge distance 2 -> E2 [2,5)
        "8:8": (100.0, 0.0, 100.0, "2", "3", ["band"]),        # r=100: band |r-100|<=1; inner is [0,100)
    },
    # radial bins (profile radial_bin_mm 50, last bin closed at R=150): counts are real, areas are null
    # because coverage is unknown (C08: no area-corrected density without coverage)
    "radial": {"0-50)": 1, "50-100)": 4, "100-150]": 3},
    "bin_sector": {"1": {"3": 1, "12": 1, "center": 1}, "2": {"3": 1, "6": 1, "9": 1},
                   "3": {"3": 2}},        # hours not listed are real 0
}


def _download(page, button_name):
    with page.expect_download(timeout=60000) as info:
        page.get_by_role("button", name=button_name).click()
    return Path(info.value.path()).read_bytes()


def _expect_bin_sector(sparse):
    """Full 12h + center rows from the sparse oracle above (absent hour = real 0, never blank)."""
    return {b: {**{str(h): 0 for h in range(1, 13)}, "center": 0, **row} for b, row in sparse.items()}


def test_e16_downloaded_json_matches_independent_f01_expectations(server, browser):
    page = browser.new_page()
    _run(page, server, klarf=K / "f01.klf")
    page.get_by_text("내보내기").first.wait_for(timeout=60000)
    doc = json.loads(_download(page, "JSON 다운로드").decode("utf-8"))
    assert _metric(page, "included") == "8"       # screen agrees, but both are checked against the oracle
    page.close()

    assert (doc["job_status"], doc["data_quality_status"]) == ("succeeded", "valid")
    assert not [k for k in doc if k.startswith("_")]          # in-process keys are never exported
    r = doc["result"]
    assert (r["n_parsed"], r["n_included"], r["n_excluded"]) == F01["counts"]
    assert r["n_parsed"] == r["n_included"] + r["n_excluded"]
    assert r["bin_totals"] == F01["bin_totals"] and sum(r["bin_totals"].values()) == r["n_included"]
    assert r["center"] == F01["center"]
    assert r["sectors_clock"] == F01["sectors_clock"]
    assert sum(r["sectors_clock"].values()) + r["center"] == r["n_included"]
    assert r["bin_sector"] == _expect_bin_sector(F01["bin_sector"])
    assert r["zone_union_unique"] == 8 and r["excluded"] == []

    # null vs 0 (C15): an empty hour is the integer 0; an uncomputable area/density is null
    assert r["sectors_clock"]["1"] == 0 and r["sectors_clock"]["1"] is not None
    assert r["n_excluded"] == 0 and r["n_multi_sector"] == 0
    assert {"%g-%g%s" % (w["r_lo_mm"], w["r_hi_mm"], "]" if w["closed"] == "both" else ")"): w["count"]
            for w in r["radial_density"]["rows"]} == F01["radial"]
    for w in r["radial_density"]["rows"]:
        assert w["area_mm2"] is None and w["density_per_mm2"] is None and w["reason"] == "coverage_unknown"
    assert r["clark_evans"]["calc_status"] == "insufficient_data"   # not 0, not "random"
    assert r["affected_die_count"] is None and r["inspected_die_count"] is None
    assert r["lift_pin"] == {"feature_status": "disabled"}          # disabled, not no_match

    # provenance: hashes recomputed here from the input bytes, not copied from the screen
    prov = r["provenance"]
    assert prov["source_sha256"] == hashlib.sha256((K / "f01.klf").read_bytes()).hexdigest()
    assert prov["profile_sha256"] == hashlib.sha256(PROFILE.read_bytes()).hexdigest()
    assert prov["profile_id"] == "f01_test_only" and prov["adapter"] == "synthetic-um-die00-notch-down"
    assert prov["coverage"] == {"status": "unknown", "inspected_radius_mm": None}
    assert prov["schema_version"] and prov["code_version"] and prov["rule_version"] and prov["parser"]
    assert prov["model_version"] is None
    assert doc["review"] is None                              # no SQLite path -> no review revision


def test_e16_downloaded_csv_zip_matches_the_same_expectations(server, browser):
    page = browser.new_page()
    _run(page, server, klarf=K / "f01.klf")
    page.get_by_text("내보내기").first.wait_for(timeout=60000)
    blob = _download(page, "CSV(zip) 다운로드")
    doc = json.loads(_download(page, "JSON 다운로드").decode("utf-8"))
    page.close()

    z = zipfile.ZipFile(io.BytesIO(blob))
    assert sorted(z.namelist()) == ["bin_sector.csv", "defects.csv", "manifest.json", "review.json",
                                    "spatial_counts.csv"]

    def rows(name):
        return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8"))))

    d = rows("defects.csv")
    assert len(d) == 8
    assert {x["defect_id"]: (float(x["x_mm"]), float(x["y_mm"]), float(x["r_mm"]), x["bin"], x["clock"],
                             json.loads(x["zones"])) for x in d} == F01["defects"]
    for x in d:
        assert x["included"] == "True" and x["excluded_reason"] == "" and x["also_clock_tolerant"] == ""

    sc = rows("spatial_counts.csv")
    by = {(x["table"], x["key"]): x for x in sc}
    assert {k[1]: int(v["count"]) for k, v in by.items() if k[0] == "bin_total"} == F01["bin_totals"]
    assert {k[1]: int(v["count"]) for k, v in by.items() if k[0] == "sector_strict"} == F01["sectors_clock"]
    assert int(by[("center", "center")]["count"]) == F01["center"]
    assert int(by[("zone_union", "unique")]["count"]) == 8
    assert {k[1]: int(v["count"]) for k, v in by.items() if k[0] == "zone"} == \
        {"E1": 1, "E2": 1, "inner": 5, "band": 1}
    # null/0 in CSV: a real zero is written "0", an uncomputed value is an empty cell (manifest convention)
    assert by[("sector_strict", "1")]["count"] == "0"
    assert {k[1]: int(v["count"]) for k, v in by.items() if k[0] == "radial"} == F01["radial"]
    assert all(v["area_mm2"] == "" and v["density_per_mm2"] == "" for v in sc)
    assert all(v["reason"] == "coverage_unknown" for k, v in by.items() if k[0] == "radial")

    bs = rows("bin_sector.csv")
    assert {x["bin"]: {h: int(x[h]) for h in [str(i) for i in range(1, 13)] + ["center"]} for x in bs} == \
        _expect_bin_sector(F01["bin_sector"])
    assert {x["bin"]: int(x["total"]) for x in bs} == F01["bin_totals"]
    assert all(x["status"] == "computed" for x in bs)

    man = json.loads(z.read("manifest.json").decode("utf-8"))
    assert man["provenance"] == doc["result"]["provenance"]      # same provenance in both channels
    assert man["orientation_status"] == "notch_registered" and man["coordinate_frame"] == "notch_down"
    assert "empty cell = null" in man["null_convention"]
    assert json.loads(z.read("review.json").decode("utf-8")) is None


def test_e19_downloads_carry_the_stored_review_and_keep_the_prediction(server, browser, tmp_path):
    db = tmp_path / "dl.db"
    page = browser.new_page()
    _run(page, server, klarf=K / "f01.klf", db=str(db))
    page.get_by_text("내보내기").first.wait_for(timeout=60000)
    before = json.loads(_download(page, "JSON 다운로드").decode("utf-8"))
    assert before["review"]["review_status"] == "unreviewed" and before["review"]["latest_revision"] is None

    page.get_by_role("textbox", name="payload (JSON)").fill(json.dumps({"reason_code": "needs_sem_review"}))
    _select(page, "action", "defer")
    page.get_by_role("button", name="검토 저장").click()
    page.get_by_text("revision 1 저장").wait_for(timeout=60000)
    after = json.loads(_download(page, "JSON 다운로드").decode("utf-8"))
    z = zipfile.ZipFile(io.BytesIO(_download(page, "CSV(zip) 다운로드")))
    page.close()

    from wafer import store
    con = store.connect(db)
    key = con.execute("SELECT analysis_key FROM runs").fetchone()[0]
    con.close()
    assert after["review"] == {"analysis_key": key, "review_status": "deferred", "latest_revision": 1}
    assert json.loads(z.read("review.json").decode("utf-8")) == after["review"]
    assert after["result"] == before["result"]      # review is a separate revision; prediction unchanged
    assert after["result"]["n_included"] == 8 and after["result"]["bin_totals"] == F01["bin_totals"]
    assert json.loads(z.read("manifest.json").decode("utf-8"))["provenance"] == after["result"]["provenance"]


def test_e16_downloads_with_coverage_sidecar_carry_independent_density_values(server, browser, tmp_path):
    """Coverage given explicitly (full disk R=150, synthetic sidecar): areas and densities become real
    numbers, computed here by hand as pi*(hi^2 - lo^2) and count/area - never copied from the app."""
    import math
    side = tmp_path / "coverage.json"
    side.write_text(json.dumps({"coverage": {"shape": "full_disk", "radius_mm": 150,
                                             "source": "e2e synthetic full-disk declaration"}}), encoding="utf-8")
    page = browser.new_page()
    _run(page, server, klarf=K / "f01.klf", coverage=side)
    page.get_by_text("내보내기").first.wait_for(timeout=60000)
    doc = json.loads(_download(page, "JSON 다운로드").decode("utf-8"))
    z = zipfile.ZipFile(io.BytesIO(_download(page, "CSV(zip) 다운로드")))
    page.close()

    expect = {"0-50)": (1, math.pi * (50 ** 2 - 0 ** 2)), "50-100)": (4, math.pi * (100 ** 2 - 50 ** 2)),
              "100-150]": (3, math.pi * (150 ** 2 - 100 ** 2))}
    r = doc["result"]
    got = {"%g-%g%s" % (w["r_lo_mm"], w["r_hi_mm"], "]" if w["closed"] == "both" else ")"): w
           for w in r["radial_density"]["rows"]}
    assert set(got) == set(expect)
    for k, (n, area) in expect.items():
        assert got[k]["count"] == n and got[k]["reason"] is None
        assert got[k]["area_mm2"] == pytest.approx(area, rel=1e-12)
        assert got[k]["density_per_mm2"] == pytest.approx(n / area, rel=1e-12)
    assert r["clark_evans"]["calc_status"] == "computed" and r["clark_evans"]["n"] == 8
    prov = r["provenance"]
    assert prov["coverage"] == {"status": "declared_by_sidecar", "shape": "full_disk", "inspected_radius_mm": 150.0,
                                "source": "e2e synthetic full-disk declaration",
                                "sidecar_sha256": hashlib.sha256(side.read_bytes()).hexdigest()}
    assert r["n_included"] == 8 and r["bin_totals"] == F01["bin_totals"]      # coverage does not change counts

    sc = list(csv.DictReader(io.StringIO(z.read("spatial_counts.csv").decode("utf-8"))))
    radial = {x["key"]: x for x in sc if x["table"] == "radial"}
    for k, (n, area) in expect.items():
        assert int(radial[k]["count"]) == n and radial[k]["reason"] == ""
        assert float(radial[k]["area_mm2"]) == pytest.approx(area, rel=1e-12)
        assert float(radial[k]["density_per_mm2"]) == pytest.approx(n / area, rel=1e-12)
    assert json.loads(z.read("manifest.json").decode("utf-8"))["provenance"]["coverage"] == prov["coverage"]
