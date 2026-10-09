"""Streamlit review screen: streamlit run wafer/app.py

Thin UI over the shared core (wafer.cli.run_job / wafer.report / wafer.store) - no analysis logic here.
Display filters never change the stored counts (E16). Physical values (wafer radius, notch) are drawn only
from the profile, never estimated from the data (CLAUDE.md 4-1).
"""
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from wafer import store  # noqa: E402
from wafer.cli import run_job  # noqa: E402
from wafer.report import spatial_rows, write_csv  # noqa: E402

st.set_page_config(page_title="Wafer inspection map", layout="wide")
st.title("Wafer inspection map")
st.caption("합성 adapter 기준 개발 단계입니다. 실제 장비 export와 운영 임계값은 검증되지 않았습니다 (TBD.md).")

with st.sidebar:
    st.header("입력")
    k_up = st.file_uploader("KLARF", type=["klf", "klarf", "txt"])
    k_path = st.text_input("또는 KLARF 경로", key="klarf_path")
    p_up = st.file_uploader("Profile (YAML)", type=["yaml", "yml"])
    p_path = st.text_input("또는 profile 경로", key="profile_path")
    cov_path = st.text_input("coverage sidecar 경로 (선택, 없으면 coverage 미상)", key="coverage_path")
    db = st.text_input("SQLite 저장 경로 (선택)", key="db_path")
    run = st.button("분석 실행", key="run")

if run:
    st.session_state.pop("job", None)            # never show a previous result for a new request
    if not (k_up or k_path) or not (p_up or p_path):
        st.error("KLARF와 profile을 모두 지정하세요.")
    else:
        with tempfile.TemporaryDirectory() as d:  # uploaded inputs are removed right after the run
            klarf, name = k_path, k_path
            if k_up:
                klarf, name = str(Path(d) / Path(k_up.name).name), k_up.name
                Path(klarf).write_bytes(k_up.getvalue())
            profile = p_path
            if p_up:
                profile = str(Path(d) / Path(p_up.name).name)
                Path(profile).write_bytes(p_up.getvalue())
            out, code = run_job(klarf, profile, db=db or None, source_name=name, coverage_path=cov_path or None)
        st.session_state["job"] = {"out": out, "code": code, "db": db or None, "source": Path(name).name}

job = st.session_state.get("job")
if not job:
    st.info("왼쪽에서 KLARF와 profile을 지정하고 분석을 실행하세요.")
    st.stop()

out, code = job["out"], job["code"]
st.subheader("상태")
c1, c2, c3 = st.columns(3)
c1.metric("job_status", out["job_status"])
c2.metric("data_quality_status", out.get("data_quality_status") or "-")
c3.metric("exit code", code)
st.caption(f"입력: {job['source']}")
if out["job_status"] != "succeeded":
    st.error(f'{out.get("error")}: {out.get("detail", "")} {out.get("keys", "")}')
    st.stop()

res, points = out["result"], out["_points"]
prov = res["provenance"]
st.caption(f"source_sha256 {prov['source_sha256'][:12]}… · profile {prov['profile_id']} · schema {prov['schema_version']} "
           f"· code {prov['code_version']} · adapter {prov['adapter']} · coverage {prov['coverage']['status']} · 단위 mm")
st.write("pattern_summary:", ", ".join(res["pattern_summary"]))

st.subheader("개수 (원본 전체, 필터와 무관)")
m = st.columns(4)
m[0].metric("parsed", res["n_parsed"])
m[1].metric("included", res["n_included"])
m[2].metric("excluded", res["n_excluded"])
m[3].metric("center", "-" if res["center"] is None else res["center"])

bins_all = sorted(res["bin_totals"])
shown = st.multiselect("지도에 표시할 bin (표시 범위만 바뀜)", bins_all, default=bins_all, key="bin_filter")
groups = res["detect"].get("signature_groups") or {}
overlay = st.selectbox("강조할 signature group", ["(없음)"] + list(groups), key="overlay")

inc = [p for p in points if p["included"]]
vis = [p for p in inc if p["bin"] in shown]
fig = go.Figure()
R = out.get("_wafer_radius_mm")
if R is not None:
    t = np.linspace(0, 2 * np.pi, 361)
    fig.add_trace(go.Scatter(x=R * np.sin(t), y=R * np.cos(t), mode="lines", name="wafer", line={"color": "#888"}))
    if res["orientation_status"] == "notch_registered":
        fig.add_trace(go.Scatter(x=[0], y=[-R], mode="markers", name="notch (6시)", marker={"symbol": "triangle-up", "size": 12}))
for b in shown:
    pts = [p for p in vis if p["bin"] == b]
    fig.add_trace(go.Scatter(x=[p["x_mm"] for p in pts], y=[p["y_mm"] for p in pts], mode="markers", name=f"bin {b}",
                             text=[str(p["defect_id"]) for p in pts], marker={"size": 7}))
if overlay != "(없음)":
    ids = set(groups[overlay])
    pts = [p for p in inc if p["defect_id"] in ids]
    fig.add_trace(go.Scatter(x=[p["x_mm"] for p in pts], y=[p["y_mm"] for p in pts], mode="markers",
                             name=f"group {overlay}", marker={"size": 13, "symbol": "circle-open", "line": {"width": 2}}))
fig.update_layout(yaxis={"scaleanchor": "x"}, height=560, margin={"l": 10, "r": 10, "t": 10, "b": 10})
st.plotly_chart(fig, width="stretch")
st.caption(f"표시 중 {len(vis)} / 포함 {len(inc)} (bin 필터는 집계값을 바꾸지 않음)"
           + ("" if R is not None else " · wafer 반경 미설정: 외곽선·노치를 그리지 않음")
           + ("" if res["orientation_status"] == "notch_registered" else " · 노치 위치 미상: 화면 방향은 물리 방향이 아님"))

st.subheader("bin × 시계방향")
if res["bin_sector"] is None:
    st.warning(f'시계방향 집계 없음 — {res["clock_status"]["status"]}: {res["clock_status"]["reason"]}')
else:
    bs = pd.DataFrame(res["bin_sector"]).T
    bs.columns = [str(c) for c in bs.columns]
    bs["total"] = bs.sum(axis=1)
    st.dataframe(bs, key="bin_sector_table")

st.subheader("공간 집계 (빈 칸 = 미계산/비활성, 0 = 실제 0)")
st.dataframe(pd.DataFrame(spatial_rows(res), columns=["table", "key", "count", "area_mm2", "density_per_mm2", "reason"]).astype(str))

st.subheader("판정 상태")
det = res["detect"]
rows = [("ring", det.get("ring", det)), ("line", det.get("line", det)), ("lift_pin", res["lift_pin"])]
rows = [(n, r.get("feature_status"), r.get("reason") or r.get("match_type") or r.get("coverage_flag") or "")
        for n, r in rows]
rows += [(n, r.get("calc_status"), r.get("reason") or "") for n, r in
         (("clark_evans (calc)", res["clark_evans"]), ("radial_density (calc)", res["radial_density"]))]
st.table(pd.DataFrame(rows, columns=["feature", "status", "reason / detail"]))
if "clusters" in det:
    st.caption(f"DBSCAN 군집 {len(det['clusters'])}개 · noise {len(det['noise'])}건(총수에 포함)")
st.caption("후보(candidate)는 형상 근거이며 원인 확정이 아닙니다.")

# ---- review (before the downloads, so exports carry the latest revision) ----
review_info = None
st.subheader("검토")
if not job["db"] or "store" not in out:
    st.info("검토를 저장하려면 SQLite 저장 경로를 지정해 분석하세요.")
else:
    key = out["store"]["analysis_key"]
    con = store.connect(job["db"])
    try:
        with st.form("review"):
            action = st.selectbox("action", store.ACTIONS, key="rv_action")
            payload_text = st.text_area("payload (JSON)", "{}", key="rv_payload",
                                        help='예: {"target": "0", "axis": "morphology", "label": "edge_local"} / '
                                             '{"clusters": ["0", "1"]} / {"reason_code": "needs_sem_review"}')
            reason = st.text_input("사유", key="rv_reason")
            reviewer = st.text_input("검토자", key="rv_reviewer")
            submitted = st.form_submit_button("검토 저장", key="rv_submit")
        if submitted:
            try:
                rev = store.add_review(con, key, action, json.loads(payload_text), reason=reason or None,
                                       reviewer=reviewer or None)
                st.success(f"revision {rev} 저장 (예측 원본은 변경되지 않음)")
            except (ValueError, json.JSONDecodeError) as e:
                st.error(f"검토 거부: {e}")
        revs = store.reviews(con, key)
        review_info = {"analysis_key": key, "review_status": store.review_status(con, key),
                       "latest_revision": revs[-1]["revision"] if revs else None}
        st.write(f"analysis_key `{key[:12]}…` · review_status: **{review_info['review_status']}**")
        st.write("현재 군집(검토 반영):", {k: len(v) for k, v in store.reviewed_clusters(con, key).items()})
        if revs:
            st.dataframe(pd.DataFrame(revs).astype(str))
    finally:
        con.close()

st.subheader("내보내기")
clean = {k: v for k, v in out.items() if not k.startswith("_")}
clean["review"] = review_info            # null when not stored; ties the export to a review revision
st.download_button("JSON 다운로드", json.dumps(clean, ensure_ascii=False, indent=2, default=str),
                   file_name="result.json", key="dl_json")
with tempfile.TemporaryDirectory() as d:
    files = write_csv(res, points, d)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in files:
            z.write(f, Path(f).name)
        z.writestr("review.json", json.dumps(review_info, ensure_ascii=False, indent=2))
st.download_button("CSV(zip) 다운로드", buf.getvalue(), file_name="result_csv.zip", key="dl_csv")
