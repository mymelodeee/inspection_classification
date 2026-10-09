# 웨이퍼 분석 앱용 Claude Code 도구 가이드

작성일: 2026-10-09 · 대상: 이 저장소의 현재 작업 폴더(미커밋 파일 포함)

## 1. 추천 결론

이 프로젝트에는 **기존 서브에이전트 3개 + Python pytest/Playwright + 프로젝트 전용 검증 스킬** 조합이 가장 적합하다. 화면을 직접 탐색할 일이 많으면 Playwright MCP 또는 공식 Playwright CLI+Skills 중 하나를 추가한다. 외부 DB·ML·범용 에이전트 프레임워크를 먼저 도입할 필요는 없다.

아래 우선순위는 보편적인 인기 순위가 아니라 실제 파일을 읽고 판단한 프로젝트 적합도다. 이 문서는 처음에 추천과 설정 예시만 제공했다. **2026-10-09에 스킬 2개와 Playwright MCP를 실제로 적용했다 — 현재 상태는 11절.**

| 우선순위 | 구성 | 현재 상태 / 권장 조치 |
|---|---|---|
| 1 | 기존 wafer 서브에이전트 3개 | 정의 파일 존재. 역할을 유지하고 작업에 필요한 것만 호출 |
| 1 | pytest + Streamlit AppTest + Python Playwright | 의존성 선언과 테스트 코드 존재. 기존 검증 경로 우선 |
| 1 | `wafer-verify` 프로젝트 스킬 | **적용됨**(`.claude/skills/wafer-verify/`). 변경 파일에 맞는 검사·명령을 반복 가능하게 정리 |
| 2 | Playwright MCP **또는** Playwright CLI+Skills | **MCP 등록됨**(`.mcp.json`, 사용자 승인 대기). CLI+Skills는 중복이라 미설치 |
| 2 | `wafer-contract-audit` 프로젝트 스킬 | **적용됨**(`.claude/skills/wafer-contract-audit/`). 오래된 상태 문서와 실제 코드의 불일치 점검 |
| 3 | Context7 MCP | 공개 라이브러리 문서 조회가 반복될 때 선택 |
| 보류 | DB MCP, 별도 파일시스템 MCP, ML 전용 에이전트 | 현재 구조에서 추가 이점이 작거나 필요한 자료가 없음 |

## 2. 파일 분석에서 확인한 근거

| 파일 | 확인한 내용 | 도구 선택에 미치는 영향 |
|---|---|---|
| `CLAUDE.md` | 단일 Python core, 최소 구현, 개수·좌표·상태 계약, 기존 insenv 사용 | 범용 full-stack 구성보다 분석 계약 검증 우선 |
| `wafer/ingest.py`, `wafer/cli.py` | 자체 KLARF 파서, adapter, 공통 `run_job`, coverage sidecar 입력 | parser 의존성 설치만으로 장비 입력 지원을 보장하지 않음 |
| `wafer/app.py` | Streamlit, Plotly, 업로드/경로 입력, bin 필터, 검토 저장, JSON/CSV ZIP 다운로드 | AppTest와 실제 브라우저 검사를 함께 활용 |
| `wafer/geometry.py`, `wafer/aggregate.py` | 좌표·sector·영역·bin 집계 | 화면 이미지보다 독립 숫자 oracle이 핵심 |
| `wafer/detect.py`, `wafer/ring.py`, `wafer/line.py`, `wafer/lift_pin.py` | 형상 후보와 설비 template 관련 분석 코드 | 일반 데이터 분석 스킬보다 도메인 계약 점검이 유효 |
| `wafer/store.py`, `tests/test_store.py` | SQLite, 분석 키, append-only 검토 revision | 외부 DB MCP보다 기존 Python 저장 계층과 테스트 활용 |
| `wafer/report.py`, `wafer/version.py` | 결과 불변식·CSV, 코드/규칙 fingerprint | UI·CLI·export·provenance를 함께 비교 |
| `tests/test_app.py` | Streamlit AppTest, F01 독립 기대값, 필터·실패 후 상태·검토 검사 | 빠른 UI 회귀 기반이 이미 있음 |
| `tests/test_e2e_browser.py`, `pytest.ini` | 실제 Streamlit 서버 + `channel="msedge"`, `e2e` marker | 기존 Edge 기반 E2E 유지. 별도 JS 테스트 프로젝트 불필요 |
| `tests/fixtures/f01/oracle.json`, `tests/profiles/` | 합성 정답과 시험 profile | 탐색에서도 재현 가능한 동일 입력 사용 |
| `.claude/agents/`, `README-wafer-agents.md` | maintainer·validator·reviewer 3역할 | 비슷한 이름의 agent를 추가하지 않고 재사용 |
| `requirements.txt` | NumPy/Pandas/SciPy/scikit-learn, Streamlit/Plotly, pytest-playwright 등 | 필요한 기본 패키지는 이미 선언됨. 실제 설치 상태와 구분 |
| `TBD.md`, 실행계획, 지식 문서 | 실제 장비 좌표/운영 임계값·coverage·성능 평가의 미확정 범위 | MCP나 스킬이 사내 정의·검증 자료를 대신할 수 없음 |

작성 당시 프로젝트 `.claude/`에는 agents만 있고 프로젝트 스킬이나 settings 파일은 없었으며, 프로젝트 `.mcp.json`도 없었다(2026-10-09 적용 후 상태는 11절). 사용자 전역 Claude Code 설정은 조사하지 않았으므로 “MCP가 어디에도 설치되지 않음”을 뜻하지 않는다. Claude Code에서 실제 agent 로딩 여부 역시 별도 확인 대상이다.

### 문서와 코드의 차이

- `README.md`의 “웹 UI/검토 화면 미구현”은 `wafer/app.py` 및 두 UI 테스트 파일과 불일치한다.
- README의 “CLI coverage 미상만 지원” 설명과 달리 `wafer/cli.py`에는 `--coverage`와 full-disk sidecar 경로가 있다. 일반 ROI/polygon 지원으로 확대 해석하면 안 된다.
- `CLAUDE.md` 첫 부분은 Edge 테스트를 설명하지만 뒤쪽의 Chromium 설치 안내는 현재 `channel="msedge"` fixture와 다르다. Chromium 다운로드만으로 Edge fixture의 실행 조건이 해결되지는 않는다.
- README의 과거 테스트 통과 수는 이번 작업에서 재실행한 결과가 아니다.

작성 당시에는 가이드만 추가했다. **2026-10-09에 위 차이를 정리했다:** README의 UI·coverage 설명, CLAUDE.md의 브라우저 준비 안내(Edge 사용), 테스트 수 기록을 현재 코드·실행 결과에 맞췄다. 미확정 운영 정의는 보류 상태로 유지했다.

## 3. Subagent, MCP, Skill의 역할 구분

| 종류 | 이 프로젝트에서의 역할 | 예시 |
|---|---|---|
| Subagent | 분리된 작업 맥락에서 특정 책임 수행 | 테스트 개정, 실행 검증, 읽기 전용 계약 리뷰 |
| MCP | Claude가 외부 도구에 접근하는 연결 | 실제 브라우저 조작, 공개 문서 조회 |
| Skill | 반복 작업의 절차와 판단 기준 저장 | 변경 영향별 검증 명령·oracle 선택 |
| 테스트 코드 | 재현 가능한 입력·assertion으로 회귀 검증 | `tests/test_e2e_browser.py` |

Claude Code의 프로젝트 agent는 `.claude/agents/*.md`, 프로젝트 skill은 `.claude/skills/<name>/SKILL.md`에 둔다. Skill 이름은 `/name`으로 호출할 수 있다. MCP와 agent는 서로 대체 관계가 아니다. 공식 형식은 [Subagents](https://code.claude.com/docs/en/sub-agents), [Skills](https://code.claude.com/docs/en/skills), [MCP](https://code.claude.com/docs/en/mcp)를 따른다.

## 4. 이미 있는 서브에이전트부터 활용

| Agent | 사용할 때 | 경계 |
|---|---|---|
| `wafer-test-maintainer` | 변경 전 시나리오 audit, 승인된 계약 변경 뒤 테스트 update | audit은 수정·실행 없음. update도 production 코드 수정 없음 |
| `wafer-e2e-validator` | 변경 완료 후 실제 명령 실행·정답 비교 | 소스/기대값을 고쳐 통과시키지 않음 |
| `wafer-contract-reviewer` | 코드·YAML·oracle·리포트 정합성 최종 점검 | Read/Glob/Grep만 사용. 실행 PASS 판정 담당이 아님 |

기존 정의는 모두 `model: inherit`이다. 작은 문서 변경에 세 agent를 전부 호출할 필요는 없다. 동일 파일을 여러 agent가 동시에 수정하게 하지 않는다. 로딩과 호출 예시는 `README-wafer-agents.md`를 재사용한다.

새로운 frontend/backend/data-scientist agent는 당장 권하지 않는다. 현재 UI와 CLI가 같은 Python core를 사용하고, 실제 장비 사양과 운영 라벨이 미확정이기 때문이다. 향후 장비별 adapter 작업이 반복될 때만 KLARF adapter 검토 역할을 별도로 분리한다.

**MCP 권한 주의:** 기존 validator의 도구 목록은 Read/Glob/Grep/Bash다. Playwright MCP를 등록해도 이 agent가 자동으로 MCP 도구를 쓸 수 있다고 가정하지 않는다. 우선 메인 Claude가 MCP 탐색을 담당하고 validator는 기존 Bash 기반 Python E2E를 실행하도록 한다.

## 5. Playwright를 적용하는 방법

### 5.1 세 가지 경로를 구분

| 경로 | 적합한 작업 | 프로젝트 적용 |
|---|---|---|
| Python Playwright 테스트 | 반복 가능한 브라우저 회귀 | 이미 구현됨. 지속적인 검증 기준으로 유지 |
| Playwright MCP | 대화 중 상태를 유지하며 UI 탐색·오류 재현 | 업로드, rerun, 검토 폼, 다운로드를 실제 화면에서 탐색할 때 |
| Playwright CLI+Skills | 명령 기반 브라우저 탐색·스크린샷 | Bash 중심 작업을 선호할 때 MCP의 대안 |

공식 Playwright 저장소도 코딩 agent용 CLI+Skills와 상태를 유지하는 탐색용 MCP를 구분한다. 이 프로젝트에서는 기존 Python 테스트를 보존하고 탐색 도구만 선택적으로 추가하는 구성이 적합하다. [Playwright MCP](https://github.com/microsoft/playwright-mcp), [Playwright CLI](https://github.com/microsoft/playwright-cli)

### 5.2 선택 A: Playwright MCP

Node.js 18 이상과 사용 가능한 Edge가 필요하다. 다음은 Windows 프로젝트용 설정 예시다(2026-10-09에 Node v24.18.0, `@playwright/mcp@0.0.83`으로 실제 등록 — 11절). 프로젝트 루트에서 실행하면 project scope `.mcp.json`에 등록된다. 기존 서버 설정이 있으면 보존한다.

```powershell
node --version
claude mcp add --transport stdio --scope project playwright -- cmd /c npx -y @playwright/mcp@latest --browser msedge --isolated
claude mcp list
```

Claude Code의 `/mcp`에서 연결 상태와 프로젝트 설정 승인 여부를 확인한다. `--isolated`는 브라우저 프로필을 분리하기 위한 옵션이다. `@latest`는 도입용 예시이며 팀에서 재현성을 요구하면 실제 검증한 버전으로 고정한다. Python `pytest-playwright` 설치와 Node MCP 서버 설치는 별개다. [MCP 설정](https://code.claude.com/docs/en/mcp), [서버 옵션](https://github.com/microsoft/playwright-mcp)

먼저 기존 Python 환경으로 앱을 실행한 뒤 MCP가 localhost 화면을 열도록 한다. 실제 사내 KLARF 대신 저장소의 합성 fixture를 사용한다. 로컬 MCP라는 이유만으로 브라우저에서 읽은 내용이 모델 처리와 무관해지는 것은 아니다. 자료 취급은 `CLAUDE.md` 7절을 따른다.

### 5.3 선택 B: 공식 Playwright CLI+Skills

MCP 대신 명령 기반으로 탐색하려면 다음 공식 설치 경로를 검토한다. 전역 npm 도구 설치와 프로젝트 스킬 생성이 포함되므로 적용 전 생성 파일을 확인한다. 이 문서 작성에서는 실행하지 않았다.

```powershell
npm install -g @playwright/cli@latest
playwright-cli --help
playwright-cli install --skills
```

이 도구는 Python의 `python -m playwright`와 별개다. 실제 브라우저 선택과 필요한 실행 옵션은 설치한 버전의 help로 확인한다. 자동 생성된 코드가 있더라도 최종 회귀는 기존 Python 테스트 구조에 맞춰 검토한다. [공식 CLI 설치·스킬 안내](https://github.com/microsoft/playwright-cli)

### 5.4 화면에서 확인할 시나리오

| 우선 확인 | 기대 결과 | 현재 검사 / 추가 탐색 |
|---|---|---|
| F01 경로 입력·업로드 | included=8, center=1, bin=3/3/2, 12·3·6·9시=1/4/1/1 | AppTest와 브라우저 테스트 존재. 브라우저의 숫자 assertion 범위는 일부 |
| B1 표시 필터 | 지도 3건, 원본 included=8 유지 | AppTest 존재. 브라우저 지도도 확인 |
| 실패 후 잔여 화면 | INVALID_INPUT, 직전 성공 결과가 남지 않음 | AppTest 존재. 브라우저에서 성공→실패 연속 조작 확인 |
| 검토 저장 | revision 증가, 예측 원본 유지 | AppTest·브라우저 defer 저장 검사 존재 |
| JSON/CSV ZIP 다운로드 | core 수치·null/0·review/provenance 일치 | 현재 브라우저 테스트에 다운로드 내용 assertion 없음. 추가 가치 높음 |
| Plotly 지도 | +X 오른쪽, +Y 위쪽, 노치 6시, 축 비율·범례·강조가 의도와 일치 | 실제 화면 점검과 수치 검증 병행 |

접근성 스냅샷의 텍스트만으로 Plotly의 점 위치·방향·축 비율이 정확하다고 확정하지 않는다. 화면 증빙과 독립 좌표/집계 정답을 함께 비교한다. E15/E16/E19 전체 완료와 개별 하위 case 통과도 구분한다.

## 6. 이 프로젝트에 만들면 유용한 Skill

아래 이름 중 `wafer-verify`, `wafer-contract-audit`는 **2026-10-09에 설치됐다**(11절). `wafer-fixture-audit`는 아직 제안 상태다. 본문에 기존 계약을 통째로 복사하기보다 `CLAUDE.md`, 실행계획, TBD, 실제 테스트를 읽도록 구성한다.

| 제안 Skill | 포함할 절차 | 연결할 파일·시나리오 |
|---|---|---|
| `wafer-verify` | 변경 파일 확인 → 관련 계약/독립 oracle 확인 → 영향받는 시험 → 증빙 보고 | 좌표 E02/E08, UI E15/E16, 저장 E17~E19 |
| `wafer-contract-audit` | README/TBD/실행계획과 실제 인터페이스 비교 → 오래된 설명과 실제 결함 구분 | 이번에 확인한 UI·coverage·브라우저 안내 차이 |
| `wafer-fixture-audit` | 합성/실제 출처, seed, 단위·노치·coverage, oracle 독립성 확인 | `tests/fixtures/`, `klarf_dummy_data/`, 시험 profile |

먼저 `wafer-verify` 한 개로 시작하고 다른 절차가 자주 반복될 때 분리한다. 스킬은 체크리스트를 재사용하는 역할이고 서브에이전트는 작업 책임을 분리하는 역할이다. 스킬이 모든 agent를 매번 호출하게 만들 필요는 없다.

`wafer-verify`에 넣을 최소 계약:

1. 현재 git 변경과 요청 범위를 확인하고 사용자 변경을 보존한다.
2. 해당 C/E ID, 입력 fixture, 독립 기대값, 기존 테스트의 최신성을 확인한다.
3. 기존 insenv의 Python 경로·버전을 확인한다. 매번 환경을 만들거나 패키지를 재설치하지 않는다.
4. 영향받는 테스트를 먼저 실행한다. 브라우저 skip을 PASS로 계산하지 않는다.
5. 숫자 정답을 현재 production 출력에서 복사해 만들지 않는다.
6. 실행 명령·환경·기대/실제·증빙·남은 한계를 보고한다. 실제 장비 검증과 합성 검증을 분리한다.

검증 스킬을 사용자 호출 전용으로 두고 싶으면 `disable-model-invocation: true`를 사용한다. 메타데이터의 `name`, `description`과 SKILL.md 형식은 [Claude Code Skills 공식 문서](https://code.claude.com/docs/en/skills)를 따른다. 이 가이드 자체는 자동으로 로드되는 스킬 파일이 아니다.

## 7. 선택 MCP와 지금 보류할 구성

**Context7 MCP — 공개 라이브러리 문서 조회가 반복될 때만.** Streamlit·Plotly·Pydantic 등 사용 중인 버전에 맞는 API 확인에 활용할 수 있다. 조회할 라이브러리와 버전을 명시하고 실제 설치 버전 및 공식 문서와 대조한다. 사내 원본 데이터·lot ID·profile 내용을 문서 질의에 붙이지 않는다. 문서 검색은 사내 E1/E2나 adapter 정의의 근거가 아니다. 설치·인증 조건은 [공식 Context7 저장소](https://github.com/upstash/context7)에서 확인한다.

| 현재 보류 | 이유 / 다시 검토할 조건 |
|---|---|
| 별도 파일시스템·Git MCP | Claude Code 기본 파일·검색·Bash와 중복. 현재 로컬 작업에 연결 계층을 추가할 이유가 작음 |
| SQLite/PostgreSQL/Supabase MCP | 현재 `sqlite3` 저장 계층과 테스트로 접근 가능. 외부 DB 연동 요구가 생길 때 검토 |
| 별도 Chrome 디버깅 MCP | 일반 화면 탐색은 Playwright로 시작. 실제 성능·네트워크 진단에 추가 기능이 필요할 때 검토 |
| 범용 data-scientist/ML 학습 agent | 실제 라벨·blind set·운영 임계값 미확정. 현재 rule 기반 개발 순서를 따름 |
| PDF/Excel/Notebook 전용 skill | 현재 산출물은 JSON/CSV와 Streamlit. 해당 형식의 리포트가 실제 요구될 때 추가 |
| 대형 agent orchestration·memory MCP | 기존 3역할과 버전 관리 문서로 진행 가능. 미확정 운영 정의를 별도 기억 저장소로 복제할 이유가 없음 |

## 8. 기존 환경의 실행 예시

아래 명령은 저장소 루트의 PowerShell 예시다. Python 경로는 `CLAUDE.md`에 기록된 환경을 사용한다. (2026-10-09 실행: `-m "not e2e"` 319 passed, `-m e2e` 4 passed.)

```powershell
$waferPython = 'C:\Users\gongj\anaconda3\envs\insenv\python.exe'
& $waferPython -c "import sys; print(sys.executable); print(sys.version)"

# UI 로직 회귀: headless AppTest, 실제 브라우저 시험과 구분
& $waferPython -m pytest tests/test_app.py -q

# 브라우저 E2E: fixture가 임시 포트에서 서버를 시작하고 Edge 사용
& $waferPython -m pytest tests/test_e2e_browser.py -m e2e -q -rs

# 넓은 변경일 때 브라우저를 제외한 회귀
& $waferPython -m pytest tests -m "not e2e" -q

# 대화형 화면 탐색용 서버: 별도 터미널에서 필요한 경우 실행
& $waferPython -m streamlit run wafer/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

브라우저 E2E 파일은 자체 서버를 시작하므로 마지막 수동 실행 명령이 선행 조건은 아니다. 현재 테스트는 브라우저 실행 실패를 skip으로 처리한다. `-rs`의 사유를 보고 환경 문제를 BLOCKED로 기록하며, 코드의 광범위한 예외 처리가 실제 오류까지 숨기는지도 필요할 때 조사한다.

Streamlit AppTest는 실제 브라우저 없이 UI 로직을 검사하는 별도 층이다. 다운로드·렌더링·실제 브라우저 동작은 브라우저 검증으로 보완한다. [Streamlit App testing](https://docs.streamlit.io/develop/api-reference/app-testing)

## 9. Claude Code에 바로 사용할 요청 예시

### 현재 도구만으로 UI 변경 검증

```text
CLAUDE.md와 CLAUDE_CODE_TOOLING_GUIDE.md를 읽고 현재 git 변경을 보존해줘.
wafer-test-maintainer를 audit 모드로 사용해 이번 UI 변경에 관련된 E15/E16/E19 하위 case만 점검해줘.
wafer/app.py는 wafer.cli.run_job을 재사용하고 분석 로직을 복제하지 않도록 해줘.
구현 후 wafer-e2e-validator로 관련 AppTest와 기존 Edge E2E를 실행해줘.
최종적으로 wafer-contract-reviewer가 개수·상태·export·revision 계약을 확인하게 해줘.
실제 실행 결과와 skip/BLOCKED를 구분하고 합성 시험을 장비 검증으로 보고하지 마.
```

### Playwright 탐색 도구를 연결한 뒤 다운로드 확인

```text
연결된 Playwright로 로컬 Streamlit 앱을 열고 합성 F01과 시험 profile을 입력해줘.
included=8, center=1과 bin/sector oracle을 확인하고 B1 필터는 표시만 바꾸는지 확인해줘.
JSON과 CSV ZIP을 내려받아 수치·null/0·review revision·provenance 정합성을 비교해줘.
기존 tests/test_e2e_browser.py의 누락을 먼저 확인한 뒤 필요한 Python 회귀만 추가해줘.
사내 데이터 대신 합성 fixture와 임시 DB를 사용하고 현재 oracle을 출력값으로 덮어쓰지 마.
```

## 10. 이번 문서의 확인 범위

- 수행: 프로젝트 구조, 기존 agent 정의, 앱·CLI·저장·리포트 관련 코드, UI 테스트, fixture 목록, 요구사항·보류 기록 검토; 공식 도구 문서 조회.
- 검증: 문서의 로컬 경로와 예시 대상 테스트 존재 여부, 기존 Edge 실행 방식, 추천 역할의 중복 여부 확인.
- 미수행: pytest/앱 실행, Node/Claude Code 버전 확인, MCP 연결, agent 호출, 스킬 설치, 실제 장비 데이터 검증.
- 변경: 이 가이드 파일만 추가. 기존 코드·설정·완료 체크는 변경하지 않음.

도입 순서는 **기존 agent 확인 → 기존 테스트 실행 → 반복 검증 스킬 작성 → 필요한 경우 브라우저 탐색 도구 하나 추가**를 권장한다.

## 11. 적용 결과 (2026-10-09)

이 가이드의 제안 중 아래 항목을 실제로 적용했다. 위 1~10절의 "미수행/예시" 문구는 작성 당시 기록으로 남기고, 현재 상태는 이 절을 기준으로 한다.

| 항목 | 상태 | 내용 / 증빙 |
|---|---|---|
| 기존 서브에이전트 3개 | 유지(적용) | `.claude/agents/` 그대로. 중복 agent 추가 없음 |
| `wafer-verify` 스킬 | 적용 | `.claude/skills/wafer-verify/SKILL.md` — 변경 파일별 테스트 선택, 독립 oracle, insenv, PASS/FAIL/NOT_RUN/BLOCKED/N/A. 새 헤드리스 세션(`claude -p`)에서 이름 인식 확인 |
| `wafer-contract-audit` 스킬 | 적용 | `.claude/skills/wafer-contract-audit/SKILL.md` — 문서·코드·YAML·테스트 정합성, 오래된 설명/승인된 변경/코드 결함/미확정 정의 구분. 같은 방법으로 인식 확인 |
| Playwright MCP | 등록(사용자 승인 대기) | 전역 설정에 같은 MCP가 없음을 `claude mcp list`로 확인 후 project scope로 등록. `.mcp.json`: `cmd /c npx -y @playwright/mcp@0.0.83 --browser msedge --isolated`(버전 고정). 상태는 "Pending approval" — 대화형 `claude`에서 사용자가 승인해야 세션 도구로 쓰인다. 승인 우회 설정은 하지 않음 |
| MCP 동작 | 확인(stdio 직접) | `.mcp.json` 명령으로 서버를 띄워 JSON-RPC로 initialize·tools/list(25개)·browser_navigate·browser_type·browser_click·browser_snapshot 호출. 로컬 Streamlit에 합성 F01과 시험 profile을 입력해 job_status=succeeded, parsed/included/excluded/center=8/8/0/1 확인(Edge, isolated). 대화형 세션의 MCP 도구 호출은 승인 전이라 NOT_RUN |
| Python Playwright E2E | 유지 | `tests/test_e2e_browser.py`(Edge `channel="msedge"`) 4 passed — 기존 회귀 기준 |
| Playwright CLI+Skills | 보류(중복 방지) | MCP를 선택했으므로 설치하지 않음 |
| Context7, DB/파일시스템/Git MCP, 별도 agent | 보류 | 7절 사유 그대로 |

설치 시 주의: Git Bash에서 `claude mcp add ... -- cmd /c ...`를 실행하면 `/c`가 `C:/`로 경로 변환된다. PowerShell에서 실행하거나 `.mcp.json`의 `args`가 `"/c"`인지 확인한다. MCP 도구 인자 이름은 버전에 따라 다르다(0.0.83의 `browser_type`·`browser_click`은 요소 지정에 `target`을 쓴다).

남은 조치:
1. 사용자가 이 저장소에서 `claude`를 실행해 프로젝트 MCP `playwright`를 승인하고 `/mcp`에서 연결을 확인한다.
2. ~~다운로드 내용 대조~~ **완료(2026-10-10):** `tests/test_e2e_browser.py`가 실제 Edge에서 내려받은 JSON·CSV zip을 독립 기대값과 대조한다(4건, coverage 유/무, 검토 저장 전·후).
3. 버전을 올릴 때는 `.mcp.json`의 고정 버전을 바꾸고 같은 확인을 반복한다.
