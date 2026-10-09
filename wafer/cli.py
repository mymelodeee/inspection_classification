"""CLI: python -m wafer.cli <file.klf> --profile <profile.yaml> [--out result.json]

Runs the shared core (ingest -> aggregate -> stats -> detect). Emits JSON; job_status is separate
from data quality and from per-feature status.
"""
import argparse
import hashlib
import json
import sys

import numpy as np

from . import ingest
from .aggregate import aggregate, included_mask
from .detect import detect_groups
from .groups import summarize_groups
from .lift_pin import match_lift_pin
from .profile import ConfigInvalid, load_profile, validate_for_run
from .stats import clark_evans, radial_density

CODE_VERSION = "0.1.0-dev"
SCHEMA_VERSION = "result-0.1"
INSPECTED_RADIUS_MM = None  # coverage is unknown for every supported input (TBD T-05, option a)


def _radial(r, profile):
    step, R = profile.stats.radial_bin_mm, profile.wafer_radius_mm
    if step is None:
        return {"calc_status": "disabled", "reason": "stats.radial_bin_mm not set"}
    n = int(np.ceil(R / step))
    edges = [k * step for k in range(n)] + [R]       # exact R; last bin closed so r = R counts (16.3-8)
    return {"calc_status": "computed", **radial_density(r, edges, INSPECTED_RADIUS_MM, close_last=True)}


def _pattern_summary(n_included, det, lift_pin):
    """Plan 8.1 labels, kept apart from feature_status (T-10)."""
    if n_included == 0:
        return ["no_detected_defect"]
    labels = sorted({v["label"] for k, v in det.items() if k in ("ring", "line") and "label" in v})
    if any(c["same_as"] is None for c in det.get("clusters", {}).values()):
        labels.append("local_cluster")
    if lift_pin.get("feature_status") in ("candidate", "matched"):
        labels.append("lift_pin")
    return labels or ["no_clear_pattern"]


def analyze_file(path, profile, profile_sha256=None):
    k = ingest.read_klarf(path)
    ids, xs, ys, bins, dies = ingest.to_standard(k)
    res = aggregate(ids, xs, ys, bins, profile)
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    inc = np.flatnonzero(included_mask(x, y, profile))   # same definition aggregate used
    iid = [ids[i] for i in inc]
    ix, iy = x[inc], y[inc]
    rnd = profile.randomness
    res["radial_density"] = _radial(np.hypot(ix, iy), profile)
    res["clark_evans"] = clark_evans(ix, iy, INSPECTED_RADIUS_MM, nsim=rnd.nsim, seed=rnd.seed)
    det = detect_groups(iid, ix, iy, profile)
    if "signature_groups" in det:
        bin_by_id = {ids[i]: (bins[i] or "unknown") for i in inc}
        det["summary"] = summarize_groups(det["signature_groups"], bin_by_id)
    res["detect"] = det  # candidates are computed regardless of the randomness result (C07)
    res["lift_pin"] = match_lift_pin(iid, ix, iy, profile.signatures.lift_pin, uncovered=None)  # coverage unknown
    res["pattern_summary"] = _pattern_summary(res["n_included"], det, res["lift_pin"])
    res["affected_die_count"] = None  # synthetic adapter has a single pseudo-die; real die rule TBD (T-02, T-05)
    res["inspected_die_count"] = None
    res["provenance"] = {"source_sha256": k.source_sha256, "profile_id": profile.profile_id,
                         "profile_sha256": profile_sha256, "schema_version": SCHEMA_VERSION,
                         "adapter": "synthetic-um-die00-notch-down", "code_version": CODE_VERSION,
                         "parser": "wafer.ingest-strict-1", "rule_version": None, "model_version": None,
                         "seed": rnd.seed}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wafer")
    ap.add_argument("klarf")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        with open(a.profile, "rb") as f:
            psha = hashlib.sha256(f.read()).hexdigest()   # hash of the bytes loaded right below
        prof = load_profile(a.profile)
        validate_for_run(prof)
        result = analyze_file(a.klarf, prof, psha)
        out = {"job_status": "succeeded", "data_quality_status": "valid", "result": result}
        code = 0
    except FileNotFoundError as e:
        out, code = {"job_status": "failed", "error": "INPUT_NOT_FOUND",
                     "detail": f"file not found: {e.filename}"}, 4
    except ConfigInvalid as e:
        out, code = {"job_status": "failed", "error": "CONFIG_INVALID", "keys": list(e.keys)}, 2
    except ingest.KlarfError as e:
        out = {"job_status": "failed", "detail": str(e)}
        if isinstance(e, ingest.AdapterUnsupported):
            out["error"] = "UNSUPPORTED_ADAPTER"  # input not judged bad; coverage of this export is TBD
        else:
            out.update(error="INVALID_INPUT", data_quality_status="invalid")
        code = 3
    except Exception as e:  # never a bare traceback; do not echo input content
        out, code = {"job_status": "failed", "error": "INTERNAL_ERROR", "detail": type(e).__name__}, 5
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
