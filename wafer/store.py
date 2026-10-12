"""Local SQLite store for analysis runs and human review revisions (E17-E19, plan 16.4).

- A run is keyed by the analysis key: input content hash + profile hash + schema/code/parser/adapter
  versions + seed. Re-submitting the same key (e.g. same bytes under another filename) reuses the
  stored result - but only if the new result is identical; a different result under the same key
  (e.g. code changed without a version bump) is refused, never silently kept (KeyCollision).
- Every attempt is logged separately, so retries are visible without duplicating completed results.
- Reviews are append-only revisions that reference a run; the predicted result is never modified.
  Validation and numbering happen in one IMMEDIATE transaction, and replay refuses invalid revisions.
"""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    analysis_key TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    profile_sha256 TEXT,
    data_quality_status TEXT,
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_key TEXT,
    source_name TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_members (
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    position INTEGER NOT NULL,
    rel_path TEXT,
    size INTEGER,
    content_sha256 TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    analysis_key TEXT,
    duplicate_of INTEGER,
    PRIMARY KEY (batch_id, position)
);
CREATE TABLE IF NOT EXISTS reviews (
    analysis_key TEXT NOT NULL REFERENCES runs(analysis_key),
    revision INTEGER NOT NULL,
    action TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    reason TEXT,
    reviewer TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_key, revision)
);
"""
ACTIONS = ("confirm", "correct_label", "merge_clusters", "split_cluster", "defer")
LABEL_AXES = ("morphology", "zone", "signature_match")       # separate label axes (plan 5.2, C10/C11)
KEY_PARTS = ("source_sha256", "profile_sha256", "schema_version", "code_version", "rule_version",
             "parser", "adapter", "seed", "coverage")


class KeyCollision(Exception):
    """Same analysis key, different result: a version that affects results was not bumped."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    con = sqlite3.connect(path, timeout=30, isolation_level=None)   # explicit transactions only
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


@contextmanager
def _tx(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def analysis_key(result):
    prov = result["provenance"]
    missing = [k for k in KEY_PARTS if prov.get(k) is None]
    if missing:
        raise ValueError(f"cannot build analysis key, provenance lacks {missing}")
    parts = {k: prov[k] for k in KEY_PARTS}
    if isinstance(parts["coverage"], dict):
        parts["coverage"] = {k: parts["coverage"].get(k) for k in
                             ("status", "shape", "inspected_radius_mm", "sidecar_sha256")}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _name(source_name):
    return None if source_name is None else os.path.basename(str(source_name))   # no directory paths stored


def log_attempt(con, status, source_name=None, key=None, detail=None):
    with _tx(con):
        con.execute("INSERT INTO attempts (analysis_key, source_name, status, detail, created_at) VALUES (?,?,?,?,?)",
                    (key, _name(source_name), status, detail, _now()))


def save_run(con, result, source_name=None, data_quality_status=None):
    """Store a completed result once per analysis key. Returns (key, created). Only call with a
    finished, invariant-checked result: a failed job never reaches the store."""
    key = analysis_key(result)
    blob = json.dumps(result, ensure_ascii=False, default=str)   # compared after json round-trip (dict equality)
    with _tx(con):
        row = con.execute("SELECT result_json FROM runs WHERE analysis_key = ?", (key,)).fetchone()
        if row is not None and json.loads(row[0]) != json.loads(blob):
            con.execute("INSERT INTO attempts (analysis_key, source_name, status, detail, created_at) VALUES (?,?,?,?,?)",
                        (key, _name(source_name), "failed", "key_collision_result_mismatch", _now()))
            created = None
        else:
            created = row is None
            if created:
                con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                            (key, result["provenance"]["source_sha256"], result["provenance"].get("profile_sha256"),
                             data_quality_status, _now(), blob))
            con.execute("INSERT INTO attempts (analysis_key, source_name, status, detail, created_at) VALUES (?,?,?,?,?)",
                        (key, _name(source_name), "succeeded", "stored" if created else "reused_existing", _now()))
    if created is None:
        raise KeyCollision(key)
    return key, created


def get_run(con, key):
    row = con.execute("SELECT result_json FROM runs WHERE analysis_key = ?", (key,)).fetchone()
    return None if row is None else json.loads(row[0])


def _cluster_ids(result):
    return {str(k): set(v["ids"]) for k, v in result["detect"].get("clusters", {}).items()}


def _targets(result, clusters):
    return set(clusters) | set(result["detect"].get("signature_groups", {})) | {"lift_pin", "wafer"}


def _validate(result, clusters, action, payload):
    """clusters: the CURRENT reviewed membership (earlier merges/splits applied)."""
    if action not in ACTIONS:
        raise ValueError(f"unknown review action {action!r}")
    if action == "merge_clusters":
        ids = [str(c) for c in payload.get("clusters", [])]
        if len(ids) < 2 or len(set(ids)) != len(ids) or any(c not in clusters for c in ids):
            raise ValueError("merge_clusters needs >= 2 distinct existing cluster ids")
    if action == "split_cluster":
        c, parts = str(payload.get("cluster")), payload.get("parts", [])
        if c not in clusters or len(parts) < 2 or any(len(p) == 0 for p in parts):
            raise ValueError("split_cluster needs an existing cluster and >= 2 non-empty parts")
        if not all(isinstance(p, list) for p in parts):
            raise ValueError("split parts must be lists of defect ids")
        flat = [i for p in parts for i in p]
        if len(flat) != len(set(flat)) or set(flat) != clusters[c]:
            raise ValueError("split parts must partition the cluster's ids exactly (no loss, no duplicate)")
    if action == "correct_label":
        if not payload.get("label") or payload.get("axis") not in LABEL_AXES:
            raise ValueError(f"correct_label needs a label and an axis in {LABEL_AXES}")
        if str(payload.get("target")) not in _targets(result, clusters):
            raise ValueError("correct_label target must be a current cluster, a signature group, lift_pin or wafer")
    if action == "defer" and not payload.get("reason_code"):
        raise ValueError("defer needs a reason_code")


def add_review(con, key, action, payload, reason=None, reviewer=None):
    """Append a review revision; the stored prediction stays unchanged. Returns the revision number."""
    if not isinstance(payload, dict):
        raise ValueError("review payload must be a JSON object")
    with _tx(con):   # validate against the latest membership and number the revision atomically
        result = get_run(con, key)
        if result is None:
            raise ValueError("unknown analysis key")
        _validate(result, reviewed_clusters(con, key), action, payload)
        rev = con.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM reviews WHERE analysis_key = ?", (key,)).fetchone()[0]
        con.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?)",
                    (key, rev, action, json.dumps(payload, ensure_ascii=False), reason, reviewer, _now()))
    return rev


def reviews(con, key):
    rows = con.execute("SELECT revision, action, payload_json, reason, reviewer, created_at FROM reviews "
                       "WHERE analysis_key = ? ORDER BY revision", (key,)).fetchall()
    return [{"revision": r[0], "action": r[1], "payload": json.loads(r[2]), "reason": r[3],
             "reviewer": r[4], "created_at": r[5]} for r in rows]


def reviewed_clusters(con, key, upto=None):
    """Cluster membership after applying merge/split revisions (up to `upto`) to the stored prediction.
    A revision that no longer applies is an error, never silently skipped."""
    result = get_run(con, key)
    if result is None:
        raise ValueError("unknown analysis key")
    clusters = _cluster_ids(result)
    for rv in reviews(con, key):
        if upto is not None and rv["revision"] > upto:
            break
        p = rv["payload"]
        if rv["action"] == "merge_clusters":
            ids = [str(c) for c in p["clusters"]]
            if len(set(ids)) != len(ids) or not all(c in clusters for c in ids):
                raise ValueError(f"revision {rv['revision']} cannot be replayed (merge)")
            clusters["+".join(ids)] = set().union(*(clusters.pop(c) for c in ids))
        elif rv["action"] == "split_cluster":
            c = str(p["cluster"])
            if c not in clusters:
                raise ValueError(f"revision {rv['revision']} cannot be replayed (split)")
            clusters.pop(c)
            for n, part in enumerate(p["parts"]):
                clusters[f"{c}.{n}"] = set(part)
    return clusters


def review_status(con, key):
    """Plan 16.2 review_status of a run: unreviewed / confirmed / corrected / deferred (latest revision wins)."""
    revs = reviews(con, key)
    if not revs:
        return "unreviewed"
    last = revs[-1]["action"]
    return {"confirm": "confirmed", "defer": "deferred"}.get(last, "corrected")


def save_batch(con, config, entries):
    """Link a batch to its members. Results and reviews stay in runs / reviews (one copy each); a run that
    appears in several batches is referenced, never duplicated or overwritten. Only the file name (basename)
    is stored, as for attempts (T-24); the full relative path stays in the downloaded manifest."""
    with _tx(con):
        con.execute("INSERT INTO batches VALUES (?,?,?)",
                    (config["batch_id"], config["created_at"], json.dumps(config, ensure_ascii=False, default=str)))
        con.executemany("INSERT INTO batch_members VALUES (?,?,?,?,?,?,?,?,?)",
                        [(config["batch_id"], e["index"], os.path.basename(e["rel_path"]), e["size"], e["sha256"],
                          e["status"], e["reason"], e.get("analysis_key"), e["duplicate_of"]) for e in entries])


def update_batch_member(con, batch_id, e):
    """Status of one member after its run (link row only; runs and reviews are not touched)."""
    with _tx(con):
        con.execute("UPDATE batch_members SET status = ?, reason = ?, analysis_key = ? WHERE batch_id = ? AND position = ?",
                    (e["status"], e["reason"], e.get("analysis_key"), batch_id, e["index"]))


def batch_members(con, batch_id):
    rows = con.execute("SELECT position, rel_path, status, analysis_key, duplicate_of FROM batch_members "
                       "WHERE batch_id = ? ORDER BY position", (batch_id,)).fetchall()
    return [{"position": r[0], "rel_path": r[1], "status": r[2], "analysis_key": r[3], "duplicate_of": r[4]}
            for r in rows]
