# Wafer Inspection Map 프로젝트 작업 지침

이 파일은 프로젝트 루트에 둔다. 목표는 인라인 검사 결함의 유형, 존, 시계방향, bin 분포를 분석하는 Python 프로그램이다. 기존 코드가 있으면 먼저 읽고 이어서 구현한다. 이 문서를 받았다는 이유만으로 전체 시스템을 한 번에 만들지 않는다.

## 0. 저장소 현황 (코드베이스 개요)

2026-10-10 후속 통합: UI의 단일/다중 모드 선택을 없애고 `batch_ui.render`를 공통 입력 화면으로 사용한다. 기본 YAML 경로는 자동 설정되며, 파일 1개도 같은 batch 경로를 사용한다. 결과의 상세보기는 `app.py`의 기존 맵·통계·검토 화면을 사용하고, 목록 복귀 시 업로드·선택·결과를 유지한다. 상세 중에도 입력 sidebar widget은 렌더링하여 파일 업로드가 소실되지 않게 한다. `tests/browser_demo.py`는 합성 자료로 보이는 Edge 시연을 실행하고 `demo_output/`에 독립 DB·증빙을 남긴다.

2026-10-10 입력 UI 보완: `wafer/ui_inputs.py`에 단일/일괄 공통 기본 profile 경로(`tests/profiles/dummy_die_local_test_profile.yaml`)와 입력 도움말을 둔다. 경로 파일은 매 분석 때 다시 읽고, batch UI는 profile 변경을 감지하면 목록을 재검증한다(core의 hash 불변 계약은 유지). batch UI의 전체 삭제·선택/제외는 업로드 메모리와 현재 결과에만 적용하며 원본 파일·DB 이력은 지우지 않는다. coverage·SQLite 시험 방법은 README의 해당 절 참조.

**현재 상태(Phase 1 합성 경로 구현 중):** `wafer/`(geometry, profile, aggregate, ingest, cli, clustering[DBSCAN, noise 보존], ring[환형 반지름·두께(P95−P5)·직경 측정], line[PCA 직선 측정·후보], detect[ring/line/local 검출기→지원 ID], groups[그룹 지원·고유 ID union 집계], lift_pin[삼발이 template 일치 — 기본 비활성], report[결과 스키마 검사·CSV export], store[SQLite 실행·검토 이력, append-only], app[Streamlit 검토 화면 — core(`cli.run_job`)만 호출], batch·batch_ui[여러 파일·폴더 일괄 분석: 입력 목록→고정 입력으로 `run_job` 순차 호출→개요·유형 요약·원시 정도 지표·갤러리·CSV/ZIP, SQLite에는 batch·구성원 연결 행만], stats[반경 밀도·Clark–Evans; coverage 미상이면 null, `--coverage` sidecar 입력 시 계산])와 `tests/`(합성 KLARF·F01 oracle·시험 profile 포함)가 있다. 실제 장비 KLARF, 사내 E1/E2·삼발이 정의, coverage는 없어 **`TBD.md`에 보류 항목(T-01~)을 관리하며 사용자 확인을 계속 요청한다.** 입력 처리는 합성 규약에서만 검증됐고 사내 입력 지원은 미완료다(실제 데이터 도입 시 입력 계약 재검증: 실행계획 5.3·19.3, TBD T-29). 완료 체크는 합성 증빙으로 충족되는 항목(P1-06, P2-02, P2-03, C01·C07·C08·C14 구현 검증)만 "합성 증빙" 표기와 함께 체크했고, 실제 장비·사내 정의·blind set·배포가 필요한 항목은 미완료다. 실행: `C:\Users\gongj\anaconda3\envs\insenv\python.exe -m pytest tests -q`(브라우저 E2E 제외 시 `-m "not e2e"`; E2E는 시스템 Edge를 Playwright로 사용, 브라우저 다운로드 불필요), CLI `python -m wafer.cli <klf> --profile tests/profiles/f01_test_profile.yaml [--out result.json] [--csv-dir out/] [--db runs.db] [--coverage sidecar.json]`(합성 KLARF 1.8: `klarf_dummy_data/` + `tests/profiles/dummy_die_local_test_profile.yaml`), UI `python -m streamlit run wafer/app.py`. Claude Code 도구: 서브에이전트 3개(`.claude/agents/`), 프로젝트 스킬 `/wafer-verify`·`/wafer-contract-audit`(`.claude/skills/`), Playwright MCP(`.mcp.json`, 시스템 Edge·isolated, 첫 사용 시 `claude`에서 프로젝트 MCP 승인 필요) — `CLAUDE_CODE_TOOLING_GUIDE.md`. (구조가 바뀌면 이 절을 갱신한다.)

| 파일                                                  | 역할                                                                                                                                                                                                                                                                                                                                             |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `CLAUDE.md`                                           | 작업 지침(이 파일). 우선순위·분석 계약·작업 흐름·보고 형식                                                                                                                                                                                                                                                                                       |
| `wafer_inspection_execution_plan.md` (v1.1 + 2026-10-09 보완) | **구현 기준 문서.** 1~4절 범위·구조·Phase 0~4 일정, 5~8절 데이터/좌표/특징/rule 상세(삼발이, E1/E2, 100mm zone), 9절 YAML 계약 초안, 10절 결과 JSON, 11~13절 검증·ML·배포, 16절 공통 계약(상태 필드, 개수 규칙), 17절 완료 체크리스트(P0~P4 ID), 18절 위배 검증표(C01~C20), 19절 E2E 시나리오(F01 fixture, E01~E24), 20절 실행 기록·release 판정 |
| `wafer_inspection_map_knowledge.md`                   | 배경 지식·문헌(R1~R11, T1~T6). inspection map vs 전기적 WBM 차이, 분류 체계, 이미지 추출, 시계방향/sector 식, 모델 선택. 입력 우선순위·분석 단위는 실행계획이 우선                                                                                                                                                                               |
| `requirements.txt`                                    | 범위 지정 직접 의존성(CPython 3.11/3.12). klarfrs==0.2.1, numpy/pandas/scipy, scikit-learn, opencv-python-headless, shapely, pydantic, PyYAML, plotly/matplotlib/streamlit, pytest/playwright. fastapi·xgboost·torch는 주석 처리된 선택 항목. 락파일이 아님                                                                                      |

### 계획된 아키텍처 (실행계획 3·13절)

`KLARF → 파싱·좌표·노치 정합 → 표준 좌표(mm, 중심 원점, +X 우, +Y 상, notch 6시)·bin·coverage → 공간 통계 → 국부 cluster(DBSCAN)·전역 ring/line 후보 → 형상 판정·signature group → zone/시계방향/bin 집계 → JSON/CSV/리포트`. 이미지 입력은 원본 좌표가 없을 때만 쓰는 제한적 보조 경로다.

- 판정 단위 4층: `defect` → `cluster` → `signature_group` → `wafer_summary`. 라벨 축은 `morphology / zone / signature_match / review_status`로 분리한다.
- 책임 구분 예시(필요한 것만 생성): ingest, geometry, coverage, grid, features, clustering, signatures, rules, model, report, interface(CLI → Streamlit → 필요 시 FastAPI).
- 구현 순서: 원본 파싱 → 좌표 검증 → 개수/bin 집계 → CLI → 특징/rule → 리포트 → UI. 첫 완성 목표는 "KLARF 한 파일로 defect/bin count 보존 + 노치 6시 map + 12 sector 표를 출력하는 CLI"이다.
- 명령: 아직 확정된 빌드/실행/테스트 명령이 없다. 6절의 환경 명령만 유효하며, 구현 후 실제 명령을 6절에 기록한다.

## 1. 최우선 수칙

1. **오버엔지니어링 금지.** 현재 요청한 기능을 만족하는 가장 작은 구현을 선택한다. 미래 기능을 위한 추상화, 미사용 모듈, 불필요한 의존성은 만들지 않는다.
2. **변경 전 테스트 시나리오의 최신성을 확인한다.** 구형 계약, 폐기된 경로, 변경된 스키마, 누락된 경계값을 확인하고 근거가 있는 항목만 개정한다.
3. **코드 수정 후 상호 위배 여부를 검증한다.** 요구사항, 코드, YAML, 테스트 기대값, 결과 스키마, UI/리포트가 같은 계약을 따르는지 확인한다.
4. 구현과 검증을 모두 마친 범위만 완료로 보고한다. 문서 작성, mock 통과, 의존성 해석 성공을 실제 분석 또는 E2E 통과로 표시하지 않는다.

## 2. 기준 자료와 충돌 처리

작업 시작 시 다음 파일을 읽는다. 다른 폴더에 있으면 `rg --files`로 실제 위치를 찾는다.

1. `wafer_inspection_execution_plan.md`: 단계별 범위, 완료 체크, C01~C20 위배 검증, F01 fixture 명세, E01~E24 E2E 시나리오.
2. `wafer_inspection_map_knowledge.md`: 배경 지식, 문헌, 알고리즘의 적용 한계.
3. `requirements.txt`: 현재 의존성과 선택 기능, 환경 조건. 범위 지정 파일이며 완전한 배포 lockfile이 아니다.
4. 기존 README, 적용되는 작업 지침, 코드, YAML profile, 테스트 및 CI 설정.

사용자의 최신 명시적 요구사항을 반영한다. 외부 라이브러리 문서로 사내 E1/E2 또는 장비 좌표 정의를 덮어쓰지 않는다. 충돌을 발견하면 파일·항목·충돌 내용·해결 근거를 기록한다. 검증을 통과시키려고 규칙을 임의 삭제하지 않는다. 정의가 불명확한 부분은 보류하고 독립적으로 구현 가능한 범위를 진행한다. 필요한 자료나 결정만 구체적으로 요청한다.

## 3. 구현 범위와 단순성

1. 우선 순서는 **원본 파싱 → 좌표 검증 → 개수/bin 집계 → CLI → 특징/rule → 리포트 → 필요한 UI/배포**다. 처음에는 한 장비 export 계열과 한 제품/공정 범위를 검증한다.
2. MVP는 NumPy 좌표·집계와 해석 가능한 rule을 사용한다. 내부 라벨과 비교 근거가 생긴 뒤 RandomForest 등의 ML을 검토한다. CNN/ViT, 공개 EDS 사전학습은 후속 작업이다.
3. 단일 Python 프로젝트와 공통 분석 core를 기본으로 한다. CLI와 UI에서 분석 로직을 복제하지 않는다. `io/grid/features/rules/model/report`는 책임 구분 예시이며 빈 모듈을 모두 생성할 의무가 아니다.
4. 일반 함수와 필요한 작은 데이터 구조부터 쓴다. 실제 중복이나 확장 요구가 생기기 전에는 범용 plugin framework, factory/registry, DI framework를 추가하지 않는다.
5. 현재 요구가 없는 microservice, 분산 queue, Kubernetes, 외부 DB, 모델 관리 플랫폼을 도입하지 않는다. 저장이 필요하면 실제 조회·이력 요구에 맞춰 파일 또는 SQLite부터 검토한다.
6. 먼저 CLI를 완성하고 필요한 경우 Streamlit을 붙인다. FastAPI는 사내 HTTP 연동이 요구될 때 추가한다. API 전용 의존성과 PyTorch는 필요할 때만 활성화한다.
7. 변경과 무관한 재작성, 대규모 리팩터링, 파일 이동, 스타일 변경을 묶지 않는다. 기존 사용자의 변경을 보존한다.
8. 새 의존성은 필요한 이유와 표준 라이브러리/기존 패키지로 해결할 수 없는 이유를 설명한다. 패키지가 설치되어 있다는 이유로 모두 사용하지 않는다.

## 4. 반드시 보존할 분석 계약

1. **KLARF 우선.** 원본 결함 이벤트 좌표와 bin이 기준이다. 이미지는 overlay와 검증, 원본이 없는 경우의 제한적 fallback이다. 이미지 dot 수를 원본 이벤트 수로 대체하지 않는다. 알 수 없는 bin·mm scale·방향을 생성하지 않는다.
2. **좌표 변환은 장비별 검증.** 단위, die index/pitch, 상대좌표, sample center, 축 방향, front/back side, notch를 adapter에서 해석한다. 표준 좌표는 wafer 중심 원점, mm, +X 오른쪽, +Y 위쪽, notch 6시다. Orientation 값만으로 mirror 여부를 추정하지 않는다. 이중 회전을 막는다.
3. **물리 방향이 없으면 방향 판정을 보류.** 단위·중심 등이 검증되면 가능한 반경 집계는 제공할 수 있다. 물리 시계방향과 설비 template phase는 부족한 정보를 임의 보완해 확정하지 않는다.
4. **시계방향 정의를 고정.** `theta = degrees(atan2(x, y)) mod 360`: 0°=12시, 90°=3시, 180°=6시, 270°=9시. Sector는 시각 중심 ±15°다. 설정된 중심 제외 영역은 center로 따로 집계한다. 원형 각도 평균과 경계 wraparound를 사용한다.
5. **개수 보존.** `N_parsed = N_included + N_excluded`; 제외 ID와 사유를 남긴다. Unknown bin을 포함한 bin 합계는 N_included다. 방향 분석이 유효하면 12 sector 합 + center = N_included다. DBSCAN noise도 원본 집계와 다른 검출기에 남긴다.
6. **이벤트와 die를 구분.** 동일 좌표의 서로 다른 유효 이벤트를 삭제하지 않는다. 검사/record 식별자를 포함한 키를 사용한다. Defect count와 affected die count를 구분하며, 검사 die 분모 없이 불량 die 비율을 만들지 않는다.
7. **군집과 시그니처를 구분.** Cluster별 분석과 여러 cluster를 묶는 signature group을 지원한다. Ring/line은 DBSCAN 군집 밖에서도 후보를 찾을 수 있다. 형상, zone, 설비 signature는 별도 축이며 혼합형을 보존한다. 중첩 group/zone 총수는 고유 이벤트 ID의 union으로 계산한다.
8. **무작위성 검정은 차단 gate가 아니다.** 비유의 결과를 정상으로 단정하거나 후속 후보 검출을 중단하지 않는다. 검사 coverage 미상은 면적 보정 density와 의존 검정을 계산 불가로 표시한다. 비검사 영역을 0 density로 채우지 않는다.
9. **사내 정의는 YAML.** E1/E2, r=100mm 내부/경계, 삼발이 반경·위상·허용오차는 확인된 profile로만 활성화한다. 미정 기능은 기본 비활성이다. 100mm를 101.6mm로 치환하지 않는다. 기본 구간은 [하한, 상한), 100mm 경계 band는 계획의 양끝 포함 예외를 따른다. 시험용 값은 운영값으로 복사하지 않는다.
10. **삼발이와 원인을 과장하지 않는다.** k=3 고조파만으로 삼발이를 확정하지 않는다. 세 lobe, 120° 간격, 반경, 위상, coverage를 함께 확인한다. 두 lobe/부분 관측은 candidate 또는 보류다. 형상 match는 공정 원인의 확증이 아니며 평면 XY로 bevel side를 확정하지 않는다.
11. **실행·데이터·판정 상태를 분리.** Job 상태와 `matched/candidate/no_match/unknown/insufficient_data/disabled` 등을 혼용하지 않는다. 활성 기능의 필수 설정 누락은 `CONFIG_INVALID`; 정상 설정에서 입력만 부족하면 가능한 결과와 기능별 보류 사유를 반환한다. 계산 불가의 null과 실제 0을 구분한다.
12. **재현성과 이력 보존.** Source hash, code/parser/adapter/config/rule/model version, 필요한 seed를 기록한다. 저장·검토 기능 구현 시 예측 원본과 review revision을 분리하고 재시도·재분석·rollback이 과거 결과를 지우지 않게 한다.

## 5. 매 작업의 필수 흐름

### 변경 전

1. 요청 범위와 현재 구현 상태를 확인한다. 적용되는 지침, 기존 변경, 관련 모듈과 테스트를 읽는다.
2. 작업에 해당하는 P/EX/RL 완료 항목, C 검증 항목, E 시나리오를 연결한다. 모든 단계의 기능을 동시에 구현할 필요는 없다.
3. 아래 최신성 확인을 수행하고, 가장 작은 수정 범위와 검증 방법을 정한다. 좌표·집계·상태 계약이 바뀌는 작업은 독립 정답을 먼저 확정한다.

### 테스트 최신성 확인 및 업그레이드

1. 시나리오의 입력 형식/스키마, feature 활성 범위, YAML key/경계 규칙, 오류/보류 상태, CLI/UI/API 경로, 의존성·실행 환경이 현재 구현 및 승인된 요구사항과 맞는지 확인한다.
2. Fixture가 실제 파일인지 명세만 있는지, 정답 출처·버전·단위·coverage·orientation이 명시됐는지, mock과 실제 검증이 구분됐는지 확인한다.
3. 오래됐다는 판단은 날짜만으로 하지 않는다. **원래 유효한 계약을 코드가 위반하면 코드를 고친다.** 승인된 사양 변경이나 실제 인터페이스 변경으로 시나리오가 구형이면 테스트와 관련 문서를 함께 개정한다.
4. 변경한 시나리오에는 기존/신규 기대값, 변경 사유, 요구사항 근거, fixture/oracle 버전, 연계 E/C ID를 남긴다. 기존 ID는 보존하고 변형은 `E02-UP` 같은 하위 ID로 추가한다.
5. 실패를 숨기기 위한 assert 삭제, 근거 없는 허용오차 확대, skip/xfail 추가, 구현 결과를 그대로 golden 정답으로 복사하는 행위를 금지한다. 정당한 제외는 범위와 사유를 기록한다.
6. 예상값은 독립 계산, 도메인 검토 또는 검증된 실제 자료에서 얻는다. Production 함수를 호출해 그 함수의 정답을 생성하는 순환 검증을 피한다.

### 구현 및 수정 후 검증

1. 필요한 코드와 설정을 최소 범위로 수정한다. 중요한 버그는 먼저 재현하고 수정 후 다시 확인한다. 기존 계약을 깨면 관련 호출부, 스키마, 문서, 시나리오를 함께 수정한다.
2. 변경된 계약별로 **요구사항 ↔ 코드 ↔ 설정 ↔ 테스트 기대값 ↔ 리포트**를 대조한다. 연계 C 항목을 확인하고 새 충돌이 생기지 않았는지 diff를 검토한다.
3. 영향받는 테스트와 연결된 통합/E2E 하위 case를 실행한다. 독립 숫자 정답과 경계값을 검증하는 테스트를 우선한다. 단순 구현 복제 테스트나 의미 없는 테스트 수 늘리기는 하지 않는다.
4. 영향이 넓거나 배포 단계면 해당 범위의 회귀 및 release gate를 실행한다. UI/API가 구현되지 않은 CLI 시험을 전체 E16 E2E 통과라고 부르지 않는다.
5. 실패가 남으면 원인을 고치고 영향받는 검증을 다시 수행한다. 실제 장비 샘플이나 실행 환경이 없으면 BLOCKED/NOT_RUN과 필요한 자료를 기록한다. 합성 fixture 검증은 별도로 완료할 수 있다.
6. 실제 수행한 검증의 명령, 환경, 결과, 증빙을 남긴 뒤 해당 완료 체크만 갱신한다. 체크박스만으로 통과를 대신하지 않는다.

### 실행 환경과 검증 명령

1. 이미 준비된 프로젝트 가상환경을 사용한다.
2. 현재 개발 환경 이름은 `insenv`(conda, `C:\Users\gongj\anaconda3\envs\insenv\python.exe`, Python 3.12)이다.
3. 사용자별 환경 이름이 다르면 실제 이름 또는 Python 실행 경로를 사용한다.
4. 환경 이름을 애플리케이션 코드에 하드코딩하지 않는다.
5. 기존 환경이 준비되어 있으면 새 venv 생성이나 requirements 재설치를 매 작업마다 수행하지 않는다.
6. 실행 전 Python 경로와 버전을 확인하고, 설치·앱 실행·테스트에 동일한 환경의 Python을 사용한다.
7. 의존성이 변경되었을 때만 해당 환경에서 필요한 설치를 수행한다.
8. 별도 환경은 의존성 변경 실험이나 깨끗한 설치·CI 재현 검증이 필요할 때 준비한다.

## 6. 테스트 및 실행 기준

기존 프로젝트에 확정된 명령이 있으면 그것을 사용한다. 초기 환경 명령은 다음과 같다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -m pytest <영향받는_실제_테스트_경로> -q
```

1. 위 테스트 경로는 자리표시자다. 실제 테스트 파일을 확인한 뒤 실행한다. 전체 `python -m pytest -q`는 통합 확인 또는 release 범위에 맞춰 사용한다. 테스트 파일이 없으면 테스트 통과라고 보고하지 않는다.
2. 기본 대상은 64-bit CPython 3.11/3.12다. 대상 OS의 parser wheel/glibc 조건은 requirements 주석과 실제 환경에서 확인한다. 다른 환경을 지원하려면 근거와 실행 증빙을 추가한다.
3. OpenCV는 `opencv-python-headless` 한 배포판만 사용한다. 현재 Browser E2E(`tests/test_e2e_browser.py`, marker `e2e`)는 Python Playwright로 **Windows 시스템 Edge**(`channel="msedge"`)를 사용하므로 별도 browser 다운로드가 필요 없다. Edge를 띄울 수 없으면 해당 테스트는 "BLOCKED" 사유로 skip되며 PASS로 계산하지 않는다. Linux CI 등 Edge가 없는 환경은 실제 image에서 browser 준비 방법을 따로 확인한다.
4. 배포 lock은 격리된 목표 환경에서 검증 후 생성한다. 기존 작업 환경의 무관한 패키지를 `pip freeze`로 통째로 넣지 않는다. 신규 정적 분석 도구는 프로젝트에 없으면 검증 명령만 만들지 않는다.
5. **첫 검증 기준은 계획의 F01/E01이다.** 이미지 없이 included=8, B1=3/B2=3/B3=2(출력 bin 표기는 "1"/"2"/"3", T-04), center=1, 12시=1/3시=4/6시=1/9시=1을 독립 기대값과 대조한다. F01은 좌표·집계용이며 형상 정답을 강요하지 않는다.
6. 초기 핵심 회귀는 E02 좌표/side, E03 빈 입력/center, E04 noise 보존, E08 경계, E09 이벤트/bin, E10 정보 부족, E11 coverage, E12 설정, E13 파일 오류다. 형상 rule 추가 시 E05~E07/E14/E23을 연결한다.
7. UI/export는 E15/E16, 저장·검토는 E17~E19, 성능/실제 평가/배포는 E20~E22, 후속 ML/repeater/gripper는 E24의 적용 case를 실행한다. 상세 입력·정답·통과 기준은 실행계획을 따른다.
8. 시험 상태는 `PASS/FAIL/NOT_RUN/BLOCKED/N/A`다. 비활성·범위 제외 기능만 근거 있는 N/A로 둔다. 활성 기능의 실패/자료 부족을 N/A로 숨기지 않는다. 상위 시나리오는 필수 하위 case를 모두 통과해야 PASS다.
9. 실제 샘플 검증, 합성 fixture 시험, mock 흐름 시험, 문서 검토를 분리 보고한다. 합성 통과를 장비 adapter 검증이나 실제 분류 성능으로 표시하지 않는다.
10. 공개 WM-811K/MixedWM38은 EDS 자료다. 내부 인라인 성능으로 대신 보고하지 않는다. ML 활성화 시 lot/time 분할과 blind set 누출을 점검하고 방향 계약을 깨는 회전·반전을 제한한다.

## 7. 자료 취급과 변경 안전성

1. 사내 KLARF, wafer/lot ID, 경로, 고객 정보, 라벨을 외부 서비스에 전송하지 않는다. 테스트 자료를 저장소에 넣을 때 승인된 비식별 fixture를 사용한다.
2. Secret은 코드·YAML·로그·테스트 결과에 남기지 않는다. 파싱·설정 오류는 원인과 위치를 보여주되 불필요한 원본 내용을 로그에 출력하지 않는다.
3. 로컬 구현과 검증은 요청 범위에서 진행한다. 운영 배포, 데이터 삭제, 외부 전송은 별도 승인 없이 수행하지 않는다. 실제 배포 전에 테스트와 검토 가능한 변경을 준비한다.

## 8. 작업 종료 보고와 완료 기준

다음 형식으로 간결하게 보고한다. 별도 대형 검증 프레임워크를 만들 필요는 없다. 기존 실행계획의 증빙 표 또는 작업 기록을 활용한다.

1. 변경 내용과 목적, 이번에 구현한 범위.
2. 테스트 최신성 확인 결과: 개정 여부, 관련 E ID, 사유와 정답 근거. 변경이 없으면 확인한 범위를 명시.
3. 상호 위배 검증 결과: 적용 C ID, 확인한 계약, 발견한 충돌과 해결 또는 남은 문제.
4. 실행 명령·환경·PASS/FAIL/NOT_RUN/BLOCKED/N/A 및 증빙. 미실행 항목은 이유와 다음 조건.
5. 갱신한 완료 체크 ID와 남은 자료/결정.

**완료란 요청한 범위의 구현, 필요한 시나리오 개정, 수정 후 계약 정합성 확인, 적용 테스트 실행 및 증빙 기록까지 마친 상태다. 알려진 핵심 실패나 미검증을 숨긴 채 완료로 선언하지 않는다.**
