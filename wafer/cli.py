"""CLI: python -m wafer.cli <file.klf> --profile <profile.yaml> [--out result.json]

Runs the shared core (ingest -> aggregate -> stats -> detect). Emits JSON; job_status is separate
from data quality and from per-feature status.
"""
import argparse
import hashlib
import math
import json
import sys
from pathlib import Path

import numpy as np

from . import ingest
from .aggregate import aggregate, included_mask
from .detect import detect_groups
from .groups import summarize_groups
from .lift_pin import match_lift_pin
from .profile import ConfigInvalid, load_profile, validate_for_run
from .report import ResultInvariantError, check_result, null_reasons, write_csv
from . import store, version
from .stats import clark_evans, radial_density

CODE_VERSION = version.code_version()   # base version + content hash of result-affecting modules
RULE_VERSION = version.rule_version()
SCHEMA_VERSION = "result-0.2"   # 0.2: null_reasons for every top-level null (2026-10-11)


class CoverageInvalid(ConfigInvalid):
    """Coverage sidecar rejected; `reason` says why: syntax_error / unsupported_shape / invalid_value (T-04)."""

    def __init__(self, keys, reason, message=""):
        super().__init__(keys, message)
        self.reason = reason


def load_coverage(path, profile):
    """Coverage is an explicit INPUT (a sidecar), never inferred from defects or file size (T-04).
    Supported: {"coverage": {"shape": "full_disk", "radius_mm": R, "source": "..."}}. None -> unknown."""
    if path is None:
        return {"status": "unknown", "inspected_radius_mm": None}
    raw = Path(path).read_bytes()
    try:
        cov = json.loads(raw.decode("utf-8"))["coverage"]
    except (ValueError, KeyError, TypeError):
        raise CoverageInvalid(["coverage"], "syntax_error", "coverage sidecar must be JSON with a 'coverage' object")
    if not isinstance(cov, dict):
        raise CoverageInvalid(["coverage"], "syntax_error", "coverage must be an object")
    if cov.get("shape") != "full_disk":
        raise CoverageInvalid(["coverage.shape"], "unsupported_shape", "only shape=full_disk is supported")
    R = cov.get("radius_mm")
    if (not isinstance(R, (int, float)) or isinstance(R, bool) or not math.isfinite(R) or R <= 0
            or profile.wafer_radius_mm is None or R > profile.wafer_radius_mm):
        raise CoverageInvalid(["coverage.radius_mm"], "invalid_value", "radius must be finite, > 0 and <= wafer_radius_mm")
    return {"status": "declared_by_sidecar", "shape": "full_disk", "inspected_radius_mm": float(R),
            "source": cov.get("source"),   # file name deliberately not recorded: content hash identifies it
            "sidecar_sha256": hashlib.sha256(raw).hexdigest()}


# Measurement keys that encode a direction or a position in the (unregistered) frame. Radius, thickness,
# length, occupancy and labels are rotation-invariant and are kept (plan 16.1, E10, TBD T-02).
ORIENTATION_KEYS = ("occupied_hours", "occupied_hours_tolerant", "center_x_mm", "center_y_mm",
                    "direction_deg", "centroid_mm")


def _withhold_orientation(det):
    for name in ("ring", "line"):
        m = det.get(name, {}).get("measurement")
        if isinstance(m, dict):
            for k in ORIENTATION_KEYS:
                if k in m:
                    m[k] = None
            m["withheld"] = {"keys": [k for k in ORIENTATION_KEYS if k in m], "reason": "orientation_unknown"}


def _uncovered(rc, profile):
    """None = coverage unknown; [] = whole wafer inspected; otherwise the uninspected ring (rc, R]."""
    if rc is None:
        return None
    R = profile.wafer_radius_mm
    if R is None or rc >= R:
        return []
    return [{"clock_deg_interval": [0, 360], "radius_mm_interval": [rc, R + 1e-9]}]


def _radial(r, profile, inspected_radius_mm):
    step, R = profile.stats.radial_bin_mm, profile.wafer_radius_mm
    if step is None:
        return {"calc_status": "disabled", "reason": "stats.radial_bin_mm not set"}
    n = int(np.ceil(R / step))
    edges = [k * step for k in range(n)] + [R]       # exact R; last bin closed so r = R counts (16.3-8)
    return {"calc_status": "computed", **radial_density(r, edges, inspected_radius_mm, close_last=True)}


def _pattern_summary(n_included, det, lift_pin):
    """Plan 8.1 labels, kept apart from feature_status (R-02)."""
    if n_included == 0:
        return ["no_detected_defect"]
    labels = sorted({v["label"] for k, v in det.items() if k in ("ring", "line") and "label" in v})
    if any(c["same_as"] is None for c in det.get("clusters", {}).values()):
        labels.append("local_cluster")
    if lift_pin.get("feature_status") in ("candidate", "matched"):
        labels.append("lift_pin")
    return labels or ["no_clear_pattern"]


def analyze_file(path, profile, profile_sha256=None, return_points=False, coverage=None):
    k = ingest.read_klarf(path)
    coverage = coverage or {"status": "unknown", "inspected_radius_mm": None}
    rc = coverage["inspected_radius_mm"]
    adapter, orientation, (ids, xs, ys, bins, dies) = ingest.standardize(k, profile.coordinates)
    res, points = aggregate(ids, xs, ys, bins, profile, n_parsed=len(k.records), return_points=True,
                            orientation=orientation)
    res["orientation_status"] = orientation   # notch_registered | unknown (clock / phase withheld when unknown)
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    inc = np.flatnonzero(included_mask(x, y, profile))   # same definition aggregate used
    iid = [ids[i] for i in inc]
    ix, iy = x[inc], y[inc]
    rnd = profile.randomness
    res["radial_density"] = _radial(np.hypot(ix, iy), profile, rc)
    res["clark_evans"] = clark_evans(ix, iy, rc, nsim=rnd.nsim, seed=rnd.seed)
    det = detect_groups(iid, ix, iy, profile)
    if "signature_groups" in det:
        bin_by_id = {ids[i]: (bins[i] or "unknown") for i in inc}
        det["summary"] = summarize_groups(det["signature_groups"], bin_by_id)
    if isinstance(det, dict) and det.get("feature_status") != "disabled":
        det["frame"] = "notch_down" if orientation == "notch_registered" else "unregistered"   # angles/directions
        if orientation != "notch_registered":
            _withhold_orientation(det)
    res["detect"] = det  # candidates are computed regardless of the randomness result (C07)
    if orientation != "notch_registered" and profile.signatures.lift_pin.enabled:
        res["lift_pin"] = {"feature_status": "insufficient_data", "reason": "orientation_unknown"}   # phase needs notch
    else:
        res["lift_pin"] = match_lift_pin(iid, ix, iy, profile.signatures.lift_pin, uncovered=_uncovered(rc, profile))
    res["pattern_summary"] = _pattern_summary(res["n_included"], det, res["lift_pin"])
    res["affected_die_count"] = None  # no inspected-die list / real die rule yet (T-01, T-04, T-13)
    res["inspected_die_count"] = None
    res["provenance"] = {"source_sha256": k.source_sha256, "profile_id": profile.profile_id,
                         "profile_sha256": profile_sha256, "schema_version": SCHEMA_VERSION,
                         "adapter": adapter, "coverage": coverage, "code_version": CODE_VERSION,
                         "parser": "wafer.ingest-strict-2", "rule_version": RULE_VERSION, "model_version": None,
                         "seed": rnd.seed}
    res["null_reasons"] = null_reasons(res)
    check_result(res)
    return (res, points) if return_points else res


class _OutputError(Exception):
    pass


def run_job(klarf, profile_path, db=None, csv_dir=None, source_name=None, coverage_path=None):
    """Shared job entry for the CLI and the UI (no duplicated analysis or error mapping, plan 13).
    Returns (out, exit_code); out carries job_status / data_quality_status / result separately."""
    source_name = source_name or klarf
    try:
        with open(profile_path, "rb") as f:
            psha = hashlib.sha256(f.read()).hexdigest()   # hash of the bytes loaded right below
        prof = load_profile(profile_path)
        validate_for_run(prof)
        result, points = analyze_file(klarf, prof, psha, return_points=True,
                                      coverage=load_coverage(coverage_path, prof))
        out = {"job_status": "succeeded", "data_quality_status": "valid", "result": result}
        if csv_dir:
            try:
                write_csv(result, points, csv_dir)
            except OSError as e:
                raise _OutputError(str(e.filename or csv_dir)) from None
        if db:
            con = store.connect(db)
            try:
                key, created = store.save_run(con, result, source_name=source_name,
                                              data_quality_status=out["data_quality_status"])
            finally:
                con.close()
            out["store"] = {"analysis_key": key, "created": created}   # False = same analysis already stored
        # underscore keys are for in-process callers (UI/exports) only; main() strips them from the JSON
        out["_points"] = points
        out["_wafer_radius_mm"] = prof.wafer_radius_mm
        code = 0
    except store.KeyCollision as e:
        out, code = {"job_status": "failed", "error": "KEY_COLLISION_RESULT_MISMATCH",
                     "detail": f"analysis key {e} already stored with a different result; bump a version"}, 7
    except _OutputError as e:
        out, code = {"job_status": "failed", "error": "OUTPUT_WRITE_FAILED", "detail": f"cannot write: {e}"}, 6
    except ResultInvariantError as e:   # program defect; message names the broken invariant only
        out, code = {"job_status": "failed", "error": "RESULT_INVARIANT_VIOLATED", "detail": str(e)}, 5
    except FileNotFoundError as e:
        out, code = {"job_status": "failed", "error": "INPUT_NOT_FOUND",
                     "detail": f"file not found: {e.filename}"}, 4
    except ConfigInvalid as e:
        out, code = {"job_status": "failed", "error": "CONFIG_INVALID", "keys": list(e.keys)}, 2
        if isinstance(e, CoverageInvalid):
            out["reason"] = f"coverage_{e.reason}"
    except ingest.KlarfError as e:
        out = {"job_status": "failed", "detail": str(e)}
        if isinstance(e, ingest.AdapterUnsupported):
            out["error"] = "UNSUPPORTED_ADAPTER"  # input not judged bad; coverage of this export is TBD
        else:
            out.update(error="INVALID_INPUT", data_quality_status="invalid")
        code = 3
    except Exception as e:  # never a bare traceback; do not echo input content
        out, code = {"job_status": "failed", "error": "INTERNAL_ERROR", "detail": type(e).__name__}, 5
    if code not in (0, 7) and db:   # failed jobs are logged as attempts, never stored as results
        try:
            con = store.connect(db)
            store.log_attempt(con, "failed", source_name=source_name, detail=out.get("error"))
            con.close()
        except Exception:
            out["attempt_log_failed"] = True   # surfaced, not hidden
    return out, code


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wafer")
    ap.add_argument("klarf")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out")
    ap.add_argument("--csv-dir", help="also write defects.csv, spatial_counts.csv, bin_sector.csv here")
    ap.add_argument("--db", help="SQLite file: store the completed run (idempotent per analysis key)")
    ap.add_argument("--coverage", help="coverage sidecar JSON (explicit input; omitted = coverage unknown)")
    a = ap.parse_args(argv)
    out, code = run_job(a.klarf, a.profile, db=a.db, csv_dir=a.csv_dir, coverage_path=a.coverage)
    out = {k: v for k, v in out.items() if not k.startswith("_")}
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
