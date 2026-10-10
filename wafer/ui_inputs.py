"""Shared defaults for the local analysis screens (paths, never cached file contents)."""
from pathlib import Path

DEFAULT_PROFILE = str(Path(__file__).resolve().parents[1] / "tests/profiles/dummy_die_local_test_profile.yaml")
PROFILE_HELP = "기본 경로의 YAML을 덮어쓰면 다음 분석 때 최신 내용을 읽습니다. 업로드한 profile이 있으면 업로드가 우선합니다. 현재 기본값은 dummy 데이터 시험용입니다."
COVERAGE_HELP = "검사한 면적을 선언하는 JSON 파일 경로입니다. 예: tests/fixtures/coverage/full_disk_150.json. 밀도 계산의 분모이며 일괄 분석의 모든 파일에 공통 적용됩니다."
DB_HELP = "분석 결과·실행 이력·검토를 보존하는 SQLite 파일입니다. 예: analysis_test.db. 동일 경로로 재실행하면 같은 분석 키의 저장 결과를 재사용합니다."
