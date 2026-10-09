# 추가 확인 필요 사항 (TBD)

실제 장비 KLARF export, 사내 정의, 계획서 모호 지점 중 **사용자 확인 전까지 구현하지 않고 보류**한 항목이다.
해결되면 상태를 갱신하고 관련 E/C 시나리오를 재검토한다. 이 파일은 계획서(`wafer_inspection_execution_plan.md`)를 수정하지 않는 별도 기록이다.
최종 갱신: 2026-10-09

| ID | 상태 | 항목 | 현재 처리 | 필요한 자료/결정 | 연계 |
|---|---|---|---|---|---|
| T-01 | 결정됨 | KLARF 파서: klarfrs 0.2.1은 DefectList를 조용히 누락·이동·생성함(개수 토큰을 열로 취급, EndOfFile 줄을 결함으로 읽음, 변환 실패→0). 실제 장비 파일에서 재확인 필요 | `wafer/ingest.py`의 자체 엄격 파서 사용(개수·열·숫자·종료 검증). klarfrs는 사용하지 않음 | 실제 KLARF 1~2개로 문법(다중 wafer, 행 종료 `;`/`,`, 소문자, ClassLookup 등) 확인. 대안 klarfio는 GPLv3라 사내 반입 기준 확인 필요 | P0-01, E13 |
| T-02 | 열림 | 좌표 변환 공식: die origin(index×pitch)+XREL/YREL, SampleCenterLocation, 단위(µm/mm) | 합성 adapter만 구현(단일 die, 원점=wafer 중심, µm→mm). 0이 아닌 SampleCenterLocation/DieOrigin은 `AdapterUnsupported` | 실제 export의 필드 의미, 화면과 대조할 기준점 몇 개 | P0-02, P1-02, E02 |
| T-03 | 열림 | 방향·side: 노치 위치, front/back, mirror, 이미 정규화된 export 여부 | notch=DOWN, CoordinatesMirrored=NO만 허용. 그 외는 추정하지 않고 `UNSUPPORTED_ADAPTER` | 장비별 축 방향·side 표기 규칙, 노치 변환 검증 샘플 | P0-02, E02, E10, C03/C04 |
| T-04 | 열림 | Bin 매핑: CLASSNUMBER의 사내 의미(ADC/review class 등), 0의 의미 | 합성: 1/2/3→B1/B2/B3, 0→unknown (사내 매핑 아님) | 실제 CLASSNUMBER 정의와 bin 매핑 버전 | P0-02, E09 |
| T-05 | 열림(방침 결정) | 검사 coverage / 검사 die 목록 / sampling. **방침(2026-10-09): coverage 미상이면 밀도·의존 검정은 null+사유(안 a). profile 선언(안 b)은 채택 안 함** | density·affected die 비율은 null. 실제 coverage 정보는 입력 자료 확인 필요 | scan ROI(edge exclusion 폭 포함), 제외 영역, 검사 die 목록 위치(KLARF SampleTestPlan 여부) | P0-03, E11, C06 |
| T-06 | 재정의됨(2026-10-09) | **band 폭**: 사용자 정의 = 환형(ring) 결함이 관찰될 때 그 환형의 두께(폭)이며 100mm와 무관한 **측정량**. band 모양 원이 나오면 중심으로부터 반지름(또는 직경)을 구할 수 있어야 함 | Phase 2 ring 검출기의 출력으로 구현(중심반경·내/외경·폭·직경). 100mm 경계 태그(`zone_8inch_boundary.band_width_mm`)는 별도 설정으로 유지, 기본 비활성, 시험값만 존재 | 사용 결정됨(2026-10-09: 계속 사용). 폭 값과 목적만 TBD | P0-05, E05, E06, E08 |
| T-07 | 일부 해결 | E1/E2 **metric = edge 거리(distance_from_edge_mm)** 확정(중심 반경 아님). **실제 구간 값·경계 포함 규칙은 사내 규정 확인 후 갱신 예정** | profile에서 E1/E2 metric은 edge 거리로 고정(다르면 CONFIG_INVALID). 기본 비활성, 시험 profile 값은 시험 전용 | 사내 규정 값 | P0-05, E08, C12 |
| T-08 | 열림 | 삼발이 template: 반경, 위상, 허용오차, 좌표 기준 | 합성 시험 template로 구현(`wafer/lift_pin.py`, T-25). 사내 template 없음 → 기본 비활성 | 설비 template, 적용 공정/설비 | P0-05, E07 |
| T-09 | 열림 | 중심 제외 반경(center exclusion), 경계 tolerance·snap 정책 | 시험 profile 1mm만 사용. null이면 clock 결과는 null | 운영 값과 근거, 좌표 분해능 | P0-02, E08 |
| T-10 | 결정됨(기본안) | 계획서 문구 충돌: 상태 어휘(8.1 vs 16.2), INVALID_INPUT 대응, "허용되지 않은 zone 중첩" | 16.2절 기준 / INVALID_INPUT = job failed + data_quality invalid / 같은 계층(E1·E2끼리)만 금지 | 계획서 개정 여부(현재 미개정) | C05, E03, E12, E13 |
| T-11 | 해결 | `wafer_radius_mm` 키 신설 | 사용자 승인(2026-10-09). 계획서 9절 YAML 예시에는 아직 미반영(계획서 미개정) | — | E12 |
| T-12 | 열림 | 다중 wafer/lot KLARF, 복수 inspection 묶음 | 첫 구현은 단일 wafer만 | 실제 파일 구성 | E09 |
| T-14 | 열림 | CLI 오류 코드·종료코드 체계: 0 성공 / 2 CONFIG_INVALID / 3 INVALID_INPUT·UNSUPPORTED_ADAPTER / 4 INPUT_NOT_FOUND. UNSUPPORTED_ADAPTER는 입력 불량이 아니므로 data_quality_status를 생략. 계획서 16.1은 방향·단위 미상 시 가능한 원본 집계를 요구하나 현재는 job 전체를 실패시킴 | 임시 체계(계획서 미정의) | 코드 체계 승인, 미지원 adapter 시 부분 결과(원본 집계) 반환 여부 | C05, C15, E10, E13 |
| T-15 | 일부 해결 | zone metric 기본값은 E1/E2=edge 거리로 확정(T-07). 지원 FileVersion `1 2`는 근거 없이 코드에 있음. SampleSize(헤더)와 wafer_radius_mm 일치 검사 없음 | 합성 한정 | 지원 버전 범위(P0-01), 크기 불일치 처리 | C12, E12 |
| T-16 | 열림 | affected_die_count: 합성 adapter는 단일 pseudo-die라 의미 없음 | null로 출력 | die 좌표 규칙(T-02)과 검사 die 목록(T-05) | C02, C06 |
| T-17 | 열림 | **두께 = P95−P5, 사용자 결정 2026-10-09**(이상점에 강건; 극단값 r_max−r_min은 `radial_extent_mm`로 별도 유지). 측정 키는 `ring_thickness_mm`로 정함(승인 대기). **원 fit 한계**: Kasa 대수 fit은 짧은 호/두꺼운 band에서 편향(RB-ARC 90° 호 자유 fit: 중심 약 (1.96,1.62), 반지름 약 77.8 vs 정답 (0,0), 80) → 부분 호 fit은 **NOT_RUN/미검증**, 중심을 알 때만 호 측정. ring/arc/blob **분류 threshold**(최대 각도 공백, 최소 span, 폭 대비 반지름, 원 fit 허용오차)와 ring 폭 측정 키 이름(profile의 `band_width_mm`와 혼동 방지를 위해 `ring_thickness_mm` 등 별도 이름 권장) | `wafer/ring.py`는 측정만 수행(반지름·내외경·두께·직경·각도 점유). 분류는 미구현 | threshold 값과 근거(calibration 자료), 키 이름 승인 | E05, E06, P2-04 |
| T-18 | 해결(구현) · 해석 확인 대기 | 15°/345°(및 모든 sector 경계) **허용오차 ±5°, 변경 가능**(`clock.boundary_tolerance_deg`, 기본 5.0, 0 ≤ 값 < 15). **계산에 반영(2026-10-09 사용자 지시)**: ① `sectors_clock` = 엄격 분할(합 + center = N_included 유지), ② `sectors_clock_tolerant` = 경계 ±tol 이내 점을 자기 sector와 **인접 sector 양쪽**에 집계(합은 N을 초과 가능, `n_multi_sector`로 차이 표시, 고유 점 수는 N), ③ `boundary_ambiguous`(ID·개수 표시), ④ `ring.angular_coverage`의 `occupied_hours_tolerant`(**`max_gap_deg`/`span_deg`와 `classify_ring` 라벨은 strict** — 허용오차를 판정에도 쓸지 결정 필요). `sum(tolerant) = N_included − center + n_multi_sector`(분할 아님). 함수: `geometry.neighbor_hour/near_sector_boundary`. **사용자 결정(2026-10-09): 허용오차는 판정(라벨·각도 span)에 반영하지 않음 — 이 항목은 추가 확인 필요로 유지.** 확인 필요: "인접 sector 양쪽 집계" 해석이 의도와 같은지(대안: 경계 점 제외, 가중 분배), ring 점유율 bin에도 적용할지 | 해석 승인 | T-09, E08 |
| T-19 | 열림 | **각도 점유율 bin 크기와 점 간격의 상호작용**(E06 발견): 15° 간격 ring을 10° bin으로 재면 점유율 24/36=0.67(<ring_min 0.8 → arc), 30° bin이면 1.0(ring). bin 크기·ring_min_occupancy는 함께 보정해야 함. bin 경계 위 점은 부동소수 잡음(1e-9°로 반올림)으로 결정론화함 | 보정 자료로 bin 크기·임계값 결정(T-17과 함께) | E06, T-17 |
| T-20 | 열림 | `shapes.ring.calibrated: true`는 자기선언 불리언 — 보정 근거(자료 ID·날짜·승인자)와 연결되지 않음. 운영 profile에서 true로 바꾸는 절차(보정 보고서 첨부, 승인) 필요. E06은 **부분**: 그룹 산술만 검증, 검출기→support 연결 미구현 | 승인 절차 정의 | E06, T-17 |
| T-21 | 열림 | line 분류 임계값: `shapes.line.min_points / max_relative_width / max_gap_ratio` (ring과 동일하게 내부 라벨로 보정, 코드 기본값 없음). 두께·폭 정의는 ring과 같이 P95−P5(정규 거리) | 보정 자료 | E05, T-17 |
| T-22 | 열림 | 검출기 탐색 파라미터: `detect.ring_radial_tol_mm`(ring 지원 반경 허용), `detect.line_inlier_mm`(직선 inlier 거리), `detect.line_ransac_trials`. 현재 ring 검출은 **wafer 중심 기준 반경 밀도 최대 지점 하나**만(중심이 어긋난 ring, 다중 ring은 미구현), line은 최대 inlier 직선 하나만 | 보정 자료, 다중/offset ring 필요 여부 | E05, E06 |
| T-23 | 열림 | `data_quality_status` 판정 기준(16.2에 없음). 현재 성공 job은 항상 `valid`. 기본안: coverage 미상·지원 범위 밖 정보가 있으면 `degraded` | 사용자 결정 | C15, E10, E11 |
| T-24 | 결정(임시) | 통계 항목 상태 키는 `calc_status`(computed / insufficient_data / disabled)로 판정용 `feature_status`(16.2)와 분리. 결과 요약 라벨 `pattern_summary`는 8.1 어휘(no_detected_defect / no_clear_pattern / 후보 라벨 목록). CLI 종료코드에 5=INTERNAL_ERROR 추가(T-14) | 계획서 16.2 개정 여부 | C15, E03 |
| T-25 | 열림 | 삼발이(lift pin) 판정 정책(합성 template로 구현, `wafer/lift_pin.py`): ① 세 위치 모두 지지 → `threefold_match`, template `calibrated: true`일 때만 `matched`, 아니면 `candidate`(ring/line과 동일 정책) ② 두 위치 → `candidate`+`partial_match`, 빈 위치는 coverage에 따라 `incomplete_coverage`(미검사)/`coverage_unknown`/`inspected_empty` ③ 1개 이하 → `no_match`(사유: 반경 band 내 점 없음, 위상 불일치, lobe 부족). A3는 특징값으로만 출력. ④ lobe 인정 조건: 창 안 점 수 ≥ min_support_per_lobe **그리고** 나머지 band 대비 밀도비 ≥ `min_lobe_contrast`(신규 키, 균일 ring을 삼발이로 오인 방지) **그리고** lobe 평균 반경이 band 중심 ± radial_tolerance_mm ⑤ 0~1 lobe에서 미관측 위치의 coverage가 미상/미검사면 `insufficient_data`(16.2), coverage가 알려진 경우만 `no_match` ⑥ 반경 band는 기본 규칙 [하한, 상한) ⑦ `calibrated` 자기선언 문제는 T-20과 동일. 결정 필요: 2개 관측+1개 미검사를 `candidate`로 둘지 `insufficient_data`로 둘지(계획서 미정), `min_lobe_contrast` 값, band 경계 규칙 확인, coverage 입력 schema(T-05), 사내 template(T-08) | 사용자 결정 | E07, C09, C19 |
| T-13 | 열림 | 성능 목표, blind set, 정상 참고군, 유형 지표(P0-06) | 없음. E20/E21은 BLOCKED | Phase 0 합의 | P0-06, E20, E21 |

## T-06 정리 (2026-10-09 사용자 답변 반영)

- 이전 해석(100mm 원 둘레의 띠)은 **폐기**한다. band 폭은 100mm 기준선과 무관하다.
- band 폭 = 환형 defect 패턴의 **두께**(정의: 중심 기준 거리의 P95−P5, 극단값 아님). ring 검출 결과로 다음을 출력해야 한다: 중심(wafer 중심 또는 offset), 중심선 반지름, 내/외 반지름, 폭(두께), 직경, 각도 점유 범위.
- `zone_8inch_boundary`(100mm 근처 tag)는 별개 기능으로 남기되 값은 TBD이며 기본 비활성이다. 사용 목적이 불필요하면 제거 여부를 알려 달라.
