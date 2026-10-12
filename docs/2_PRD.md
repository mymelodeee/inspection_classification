# 2. PRD (제품 요구사항 정의서)

- 상태: 개발 단계(Phase 1~3 합성 경로 구현). release 판정 **NOT_READY**([6_execution_plan.md](6_execution_plan.md) 20.3).
- 기준일: 2026-10-11. 구현 여부는 `wafer/` 코드와 `tests/`로 확인한 값이며, 검증 상태는 [3_user_scenarios.md](3_user_scenarios.md)의 추적표를 따른다.
- 용어는 [1_domain_definition.md](1_domain_definition.md)를 따른다.

## 1. 배경과 문제

인라인 검사 결함 map은 점 수가 많고, 결함 위치·방향·bin 분포와 설비 시그니처(삼발이 등)를 사람이 눈으로 판단한다. 판단 기준이 사람마다 다르고, 이미지 기반 집계는 원본 이벤트 수·bin·방향을 잃는다. 이 제품은 **KLARF 원본 좌표를 기준으로** 개수를 보존하면서 bin·영역·시계방향 분포와 패턴 후보를 재현 가능하게 계산하고, 사람이 검토한 결과를 이력으로 남긴다.

## 2. 사용자

| 사용자 | 목적 | 주 경로 |
|---|---|---|
| 공정·검사 엔지니어 | 웨이퍼 한 장 또는 lot 단위로 분포·패턴 후보를 보고 검토 기록을 남긴다 | Streamlit 화면 |
| 분석 자동화 담당 | 파일을 일괄 처리하고 JSON/CSV를 다른 도구로 넘긴다 | CLI, 다운로드 |
| 규칙·설정 관리자 | profile(YAML)의 zone·임계값·template을 관리하고 결과 재현성을 확인한다 | YAML, provenance |
| 개발·검증 담당 | 계약 위배 없이 기능을 바꾸고 시나리오를 최신 코드에 맞춘다 | pytest, 서브에이전트·스킬 |

## 3. 목표와 비목표

**목표**

1. 원본 이벤트 개수·bin을 잃지 않는다(개수 보존 불변식).
2. 노치 6시 표준 좌표에서 bin·zone·12 sector·center를 집계한다.
3. ring/line/local/삼발이 후보와 원시 측정값을 근거와 함께 보고한다.
4. 계산 불가와 실제 0, 후보와 확정, 실행 실패와 판정 보류를 구분한다.
5. 같은 입력·설정·버전이면 같은 결과를 내고, 결과와 검토 이력을 덮어쓰지 않는다.
6. 파일 1개와 여러 파일·폴더를 같은 화면 흐름으로 분석·비교·내보낸다.

**비목표(현재)**: 공정 원인 확정, 정상/위험 등급·0~100 점수, 수율 예측, 이미지 입력, ML/CNN 분류, HTTP API, 다중 사용자 인증, 운영 배포.

## 4. 기능 요구사항

상태: **구현**(합성 검증됨) / **부분** / **미구현** / **BLOCKED**(자료·결정 필요). 시나리오 ID의 상세 통과 기준은 실행계획 19절.

### 4.1 입력·좌표

| ID | 요구사항 | 상태 | 근거 코드 | 시나리오 |
|---|---|---|---|---|
| FR-IN-01 | KLARF를 엄격 파싱하고 조용한 레코드 소실 없이 성공 또는 명시적 실패 | 구현(합성 문법) | `ingest.read_klarf` | E01, E13 |
| FR-IN-02 | 원본 sha256을 기록하고 분석 키에 쓴다 | 구현 | `ingest`, `store.analysis_key` | E17 |
| FR-IN-03 | adapter가 단위·die·중심·노치를 표준 좌표로 한 번 변환, 지원 밖은 추정 없이 거부 | 구현(합성 adapter 2종) | `ingest.standardize`, `geometry` | E02 |
| FR-IN-04 | 노치 미상이면 개수·반경 결과는 내고 방향·위상은 보류 | 구현 | `cli.analyze_file`, `_withhold_orientation` | E10 |
| FR-IN-05 | 실제 장비 export 계열의 입력 계약(파일명·형식·메타데이터·좌표·bin) | BLOCKED(T-26) | — | 19.3 |
| FR-IN-06 | 한 파일의 복수 wafer/inspection을 분석 단위로 분리 | 미구현(현재 `invalid_input`, T-09) | — | E09-MULTI |
| FR-IN-07 | 이미지 전용 입력 fallback | 미구현(후속) | — | E15 |

### 4.2 집계·통계

| ID | 요구사항 | 상태 | 근거 코드 | 시나리오 |
|---|---|---|---|---|
| FR-AG-01 | 포함/제외, bin 합계(unknown 포함) | 구현 | `aggregate` | E01, E09 |
| FR-AG-02 | 12 sector + center 엄격 집계, bin×sector 표 | 구현 | `aggregate`, `geometry` | E01, E08 |
| FR-AG-03 | 경계 ±tol 허용오차 집계(판정 미반영) | 구현(해석 확인 대기, T-15) | `geometry.neighbor_hour` | E08 |
| FR-AG-04 | E1/E2·100mm zone, 고유 ID union | 구현(기본 비활성, 운영값 T-06) | `aggregate`, `geometry` | E08 |
| FR-AG-05 | 반경 구간 개수·면적·밀도, Clark–Evans(coverage 있을 때) | 구현 | `stats`, `cli._radial` | E03, E11, E14, E23 |
| FR-AG-06 | coverage sidecar(full_disk) 명시 입력, 추정 금지 | 구현(실제 coverage 자료 T-04) | `cli.load_coverage` | E11 |
| FR-AG-07 | affected die 수·비율 | 미구현(`null`, T-13) | — | E09 |

### 4.3 패턴 후보

| ID | 요구사항 | 상태 | 근거 코드 | 시나리오 |
|---|---|---|---|---|
| FR-PT-01 | DBSCAN 국부 군집, noise 보존 | 구현 | `clustering`, `detect` | E04 |
| FR-PT-02 | ring/arc 후보와 반지름·직경·두께(P95−P5)·극단 폭·각도 점유 | 구현(중심 기준 1개, T-19) | `ring`, `detect` | E05, E06 |
| FR-PT-03 | line 후보와 길이·폭·잔차·방향 | 구현(직선 1개) | `line`, `detect` | E05 |
| FR-PT-04 | 혼합 패턴 그룹 support와 고유 union | 구현 | `groups`, `detect` | E06 |
| FR-PT-05 | 삼발이 template 일치(3 lobe·120°·반경·위상·coverage) | 구현(기본 비활성, 사내 template T-07) | `lift_pin` | E07 |
| FR-PT-06 | 보정 전 규칙은 `candidate`까지만 | 구현 | `ring`, `line`, `lift_pin` | E05~E07 |
| FR-PT-07 | 분류 임계값 보정(calibration) | BLOCKED(라벨 자료, T-14·T-16·T-18) | — | E21 |

### 4.4 출력·저장·검토

| ID | 요구사항 | 상태 | 근거 코드 | 시나리오 |
|---|---|---|---|---|
| FR-OUT-01 | JSON 결과(상태 3종 분리, provenance) | 구현 | `cli.run_job`, `report.check_result` | E01, E16 |
| FR-OUT-02 | CSV(`defects`, `spatial_counts`, `bin_sector`) + `manifest.json`, 빈 칸=null | 구현 | `report.write_csv` | E16 |
| FR-ST-01 | SQLite 결과 저장, 분석 키 idempotent, 시도 별도 기록 | 구현 | `store.save_run`, `log_attempt` | E17, E18 |
| FR-ST-02 | 검토 revision(confirm·correct_label·merge·split·defer) append-only | 구현 | `store.add_review` | E19 |
| FR-ST-03 | 과거 batch·분석 목록 조회 화면 | 미구현(같은 입력 재분석으로 재조회) | — | E19 |

### 4.5 화면·일괄 분석

| ID | 요구사항 | 상태 | 근거 코드 | 시나리오 |
|---|---|---|---|---|
| FR-UI-01 | 파일 1개~여러 개·폴더를 같은 흐름으로 업로드, 서버 경로 입력 | 구현 | `batch_ui.render` | E16-BATCH-SELECT |
| FR-UI-02 | 분석할 파일 선택/전체 선택/전체 제외/업로드 전체 삭제(원본·DB는 삭제 안 함) | 구현 | `batch_ui` | E16-BATCH-SELECT |
| FR-UI-03 | 기본 profile 경로(dummy 시험용), 경로 YAML은 매 분석 때 다시 읽음 | 구현 | `ui_inputs`, `batch_ui` | E12-DEFAULT |
| FR-UI-04 | 입력 목록(분석 전): 경로·크기·상태·사유·hash·헤더 lot/wafer·parser/adapter/profile | 구현 | `batch.scan` | E13-BATCH |
| FR-UI-05 | 입력 고정: profile·sidecar·파일 hash가 바뀌면 core는 실행 거부, UI는 경로 profile 변경 시 재검증 | 구현 | `batch.run_batch`, `batch_ui` | E18-BATCH |
| FR-UI-06 | 순차 실행·진행률, 한 파일 실패가 다른 파일을 멈추지 않음, 실패를 0건으로 저장 안 함 | 구현 | `batch.run_batch` | E13-BATCH |
| FR-UI-07 | 개요(파일·단위·성공·실패·보류·포함 결함 합, 고유 wafer, 미상 wafer 단위), `candidate_types`별 단위 수·비율(%) | 구현 | `batch.overview`, `batch.candidate_type_counts` | E02-BATCH-COUNT |
| FR-UI-08 | 분석 단위 표(필터·필터 CSV), 유형별 요약(candidate/matched·평가 분모), 그룹별 밀도·bin | 구현 | `batch.unit_rows`, `type_summary`, `batch_density` | E03/E06/E11-BATCH |
| FR-UI-09 | 원시 정도 지표만 제공, 점수·등급 없음 | 구현 | `batch.unit_metrics` | E10/E11-BATCH |
| FR-UI-10 | 맵 갤러리(페이지 12개, 맵당 2000점 표시 상한, 통계 불변), 파일 이름 옆에 단위 표와 같은 `candidate_types` 표시 | 구현 | `batch_ui._thumb`, `_types_label` | E20(부분), E16-GALLERY-TYPES |
| FR-UI-13 | 설비성 후보: 같은 검사 설비(`InspectionStationID`)에서 step과 무관하게 반복된 환형·일자형·몰림형, 과다 defect·검사 중단 의심(중단 근거와 과다 구분) | 구현(합성 검증, 실제 설비·상한 값 BLOCKED T-29) | `batch.batch_candidates`, profile `equipment_signature`·`defect_volume` | E06-EQUIP, E13-VOLUME, E12-EQUIP-CONFIG |
| FR-UI-11 | 상세 화면: 상태·개수·map(bin 필터·group 강조)·bin×sector·공간 집계·판정 상태·검토·JSON/CSV zip | 구현 | `app.py` | E16, E19 |
| FR-UI-12 | 다운로드: 요약 CSV, 유형 CSV, 개별 결과+manifest ZIP | 구현 | `batch.summary_csv`, `type_csv`, `export_zip` | E16-BATCH |

### 4.6 CLI

| ID | 요구사항 | 상태 | 근거 코드 |
|---|---|---|---|
| FR-CLI-01 | `python -m wafer.cli <klarf> --profile <yaml> [--out] [--csv-dir] [--db] [--coverage]` | 구현 | `cli.main` |
| FR-CLI-02 | 오류는 traceback 대신 JSON + 종료 코드 | 구현 | `cli.run_job` |
| FR-CLI-03 | 여러 파일 일괄 처리 CLI | 미구현(화면만 제공, `batch.folder_items`는 시험용) | — |

## 5. 비기능 요구사항

| ID | 요구사항 | 현재 |
|---|---|---|
| NFR-01 재현성 | 같은 입력·profile·coverage·버전·seed → 같은 결과, 키 충돌 시 거부 | 구현 |
| NFR-02 단일 core | CLI와 화면이 같은 `run_job`을 호출, 분석 로직 복제 금지 | 구현 |
| NFR-03 자료 취급 | 사내 KLARF·ID·경로를 외부로 보내지 않음, DB에는 파일명(basename)만 | 구현(로컬 전용) |
| NFR-04 실행 환경 | 64-bit CPython 3.11/3.12, 저장소 루트 상대 경로, 환경 이름 하드코딩 금지 | 구현 |
| NFR-05 입력 상한 | 파일 수·파일 크기·총 크기 상한(화면에서 변경) | 개발용 기본값 500개/50 MB/300 MB(운영값 T-27) |
| NFR-06 성능 | 대표 부하 p50/p95·메모리 목표 | 미정(BLOCKED, T-10, E20) |
| NFR-07 정확도 | 유형별 재현율·오경보·보류율 | 미정(BLOCKED, 내부 blind set, E21) |
| NFR-08 배포 | container·CI·rollback | 미구현(Phase 4, E22) |

## 6. 수용 기준

- 첫 기준: F01(E01) — included 8, bin "1"/"2"/"3" = 3/3/2, center 1, 12시 1·3시 4·6시 1·9시 1(독립 oracle `tests/fixtures/f01/oracle.json`).
- 합성 묶음: `klarf_dummy_data` 13개 — 단위별 개수·bin·center·sector = manifest, 총 1412.
- 기능 상태는 [3_user_scenarios.md](3_user_scenarios.md)의 추적표에서 PASS(합성)/NOT_RUN/BLOCKED/N/A로 관리한다. 합성 PASS는 실제 장비·분류 성능의 증빙이 아니다.
- 운영 진입 기준(실제 blind 성능, 배포·rollback)은 실행계획 11·20절이며 현재 모두 미충족이다.

## 7. 제약·가정

- 실제 장비 KLARF, 사내 bin 의미, E1/E2 값, 삼발이 template, coverage 자료가 없다. 해당 기능은 합성 자료로만 검증했고 기본 비활성이거나 시험 profile에서만 켜진다.
- 시험 profile 값을 운영값으로 복사하지 않는다.
- 일괄 분석은 단일 프로세스 순차 실행이다(queue·병렬 없음).

## 8. 열린 결정

[9_TBD.md](9_TBD.md)가 원본이다. 이 PRD에 영향이 큰 항목: T-26(실제 입력 계약), T-09(복수 wafer 파일), T-04(coverage 자료), T-06·T-07(사내 zone·template), T-10(성능 목표), T-14·T-18(분류 임계값), T-20(`degraded` 기준), T-27(일괄 분석 기본안), T-28(code_version 범위), R-05(화면 표 null 표시), T-29(설비성 후보의 실제 필드·임계값).
