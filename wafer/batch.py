"""Batch analysis: many uploaded files -> preflight list -> sequential run through the single-file core
(wafer.cli.run_job) -> per-unit rows, per-type summary, raw extent metrics, exports.

Small orchestration only (no queue, no new DB): one SQLite file may store runs (existing tables) plus a
batch/member link table. Uploaded names are kept as display/tracking paths only; files are written to
temp paths named by position, never by the uploaded name. File names are not parsed (TBD T-29); the
lot/wafer shown comes from the KLARF header and is marked unverified.

Counting units: an uploaded file is an entry; an analysis unit is one analysed wafer record. The current
parsers accept exactly one wafer record per file (more is INVALID_INPUT, T-12), so a successful entry
yields one unit. Identical content (same sha256) inside a batch is analysed once and the other entries
point to it (`duplicate_of`); nothing is merged silently.
"""
import csv
import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import ingest, store
from .cli import CODE_VERSION, RULE_VERSION, load_coverage, run_job
from .profile import ConfigInvalid, load_profile, validate_for_run
from .report import write_csv

# current input contract: the single-file uploader accepts these; anything else is excluded with a reason.
# The extension only selects candidates - the content must still parse (T-29: real exports, e.g. ".001", TBD).
SUPPORTED_EXTENSIONS = (".klf", ".klarf", ".txt")
DEFAULT_LIMITS = {"max_files": 500, "max_file_bytes": 50 * 1024 * 1024, "max_total_bytes": 300 * 1024 * 1024}
TYPES = ("ring", "line", "local", "lift_pin")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(v):
    return None if v is None else str(v).strip().strip('"').strip() or None


def _meta(header):
    """lot / wafer as written inside the file (flat: LotID / WaferID fields; 1.8: record names). job: no field."""
    return {"lot": _clean(header.get("LotID") or header.get("LotRecord")),
            "wafer": _clean(header.get("WaferID") or header.get("WaferRecord")),
            "job": None, "source": "klarf_header (unverified, T-29)"}


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
                 "profile_id": prof.profile_id, "meta": {"lot": None, "wafer": None, "job": None, "source": None},
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
                  "wafer_radius_mm": prof.wafer_radius_mm, "adapter": prof.coordinates.adapter_id}
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
            "total_included_defects": sum(u["result"]["n_included"] for u in units.values()) if units else None}


def unit_rows(batch, con=None):
    """One row per entry (files that did not analyse keep their status and reason; nothing is counted as
    'no pattern'). Review columns come from the store at view time and are labelled separately."""
    rows = []
    for e in batch["entries"]:
        src = e["duplicate_of"] if e["status"] == "duplicate_in_batch" else e["index"]
        out = batch["units"].get(src)
        row = {"index": e["index"], "rel_path": e["rel_path"], "lot": e["meta"]["lot"], "wafer": e["meta"]["wafer"],
               "job": e["meta"]["job"], "status": e["status"], "reason": e["reason"], "duplicate_of": e["duplicate_of"],
               "reused": e.get("reused"), "analysis_key": e.get("analysis_key")}
        if out:
            r = out["result"]
            met = unit_metrics(r)
            ts = type_status(r)
            row.update(data_quality=out.get("data_quality_status"),
                       candidate_types=",".join(t for t in TYPES if ts[t] in ("candidate", "matched")),
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
        rows.append(row)
    return rows


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
                     "density_per_mm2": (g["count"] / g["area_mm2"]) if g["area_mm2"] else None})
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
                    "null_convention": "empty cell / null = not computed or not applicable, 0 = real zero"}
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
