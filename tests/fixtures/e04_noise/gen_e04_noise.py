"""E04 noise/cluster fixture (stdlib only, no production code, deterministic, seed=None).
Usage: python gen_e04_noise.py -> e04_noise.json beside this file.

Construction:
 * 40 sparse IDs S01..S40: 25 mm grid points (multiples of 25) with 25 <= r <= 125, first 40 sorted by (r, y, x).
   Min mutual distance = 25 mm (> 20 required, > eps).
 * 1 dense cluster C01..C30 centered at (62.5, 62.5) (off-grid, >= 17.7 mm from any sparse pt; minus the 3 mm
   cluster radius = 14.7 mm > eps): 1 center + 8 at r=1 + 10 at r=2 + 11 at r=3 -> 30 pts within 3 mm of center.
Expected under DBSCAN(eps=5, min_samples=5, closed neighborhood d<=eps, a point counts itself):
 * every sparse pt has only itself within 5 mm -> noise (40 IDs).
 * every cluster pt has many neighbors within 5 mm (cluster diameter <= 6, every pt within 3 of center) -> 30 members.
 The generator verifies this with a brute-force DBSCAN (independent of production), also for the f01 test
 profile (eps=10, min_samples=3), which yields the same partition. Bins B1/B2/B3 cycle by index.
"""
import json
import math
import os

sparse = sorted([(x, y) for x in range(-125, 126, 25) for y in range(-125, 126, 25)
                 if 25 <= math.hypot(x, y) <= 125], key=lambda p: (math.hypot(*p), p[1], p[0]))[:40]
assert len(sparse) == 40
CX, CY = 62.5, 62.5
offs = [(0.0, 0.0)]
offs += [(math.cos(math.radians(45 * i)), math.sin(math.radians(45 * i))) for i in range(8)]
offs += [(2 * math.cos(math.radians(36 * i)), 2 * math.sin(math.radians(36 * i))) for i in range(10)]
offs += [(3 * math.cos(2 * math.pi * i / 11), 3 * math.sin(2 * math.pi * i / 11)) for i in range(11)]
assert len(offs) == 30 and all(math.hypot(a, b) <= 3 + 1e-12 for a, b in offs)

pts = []
for i, (x, y) in enumerate(sparse):
    pts.append(dict(id="S%02d" % (i + 1), x=float(x), y=float(y), bin="B%d" % (i % 3 + 1), role="sparse"))
for i, (dx, dy) in enumerate(offs):
    pts.append(dict(id="C%02d" % (i + 1), x=round(CX + dx, 9), y=round(CY + dy, 9),
                    bin="B%d" % (i % 3 + 1), role="cluster"))

sp = [(p["x"], p["y"]) for p in pts if p["role"] == "sparse"]
assert min(math.dist(a, b) for i, a in enumerate(sp) for b in sp[i + 1:]) >= 25
assert min(math.dist(a, (CX, CY)) for a in sp) - 3 > 10


def dbscan(P, eps, ms):  # brute-force; label -1 = noise
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


P = [(p["x"], p["y"]) for p in pts]
res = {}
for name, eps, ms in [("eps5_min5", 5.0, 5), ("f01_profile_eps10_min3", 10.0, 3)]:
    lab = dbscan(P, eps, ms)
    noise = sorted(p["id"] for p, l in zip(pts, lab) if l == -1)
    clus = sorted(p["id"] for p, l in zip(pts, lab) if l != -1)
    assert noise == sorted(p["id"] for p in pts if p["role"] == "sparse")
    assert len(set(lab) - {-1}) == 1 and len(clus) == 30
    res[name] = dict(eps_mm=eps, min_samples=ms, n_clusters=1, noise_ids=noise, cluster_ids=clus)

bins = {}
for p in pts:
    bins[p["bin"]] = bins.get(p["bin"], 0) + 1
out = dict(_meta=dict(
    fixture="E04-noise", oracle_version="e04-noise-1", synthetic=True, seed=None, generator="gen_e04_noise.py",
    units="mm", plan_links=["E04", "C07", "C08", "P2-03"], frame="standard: center origin, +X right, +Y up",
    n_total=70, bins=bins,
    conservation="N_included=70 = 40 noise + 30 clustered; noise stays in totals, bins, sectors (plan 16.3-5)",
    note="Primary assumption eps=5, min_samples=5 (user decision); f01 test profile (eps 10, min 3) gives the same partition."),
    points=pts, expected=res)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e04_noise.json"), "w") as f:
    json.dump(out, f, indent=1)
print(bins, {k: (len(v["noise_ids"]), len(v["cluster_ids"])) for k, v in res.items()})
