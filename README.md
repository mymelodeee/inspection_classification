# Wafer Inspection Classification

KLARF 결함 좌표를 기반으로 웨이퍼의 **bin·영역·시계방향 분포를 집계하고, 환형·선형·국부 군집 패턴 후보를 분석하는 Python 프로젝트**입니다. 인라인 검사에서 발생한 개별 결함 이벤트를 분석 대상으로 하며, 규칙 기반 분석 코어와 CLI를 제공합니다.

> 현재는 **합성 KLARF와 시험용 profile로 검증한 개발 단계**입니다. 실제 장비 export용 adapter와 운영 임계값은 검증되지 않았습니다. 개발용 Streamlit 검토 화면은 있으나, 이미지 입력, 학습 모델, 운영 배포는 아직 구현되지 않았습니다.

## 구현된 기능

| 영역 | 현재 구현 |
|---|---|
| 입력 | 자체 엄격 파서로 KLARF의 열 정의·필수 좌표·숫자·목록 종료를 검사하고 원본 SHA-256 기록 |
| 좌표 | 합성 adapter의 µm 좌표를 mm로 변환, 웨이퍼 중심 원점·노치 6시 기준 사용 |
| 개수·bin | 포함/제외 결함 집계, 제외 사유 기록, unknown bin 및 동일 좌표의 별도 이벤트 보존 |
| 시계방향 | 12개 sector와 중심 영역 분리, bin × sector 교차표, 경계 허용오차를 반영한 별도 집계 |
| 영역 | YAML로 설정한 E1/E2 edge 영역, 반경 100 mm 내부 및 경계 band 집계 |
| 공간 통계 | 반경 구간별 개수, 검사 영역이 주어졌을 때의 면적·밀도 및 Clark–Evans/Monte Carlo 계산 함수 |
| 패턴 후보 | DBSCAN 국부 군집, 웨이퍼 중심 기준 ring/arc 후보, RANSAC·PCA 기반 line 후보 |
| 형상 측정 | 환형의 반지름·직경·두께(P95−P5)·각도 점유, 선형의 길이·폭·연속성 |
| 혼합 패턴 | 각 후보의 결함 ID를 보존하고, 중첩 그룹의 고유 ID 합집합 및 bin 분포 계산 |
| 삼발이 | 반경·위상·120° 간격의 3개 lobe를 이용한 lift-pin template 일치 분석. 기본 비활성 |
| 출력 | JSON, 결함별 CSV, 공간 집계 CSV, bin × sector CSV, provenance manifest |
| 저장·검토 | SQLite 분석 결과·실행 시도 저장, 동일 분석 키 중복 저장 방지, 예측 원본을 보존하는 검토 revision |
| 검증 | 결과 키와 개수 보존 검사, 합성 fixture 및 독립 정답을 이용한 pytest 회귀 테스트 |

검사 coverage는 결함 분포로 추정하지 않습니다. coverage를 주지 않으면 **반경별 개수만 계산**하고 면적·밀도는 `null`, Clark–Evans는 `insufficient_data`와 `coverage_unknown`을 반환합니다. 명시적 coverage sidecar(`--coverage`, 현재 `full_disk`만 지원)를 주면 면적·밀도와 Clark–Evans를 계산하고 출처·sha256을 provenance에 기록합니다. 통계 계산을 보류해도 패턴 후보 검출은 계속 수행합니다.

## 빠른 시작

### 1. 설치

대상 환경은 **64-bit CPython 3.11 또는 3.12**입니다. 아래 명령은 저장소 루트에서 실행합니다.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
python -m pip check
```

이미 준비한 conda/venv 환경이 있다면 해당 환경을 사용해도 됩니다. `requirements.txt`는 개발·UI(Streamlit)·브라우저 테스트용 패키지를 포함하는 직접 의존성 목록이며 배포용 lockfile은 아닙니다. 포함된 `klarfrs==0.2.1`은 현재 CLI 파싱에 사용하지 않습니다. 해당 패키지의 Linux x86_64 wheel은 glibc 2.34 이상을 요구합니다.

### 2. 샘플 분석

저장소에 포함된 합성 KLARF와 시험용 YAML로 실행합니다.

```bash
python -m wafer.cli tests/fixtures/klarf/f01.klf --profile tests/profiles/f01_test_profile.yaml
```

JSON 파일과 CSV를 함께 저장하려면:

```bash
python -m wafer.cli tests/fixtures/klarf/f01.klf --profile tests/profiles/f01_test_profile.yaml --out result.json --csv-dir out/
```

`--out`을 생략하면 JSON이 표준 출력으로 나옵니다. CSV 디렉터리는 자동 생성됩니다. `--out`에 하위 경로를 지정할 경우 부모 디렉터리는 미리 만들어야 합니다. 같은 이름의 출력 파일은 덮어씁니다.

| 인자 | 의미 |
|---|---|
| `klarf` | 분석할 KLARF 파일 경로, 필수 |
| `--profile` | YAML profile 경로, 필수 |
| `--out` | JSON 저장 경로, 선택 |
| `--csv-dir` | CSV 및 manifest 저장 디렉터리, 선택 |
| `--db` | 분석 결과와 실행 시도를 저장할 SQLite 파일 경로, 선택 |
| `--coverage` | coverage sidecar JSON(`{"coverage": {"shape": "full_disk", "radius_mm": R}}`), 선택. 생략하면 coverage 미상 |

SQLite에도 결과를 보관하려면 다음과 같이 실행합니다.

```bash
python -m wafer.cli tests/fixtures/klarf/f01.klf --profile tests/profiles/f01_test_profile.yaml --db analysis.db --out result.json
```

입력·profile hash, 결과 스키마·코드·규칙·파서·adapter 버전, seed, coverage(상태·형상·반경·sidecar hash)가 같은 분석은 저장된 결과를 중복 생성하지 않습니다. 같은 키인데 결과가 다르면 `KEY_COLLISION_RESULT_MISMATCH`로 거부합니다. 실행 시도는 별도로 기록하며 JSON의 `store.analysis_key`와 `store.created`로 저장 여부를 확인합니다. `wafer.store`의 Python 함수로 확인, 라벨 수정, 군집 병합·분할, 보류 revision을 추가할 수 있으며, 아래 검토 화면에서도 입력할 수 있습니다. 검토 기록은 예측 원본을 수정하지 않습니다.

### 3. 샘플 결과 확인

F01은 **좌표·개수 집계 검증용** 샘플입니다. 기대 결과는 다음과 같습니다.

| 항목 | 결과 |
|---|---|
| 파싱 / 포함 / 제외 | 8 / 8 / 0 |
| Bin | "1"=3, "2"=3, "3"=2 (계획서 F01 표기 B1/B2/B3에 해당) |
| 중심 영역 | 1 |
| 시계방향 | 12시=1, 3시=4, 6시=1, 9시=1, 나머지=0 |
| 반경 구간별 개수 | [0, 50)=1, [50, 100)=4, [100, 150]=3 |
| 패턴 요약 | `no_clear_pattern` |
| 삼발이 분석 | `disabled` |

이 샘플의 ring/line은 최소 점 수가 부족하여 `insufficient_data`입니다. `no_clear_pattern`은 정상 판정이나 결함 없음 판정이 아닙니다.

### 4. 검토 화면(Streamlit, 개발용)

```bash
python -m streamlit run wafer/app.py
```

- 입력: KLARF·profile을 업로드하거나 경로로 지정, coverage sidecar 경로(선택), SQLite 경로(선택, 검토 저장에 필요).
- 표시: `job_status`·`data_quality_status`·개수, 입력 파일명·source hash·profile·버전·coverage 상태, wafer map(profile 반경 기준 원, 노치가 확인된 경우에만 노치 표시, bin 표시 필터는 개수를 바꾸지 않음, signature group 강조), bin × 시계방향 표, 공간 집계(빈 칸=미계산, 0=실제 0), 판정 상태와 보류 사유.
- 검토: `review_status`, 검토 반영 군집, revision 목록, revision 입력 폼(잘못된 입력은 거부).
- 다운로드: JSON, CSV(zip). 둘 다 분석 키·검토 상태·최신 revision을 함께 담습니다.
- 업로드한 파일은 분석 후 임시 폴더에서 삭제합니다. 화면은 CLI와 같은 `wafer.cli.run_job`을 호출하며 분석 로직을 따로 갖지 않습니다.

#### 화면에서 처음 분석하기

1. 저장소 루트에서 위 Streamlit 명령을 실행하고 터미널에 표시된 Local URL을 엽니다(기본 `http://localhost:8501`). 종료할 때는 실행 터미널에서 `Ctrl+C`를 누릅니다.
2. 왼쪽 **또는 KLARF 경로**에 `tests/fixtures/klarf/f01.klf`, **또는 profile 경로**에 `tests/profiles/f01_test_profile.yaml`을 입력합니다. 업로드 방식도 가능하며, 같은 입력에 업로드와 경로를 모두 지정하면 업로드 파일이 우선합니다.
3. coverage 경로는 첫 실행에서 비워 두고, 검토를 저장하려면 **SQLite 저장 경로**에 `analysis.db`를 입력합니다. 상대 경로는 Streamlit을 실행한 디렉터리 기준이며, DB의 부모 디렉터리는 미리 존재해야 합니다.
4. **분석 실행**을 누릅니다. F01에서는 `included=8`, `center=1`과 위의 bin·시계방향 기대값을 확인합니다.
5. 지도에서 bin을 선택하거나 signature group을 강조합니다. bin 선택은 표시만 바꾸며 전체 집계값이나 저장 결과를 바꾸지 않습니다.
6. **검토**에서 action과 JSON payload를 입력하고 **검토 저장**을 누릅니다. `review_status`와 revision 목록에서 반영 여부를 확인합니다.
7. **JSON 다운로드** 또는 **CSV(zip) 다운로드**를 누릅니다. UI의 JSON에는 `review`, CSV ZIP에는 `review.json`이 추가됩니다. CLI export에는 이 UI 검토 메타데이터가 추가되지 않습니다.

현재 화면에는 저장된 분석 목록을 불러오는 메뉴가 없습니다. 이전 검토를 다시 보려면 같은 입력·profile·coverage와 같은 DB로 재분석합니다. 분석 키가 같으면 이전 revision이 표시되고, 코드나 설정 등이 달라지면 별도 분석으로 저장됩니다.

#### 검토 payload 예제

| action | payload 예제 | 조건 |
|---|---|---|
| `confirm` | `{}` | 분석을 확인 처리 |
| `defer` | `{"reason_code": "needs_sem_review"}` | 보류 사유 코드 필요 |
| `correct_label` | `{"target": "wafer", "axis": "morphology", "label": "needs_review"}` | 대상과 라벨 축 지정. 예시 label은 사용자 검토 기록이며 자동 판정값이 아님 |
| `merge_clusters` | `{"clusters": ["0", "1"]}` | 현재 존재하는 서로 다른 군집 2개 이상 |
| `split_cluster` | `{"cluster": "0", "parts": [["1:1"], ["2:2", "3:3"]]}` | 실제 군집의 모든 결함 ID를 누락·중복 없이 2개 이상의 비어 있지 않은 묶음으로 분할 |

병합·분할의 군집 및 결함 ID는 예시입니다. 실제 결과 JSON의 `detect.clusters`와 화면의 **현재 군집(검토 반영)**을 기준으로 바꿔야 합니다. F01은 DBSCAN 군집이 없어 이 병합·분할 예제를 그대로 적용할 수 없습니다. 라벨 수정의 `axis`는 `morphology`, `zone`, `signature_match` 중 하나이며 `target`은 현재 군집 ID, signature group 이름, `lift_pin`, `wafer`를 지원합니다. 검토는 revision으로 기록되며 기존 예측값과 지도·집계표를 재계산하지 않습니다.

### 5. KLARF 1.8 패턴 예제와 coverage 사용

입력 파일과 YAML profile은 아래 조합을 사용합니다. 서로 바꾸면 adapter가 맞지 않아 실패합니다.

| 입력 묶음 | 사용할 `--profile` | adapter |
|---|---|---|
| `tests/fixtures/klarf/*.klf`의 정상 합성 파일 | `tests/profiles/f01_test_profile.yaml` | `synthetic-um-die00-notch-down` |
| `klarf_dummy_data/klarf/*.klarf` | `tests/profiles/dummy_die_local_test_profile.yaml` | `synthetic-die-local-v1` |

환형 예제를 JSON·CSV·SQLite로 함께 저장하는 실행 예제입니다.

```bash
python -m wafer.cli klarf_dummy_data/klarf/ring.klarf --profile tests/profiles/dummy_die_local_test_profile.yaml --coverage klarf_dummy_data/synthetic_profile.json --out ring_result.json --csv-dir out/ring --db analysis.db
```

`ring.klarf`는 240개 결함을 가진 합성 환형입니다. 같은 디렉터리의 `line.klarf`, `mixed.klarf`, `local_3oclock.klarf`, `empty.klarf` 등으로 입력 경로를 바꾸어 실행할 수 있습니다. 전체 목록과 제작 의도는 [합성 데이터 안내](klarf_dummy_data/README.md)에 있습니다. `threefold.klarf`를 넣더라도 제공 YAML에서는 `signatures.lift_pin.enabled: false`이므로 삼발이 판정은 비활성입니다.

UI에서도 위 KLARF와 YAML을 입력하고 **coverage sidecar 경로**에 `klarf_dummy_data/synthetic_profile.json`을 넣으면 같은 조건으로 분석합니다. 이 JSON은 `coverage` 객체를 포함한 보조 입력이며 **Profile (YAML)** 자리에 넣는 파일이 아닙니다.

별도 coverage 파일을 사용할 때의 최소 형식은 다음과 같습니다(UTF-8 JSON).

```json
{
  "coverage": {
    "shape": "full_disk",
    "radius_mm": 150,
    "source": "synthetic full-disk example"
  }
}
```

현재는 웨이퍼 중심의 원판(`full_disk`)만 지원하고, 반경은 0보다 크고 `wafer_radius_mm` 이하여야 합니다. 검사 영역을 실제로 알 때만 지정하세요. coverage를 생략하면 미상 상태를 유지하며, 지정해도 점 수 부족이나 검사 영역 밖 결함 등의 이유로 일부 통계가 보류될 수 있습니다. 결과의 `calc_status`와 `reason`을 함께 확인합니다.

## 입력 지원 범위

현재는 두 종류의 합성 adapter를 지원합니다. 먼저 `synthetic-um-die00-notch-down`의 규약은 다음과 같습니다.

- UTF-8 텍스트, 단일 `DefectList`, 한 레코드당 한 줄의 숫자 필드.
- 필수 열: `DEFECTID`, `XREL`, `YREL`, `CLASSNUMBER`.
- `XREL`/`YREL`은 µm이며, 원점은 웨이퍼 중심입니다.
- `SampleCenterLocation`과 `DieOrigin`은 `0 0`, die index는 `(0, 0)`입니다.
- `OrientationMarkLocation`은 `DOWN`, `CoordinatesMirrored`는 `NO`입니다. 노치 위치 필드가 없으면 실패하지 않고 개수·bin·반경/edge 거리 집계만 반환하며 시계방향·위상 판정은 보류합니다(`clock_status=insufficient_data`).
- `CLASSNUMBER=0`은 `unknown`, 그 외 정수는 숫자 그대로 문자열(`"1"`, `"2"`, …)로 표기합니다(모든 adapter 공통).
- 웨이퍼 반경은 profile의 `wafer_radius_mm`을 사용합니다. KLARF `SampleSize`와의 일치 검사는 아직 없습니다.

파서의 버전 허용값은 `FileVersion 1 2`와 `1 8`이지만, **두 버전의 일반적인 장비 export 전체를 지원한다는 의미는 아닙니다.** 좌표·방향 규약이 다르면 `UNSUPPORTED_ADAPTER`로 실패하며, 다중 wafer/list는 지원하지 않습니다. YAML의 좌표 선언만 바꿔 다른 장비용 변환을 활성화할 수는 없습니다.

두 번째 합성 규약으로 KLARF 1.8 Record/Field/List 문법(단일 wafer)과 `synthetic-die-local-v1` adapter도 지원합니다. 이 adapter는 `raw=(die index×pitch+XREL/YREL−SampleCenterLocation)/1000`을 쓰고 notch를 한 번 회전하며, profile에서 `coordinates.adapter_id`로 명시해야 쓰입니다. `adapter_id`는 모든 profile에서 필수이며, 비어 있으면 `CONFIG_INVALID`입니다. 예제는 `klarf_dummy_data/`와 `tests/profiles/dummy_die_local_test_profile.yaml`이며, coverage는 `--coverage` sidecar로 명시적으로 넘깁니다.

파일명은 파싱하지 않으며 lot/wafer/job/시간 메타데이터도 추출하지 않습니다. **위 내용은 합성 입력에서 검증된 범위이며 사내 입력 지원 완료가 아닙니다.** 실제 사내 데이터 도입 시의 입력 계약 재검증은 [실행계획 5.3](wafer_inspection_execution_plan.md)과 [TBD.md T-29](TBD.md)에 정리되어 있습니다.

입력 예제의 상세 규약은 [합성 KLARF 설명](tests/fixtures/klarf/README.md)을 참고하세요.

## 설정과 분석 원칙

[시험용 profile](tests/profiles/f01_test_profile.yaml)에 실행 가능한 설정이 있습니다. **이 파일의 E1/E2 구간, 형상 임계값, 군집 파라미터는 시험 전용이며 운영 기준으로 사용할 수 없습니다.**

| 설정 | 역할 |
|---|---|
| `wafer_radius_mm` | 웨이퍼 반경과 외부 결함 제외 기준 |
| `coordinates.adapter_id` | 필수 adapter 선택. 입력 묶음에 맞는 위 표의 YAML 사용 |
| `clock` | 중심 제외 반경, sector 경계 허용오차 |
| `zones` | E1/E2 edge 거리 구간, 100 mm 내부/경계 영역 |
| `clustering` | DBSCAN의 `eps_mm`, `min_samples` |
| `detect` | 후보 검출 활성화, ring 반경 허용오차, line inlier 거리·시도 횟수 |
| `shapes` | ring/arc·line 분류 임계값 및 `calibrated` 여부 |
| `signatures.lift_pin` | 삼발이 template, 반경·위상·허용오차·lobe 지지 조건 |
| `stats.radial_bin_mm` | 반경별 집계 구간 폭 |
| `randomness` | Monte Carlo 반복 수 및 재현 가능한 seed |

활성화한 기능의 필수 설정이 없거나 허용되지 않은 설정이면 `CONFIG_INVALID`를 반환합니다. `calibrated: false`인 형상 규칙은 조건을 충족해도 확정 `matched` 대신 `candidate`로 보고합니다. `calibrated`는 현재 자기 선언 값이므로, 값 변경만으로 실제 보정·검증을 대신할 수 없습니다.

분석 결과는 다음 원칙을 따릅니다.

- **개수 보존:** `n_parsed = n_included + n_excluded`, unknown을 포함한 bin 합계는 `n_included`입니다. DBSCAN noise도 전체 집계와 다른 검출기에 남습니다.
- **방향 기준:** +X는 오른쪽, +Y는 위쪽이며 `atan2(x, y)`로 12시=0°, 3시=90°, 6시=180°, 9시=270°를 계산합니다.
- **엄격 분할과 경계 집계 구분:** `sectors_clock`의 12개 합과 `center`의 합은 포함 결함 수입니다. `sectors_clock_tolerant`는 경계 근처 점을 양쪽 sector에 세므로 합이 더 클 수 있습니다.
- **중첩 보존:** 영역·패턴별 개수를 단순 합산하지 않고 고유 이벤트 ID의 합집합을 사용합니다. 같은 좌표나 `DEFECTID`를 가진 별도 레코드도 보존합니다.
- **두께와 영역 구분:** 환형의 두께는 측정값 P95−P5입니다. 설정된 100 mm 경계 band 폭과는 별개입니다.
- **계산 불가와 0 구분:** JSON의 `null`과 CSV의 빈 칸은 실제 관측값 0과 구분합니다. 형상/template 일치는 공정 원인의 확증이 아닙니다.

## 출력 파일과 상태

| 파일 | 내용 |
|---|---|
| `result.json` | 실행 상태, 집계, 통계·패턴 상태, 검출 그룹, provenance. `--out`으로 지정한 파일명 |
| `defects.csv` | 결함별 좌표·반경·bin·포함 여부·제외 사유·sector·영역 |
| `spatial_counts.csv` | bin, 엄격/허용오차 sector, 중심, 영역, 반경별 집계와 계산 보류 사유 |
| `bin_sector.csv` | bin × 12 sector·중심 교차표, 합계 및 상태 |
| `manifest.json` | CSV 목록, null 표기 규약, 입력/profile hash와 버전 정보 |

JSON은 최상위 `job_status`, 성공 시 `data_quality_status`와 `result`를 제공합니다. 결함별 행은 CSV에 있으며 JSON에는 포함하지 않습니다. `provenance`에는 입력·profile SHA-256, profile ID, 코드·규칙·파서·adapter·결과 스키마 버전, coverage, seed가 기록됩니다. 현재 결과 스키마는 `result-0.1`, 코드 버전은 `0.1.0-dev+<모듈 내용 해시>`(자동 산출), 파서는 `wafer.ingest-strict-2`입니다. 결과의 `orientation_status`(`notch_registered`/`unknown`)와 `clock_status`로 시계방향 집계가 계산됐는지 확인합니다.

`job_status: succeeded`와 `data_quality_status: valid`여도 모든 기능이 계산된 것은 아닙니다. 각 기능의 `feature_status` 또는 `calc_status`, `reason`을 함께 확인해야 합니다.

| 종료 코드 | 의미 |
|---|---|
| `0` | 성공 |
| `2` | `CONFIG_INVALID`(coverage sidecar 오류는 `reason`으로 구분) 또는 CLI 인자 사용 오류 |
| `3` | `INVALID_INPUT` / `UNSUPPORTED_ADAPTER` |
| `4` | `INPUT_NOT_FOUND` |
| `5` | `RESULT_INVARIANT_VIOLATED` / `INTERNAL_ERROR` |
| `6` | `OUTPUT_WRITE_FAILED` — CSV/manifest 쓰기 실패 |
| `7` | `KEY_COLLISION_RESULT_MISMATCH` — 같은 분석 키에 다른 결과 |

분석 중 처리된 오류는 JSON으로 보고합니다. CLI 인자 오류는 argparse의 사용법 메시지로 출력하며, `--out` JSON 파일 자체의 쓰기 실패는 현재 위 오류 처리 범위 밖입니다.

## 테스트

```bash
python -m pytest tests -q -m "not e2e"   # 단위·회귀·CLI·AppTest(헤드리스 UI)
python -m pytest tests -q -m e2e -rA     # 실제 Streamlit 서버 + Windows 시스템 Edge(Playwright)
```

브라우저 E2E는 Python Playwright의 `channel="msedge"`를 사용하므로 별도 browser 다운로드가 필요 없습니다. Edge를 띄울 수 없으면 "BLOCKED" 사유로 skip되며, skip은 통과가 아닙니다.

**2026-10-09 로컬 검증: Windows · Python 3.12.15에서 192 passed.** (이후 갱신: `pytest tests -q -m "not e2e"` 319 passed, 브라우저 E2E `-m e2e` 4 passed — 2026-10-09; 2026-10-10 다운로드 내용 대조 추가 후 `-m e2e` 8 passed, `not e2e` 319 passed — Windows, insenv, 합성 fixture 기준.) F01 CLI 실행 결과도 위 기대값과 일치했습니다. 이 기록은 현재 작업 폴더의 합성·단위·CLI 회귀 테스트 결과이며, 깨끗한 환경의 설치 검증이나 실제 장비 데이터의 분류 성능 검증은 아닙니다.

테스트는 개수 보존, 좌표·경계, 빈 입력, unknown bin, 중복 이벤트, 손상 입력, 설정 오류, noise 보존, 형상·혼합 패턴·삼발이, 통계 재현성, JSON↔CSV 정합성, SQLite 중복 저장·재시도·동시 저장·검토 revision, 합성 KLARF 1.8 묶음(`klarf_dummy_data/`), 노치 미상 부분 결과, Streamlit 화면(AppTest)과 Edge 브라우저 흐름을 다룹니다. F01의 독립 정답은 [oracle.json](tests/fixtures/f01/oracle.json)에 있습니다. 설계 시나리오 E01~E24 전체나 API E2E가 완료된 상태는 아니며, UI E2E는 일부 하위 case만 다룹니다.

## 프로젝트 구조

```text
inspection_classification/
├── wafer/
│   ├── cli.py          # CLI와 공통 분석 흐름
│   ├── ingest.py       # 엄격 KLARF 파서, 합성 adapter
│   ├── profile.py      # YAML/Pydantic 설정 검증
│   ├── geometry.py     # 반경, 각도, sector, 영역 계산
│   ├── aggregate.py    # 개수·bin·영역·sector 집계
│   ├── stats.py        # 반경 밀도와 Clark–Evans 통계
│   ├── clustering.py   # DBSCAN, noise 보존
│   ├── ring.py         # 환형/호형 측정과 규칙
│   ├── line.py         # PCA 선형 측정과 규칙
│   ├── detect.py       # ring/line/local 후보 및 지원 ID
│   ├── groups.py       # 그룹 중첩·고유 ID 합집합
│   ├── lift_pin.py     # 삼발이 template 분석
│   ├── report.py       # 결과 불변식 검사, CSV export
│   ├── store.py        # SQLite 분석·실행 시도·검토 revision
│   ├── version.py      # 코드·규칙 버전(모듈 내용 해시)
│   └── app.py          # Streamlit 검토 화면(개발용)
├── tests/
│   ├── fixtures/      # 합성 KLARF·형상 데이터·독립 정답
│   ├── profiles/      # 시험 전용 YAML
│   └── test_*.py      # 단위·회귀·CLI·UI·브라우저 E2E 테스트
├── klarf_dummy_data/  # 합성 KLARF 1.8 묶음과 독립 정답
├── .claude/           # 서브에이전트 3개, 프로젝트 스킬 2개
├── .mcp.json          # 프로젝트 Playwright MCP(Edge, isolated)
├── requirements.txt
├── TBD.md
├── wafer_inspection_execution_plan.md
└── wafer_inspection_map_knowledge.md
```

## 현재 한계와 다음 단계

- 실제 장비의 die pitch/origin, 좌표 단위, notch·side·mirror, bin 의미에 맞는 adapter 검증이 필요합니다.
- 원판 coverage는 sidecar로 지정할 수 있으나, 실제 die 규칙과 검사 die 목록이 없어 `affected_die_count`, `inspected_die_count`는 `null`입니다.
- 전역 ring 탐색은 웨이퍼 중심 기준 가장 밀집한 반경 하나, line 탐색은 최대 inlier 직선 하나에 한정됩니다. 중심이 어긋난 ring, 다중 ring/line의 일반적인 검출은 미구현입니다.
- 운영 E1/E2 구간, 중심 제외 반경, 형상 임계값 및 설비별 삼발이 template은 실제 자료로 확정해야 합니다.
- 개발용 Streamlit 화면(wafer map, bin×시계방향 표, 검토 입력)은 있으나, 원본 화면 대조 overlay, 이미지 fallback, HTTP API, ML 학습·추론, CI/CD·배포 구성은 후속 범위입니다.
- SQLite 저장·검토는 로컬 구현이며 검토자 인증, schema migration, 운영 rollback은 미구현입니다.
- 실제 blind 데이터의 성능·처리시간 평가가 남아 있습니다.

## 관련 문서

- [실행계획](wafer_inspection_execution_plan.md): 단계별 요구사항, 분석 계약, E01~E24 검증 시나리오
- [분석 배경과 참고 문헌](wafer_inspection_map_knowledge.md): 인라인 inspection map 분석 개념과 연구 자료
- [보류 항목 및 결정 기록](TBD.md): 실제 데이터·운영 정의가 필요한 항목
- [개발 작업 지침](CLAUDE.md): 구현·검증·데이터 취급 원칙
- [Claude Code 도구 가이드](CLAUDE_CODE_TOOLING_GUIDE.md), [서브에이전트 안내](README-wafer-agents.md): 에이전트·스킬·MCP 구성과 사용법

설계 문서와 일부 상태 기록에는 구현 전 설명이 남아 있습니다. 현재 실행 가능한 인터페이스는 `wafer/` 코드와 테스트, 이 README의 실행 예제를 기준으로 확인하세요.
