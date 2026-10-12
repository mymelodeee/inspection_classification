# 8. 스타일 가이드 — 표시·용어·문서 규약

- 범위: 이 앱은 Streamlit 기본 테마를 그대로 쓰며 별도 CSS·색 체계가 없다. 따라서 이 문서는 시각 디자인보다 **값을 어떻게 보여 주고 어떤 말로 설명하는지**를 정한다. 잘못 표시하면 분석 계약(null≠0, 후보≠원인)을 어기게 되는 부분이 대상이다.
- 기준: `wafer/app.py`, `wafer/batch_ui.py`, `wafer/report.py`, `wafer/batch.py`의 현재 표시 방식(2026-10-11). 화면 배치는 [7_wireframe.md](7_wireframe.md).

## 1. 값 표시

| 상황 | 화면 metric | 표·CSV | JSON |
|---|---|---|---|
| 계산 불가·해당 없음·비활성 | `-` + 사유 캡션 | 화면 표: `None` + 사유 열(`reason`/`null_reasons`). CSV: 빈 칸 + 사유 열 | `null` + 사유(`null_reasons`·`reason`·`calc_status`) |
| 실제 0 | `0` | `0` | `0` |
| 비율 | 0~1 소수(퍼센트 아님) + 분모 열 | 동일 | 동일 |
| 해시 | 앞 12자 + `…` | 전체(manifest) 또는 앞 12자(입력 목록) | 전체 |

- 0을 "없음"·"정상"으로 바꿔 쓰지 않는다. null을 0으로 채우지 않는다.
- 단위는 값 옆이나 열 이름에 붙인다: 길이 `_mm`, 면적 `_mm2`, 밀도 `_per_mm2`, 각도 `_deg`. 화면 caption에 "단위 mm"를 둔다.
- 시계방향은 `1`~`12`(시)로 표기하고 center는 따로 표시한다. 주요 방향이 여러 시각에서 같으면 `3,9`처럼 모두 표시한다.
- bin은 `CLASSNUMBER` 문자열(`"1"`, `"2"` …), 0은 `unknown`. "B1" 같은 다른 표기를 섞지 않는다.

## 2. 상태·판정 용어

| 내부 값 | 화면·문서 표현 | 쓰지 않는 표현 |
|---|---|---|
| `candidate` | 후보(보정 전) | 확정, 불량, 원인 |
| `matched` | 일치(보정된 규칙) | 원인 확정 |
| `no_match` | 해당 시그니처 미관측 | 정상, 양호 |
| `insufficient_data` | 자료 부족으로 보류 | 없음, 0 |
| `disabled` | 비활성(설정에서 끔) | 통과, 정상 |
| `no_detected_defect` | 결함 0건 | 정상 웨이퍼 |
| `no_clear_pattern` | 뚜렷한 패턴 후보 없음 | 정상, 무결함 |
| `failed`/`invalid_input` | 실패·평가 안 됨 | 유형 없음, 0건 |
| `held` | 보류(지원 밖 좌표 규약) | 실패한 입력, 불량 파일 |

- 형상·template 일치를 설명할 때는 "…와 일치하는 후보가 관찰됨"까지만 쓴다. "lift pin이 원인" 같은 원인 단정을 쓰지 않는다.
- 점수(0~100)·등급(정상/주의/위험)을 만들거나 표시하지 않는다(T-27).
- 헤더에서 읽은 lot/wafer는 "KLARF 헤더 값, 미검증"으로 표시한다.
- 합성 adapter·시험 profile로 얻은 결과임을 화면 상단 caption에 계속 둔다.

## 3. 지도(wafer map)

| 요소 | 상세 화면 | 갤러리 썸네일 |
|---|---|---|
| 좌표계 | 표준 좌표(mm, +X 오른쪽, +Y 위, 노치 6시), 축 비율 1:1(`scaleanchor`) | 동일 |
| wafer 외곽 | profile `wafer_radius_mm` 원, 회색 `#888` | 회색 `#999` |
| 노치 | (0, −R)의 `triangle-up` 마커, 크기 12, "notch (6시)" — **노치 정합된 경우만** | 크기 9, 정합된 경우만 |
| 결함 점 | bin별 trace(Plotly 기본 색 순서), 크기 7, hover에 defect ID. 또는 후보 유형 모드: ring `#d62728`·line `#1f77b4`·local `#2ca02c`·lift_pin `#9467bd`, 겹침 `#ff7f0e` 마름모, 후보 아님 `#bbbbbb` 크기 5 | 크기 4 |
| group 강조 | 빈 원(`circle-open`) 크기 13, 선 두께 2 | 없음 |
| 크기 | 높이 560 | 높이 260, 3열 |

- wafer 반경이 없으면 외곽선·노치를 그리지 않고 그 사실을 caption으로 알린다. 데이터 범위로 반경을 추정하지 않는다.
- 노치 미상이면 "노치 위치 미상: 화면 방향은 물리 방향이 아님"을 caption에 붙인다.
- 화면용 점 축소는 갤러리에서만 쓰고(맵당 최대 2000점), 축소했을 때 "표시 n/N점"을 붙인다. 통계는 항상 전체 점으로 계산한다.

## 4. 화면 문구와 위젯

- 화면 문구는 한국어, 데이터 키·열 이름은 영어 snake_case(코드 값 그대로)다. 표 제목에는 "None = 계산 불가 또는 해당 없음, 사유는 reason 열 · 0 = 실제 0"처럼 해석 규칙을 함께 적는다. 화면 표의 계산 불가 값은 `None`으로 두고(2026-10-11 결정, R-05), 제목·캡션에 "None = 계산 불가 또는 해당 없음"과 사유 열 위치를 적는다.
- 필터·선택 위젯 옆에는 "표시만 바뀜", "batch 결과·총수는 그대로" 같은 범위 문구를 둔다.
- 위젯 key 접두사: `batch_`(입력·일괄), `lim_`(상한), `flt_`(단위 표 필터), `dl_`(다운로드), `rv_`(검토), `thumb_`(갤러리). 그 외 단독 key: `gallery_page`, `back_to_batch`, `bin_filter`, `overlay`, `bin_sector_table`. key와 라벨은 테스트가 쓰므로 바꾸면 [7_wireframe.md](7_wireframe.md)와 테스트를 함께 고친다.
- 오류 문구 형식: `CONFIG_INVALID: <키> <사유> <메시지>`, `INPUT_NOT_FOUND: <경로>`, 상세 화면은 `<error>: <detail> <keys>`. 원본 KLARF 내용을 오류 문구에 넣지 않는다.

## 5. 내보내기 파일

- CSV: UTF-8, 첫 행 헤더, 빈 칸 = null, `0` = 실제 0. 개별 결과 CSV의 열 이름은 JSON 키와 같고, 일괄 요약 CSV는 유형 접두사를 붙인 평탄화 이름이다(예: JSON `ring.measurement.center_radius_mm` → `ring_radius_mm`).
- JSON: UTF-8(`ensure_ascii=False`), 들여쓰기 2. 내부 전용 키(`_`로 시작)는 내보내지 않는다.
- 파일 이름: 상세 `result.json`, `result_csv.zip`; 일괄 `batch_summary.csv`, `batch_type_summary.csv`, `batch_results.zip`, `batch_filtered_view.csv`. ZIP 안 단위 폴더는 `units/<4자리 위치>_<정리된 파일명>/`.
- provenance(입력·profile hash, 버전)와 null 규약은 개별 CSV 묶음의 `manifest.json`과 일괄 ZIP의 `batch_manifest.json`에 있다. 상세 `result.json`에는 provenance만 있고, 요약 CSV·필터 CSV 단독 파일에는 둘 다 없다. 단독 CSV를 넘길 때는 manifest를 함께 넘긴다.

## 6. 문서 작성 규약

1. 한국어로 쓰고, 코드 식별자·키·명령은 백틱으로 그대로 쓴다.
2. 경로는 **저장소 루트 기준 상대 경로**로만 쓴다. 사용자 홈·설치 위치·Python 절대 경로를 쓰지 않는다. `docs/` 안 문서끼리는 상대 링크(`[9_TBD.md](9_TBD.md)`)를 쓴다.
3. 날짜는 `YYYY-MM-DD` 절대 날짜로 쓴다. 결정 사항에는 결정일을 붙인다.
4. 미확정 정의는 추측해 채우지 않고 `T-xx` ID로 [9_TBD.md](9_TBD.md)를 가리킨다.
5. 시험 상태는 `PASS / FAIL / NOT_RUN / BLOCKED / N/A`만 쓰고, 합성 자료 결과는 `PASS(합성)`으로 구분한다. 문서 검토를 실행 시험 통과로 쓰지 않는다.
6. 시험용 값(시험 profile, 합성 fixture)을 설명할 때는 "시험 전용"을 명시한다.
7. 코드와 문서가 다르면 요구사항을 코드에 맞춰 바꾸지 않는다. 원래 계약을 코드가 어기면 코드를, 승인된 변경이면 문서·시나리오를 고친다([3_user_scenarios.md](3_user_scenarios.md) 3부).
8. 코드 주석은 영어, 주변 코드의 밀도에 맞춘다. 결과에 영향을 주는 모듈(`app.py` 외 `wafer/*.py`)은 주석 수정도 `code_version`을 바꾸므로, 문서 링크 갱신 같은 이유로 주석을 고치지 않는다(T-28).
