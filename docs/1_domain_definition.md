# 1. 도메인 정의서

- 문서 목적: 인라인 검사 결함 map 분석에서 쓰는 용어·좌표계·상태·개수 규칙·설정 항목을 **현재 코드 기준**으로 한곳에 정의한다. 설계를 바꿀 때 이 문서의 정의를 먼저 고친 뒤 코드·테스트·다른 문서를 맞춘다.
- 기준: `wafer/` 코드(2026-10-11 작업 트리), [6_execution_plan.md](6_execution_plan.md) 5.2·6·8·16절, [CLAUDE.md](../CLAUDE.md) 4절.
- 배경 지식·문헌: [wafer_inspection_map_knowledge.md](../wafer_inspection_map_knowledge.md)(inspection map vs 전기적 WBM, 분류 체계, 모델 선택). 이 문서와 다르면 실행계획·이 문서가 우선한다.
- 미확정 정의는 [9_TBD.md](9_TBD.md)의 ID로 표시한다. **합성 adapter·시험 profile 값은 사내 정의가 아니다.**

## 1. 분석 대상과 범위

| 구분 | 정의 |
|---|---|
| 대상 | 인라인 검사 장비가 출력한 **개별 결함 이벤트**(KLARF의 결함 레코드). 전기적 fail die map(EDS/WBM)이 아니다 |
| 주 입력 | KLARF 텍스트. 원본 좌표·bin이 기준이며 이미지는 현재 구현하지 않는다(이미지 fallback은 후속, E15) |
| 산출 | 개수·bin·영역(zone)·시계방향 집계, 공간 통계, 패턴 후보(ring/line/local/lift_pin)와 원시 측정값, 검토 이력 |
| 비범위 | 공정 원인 확정, 설비 제어, 수율 예측, 정상/위험 등급·점수(사내 보정 자료 없음, T-27) |

## 2. 판정 단위(4층)와 라벨 축

| 층 | 코드 표현 | 의미 |
|---|---|---|
| `defect` | `excluded`, CSV `defects.csv` 행, 이벤트 ID | 원본 개별 이벤트. bin·좌표의 기준 단위 |
| `cluster` | `detect.clusters` (DBSCAN) | 공간적으로 인접한 점 집합. noise(`detect.noise`)도 삭제하지 않는다 |
| `signature_group` | `detect.signature_groups`, `detect.shape_supports` | 여러 cluster 또는 후보 점을 묶은 ring·line·local·삼발이 지원 집합 |
| `wafer_summary` | `pattern_summary`, `bin_totals`, `sectors_clock` 등 | 웨이퍼 단위 다중 라벨 요약과 총수 |

라벨 축은 `morphology`(형태) / `zone`(위치) / `signature_match`(설비 시그니처) / `review_status`(검토)로 분리한다. 한 결함이 여러 축의 라벨을 동시에 가질 수 있고, 축을 하나의 상호배타 class로 합치지 않는다. 검토 라벨 수정(`correct_label`)도 축을 지정해야 한다(`store.LABEL_AXES`).

### 2.1 이벤트 키와 개수 단위

- 이벤트 키: `레코드순서:DEFECTID`(예 `3:3`). 같은 좌표·같은 DEFECTID를 가진 서로 다른 레코드도 별도 이벤트로 보존한다.
- 결과에 나오는 수는 단위가 다르다: 결함 이벤트 수(`n_*`), cluster 수, support(지원 이벤트 수), affected die 수. 현재 die 규칙·검사 die 목록이 없어 `affected_die_count`, `inspected_die_count`는 항상 `null`이다(T-13).
- 일괄 분석에서는 **업로드 파일 수 ≠ 분석 단위 수 ≠ 고유 wafer 수**다. 분석 단위는 분석에 성공한 wafer record 1개이며, 현재 파서는 파일당 wafer record 1개만 허용한다(복수는 `invalid_input`, T-09).

## 3. 좌표계

### 3.1 표준 좌표

| 항목 | 정의 |
|---|---|
| 원점·단위 | wafer 중심, mm |
| 축 | +X 오른쪽, +Y 위쪽 |
| 노치 | 6시(아래) |
| 반경 | `r = sqrt(x² + y²)` |
| 시계 각도 | `theta = degrees(atan2(x, y)) mod 360` → 0°=12시, 90°=3시, 180°=6시, 270°=9시. 360.0은 0으로 정규화 |
| edge 거리 | `distance_from_edge_mm = wafer_radius_mm − r` |

원본 → 표준 변환은 **adapter**가 한 번만 수행한다(이중 회전 금지). Orientation 값만으로 mirror를 추정하지 않는다.

### 3.2 구현된 adapter(합성 전용)

| adapter_id | 입력 문법 | 변환 | 지원 조건(어기면 `UNSUPPORTED_ADAPTER`) |
|---|---|---|---|
| `synthetic-um-die00-notch-down` | 평면 1.2 스타일(`DefectRecordSpec`/`DefectList`) | XREL/YREL(µm, 중심 기준) → mm | `source_units: um`, SampleCenterLocation·DieOrigin `0 0`, die index (0,0), `CoordinatesMirrored NO`, 노치 DOWN |
| `synthetic-die-local-v1` | KLARF 1.8 Record/Field/List(단일 WaferRecord) | `raw_mm = (die index × pitch + XREL/YREL − SampleCenterLocation) / 1000`, 노치 회전 1회 | `source_units: um`, `DiePitch > 0`, `DieOrigin 0 0`, `XINDEX`/`YINDEX` 열, XREL/YREL ∈ [0, pitch), `CoordinatesMirrored` 없음 또는 NO, `SampleOrientationMarkType` NOTCH, profile `side_convention: front` |

위 표는 주요 조건이다. 전체 거부 조건의 원본은 `wafer/ingest.py`(`standardize`)다.

- adapter는 profile의 `coordinates.adapter_id`로 **명시 선택**한다. 누락·미등록은 `CONFIG_INVALID`(T-01).
- 노치 위치 필드가 없으면 실패하지 않고 부분 결과를 낸다: 개수·bin·반경·edge 거리·center는 계산, 시계방향·위상은 보류(`orientation_status=unknown`, T-02).
- 실제 장비 좌표 공식은 미검증이다(T-01, T-02, T-26).

### 3.3 시계 sector와 center

| 항목 | 정의 |
|---|---|
| sector | 12개, 시각 중심 ±15°, 반개구간 `[h·30−15, h·30+15)`. 정확히 15°는 1시, 345°는 12시 |
| center | `r < clock.center_exclusion_radius_mm`. sector에 넣지 않고 따로 센다. 값이 `null`이면 시계방향 집계 비활성 |
| 엄격 집계 `sectors_clock` | 각 점은 sector 하나. `Σ sectors + center = n_included` |
| 허용오차 집계 `sectors_clock_tolerant` | 경계 ±`clock.boundary_tolerance_deg`(기본 5°, `0 ≤ 값 < 15`) 안의 점을 인접 sector에도 센다. 합이 `n_included`보다 클 수 있다(`n_multi_sector`). 판정·라벨에는 쓰지 않는다(T-15) |
| `boundary_ambiguous` | 허용오차 안에 든 점의 ID와 개수 |

### 3.4 영역(zone)

| zone | 지표 | 구간 규칙 | 기본 |
|---|---|---|---|
| `E1`, `E2` | edge 거리(중심 반경 아님, 다른 metric이면 `CONFIG_INVALID`) | `[하한, 상한)` | 비활성. 운영값 미정(T-06) |
| `zone_8inch_inside` | 반경 | `[0, 100)` | 비활성 |
| `zone_8inch_boundary` | 반경 | `|r − 100| ≤ band_width_mm / 2`(양끝 포함 예외) | 비활성, 폭 미정(T-05) |

- 100mm를 101.6mm로 치환하지 않는다. 같은 계층(E1·E2끼리)의 중첩은 금지, 다른 계층 간 중첩은 허용(R-02).
- zone 수는 중첩할 수 있으므로 합계 대신 고유 이벤트 ID union(`zone_union_unique`)을 쓴다.
- wafer 경계 `r = R`은 포함한다. `r > R`은 `outside_wafer`로 제외하며 잘라 넣지(clip) 않는다.

## 4. 패턴 후보와 측정값

| 유형 | 검출 방식(현재) | 주요 측정값 | 판정 |
|---|---|---|---|
| `local` | DBSCAN(`clustering.eps_mm`, `min_samples`) 군집 중 ring/line support와 동일하지 않은 것 | 군집 ID·구성 이벤트 | 규칙·보정 없음. 일괄 요약의 local 상태는 이 파생 정의다 |
| `ring`/`arc` | wafer 중심 기준 반경 밀도 최대 지점 ±`detect.ring_radial_tol_mm` 하나 | 중심선 반지름 `center_radius_mm`, 직경, 두께 `ring_thickness_mm`=P95−P5, 극단 폭 `radial_extent_mm`=max−min, 각도 점유 | `shapes.ring` 임계값. offset·다중 ring 미구현(T-19) |
| `line` | 최대 inlier 직선 하나(RANSAC) + PCA 측정 | 길이, 폭(정규 거리 P95−P5), RMS 잔차, 방향 | `shapes.line` 임계값 |
| `lift_pin`(삼발이) | template(반경 band·위상·120° 간격·허용오차) 일치 | lobe별 위치·평균 각·점 수·존재 여부, A1/A2/A3 | 기본 비활성. 3 lobe → `threefold_match`, 2 lobe → `partial_match` 후보 |

- **band 폭(T-05)** 은 관측된 환형 패턴의 두께(측정값)이며 100mm 경계 band 설정과 무관하다.
- `calibrated: false`인 규칙은 조건을 만족해도 `candidate`까지만 보고한다. `matched`는 보정된 규칙만 낼 수 있다. `calibrated`는 현재 자기 선언 값이다(T-17).
- k=3 고조파(A3)만으로 삼발이를 확정하지 않는다. 형상 일치는 공정 원인의 확증이 아니다.
- 노치 미상이면 방향·위치 측정 키(`occupied_hours*`, `center_x/y_mm`, `direction_deg`, `centroid_mm`)는 `null` + `withheld` 사유이고, 반경·두께·길이 등 회전 불변값은 유지한다(R-04).

### 4.1 batch 단위 후보: 설비 반복성과 defect 과다 (2026-10-12)

wafer 한 장의 공간 패턴(위 표, `ring`·`line`·`local`·`lift_pin`)과 **여러 wafer에 걸친 같은 설비 반복**을 다른 축으로 둔다. 단일 wafer의 모양만으로 설비 원인을 확정하지 않으며, 반복도 설비 원인의 확증이 아닌 후보다.

| 코드 | 한국어 | 판정 근거 | 판정 불가(후보 없음 + 사유) |
|---|---|---|---|
| `ring` / `line` / `local` | 환형 / 일자형 / 몰림형 | 기존 wafer별 후보(변경 없음) | 기존과 같음 |
| `equip_ring` | 설비 반복 환형 | 같은 검사 설비에서 환형 중심 반경 차 ≤ `ring_radius_tol_mm`인 wafer가 `min_wafers` 이상(자기 포함). 반경은 회전 불변이라 노치 미상도 비교 | 설비 ID 없음, 설비 wafer 수 < `min_wafers`, 환형 후보 없음 |
| `equip_line` | 설비 반복 일자형 | 방향(mod 180) 차 ≤ `line_angle_tol_deg`, 중심 기준 부호 있는 거리 차 ≤ `line_offset_tol_mm`인 wafer가 `min_wafers` 이상 | 위 + 노치 미상(위치 비교 불가) |
| `equip_local` | 설비 반복 몰림형 | `local_min_points` 이상 국부 군집의 중심 거리 ≤ `local_distance_tol_mm`인 wafer가 `min_wafers` 이상 | 위 + 노치 미상 |
| `inspection_abort_suspect` | 과다 defect·검사 중단 의심 | 보고 결함 수(`n_parsed`) ≥ `inspection_defect_limit`(장비·레시피의 최대 보고 결함 수; 도달 시 장비가 검사를 멈춤 = 중단 근거) | 상한 미설정 |
| `excess_defect` | 과다 defect(중단 미확인) | `n_parsed` ≥ `excess_defect_count`이나 상한 미설정·미도달 | 기준 미설정 |

- **반복 = 모든 쌍이 일치**: `min_wafers`장 이상이 **서로 모두** 허용치 안에서 일치해야 한다(한 wafer와만 비슷한 것으로는 부족). 그래서 같은 반복 묶음의 wafer는 모두 같은 판정·같은 peers를 갖는다. 상세 JSON의 `peers_rule`로 구분된다.
- **설비 = 검사 설비**: KLARF `InspectionStationID`(따옴표 제거·공백 정리한 전체 문자열)로 묶는다. 공정 설비 ID는 입력에 없으며 섞지 않는다(사용자 결정 2026-10-12).
- **step은 제외 조건이 아니다**: `StepID`가 달라도 같은 설비면 비교하며, 상세에 반복 wafer들의 step 목록을 남긴다.
- **좌표**: 모든 비교는 adapter가 만든 표준 좌표(mm, 노치 6시)에서 한다. 한 batch는 같은 profile(같은 wafer 반경)을 쓴다.
- **복수 후보**: 한 wafer가 wafer별 후보와 batch 후보를 동시에 가질 수 있다. `candidate_types`는 wafer별 코드 뒤에 batch 코드를 붙인다.
- 설정은 batch 실행 시 config에 고정되며, 설정이 없는 이전 batch는 `not_configured`로 표시된다.

## 5. Coverage(검사 영역)

| 상태 | 입력 | 결과 |
|---|---|---|
| `unknown` | sidecar 없음 | 반경별 개수만. 면적·밀도 `null`(`coverage_unknown`), Clark–Evans `insufficient_data` |
| `declared_by_sidecar` | `{"coverage": {"shape": "full_disk", "radius_mm": R, "source": "..."}}` | 면적·밀도·Clark–Evans 계산, sidecar sha256을 provenance·분석 키에 기록 |

- coverage는 결함 분포나 파일 크기로 추정하지 않는다(T-04). 현재 `full_disk`만 지원, `0 < R ≤ wafer_radius_mm`.
- 오류는 `CONFIG_INVALID` + `reason`(`coverage_syntax_error` / `coverage_unsupported_shape` / `coverage_invalid_value`).
- 검사 창 밖 결함이 있으면 그 단위의 면적 보정 밀도는 `null`(`points_outside_inspected_window`).
- 면적 0은 계산 불가(`null`), 면적 > 0이고 개수 0이면 밀도 0이다.
- 일괄 분석에서는 sidecar 하나가 모든 파일에 공통 적용된다.

## 6. 상태 어휘

상태 필드는 서로 섞지 않는다. 성공한 job 안에서도 기능별 상태는 보류일 수 있다.

| 필드 | 값 | 의미 |
|---|---|---|
| `job_status` | `succeeded`, `failed` (계획상 `queued`, `running`은 미구현) | 결과를 반환했는지 |
| `data_quality_status` | `valid`, `invalid` (`degraded`는 기준 미정, T-20) | 입력 품질. `UNSUPPORTED_ADAPTER`는 입력 불량이 아니므로 생략 |
| `feature_status` | `matched`, `candidate`, `no_match`, `unknown`, `insufficient_data`, `disabled` | 규칙 판정. `no_match`는 정상이라는 뜻이 아니다 |
| `calc_status` | `computed`, `insufficient_data`, `disabled` | 통계 계산 상태(판정과 분리, T-21) |
| `clock_status.status` | `computed`, `insufficient_data`, `disabled` | 시계방향 집계 계산 여부 |
| `orientation_status` | `notch_registered`, `unknown` | 노치 정합 여부. `detect.frame`은 `notch_down`/`unregistered` |
| `review_status` | `unreviewed`, `confirmed`, `corrected`, `deferred` | 최신 revision 기준 |
| `pattern_summary` | `no_detected_defect`, `no_clear_pattern`, 후보 라벨 목록 | 웨이퍼 요약 라벨. 0건과 무패턴을 구분 |

### 6.1 일괄 분석 항목 상태

| 단계 | 상태 | 의미 |
|---|---|---|
| 입력 목록 | `ready` | 분석 대상 |
| 입력 목록 | `excluded` | 확장자(`.klf`/`.klarf`/`.txt` 외) 또는 상한 초과. 사유 기록 |
| 입력 목록 | `invalid_input` | 파싱 실패(손상·복수 WaferRecord 등) |
| 입력 목록 | `held` | profile의 adapter로 해석할 수 없음(입력 불량 아님) |
| 입력 목록 | `duplicate_in_batch` | 같은 내용(sha256)이 앞에 있음. 한 번만 분석하고 원본 항목을 가리킨다 |
| 실행 후 | `succeeded`, `failed`, `held` | 실행 결과. 실패를 0건으로 저장하지 않는다 |

## 7. 개수·null 규칙(불변식)

검사 위치가 항목마다 다르다. 1~3과 결과 키 집합은 `wafer/report.py check_result`가 결과마다 검사하며 위반은 `RESULT_INVARIANT_VIOLATED`(종료 코드 5)다. 4는 `wafer/clustering.py`의 assert가 검사하며 위반은 `INTERNAL_ERROR`(5)가 된다. 5~8은 런타임 검사가 없고 테스트로 확인한다([3_user_scenarios.md](3_user_scenarios.md)).

1. `n_parsed = n_included + n_excluded`. 제외 목록은 이벤트 ID와 사유를 가진다.
2. unknown을 포함한 `Σ bin_totals = n_included`.
3. 시계방향 집계가 계산됐으면 `Σ sectors_clock + center = n_included`, bin×sector 표의 행·열 합도 일치.
4. DBSCAN noise도 총수·bin·sector에 포함된다. noise ∪ cluster = 포함 이벤트(서로소).
5. 중첩 group·zone 총수는 고유 이벤트 ID union으로 센다.
6. **`null`(JSON) / 빈 칸(CSV) = 계산 불가·해당 없음, `0` = 실제 0.** **계산 불가 값은 `None`(화면 표)·`-`(화면 metric) 그대로 두고, 반드시 사유를 함께 남긴다**(2026-10-11 사용자 결정, R-05): 결과 JSON 최상위 `null_reasons`(null 필드 ↔ 사유가 정확히 일치해야 하며 `check_result`가 검사), `spatial_counts.csv`·화면 공간 집계의 `reason` 열, CSV `manifest.json`의 `null_reasons`(결과·`defects.csv` 열별), 일괄 단위 표·요약 CSV의 `null_reasons` 열(JSON), 그룹별 밀도 `reason`, 개요 `null_reasons`. 사유 접두사: `not computable`(계산 불가), `not applicable`(해당 없음), `not available`(입력에 값 없음), `not stored`(DB 미지정). 표시 세부는 [8_style_guide.md](8_style_guide.md).
7. 비율은 분모를 함께 표시하고 분모 0이면 `null`이다. 일괄 주요 방향 비율의 분모는 `n_included − center`.
8. 평가 불가(`disabled`/`insufficient_data`) 유형의 support는 0이 아니라 `null`이다.

## 8. 분석 키와 재현성

- 분석 키 = sha256(`source_sha256`, `profile_sha256`, `schema_version`, `code_version`, `rule_version`, `parser`, `adapter`, `seed`, `coverage{status, shape, inspected_radius_mm, sidecar_sha256}`) — `store.KEY_PARTS`.
- 파일명은 키에 들어가지 않는다. 같은 내용을 다른 이름으로 내도 같은 키다.
- `code_version` = `0.1.0-dev+<wafer/*.py 내용 해시>`(줄바꿈 정규화). `app.py`만 제외되고 `batch_ui.py`·`ui_inputs.py`를 포함한 나머지 모듈은 모두 들어간다. 따라서 이 모듈들의 주석만 바꿔도 키가 바뀐다(T-28).
- `rule_version` = 규칙 모듈(ring, line, lift_pin, detect, groups, clustering) 내용 해시.
- 같은 키·같은 결과면 저장 결과를 재사용하고, 같은 키·다른 결과는 `KEY_COLLISION_RESULT_MISMATCH`(종료 코드 7)로 거부한다.
- seed: `randomness.seed`(Monte Carlo). 같은 입력·설정·버전·seed면 결과가 재현돼야 한다.

## 9. 설정(profile YAML) — 현재 구현 스키마

정의 위치: `wafer/profile.py`(이 표는 요약이며 원본은 코드다). 알 수 없는 키·잘못된 타입은 `CONFIG_INVALID`. **활성 기능의 필수값 누락은 `CONFIG_INVALID`, 비활성 기능의 null은 허용(`disabled`).** 임계값에는 코드 기본값이 없다.

| 키 | 필수/기본 | 역할 |
|---|---|---|
| `profile_id` | 필수 | 결과 provenance 표시 |
| `schema_version` | `"1.0"` | profile 스키마 |
| `units` | `mm`만 허용 | |
| `wafer_radius_mm` | 반경 기반 기능에 필요 | 외부 결함 제외, edge 거리, coverage 상한 |
| `coordinates.adapter_id` | **필수** | adapter 선택(3.2) |
| `coordinates.source_units` | 모든 adapter 필수 | 현재 두 adapter 모두 `um`만 허용 |
| `coordinates.side_convention` | die-local adapter 필수 | `front`만 지원 |
| `coordinates.target_notch/x/y`, `missing_orientation` | 고정값 `DOWN/RIGHT/UP`, `retain_unknown` | |
| `clock.center_exclusion_radius_mm` | null → 시계방향 비활성 | center 정의 |
| `clock.boundary_tolerance_deg` | 5.0, `0 ≤ 값 < 15` | 허용오차 집계 |
| `clock.sector_width_deg`, `sector_centers_start_deg` | 30, 0 고정 | |
| `zones.E1/E2` | `enabled`, `metric: distance_from_edge_mm`, `interval_mm` | 3.4 |
| `zones.zone_8inch_inside`, `zone_8inch_boundary` | 기본 비활성 | 3.4 |
| `clustering.eps_mm`, `min_samples` | **모든 분석 실행에 필수**(`validate_for_run`). detect 활성 시 로드 단계에서도 값 범위 검사 | DBSCAN |
| `detect.enabled`, `ring_radial_tol_mm`, `line_inlier_mm`, `line_ransac_trials` | 활성 시 필수(T-19) | 후보 검출 |
| `shapes.ring.*` (`occupancy_bin_deg`, `ring_min_occupancy`, `arc_min_occupancy`, `max_relative_thickness`, `min_points`, `calibrated`) | 활성 시 필수(T-14, T-16) | ring/arc 분류 |
| `shapes.line.*` (`min_points`, `max_relative_width`, `max_gap_ratio`, `calibrated`) | 활성 시 필수(T-18) | line 분류 |
| `signatures.lift_pin.*` (`template_id`, `radius_band_mm`, `phase_deg`, `angular_tolerance_deg`, `radial_tolerance_mm`, `min_support_per_lobe`, `min_lobe_contrast`, `calibrated` …) | 기본 비활성, 활성 시 필수(T-07, T-22) | 삼발이 |
| `stats.radial_bin_mm` | null → 반경 집계 비활성 | 반경 구간 폭 |
| `randomness.seed`, `nsim`, `block_downstream_on_non_significance` | 20261009, 999, `false`만 허용 | 검정은 차단 gate가 아님 |
| `equipment_signature.*` (`enabled`, `equipment_field`=InspectionStationID 고정, `min_wafers` 기본 3·≥2, `ring_radius_tol_mm`, `line_angle_tol_deg`<90, `line_offset_tol_mm`, `local_distance_tol_mm`, `local_min_points`) | 기본 비활성, 활성 시 허용치 필수(>0) | 4.1 설비 반복 후보. dummy 시험 profile만 시험값으로 활성 |
| `defect_volume.excess_defect_count`, `inspection_defect_limit` | null이면 평가 안 함, ≥1, 과다 기준 ≤ 상한 | 4.1 과다 defect·검사 중단 의심. 장비·레시피 값이 필요하므로 기본값 없음 |
| `coverage.*`, `bin_mapping.*` | 기본값 | 현재 동작에 영향 없음(coverage는 sidecar로 입력) |

시험 profile: `tests/profiles/f01_test_profile.yaml`(평면 F01용), `tests/profiles/dummy_die_local_test_profile.yaml`(KLARF 1.8 dummy용, UI 기본 경로). 둘 다 **시험 전용**이다.

## 10. 오류와 종료 코드

| 종료 코드 | `error` | 상황 |
|---|---|---|
| 0 | — | 성공 |
| 2 | `CONFIG_INVALID` (+`keys`, coverage는 `reason`) | 설정 누락·오류. (CLI 인자 오류도 종료 코드 2지만 argparse가 사용법을 출력하며 JSON은 없다) |
| 3 | `INVALID_INPUT` (`data_quality_status=invalid`) / `UNSUPPORTED_ADAPTER` | 손상 파일 / 지원 밖 좌표 규약 |
| 4 | `INPUT_NOT_FOUND` | 파일 없음 |
| 5 | `RESULT_INVARIANT_VIOLATED` / `INTERNAL_ERROR` | 프로그램 결함 |
| 6 | `OUTPUT_WRITE_FAILED` | CSV/manifest 쓰기 실패 |
| 7 | `KEY_COLLISION_RESULT_MISMATCH` | 같은 분석 키에 다른 결과 |

일괄 분석은 batch 전체를 멈추는 오류(`CONFIG_INVALID` profile/coverage/inputs, `INPUT_NOT_FOUND`)와 파일별 실패(항목 상태 `failed`/`invalid_input`/`held`)를 구분한다.

## 11. 용어집

| 용어 | 정의 |
|---|---|
| KLARF | KLA Results File. 검사 결함 목록 텍스트 형식. 현재 평면 1.2 스타일과 1.8 Record 문법 일부를 엄격 파싱 |
| bin | `CLASSNUMBER` 값을 그대로 문자열로 표기(`"1"`, `"2"` …), 0은 `unknown`. 사내 bin 의미는 미정(T-03) |
| support | 어떤 후보·그룹을 지지하는 고유 이벤트 ID 집합 |
| 분석 단위 | 분석에 성공한 wafer record 1개 |
| batch | 한 번의 "입력 목록 확인 → 일괄 분석 실행"으로 고정된 입력 묶음. `batch_id`(uuid) |
| sidecar | KLARF 옆에 별도로 주는 coverage JSON |
| provenance | 결과의 출처·버전 기록(입력·profile·sidecar hash, 코드·규칙·파서·adapter·스키마 버전, seed) |
| revision | 검토 1건. append-only이며 예측 원본을 바꾸지 않는다 |
| 정도 지표 | 일괄 분석의 원시 지표(개수, support·비율, 면적·밀도, ring/line 측정값, 주요 방향). 점수·등급이 아니다 |
| 합성(synthetic) | 실제 장비 export가 아닌 시험 자료. 합성 통과는 장비 검증·분류 성능이 아니다 |
