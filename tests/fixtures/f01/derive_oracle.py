"""Standalone, stdlib-only derivation of the F01 oracle (plan sec 19.2, v1.1).
Independent of any production code. Usage: python derive_oracle.py > oracle.json
Sector rule: half-open [center-15, center+15) deg per clock hour (plan 6.3/16.3-7).
"""
import json, math
R, CEN = 150.0, 1.0
D = [("D01",0,50,"B1"),("D02",50,0,"B1"),("D03",0,-50,"B2"),("D04",-50,0,"B2"),
     ("D05",0,0,"B1"),("D06",149,0,"B3"),("D07",148,0,"B3"),("D08",100,0,"B2")]
rows, sec, bins = [], {h: 0 for h in range(1, 13)}, {}
zones = {"E1": [], "E2": [], "inner_r_lt_100": [], "band_100mm_pm1": []}
center = 0
for i, x, y, b in D:
    r = math.hypot(x, y)
    bins[b] = bins.get(b, 0) + 1
    if r < CEN:
        lab = "center"; center += 1; theta = None
    else:
        theta = math.degrees(math.atan2(x, y)) % 360
        h = int(((theta + 15) % 360) // 30) or 12
        sec[h] += 1; lab = h
    e = R - r
    if 0 <= e < 2: zones["E1"].append(i)
    if 2 <= e < 5: zones["E2"].append(i)
    if r < 100: zones["inner_r_lt_100"].append(i)
    if abs(r - 100) <= 1: zones["band_100mm_pm1"].append(i)
    rows.append({"id": i, "x_mm": x, "y_mm": y, "bin": b, "r_mm": r,
                 "theta_clock_deg": theta, "edge_distance_mm": e, "sector": lab})
assert sum(sec.values()) + center == len(D)
print(json.dumps({"defects": rows, "bins": bins, "center": center,
                  "sectors_clock": {str(k): v for k, v in sec.items()}, "zones": zones}, indent=1))
