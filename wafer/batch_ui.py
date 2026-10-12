"""Streamlit batch page (mode "일괄 분석" in wafer/app.py). UI only: everything is computed by wafer.batch,
which runs the single-file core. Uploads -> preflight list -> run (frozen inputs) -> overview, unit table,
type summary, extent metrics, gallery, downloads. Filters change the view only, never the batch.
"""
import tempfile
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wafer import batch as B
from wafer import store
from wafer.profile import ConfigInvalid
from wafer.ui_inputs import DEFAULT_PROFILE, PROFILE_HELP, COVERAGE_HELP, DB_HELP

GALLERY_PAGE = 12
MAX_POINTS_PER_THUMB = 2000     # display only; statistics always use every included defect


def _with_profile(d, raw, path):
    """Uploaded profile bytes go to a temp file inside `d` (removed with it); else the given path."""
    if raw is None:
        return path or None
    p = Path(d) / "profile.yaml"    # never the uploaded name as a path
    p.write_bytes(raw)
    return str(p)


def _input_error(e):
    if isinstance(e, ConfigInvalid):
        st.error(f"CONFIG_INVALID: {', '.join(e.keys)} {getattr(e, 'reason', '')} {e.message}".rstrip())
    else:   # missing / unreadable profile or sidecar path
        st.error(f"INPUT_NOT_FOUND: {getattr(e, 'filename', '') or e}")


def _set_page(key, page):
    st.session_state[key] = page


def _pager(pages, key="gallery_page", window=9):
    """<< < [page numbers] > >> buttons; returns the current page (1-based). Shows at most `window` numbers
    around the current page. The current page is highlighted and disabled; out-of-range arrows are disabled."""
    cur = min(max(1, int(st.session_state.get(key, 1))), pages)
    st.session_state[key] = cur
    lo = max(1, min(cur - window // 2, pages - window + 1))
    nums = list(range(lo, min(pages, lo + window - 1) + 1))
    items = [("<<", 1, "first"), ("<", cur - 1, "prev")] + [(str(n), n, f"n{n}") for n in nums] +             [(">", cur + 1, "next"), (">>", pages, "last")]
    for col, (label, target, name) in zip(st.columns(len(items)), items):
        col.button(label, key=f"{key}_{name}", on_click=_set_page, args=(key, target),
                   disabled=not 1 <= target <= pages or target == cur,
                   type="primary" if label == str(cur) else "secondary", width="stretch")
    st.caption(f"페이지 {cur} / {pages}")
    return cur


def _types_label(value):
    """candidate_types cell -> gallery text: 'ring, local'; '' -> 없음; None/missing (older data) -> '-'."""
    if value is None or (isinstance(value, float) and value != value):
        return "-"
    parts = [t for t in str(value).split(",") if t]
    return ", ".join(parts) if parts else "없음"


def _thumb(out, title, R):
    pts = [p for p in out["_points"] if p["included"]]
    step = max(1, -(-len(pts) // MAX_POINTS_PER_THUMB))     # ceil: never more than the cap
    shown = pts[::step]
    fig = go.Figure()
    if R is not None:
        t = np.linspace(0, 2 * np.pi, 181)
        fig.add_trace(go.Scatter(x=R * np.sin(t), y=R * np.cos(t), mode="lines", line={"color": "#999"}, showlegend=False))
        if out["result"]["orientation_status"] == "notch_registered":
            fig.add_trace(go.Scatter(x=[0], y=[-R], mode="markers", marker={"symbol": "triangle-up", "size": 9},
                                     showlegend=False))
    for b in sorted({p["bin"] for p in shown}):
        q = [p for p in shown if p["bin"] == b]
        fig.add_trace(go.Scatter(x=[p["x_mm"] for p in q], y=[p["y_mm"] for p in q], mode="markers",
                                 marker={"size": 4}, name=f"bin {b}"))
    fig.update_layout(title={"text": title, "font": {"size": 11}}, height=260, margin={"l": 5, "r": 5, "t": 30, "b": 5},
                      yaxis={"scaleanchor": "x"}, showlegend=False)
    return fig, len(shown), len(pts)


def _open_detail(unit_index, candidate_types=None):
    """Hand one analysed unit to the existing single-map detail / review screen, with the SAME candidate_types
    cell as the unit table (batch-level codes cannot be derived from one result)."""
    b = st.session_state["batch"]
    out = b["units"][unit_index]
    e = next(x for x in b["entries"] if x["index"] == unit_index)
    st.session_state["job"] = {"out": out, "code": 0, "db": st.session_state.get("batch_db"), "source": e["rel_path"],
                               "candidate_types": candidate_types}
    for key in ("bin_filter", "overlay", "map_color", "rv_payload", "rv_reason", "rv_reviewer", "rv_action"):
        st.session_state.pop(key, None)
    st.session_state["show_detail"] = True


def _invalidate_inputs():
    for key in ("batch_scan", "batch", "batch_items", "job"):
        st.session_state.pop(key, None)
    st.session_state["show_detail"] = False


def _clear_uploads():
    st.session_state["batch_upload_epoch"] = st.session_state.get("batch_upload_epoch", 0) + 1
    st.session_state.pop("batch_selected", None)
    st.session_state.pop("batch_upload_signature", None)
    st.session_state["batch_paths"] = ""
    _invalidate_inputs()


def _restore_default_profile():
    if not st.session_state.get("batch_profile_path", "").strip():
        st.session_state["batch_profile_path"] = DEFAULT_PROFILE


def render():
    with st.sidebar:
        st.header("분석 입력")
        epoch = st.session_state.get("batch_upload_epoch", 0)
        suffix = f"_{epoch}" if epoch else ""
        files = st.file_uploader("여러 파일 선택", accept_multiple_files=True, key="batch_files" + suffix)
        folder = st.file_uploader("폴더 선택(하위 폴더 포함)", accept_multiple_files="directory", key="batch_folder" + suffix)
        paths = st.text_area("또는 KLARF 경로 (한 줄에 하나)", key="batch_paths")
        st.button("업로드 전체 삭제", key="batch_clear", on_click=_clear_uploads)
        p_up = st.file_uploader("Profile (YAML)", type=["yaml", "yml"], key="batch_profile_up")
        if "batch_profile_path" in st.session_state and not st.session_state["batch_profile_path"].strip():
            del st.session_state["batch_profile_path"]
        p_path = st.text_input("또는 profile 경로", value=DEFAULT_PROFILE, key="batch_profile_path",
                               help=PROFILE_HELP, on_change=_restore_default_profile)
        st.caption(PROFILE_HELP)
        cov = st.text_input("coverage sidecar 경로 (선택, 없으면 coverage 미상)", key="batch_coverage", help=COVERAGE_HELP)
        db = st.text_input("SQLite 저장 경로 (선택, 검토·재사용에 필요)", key="batch_db_path", help=DB_HELP)
        with st.expander("입력 상한"):
            max_files = st.number_input("최대 파일 수", 1, 100000, B.DEFAULT_LIMITS["max_files"], key="lim_files")
            max_file_mb = st.number_input("파일당 최대 MB", 1, 10000, B.DEFAULT_LIMITS["max_file_bytes"] // 2**20, key="lim_file")
            max_total_mb = st.number_input("총 최대 MB", 1, 100000, B.DEFAULT_LIMITS["max_total_bytes"] // 2**20, key="lim_total")
        do_scan = st.button("입력 목록 확인", key="batch_scan_btn")

    if st.session_state.get("show_detail") and not do_scan:
        # Keep the selection widget's value when its main-page widget is not rendered.
        if "batch_selected" in st.session_state:
            st.session_state["batch_selected"] = st.session_state["batch_selected"]
        st.sidebar.info("상세보기는 분석 당시의 결과입니다. 새 입력·설정은 입력 목록 확인 후 분석에 반영됩니다.")
        return
    st.session_state["show_detail"] = False
    st.subheader("파일 분석")
    st.caption("파일 1개 또는 여러 개를 같은 방식으로 분석합니다. 결과에서 파일을 선택하고 상세보기를 여세요.")
    st.caption("업로드한 파일은 서버 메모리에서만 처리하고 분석 후 임시 파일을 지웁니다. 파일명은 해석하지 않으며 "
               "lot/wafer는 KLARF 헤더 값(검증 전, TBD T-26)입니다. 합성 adapter 기준이며 실제 장비 검증이 아닙니다.")

    uploaded = [(f.name, f.getvalue()) for f in (files or []) + (folder or [])]
    try:
        uploaded += [(str(Path(p.strip())), Path(p.strip()).read_bytes())
                     for p in paths.splitlines() if p.strip()]
    except OSError as e:
        _invalidate_inputs()
        _input_error(e)
        return
    signature = [(name, hashlib.sha256(raw).hexdigest()) for name, raw in uploaded]
    if signature != st.session_state.get("batch_upload_signature"):
        st.session_state["batch_upload_signature"] = signature
        st.session_state["batch_selected"] = list(range(len(uploaded)))
        _invalidate_inputs()
    if uploaded:
        a, b = st.columns(2)
        if a.button("전체 선택", key="batch_select_all"):
            st.session_state["batch_selected"] = list(range(len(uploaded)))
        if b.button("전체 제외", key="batch_select_none"):
            st.session_state["batch_selected"] = []
        chosen = st.multiselect("분석할 파일 (제거하면 분석에서 제외)", list(range(len(uploaded))),
                                key="batch_selected", format_func=lambda i: f"{i + 1}. {uploaded[i][0]}")
        st.caption(f"업로드 {len(uploaded)}개 · 분석 선택 {len(chosen)}개 · 제외 {len(uploaded) - len(chosen)}개")
    else:
        chosen = []
    items = [uploaded[i] for i in sorted(chosen)]
    p_raw = p_up.getvalue() if p_up is not None else None
    context = (signature, sorted(chosen), p_raw, p_path, cov, db, max_files, max_file_mb, max_total_mb)
    if context != st.session_state.get("batch_input_context"):
        _invalidate_inputs()
        st.session_state["batch_input_context"] = context

    if do_scan:
        for k in ("batch_scan", "batch", "batch_items"):
            st.session_state.pop(k, None)
        if not items or not (p_raw or p_path):
            st.error("파일(또는 폴더)과 profile을 지정하세요.")
        else:
            limits = {"max_files": int(max_files), "max_file_bytes": int(max_file_mb) * 2**20,
                      "max_total_bytes": int(max_total_mb) * 2**20}
            try:
                with tempfile.TemporaryDirectory() as d:
                    scanned = B.scan(items, _with_profile(d, p_raw, p_path), limits, coverage_path=cov or None)
            except (ConfigInvalid, OSError) as e:
                _input_error(e)
            else:   # inputs are frozen here: run_batch refuses a profile/sidecar/file that differs from this list
                st.session_state.update(batch_items=items, batch_scan=scanned, batch_profile_raw=p_raw,
                                        batch_profile=p_path, batch_cov=cov or None, batch_db=db or None)

    scanned = st.session_state.get("batch_scan")
    if not scanned:
        st.info("왼쪽에서 여러 파일 또는 폴더와 profile을 지정한 뒤 '입력 목록 확인'을 누르세요.")
        return
    st.markdown("#### 1. 입력 목록 (분석 전)")
    st.write(scanned["status_counts"])
    st.dataframe(pd.DataFrame([{"#": e["index"], "상대 경로": e["rel_path"], "크기(B)": e["size"], "상태": e["status"],
                                "사유": e["reason"], "중복 대상": e["duplicate_of"], "lot": e["meta"]["lot"],
                                "wafer": e["meta"]["wafer"], "job": e["meta"]["job"], "parser": e["parser"],
                                "adapter": e["adapter"], "profile": e["profile_id"], "sha256": e["sha256"][:12]}
                               for e in scanned["entries"]]).astype(str), key="batch_scan_table")
    st.caption("None = 해당 없음(사유·중복 대상 없음) 또는 값 없음(KLARF 헤더에 lot/wafer 없음, job 필드는 읽지 않음, "
               "파싱 전 제외된 파일의 parser).")

    if st.button("일괄 분석 실행", key="batch_run_btn"):
        st.session_state.pop("batch", None)
        bar = st.progress(0.0, text="시작")

        def progress(n, total, name):
            bar.progress(n / max(total, 1), text=f"{n}/{total} 처리 중: {name}")
        try:
            with tempfile.TemporaryDirectory() as d:
                profile_path = _with_profile(d, st.session_state["batch_profile_raw"], st.session_state["batch_profile"])
                if hashlib.sha256(Path(profile_path).read_bytes()).hexdigest() != scanned["profile_sha256"]:
                    scanned = B.scan(st.session_state["batch_items"], profile_path, scanned["limits"],
                                     coverage_path=st.session_state["batch_cov"])
                    st.session_state["batch_scan"] = scanned
                    st.info("Profile 파일 변경을 감지하여 최신 내용으로 입력 목록을 재검증했습니다.")
                b = B.run_batch(st.session_state["batch_items"], scanned,
                                profile_path,
                                coverage_path=st.session_state["batch_cov"], db=st.session_state["batch_db"],
                                progress=progress)
        except (ConfigInvalid, OSError) as e:
            _input_error(e)
            return
        st.session_state["batch"] = b
        bar.progress(1.0, text="완료")
        st.rerun()  # show the refreshed preflight table together with the new result

    b = st.session_state.get("batch")
    if not b:
        return
    _results(b)


def _results(b):
    cfg = b["config"]
    ov = B.overview(b)
    st.markdown("#### 2. Batch 개요 (분석 시점에 고정)")
    st.caption(f"batch {cfg['batch_id'][:12]}… · profile {cfg['profile_id']} · code {cfg['code_version']} · "
               f"adapter {cfg['adapter']} · coverage sidecar {'있음' if cfg['coverage_sidecar_sha256'] else '없음(미상)'} · "
               f"wafer 반경 {cfg['wafer_radius_mm']} mm · 좌표 mm, 노치 6시 기준 · coverage sidecar는 batch 전체 공통 선언")
    cols = st.columns(6)
    for c, (k, label) in zip(cols, [("files_uploaded", "업로드 파일"), ("analysis_units", "분석 단위"),
                                    ("succeeded", "성공"), ("failed", "실패"), ("held", "보류"),
                                    ("total_included_defects", "포함 결함 합")]):
        c.metric(label, "-" if ov[k] is None else ov[k])     # "-" = not computed (nothing analysed), not 0
    for k, why in ov["null_reasons"].items():
        st.caption(f"{k} 계산 불가: {why}")
    st.caption(f"제외 {ov['excluded']} · 배치 내 중복 {ov['duplicates_in_batch']} · 저장 결과 재사용 {ov['reused_from_store']} · "
               f"고유 wafer(KLARF 헤더 값, 미검증) {ov['unique_wafers_from_header_unverified']} · wafer ID 미상 단위 {ov['units_with_unknown_wafer_id']}")

    con = store.connect(st.session_state["batch_db"]) if st.session_state.get("batch_db") else None
    try:
        rows = B.unit_rows(b, con)
    finally:
        if con:
            con.close()
    df = pd.DataFrame(rows)

    # still part of section 2 (overview): counts come from the same candidate_types as the unit table
    cc = B.candidate_type_counts(rows)
    st.markdown("**candidate_types별 분석 단위 수·비율**")
    st.dataframe(pd.DataFrame([{"코드": r["type"], "유형": r["label"], "단위 수": r["units"],
                                "비율(%)": "-" if r["percent"] is None else f'{r["percent"]:.1f}'}
                               for r in cc["rows"]]), hide_index=True, key="batch_type_counts")
    st.caption(f'분모 = 분석 단위 {cc["denominator_units"]}개(배치 내 중복 파일은 같은 단위라 다시 세지 않음). '
               "한 단위가 여러 유형을 가질 수 있어 합이 100%를 넘을 수 있습니다."
               + (f' 비율 계산 불가: {cc["reason"]}' if cc["reason"] else ""))

    st.markdown("#### 3. 분석 단위별 요약")
    f1, f2, f3, f4 = st.columns(4)
    statuses = f1.multiselect("상태", sorted(df["status"].unique()), key="flt_status")
    types = f2.multiselect("후보 유형", list(B.TYPES) + list(B.EQUIP_TYPES), key="flt_type",
                           format_func=lambda t: f"{t} ({B.TYPE_LABELS.get(t, t)})")
    direc = f3.text_input("주요 방향(시) 포함", key="flt_dir")
    meta = f4.text_input("lot/wafer/경로 포함", key="flt_meta")
    view = df
    if statuses:
        view = view[view["status"].isin(statuses)]
    if types and "candidate_types" in view:
        view = view[view["candidate_types"].fillna("").apply(lambda s: any(t in s.split(",") for t in types))]
    if direc and "main_direction" in view:
        view = view[view["main_direction"].fillna("").apply(lambda s: direc in s.split(","))]
    if meta:
        view = view[view[["rel_path", "lot", "wafer"]].astype(str).apply(lambda r: meta in " ".join(r), axis=1)]
    st.caption(f"표시 {len(view)} / 전체 {len(df)} 행 (필터는 화면만 바꾸며 batch 결과·총수는 그대로)")
    st.caption("None = 계산 불가(not computable) 또는 해당 없음(not applicable) · 0 = 실제 0. "
               "셀별 사유는 null_reasons 열(JSON)에 있습니다.")
    st.dataframe(view.astype(str), key="batch_unit_table")
    st.download_button("필터된 표 CSV(화면 기준)", view.to_csv(index=False), file_name="batch_filtered_view.csv",
                       key="dl_filtered")

    analysed = [r["index"] for r in rows if r["index"] in b["units"]]
    if analysed:
        pick = st.selectbox("상세 조회할 분석 단위", analysed, key="batch_pick",
                            format_func=lambda i: next(r["rel_path"] for r in rows if r["index"] == i))
        st.button("상세 맵·검토 화면 열기", key="batch_open", on_click=_open_detail,
                  args=(pick, next(r.get("candidate_types") for r in rows if r["index"] == pick)))

    st.markdown("#### 4. 유형별 요약")
    st.caption("유형은 서로 겹칠 수 있어 합이 분석 단위 수와 같지 않습니다. 실패·보류 파일은 '평가 안 됨'이며 '유형 없음'이 아닙니다. "
               "candidate는 보정 전 후보, matched는 보정된 규칙의 판정입니다.")
    st.dataframe(pd.DataFrame(B.type_summary(b)).astype(str), key="batch_type_table")
    st.markdown("**면적 보정 밀도(비교 가능 그룹별 sum(count)/sum(유효 면적))** — None이면 reason 열에 계산 불가 사유")
    st.dataframe(pd.DataFrame(B.batch_density(b)).astype(str), key="batch_density_table")
    st.markdown("**원본 bin 합계(profile·adapter 그룹별)**")
    st.dataframe(pd.DataFrame(B.bin_totals_by_group(b)).astype(str), key="batch_bins_table")

    st.markdown("#### 5. 맵 갤러리")
    st.caption(f"모든 맵은 같은 기준(표준 좌표 mm, +X 오른쪽 +Y 위, 노치 6시; 노치 미상 맵은 노치 표시 없음). "
               f"맵당 최대 {MAX_POINTS_PER_THUMB}점만 표시하며 통계에는 영향이 없습니다.")
    idx = list(b["units"])
    pages = max(1, -(-len(idx) // GALLERY_PAGE))
    page = _pager(pages)
    sub = idx[(page - 1) * GALLERY_PAGE: page * GALLERY_PAGE]
    st.caption("후보 코드: " + " · ".join(f"{t}={B.TYPE_LABELS[t]}" for t in (*B.TYPES, *B.EQUIP_TYPES))
               + ". equip_*는 같은 검사 설비(InspectionStationID)에서 step과 무관하게 "
               + f"{(cfg.get('equipment_signature') or {}).get('min_wafers', '?')}장 이상 반복된 후보이며 "
               + "설비 원인 확정이 아닙니다. 근거·판정 불가 사유는 단위 표의 equipment_signature_*, defect_volume_* 열.")
    grid = st.columns(3)
    # same candidate_types as section 3 (unit_rows), joined on the entry index - never recomputed here
    types_by_index = {r["index"]: r.get("candidate_types") for r in rows}
    for k, i in enumerate(sub):
        e = next(x for x in b["entries"] if x["index"] == i)
        fig, shown, total = _thumb(b["units"][i], f"#{i} {e['rel_path']} · 후보: {_types_label(types_by_index.get(i))}",
                                   b["config"]["wafer_radius_mm"])
        with grid[k % 3]:
            st.plotly_chart(fig, width="stretch", key=f"thumb_{i}")
            if shown < total:
                st.caption(f"표시 {shown}/{total}점")

    st.markdown("#### 6. 다운로드 (고정 batch 기준)")
    con = store.connect(st.session_state["batch_db"]) if st.session_state.get("batch_db") else None
    try:
        st.download_button("전체 요약 CSV", B.summary_csv(b, con), file_name="batch_summary.csv", key="dl_summary")
        st.download_button("유형별 요약 CSV", B.type_csv(b), file_name="batch_type_summary.csv", key="dl_types")
        st.download_button("개별 결과 + manifest ZIP", B.export_zip(b, con), file_name="batch_results.zip",
                           key="dl_zip")
    finally:
        if con:
            con.close()
    st.caption("검토(review) 열은 다운로드 시점의 저장소 값이며, 예측 결과와 별도 열로 구분됩니다.")
