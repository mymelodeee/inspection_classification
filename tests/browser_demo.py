"""Visible local Edge demo: unified input -> coverage -> SQLite reuse -> review.
Run with the project's Python. Closing the demo browser stops its private Streamlit server.
Uses only synthetic project fixtures and writes a new timestamped demo_output directory.
"""
import csv
import io
import json
import math
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "demo_output" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    db = output / "coverage_sqlite.db"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "wafer/app.py"),
                             "--server.headless=true", f"--server.port={port}",
                             "--browser.gatherUsageStats=false"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    print(json.dumps({"url": url, "output": str(output), "db": str(db)}), flush=True)
    try:
        for _ in range(120):
            try:
                if urlopen(url + "/_stcore/health", timeout=1).read() == b"ok":
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Demo server did not start")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=False)
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            profile = page.get_by_role("textbox", name="또는 profile 경로", exact=True)
            profile.wait_for(timeout=60000)
            assert Path(profile.input_value()).name == "dummy_die_local_test_profile.yaml"
            page.locator(".st-key-batch_files input[type=file]").set_input_files(
                [str(ROOT / "klarf_dummy_data/klarf" / name) for name in ("F01_counts.klarf", "F01_up.klarf")])
            page.get_by_text("업로드 2개", exact=False).wait_for()

            def analyse(scan=True):
                page.wait_for_load_state("networkidle")
                if scan:
                    page.get_by_role("button", name="입력 목록 확인").click()
                    page.wait_for_load_state("networkidle")
                page.get_by_role("button", name="일괄 분석 실행").click()
                page.locator('[data-testid="stMetric"]').filter(has_text="포함 결함 합").wait_for(timeout=60000)
                page.wait_for_load_state("networkidle")
                assert page.locator('[data-testid="stMetric"]').filter(has_text="포함 결함 합").inner_text().strip().endswith("16")

            def summary():
                # Wait for Streamlit's post-analysis rerun before initiating the download.
                page.wait_for_timeout(1500)
                for attempt in range(3):
                    with page.expect_download() as event:
                        page.get_by_role("button", name="전체 요약 CSV", exact=True).click()
                    try:
                        raw = Path(event.value.path()).read_text(encoding="utf-8")
                        page.wait_for_timeout(1000)
                        return list(csv.DictReader(io.StringIO(raw)))
                    except Exception as error:
                        if "canceled" not in str(error) or attempt == 2:
                            raise
                        page.wait_for_timeout(1500)

            analyse()
            assert all(row["density_per_mm2"] == "" for row in summary())
            print("PASS 1: no coverage -> density unknown; 2 files, 16 defects", flush=True)
            page.get_by_text("면적 보정 밀도(비교 가능", exact=False).scroll_into_view_if_needed()
            page.screenshot(path=str(output / "01-no-coverage.png"), full_page=True)
            time.sleep(3)
            for label, value in (
                ("coverage sidecar 경로 (선택, 없으면 coverage 미상)", ROOT / "tests/fixtures/coverage/full_disk_150.json"),
                ("SQLite 저장 경로 (선택, 검토·재사용에 필요)", db),
            ):
                field = page.get_by_role("textbox", name=label, exact=True)
                field.fill(str(value))
                field.press("Enter")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            analyse()
            rows = summary()
            for row in rows:
                assert math.isclose(float(row["valid_area_mm2"]), math.pi * 150**2)
                assert math.isclose(float(row["density_per_mm2"]), 8 / (math.pi * 150**2))
            print("PASS 2: coverage area=70685.8347 mm2 per wafer; density=0.0001131768/mm2", flush=True)
            page.get_by_text("면적 보정 밀도(비교 가능", exact=False).scroll_into_view_if_needed()
            page.screenshot(path=str(output / "02-coverage.png"), full_page=True)
            time.sleep(3)
            analyse(scan=False)
            page.get_by_text("저장 결과 재사용 2", exact=False).wait_for(timeout=60000)
            print("PASS 3: same SQLite DB -> 2 reused results", flush=True)
            page.get_by_role("button", name="상세 맵·검토 화면 열기").click()
            page.get_by_text("job_status").wait_for(timeout=60000)
            page.wait_for_load_state("networkidle")
            page.get_by_text("파일 상세보기", exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(output / "03-detail.png"), full_page=True)
            time.sleep(3)
            # The initial review action is confirm; save that explicit review with an empty payload.
            page.get_by_role("textbox", name="payload (JSON)").fill('{}')
            page.get_by_role("textbox", name="검토자", exact=True).fill("demo")
            page.get_by_role("button", name="검토 저장").click()
            page.get_by_text("revision 1 저장", exact=False).wait_for()
            page.get_by_role("button", name="검토 저장").scroll_into_view_if_needed()
            page.screenshot(path=str(output / "04-review.png"))
            with sqlite3.connect(db) as con:
                counts = {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                          for table in ("runs", "attempts", "batches", "batch_members", "reviews")}
            assert counts == {"runs": 2, "attempts": 4, "batches": 2, "batch_members": 4, "reviews": 1}, counts
            (output / "verification.json").write_text(json.dumps({"url": url, "db": str(db), "counts": counts,
                "area_per_wafer_mm2": math.pi * 150**2, "density_per_mm2": 8 / (math.pi * 150**2)}, indent=2), encoding="utf-8")
            print("PASS 4: review revision 1 saved; " + json.dumps(counts), flush=True)
            page.get_by_role("button", name="← 분석 목록으로 돌아가기").click()
            page.get_by_text("분석 선택 2개", exact=False).wait_for()
            page.get_by_role("button", name="상세 맵·검토 화면 열기").scroll_into_view_if_needed()
            page.screenshot(path=str(output / "05-overview.png"))
            print("READY: browser stays open for inspection; close the browser to stop this demo", flush=True)
            while browser.is_connected() and browser.contexts and any(c.pages for c in browser.contexts):
                page.wait_for_timeout(1000)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
