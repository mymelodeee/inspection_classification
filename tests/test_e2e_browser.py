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
    page.get_by_label("또는 KLARF 경로 (한 줄에 하나)").wait_for(timeout=60000)
    if upload:
        page.locator("input[type=file]").first.set_input_files(str(upload))
    else:
        page.get_by_label("또는 KLARF 경로 (한 줄에 하나)").fill(str(klarf))
    page.get_by_role("textbox", name="또는 profile 경로", exact=True).fill(str(PROFILE))
    if coverage:
        page.get_by_role("textbox", name="coverage sidecar 경로 (선택, 없으면 coverage 미상)").fill(str(coverage))
    page.get_by_role("textbox", name="SQLite 저장 경로 (선택, 검토·재사용에 필요)", exact=True).fill(db)
    page.get_by_role("textbox", name="SQLite 저장 경로 (선택, 검토·재사용에 필요)", exact=True).press("Enter")
    page.get_by_role("button", name="입력 목록 확인").click()
    page.get_by_role("button", name="일괄 분석 실행").click()
    page.locator('[data-testid="stMetric"]').filter(has_text="포함 결함 합").wait_for(timeout=60000)
    if _metric(page, "성공") != "0":
        page.get_by_role("button", name="상세 맵·검토 화면 열기").click()
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
    assert _metric(page, "실패") == "1"
    assert page.get_by_role("button", name="상세 맵·검토 화면 열기").count() == 0
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
# CLASSNUMBER as the bin label per T-03); provenance hashes are recomputed here with hashlib.
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
    # E16-NULLWHY (approved 2026-10-11, result-0.2): every top-level null carries a reason; nothing else does
    assert set(r["null_reasons"]) == {"affected_die_count", "inspected_die_count"}
    assert all(v.startswith("not computable") for v in r["null_reasons"].values())
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
    assert man["null_reasons"]["result"] == doc["result"]["null_reasons"]       # E16-NULLWHY (2026-10-11)
    assert all(by[k]["reason"] for k in by if "" in (by[k]["count"], by[k]["area_mm2"], by[k]["density_per_mm2"]))
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


# ---- Batch mode '일괄 분석' in the real browser (added 2026-10-10). Real Edge directory picker
# (input[webkitdirectory] + set_input_files(<directory>)) and multi-file picker; downloads are opened and compared
# with independent values: klarf_dummy_data/manifest.json (count / bin_counts / clock_counts), README total 1412,
# area pi*150^2 computed here. Function-level folder simulation: tests/test_batch.py (test_04, test_15 AppTest).
# Synthetic adapter only (C20). Browser rel_path for a folder upload starts with the chosen folder's name.
import math as _math      # noqa: E402
import shutil as _shutil  # noqa: E402

DD = ROOT / "klarf_dummy_data"
DUMMY_PROFILE = ROOT / "tests/profiles/dummy_die_local_test_profile.yaml"
DUMMY_SIDECAR = DD / "synthetic_profile.json"
DMAN = {c["name"]: c for c in json.loads((DD / "manifest.json").read_text(encoding="utf-8"))["cases"]}
DUMMY_TOTAL = 1412
DISK = _math.pi * 150.0 ** 2
BATCH_METRICS = ("업로드 파일", "분석 단위", "성공", "실패", "보류", "포함 결함 합")


def _dummy_folder(root):
    for k, n in enumerate(DMAN):
        d = root / f"part{k % 3}"
        d.mkdir(parents=True, exist_ok=True)
        _shutil.copy(DD / "klarf" / f"{n}.klarf", d / f"{n}.klarf")
    return root


def _batch(page, url, folder=None, files=None, coverage="", db="", n_files=None):
    page.goto(url)
    page.get_by_role("button", name="입력 목록 확인").wait_for(timeout=60000)
    if folder:
        page.locator(".st-key-batch_folder input[type=file]").set_input_files(str(folder))
        box = ".st-key-batch_folder"
    else:
        page.locator(".st-key-batch_files input[type=file]").set_input_files([str(f) for f in files])
        box = ".st-key-batch_files"
    page.locator(f'{box} [data-testid="stFileChip"]').first.wait_for(timeout=60000)   # Streamlit 1.65 file chip
    page.wait_for_load_state("networkidle")
    for label, value in (("또는 profile 경로", str(DUMMY_PROFILE)),
                         ("coverage sidecar 경로 (선택, 없으면 coverage 미상)", str(coverage)),
                         ("SQLite 저장 경로 (선택, 검토·재사용에 필요)", str(db))):
        page.get_by_role("textbox", name=label).fill(value)
        page.get_by_role("textbox", name=label).press("Enter")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="입력 목록 확인").click()
    page.get_by_role("button", name="일괄 분석 실행").wait_for(timeout=60000)
    page.get_by_role("button", name="일괄 분석 실행").click()
    page.locator('[data-testid="stMetric"]').filter(has_text="포함 결함 합").first.wait_for(timeout=180000)
    got = {k: _metric(page, k) for k in BATCH_METRICS}
    if n_files is not None:     # every chosen file reached the server (upload finished before the scan)
        assert got["업로드 파일"] == str(n_files), got
    return got


def _csv_rows(blob):
    return list(csv.DictReader(io.StringIO(blob.decode("utf-8"))))


def test_unified_detail_roundtrip_coverage_sqlite(server, browser, tmp_path):
    """E16-UNIFIED/E19: two F01 files -> detail -> review -> list -> same DB reuse.
    Count oracle: 8 each, total 16. Area oracle: pi*150^2 per wafer.
    """
    page = browser.new_page()
    db = tmp_path / "roundtrip.db"
    _batch(page, server, files=[DD / "klarf/F01_counts.klarf", DD / "klarf/F01_up.klarf"],
           coverage=ROOT / "tests/fixtures/coverage/full_disk_150.json", db=db, n_files=2)
    assert page.get_by_role("radio").count() == 0
    assert _metric(page, "포함 결함 합") == "16"
    page.get_by_role("button", name="상세 맵·검토 화면 열기").click()
    page.get_by_text("job_status").wait_for(timeout=60000)
    assert _metric(page, "included") == "8"
    _select(page, "action", "defer")
    page.get_by_role("textbox", name="payload (JSON)").fill('{"reason_code":"demo_review"}')
    page.get_by_role("button", name="검토 저장").click()
    page.get_by_text("revision 1 저장", exact=False).wait_for()
    page.get_by_role("button", name="← 분석 목록으로 돌아가기").click()
    page.get_by_text("분석 선택 2개", exact=False).wait_for()
    assert page.locator('[data-testid="stFileChip"]').count() == 2
    assert _metric(page, "포함 결함 합") == "16"
    page.get_by_role("button", name="일괄 분석 실행").click()
    page.get_by_text("저장 결과 재사용 2", exact=False).wait_for(timeout=60000)
    rows = _csv_rows(_download(page, "전체 요약 CSV"))
    assert len(rows) == 2
    assert sum(row["review_status_now"] == "deferred" for row in rows) == 1
    for row in rows:
        assert float(row["valid_area_mm2"]) == pytest.approx(DISK)
        assert float(row["density_per_mm2"]) == pytest.approx(8 / DISK)
    import sqlite3
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 4
        assert con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
    page.get_by_role("button", name="상세 맵·검토 화면 열기").click()
    page.get_by_text("review_status: deferred", exact=False).wait_for()
    page.close()


def test_batch_selection_clear_and_profile_reload(server, browser, tmp_path):
    """E16-BATCH-SELECT / E18-PROFILE-RELOAD: user selects inputs before scan;
    changed on-disk profile is revalidated. F01 independent count=8; no excluded input in ZIP.
    """
    page = browser.new_page()
    _batch(page, server, files=[DD / "klarf/F01_counts.klarf", DD / "klarf/ring.klarf"], n_files=2)
    page.get_by_role("button", name="전체 제외", exact=True).click()
    page.get_by_text("분석 선택 0개", exact=False).wait_for()
    assert page.get_by_role("button", name="일괄 분석 실행").count() == 0
    page.get_by_role("button", name="입력 목록 확인").click()
    page.get_by_text("파일(또는 폴더)과 profile을 지정하세요.").wait_for()
    page.get_by_label("분석할 파일 (제거하면 분석에서 제외)").click()
    page.get_by_role("option", name="1. F01_counts.klarf", exact=True).click()
    page.keyboard.press("Escape")
    profile = tmp_path / "editable.yaml"
    profile.write_bytes(DUMMY_PROFILE.read_bytes())
    page.get_by_role("textbox", name="또는 profile 경로").fill(str(profile))
    page.get_by_role("textbox", name="또는 profile 경로").press("Enter")
    page.get_by_role("button", name="입력 목록 확인").click()
    page.get_by_role("button", name="일괄 분석 실행").wait_for()
    profile.write_text(profile.read_text().replace("dummy_die_local_test_only", "updated_profile"), encoding="utf-8")
    page.get_by_role("button", name="일괄 분석 실행").click()
    page.locator('[data-testid="stMetric"]').filter(has_text="포함 결함 합").wait_for(timeout=60000)
    assert _metric(page, "포함 결함 합") == "8"
    assert _metric(page, "업로드 파일") == "1"
    z = zipfile.ZipFile(io.BytesIO(_download(page, "개별 결과 + manifest ZIP")))
    manifest = json.loads(z.read("batch_manifest.json"))
    assert manifest["config"]["profile_id"] == "updated_profile"
    assert manifest["config"]["profile_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest()
    page.get_by_role("button", name="전체 선택", exact=True).click()
    page.get_by_text("분석 선택 2개", exact=False).wait_for()
    folder = tmp_path / "upload_folder"
    folder.mkdir()
    (folder / "copy.klarf").write_bytes((DD / "klarf/F01_counts.klarf").read_bytes())
    page.locator(".st-key-batch_folder input[type=file]").set_input_files(str(folder))
    page.get_by_text("업로드 3개", exact=False).wait_for()
    page.get_by_role("button", name="업로드 전체 삭제").click()
    page.locator(".st-key-batch_files_1 input[type=file]").wait_for(state="attached")
    assert page.locator('[data-testid="stFileChip"]').count() == 0
    assert page.get_by_role("button", name="일괄 분석 실행").count() == 0
    page.locator(".st-key-batch_files_1 input[type=file]").set_input_files(str(DD / "klarf/F01_counts.klarf"))
    page.get_by_text("업로드 1개", exact=False).wait_for()
    page.get_by_role("button", name="입력 목록 확인").click()
    page.get_by_role("button", name="일괄 분석 실행").wait_for()
    page.close()


def test_batch_edge_folder_and_multi_file_selection_give_the_same_result(server, browser, tmp_path):
    folder = _dummy_folder(tmp_path / "dummy13")
    expect = {"업로드 파일": "13", "분석 단위": "13", "성공": "13", "실패": "0", "보류": "0",
              "포함 결함 합": str(DUMMY_TOTAL)}
    page = browser.new_page()
    mf = _batch(page, server, folder=folder, db=tmp_path / "f.db", n_files=13)
    rows_f = _csv_rows(_download(page, "전체 요약 CSV"))
    page.close()
    page = browser.new_page()
    ml = _batch(page, server, files=sorted(folder.rglob("*.klarf")), db=tmp_path / "l.db", n_files=13)
    rows_l = _csv_rows(_download(page, "전체 요약 CSV"))
    page.close()
    assert mf == ml == expect
    assert all(r["rel_path"].startswith("dummy13/part") for r in rows_f)      # relative path from the picker
    assert sorted(r["rel_path"] for r in rows_l) == sorted(f"{n}.klarf" for n in DMAN)
    kf = {Path(r["rel_path"]).name: r["analysis_key"] for r in rows_f}
    kl = {Path(r["rel_path"]).name: r["analysis_key"] for r in rows_l}
    assert kf == kl and len(set(kf.values())) == 13 and "" not in kf.values()


def test_batch_edge_downloads_match_manifest_and_independent_density(server, browser, tmp_path):
    folder = _dummy_folder(tmp_path / "dummy13")
    page = browser.new_page()
    _batch(page, server, folder=folder, coverage=DUMMY_SIDECAR, n_files=13)
    summary = _csv_rows(_download(page, "전체 요약 CSV"))
    types = _csv_rows(_download(page, "유형별 요약 CSV"))
    z = zipfile.ZipFile(io.BytesIO(_download(page, "개별 결과 + manifest ZIP")))
    page.close()

    rows = {Path(r["rel_path"]).stem: r for r in summary}
    assert set(rows) == set(DMAN)
    for n, m in DMAN.items():
        assert rows[n]["status"] == "succeeded" and int(rows[n]["n_included"]) == m["count"], n
        assert json.loads(rows[n]["bins"]) == m["bin_counts"], n
    assert sum(int(r["n_included"]) for r in summary) == DUMMY_TOTAL
    assert rows["empty"]["n_included"] == "0" and rows["empty"]["status"] == "succeeded"
    assert float(rows["F01_counts"]["density_per_mm2"]) == pytest.approx(8 / DISK, rel=1e-12)
    assert rows["F01_counts"]["ring_support"] == "" and rows["F01_counts"]["local_support"] == "0"

    assert [t["type"] for t in types] == ["ring", "line", "local", "lift_pin"]
    lp = next(t for t in types if t["type"] == "lift_pin")
    assert lp["disabled"] == "13" and lp["evaluable_units"] == "0"         # disabled in the profile, not no_match
    assert all(t["basis"] == "initial predictions (reviews not applied)" and t["files_not_evaluated"] == "0"
               for t in types)

    man = json.loads(z.read("batch_manifest.json"))
    assert man["overview"]["total_included_defects"] == DUMMY_TOTAL and man["overview"]["succeeded"] == 13
    assert man["config"]["coverage_sidecar_sha256"] == hashlib.sha256(DUMMY_SIDECAR.read_bytes()).hexdigest()
    g = man["density_by_group"]
    assert len(g) == 1 and g[0]["sum_count"] == DUMMY_TOTAL
    assert g[0]["sum_area_mm2"] == pytest.approx(13 * DISK, rel=1e-12)
    units = sorted({n.split("/")[1] for n in z.namelist() if n.startswith("units/")})
    assert len(units) == 13
    seen = set()
    for u in units:
        doc = json.loads(z.read(f"units/{u}/result.json"))
        r = doc["result"]
        name = next(n for n, m in DMAN.items() if m["file_sha256"] == r["provenance"]["source_sha256"])
        m = DMAN[name]
        assert (r["n_included"], r["bin_totals"], r["center"], r["sectors_clock"]) == \
            (m["count"], m["bin_counts"], m["center_count"], m["clock_counts"]), name
        assert doc["review"] is None and not [k for k in doc if k.startswith("_")]
        seen.add(name)
    assert seen == set(DMAN)


def test_batch_edge_mixed_folder_finishes_the_valid_inputs(server, browser, tmp_path):
    root = tmp_path / "mixed"
    (root / "lotA/w1").mkdir(parents=True)
    (root / "lotA/w2").mkdir(parents=True)
    _shutil.copy(DD / "klarf/F01_counts.klarf", root / "lotA/w1/F01_counts.klarf")
    _shutil.copy(DD / "klarf/F01_counts.klarf", root / "lotA/w2/F01_counts.klarf")     # duplicate content
    _shutil.copy(DD / "klarf/empty.klarf", root / "empty.klarf")
    src = (DD / "klarf/F01_counts.klarf").read_bytes().decode("utf-8")
    assert "Data 8" in src
    (root / "broken.klarf").write_bytes(src.replace("Data 8", "Data 9", 1).encode("utf-8"))   # damaged
    (root / "notes.txt").write_text("not a klarf file\n", encoding="utf-8")
    _shutil.copy(DD / "maps/overview.png", root / "overview.png")
    _shutil.copy(DD / "klarf/F01_counts.klarf", root / "export.001")
    _shutil.copy(K / "f01.klf", root / "flat_f01.klf")                                   # other adapter -> held
    expect_status = {"broken.klarf": "invalid_input", "empty.klarf": "succeeded", "export.001": "excluded",
                     "flat_f01.klf": "held", "lotA/w1/F01_counts.klarf": "succeeded",
                     "lotA/w2/F01_counts.klarf": "duplicate_in_batch", "notes.txt": "invalid_input",
                     "overview.png": "excluded"}
    page = browser.new_page()
    got = _batch(page, server, folder=root, n_files=8)
    summary = _csv_rows(_download(page, "전체 요약 CSV"))
    page.close()
    assert got == {"업로드 파일": "8", "분석 단위": "2", "성공": "2", "실패": "2", "보류": "1", "포함 결함 합": "8"}
    by = {r["rel_path"].removeprefix("mixed/"): r for r in summary}
    # the browser decides the file order, so which identical copy is analysed first is not fixed: one of the two
    # is succeeded and the other duplicate_in_batch pointing to it (same analysis, not run twice)
    pair = sorted(by[k]["status"] for k in ("lotA/w1/F01_counts.klarf", "lotA/w2/F01_counts.klarf"))
    assert pair == ["duplicate_in_batch", "succeeded"]
    dup = next(by[k] for k in ("lotA/w1/F01_counts.klarf", "lotA/w2/F01_counts.klarf")
               if by[k]["status"] == "duplicate_in_batch")
    assert by[next(k for k, r in by.items() if r["index"] == dup["duplicate_of"])]["status"] == "succeeded"
    rest = {k: r["status"] for k, r in by.items() if "/F01_counts.klarf" not in k}
    assert rest == {k: v for k, v in expect_status.items() if "/F01_counts.klarf" not in k}
    assert by["overview.png"]["reason"] == "extension_not_in_input_contract"
    assert all(by[k]["n_included"] == "8" for k in ("lotA/w1/F01_counts.klarf", "lotA/w2/F01_counts.klarf"))
    assert by["empty.klarf"]["n_included"] == "0"
