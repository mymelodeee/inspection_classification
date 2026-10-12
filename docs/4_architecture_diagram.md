# 4. 아키텍처 다이어그램

- 기준: `wafer/` 코드의 실제 import·호출 관계(2026-10-11). 계획 단계 구조(이미지 경로, API, 배포)는 실행계획 3·13절이며, 아래 그림에는 **구현된 것만** 그리고 미구현은 점선·주석으로 구분한다.
- 원칙: 분석 core는 하나(`wafer.cli.run_job` → `analyze_file`)이고 CLI·화면·일괄 분석이 모두 이것을 호출한다. 화면에는 분석 로직이 없다.

## 1. 시스템 구성(실행 환경)

```mermaid
flowchart LR
  user["사용자"] -->|브라우저| ui["Streamlit 앱<br/>wafer/app.py + batch_ui.py"]
  user -->|터미널| cli["CLI<br/>python -m wafer.cli"]
  ui --> batch["일괄 orchestration<br/>wafer/batch.py"]
  batch --> core["분석 core<br/>cli.run_job / analyze_file"]
  cli --> core
  core -->|읽기| inp[("KLARF 파일<br/>profile YAML<br/>coverage sidecar JSON")]
  core -->|선택| db[("SQLite")]
  core -->|선택| files[("result.json<br/>CSV·manifest.json")]
  ui -->|다운로드| dl[("JSON·CSV zip<br/>batch CSV·ZIP")]
  api["HTTP API (미구현)"] -.-> core
  img["이미지 입력 (미구현)"] -.-> core
```

- 화면은 core를 직접 부르지 않고 `batch.py`를 거쳐 `run_job`을 호출한다(파일 1개도 같다).
- SQLite 쓰기 주체: `run_job` → `runs`·`attempts`, `batch.py` → `batches`·`batch_members`, 상세 화면(`app.py`) → `reviews`. 모두 `store.py` 함수를 쓴다.
- 단일 프로세스·로컬 실행이다. queue·worker·외부 DB·인증은 없다.
- 업로드 파일은 서버 메모리에서 읽고 위치 번호 이름의 임시 파일에만 쓴 뒤 지운다. 업로드 이름을 경로로 쓰지 않는다. "또는 KLARF 경로" 입력은 **서버**의 파일을 읽는다.

## 2. 모듈 의존 관계

```mermaid
flowchart TD
  app["app.py<br/>상세·검토 화면"] --> batch_ui["batch_ui.py<br/>통합 입력·일괄 화면"]
  app --> store
  app --> report
  batch_ui --> batch["batch.py"]
  batch_ui --> store
  batch_ui --> profile
  batch_ui --> ui_inputs["ui_inputs.py<br/>기본 경로·도움말"]
  batch --> cli["cli.py<br/>run_job·analyze_file·load_coverage"]
  batch --> ingest
  batch --> store
  batch --> profile
  batch --> report
  cli --> ingest["ingest.py<br/>엄격 파서·adapter"]
  cli --> aggregate["aggregate.py<br/>개수·bin·zone·sector"]
  cli --> stats["stats.py<br/>반경 밀도·Clark–Evans"]
  cli --> detect["detect.py<br/>ring·line·local 후보"]
  cli --> groups["groups.py<br/>support union"]
  cli --> lift_pin["lift_pin.py<br/>삼발이 template"]
  cli --> profile["profile.py<br/>YAML·pydantic 검증"]
  cli --> report["report.py<br/>불변식·CSV"]
  cli --> store["store.py<br/>SQLite"]
  cli --> version["version.py<br/>code·rule 해시"]
  aggregate --> geometry["geometry.py<br/>r·theta·sector·zone·notch"]
  detect --> geometry
  detect --> clustering["clustering.py<br/>DBSCAN"]
  detect --> line["line.py<br/>PCA 측정·분류"]
  detect --> ring["ring.py<br/>반경·두께·점유"]
  ring --> geometry
  lift_pin --> geometry
  profile -.->|지연 import: adapter 목록| ingest
  ingest -.->|지연 import: 노치 회전| geometry
```

점선은 함수 안의 지연 import다. 이 그림은 `wafer/*.py`의 import를 손으로 옮긴 것이므로 import를 바꾸면 함께 고친다.

| 계층 | 모듈 | 책임 |
|---|---|---|
| 화면 | `app.py`, `batch_ui.py`, `ui_inputs.py` | 입력 수집, 세션 상태, 표·그림·다운로드. 계산하지 않음 |
| orchestration | `batch.py` | 입력 목록(scan), 입력 고정, 순차 실행, 단위 지표·요약·export |
| core 진입 | `cli.py` | 오류→종료 코드 매핑, coverage 로드, 분석 흐름, 저장 호출 |
| 입력 | `ingest.py`, `profile.py` | KLARF 엄격 파싱·adapter 변환, profile 검증 |
| 계산 | `geometry`, `aggregate`, `stats`, `clustering`, `ring`, `line`, `detect`, `groups`, `lift_pin` | 좌표·집계·통계·후보·측정 |
| 출력·저장 | `report.py`, `store.py`, `version.py` | 불변식 검사·CSV, SQLite, 버전 해시 |

`version.code_version()`은 `app.py`를 뺀 `wafer/*.py` 전체(화면 모듈 `batch_ui.py`·`ui_inputs.py` 포함)의 내용 해시다. 이 모듈들을 수정하면 분석 키가 바뀐다(T-28).

## 3. 단일 분석 흐름(`run_job`)

```mermaid
flowchart TD
  A["run_job(klarf, profile_path, db, csv_dir, coverage_path)"] --> B["profile 읽기·sha256<br/>load_profile + validate_for_run"]
  B -->|누락·오류| E2["CONFIG_INVALID (2)"]
  B --> C["load_coverage(sidecar)"]
  C -->|형식 오류| E2
  C --> D["ingest.read_klarf<br/>문법·개수·숫자 검사, source_sha256"]
  D -->|손상| E3["INVALID_INPUT (3)"]
  D --> F["ingest.standardize<br/>adapter: 단위·die·중심·노치 → 표준 mm"]
  F -->|지원 밖| E3b["UNSUPPORTED_ADAPTER (3)"]
  F -->|노치 미상| F2["orientation=unknown<br/>방향·위상 보류"]
  F --> G["aggregate: 포함/제외(r>R), bin, center, sector, zone"]
  F2 --> G
  G --> H["stats: radial_density, clark_evans<br/>(coverage 없으면 null)"]
  G --> I["detect: DBSCAN·ring·line → support<br/>groups: union·bin 분포"]
  G --> J["lift_pin (비활성/노치 미상이면 보류)"]
  H --> K["pattern_summary·provenance"]
  I --> K
  J --> K
  K --> L["report.check_result 불변식"]
  L -->|위반| E5["RESULT_INVARIANT_VIOLATED (5)"]
  L --> M["write_csv (선택)"]
  M -->|쓰기 실패| E6["OUTPUT_WRITE_FAILED (6)"]
  L --> N["store.save_run (선택)<br/>분석 키 idempotent"]
  N -->|같은 키·다른 결과| E7["KEY_COLLISION (7)"]
  N --> O["out: job_status, data_quality_status, result, store, _points"]
  M --> O
  B -->|profile·sidecar·KLARF 파일 없음| E4["INPUT_NOT_FOUND (4)"]
  D -->|그 밖의 예외| E5b["INTERNAL_ERROR (5)"]
```

- 무작위성 검정 결과와 무관하게 후보 검출을 실행한다(검정은 gate가 아님).
- 실패한 job은 결과로 저장하지 않고 `attempts`에 `failed`로만 남긴다.
- `_points`(결함별 표준 좌표)와 `_wafer_radius_mm`는 화면·export용 내부 값이며 CLI JSON에서는 지운다.

## 4. 일괄 분석 시퀀스

```mermaid
sequenceDiagram
  actor U as 사용자
  participant UI as batch_ui.render
  participant B as batch.py
  participant C as cli.run_job
  participant S as SQLite(store)
  U->>UI: 업로드/폴더/경로 + 파일 선택 + profile·coverage·DB
  UI->>UI: 입력 signature·선택·설정이 바뀌면 이전 목록·결과 무효화
  U->>UI: 입력 목록 확인
  UI->>B: scan(items, profile, limits, coverage)
  B-->>UI: entries(ready/excluded/invalid_input/held/duplicate_in_batch),<br/>profile_sha256, coverage_sha256
  U->>UI: 일괄 분석 실행
  UI->>UI: 경로 profile hash가 바뀌었으면 scan 재실행(안내 표시)
  UI->>B: run_batch(items, scanned, profile, coverage, db, progress)
  B->>B: profile·sidecar·파일 hash 재확인<br/>다르면 CONFIG_INVALID(profile/coverage/inputs)
  B->>B: profile·sidecar를 임시 사본으로 고정
  B->>S: save_batch(config, entries) — 첫 실행 전에 기록
  loop ready 항목마다(순차)
    B->>UI: progress(n, total, 이름)
    B->>C: run_job(임시 파일, 고정 profile, db, coverage 사본)
    C->>S: save_run / log_attempt
    C-->>B: out, exit code
    B->>S: update_batch_member(상태·사유·analysis_key)
  end
  B->>S: duplicate 항목은 원본 항목의 키를 가리킴
  B-->>UI: {config, entries, units}
  UI->>B: overview / unit_rows / type_summary / batch_density / bin_totals_by_group
  UI->>B: summary_csv / type_csv / export_zip (다운로드 시점 검토 열 포함)
```

## 5. 화면 상태 전이

```mermaid
stateDiagram-v2
  [*] --> 입력대기
  입력대기 --> 목록확인됨: 입력 목록 확인(성공)
  입력대기 --> 입력대기: 입력 목록 확인(오류 표시)
  목록확인됨 --> 입력대기: 업로드·선택·profile·coverage·DB·상한 변경
  목록확인됨 --> 결과표시: 일괄 분석 실행(성공)
  목록확인됨 --> 목록확인됨: 실행 거부(CONFIG_INVALID/INPUT_NOT_FOUND)
  결과표시 --> 상세보기: 상세 맵·검토 화면 열기
  상세보기 --> 결과표시: ← 분석 목록으로 돌아가기
  결과표시 --> 입력대기: 입력 변경 또는 업로드 전체 삭제
```

세션 키(테스트에서도 사용): `batch_scan`(목록), `batch`(결과), `batch_items`, `batch_selected`, `batch_input_context`, `batch_upload_signature`, `batch_upload_epoch`, `job`(상세 대상), `show_detail`.

## 6. 산출물

| 산출물 | 생성 위치 | 내용 |
|---|---|---|
| `result.json` | CLI `--out`, 상세 화면 JSON 다운로드 | `job_status`·`data_quality_status`·`result`·`store`(화면 다운로드는 `review` 추가) |
| `defects.csv`, `spatial_counts.csv`, `bin_sector.csv`, `manifest.json` | `report.write_csv` | 결함별 행, 공간 집계, bin×sector, provenance·null 규약 |
| `batch_summary.csv`, `batch_type_summary.csv` | `batch.summary_csv`, `type_csv` | 단위별 행, 유형별 요약 |
| `batch_results.zip` | `batch.export_zip` | `batch_manifest.json`, 두 요약 CSV, `units/NNNN_이름/`(result.json·CSV·manifest) |
| SQLite | `store.py` | [5_ERD.md](5_ERD.md) |

## 7. 계획 대비 미구현 구성

| 계획 구성(실행계획 3·13절) | 현재 |
|---|---|
| 이미지 → 위치 추정 경로 | 없음(E15 N/A) |
| HTTP API(FastAPI) | 없음. 사내 HTTP 연동 요구 시 추가 |
| queue·worker·동시 job 상태(`queued`/`running`) | 없음(순차 실행) |
| container·CI·staging·rollback | 없음(Phase 4) |
| 과거 분석·batch 조회 화면 | 없음(FR-ST-03) |
| ML 모델·model_version | 없음(`model_version: null`) |
