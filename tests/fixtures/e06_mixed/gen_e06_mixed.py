"""E06 mixed ring/line/local overlap fixture (stdlib only, no production code, deterministic, seed=None).
Usage: python gen_e06_mixed.py -> e06_mixed.json beside this file.  Frame: standard (center origin, mm, +X right, +Y up), R=150.
Clock angle th: x=r*sin(th), y=r*cos(th).

Construction (supports are recorded from construction, then cross-checked geometrically):
 * ring base R00..R23: r=80, th=15*k deg (24 pts).
 * line: y=-40. 13 own pts LN01..LN13 at x=-60..60 step 10, plus ring pts R08 (th=120) and R16 (th=240) which sit
   exactly at y=-40 (x=+/-69.282). Line support = 15; ring-line overlap = {R08, R16}.
   (Deviation from request: x=-35..35 cannot meet the r=80 ring, which crosses y=-40 at |x|=69.28.)
 * local blob: 12 pts within 3 mm of C=R03 position (th=45, r=80) (request said (100,60), r=116.6, which cannot touch an
   r=80 ring). Blob = R03 (center) + BR01/BR02 (on r=80 at th=44/46, chord 1.40 mm from R03) + 9 off-ring pts BL01..BL09 whose
   radial offset from the ring is >=1.5 mm. Ring support therefore = 24 + BR01 + BR02 = 26; ring-local overlap = {R03, BR01, BR02}.
 * ring support rule used for cross-check: |r-80| <= 1.0 mm.
 * bins: pattern over list index i (order below): i%4 in (0,1)->B1, 2->B2, 3->B3.
 * broken case: remove ring base pts strictly inside 60<th<120 (R05,R06,R07) and 200<th<230 (R14,R15). R08 (th=120) is kept
   so the line overlap is preserved. Remaining ring-base fragments (circular): A = th 120..195 (6 pts), B = th 240..60 (13 pts).
"""
import json
import math
import os

R = 80.0
pts = []


def add(i, x, y, role):
    pts.append(dict(id=i, x=round(x, 9), y=round(y, 9), role=role))


for k in range(24):
    th = math.radians(15 * k)
    add("R%02d" % k, R * math.sin(th), R * math.cos(th), "ring")
for n, deg in ((1, 44), (2, 46)):
    th = math.radians(deg)
    add("BR%02d" % n, R * math.sin(th), R * math.cos(th), "ring_local")
for n, x in enumerate(range(-60, 61, 10), 1):
    add("LN%02d" % n, float(x), -40.0, "line")
c45 = math.radians(45)
CX, CY = R * math.sin(c45), R * math.cos(c45)
ux, uy = math.sin(c45), math.cos(c45)
vx, vy = math.cos(c45), -math.sin(c45)
offs = [(-1.5, 0), (1.5, 0), (-2, 1), (2, -1), (-2.5, .5), (2.5, -.5), (-1.5, -1.5), (1.5, 1.5), (-2, -1)]
for n, (d, t) in enumerate(offs, 1):
    add("BL%02d" % n, CX + d * ux + t * vx, CY + d * uy + t * vy, "local")
assert len(pts) == 48 and len({p["id"] for p in pts}) == 48
for i, p in enumerate(pts):
    p["bin"] = ("B1", "B1", "B2", "B3")[i % 4]

ring_base = ["R%02d" % k for k in range(24)]
sup_full = dict(
    ring=ring_base + ["BR01", "BR02"],
    line=["LN%02d" % n for n in range(1, 14)] + ["R08", "R16"],
    local=["R03", "BR01", "BR02"] + ["BL%02d" % n for n in range(1, 10)])
assert [len(sup_full[g]) for g in ("ring", "line", "local")] == [26, 15, 12]

byid = {p["id"]: p for p in pts}


def geometric_check(ids, sup):
    P = [byid[i] for i in ids]
    assert {p["id"] for p in P if abs(math.hypot(p["x"], p["y"]) - R) <= 1.0} == set(sup["ring"])
    assert {p["id"] for p in P if p["y"] == -40.0 and abs(p["x"]) <= 70} == set(sup["line"])
    assert {p["id"] for p in P if math.hypot(p["x"] - CX, p["y"] - CY) <= 3.0} == set(sup["local"])


def dbscan(P, eps, ms):  # brute force, label -1 = noise, closed neighborhood, self counted
    n = len(P)
    lab = [None] * n
    c = 0

    def nb(i):
        return [j for j in range(n) if math.dist(P[i], P[j]) <= eps]

    for i in range(n):
        if lab[i] is not None:
            continue
        N = nb(i)
        if len(N) < ms:
            lab[i] = -1
            continue
        lab[i] = c
        q = [j for j in N if j != i]
        while q:
            j = q.pop()
            if lab[j] == -1:
                lab[j] = c
            if lab[j] is not None:
                continue
            lab[j] = c
            Nj = nb(j)
            if len(Nj) >= ms:
                q.extend(Nj)
        c += 1
    return lab


def dbscan_summary(ids, eps, ms):
    lab = dbscan([(byid[i]["x"], byid[i]["y"]) for i in ids], eps, ms)
    cl = {}
    for i, l in zip(ids, lab):
        cl.setdefault(l, []).append(i)
    return dict(eps_mm=eps, min_samples=ms, noise_ids=sorted(cl.pop(-1, [])),
                clusters=sorted((sorted(v) for v in cl.values()), key=lambda v: v[0]))


def case(removed):
    ids = [p["id"] for p in pts if p["id"] not in removed]
    sup = {g: [i for i in v if i not in removed] for g, v in sup_full.items()}
    geometric_check(ids, sup)
    S = {g: set(v) for g, v in sup.items()}
    naive = sum(len(v) for v in S.values())
    union = set().union(*S.values())
    assert union == set(ids)  # every wafer defect belongs to >=1 group
    pair = {"%s&%s" % (a, b): sorted(S[a] & S[b]) for a, b in (("ring", "line"), ("ring", "local"), ("line", "local"))}
    overlap = sorted(set().union(*[set(v) for v in pair.values()]))
    assert not (S["ring"] & S["line"] & S["local"])
    assert naive - len(union) == len(overlap)  # each overlap ID is in exactly 2 groups

    def cnt(s):
        return {b: sum(1 for i in s if byid[i]["bin"] == b) for b in ("B1", "B2", "B3")}

    exp = dict(
        support_ids={g: sorted(v) for g, v in sup.items()},
        support_count={g: len(v) for g, v in S.items()},
        naive_sum=naive, unique_union_size=len(union), naive_minus_union=naive - len(union),
        overlap_pairs=pair, overlap_ids=overlap,
        wafer_unique_defect_count=len(ids),
        bin_unique_totals=cnt(ids), bin_support_counts={g: cnt(v) for g, v in S.items()},
        bin_naive_sum={b: sum(cnt(v)[b] for v in S.values()) for b in ("B1", "B2", "B3")})
    assert sum(exp["bin_unique_totals"].values()) == len(ids)
    return ids, exp


intact_ids, intact_exp = case(set())
rm = {"R05", "R06", "R07", "R14", "R15"}
broken_ids, broken_exp = case(rm)
ring_only = [i for i in broken_ids if i in ring_base]
frag = dbscan_summary(ring_only, 25.0, 2)
fr = sorted(frag["clusters"], key=len)
assert [len(c) for c in fr] == [6, 13] and not frag["noise_ids"]
broken_exp["ring_fragments_expected"] = dict(
    removed_ids=sorted(rm), fragment_A_th120_195=fr[0], fragment_B_th240_60=fr[1],
    ring_base_remaining=len(ring_only), n_fragments=2,
    note="ring_base ids only, brute-force DBSCAN eps=25 min_samples=2 (gaps 61 mm and 80 mm >> eps, spacing 20.9 mm < eps)")
broken_exp["dbscan_whole_wafer_informational"] = {
    "eps25_min3": dbscan_summary(broken_ids, 25.0, 3), "eps10_min3": dbscan_summary(broken_ids, 10.0, 3)}
intact_exp["dbscan_whole_wafer_informational"] = {
    "eps25_min3": dbscan_summary(intact_ids, 25.0, 3), "eps10_min3": dbscan_summary(intact_ids, 10.0, 3)}


def render(ids):
    out = []
    for i in ids:
        p = dict(byid[i])
        p["groups"] = [g for g, v in sup_full.items() if i in v]
        out.append(p)
    return out


out = dict(_meta=dict(
    fixture="E06-mixed", oracle_version="e06-mixed-1", synthetic=True, seed=None, generator="gen_e06_mixed.py",
    units="mm", R_wafer=150, frame="standard: center origin, +X right, +Y up", plan_links=["E06", "C08", "C10", "C11", "P3-01"],
    construction=(
        "ring: 24 pts r=80 th=15k. line: y=-40, 13 own pts x=-60..60 step 10 + shared R08,R16 (x=+/-69.282). "
        "local: 12 pts within 3 mm of R03 (th=45): R03, BR01, BR02 shared with ring support + 9 off-ring pts. "
        "ring support=26, line=15, local=12; naive=53; 5 overlap IDs (R08,R16,R03,BR01,BR02) each in 2 groups -> union=48. "
        "bins by list index i%4: B1,B1,B2,B3. Broken case removes R05,R06,R07,R14,R15 -> ring 21, line 15, local 12, naive 48, union 43."),
    deviations_from_request=[
        "line x range -35..35 replaced by -60..60 + 2 ring pts: ring crosses y=-40 only at |x|=69.28",
        "blob center moved from (100,60) to R03 at (56.57,56.57): (100,60) has r=116.6, cannot touch r=80 ring",
        "ring support has 26 members (24 ring pts + BR01, BR02 on the ring radius) since 15-deg ring spacing (20.9 mm) cannot put 3 ring pts within a 3 mm blob"],
    support_rule="ring |r-80|<=1.0; line y==-40 & |x|<=70; local dist to R03<=3.0 (cross-checked in generator)",
    dbscan_note="Whole-wafer DBSCAN with eps>=21 bridges ring fragments through line/blob; use the ring-only fragment expectation for broken-ring test. eps=10: ring pts are noise (spacing 20.9)."),
    cases=dict(
        intact=dict(points=render(intact_ids), expected=intact_exp),
        broken_ring=dict(points=render(broken_ids), expected=broken_exp)))
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e06_mixed.json"), "w") as f:
    json.dump(out, f, indent=1)
for k, c in out["cases"].items():
    e = c["expected"]
    print(k, e["support_count"], e["naive_sum"], e["unique_union_size"], e["overlap_ids"], e["bin_unique_totals"], e["bin_naive_sum"])
