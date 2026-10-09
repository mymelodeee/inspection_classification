---
name: wafer-verify
description: Verify a change in this wafer-inspection project - pick the tests that match the changed files, compare against independent oracles (not production output), run them with the existing insenv Python, and report PASS / FAIL / NOT_RUN / BLOCKED / N/A with evidence. Use after editing wafer/*, tests/*, profiles, fixtures, or before reporting a task as done.
---

# wafer-verify

Repeatable verification for this repository. The contracts live in `CLAUDE.md` (sections 4-6),
`wafer_inspection_execution_plan.md` (16, 17-20) and `TBD.md`; read the parts that apply instead of
relying on memory. Do not copy the contracts into the report - cite the C/E IDs.

## 1. Scope first

1. `git status --short` and `git diff --stat`: list what changed. Preserve user changes and uncommitted work;
   never revert, reformat or "clean up" files outside the request.
2. Map each changed file to its checks (table below) and to the C/E IDs it affects.
3. Docs-only change -> no full test run is required; check links/commands/claims against code instead
   (use the `wafer-contract-audit` skill). Report tests as NOT_RUN with that reason.

| Changed | Run first | Independent oracle | C / E |
|---|---|---|---|
| `wafer/ingest.py`, adapters, `tests/fixtures/klarf*`, `klarf_dummy_data/` | `tests/test_ingest_cli.py tests/test_dummy_klarf18.py` | `tests/fixtures/f01/oracle.json`, `klarf_dummy_data/manifest.json` + `expected/*` | C01-C04, E01-E03, E09, E10, E13 |
| `wafer/geometry.py`, `wafer/aggregate.py` | `tests/test_geometry.py tests/test_aggregate_f01.py tests/test_phase2_fixtures.py` | F01 oracle, `tests/fixtures/e08_boundary` | C11, C14, E01, E08 |
| `wafer/profile.py`, `tests/profiles/*.yaml` | `tests/test_profile.py` | hand cases in the test | C05, C12, E12 |
| `wafer/stats.py`, coverage sidecar (`--coverage`) | `tests/test_stats.py tests/test_dummy_klarf18.py -k "t7 or coverage"` | hand-computed annulus areas | C06, C07, E11, E23 |
| `wafer/clustering.py detect.py ring.py line.py groups.py` | `tests/test_phase2_fixtures.py tests/test_e05_line_arc.py tests/test_e06_mixed.py` | `tests/fixtures/e04_noise`, `ring_band`, `e05_line_arc`, `e06_mixed` | C08-C11, E04-E06 |
| `wafer/lift_pin.py` | `tests/test_e07_lift_pin.py` | `tests/fixtures/e07_lift_pin` | C09, C19, E07 |
| `wafer/report.py`, CSV/manifest | `tests/test_ingest_cli.py -k csv` | JSON of the same run + oracle totals | C15, E16 (partial) |
| `wafer/store.py`, `wafer/version.py` | `tests/test_store.py` | hand cases (key reuse, append-only revisions) | C17, E17-E19 |
| `wafer/app.py` | `tests/test_app.py`, then browser `-m e2e` | F01 oracle values asserted directly | C15, E15, E16, E19 |
| `wafer/cli.py` (shared `run_job`) | all of the above with `-m "not e2e"` | - | - |

Wide or cross-cutting change: `pytest tests -q -m "not e2e"`, then `-m e2e`.

## 2. Environment (do not rebuild it)

- Use the prepared conda env `insenv`: `C:\Users\gongj\anaconda3\envs\insenv\python.exe` (Python 3.12).
  Print `sys.executable` and `sys.version` once. Do not create a venv or reinstall requirements;
  install only when dependencies actually changed.
- Browser E2E uses the system Edge through Python Playwright (`channel="msedge"`); no browser download.
- The project Playwright MCP (`.mcp.json`) is for interactive exploration by the main session, not a
  replacement for the pytest E2E.

```powershell
$py = 'C:\Users\gongj\anaconda3\envs\insenv\python.exe'
& $py -m pytest <selected test files> -q
& $py -m pytest tests -q -m "not e2e"
& $py -m pytest tests -q -m e2e -rA      # -rA shows PASSED / SKIPPED reasons
```

## 3. Oracle rules

- Expected values come from fixture oracles, the plan (19.2 F01 etc.), hand calculation, or reviewed
  real data - never from the current production output. If a test must change, it must be an approved
  spec change (see TBD decisions) recorded as `<E-ID>-UP` with old/new values and the reason.
- Do not widen tolerances, delete assertions, or add skip/xfail to make a run pass.
- Synthetic fixtures prove the synthetic contract only. A pass is not equipment-adapter validation,
  shape-classification performance, or support for in-house input (TBD T-29).

## 4. Status vocabulary

| Status | Use when |
|---|---|
| PASS | ran, met the fixed criterion, evidence recorded |
| FAIL | ran, criterion violated - report it, do not hide it |
| NOT_RUN | not executed (out of scope, docs-only change) |
| BLOCKED | cannot be judged: missing real samples, definitions, environment (e.g. browser could not launch -> the E2E test skips with "BLOCKED: ...") |
| N/A | feature disabled or out of release scope, with a reason |

A skipped test is never PASS. A parent scenario is PASS only when all its required sub-cases pass.

## 5. Report

1. Changed files and the checks selected (with C/E IDs).
2. Commands, environment (Python path/version, browser), and the real output counts.
3. Expected vs actual for the key numbers, oracle source.
4. Synthetic vs real-data split; what stayed NOT_RUN / BLOCKED and what data would unblock it.
5. Completion checkboxes in the plan are updated only with recorded evidence, marked "(합성 증빙)" when synthetic.
