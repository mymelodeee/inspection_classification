# 합성 KLARF 검사 맵 예제

300mm wafer, KLARF 1.8 record/list 형식으로 만든 합성 데이터 13개다. 실제 장비·lot·검사 정보는 사용하지 않았다. Seed=20261009다.

## 포함 자료

| 경로 | 내용 |
|---|---|
| `klarf/*.klarf` | 프로그램에 입력할 13개 예제 |
| `expected/*.csv` | 독립 기준 좌표(mm), classification bin, 생성 그룹, 시계방향 |
| `expected/*.json` | 총수/bin/center/12 sector/시험 zone 기대값, input hash |
| `manifest.json` | 예제 목록과 패턴 제작 의도 |
| `synthetic_profile.json` | 합성 전용 좌표 adapter 계약과 시험 설정 |
| `maps/overview.png` | 노치 6시 기준 빨간 dot·die 격자 overview |
| `verify_dummy.py` | klarfio 기반 파싱/좌표/집계 검증 및 klarfrs 호환성 비교 |
| `validation_report.json` | 이번 생성에서 실제 실행한 결과 |

## 예제 목록

| 파일 | 결함 수 | 제작 의도 |
|---|---:|---|
| `F01_counts.klarf` | 8 | 기존 실행계획 F01 좌표·bin·경계 집계 |
| `ring.klarf` | 240 | r 약 80mm 환형 |
| `edge_ring.klarf` | 240 | r 약 148mm edge 환형 |
| `line.klarf` | 120 | 수평 선형 |
| `local_3oclock.klarf` | 120 | 3시 부근 국부 몰림 |
| `threefold.klarf` | 120 | r 약 60mm, 0°/120°/240° 세 lobe |
| `single_lobe_counterexample.klarf` | 40 | 삼발이 오인 방지를 위한 단일 lobe 반례 |
| `mixed.klarf` | 300 | ring+line+local 혼합, bin별 생성 그룹 |
| `uniform_random.klarf` | 200 | 원판 면적에 균일한 무작위 생성 |
| `empty.klarf` | 0 | 정상적인 빈 결함 목록 |
| `F01_up.klarf` | 8 | 노치 UP 회전 변형 |
| `F01_left.klarf` | 8 | 노치 LEFT 회전 변형 |
| `F01_right.klarf` | 8 | 노치 RIGHT 회전 변형 |

패턴 제작 의도는 분류기의 실제 예측/성능 또는 공정 원인의 정답이 아니다. Random 한 장이 반드시 비유의 검정을 통과해야 하는 것도 아니다. Empty는 결함 목록 0건이며 전기적 정상·수율을 뜻하지 않는다. F01은 형상 분류 시험용이 아니다.

## 좌표와 bin 계약

파일의 XREL/YREL은 die 내부 µm 좌표다. 단순히 1000으로 나누어 wafer 중심 좌표라고 해석하면 안 된다. 이 합성 adapter에서만 다음 공식을 사용한다.

```text
raw_x_mm = (XINDEX * 10000 + XREL - 150000) / 1000
raw_y_mm = (YINDEX * 10000 + YREL - 150000) / 1000
```

Die pitch는 10000µm, reference die 원점은 합성 전역 원점이며 wafer 중심은 (150000,150000)µm다. 전역 원점은 wafer 중심 기준 (−150,−150)mm다. SampleCenterLocation은 이 합성 정의에서 die 기준 원점부터 중심까지의 벡터다. 실제 장비의 DieOrigin/SampleCenterLocation 의미를 이 공식으로 일반화하지 않는다.

Front side, +X 오른쪽/+Y 위쪽이다. Raw 좌표에 DOWN=0°, UP=180°, LEFT=270°, RIGHT=90° 시계방향 회전을 적용하면 notch 6시 기준 CSV 좌표가 된다. 표준 theta는 atan2(x,y)이며 center는 r<1mm다. 노치 변형은 각 좌표도 함께 회전시켰으므로 네 F01의 정규화 집계는 같아야 한다. Backside 반전·좌표 누락·손상 파일은 이 묶음의 범위가 아니다.

CLASSNUMBER를 classification bin으로 사용하고 ROUGHBINNUMBER/FINEBINNUMBER도 같은 숫자로 채웠다. Bin은 실제 설비 class 정의가 아닌 시험 코드 1/2/3이다. CLUSTERNUMBER=0은 생성 시 군집이 부여되지 않았다는 값이며 그룹 정답을 입력에 넣지 않았다. Generation group은 expected CSV에만 있다. 각 행이 고유 이벤트이며 die로 축약하지 않는다.

Coverage 전체 원판은 sidecar에 명시한 합성 전제다. 실제 검사 coverage를 결함 좌표나 이 파일의 sample size만으로 추정하지 않는다. E1=[0,2)mm/E2=[2,5)mm edge 거리와 100mm 존, 삼발이 반경/위상은 시험값이며 사내 운영 정의가 아니다. Profile JSON은 fixture 설명이며 기존 앱의 YAML schema를 대신하지 않는다.

F01 기대값은 총 8건, bin 1=3/bin 2=3/bin 3=2, center=1, 12시=1/3시=4/6시=1/9시=1이다. IDs 6/7/8은 각각 시험 E1/E2/100mm 경계 band에 속한다.

## 파서 검증과 발견한 호환성 문제

생성 환경의 CPython 3.12에서 klarfio 0.9.1로 13개 모두 파싱, 좌표 복원, bin/clock/zone 집계를 대조했다. 세부 환경과 결과는 validation_report.json을 본다. 실제 장비 adapter, 형상 분류, UI/배포 E2E는 NOT_RUN이다.

같은 파일을 기존 requirements의 klarfrs 0.2.1에 넣으면 결함 0건을 반환하며 FileRecord 1.8도 인식하지 못했다. 빈 파일 역시 format/header 인식 실패이므로 호환성 PASS로 처리하지 않았다. 문서상의 지원 표기와 별개로 이 fixture에서의 실제 호환성은 FAIL이다. 0건 반환을 정상 무결함으로 처리하지 말고 입력 버전/선언 행수/파싱 행수를 대조해야 한다. 특정 장비 export에 대한 결론은 별도 실제 샘플 검증이 필요하다.

이 생성 작업에서 프로젝트 requirements.txt는 변경하지 않았다. Claude Code에 아래 작업을 요청할 수 있다.

```text
이 dummy KLARF 1.8 묶음과 expected 자료를 사용해 파싱 adapter를 검증해줘.
klarfrs 0.2.1 호환성 FAIL 기록을 먼저 읽고, 파일을 비표준 문법으로 바꾸지 말아줘.
기존 입력 범위와 의존성을 검토한 뒤 최소 범위의 parser 수정 또는 교체를 제안/구현해줘.
F01에서 원본 8건과 bin·clock 집계가 보존되는지 확인하고,
형상 분류와 실제 장비 좌표 검증은 별도 상태로 보고해줘.
```

별도 비교 검증을 실행하려면 현재 준비된 conda 환경을 사용한다. klarfio는 기존 requirements에 포함되지 않았으므로 아래 설치는 비교 검증을 선택할 때만 수행한다.

```bash
conda run -n ins_evn python -m pip install klarfio==0.9.1
conda run -n ins_evn python verify_dummy.py
```

실행 위치는 이 README가 있는 디렉터리다. 다른 환경 이름이면 ins_evn을 바꾼다. 검증 스크립트는 validation_report.json을 현재 실행 결과로 갱신하며, 출력의 klarfrs compatibility failures도 확인한다. 합성 집계 PASS와 기존 파서 호환성 FAIL을 구분한다.

## 문법 확인 출처

1. [klarfio 공개 KLARF 1.8 예제](https://github.com/hadriman/klarfio/blob/main/test_output_v1.8.klarf): Record/Field/List/Columns/Data 구성 참고. 원본 결함 행은 복사하지 않았다.
2. [klarfio PyPI](https://pypi.org/project/klarfio/): 비교 검증 파서.
3. [klarfrs PyPI](https://pypi.org/project/klarfrs/), [upstream source](https://github.com/banickn/klarfrs): 지원 표기 및 실제 parse/parse_defects 호환성 대조.
4. 기존 `wafer_inspection_execution_plan.md` 19.2 F01: 8건 집계의 독립 기준.

공개 파서 기반 예제이며 SEMI 표준 전체 또는 특정 장비의 모든 필수 field 적합성을 인증한 파일은 아니다.
