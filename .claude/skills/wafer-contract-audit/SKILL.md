---
name: wafer-contract-audit
description: Audit consistency between the wafer-inspection documents (README.md, CLAUDE.md, TBD.md, execution plan, README-wafer-agents.md, CLAUDE_CODE_TOOLING_GUIDE.md), the code (wafer/*), the YAML profiles and the tests. Separates stale descriptions from approved spec changes and real defects. Use before or after documentation updates, after interface changes, or when a document claims a status.
---

# wafer-contract-audit

Static consistency check. It does not run the analysis and never reports a document review as a test PASS.
For execution evidence use the `wafer-verify` skill or the `wafer-e2e-validator` agent.

## 1. Read the sources of truth

- Requirements and contracts: `CLAUDE.md` (4: analysis contracts), `wafer_inspection_execution_plan.md`
  (5.3 input contract, 9 YAML, 10 results, 16 common contract, 17 checklist, 18 C table, 19 E scenarios).
- Decisions and open items: `TBD.md` (decided rows carry a date; open rows stay open).
- Current behaviour: `wafer/*.py`, `tests/profiles/*.yaml`, `tests/test_*.py`, `.claude/`, `.mcp.json`.

## 2. What to compare

| Claim in a document | Check against |
|---|---|
| CLI arguments, exit codes, output files | `wafer/cli.py` (`main`, `run_job`), `wafer/report.py` (`RESULT_KEYS`, `write_csv`) |
| Input support (syntax, adapters, notch, bins, coverage) | `wafer/ingest.py`, `load_coverage` in `wafer/cli.py`, `tests/fixtures/klarf/README.md`, `klarf_dummy_data/README.md` |
| Profile keys, required/optional, defaults | `wafer/profile.py` (`_check`, `validate_for_run`) and the test profiles |
| UI features (inputs, map, tables, review, downloads) | `wafer/app.py`, `tests/test_app.py`, `tests/test_e2e_browser.py` |
| Storage, analysis key, review revisions | `wafer/store.py` (`KEY_PARTS`), `wafer/version.py` |
| Test commands and counts | `pytest.ini`, test files; counts must cite a dated run, not be assumed |
| Agent / skill / MCP setup | `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.mcp.json`, `claude mcp list` |
| Completion checkboxes / C table | recorded evidence in plan 20.2 or task reports |

## 3. Classify every finding

1. **Stale description** - the document lags behind code that implements an approved decision (TBD row
   with a date, or an explicit user decision). Fix the document.
2. **Approved spec change not yet reflected** - update the plan/TBD record and the tests' `-UP` notes.
3. **Code defect** - the code violates a still-valid contract. Do not edit the requirement to match the
   code; report it (fix it only if the task allows code changes).
4. **Open definition** - in-house values (E1/E2, band width, lift-pin template, coverage, thresholds,
   real input contract T-29) remain open/BLOCKED. Never fill them from code defaults or test-only values.

Keep these distinctions explicit in edited text:
- "validated on synthetic input" vs "in-house input supported" (the latter is not done - T-29),
- test-only profile values vs operating values,
- `candidate` vs `matched` (matched only with a calibrated, approved rule),
- dated historical records (keep them, add an update line) vs current state.

## 4. Edit rules

- Minimal edits; preserve the user's wording and uncommitted work; do not rewrite whole files.
- Do not invent counts, versions or results. Cite the command and date of the run that produced a number.
- Do not mark checklist items or C rows complete from a document review.

## 5. Report

List each finding as: file:line, claim, actual (with code reference), class (1-4), action taken or proposed.
End with what remains open and which documents were checked but needed no change.
