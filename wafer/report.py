"""Result schema check and CSV export (E16 preparation). CSV values come from the same result dict and
point rows as the JSON, never recomputed. In CSV, null is written as an empty cell and a real zero as 0.
"""
import csv
import json
from pathlib import Path

# Top-level keys every successful result carries. A feature that did not run is present with its own
# status (feature_status / calc_status) or null - never silently absent (plan 10.2, C15).
RESULT_KEYS = ("n_parsed", "n_included", "n_excluded", "excluded", "bin_totals", "boundary_tolerance_deg",
               "orientation_status", "clock_status", "center", "sectors_clock", "sectors_clock_tolerant", "n_multi_sector", "boundary_ambiguous",
               "bin_sector", "zones", "zones_status", "zone_union_unique", "radial_density", "clark_evans", "detect",
               "lift_pin", "pattern_summary", "affected_die_count", "inspected_die_count", "provenance")


class ResultInvariantError(ValueError):
    """A finished result breaks a counting contract: a program defect, never a data condition."""


def check_result(res):
    missing = [k for k in RESULT_KEYS if k not in res]
    extra = [k for k in res if k not in RESULT_KEYS]
    if missing or extra:
        raise ResultInvariantError(f"result schema mismatch: missing={missing} extra={extra}")
    if res["n_parsed"] != res["n_included"] + res["n_excluded"]:
        raise ResultInvariantError("count conservation violated: n_parsed != n_included + n_excluded")
    if sum(res["bin_totals"].values()) != res["n_included"]:
        raise ResultInvariantError("bin totals do not sum to n_included")
    if res["sectors_clock"] is not None and sum(res["sectors_clock"].values()) + res["center"] != res["n_included"]:
        raise ResultInvariantError("12 sectors + center != n_included")
    bs = res["bin_sector"]
    if bs is not None:
        for b, row in bs.items():
            if sum(row.values()) != res["bin_totals"][b]:
                raise ResultInvariantError(f"bin_sector row {b} != bin total")
        for h in range(1, 13):
            if sum(row[h] for row in bs.values()) != res["sectors_clock"][h]:
                raise ResultInvariantError(f"bin_sector column {h} != sector total")
        if sum(row["center"] for row in bs.values()) != res["center"]:
            raise ResultInvariantError("bin_sector center column != center")
    return res


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def spatial_rows(res):
    """Long format. A table that was not computed gets one status row (count empty, reason set) so a
    disabled feature never looks like a real 0."""
    rows = [("bin_total", b, n, None, None, None) for b, n in res["bin_totals"].items()]
    if res["sectors_clock"] is not None:
        rows += [("sector_strict", h, n, None, None, None) for h, n in res["sectors_clock"].items()]
        rows += [("center", "center", res["center"], None, None, None)]
        rows += [("sector_tolerant", h, n, None, None, "not a partition (+-tol neighbours counted twice)")
                 for h, n in res["sectors_clock_tolerant"].items()]
    else:
        cs = res["clock_status"]
        why = f'{cs["status"]}: {cs["reason"]}'
        for t in ("sector_strict", "sector_tolerant"):
            rows.append((t, "*", None, None, None, why))
        rows.append(("center", "center", res["center"], None, None, None if res["center"] is not None else why))
    for z, st in res["zones_status"].items():
        if st == "enabled":
            rows.append(("zone", z, len(res["zones"][z]), None, None, "zones may overlap; use zone_union"))
        else:
            rows.append(("zone", z, None, None, None, "disabled"))
    rows.append(("zone_union", "unique", res["zone_union_unique"], None, None,
                 None if res["zone_union_unique"] is not None else "no zone enabled"))
    rd = res["radial_density"]
    if "rows" in rd:
        for row in rd["rows"]:
            key = f'{row["r_lo_mm"]:g}-{row["r_hi_mm"]:g}{"]" if row["closed"] == "both" else ")"}'
            rows.append(("radial", key, row["count"], row["area_mm2"], row["density_per_mm2"], row["reason"]))
    else:
        rows.append(("radial", "*", None, None, None, f'{rd["calc_status"]}: {rd.get("reason")}'))
    return rows


def write_csv(res, points, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cols = ["defect_id", "x_mm", "y_mm", "r_mm", "bin", "included", "excluded_reason", "clock",
            "also_clock_tolerant", "zones"]
    with open(out / "defects.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in points:
            w.writerow([_cell(p.get(c)) for c in cols])
    with open(out / "spatial_counts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table", "key", "count", "area_mm2", "density_per_mm2", "reason"])
        for r in spatial_rows(res):
            w.writerow([_cell(v) for v in r])
    with open(out / "bin_sector.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        hours = list(range(1, 13))
        w.writerow(["bin"] + [str(h) for h in hours] + ["center", "total", "status"])
        if res["bin_sector"] is None:
            w.writerow([""] * 15 + [f'{res["clock_status"]["status"]}: {res["clock_status"]["reason"]}'])
        for b, row in (res["bin_sector"] or {}).items():
            vals = [row[h] for h in hours] + [row["center"]]
            w.writerow([b] + vals + [sum(vals), "computed"])
    # provenance travels with the CSVs so a detached file can be traced (E16 / P3-03)
    with open(out / "manifest.json", "w", encoding="utf-8") as f:
        json.dump({"provenance": res["provenance"], "orientation_status": res["orientation_status"],
                   "coordinate_frame": "notch_down" if res["orientation_status"] == "notch_registered" else "unregistered",
                   "files": ["defects.csv", "spatial_counts.csv", "bin_sector.csv"],
                   "null_convention": "empty cell = null (not computed / not applicable), 0 = real zero"},
                  f, ensure_ascii=False, indent=2, default=str)
    return [str(out / n) for n in ("defects.csv", "spatial_counts.csv", "bin_sector.csv", "manifest.json")]
