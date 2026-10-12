"""Batch analysis: many uploaded files -> preflight list -> sequential run through the single-file core
(wafer.cli.run_job) -> per-unit rows, per-type summary, raw extent metrics, exports.

Small orchestration only (no queue, no new DB): one SQLite file may store runs (existing tables) plus a
batch/member link table. Uploaded names are kept as display/tracking paths only; files are written to
temp paths named by position, never by the uploaded name. File names are not parsed (TBD T-26); the
lot/wafer shown comes from the KLARF header and is marked unverified.

Counting units: an uploaded file is an entry; an analysis unit is one analysed wafer record. The current
parsers accept exactly one wafer record per file (more is INVALID_INPUT, T-09), so a successful entry
yields one unit. Identical content (same sha256) inside a batch is analysed once and the other entries
point to it (`duplicate_of`); nothing is merged silently.
"""
import csv
import hashlib
import io
import json
import math
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import ingest, store
from .cli import CODE_VERSION, RULE_VERSION, load_coverage, run_job
from .profile import ConfigInvalid, load_profile, validate_for_run
from .report import NULL_CONVENTION, write_csv

# current input contract: the single-file uploader accepts these; anything else is excluded with a reason.
# The extension only selects candidates - the content must still parse (T-26: real exports, e.g. ".001", TBD).
SUPPORTED_EXTENSIONS = (".klf", ".klarf", ".txt")
DEFAULT_LIMITS = {"max_files": 500, "max_file_bytes": 50 * 1024 * 1024, "max_total_bytes": 300 * 1024 * 1024}
TYPES = ("ring", "line", "local", "lift_pin")
# batch-level candidates (2026-10-12): repeat on the same inspection tool, defect volume. Appended to
# candidate_types after the per-wafer TYPES; the per-wafer codes are unchanged.
EQUIP_TYPES = ("equip_ring", "equip_line", "equip_local", "inspection_abort_suspect", "excess_defect")
TYPE_LABELS = {"ring": "환형", "line": "일자형", "local": "몰림형", "lift_pin": "삼발이",
               "equip_ring": "설비 반복 환형", "equip_line": "설비 반복 일자형", "equip_local": "설비 반복 몰림형",
               "inspection_abort_suspect": "과다 defect·검사 중단 의심", "excess_defect": "과다 defect(중단 미확인)"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(v):
    return None if v is None else str(v).strip().strip('"').strip() or None


def _station(v):
    """InspectionStationID as one comparable text: quotes dropped, whitespace collapsed (flat keeps the quotes,
    1.8 joins the values)."""
    return " ".join(str(v).replace('"', " ").split()) or None if v else None


def _meta(header):
    """lot / wafer as written inside the file (flat: LotID / WaferID fields; 1.8: record names). job: no field.
    equipment = inspection tool (InspectionStationID), step = StepID; display and batch grouping only (T-26)."""
    return {"lot": _clean(header.get("LotID") or header.get("LotRecord")),
            "wafer": _clean(header.get("WaferID") or header.get("WaferRecord")),
            "job": None, "equipment": _station(header.get("InspectionStationID")),
            "step": _clean(header.get("StepID")), "source": "klarf_header (unverified, T-26)"}


def _sha_file(path):
    if not path:
        return None, None
    with open(path, "rb") as f:
        raw = f.read()
    return raw, hashlib.sha256(raw).hexdigest()


def scan(items, profile_path, limits=None, coverage_path=None):
    """items: list of (relative_path, bytes). Returns the preflight list; nothing is analysed here.
    Each entry: index, rel_path, size, sha256, status (ready / excluded / invalid_input / held /
    duplicate_in_batch), reason, parser, adapter, profile_id, meta, duplicate_of.
    The profile and coverage sidecar are hashed here; run_batch refuses a list checked against other ones."""
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    prof = load_profile(profile_path)      # ConfigInvalid propagates: the batch cannot start
    validate_for_run(prof)
    entries, seen, total, targeted = [], {}, 0, 0
    with tempfile.TemporaryDirectory() as d:
        for i, (rel, data) in enumerate(items):
            rel = str(PurePosixPath(*Path(str(rel).replace("\\", "/")).parts)) if rel else f"file_{i}"
            e = {"index": i, "rel_path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                 "status": "ready", "reason": None, "parser": None, "adapter": prof.coordinates.adapter_id,
                 "profile_id": prof.profile_id, "meta": {"lot": None, "wafer": None, "job": None, "equipment": None, "step": None,
                          "source": None},
                 "duplicate_of": None}
            entries.append(e)
            if Path(rel).suffix.lower() not in SUPPORTED_EXTENSIONS:
                e.update(status="excluded", reason="extension_not_in_input_contract")
                continue
            if targeted >= lim["max_files"]:
                e.update(status="excluded", reason=f"over_max_files ({lim['max_files']})")
                continue
            if len(data) > lim["max_file_bytes"]:
                e.update(status="excluded", reason=f"over_max_file_bytes ({lim['max_file_bytes']})")
                continue
            if total + len(data) > lim["max_total_bytes"]:
                e.update(status="excluded", reason=f"over_max_total_bytes ({lim['max_total_bytes']})")
                continue
            total += len(data)
            targeted += 1           # targeted = not excluded (same definition as overview.files_targeted)
            if e["sha256"] in seen:
                first = entries[seen[e["sha256"]]]
                e.update(status="duplicate_in_batch", reason=f"same content as entry {first['index']}",
                         duplicate_of=first["index"], parser=first["parser"], meta=dict(first["meta"]))
                continue
            seen[e["sha256"]] = i
            tmp = Path(d) / f"{i:06d}.in"           # position-based name; the upload name is never a path
            tmp.write_bytes(data)
            try:
                k = ingest.read_klarf(tmp)
            except ingest.KlarfError as ex:
                e.update(status="invalid_input", reason=str(ex))
                continue
            e["parser"] = ("wafer.ingest-strict-2 (KLARF 1.8 record)" if "WaferRecord" in k.header or "LotRecord" in k.header
                           else "wafer.ingest-strict-2 (flat list)")
            e["meta"] = _meta(k.header)
            try:
                ingest.standardize(k, prof.coordinates)   # dry run of the profile's adapter, no analysis
            except ingest.AdapterUnsupported as ex:
                e.update(status="held", reason=f"adapter {prof.coordinates.adapter_id}: {ex}")
    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    _, prof_sha = _sha_file(profile_path)
    _, cov_sha = _sha_file(coverage_path)
    return {"entries": entries, "limits": lim, "status_counts": counts, "accepted_bytes": total,
            "profile_sha256": prof_sha, "coverage_sha256": cov_sha}


def run_batch(items, scanned, profile_path, coverage_path=None, db=None, progress=None):
    """Analyse the 'ready' entries of a preflight list, sequentially, through run_job. Inputs, profile,
    coverage and versions are frozen: the profile/sidecar bytes are read once, checked against the
    preflight hashes and every unit runs on those frozen copies. One failing file never stops the others."""
    by_index = {i: data for i, (_, data) in enumerate(items)}
    prof_raw, prof_sha = _sha_file(profile_path)
    if prof_sha != scanned.get("profile_sha256"):     # the list was checked against another profile
        raise ConfigInvalid(["profile"], "profile changed since the preflight list; scan again")
    cov_raw, cov_sha = _sha_file(coverage_path)
    if cov_sha != scanned.get("coverage_sha256"):
        raise ConfigInvalid(["coverage"], "coverage sidecar changed since the preflight list; scan again")
    for e in scanned["entries"]:                      # the bytes to run are the bytes that were listed
        if e["status"] == "ready" and hashlib.sha256(by_index[e["index"]]).hexdigest() != e["sha256"]:
            raise ConfigInvalid(["inputs"], f"entry {e['index']} changed since the preflight list; scan again")
    units = {}
    with tempfile.TemporaryDirectory() as d:
        frozen_prof = Path(d) / "profile.yaml"
        frozen_prof.write_bytes(prof_raw)
        frozen_cov = None
        if cov_raw is not None:
            frozen_cov = Path(d) / "coverage.json"
            frozen_cov.write_bytes(cov_raw)
        prof = load_profile(frozen_prof)
        load_coverage(frozen_cov, prof)     # a bad sidecar is a batch-level CONFIG_INVALID before any run
        config = {"batch_id": uuid.uuid4().hex, "created_at": _now(), "profile_id": prof.profile_id,
                  "profile_sha256": prof_sha, "coverage_sidecar_sha256": cov_sha, "code_version": CODE_VERSION,
                  "rule_version": RULE_VERSION, "limits": scanned["limits"],
                  "wafer_radius_mm": prof.wafer_radius_mm, "adapter": prof.coordinates.adapter_id,
                  # frozen with the batch: cross-wafer settings are evaluated from this copy, not the live profile
                  "equipment_signature": prof.equipment_signature.model_dump(),
                  "defect_volume": prof.defect_volume.model_dump()}
        entries = [dict(e) for e in scanned["entries"]]
        for e in entries:   # duplicates point at the analysed entry; nothing is run twice
            if e["status"] == "duplicate_in_batch":
                e["analysis_key"], e["exit_code"] = None, None
        todo = [e for e in entries if e["status"] == "ready"]
        con = store.connect(db) if db else None
        try:
            if con:   # recorded before the first run, so an interrupted batch still shows what was submitted
                store.save_batch(con, config, entries)
            for n, e in enumerate(todo, start=1):
                if progress:
                    progress(n, len(todo), e["rel_path"])
                tmp = Path(d) / f"{e['index']:06d}.in"      # position-based temp name
                tmp.write_bytes(by_index[e["index"]])
                out, code = run_job(str(tmp), str(frozen_prof), db=db, source_name=Path(e["rel_path"]).name,
                                    coverage_path=str(frozen_cov) if frozen_cov else None)
                tmp.unlink()
                e["exit_code"] = code
                if code == 0:
                    e["status"] = "succeeded"
                    e["analysis_key"] = out.get("store", {}).get("analysis_key")
                    e["reused"] = out.get("store", {}).get("created") is False
                    units[e["index"]] = out
                else:
                    e["status"] = "held" if out.get("error") == "UNSUPPORTED_ADAPTER" else "failed"
                    e["reason"] = f'{out.get("error")}: {out.get("detail") or out.get("keys") or ""}'
                    e["analysis_key"], e["reused"] = None, False
                if con:
                    store.update_batch_member(con, config["batch_id"], e)
            for e in entries:
                if e["status"] == "duplicate_in_batch":
                    src = next(x for x in entries if x["index"] == e["duplicate_of"])
                    e["analysis_key"], e["exit_code"] = src.get("analysis_key"), src.get("exit_code")
                    if src["status"] != "succeeded":
                        e["reason"] = f"same content as entry {src['index']} ({src['status']})"
                    if con:
                        store.update_batch_member(con, config["batch_id"], e)
        finally:
            if con:
                con.close()
    return {"config": config, "entries": entries, "units": units}


# ------------------------------------------------------------------ metrics (raw, interpretable)
def _type_support(res):
    """Unique support ids per implemented type (union inside a type; types may overlap)."""
    det = res["detect"]
    sup = {}
    if "shape_supports" in det:
        for t in ("ring", "line"):
            if t in det["shape_supports"]:
                sup[t] = set(det["shape_supports"][t])
        local = {i for k, ids in det.get("signature_groups", {}).items() if k.startswith("local_") for i in ids}
        if local:
            sup["local"] = local
    lp = res["lift_pin"]
    if lp.get("feature_status") in ("candidate", "matched"):
        sup["lift_pin"] = {i for lb in lp["lobes"] if lb.get("present") for i in lb["support_ids"]}
    return sup


EVALUABLE = ("candidate", "matched", "no_match")


def type_status(res):
    """Per type: feature_status. ring/line/lift_pin come from their rules. local has no rule: it is derived
    here from DBSCAN (cluster not identical to a ring/line support -> candidate; none -> no_match; empty map
    -> insufficient_data; detect disabled -> disabled). It is labelled as derived wherever it is shown."""
    det = res["detect"]
    st = {}
    for t in ("ring", "line"):
        st[t] = det.get(t, det).get("feature_status") if isinstance(det, dict) else None
    if det.get("feature_status") == "disabled":
        st["local"] = "disabled"
    elif res["n_included"] == 0:
        st["local"] = "insufficient_data"
    else:
        st["local"] = "candidate" if any(c["same_as"] is None for c in det.get("clusters", {}).values()) else "no_match"
    st["lift_pin"] = res["lift_pin"].get("feature_status")
    return st


def unit_metrics(res):
    """Raw extent metrics for one analysed unit. Every ratio states its denominator; null + reason when it
    cannot be computed (empty map, coverage unknown, orientation unknown)."""
    n = res["n_included"]
    sup = _type_support(res)
    ts = type_status(res)
    m = {"n_included": n, "support": {}, "support_ratio": {}, "support_reason": {}}
    for t in TYPES:
        if ts[t] not in EVALUABLE:          # disabled / insufficient_data: not evaluated -> null, never 0
            m["support"][t] = m["support_ratio"][t] = None
            m["support_reason"][t] = f"type_status={ts[t]}"
            continue
        m["support"][t] = len(sup.get(t, ()))
        m["support_ratio"][t] = (m["support"][t] / n) if n else None
        m["support_reason"][t] = None if n else "no_included_defects (denominator 0)"
    # no evaluable type -> null; evaluable but no support -> real 0
    m["support_union_all_types"] = (len(set().union(*sup.values())) if sup else 0) \
        if any(ts[t] in EVALUABLE for t in TYPES) else None
    rows = res["radial_density"].get("rows")
    cov = res["provenance"]["coverage"]
    m["valid_area_mm2"] = m["density_per_mm2"] = None
    if cov.get("status") != "declared_by_sidecar":
        m["density_reason"] = "coverage_unknown"
    elif not rows:
        m["density_reason"] = f'radial_density {res["radial_density"].get("calc_status")}: {res["radial_density"].get("reason")}'
    elif any(r.get("n_outside_window") for r in rows):
        # same rule as the radial rows: defects outside the declared window make the density undefined
        m["density_reason"] = "points_outside_inspected_window"
    else:
        area = sum(r["area_mm2"] for r in rows if r["area_mm2"] is not None)
        m["valid_area_mm2"] = area
        m["density_per_mm2"] = n / area if area else None
        m["density_reason"] = None if area else "zero_inspected_area"
    det = res["detect"]
    ring = det.get("ring", {}) if isinstance(det, dict) else {}
    rm = ring.get("measurement") or {}
    m["ring"] = ({k: rm.get(k) for k in ("center_radius_mm", "diameter_mm", "ring_thickness_mm", "radial_extent_mm")}
                 if ring.get("feature_status") in ("candidate", "matched") else None)
    line = det.get("line", {}) if isinstance(det, dict) else {}
    lm = line.get("measurement") or {}
    m["line"] = ({k: lm.get(k) for k in ("length_mm", "width_mm", "rms_residual_mm", "direction_deg")}
                 if line.get("feature_status") in ("candidate", "matched") else None)
    sc = res["sectors_clock"]
    if sc is None:
        m["main_direction"] = None
        m["direction_reason"] = res["clock_status"]["reason"]
    else:
        denom = n - (res["center"] or 0)      # center region has no direction: excluded from the denominator
        top = max(sc.values()) if sc else 0
        hours = sorted(int(h) for h, v in sc.items() if v == top and top > 0)
        m["main_direction"] = {"hours": hours, "count": top, "ratio": (top / denom) if denom else None,
                               "denominator": "n_included - center", "denominator_value": denom}
        m["direction_reason"] = None if denom else "no_non_center_defects"
    lp = res["lift_pin"]
    m["lift_pin_lobes"] = ([{"position_deg": lb["position_deg"], "mean_deg": lb.get("mean_deg"), "n": lb["n"],
                             "present": lb["present"]} for lb in lp["lobes"]] if "lobes" in lp else None)
    return m


# ------------------------------------------------------------------ batch-level candidates (2026-10-12)
def _ang_diff(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _shape_features(out, es):
    """Normalized-frame features of one unit for the repeat comparison, or a reason per type.
    ring: center radius (rotation invariant). line / local: need the notch-registered frame."""
    r = out["result"]
    ts = type_status(r)
    det = r["detect"] if isinstance(r["detect"], dict) else {}
    feats, why = {}, {}
    ring = (det.get("ring") or {}).get("measurement") or {}
    if ts["ring"] in ("candidate", "matched") and ring.get("center_radius_mm") is not None:
        feats["ring"] = ring["center_radius_mm"]
    else:
        why["ring"] = f'no ring candidate (ring_status={ts["ring"]})'
    registered = r["orientation_status"] == "notch_registered"
    line = (det.get("line") or {}).get("measurement") or {}
    if not registered:
        why["line"] = why["local"] = "not comparable: orientation_unknown (positions are not in the notch-down frame)"
        return feats, why
    if ts["line"] in ("candidate", "matched") and line.get("direction_deg") is not None:
        a = math.radians(line["direction_deg"])
        cx, cy = line["centroid_mm"]
        feats["line"] = (line["direction_deg"], -math.sin(a) * cx + math.cos(a) * cy)   # signed offset from center
    else:
        why["line"] = f'no line candidate (line_status={ts["line"]})'
    pos = {p["defect_id"]: (p["x_mm"], p["y_mm"]) for p in out.get("_points") or [] if p["included"]}
    cents = []
    for c in det.get("clusters", {}).values():
        if c["same_as"] is None and len(c["ids"]) >= es["local_min_points"] and all(i in pos for i in c["ids"]):
            xs, ys = zip(*(pos[i] for i in c["ids"]))
            cents.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    if cents:
        feats["local"] = cents
    else:
        why["local"] = f'no local cluster with >= {es["local_min_points"]} points'
    return feats, why


def _match(t, a, b, es):
    if t == "ring":
        return abs(a - b) <= es["ring_radius_tol_mm"]
    if t == "line":
        (da, oa), (db, ob) = a, b
        flipped = abs(da - db) % 180.0 > 90.0     # direction wraps at 0/180: the normal (and offset sign) flips
        return _ang_diff(da, db) <= es["line_angle_tol_deg"] and \
            abs(oa - (-ob if flipped else ob)) <= es["line_offset_tol_mm"]
    return any(math.hypot(p[0] - q[0], p[1] - q[1]) <= es["local_distance_tol_mm"] for p in a for q in b)


def _clique(i, near, match, m):
    """A set of >= m wafers containing i whose features ALL match pairwise, or None. Small search: groups are
    one equipment's wafers in one batch and the match graph is sparse."""
    def grow(clique, cand):
        if len(clique) >= m:
            return clique
        for v in sorted(cand):
            rest = {w for w in cand if w > v and match(v, w)}
            if len(clique) + 1 + len(rest) >= m:
                found = grow(clique | {v}, rest)
                if found:
                    return found
        return None
    found = grow({i}, set(near))
    if found:   # extend to a maximal mutually matching set so rows of the same repeat list the same peers
        for v in sorted(set(near) - found):
            if all(match(v, w) for w in found):
                found = found | {v}
    return found


def batch_candidates(batch):
    """Per analysed unit index: batch-level candidate codes plus the status and reason behind each axis.
    Equipment repeat: same InspectionStationID, any StepID, >= min_wafers wafers whose features match pairwise
    within the profile tolerances (the unit itself counts). Defect volume: reported events vs profile limits.
    Settings come from the frozen batch config; a batch without them (older batch) reports 'not configured'."""
    cfg = batch["config"]
    es, dv = cfg.get("equipment_signature"), cfg.get("defect_volume")
    entries = {e["index"]: e for e in batch["entries"]}
    out = {i: {"codes": [], "equipment_id": (entries[i]["meta"] or {}).get("equipment"),
               "step_id": (entries[i]["meta"] or {}).get("step")} for i in batch["units"]}
    # --- equipment repeat
    if not es:
        for v in out.values():
            v.update(equipment_status="not_configured", equipment_reason="no equipment_signature settings in this batch",
                     equipment_detail={})
    elif not es["enabled"]:
        for v in out.values():
            v.update(equipment_status="disabled", equipment_reason="equipment_signature.enabled is false in profile",
                     equipment_detail={})
    else:
        groups = {}
        for i, v in out.items():
            if v["equipment_id"] is None:
                v.update(equipment_status="insufficient_data", equipment_detail={},
                         equipment_reason="no InspectionStationID in the KLARF header (equipment unknown)")
            else:
                groups.setdefault(v["equipment_id"], []).append(i)
        for members in groups.values():
            if len(members) < es["min_wafers"]:
                for i in members:
                    out[i].update(equipment_status="insufficient_data", equipment_detail={},
                                  equipment_reason=f'{len(members)} wafer(s) on this equipment in the batch '
                                                   f'(< min_wafers {es["min_wafers"]})')
                continue
            feats = {i: _shape_features(batch["units"][i], es) for i in members}
            for i in members:
                detail = {}
                for t in ("ring", "line", "local"):
                    if t not in feats[i][0]:
                        detail[t] = {"repeat": False, "reason": feats[i][1][t]}
                        continue
                    near = {j for j in members if j != i and t in feats[j][0]
                            and _match(t, feats[i][0][t], feats[j][0][t], es)}
                    peers = _clique(i, near, lambda a, b: _match(t, feats[a][0][t], feats[b][0][t], es),
                                    es["min_wafers"])
                    hit = peers is not None
                    peers = sorted(peers) if hit else sorted({i} | near)
                    detail[t] = {"repeat": hit, "peers": peers, "n": len(peers),
                                 "peers_rule": "all pairs match" if hit else "matching neighbours (not all pairs)",
                                 "steps": sorted({str(out[j]["step_id"]) for j in peers})}
                    if hit:
                        out[i]["codes"].append(f"equip_{t}")
                out[i].update(equipment_status="computed", equipment_detail=detail,
                              equipment_reason=None if out[i]["codes"] else
                              f'no repeat on {len(members)} wafers of this equipment (min_wafers {es["min_wafers"]})')
    # --- defect volume
    for i, v in out.items():
        n = batch["units"][i]["result"]["n_parsed"]
        ex, lim = (dv or {}).get("excess_defect_count"), (dv or {}).get("inspection_defect_limit")
        if not dv:
            st, why = "not_configured", "no defect_volume settings in this batch"
        elif ex is None and lim is None:
            st, why = "disabled", "defect_volume thresholds not set in profile"
        elif lim is not None and n >= lim:
            st, why = "abort_suspect", f"reported {n} defects reached inspection_defect_limit {lim} (abort evidence)"
            v["codes"].append("inspection_abort_suspect")
        elif ex is not None and n >= ex:
            st = "excess_abort_unconfirmed"
            why = f"reported {n} >= excess_defect_count {ex}; abort " + (
                "not verifiable: inspection_defect_limit not set" if lim is None else f"evidence absent ({n} < limit {lim})")
            v["codes"].append("excess_defect")
        else:
            st = "not_excess" if ex is not None else "below_limit"
            why = f"reported {n} < " + (f"excess_defect_count {ex}" if ex is not None else f"inspection_defect_limit {lim}")
        v.update(defect_volume_status=st, defect_volume_reason=why)
    return out


# ------------------------------------------------------------------ summaries
def overview(batch):
    es = batch["entries"]
    cnt = lambda s: sum(e["status"] == s for e in es)     # noqa: E731
    units = batch["units"]
    unit_meta = [(e["meta"]["lot"], e["meta"]["wafer"]) for e in es if e["index"] in units]
    known = {k for k in unit_meta if k[0] and k[1]}
    return {"files_uploaded": len(es), "files_targeted": len(es) - cnt("excluded"),
            "excluded": cnt("excluded"), "analysis_units": len(units), "succeeded": cnt("succeeded"),
            "failed": cnt("failed") + cnt("invalid_input"), "held": cnt("held"),
            "duplicates_in_batch": cnt("duplicate_in_batch"),
            "reused_from_store": sum(bool(e.get("reused")) for e in es if e["status"] == "succeeded"),
            "unique_wafers_from_header_unverified": len(known),
            "units_with_unknown_wafer_id": sum(1 for k in unit_meta if not (k[0] and k[1])),
            # nothing analysed -> null (not a real zero)
            "total_included_defects": sum(u["result"]["n_included"] for u in units.values()) if units else None,
            "null_reasons": {} if units else {"total_included_defects": "not computable: no analysed unit"}}


def _row_null_reasons(row, e, out, met, ts):
    """Why each null cell of a unit row is null. 'not computable' = 계산 불가, 'not applicable' = 해당 없음.
    Reason columns themselves (reason, *_reason) are not explained."""
    if out is None:
        why = {"metrics": f'not applicable: not analysed (status={e["status"]}'
                          + (f'; {e["reason"]})' if e["reason"] else ")")}
    else:
        why = {}
    det = out["result"]["detect"] if out else {}
    lp = out["result"]["lift_pin"] if out else {}

    def shape_why(t, key):
        if ts[t] not in ("candidate", "matched"):
            return f"not applicable: {t}_status={ts[t]}"
        withheld = ((det.get(t) or {}).get("measurement") or {}).get("withheld") or {}
        if key in withheld.get("keys", []):
            return f'not computable: withheld ({withheld.get("reason")})'
        return "not computable: measurement not available"

    shape_keys = {"ring_radius_mm": ("ring", "center_radius_mm"), "ring_diameter_mm": ("ring", "diameter_mm"),
                  "ring_thickness_mm": ("ring", "ring_thickness_mm"), "ring_radial_extent_mm": ("ring", "radial_extent_mm"),
                  "line_length_mm": ("line", "length_mm"), "line_width_mm": ("line", "width_mm"),
                  "line_rms_residual_mm": ("line", "rms_residual_mm"), "line_direction_deg": ("line", "direction_deg")}
    for col, v in row.items():
        if v is not None or col == "reason" or col.endswith("_reason"):
            continue
        if col in ("lot", "wafer"):
            why[col] = "not available: no value in the KLARF header (unverified source, T-26)"
        elif col == "job":
            why[col] = "not available: no job field is read (T-26)"
        elif col == "candidate_types":
            why[col] = "not applicable: not analysed"
        elif col == "equipment_id":
            why[col] = "not available: no InspectionStationID in the KLARF header"
        elif col == "step_id":
            why[col] = "not available: no StepID in the KLARF header"
        elif col == "duplicate_of":
            why[col] = "not applicable: not a duplicate"
        elif col == "reused":
            why[col] = "not applicable: not analysed in this batch"
        elif col == "analysis_key":
            why[col] = "not stored: no SQLite path" if out else "not applicable: not analysed"
        elif col.startswith("main_direction"):
            why[col] = f'not computable: {met["direction_reason"]}'
        elif col in ("valid_area_mm2", "density_per_mm2"):
            why[col] = f'not computable: {met["density_reason"]}'
        elif col in shape_keys:
            why[col] = shape_why(*shape_keys[col])
        elif col == "lift_pin_lobes":
            why[col] = f'not applicable: lift_pin_status={ts["lift_pin"]}' + (f' ({lp["reason"]})' if lp.get("reason") else "")
        elif col == "support_union_all_types":
            why[col] = "not computable: no evaluable type"
        elif col.endswith("_support") or col.endswith("_support_ratio"):
            t = col.split("_support")[0]
            why[col] = f'{"not applicable" if ts[t] == "disabled" else "not computable"}: {met["support_reason"][t]}'
        elif col == "review_latest_revision":
            why[col] = "not applicable: no review revision"
        else:
            why[col] = "not computable"
    return why


def unit_rows(batch, con=None):
    """One row per entry (files that did not analyse keep their status and reason; nothing is counted as
    'no pattern'). Review columns come from the store at view time and are labelled separately."""
    rows = []
    bc = batch_candidates(batch)
    for e in batch["entries"]:
        src = e["duplicate_of"] if e["status"] == "duplicate_in_batch" else e["index"]
        out = batch["units"].get(src)
        met = ts = None
        cand = bc.get(src)
        if out:
            r = out["result"]
            met = unit_metrics(r)
            ts = type_status(r)
        # candidate_types sits right after status; None (not analysed) is explained in null_reasons
        row = {"index": e["index"], "rel_path": e["rel_path"], "lot": e["meta"]["lot"], "wafer": e["meta"]["wafer"],
               "job": e["meta"]["job"], "status": e["status"],
               "candidate_types": ",".join([t for t in TYPES if ts[t] in ("candidate", "matched")] + cand["codes"])
               if out else None,
               "reason": e["reason"], "duplicate_of": e["duplicate_of"],
               "reused": e.get("reused"), "analysis_key": e.get("analysis_key")}
        if out:
            row.update(equipment_id=cand["equipment_id"], step_id=cand["step_id"],
                       equipment_signature_status=cand["equipment_status"],
                       equipment_signature_reason=cand["equipment_reason"],
                       equipment_signature_detail=json.dumps(cand["equipment_detail"], ensure_ascii=False),
                       defect_volume_status=cand["defect_volume_status"],
                       defect_volume_reason=cand["defect_volume_reason"])
            row.update(data_quality=out.get("data_quality_status"),
                       n_included=r["n_included"], bins=json.dumps(r["bin_totals"], ensure_ascii=False),
                       main_direction=(",".join(str(h) for h in met["main_direction"]["hours"])
                                       if met["main_direction"] else None),
                       main_direction_ratio=(met["main_direction"] or {}).get("ratio"),
                       main_direction_count=(met["main_direction"] or {}).get("count"),
                       main_direction_denominator=(met["main_direction"] or {}).get("denominator_value"),
                       direction_reason=met["direction_reason"], valid_area_mm2=met["valid_area_mm2"],
                       density_per_mm2=met["density_per_mm2"], density_reason=met["density_reason"],
                       ring_radius_mm=(met["ring"] or {}).get("center_radius_mm"),
                       ring_diameter_mm=(met["ring"] or {}).get("diameter_mm"),
                       ring_thickness_mm=(met["ring"] or {}).get("ring_thickness_mm"),
                       ring_radial_extent_mm=(met["ring"] or {}).get("radial_extent_mm"),
                       line_length_mm=(met["line"] or {}).get("length_mm"),
                       line_width_mm=(met["line"] or {}).get("width_mm"),
                       line_rms_residual_mm=(met["line"] or {}).get("rms_residual_mm"),
                       line_direction_deg=(met["line"] or {}).get("direction_deg"),
                       lift_pin_lobes=(json.dumps(met["lift_pin_lobes"], ensure_ascii=False)
                                       if met["lift_pin_lobes"] is not None else None),
                       support_union_all_types=met["support_union_all_types"],
                       **{f"{t}_status": ts[t] for t in TYPES},
                       **{f"{t}_support": met["support"][t] for t in TYPES},
                       **{f"{t}_support_ratio": met["support_ratio"][t] for t in TYPES},
                       **{f"{t}_support_reason": met["support_reason"][t] for t in TYPES})
        if con is not None and row["analysis_key"]:
            revs = store.reviews(con, row["analysis_key"])
            row["review_status_now"] = store.review_status(con, row["analysis_key"])
            row["review_latest_revision"] = revs[-1]["revision"] if revs else None
        # JSON text so the cell survives CSV and the screen table unchanged
        row["null_reasons"] = json.dumps(_row_null_reasons(row, e, out, met, ts), ensure_ascii=False)
        rows.append(row)
    return rows


def candidate_type_counts(rows):
    """Per candidate code: analysis units carrying it and percent of analysis units, counted from the SAME
    unit_rows candidate_types (no re-judging). Denominator = succeeded rows (duplicates in the batch are the same
    unit and are not counted again). Codes overlap, so percents may sum above 100."""
    units = [r for r in rows if r["status"] == "succeeded"]
    n = len(units)
    sets = [set(t for t in (r.get("candidate_types") or "").split(",") if t) for r in units]
    pct = (lambda c: round(100.0 * c / n, 1)) if n else (lambda c: None)
    out = [{"type": t, "label": TYPE_LABELS[t], "units": sum(t in s for s in sets), "percent": None}
           for t in (*TYPES, *EQUIP_TYPES)]
    out.append({"type": "(none)", "label": "후보 없음", "units": sum(not s for s in sets), "percent": None})
    for o in out:
        o["percent"] = pct(o["units"])
    return {"denominator_units": n, "rows": out,
            "reason": None if n else "not computable: no analysed unit (percent denominator 0)"}


def type_summary(batch):
    """Per implemented type: units by status, evaluable denominator, unique support total. Failed / held
    files are 'not_evaluated', never 'no pattern'. Types may overlap: no row-sum equals the unit count."""
    units = batch["units"]
    not_eval = sum(e["status"] in ("failed", "invalid_input", "held") for e in batch["entries"])
    out = []
    for t in TYPES:
        st = {}
        support = 0
        for u in units.values():
            s = type_status(u["result"])[t] or "unknown"
            st[s] = st.get(s, 0) + 1
            support += unit_metrics(u["result"])["support"][t] or 0     # only evaluable units contribute
        evaluable = st.get("candidate", 0) + st.get("matched", 0) + st.get("no_match", 0)
        out.append({"type": t, "candidate": st.get("candidate", 0), "matched": st.get("matched", 0),
                    "no_match": st.get("no_match", 0), "insufficient_data": st.get("insufficient_data", 0),
                    "disabled": st.get("disabled", 0), "evaluable_units": evaluable,
                    "not_evaluable_units": len(units) - evaluable, "files_not_evaluated": not_eval,
                    "unique_support_defects": support,
                    "note": "local = derived from DBSCAN clusters not identical to a ring/line support (no rule, no calibration)"
                            if t == "local" else None,
                    "basis": "initial predictions (reviews not applied)"})
    return out


def batch_density(batch):
    """sum(count) / sum(valid area) per comparable group (same profile, adapter, coverage shape/radius,
    schema). Units without coverage are excluded and counted - never averaged in as 0."""
    groups = {}
    for u in batch["units"].values():
        r = u["result"]
        p = r["provenance"]
        cov = p["coverage"]
        key = (p["profile_sha256"], p["adapter"], cov.get("status"), cov.get("shape"), cov.get("inspected_radius_mm"),
               p["schema_version"])
        g = groups.setdefault(key, {"units": 0, "count": 0, "area_mm2": 0.0, "excluded_no_coverage": 0})
        met = unit_metrics(r)
        if met["valid_area_mm2"] is None:
            g["excluded_no_coverage"] += 1
            continue
        g["units"] += 1
        g["count"] += r["n_included"]
        g["area_mm2"] += met["valid_area_mm2"]
    rows = []
    for (psha, adapter, cst, shape, radius, schema), g in groups.items():
        rows.append({"profile_sha256": psha, "adapter": adapter, "coverage_status": cst, "coverage_shape": shape,
                     "inspected_radius_mm": radius, "schema_version": schema, "units_in_density": g["units"],
                     "units_excluded_no_valid_area": g["excluded_no_coverage"], "sum_count": g["count"],
                     "sum_area_mm2": g["area_mm2"] or None,
                     "density_per_mm2": (g["count"] / g["area_mm2"]) if g["area_mm2"] else None,
                     "reason": None if g["area_mm2"] else
                     (f'not computable: no unit with a valid inspected area ({g["excluded_no_coverage"]} excluded: '
                      "coverage unknown, radial table disabled or points outside the inspected window)"
                      if g["excluded_no_coverage"] else "not computable: zero inspected area")})
    return rows


def bin_totals_by_group(batch):
    """Original bin totals, kept apart per profile content/adapter (bin meaning may differ between groups;
    same grouping basis as batch_density)."""
    groups = {}
    for u in batch["units"].values():
        p = u["result"]["provenance"]
        g = groups.setdefault((p["profile_id"], p["profile_sha256"], p["adapter"]), {})
        for b, n in u["result"]["bin_totals"].items():
            g[b] = g.get(b, 0) + n
    return [{"profile_id": k[0], "profile_sha256": k[1], "adapter": k[2], "bin_totals": v} for k, v in groups.items()]


# ------------------------------------------------------------------ exports
def _csv(rows):
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()


def summary_csv(batch, con=None):
    return _csv(unit_rows(batch, con))


def type_csv(batch):
    return _csv(type_summary(batch))


def _safe(name):
    keep = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(name).name)
    return keep[:80] or "file"


def export_zip(batch, con=None):
    """batch_manifest.json + summary CSVs + one folder per analysed unit (result.json, CSVs, manifest).
    Folder names are position + sanitized basename; the original relative path is in the manifest."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {"config": batch["config"], "overview": overview(batch),
                    "scope": "fixed batch at analysis time (initial predictions); review columns are read at export time",
                    "coverage_note": "one coverage sidecar (or none) applies to every unit of the batch",
                    "entries": [{k: e.get(k) for k in ("index", "rel_path", "size", "sha256", "status", "reason", "parser",
                                                       "adapter", "profile_id", "meta", "duplicate_of", "analysis_key",
                                                       "reused", "exit_code")} for e in batch["entries"]],
                    "type_summary": type_summary(batch), "density_by_group": batch_density(batch),
                    "bin_totals_by_group": bin_totals_by_group(batch),
                    "null_convention": NULL_CONVENTION + "; summary.csv: null_reasons column per row, density_by_group: reason, overview: null_reasons"}
        z.writestr("batch_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        z.writestr("summary.csv", summary_csv(batch, con))
        z.writestr("type_summary.csv", type_csv(batch))
        for idx, out in batch["units"].items():
            e = next(x for x in batch["entries"] if x["index"] == idx)
            folder = f"units/{idx:04d}_{_safe(e['rel_path'])}"
            clean = {k: v for k, v in out.items() if not k.startswith("_")}
            key = e.get("analysis_key")
            if con is not None and key:
                revs = store.reviews(con, key)
                clean["review"] = {"analysis_key": key, "review_status": store.review_status(con, key),
                                   "latest_revision": revs[-1]["revision"] if revs else None}
            else:
                clean["review"] = None
            z.writestr(f"{folder}/result.json", json.dumps(clean, ensure_ascii=False, indent=2, default=str))
            with tempfile.TemporaryDirectory() as d:
                for f in write_csv(out["result"], out["_points"], d):
                    z.write(f, f"{folder}/{Path(f).name}")
    return buf.getvalue()


def folder_items(root):
    """Test/CLI helper: (relative path, bytes) for every file under a server-side folder."""
    root = Path(root)
    return [(p.relative_to(root).as_posix(), p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()]
