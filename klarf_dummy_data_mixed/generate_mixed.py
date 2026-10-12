"""Generate a messy MixedWM38-style SYNTHETIC KLARF 1.8 set (38 classes) with independent expected values.

SYNTHETIC ONLY - not a tool export, not MixedWM38 data. MixedWM38 is an EDS die-level fail-map set; here only
its class list (Normal + 8 single + 13/12/4 mixed) is borrowed to place inline-inspection-like defect DOTS with
heavy background noise. Pattern labels are the generator's intent, not a classifier answer or a process cause.

stdlib only (expected values never call wafer/*). Same file contract as klarf_dummy_data
(adapter synthetic-die-local-v1, notch DOWN, pitch 10000 um, SampleCenterLocation 150000 um).

    python klarf_dummy_data_mixed/generate_mixed.py            # rewrite klarf/, expected/, manifest.json
    python klarf_dummy_data_mixed/generate_mixed.py --png      # also maps/overview.png (needs matplotlib)
    python klarf_dummy_data_mixed/generate_mixed.py --out DIR  # write elsewhere (determinism check)
"""
import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path

SEED = 20261012
R = 150.0                 # wafer radius mm
PITCH = 10000.0           # die pitch um
CENTER_UM = 150000.0      # SampleCenterLocation um
CENTER_EXCL = 1.0         # center region r < 1 mm (test profile value)

NAMES = {"C": "Center", "D": "Donut", "EL": "Edge-Loc", "ER": "Edge-Ring", "L": "Loc", "NF": "Near-full",
         "S": "Scratch", "R": "Random"}
SINGLES = ["C", "D", "EL", "ER", "L", "NF", "S", "R"]
MIXED2 = [("C", "EL"), ("C", "ER"), ("C", "L"), ("C", "S"), ("D", "EL"), ("D", "ER"), ("D", "L"), ("D", "S"),
          ("EL", "L"), ("EL", "S"), ("ER", "L"), ("ER", "S"), ("L", "S")]
MIXED3 = [("C", "EL", "L"), ("C", "EL", "S"), ("C", "ER", "L"), ("C", "ER", "S"), ("C", "L", "S"),
          ("D", "EL", "L"), ("D", "EL", "S"), ("D", "ER", "L"), ("D", "ER", "S"), ("D", "L", "S"),
          ("EL", "L", "S"), ("ER", "L", "S")]
MIXED4 = [("C", "L", "EL", "S"), ("C", "L", "ER", "S"), ("D", "L", "EL", "S"), ("D", "L", "ER", "S")]
# dominant classification bin per pattern (synthetic test codes 1/2/3, not in-house bins); None = mixed bins
DOMINANT_BIN = {"C": 1, "D": 2, "EL": 3, "ER": 3, "L": 1, "S": 2, "NF": None, "R": None, "background": None,
                "nuisance_clump": None}


def cases():
    out = [("N00_normal", [])]
    out += [(f"S{i:02d}_{c}", [c]) for i, c in enumerate(SINGLES, 1)]
    out += [(f"M2_{i:02d}_{'+'.join(c)}", list(c)) for i, c in enumerate(MIXED2, 1)]
    out += [(f"M3_{i:02d}_{'+'.join(c)}", list(c)) for i, c in enumerate(MIXED3, 1)]
    out += [(f"M4_{i:02d}_{'+'.join(c)}", list(c)) for i, c in enumerate(MIXED4, 1)]
    return out


# ---------------------------------------------------------------- pattern samplers (standard frame, mm)
def polar(r, deg):
    t = math.radians(deg)
    return r * math.sin(t), r * math.cos(t)          # clock angle: 0 deg = 12 o'clock, clockwise


def disk(rng, n, rmax, rmin=0.0):
    return [polar(math.sqrt(rng.uniform(rmin * rmin, rmax * rmax)), rng.uniform(0, 360)) for _ in range(n)]


def p_center(rng):
    n, rc = rng.randint(250, 420), rng.uniform(22, 34)
    ox, oy = rng.uniform(-6, 6), rng.uniform(-6, 6)
    pts = []
    for _ in range(n):   # ragged edge: radius scaled by a noisy factor
        x, y = polar(rc * math.sqrt(rng.random()) * (1 + rng.gauss(0, 0.08)), rng.uniform(0, 360))
        pts.append((x + ox, y + oy))
    return pts


def p_donut(rng):
    n, ri, w = rng.randint(300, 480), rng.uniform(30, 45), rng.uniform(10, 16)
    ox, oy, weak = rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(0, 360)
    pts = []
    while len(pts) < n:
        a = rng.uniform(0, 360)
        if rng.random() > 0.55 + 0.45 * math.cos(math.radians(a - weak)) ** 2:   # uneven, partly thin ring
            continue
        x, y = polar(ri + w * rng.random() + rng.gauss(0, 2.0), a)
        pts.append((x + ox, y + oy))
    return pts


def p_edge_loc(rng):
    n, a0, span, depth = rng.randint(180, 320), rng.uniform(0, 360), rng.uniform(25, 60), rng.uniform(15, 28)
    return [polar(R - abs(rng.gauss(0, depth / 2)), a0 + rng.gauss(0, span / 3)) for _ in range(n)]


def p_edge_ring(rng):
    n = rng.randint(380, 600)
    gaps = [(rng.uniform(0, 360), rng.uniform(8, 25)) for _ in range(rng.randint(1, 3))]
    pts = []
    while len(pts) < n:
        a = rng.uniform(0, 360)
        if any(abs((a - g + 180) % 360 - 180) < w / 2 for g, w in gaps):
            continue
        pts.append(polar(R - abs(rng.gauss(0, 3.5)), a))
    return pts


def p_loc(rng):
    n, r0, a0 = rng.randint(150, 260), rng.uniform(40, 105), rng.uniform(0, 360)
    s1, s2, rot = rng.uniform(5, 10), rng.uniform(3, 7), math.radians(rng.uniform(0, 180))
    cx, cy = polar(r0, a0)
    pts = []
    for _ in range(n):   # anisotropic gaussian blob
        u, v = rng.gauss(0, s1), rng.gauss(0, s2)
        pts.append((cx + u * math.cos(rot) - v * math.sin(rot), cy + u * math.sin(rot) + v * math.cos(rot)))
    return pts


def p_near_full(rng):
    n = rng.randint(1400, 1900)
    holes = [(polar(rng.uniform(20, 120), rng.uniform(0, 360)), rng.uniform(8, 18)) for _ in range(rng.randint(2, 4))]
    pts = []
    while len(pts) < n:
        x, y = polar(R * 0.97 * math.sqrt(rng.random()) ** 0.9, rng.uniform(0, 360))   # slightly edge-heavy
        if any(math.hypot(x - hx, y - hy) < hr for (hx, hy), hr in holes):
            continue
        pts.append((x, y))
    return pts


def p_scratch(rng):
    n = rng.randint(150, 300)
    while True:   # quadratic Bezier with breaks; keep the curve inside the wafer
        p0 = polar(rng.uniform(0, 110), rng.uniform(0, 360))
        ang, length = math.radians(rng.uniform(0, 360)), rng.uniform(90, 190)
        p2 = (p0[0] + length * math.cos(ang), p0[1] + length * math.sin(ang))
        mid = ((p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2)
        bend = rng.uniform(-25, 25)
        p1 = (mid[0] - bend * math.sin(ang), mid[1] + bend * math.cos(ang))
        if math.hypot(*p2) < R - 3 and math.hypot(*p1) < R:
            break
    cuts = sorted(rng.uniform(0.1, 0.9) for _ in range(rng.randint(1, 3)))
    breaks = [(c, c + rng.uniform(0.03, 0.10)) for c in cuts]
    pts = []
    while len(pts) < n:
        t = rng.random()
        if any(a <= t < b for a, b in breaks):
            continue
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        if rng.random() < 0.08:              # stray points scattered around the scratch
            pts.append((x + rng.gauss(0, 4.0), y + rng.gauss(0, 4.0)))
        else:
            pts.append((x + rng.gauss(0, 1.1), y + rng.gauss(0, 1.1)))
    return pts


def nuisance_clumps(rng):
    """Messy background: a few tiny random clumps (not a pattern intent; may look like local candidates)."""
    pts = []
    for _ in range(rng.randint(3, 8)):
        cx, cy = polar(rng.uniform(0, 140), rng.uniform(0, 360))
        s = rng.uniform(1.0, 3.0)
        pts += [(cx + rng.gauss(0, s), cy + rng.gauss(0, s)) for _ in range(rng.randint(5, 15))]
    return pts


def p_random(rng):
    return disk(rng, rng.randint(700, 1000), R)


SAMPLERS = {"C": p_center, "D": p_donut, "EL": p_edge_loc, "ER": p_edge_ring, "L": p_loc, "NF": p_near_full,
            "S": p_scratch, "R": p_random}


# ---------------------------------------------------------------- quantization and independent oracle
def to_klarf_coords(x, y):
    """mm (standard, notch DOWN) -> (XINDEX, XREL, YINDEX, YREL) with 0.1 um resolution, rel in [0, pitch)."""
    out = []
    for v in (x, y):
        u = v * 1000.0 + CENTER_UM
        idx = int(math.floor(u / PITCH))
        rel = round(u - idx * PITCH, 1)
        if rel >= PITCH:
            idx, rel = idx + 1, round(rel - PITCH, 1)
        out += [idx, rel]
    return out


def from_klarf(idx, rel):
    return (idx * PITCH + rel - CENTER_UM) / 1000.0     # same operation order as the synthetic adapter


def clock_hour(x, y):
    t = math.degrees(math.atan2(x, y)) % 360.0
    if t >= 360.0:
        t = 0.0
    h = int(((t + 15.0) % 360.0) // 30.0)
    return 12 if h == 0 else h, t


def unsafe(x, y):
    """Points whose expected label would depend on float rounding at a contract boundary are redrawn."""
    r = math.hypot(x, y)
    _, t = clock_hour(x, y)
    off = (t + 15.0) % 30.0
    return abs(r - R) < 0.01 or abs(r - CENTER_EXCL) < 1e-3 or min(off, 30.0 - off) < 1e-6


def build(name, comps, rng):
    groups = [("background", disk(rng, rng.randint(450, 800), R)), ("nuisance_clump", nuisance_clumps(rng))]
    groups += [(c, SAMPLERS[c](rng)) for c in comps]
    recs = []
    for g, pts in groups:
        for x, y in pts:
            if math.hypot(x, y) > R - 0.02:      # pattern tails beyond the edge are dropped, not clipped
                continue
            recs.append([g, x, y])
    k_out = rng.randint(0, 4)                   # messy: a few events just outside the wafer (excluded)
    while k_out:
        x, y = polar(rng.uniform(150.2, 153.0), rng.uniform(0, 360))
        if x > -149.0 and y > -149.0:            # keep die index >= 0
            recs.append(["outside", x, y])
            k_out -= 1
    rows = []
    for g, x, y in recs:
        xi, xr, yi, yr = to_klarf_coords(x, y)
        xq, yq = from_klarf(xi, xr), from_klarf(yi, yr)
        if unsafe(xq, yq):
            continue
        rows.append({"group": g, "XINDEX": xi, "XREL": xr, "YINDEX": yi, "YREL": yr, "x": xq, "y": yq})
    for _ in range(rng.randint(1, 3)):          # messy: distinct events at an identical position
        src = dict(rng.choice([r for r in rows if r["group"] != "outside"]))
        src["group"] = f"duplicate_position({src['group']})"
        rows.append(src)
    rng.shuffle(rows)                            # groups interleaved in the file
    for i, r in enumerate(rows, 1):
        r["DEFECTID"] = i
        base = r["group"].split("(")[-1].rstrip(")")
        dom = DOMINANT_BIN.get(base)
        if rng.random() < 0.02:
            b = 0                                # unknown classification
        elif dom is not None and rng.random() < 0.85:
            b = dom
        else:
            b = rng.choice([1, 2, 3])
        r["CLASSNUMBER"] = b
        r["size"] = round(rng.uniform(0.3, 4.0), 2)
    return rows


def klarf_text(name, rows):
    head = [
        'Record FileRecord "1.8"', "{", ' Record LotRecord "DUMMY_MIXED_LOT"', " {",
        f'  Record WaferRecord "{name}"', "  {",
        '   Field SampleType 1 {"WAFER"}', "   Field SampleSize 2 {1, 300}", "   Field DiePitch 2 {10000, 10000}",
        "   Field DieOrigin 2 {0, 0}", "   Field SampleCenterLocation 2 {150000, 150000}",
        '   Field SampleOrientationMarkType 1 {"NOTCH"}', '   Field OrientationMarkLocation 1 {"DOWN"}',
        '   Field DeviceID 1 {"SYNTHETIC_ONLY"}', '   Field StepID 1 {"DUMMY_MIXED_INSPECTION"}',
        "   Field SlotNumber 1 {1}", "   List DefectList", "   {",
        "    Columns 14 {int32 DEFECTID, float XREL, float YREL, int32 XINDEX, int32 YINDEX, float XSIZE, float YSIZE, "
        "float DEFECTAREA, float DSIZE, int32 CLASSNUMBER, int32 TEST, int32 CLUSTERNUMBER, int32 ROUGHBINNUMBER, "
        "int32 FINEBINNUMBER}",
        f"    Data {len(rows)}", "    {"]
    body = [f'     {r["DEFECTID"]} {r["XREL"]:.1f} {r["YREL"]:.1f} {r["XINDEX"]} {r["YINDEX"]} {r["size"]} {r["size"]} '
            f'{round(r["size"] * r["size"], 4)} {r["size"]} {r["CLASSNUMBER"]} 1 0 {r["CLASSNUMBER"]} {r["CLASSNUMBER"]} ;'
            for r in sorted(rows, key=lambda r: r["DEFECTID"])]
    tail = ["    }", "   }", "  }", " }", "}", "EndOfFile;", ""]
    return "\n".join(head + body + tail)


def expected(name, comps, rows, sha):
    inc = [r for r in rows if math.hypot(r["x"], r["y"]) <= R]
    bins, clock, center, groups = {}, {str(h): 0 for h in range(1, 13)}, 0, {}
    for r in inc:
        b = "unknown" if r["CLASSNUMBER"] == 0 else str(r["CLASSNUMBER"])
        bins[b] = bins.get(b, 0) + 1
        if math.hypot(r["x"], r["y"]) < CENTER_EXCL:
            center += 1
        else:
            clock[str(clock_hour(r["x"], r["y"])[0])] += 1
    for r in rows:
        groups.setdefault(r["group"], []).append(r["DEFECTID"])
    return {"name": name, "class_label": "+".join(comps) or "Normal",
            "components": [{"code": c, "name": NAMES[c]} for c in comps],
            "mixed_order": len(comps), "lot_id": "DUMMY_MIXED_LOT", "wafer_id": name, "notch": "DOWN",
            "count": len(rows), "n_included": len(inc), "n_excluded": len(rows) - len(inc),
            "excluded_ids": sorted(r["DEFECTID"] for r in rows if math.hypot(r["x"], r["y"]) > R),
            "bin_counts": dict(sorted(bins.items())), "center_count": center, "clock_counts": clock,
            "generation_groups": {g: sorted(v) for g, v in sorted(groups.items())},
            "generation_intent_only": True, "classifier_output_validated": False, "file_sha256": sha}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    (out / "klarf").mkdir(parents=True, exist_ok=True)
    (out / "expected").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    manifest, maps = [], []
    for name, comps in cases():
        rows = build(name, comps, rng)
        data = klarf_text(name, rows).encode("utf-8")
        (out / "klarf" / f"{name}.klarf").write_bytes(data)
        exp = expected(name, comps, rows, hashlib.sha256(data).hexdigest())
        (out / "expected" / f"{name}.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
        with open(out / "expected" / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["defect_id", "x_mm", "y_mm", "r_mm", "classification_bin", "generation_group", "included",
                        "clock_hour"])
            for r in sorted(rows, key=lambda r: r["DEFECTID"]):
                rr = math.hypot(r["x"], r["y"])
                hour = "" if rr > R else ("center" if rr < CENTER_EXCL else clock_hour(r["x"], r["y"])[0])
                w.writerow([r["DEFECTID"], f'{r["x"]:.6f}', f'{r["y"]:.6f}', f"{rr:.6f}",
                            "unknown" if r["CLASSNUMBER"] == 0 else r["CLASSNUMBER"], r["group"], rr <= R, hour])
        manifest.append({k: exp[k] for k in ("name", "class_label", "mixed_order", "count", "n_included",
                                             "n_excluded", "file_sha256")})
        maps.append((name, exp["class_label"], rows))
    (out / "manifest.json").write_text(json.dumps(
        {"seed": SEED, "synthetic_only": True, "style": "MixedWM38-like class list (38), inline defect dots",
         "adapter": "synthetic-die-local-v1", "profile": "tests/profiles/dummy_die_local_test_profile.yaml",
         "coverage_sidecar": "klarf_dummy_data/synthetic_profile.json (full_disk 150, synthetic declaration)",
         "generator": "klarf_dummy_data_mixed/generate_mixed.py (stdlib only)", "cases": manifest},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.png:
        overview(out / "maps" / "overview.png", maps)


def overview(path, maps):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = 8
    rows = -(-len(maps) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.2, rows * 2.4))
    for ax in axes.flat:
        ax.axis("off")
    for ax, (name, label, recs) in zip(axes.flat, maps):
        t = [i * math.pi / 90 for i in range(181)]
        ax.plot([R * math.sin(v) for v in t], [R * math.cos(v) for v in t], color="#888", lw=0.6)
        ax.plot([0], [-R], marker="^", color="k", ms=4)
        ax.scatter([r["x"] for r in recs], [r["y"] for r in recs], s=0.6, c="#d62728")
        ax.set_aspect("equal")
        ax.set_xlim(-160, 160)
        ax.set_ylim(-160, 160)
        ax.set_title(f"{name.split('_')[0]} {label}", fontsize=7)
    fig.suptitle("klarf_dummy_data_mixed (SYNTHETIC, notch 6 o'clock, standard frame)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=90)


if __name__ == "__main__":
    main()
