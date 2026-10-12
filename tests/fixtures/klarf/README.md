# Synthetic KLARF fixtures (SYNTHETIC - not a real tool export)

Hand-written KLARF text in the flat 1.2-style syntax (`Key value;` header lines, `DefectRecordSpec`,
`DefectList` rows, `;` terminator) that only carries the version token `FileVersion 1 8`. It is NOT the
KLARF 1.8 Record/Field/List syntax; that syntax is exercised by `klarf_dummy_data/`
(`tests/test_dummy_klarf18.py`). See docs/9_TBD.md T-12. Header fields follow common KLARF names but this is NOT
verified against any real equipment export (Phase 0 / P0-01, P0-02 pending). Passing these
files proves nothing about a tool adapter (CLAUDE.md 6-9, C20).

## Assumed SYNTHETIC adapter (documented, deliberately trivial)
- `DefectRecordSpec` columns: DEFECTID XREL YREL XINDEX YINDEX CLASSNUMBER TEST.
- XREL/YREL are in micrometres. Single die: XINDEX=YINDEX=0 for every defect, the die origin
  coincides with the wafer centre (`DieOrigin 0 0`, `SampleCenterLocation 0 0`), so DiePitch
  (400000 um, larger than the wafer) plays no role. No pitch trick is used.
- If `OrientationMarkLocation` is absent the run still succeeds with partial results (counts, bins, radial/edge zones);
  clock sectors and phase are withheld (`orientation_status=unknown`, T-02 decision 2026-10-09). A notch other than DOWN
  is still rejected for this adapter.
- `x_mm = XREL/1000`, `y_mm = YREL/1000`. +X right, +Y up, no mirror (`CoordinatesMirrored NO`),
  notch already at 6 o'clock (`OrientationMarkLocation DOWN`) so NO rotation is applied
  (guards against double rotation, C03).
- CLASSNUMBER 1/2/3 -> bins "1"/"2"/"3" (plan F01 names them B1/B2/B3; label unified 2026-10-09, T-03). CLASSNUMBER 0 -> unclassified -> must be kept as an unknown bin.
- Wafer radius R=150 mm is profile data, not read from the file (SampleSize 1 300 = 300 mm dia).
- All defects share die (0,0): affected-die count is 1 for every file with defects (E09 die
  separation needs a multi-die variant; not provided).

## Files
| file | purpose | expected (derived by hand, see ../f01/oracle.json) |
|---|---|---|
| f01.klf | F01, E01 | 8 defects; oracle.json |
| empty_list.klf | E03 valid 0 defects | parse OK, N=0, no_detected_defect |
| single_point.klf | E03 N=1 (D02 at 50,0) | N=1, 3 o'clock, NN test insufficient_data |
| center_only.klf | E03 (D05 at 0,0) | center=1, sectors all 0 |
| e09_unclassified_bin.klf | E09: F01 with D08 CLASSNUMBER 0 | included 8, "1"=3,"2"=2,"3"=2,unknown=1 |
| bad_truncated.klf | E13 | last record cut mid-number, no `;`/EndOfFile -> explicit failure |
| bad_missing_coord_column.klf | E13 | spec lacks YREL -> INVALID_INPUT |
| bad_number.klf | E13 | defect 2 XREL `5O000.0` -> INVALID_INPUT at record 2 |
| bad_unsupported_version.klf | E13 | `FileVersion 9 9` -> unsupported, not 0 defects |
