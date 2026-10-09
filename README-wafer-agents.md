# Wafer 검사용 Claude Code 에이전트

## 구성과 설치

프로젝트별 agent 정의를 `.claude/agents/`에 두는 공식 형식을 사용한다. 각 파일은 YAML frontmatter와 Markdown 지침으로 구성했다. 기존 `CLAUDE.md`는 그대로 두고 이 묶음의 `.claude` 내용을 프로젝트의 `.claude`에 병합한다. 기존 settings나 다른 agent를 지우지 않는다.

| 파일/agent 이름 | 역할 | 도구와 변경 범위 |
|---|---|---|
| `wafer-test-maintainer.md` | 테스트 최신성 점검과 근거 있는 개정 | Audit은 검토만, update는 위임된 테스트/문서 수정과 관련 시험 |
| `wafer-e2e-validator.md` | 실제 흐름 실행과 정답·증빙 대조 | Read/검색/Bash, 소스·설정·기대값 수정 금지 |
| `wafer-contract-reviewer.md` | 계약 위배 및 과도한 설계 검토 | Read/검색만, 파일 수정과 시험 실행 불가 |

모델은 모두 `inherit`, 권한 모드는 `default`다. Agent 정의 자체에는 MCP, hook, 영구 memory, orchestration framework를 넣지 않았다. 프로젝트 MCP(`.mcp.json`의 Playwright)와 스킬은 별도 구성이며, agent가 MCP 도구를 자동으로 쓴다고 가정하지 않는다(validator는 Bash 기반 Python E2E를 실행한다). Validator와 maintainer의 Bash는 도구 자체로 파일 쓰기를 차단하지 않으므로 정의의 작업 범위 지침을 따라야 한다.

설치 후 Claude Code에서 `/agents`로 세 이름을 확인한다. 처음 `agents` 디렉터리를 만들었다면 세션을 다시 시작하고 확인한다. Agent가 필요할 때 이름을 명시해 호출한다. 작은 변경은 메인 Claude Code가 직접 같은 체크를 수행할 수 있다.

## 현재 설치 상태 (2026-10-09 확인)

- `.claude/agents/`에 세 정의가 있고, 이 저장소의 Claude Code 세션에서 세 이름으로 실제 호출해 audit·update·실행 검증·정적 검토에 사용했다.
- 함께 쓰는 프로젝트 스킬: `/wafer-verify`(변경 범위별 테스트 선택·독립 oracle·insenv·상태 구분), `/wafer-contract-audit`(문서·코드·YAML·테스트 정합성). 위치 `.claude/skills/<name>/SKILL.md`. 스킬은 체크리스트이고 agent는 책임 분리라서 서로 대체하지 않는다.
- 브라우저 탐색용 Playwright MCP는 `.mcp.json`(project scope)에 등록돼 있다. 처음 사용할 때 대화형 `claude`에서 프로젝트 MCP를 승인해야 한다. 자세한 내용은 `CLAUDE_CODE_TOOLING_GUIDE.md`.

## 기준 파일

프로젝트에 기존 `CLAUDE.md`, `wafer_inspection_execution_plan.md`, `wafer_inspection_map_knowledge.md`, `requirements.txt`를 함께 둔다. 다른 폴더에 있으면 실제 위치를 전달한다. 이 묶음에는 해당 문서의 복사본을 넣지 않았으므로 중복 버전이 생기지 않는다.

## 권장 작업 순서

1. 변경 전 `wafer-test-maintainer`를 audit 모드로 호출해 이번 변경에 해당하는 시나리오 최신성을 확인한다.
2. 메인 Claude Code가 확인된 계약에 맞춰 최소 기능을 구현한다.
3. 개정이 필요하면 maintainer를 update 모드로 호출한다. 유효한 테스트에 실패하는 코드는 메인이 수정한다.
4. `wafer-e2e-validator`가 고정한 코드·정답으로 영향받는 case를 실행한다.
5. `wafer-contract-reviewer`가 최종 파일과 실행 결과의 계약 정합성을 확인한다.
6. 실패나 주요 위배가 있으면 메인이 수정하고 영향받는 시험·검토를 반복한다. 최종 증빙으로만 완료 체크를 갱신한다.

에이전트를 동시에 같은 파일에 쓰게 하지 않는다. 이번 단계의 변경 파일, 활성 기능, C/E ID와 결과를 다음 역할에 전달한다. 전체 프로젝트를 매번 세 역할로 순회할 의무는 없지만 CLAUDE.md의 필수 점검은 생략하지 않는다.

## 그대로 사용할 위임 메시지

다음은 이름을 명시한 자연어 호출 예시다. Agent 정의가 정상 인식됐는지 먼저 `/agents`에서 확인한다.

```text
wafer-test-maintainer 에이전트를 audit 모드로 사용해줘.
이번 작업: KLARF 입력, 노치 6시 정규화, bin 및 시계방향 집계 CLI 구현.
실행계획의 F01/E01과 영향받는 E02/E03/E08~E13, C 항목을 확인해줘.
관련 실제 파일을 찾아 현행 유지, 근거 있는 개정 필요, 코드 결함, 판단 보류를 나눠 보고해줘.
파일 수정과 테스트 실행은 하지 말아줘.
```

```text
메인에서 이번 요청의 최소 구현을 진행해줘.
방금 audit 결과를 반영하고 최신 CLAUDE.md의 좌표·count·상태 계약을 지켜줘.
코드 변경이 완료되면 개정이 필요한 테스트만 wafer-test-maintainer를 update 모드로 사용해 수정하고 관련 회귀를 실행해줘.
현재 구현이 유효한 정답에 실패하면 정답을 바꾸지 말고 코드를 고쳐줘.
```

```text
wafer-e2e-validator 에이전트를 사용해 이번 변경의 통합/E2E를 검증해줘.
변경 목적, 실제 변경 파일 또는 diff, 활성 기능, 확정된 oracle과 maintainer 결과를 전달해줘.
실제 존재하는 테스트와 연결 E 하위 case를 실행하고 기대/실제값·상태·증빙을 보고해줘.
소스와 테스트 기대값은 수정하지 말고 합성·mock·실제 장비 검증을 구분해줘.
```

```text
wafer-contract-reviewer 에이전트를 사용해 최종 변경을 읽기 전용으로 검토해줘.
최종 변경 파일/diff와 maintainer 및 validator 결과를 전달해줘.
적용 C01~C20에 대해 요구사항·코드·YAML·테스트·리포트의 상호 위배와 과도한 설계를 확인해줘.
치명/주요 결함은 최소 수정안으로 보고하고 정적 검토를 E2E PASS로 표현하지 말아줘.
메인은 결함 수정 후 영향받는 검증을 반복하고 증빙에 따라 완료 체크를 갱신해줘.
```

## 이 묶음의 검증 범위

생성 시 frontmatter, 이름/도구/역할 범위, 문서 참조, 기존 CLAUDE.md 및 실행계획과의 정합성을 점검한다. 최초 문서 생성 시에는 실제 agent 로딩·호출, 프로그램 구현, pytest/E2E를 검증하지 않았다. 이후 이 저장소 작업에서 세 agent의 실제 호출과 위임 결과를 확인했다(위 "현재 설치 상태").

## 공식 형식 참고

Anthropic, Claude Code: [Create custom subagents](https://code.claude.com/docs/en/sub-agents).
파일 위치, frontmatter, tools/model/permissionMode, `/agents`, agent 이름을 명시한 호출 방식의 근거다. 프로젝트별 역할과 검증 규칙은 기존 실행계획 및 CLAUDE.md에 맞춘 자체 지침이다.
