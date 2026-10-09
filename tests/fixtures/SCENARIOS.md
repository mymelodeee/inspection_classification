> **주의(2026-10-09 갱신):** 아래 점검표는 코드 작성 전 시점의 기록이다. 현재는 wafer/ 코드와 tests/test_*.py가 존재하며(합성 경로 한정), 상태어휘·INVALID_INPUT·zone 중첩 항목은 TBD.md T-10에서 결정되었다. 실행 상태의 최신 기록은 작업 보고와 TBD.md를 따른다.

> 추가(2026-10-09): E16-DL/E19-DL — 브라우저에서 실제로 내려받은 result.json과 result_csv.zip을 열어 독립 기대값(plan 19.2 + fixture 본문에서 재도출, provenance 해시는 hashlib 재계산)과 대조한다. 화면-파일 비교만으로는 두 채널이 함께 틀린 경우를 잡지 못하므로 파일 값 자체를 oracle과 비교한다. tests/test_e2e_browser.py.

> 추가(2026-10-09): E08 경계(`e08_boundary/`), E04 noise(`e04_noise/`), ring/band(`ring_band/`) 독립 fixture가 생겼다. 15°/345° 정확 경계는 T-18로 보류.

# Scenario audit (Phase 1 prep) - plan v1.1, 2026-10-09
Status values: no test has been run. Every entry below is NOT_RUN. "Runnable now" = can be executed
on synthetic fixtures once Phase 1 code exists; it is not a PASS and not an adapter validation.

| E | Phase 1 synthetic scope (runnable once code exists) | BLOCKED / deferred | C IDs | Fixture / oracle |
|---|---|---|---|---|
| E01 | CLI-only: parse f01.klf, 8/8/0, bins "1"=3 "2"=3 "3"=2 (plan F01 B1/B2/B3; label unified 2026-10-09, T-04), center 1, 12 sectors, JSON/CSV equality. Image-free. UI/overlay/screen parts N/A until UI exists (partial core pass only, plan 19.1) | UI screen, hash of real profile | C01 C02 C14 | klarf/f01.klf, f01/oracle.json |
| E02 | Synthetic only if variants authored: UP/LEFT/RIGHT, um vs mm, center offset. Only DOWN/um/no-offset exists now | Real adapter for notch/side/mirror/center, backside flip, "already normalized" variants need real tool export + P0-02 | C03 C04 | none beyond f01.klf (variants TODO) |
| E03 | empty_list, single_point, center_only | Coverage-known variant needs a coverage spec; NN test only if Phase 2 | C14 C15 | klarf/empty_list.klf, single_point.klf, center_only.klf |
| E08 | F01 zones/sectors (oracle). Boundary-only fixture (edge 0/2/5, r 99/100/101, theta 15/345, center +-) not yet authored | zone-disabled profile run needs profile schema; real E1/E2 definitions are in-house (P0-05) | C10-C14 | f01/oracle.json zones; boundary fixture TODO |
| E09 | unclassified bin (provided). Same-coord duplicates + cross-inspection same ID not authored | Affected-die counts need multi-die inspected-die denominator; sampling/inspected die list unknown | C02 C11 | klarf/e09_unclassified_bin.klf |
| E10 | Notch-unknown partial path (2026-10-09, T-03): f01 / dummy F01_counts / F01_up / ring / line with OrientationMarkLocation removed (generated in tmp_path by tests) -> counts, bins, radial zones, center kept; clock, phase and direction keys withheld | Side semantics, unit/center unknown handling needs real field semantics | C04 C05 C13 C15 | tests/test_ingest_cli.py, tests/test_dummy_klarf18.py, tests/test_app.py (E10-UP) |
| E11 | Partial: coverage-less F01 gives density null (needs profile) | Coverage geometry source and area oracle undefined (P0-03) | C05 C06 C07 | TODO |
| E12 | Pure YAML validation, no KLARF needed, but requires profile schema (sec 9) in code | In-house E1/E2/gripper values unconfirmed | C05 C12 C15 | TODO |
| E13 | truncated, missing column, bad number, unsupported version, empty (valid) | "Being-written file" and ingest/auto-collection state transitions: needs watcher/job layer; real vendor corruption modes | C15 C20 | klarf/bad_*.klf, empty_list.klf |

## Plan text audit (not edited)
1. Sec 19.1 vs 19.2 "Fixture status": says no KLARF fixture exists; now synthetic ones exist. Needs revision when adopted. (Current otherwise: oracle matches 19.2 exactly.)
2. Sec 8.1 states list (matched, candidate, unknown, insufficient_data, invalid_input, no_clear_pattern, no_detected_defect) vs sec 16.2 feature_status (matched, candidate, no_match, unknown, insufficient_data, disabled). Contradiction: no_clear_pattern/no_detected_defect/invalid_input absent from 16.2, no_match absent from 8.1. E03 uses no_detected_defect, E12 uses disabled. Needs revision (status vocabulary).
3. Sec 16.1 "INVALID_INPUT" (file errors) vs 16.2 data_quality_status "invalid" / job_status "failed": error-code vs status-field naming unspecified; E13 expects "explicit failure". Needs revision (mapping).
4. Sec 8.3 "Band width undecided, rule disabled until set" vs 19.2/E08 test band |r-100|<=1: consistent only as test-only profile; ensure oracle/profile marked test-only (done in oracle.json, C12).
5. Sec 8.3 allows E1 vs inner-zone overlap; E12 lists "허용되지 않은 zone 중첩" without defining which overlaps are disallowed. Needs revision/definition before E12 can be written.
6. Sec 6.3 "345~15 deg is 12 o'clock" is ambiguous at 15 deg; E08/16.3 resolve ([lo,hi), 15 deg -> 1 o'clock). Current, but 6.3 should cite the half-open rule.
7. E11 "면적 0 = 계산 불가, count 0 & area>0 -> density 0" vs E03 "유효면적이 있으면 0건 density=0": consistent.
8. F01 E1 = edge distance [0,2) (D06 edge dist 1; D07 edge dist 2 -> E2) is consistent with oracle. Note 6.4 and 16.3-8 (r=R included) is not exercised by F01 (max r=149); covered only by the E08 boundary fixture (TODO).
9. E02 "허용오차" / E08 "tolerance" values not specified numerically anywhere; blocks writing assertions (needs decision).
No code defects assessed (no code exists).
