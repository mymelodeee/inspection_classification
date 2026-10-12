E07 삼발이(lift pin) 합성 fixture (synthetic=true, seed=null, oracle `e07-lift-pin-1`, 2026-10-09). `python gen_e07_lift_pin.py`로 `e07_lift_pin.json`을 재생성한다. 생성기는 stdlib만 사용하고 production 코드를 호출하지 않는다.

**TEST-ONLY template (사내값 아님, 운영 profile로 복사 금지):** 반경 60mm(band [55,65]), phase 0°, 위치 0/120/240°, angular_tolerance 10°, radial_tolerance 5mm, min_support_per_lobe 3, frame notch_down, 시계방향 clock angle `degrees(atan2(x,y)) mod 360`.

| case | 구성 | 기대 feature_status / match_type | 핵심 기대값 (equal_per_lobe A1/A2/A3, phase 잔차) |
|---|---|---|---|
| LP-IDEAL | 0/120/240° r=60, lobe당 5점(1.5mm 이내) | matched / threefold_match (형상 template 일치, 원인 확정 아님) | 0 / 0 / 1, 0° |
| LP-SINGLE-BLOB | 0° r=60 한 곳에 15점(3x5 grid, 3.354mm 이내) | no_match (lobe 1개) | 1 / 1 / 1, 0° (A3 단독 판정 금지 반례) |
| LP-TWO-LOBES | 0/120°만, 240°는 검사됨·비어 있음 | candidate / partial_match | 0.5 / 0.5 / 1, 0° |
| LP-WRONG-RADIUS | 0/120/240° r=90 | no_match (반경 잔차 +30mm) | 0 / 0 / 1, 0° |
| LP-WRONG-PHASE | 40/160/280° r=60 | no_match (phase 잔차 40°) | 0 / 0 / 1, 40° |
| LP-UNCOVERED | 0/120°만, 240° 창(clock [220,260) x r [40,80])은 미검사 | candidate / partial_match + incomplete_coverage, 240°는 not_inspected(부재 아님) | 0.5 / 0.5 / 1, 0° |

점 단위 가중 A3(민감도용): 5점 lobe는 `(3+2cos(3·atan(1.5/r)))/5` → r=60: 0.998875995, r=90: 0.999500197; SINGLE-BLOB 0.994384916.

주의: lobe는 구성으로 정의된 support ID이며 lobe 탐색 알고리즘은 고정하지 않는다. Coverage 표현은 fixture 전용(TBD T-04, 현재 production coverage는 unknown). LP-UNCOVERED의 candidate vs insufficient_data는 계획서가 정하지 않았다(`decision_pending`); 고정 요구는 `must_not`과 `coverage_flag`다. 연계: E07, C09, C19, P2-05, P3-01, 계획 8.2.

Note (2026-10-09, main agent): the expected `matched` for LP-IDEAL presumes a calibrated template
(`signatures.lift_pin.calibrated: true`); uncalibrated templates report `candidate` (TBD T-17/T-22).
The no_match expectations of SINGLE-BLOB / WRONG-RADIUS / WRONG-PHASE presume FULL coverage (known);
with coverage unknown the result is `insufficient_data` (plan 16.2). Oracle numbers are unchanged.
