# 3. 사용자 시나리오와 시험 추적표

- 1부: 사용자가 실제로 하는 일(US)과 기대 결과. 화면 배치는 [7_wireframe.md](7_wireframe.md), 기능 ID는 [2_PRD.md](2_PRD.md).
- 2부: 시험 시나리오(E01~E24와 하위 case) ↔ **현재 테스트 함수** ↔ 상태 추적표. 각 시나리오의 상세 입력·통과 기준은 [6_execution_plan.md](6_execution_plan.md) 19절이 원본이다.
- 이 문서의 추적표는 **항상 최신 코드에 맞춘다**(3부 유지 규칙).

---

## 1부. 사용자 시나리오

모든 예시 경로는 저장소 루트 기준 상대 경로다. 화면은 `python -m streamlit run wafer/app.py`로 연다.

### US-01 파일 1개 분석하고 상세 확인

| 항목 | 내용 |
|---|---|
| 사용자 | 공정·검사 엔지니어 |
| 전제 | 기본 profile 경로(`tests/profiles/dummy_die_local_test_profile.yaml`)가 채워져 있다 |
| 흐름 | ① "여러 파일 선택"에 `klarf_dummy_data/klarf/F01_counts.klarf` 업로드 또는 "또는 KLARF 경로"에 입력 → ② **입력 목록 확인** → 상태 `ready` 확인 → ③ **일괄 분석 실행** → ④ 개요·단위 표 확인 → ⑤ **상세 맵·검토 화면 열기** → ⑥ map·bin×시계방향·공간 집계·판정 상태 확인 → ⑦ **← 분석 목록으로 돌아가기** |
| 기대 | 포함 8, bin "1"=3·"2"=3·"3"=2, center 1, 3시 4건. 상세 화면 값 = 일괄 표 값 = CLI JSON 값. bin 표시 필터는 개수를 바꾸지 않는다 |
| 연계 | FR-UI-01·04·06·11, E01, E16, E01-BATCH1 |

### US-02 폴더 일괄 분석과 비교

| 항목 | 내용 |
|---|---|
| 흐름 | "폴더 선택(하위 폴더 포함)"에 `klarf_dummy_data/klarf` 업로드 → 입력 목록 확인 → 일괄 분석 실행 → 개요 → 단위 표 필터(상태·후보 유형·주요 방향·lot/wafer/경로) → 유형별 요약 → 맵 갤러리 |
| 기대 | 13개 단위 성공, 포함 결함 합 1412. 유형별 요약은 candidate/matched/no_match/평가 불가를 따로 세고 유형 간 중첩을 허용한다. 실패·보류 파일은 "평가 안 됨"이지 "유형 없음"이 아니다. 갤러리는 노치 6시 같은 기준으로 그린다 |
| 연계 | FR-UI-07~10, E01-BATCH13, E06-BATCH |

### US-03 일부 파일만 분석·업로드 비우기

| 항목 | 내용 |
|---|---|
| 흐름 | 여러 파일 업로드 → "분석할 파일"에서 일부 해제 또는 **전체 제외**/**전체 선택** → 입력 목록 확인 → 실행. 다시 시작하려면 **업로드 전체 삭제** |
| 기대 | 선택한 파일만 목록·결과·CSV·ZIP·DB에 들어간다. 선택·입력 설정을 바꾸면 이전 목록·결과는 무효화된다. 전체 삭제는 화면의 업로드·결과만 비우고 원본 파일·DB 이력은 지우지 않는다 |
| 연계 | FR-UI-02, E16-BATCH-SELECT |

### US-04 검사 영역(coverage)을 선언하고 밀도 보기

| 항목 | 내용 |
|---|---|
| 흐름 | "coverage sidecar 경로"에 `tests/fixtures/coverage/full_disk_150.json` 입력 → 입력 목록 확인 → 실행 → "면적 보정 밀도" 표, 단위 표 `valid_area_mm2`·`density_per_mm2` 확인 |
| 기대 | F01: 유효 면적 π×150² ≈ 70685.83 mm², 밀도 8/(π×150²). 경로를 비우면 면적·밀도는 빈 칸(null) + `coverage_unknown`. batch 밀도는 같은 그룹 안에서 Σcount/Σarea |
| 주의 | 실제 검사 영역을 모르는 입력에 시험 sidecar를 쓰지 않는다 |
| 연계 | FR-AG-05·06, E11, E10/E11-BATCH |

### US-05 검토 기록 저장과 재조회

| 항목 | 내용 |
|---|---|
| 흐름 | "SQLite 저장 경로"에 `analysis_test.db` 입력 → 분석 → 상세 화면 **검토**에서 action=`defer`, payload=`{"reason_code": "needs_sem_review"}` → **검토 저장** → 같은 입력·profile·coverage·DB로 다시 분석 |
| 기대 | revision 1 저장, `review_status=deferred`. 재분석은 같은 분석 키를 재사용("저장 결과 재사용" 증가)하고 검토 이력을 지우지 않는다. 예측 원본은 바뀌지 않는다 |
| 한계 | 과거 batch·분석 목록 화면은 없다(FR-ST-03). SQLite 조회 도구 또는 같은 입력 재분석으로 확인한다 |
| 연계 | FR-ST-01·02, E17, E19, E19-BATCH |

### US-06 결과 내려받기

| 항목 | 내용 |
|---|---|
| 흐름 | 일괄 화면 6절: 전체 요약 CSV / 유형별 요약 CSV / 개별 결과 + manifest ZIP. 상세 화면: JSON, CSV(zip). 단위 표 위의 "필터된 표 CSV"는 화면 기준 |
| 기대 | 빈 칸=null, "0"=실제 0. ZIP의 `batch_manifest.json`에 입력 hash·상태·사유·중복·버전·범위가 있고, 단위별 `result.json`에 검토 블록이 있다. 중복 행은 원본 값을 반복하므로 합산은 `status=succeeded` 행만 |
| 연계 | FR-OUT-01·02, FR-UI-12, E16, E16-BATCH |

### US-07 CLI로 한 파일 처리

| 항목 | 내용 |
|---|---|
| 흐름 | `python -m wafer.cli klarf_dummy_data/klarf/ring.klarf --profile tests/profiles/dummy_die_local_test_profile.yaml --coverage klarf_dummy_data/synthetic_profile.json --out ring_result.json --csv-dir out/ring --db analysis.db` |
| 기대 | 종료 코드 0, JSON·CSV·manifest 생성, 같은 명령 재실행 시 `store.created=false`. 오류는 traceback 없이 JSON + 종료 코드(2~7) |
| 연계 | FR-CLI-01·02, E01, E17 |

### US-08 profile을 고쳐 다시 분석

| 항목 | 내용 |
|---|---|
| 흐름 | 기본 경로의 YAML을 같은 위치에서 수정·저장 → 같은 화면에서 **일괄 분석 실행** |
| 기대 | 입력 목록 확인 뒤 경로 YAML이 바뀌었으면 화면이 최신 profile로 목록을 다시 검증하고 안내한다. 실행 중에는 검증한 사본만 쓴다. 잘못된 YAML은 `CONFIG_INVALID`로 멈춘다. 결과의 profile hash가 바뀌므로 별도 분석 키로 저장된다 |
| 연계 | FR-UI-03·05, E12-DEFAULT, E18-PROFILE-RELOAD, E17 |

### US-09 문제가 있는 입력

| 입력 | 기대 화면 |
|---|---|
| 손상·잘린 KLARF, 복수 WaferRecord | 목록 `invalid_input` + 사유. 분석 단위·0건 결과를 만들지 않는다 |
| 지원 밖 확장자(`.png`, `.001` 등) | `excluded`(`extension_not_in_input_contract`) |
| profile adapter와 맞지 않는 파일 | `held`(보류), 다른 파일은 계속 처리 |
| 노치 위치 없는 파일 | 성공. 개수·반경은 표시, 시계방향은 "시계방향 집계 계산 불가" 경고 + "계산 불가 항목" 목록에 사유, 노치 표시 없음, 주요 방향 보류 |
| 상한 초과 | `excluded` + `over_max_*` 사유 |
| 없는 profile/sidecar 경로 | `INPUT_NOT_FOUND` 오류, 분석하지 않음 |
| 연계 | E03, E09-MULTI-BATCH, E10, E13, E13-BATCH, E18-BATCH |

### US-10 실제 사내 데이터 도입 (BLOCKED)

실제 export 샘플·장비 명세·사내 정의가 들어오면 입력 계약(파일명·형식·메타데이터·좌표·bin)을 재검증하고 adapter·profile을 추가한다. 절차와 하위 case는 실행계획 5.3·19.3, [9_TBD.md](9_TBD.md) T-26. 합성 시험 통과로 대신하지 않는다.

---

## 2부. 시험 시나리오 추적표

### 2.1 상태 표기

- **PASS(합성)**: 합성 fixture·독립 oracle로 실행해 통과. 실제 장비·분류 성능 증빙이 아니다.
- **NOT_RUN**: 실행하지 않음. **BLOCKED**: 자료·환경·결정 부족. **N/A**: 범위 제외·비활성 기능(근거 기재).
- 상위 E는 필수 하위 case가 모두 통과해야 PASS다. 실제 데이터 하위 case가 BLOCKED인 동안 상위 E는 PASS로 올리지 않는다.
- 테스트 경로는 `tests/` 기준. `e2e`는 `tests/test_e2e_browser.py`(실제 Streamlit 서버 + 시스템 Edge).

### 2.2 E01~E24

| E | 합성 하위 case와 테스트 | 합성 결과 | 상위 판정 | 남은 하위 case(사유) |
|---|---|---|---|---|
| E01 정상 입력·집계 | `test_aggregate_f01.py::test_counts_bins_sectors_center`, `test_ingest_cli.py::test_e01_*`, `test_dummy_klarf18.py::test_t1_*`, `test_dummy_mixed.py::test_03_*`(E01-MIXED38), `test_app.py::test_ui_shows_the_independent_f01_values`, e2e `test_e16_browser_values_match_the_f01_oracle` | PASS(합성) | BLOCKED | 실제 KLARF·화면 대조(T-26) |
| E02 노치·단위·중심·side | `test_geometry.py::test_notch_*`·`test_no_double_rotation_*`, `test_dummy_klarf18.py::test_t2_*`·`test_t3_*` | PASS(합성) | BLOCKED | backside·실제 기준점(T-02, E02-REAL) |
| E03 무검출·한 점·중심점 | `test_ingest_cli.py::test_e03_*`, `test_dummy_klarf18.py::test_t6_empty_list_*`, `test_stats.py::test_clark_evans_not_computed_*`, `test_batch.py::test_06_*`·`test_23_*` | PASS(합성) | BLOCKED | 실제 빈 export(E03-EMPTY-REAL) |
| E04 noise 보존 | `test_phase2_fixtures.py::test_e04_*`, `test_dummy_klarf18.py::test_t8_*` | PASS(합성) | PASS(합성) | — |
| E05 선형·호형·국부 | `test_e05_line_arc.py` 전체, `test_phase2_fixtures.py` ring/arc 측정 | PASS(합성) | BLOCKED | 보정된 임계값·실제 라벨(T-14, T-18) |
| E06 혼합·중첩 | `test_e06_mixed.py` 전체, `test_batch.py::test_07_*`, `test_dummy_mixed.py::test_03_*`(혼합 38 class 개수 보존만, 형상 라벨 N/A) | PASS(합성) | BLOCKED | 보정 임계값, offset·다중 ring(T-19) |
| E07 삼발이 | `test_e07_lift_pin.py` 전체, `test_dummy_klarf18.py::test_t9_*`·`test_e07_up_*` | PASS(합성, 시험 template) | BLOCKED | 사내 template(T-07, T-22) |
| E08 zone·시계 경계 | `test_geometry.py`(구간·band·sector 경계), `test_phase2_fixtures.py::test_e08_*`, `test_aggregate_f01.py::test_zones_match_oracle`, `test_dummy_klarf18.py::test_t4_*`·`test_t5_*`, `test_profile.py::test_same_E1_values_disabled_stays_disabled` | PASS(합성) | BLOCKED | 사내 E1/E2 값(T-06), 허용오차 해석(T-15) |
| E09 bin 누락·동일 좌표·복수 검사 | `test_ingest_cli.py::test_e09_unclassified_bin_preserved`·`test_duplicate_coordinates_and_ids_are_kept`, `test_batch.py::test_18_*`·`test_19_*`, `test_dummy_mixed.py::test_03_*`·`test_03b_*`(E09-MIXED) | PASS(합성, 복수 record는 명시적 실패) | BLOCKED | 복수 inspection 지원(T-09), affected die(T-13) |
| E10 방향·scale 부족 | `test_dummy_klarf18.py::test_e10_up_*`, `test_ingest_cli.py::test_e10_up_*`, `test_app.py::test_e10_up_*`·`test_e16_nullwhy_*`, `test_batch.py::test_09_*`·`test_24_*`, `test_null_reasons.py`(노치 제거 null 사유) | PASS(합성, 노치 미상) | BLOCKED | side·단위·중심 미상 실제 필드(T-02) |
| E11 coverage | `test_stats.py` 전체, `test_dummy_klarf18.py::test_t7_*`, `test_batch.py::test_08_*`·`test_11_*`·`test_22_*`·`test_24_*`(밀도 null 사유), e2e `test_e16_downloads_with_coverage_*`·`test_unified_detail_roundtrip_coverage_sqlite` | PASS(합성, full_disk) | BLOCKED | 비원판 coverage·비검사 sector(T-04) |
| E12 설정 오류·비활성 | `test_profile.py` 전체, `test_ingest_cli.py::test_e12_up_*`, `test_dummy_klarf18.py::test_e12_up_*`·`test_unknown_adapter_id_*` | PASS(합성) | PASS(합성) | 사내 값 확정 시 재실행 |
| E13 손상·미지원·작성 중 | `test_ingest_cli.py::test_e13_*`·`test_bad_*`·`test_non_utf8_*`, `test_dummy_klarf18.py::test_t6_damaged_*`·`test_ambiguous_*`, `test_batch.py::test_05_*`, e2e `test_e13_bad_file_is_shown_as_failed`·`test_batch_edge_mixed_folder_*` | PASS(합성) | NOT_RUN | 작성 중 파일·자동 수집 경로 미구현 |
| E14 검정이 후속을 막지 않음 | `test_ingest_cli.py::test_cli_detect_runs_even_when_randomness_is_insufficient`, `test_profile.py::test_blocking_on_non_significance_is_rejected_c07`, `klarf_dummy_data` uniform_random(P2-02 기록) | PASS(합성) | NOT_RUN | fault-injection 변형, calibration fixture |
| E15 이미지 fallback | — | — | N/A | 이미지 입력 미구현(현재 release 범위 제외, PRD FR-IN-07) |
| E16 채널·export 동일성 | `test_app.py::test_ui_values_match_cli_json`·`test_bin_filter_changes_display_only`, `test_ingest_cli.py::test_csv_*`, `test_dummy_klarf18.py::test_csv_exports_*`, `test_null_reasons.py`(result-0.2 null_reasons), `test_app.py::test_e16_nullwhy_*`, e2e `test_e16_*` | PASS(합성, CLI·UI) | NOT_RUN | 배포 image digest(E22), API는 N/A(미구현) |
| E17 중복 입력·버전 변경 | `test_store.py::test_e17_*`·`test_same_key_*`·`test_cli_key_collision_exit_code`, `test_dummy_klarf18.py::test_sidecar_file_name_does_not_change_the_analysis_key`, `test_batch.py::test_13_*`·`test_16_*`·`test_17_*` | PASS(합성) | PASS(합성) | — |
| E18 실패·재시도·동시 | `test_store.py::test_e18_*`, `test_batch.py::test_12*`·`test_20_*` | PASS(합성, 로컬 스레드) | NOT_RUN | worker 종료 주입·다중 프로세스 |
| E19 검토·병합/분리·재조회 | `test_store.py::test_e19_*`·`test_review_*`, `test_app.py::test_review_*`, e2e `test_e19_*`·`test_unified_detail_roundtrip_coverage_sqlite`, `test_batch.py::test_20_*` | PASS(합성) | NOT_RUN | 저장된 분석 목록 재조회 화면 미구현(FR-ST-03) |
| E20 부하·과도한 입력 | `test_batch.py::test_02_*`(상한 제외) | PASS(합성, 상한 처리만) | BLOCKED | 성능 목표 없음(T-10) |
| E21 실제 blind | — | — | BLOCKED | 내부 blind set·목표(T-10) |
| E22 배포·rollback | — | — | NOT_RUN | 배포 구성 미구현(Phase 4) |
| E23 통계 재현성·오경보 | `test_stats.py::test_clark_evans_reproducible_*`, `test_e06_mixed.py::test_detect_is_disabled_by_default_and_reproducible` | PASS(합성, 재현성) | NOT_RUN | null simulation 오경보율 묶음 |
| E24 후속 기능 | — | — | N/A | ML·repeater·gripper 비활성 |

### 2.3 일괄 분석 하위 case (실행계획 19.4)

| 하위 case | 테스트 | 결과 |
|---|---|---|
| E01-BATCH1 | `test_batch.py::test_16_one_file_batch_equals_single_run_job` | PASS(합성) |
| E01-BATCH13 | `test_batch.py::test_03_*` | PASS(합성) |
| E01-MIXED38 (사용자 요청 2026-10-12, `klarf_dummy_data_mixed` seed 20261012, 생성기 stdlib oracle; C01 C02 C04 C10 C14 C15 C20) | `test_dummy_mixed.py::test_01_*`(MixedWM38 38 class 목록·sha256)·`test_02_*`(생성기 byte 재현)·`test_03_*`(38 파일: n_parsed/included/excluded·bin(unknown 포함)·center·12 sector·제외 ID·defect별 시계·null_reasons) | PASS(합성) |
| E09-MIXED (같은 oracle) | `test_dummy_mixed.py::test_03_*`(CLASSNUMBER 0 → bin "unknown")·`test_03b_*`(동일 위치 1~3건 별도 이벤트 유지)·`test_03c_*`(fixture에 제외·unknown 실재) | PASS(합성) |
| E01-BATCH-MIXED (같은 oracle) | `test_dummy_mixed.py::test_04_*`(폴더 일괄 6 파일: 총 포함 수·bin 합·batch_density sum_count = oracle 합) | PASS(합성) |
| E17-BATCH | `test_batch.py::test_04_*`·`test_15_*`·`test_17_*`, e2e `test_batch_edge_folder_and_multi_file_selection_give_the_same_result` | PASS(합성) |
| E13-BATCH | `test_batch.py::test_01_*`·`test_05_*`, e2e `test_batch_edge_mixed_folder_finishes_the_valid_inputs` | PASS(합성) |
| E03-BATCH | `test_batch.py::test_06_*`·`test_23_*` | PASS(합성) |
| E06-BATCH | `test_batch.py::test_07_*`·`test_19_*` | PASS(합성) |
| E10/E11-BATCH | `test_batch.py::test_08_*`·`test_09_*`·`test_11_*` | PASS(합성) |
| E09-MULTI-BATCH | `test_batch.py::test_18_*` | PASS(합성) |
| E16-BATCH | `test_batch.py::test_14_*`·`test_22_*`, e2e `test_batch_edge_downloads_match_manifest_and_independent_density` | PASS(합성) |
| E19-BATCH | `test_batch.py::test_13_*`·`test_20_*` | PASS(합성) |
| E18-BATCH | `test_batch.py::test_02_*`·`test_12_*`·`test_12b_*`·`test_12c_*`·`test_20_*` | PASS(합성) |
| E16-BATCH-SELECT | e2e `test_batch_selection_clear_and_profile_reload` | PASS(합성) |
| E12-DEFAULT / E18-PROFILE-RELOAD | `test_app.py::test_default_profile_and_single_file_reload`·`test_profile_path_default_is_explicit_and_restored_when_cleared`, e2e `test_batch_selection_clear_and_profile_reload` | PASS(합성) |
| E02-BATCH-COUNT | `test_batch.py::test_21_*`·`test_22_*`·`test_23_*` | PASS(합성) |
| E16-NULLWHY / E10-UP-NULLWHY (승인 2026-10-11: None 유지 + 계산 불가 사유 표기, C15) | `test_null_reasons.py` 전체, `test_batch.py::test_05_*`·`test_23_*`·`test_24_*`, `test_app.py::test_e16_nullwhy_*`, `test_dummy_klarf18.py::test_e10_up_missing_notch_*`, `test_ingest_cli.py::test_csv_distinguishes_*`, e2e `test_e16_browser_values_*`·`test_e16_downloaded_csv_zip_*` | PASS(합성) |
| E06-EQUIP (승인 2026-10-12: 같은 검사 설비 InspectionStationID 반복 후보 equip_ring/line/local, step 무관, min_wafers 3; C11 C14 C17 C20) | `test_equipment_candidates.py::test_a_*`(파일별 코드 불변·접두), `test_d_*`(파일별+설비+과다 동시), `test_f_*`(step 상이 묶음·설비 분리·2장 insufficient_data·필드 없음·노치 제거 시 ring만 비교·위치 상이 불일치). Oracle: 동일 좌표 → 특징 차 0, 노치 UP/LEFT 회전으로 3시→9시·수평→수직, ring 반경 80 vs 148 mm | PASS(합성) |
| E06-EQUIP-PAIRWISE (결정 2026-10-12: "모든 특징이 쌍마다 일치" — 자기 포함 min_wafers 이상 집합의 모든 쌍이 허용오차 이내일 때만 반복; 이전 구현은 star 방식이라 80/84/88에서 84만 표시) | `test_equipment_candidates.py::test_f2_pairwise_rule_on_constructed_ring_radii`(수기 반경 80/84/88 → 반복 없음, 80/84/86/88 → 84·86·88 같은 peers, 80 없음; 순서 무관; 반복 표시 wafer의 peers도 모두 반복), `test_f2_pairwise_rule_through_real_batch_runs_of_scaled_rings`(ring.klarf 좌표 ×1.0/1.05/1.075/1.10 실제 batch 실행, 측정 반경 80k±0.5), `test_f_equipment_grouping_*`(동일 ring 4장: 모든 행 peers = 4장 전체, 최대 집합 확장) | PASS(합성) |
| E16-OVERVIEW-TYPECOUNT (승인 2026-10-12: Batch 개요에 candidate_types별 단위 수·비율(%); 분모 = 분석 단위(succeeded), 중복·실패·제외 미포함, 중첩 허용으로 합 > 100% 가능, 분모 0 → 비율 None + 사유; C14 C15) | `test_equipment_candidates.py::test_overview_type_counts_*`(dummy 13 + 동일 byte 중복 + 손상 파일 → 분모 13, 코드별 수는 type_status 기반 독립 계산; TOOL_L local 3장 + F01 → local 3·equip_local 3·(none) 1 / 4 = 75.0·75.0·25.0, 합 175%; 단위 0 → None + 사유; AppTest 표 `batch_type_counts` 값·"-"·캡션 분모 5/0) | PASS(합성, AppTest·브라우저 아님) |
| E16-GALLERY-PAGER (승인 2026-10-12: 갤러리 페이지 버튼 << < 번호(최대 9) > >>, 현재 페이지 primary·비활성, 범위 밖 화살표 비활성, 페이지 수 감소 시 clamp) | `test_gallery_pager_detail.py::test_pager_*`(작은 AppTest 스크립트, 20쪽 창 1–9 / 5–13 / 6–14 / 12–20 수기 계산, 20→5쪽 clamp, 1쪽 모두 비활성), `test_gallery_pages_show_the_right_thumbnails_and_clamp`(dummy 13 → 12개/쪽: 1쪽 #0–#11, 2쪽 #12, 오래된 page 7 → 2) | PASS(합성, AppTest) |
| E16-DETAIL-TYPES (승인 2026-10-12: 상세 화면 candidate_types = 단위 표 같은 행 값; C14) | `test_gallery_pager_detail.py::test_detail_shows_the_unit_table_candidate_types_for_the_opened_index`(5 단위 모두 열어 표 셀과 대조, '' → 없음, "local, equip_local (몰림형, 설비 반복 몰림형)", 키 없는 구 session → -) | PASS(합성, AppTest) |
| E16-MAP-TYPECOLOR (승인 2026-10-12: 상세 지도 후보 유형 색, 겹침 별도 표시; C11, E16 표시 필터) | `test_gallery_pager_detail.py::test_candidate_colour_mode_labels_overlaps_counts_and_bin_filter`(mixed.klarf: 저장된 shape_supports·signature_groups local_*로 점별 라벨 독립 계산 = trace 라벨, 300점 각 1회, ring+local·line+local·ring+line+local 겹침 마름모, 색 전환 시 개수 불변, bin 1·3 필터 → 180/300, 상세 재진입 시 bin 모드로 초기화, equip_local은 "·설비 반복") | PASS(합성, AppTest) |
| E16-GALLERY-TYPES (승인 2026-10-12: candidate_types를 status 바로 뒤로, 갤러리 제목 "후보: " = 같은 행 값; C14) | `test_equipment_candidates.py::test_b_*`(이전 열 순서 수기 명시 대비 unit_rows·summary.csv), `test_c_*`(AppTest 표 ↔ plotly 제목, ", " 결합, '' → 없음, None → -, 범례 code=한글), `test_e_apptest_old_batch_*` | PASS(합성, AppTest·브라우저 아님) |
| E12-EQUIP-CONFIG (equipment_signature·defect_volume 검증) | `test_equipment_candidates.py::test_h_*`(enabled+null/0 tolerance, min_wafers 1, angle 90, excess > limit, limit 0 → CONFIG_INVALID + key; equipment_field 고정; disabled+null·블록 없음 → 유효; scan 단계 거부) | PASS(합성) |
| E13-VOLUME (과다 defect vs 검사 중단 의심, 임계값은 시험값) | `test_equipment_candidates.py::test_g_*`(n_parsed ≥ limit → abort_suspect, 경계 포함; excess만 → excess_abort_unconfirmed, abort 코드 없음; 둘 다 null → disabled; 고정 config 기준) | PASS(합성) |
| E17-BATCH (구 batch dict) | `test_equipment_candidates.py::test_e_*`(config에 새 블록 없음·meta에 equipment/step 없음 → not_configured, 파일별 코드만, 미분석 행 candidate_types None + 사유) | PASS(합성) |

### 2.4 실제 사내 입력 하위 case (실행계획 19.3)

E01-FN, E01-FN-DELIM, E01-FN-TIME, E09-META, E01-COLORDER, E13-COLX, E09-MULTI, E13-VER, E03-EMPTY-REAL, E13-CORRUPT-REAL, E02-REAL, E09-BIN-REAL: **모두 BLOCKED**(실제 샘플·명세 없음, T-26). 합성 fixture로 대신 통과 처리하지 않는다.

### 2.5 실행 기록

| 일자 | 명령(저장소 루트) | 환경 | 결과 |
|---|---|---|---|
| 2026-10-11 | `python -m pytest --collect-only -q` | Windows, Python 3.12.15 | 360 tests collected (e2e 13) |
| 2026-10-11 | `python -m pytest -m "not e2e" -q` | 동상 | 347 passed, 13 deselected — PASS(합성) |
| 2026-10-11 | `python -m pytest -m e2e -q -rs` | 동상 + 시스템 Edge | 13 passed, skip 0 — PASS(합성) |
| 2026-10-11 (null 사유, result-0.2) | `python -m pytest -m "not e2e" -q` | Windows, Python 3.12.15 (insenv) | 359 passed, 13 deselected — PASS(합성) |
| 2026-10-11 (null 사유, result-0.2) | `python -m pytest -m e2e -q -rs` | 동상 + 시스템 Edge | 13 passed, skip 0 — PASS(합성) |
| 2026-10-12 (mixed 38 dummy) | `python -m pytest tests/test_dummy_mixed.py -q` | Windows, Python 3.12.15 (insenv) | 80 passed in 55.15s — PASS(합성). E01-MIXED38·E09-MIXED·E01-BATCH-MIXED. 형상 라벨 N/A(생성 의도 ≠ 분류 정답) |
| 2026-10-12 (mixed 38 dummy) | `python -m pytest -m "not e2e" -q` | 동상 | 439 passed, 13 deselected in 90.01s — PASS(합성). e2e는 이번에 NOT_RUN |
| 2026-10-12 (설비 반복·과다 defect·열 순서·갤러리) | `python -m pytest tests/test_equipment_candidates.py -q` | Windows, Python 3.12 (insenv) | 23 passed in 18.34s — PASS(합성). E06-EQUIP·E16-GALLERY-TYPES·E12-EQUIP-CONFIG·E13-VOLUME·E17-BATCH(구 batch) |
| 2026-10-12 (동상) | `python -m pytest -m "not e2e" -q --durations=0` | 동상 | 462 passed, 13 deselected in 225.98s — PASS(합성). 새 파일 추가 전 같은 439건은 148.70s. 소요의 약 60%가 `test_dummy_mixed.py`(136 s, run_job 내 `stats.clark_evans` 1000회 모의 ≈ 파일당 3.4 s / 3.9 s); `batch_candidates`는 23 unit batch에서 약 1 ms. 시간 변동은 이번 변경 원인 아님(stats.py 미변경) |
| 2026-10-12 (동상) | `python -m pytest -m e2e -q -rs` | 동상 + 시스템 Edge | 13 passed, skip 0 in 130.71s — PASS(합성) |
| 2026-10-12 (pairwise 수정 `_clique`, 캡션 위치 문구 제거) | `python -m pytest tests/test_equipment_candidates.py -q` | Windows, Python 3.12 (insenv) | 31 passed in 18.65s — PASS(합성). E06-EQUIP-PAIRWISE 추가, star 가정 기대값 2건 개정(peers = 전체 4장 → 모두 일치하는 부분집합, detail에 peers_rule) |
| 2026-10-12 (동상) | `python -m pytest -m "not e2e" -q` | 동상 | 470 passed, 13 deselected in 198.32s — PASS(합성) |
| 2026-10-12 (동상) | `python -m pytest -m e2e -q -rs` | 동상 + 시스템 Edge | 13 passed, skip 0 in 85.25s — PASS(합성) |
| 2026-10-12 (개요 유형별 개수·비율, `_clique` 최대 집합 확장) | `python -m pytest tests/test_equipment_candidates.py -q` | Windows, Python 3.12 (insenv) | 36 passed in 22.05s — PASS(합성). E16-OVERVIEW-TYPECOUNT 5건 추가; 동일 ring 4장 peers 기대값을 "부분집합"에서 "4장 전체·steps 4개"로 강화 |
| 2026-10-12 (동상) | `python -m pytest -m "not e2e" -q` | 동상 | 475 passed, 13 deselected in 173.07s — PASS(합성) |
| 2026-10-12 (동상) | `python -m pytest -m e2e -q -rs` | 동상 + 시스템 Edge | 13 passed, skip 0 in 108.30s — PASS(합성) |
| 2026-10-12 (갤러리 pager·상세 candidate_types·후보 유형 색, TBD 번호 재정리 후) | `python -m pytest tests/test_gallery_pager_detail.py -q` | Windows, Python 3.12 (insenv) | 5 passed in 12.61s — PASS(합성, AppTest) |
| 2026-10-12 (동상) | `python -m pytest -m "not e2e" -q` | 동상 | 480 passed, 13 deselected in 225.42s — PASS(합성). TBD 번호 재정리로 인한 실패 0 |
| 2026-10-12 (동상) | `python -m pytest -m e2e -q -rs` | 동상 + 시스템 Edge | 13 passed, skip 0 in 143.47s — PASS(합성) |

이전 실행 기록과 결함 조치 이력은 실행계획 20.2.

---

## 3부. 유지 규칙 — 시나리오를 최신 코드에 맞춘다

1. **코드·설정·화면을 바꾸는 작업은 같은 변경 안에서** 이 문서 2부의 추적표(테스트 함수명·상태)와 실행계획 19절의 해당 시나리오를 갱신한다. 테스트 함수 이름을 바꾸거나 지우면 추적표도 고친다.
2. 기존 계약을 코드가 어기면 시나리오가 아니라 코드를 고친다. 승인된 사양 변경으로 기대값이 바뀌면 기존 ID를 보존하고 `E02-UP`처럼 하위 ID를 추가하며, 기존/신규 기대값·사유·근거·연계 C ID를 실행계획 20.2에 남긴다.
3. 기대값은 독립 계산·manifest·도메인 검토에서 얻는다. production 함수 출력을 정답으로 복사하지 않는다. 실패를 숨기기 위한 assert 삭제·허용오차 확대·skip/xfail 추가를 하지 않는다.
4. 상태는 실제 실행한 명령·환경·결과가 있을 때만 갱신하고 2.5에 기록한다. 합성 PASS를 상위 E PASS나 실제 데이터 PASS로 올리지 않는다.
5. 현재 테스트 목록 확인: `python -m pytest --collect-only -q`. 추적표는 E 시나리오를 대표하는 테스트를 적는다(모든 테스트를 나열하지 않는다). 표에 적힌 테스트가 사라지거나 이름이 바뀌면, 또는 새 테스트가 새 E/하위 case를 검증하면 표를 고친다.
6. 점검 도구: `/wafer-verify`(영향 테스트 선택·실행), `/wafer-contract-audit`(문서↔코드 정합), 서브에이전트 `wafer-test-maintainer`(최신성 점검·개정).
