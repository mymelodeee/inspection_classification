E05 합성 fixture(synthetic, seed=null, oracle e05-line-arc-1): LINE-CLEAN/LINE-NOISY/LINE-TWO-BLOBS(반례)/ARC-KNOWN/LINE-SPARSE(insufficient 후보)/SCATTER-SPARSE 6개 case의 점과 손계산 기대값(방향·길이·잔차·폭·gap·중심/반경)을 `e05_line_arc.json`에 기록; `python gen_e05_line_arc.py`로 재생성.

## E05-UP (2026-10-09): LINE-NOISY width
Old expectation: width_p95_minus_p5 = 2.0, tolerance 0.1 (generating-line frame). New check in
tests/test_e05_line_arc.py: 2.0 <= width <= 2.0 + |s| * L, where s is the regression slope of the +-1
pattern on the along-axis coordinate (computed independently, ~ -8.2e-4) because the code measures
normal distance about the fitted PCA axis. Reason: frame difference, not a relaxed tolerance. The JSON
field width_tolerance_mm (0.1) still describes the generating-line frame. Oracle e05-line-arc-1; C08/C19.
