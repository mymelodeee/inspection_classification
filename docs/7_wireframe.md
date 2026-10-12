# 7. 와이어프레임

- 기준: 현재 Streamlit 화면(`wafer/app.py`, `wafer/batch_ui.py`, `wafer/ui_inputs.py`). 2026-10-11.
- 앱은 화면이 하나이며 단일/다중 모드 구분이 없다. **목록 화면**(입력→일괄 분석 결과)과 **상세 화면**(한 분석 단위) 두 상태를 오간다.
- 아래 `"…"` 라벨과 `[key]`는 코드의 실제 문자열·위젯 key다. 화면 테스트(AppTest·Edge E2E)가 이 값으로 위젯을 찾으므로 바꿀 때는 테스트와 이 문서를 함께 고친다.
- 표시 규칙(빈 칸·`-`·색·용어)은 [8_style_guide.md](8_style_guide.md). 화면 표의 계산 불가 값은 `None`으로 두고 사유를 reason/null_reasons 열·캡션에 함께 표시한다(R-05 결정).

## 1. 공통 틀

```text
┌────────────────────────────┬──────────────────────────────────────────────────────────────┐
│ 사이드바: 분석 입력          │ Wafer inspection map                                           │
│ (목록·상세 모두 유지)        │ 합성 adapter 기준 개발 단계입니다 … (docs/9_TBD.md)              │
│                            │ ─────────────────────────────────────────────────────────── │
│                            │  목록 화면(2절) 또는 상세 화면(3절)                              │
└────────────────────────────┴──────────────────────────────────────────────────────────────┘
```

## 2. 사이드바 — 분석 입력

```text
분석 입력
┌ "여러 파일 선택" [batch_files(_epoch)]        파일 여러 개 드래그/선택
┌ "폴더 선택(하위 폴더 포함)" [batch_folder(_epoch)]  폴더 업로드(상대 경로 유지)
┌ "또는 KLARF 경로 (한 줄에 하나)" [batch_paths]   서버 파일 경로, 여러 줄
[ 업로드 전체 삭제 ] [batch_clear]
┌ "Profile (YAML)" [batch_profile_up]          업로드가 경로보다 우선
┌ "또는 profile 경로" [batch_profile_path]      기본: tests/profiles/dummy_die_local_test_profile.yaml
                                               (실제 위젯 값은 이 파일의 절대 경로, ui_inputs.DEFAULT_PROFILE)
   (비우면 기본 경로로 복원) · 도움말 문구
┌ "coverage sidecar 경로 (선택, 없으면 coverage 미상)" [batch_coverage]
┌ "SQLite 저장 경로 (선택, 검토·재사용에 필요)" [batch_db_path]
▸ 입력 상한  (펼침)
    "최대 파일 수" [lim_files] 500 · "파일당 최대 MB" [lim_file] 50 · "총 최대 MB" [lim_total] 300
[ 입력 목록 확인 ] [batch_scan_btn]
```

- 상세 화면에서는 사이드바 아래에 "상세보기는 분석 당시의 결과입니다 …" 안내가 나온다. 입력을 바꿔도 상세 결과는 그대로이며, 목록으로 돌아가 다시 확인·실행해야 반영된다.
- 업로드·선택·profile·coverage·DB·상한 중 하나라도 바뀌면 이전 입력 목록과 결과가 사라진다.

## 3. 목록 화면

### 3.1 입력 대기·파일 선택

```text
파일 분석
 파일 1개 또는 여러 개를 같은 방식으로 분석합니다 …
 업로드한 파일은 서버 메모리에서만 처리 … lot/wafer는 KLARF 헤더 값(검증 전, TBD T-26) …

[ 전체 선택 ][batch_select_all]   [ 전체 제외 ][batch_select_none]
"분석할 파일 (제거하면 분석에서 제외)" [batch_selected]
  [1. F01_counts.klarf ×] [2. ring.klarf ×] [3. line.klarf ×] …
 업로드 3개 · 분석 선택 3개 · 제외 0개

ⓘ 왼쪽에서 여러 파일 또는 폴더와 profile을 지정한 뒤 '입력 목록 확인'을 누르세요.
```

오류 표시: 파일·profile 미지정 → "파일(또는 폴더)과 profile을 지정하세요." / `CONFIG_INVALID: <keys> <reason> <message>` / `INPUT_NOT_FOUND: <경로>`.

### 3.2 입력 목록(분석 전)

```text
#### 1. 입력 목록 (분석 전)
{ready: 11, excluded: 1, invalid_input: 1}
┌──┬──────────────┬──────┬──────┬──────┬────────┬─────┬──────┬───┬──────┬───────┬───────┬────────┐
│# │상대 경로      │크기(B)│상태   │사유   │중복 대상│lot  │wafer │job│parser│adapter│profile│sha256  │ [batch_scan_table]
└──┴──────────────┴──────┴──────┴──────┴────────┴─────┴──────┴───┴──────┴───────┴───────┴────────┘
[ 일괄 분석 실행 ] [batch_run_btn]
 ▓▓▓▓▓▓░░░░  6/11 처리 중: ring.klarf          (진행률)
 ⓘ Profile 파일 변경을 감지하여 최신 내용으로 입력 목록을 재검증했습니다.   (경로 YAML이 바뀐 경우)
```

### 3.3 Batch 결과

```text
#### 2. Batch 개요 (분석 시점에 고정)
 batch 1a2b3c… · profile … · code … · adapter … · coverage sidecar 있음/없음(미상) · wafer 반경 150 mm · …
┌업로드 파일┐┌분석 단위┐┌성공┐┌실패┐┌보류┐┌포함 결함 합┐     (계산 불가면 "-")
│   13     ││   13    ││ 13 ││ 0  ││ 0  ││   1412     │
 (포함 결함 합이 "-"이면) total_included_defects 계산 불가: not computable: no analysed unit
 제외 0 · 배치 내 중복 0 · 저장 결과 재사용 0 · 고유 wafer(KLARF 헤더 값, 미검증) 13 · wafer ID 미상 단위 0

**candidate_types별 분석 단위 수·비율**   [batch_type_counts]
┌코드│유형│단위 수│비율(%)┐   ring 환형 3 23.1 · line 일자형 4 30.8 · … · equip_* · inspection_abort_suspect · excess_defect · (none) 후보 없음
 분모 = 분석 단위 N개(배치 내 중복 파일은 다시 세지 않음). 한 단위가 여러 유형을 가질 수 있어 합이 100%를 넘을 수 있음. 분석 단위 0이면 비율 "-" + 사유

#### 3. 분석 단위별 요약
 "상태"[flt_status]  "후보 유형"[flt_type](코드 + 한국어, equip_* 포함)  "주요 방향(시) 포함"[flt_dir]  "lot/wafer/경로 포함"[flt_meta]
 표시 13 / 전체 13 행 (필터는 화면만 바꾸며 batch 결과·총수는 그대로)
 None = 계산 불가(not computable) 또는 해당 없음(not applicable) · 0 = 실제 0. 셀별 사유는 null_reasons 열(JSON)
┌index│rel_path│lot│wafer│job│status│candidate_types│reason│…│equipment_id│step_id│equipment_signature_*│defect_volume_*│…│n_included│…┐ [batch_unit_table]
[ 필터된 표 CSV(화면 기준) ] [dl_filtered]
"상세 조회할 분석 단위" [batch_pick] ▾ F01_counts.klarf     [ 상세 맵·검토 화면 열기 ] [batch_open]

#### 4. 유형별 요약
 유형은 서로 겹칠 수 있어 … 실패·보류 파일은 '평가 안 됨' … candidate는 보정 전 후보 …
┌type│candidate│matched│no_match│insufficient_data│disabled│evaluable_units│…┐ [batch_type_table]
**면적 보정 밀도(… sum(count)/sum(유효 면적))** — None이면 reason 열에 계산 불가 사유   [batch_density_table]
**원본 bin 합계(profile·adapter 그룹별)**                       [batch_bins_table]

#### 5. 맵 갤러리
 모든 맵은 같은 기준(표준 좌표 mm, +X 오른쪽 +Y 위, 노치 6시 …). 맵당 최대 2000점 …
 후보 코드: ring=환형 · line=일자형 · local=몰림형 · lift_pin=삼발이 · equip_ring=설비 반복 환형 · … (범례)
[<<][<][1][2][3]…[>][>>]   [gallery_page_first|prev|n{N}|next|last]  현재 페이지는 강조·비활성, 범위 밖 화살표 비활성, 번호는 현재 주변 최대 9개
 페이지 1 / 4
┌──────────┐┌──────────┐┌──────────┐
│#0 name · 후보: ring, equip_ring││#1 … · 후보: 없음││#2 … · 후보: -│  3열 × 최대 4행(페이지당 12)
    제목의 후보 = 3절 단위 표 candidate_types(같은 index), 여러 개는 ", ", 빈 값 "없음", 값 없음(이전 자료) "-"
│  ( ∘ ∘ ) ││  ( ◯ )   ││  ( / )   │   원 = profile 반경, ▲ = 노치(정합된 경우만)
│    ▲     ││    ▲     ││    ▲     │   [thumb_<index>]
└──────────┘└──────────┘└──────────┘
 표시 1767/5300점   (축소된 경우만: 간격 ceil(N/2000)로 추출해 2000점 이하)

#### 6. 다운로드 (고정 batch 기준)
[ 전체 요약 CSV ][dl_summary]  [ 유형별 요약 CSV ][dl_types]  [ 개별 결과 + manifest ZIP ][dl_zip]
 검토(review) 열은 다운로드 시점의 저장소 값이며, 예측 결과와 별도 열로 구분됩니다.
```

## 4. 상세 화면(분석 단위 1개)

목록의 "상세 맵·검토 화면 열기"로만 들어온다(성공한 단위만 선택 가능).

```text
[ ← 분석 목록으로 돌아가기 ] [back_to_batch]
파일 상세보기
상태
┌job_status┐┌data_quality_status┐┌exit code┐
│succeeded ││ valid             ││    0    │
 입력: lotA/w1/F01_counts.klarf
 **candidate_types:** ring, local (환형, 몰림형)      (단위 표와 같은 값, 이전 세션은 "-")
 source_sha256 1a2b… · profile … · schema result-0.2 · code … · adapter … · coverage unknown · 단위 mm
 pattern_summary: no_clear_pattern

개수 (원본 전체, 필터와 무관)
┌parsed┐┌included┐┌excluded┐┌center┐        (center 계산 불가면 "-" + "center 계산 불가: <사유>" 캡션)
▸ 계산 불가 항목 N개와 사유 (값은 None 그대로)    펼치면 field | reason 표(결과 null_reasons)
"지도에 표시할 bin (표시 범위만 바뀜)" [bin_filter]  [1 ×][2 ×][3 ×]
"강조할 signature group" [overlay] ▾ (없음)
"지도 색 구분" [map_color] (•) bin  ( ) 후보 유형(candidate_types)
   후보 유형 모드: 저장된 support 기준 ring 빨강·line 파랑·local 초록·lift_pin 보라, 두 유형 이상 겹친 점 = 주황 마름모 "(겹침)",
   후보 아님 = 회색 작은 점, 같은 검사 설비 반복 유형은 범례에 "·설비 반복". bin 필터는 두 모드 모두 적용
┌──────────────────────────────┐
│          ·                    │  회색 원 = wafer(profile 반경)
│     ·    +    · ·             │  bin별 색 점, 강조 group은 빈 원 테두리
│          ·                    │  ▲ "notch (6시)" — 노치 정합된 경우만
│          ▲                    │
└──────────────────────────────┘
 표시 중 8 / 포함 8 (bin 필터는 집계값을 바꾸지 않음) [· wafer 반경 미설정 …] [· 노치 위치 미상 …]

bin × 시계방향            [bin_sector_table]   또는 ⚠ 시계방향 집계 계산 불가 — <status>: <reason>
공간 집계 (None = 계산 불가 또는 해당 없음, 사유는 reason 열 · 0 = 실제 0)   table|key|count|area_mm2|density_per_mm2|reason
판정 상태                 feature|status|reason / detail  (ring, line, lift_pin, clark_evans, radial_density)
 DBSCAN 군집 n개 · noise m건(총수에 포함) · 후보(candidate)는 형상 근거이며 원인 확정이 아닙니다.

검토   (DB 미지정 시: "검토를 저장하려면 SQLite 저장 경로를 지정해 분석하세요.")
┌ form ─────────────────────────────────────────────┐
│ "action" [rv_action] ▾ confirm|correct_label|merge_clusters|split_cluster|defer │
│ "payload (JSON)" [rv_payload]  {}                 │
│ "사유" [rv_reason]   "검토자" [rv_reviewer]          │
│ [ 검토 저장 ] [rv_submit]                          │
└───────────────────────────────────────────────────┘
 revision n 저장 (예측 원본은 변경되지 않음) | 검토 거부: <사유>
 analysis_key 1a2b… · review_status: deferred
 현재 군집(검토 반영): {…}   + revision 목록 표

내보내기
[ JSON 다운로드 ][dl_json]  [ CSV(zip) 다운로드 ][dl_csv]
```

## 5. 화면 원칙과 현재 한계

| 원칙 | 적용 |
|---|---|
| 필터·표시 축소는 계산값을 바꾸지 않는다 | bin 필터, 단위 표 필터, 갤러리 2000점 상한 |
| 물리값은 profile에서만 그린다 | wafer 원 반경, 노치 위치. 데이터로 추정하지 않음 |
| 노치 미상은 화면에서 숨기지 않는다 | 노치 표시 생략 + "노치 위치 미상: 화면 방향은 물리 방향이 아님" |
| 후보는 원인이 아니다 | 판정 상태 아래 고정 문구 |

| 한계 | 관련 |
|---|---|
| 과거 batch·분석 목록 조회 화면 없음 | FR-ST-03, E19 |
| 원본 장비 화면 대조 overlay 없음 | 실행계획 10.1 ①, T-25 |
| 다운로드는 화면을 다시 그릴 때마다 생성(대량 파일 시 느림) | T-27 ⑨ |
| 인증·다중 사용자 없음 | T-24, T-25 |
