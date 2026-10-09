"""E17 (duplicate input / re-analysis), E18 (failure / retry / concurrent writers), E19 (review revisions)
on the local SQLite store. Synthetic inputs; the review flow is exercised through functions (no UI yet).
"""
import json
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest
import yaml

from wafer import store
from wafer.cli import main

HERE = Path(__file__).parent
K = HERE / "fixtures/klarf"
PROFILE = HERE / "profiles/f01_test_profile.yaml"
E06 = json.loads((HERE / "fixtures/e06_mixed/e06_mixed.json").read_text(encoding="utf-8"))


def cli(klf, db, tmp_path, profile=PROFILE, name="o.json"):
    out = tmp_path / name
    code = main([str(klf), "--profile", str(profile), "--out", str(out), "--db", str(db)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def counts(db):
    con = sqlite3.connect(db)
    r = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("runs", "attempts", "reviews")}
    con.close()
    return r


def test_e17_same_bytes_other_filename_reuses_the_run(tmp_path):
    db = tmp_path / "w.db"
    copy = tmp_path / "renamed.klf"
    shutil.copy(K / "f01.klf", copy)
    c1, o1 = cli(K / "f01.klf", db, tmp_path, name="a.json")
    c2, o2 = cli(copy, db, tmp_path, name="b.json")
    c3, o3 = cli(K / "f01.klf", db, tmp_path, name="c.json")
    assert (c1, c2, c3) == (0, 0, 0)
    assert o1["store"]["created"] is True and o2["store"]["created"] is False and o3["store"]["created"] is False
    assert o1["store"]["analysis_key"] == o2["store"]["analysis_key"] == o3["store"]["analysis_key"]
    assert counts(db) == {"runs": 1, "attempts": 3, "reviews": 0}   # 3 attempts, one logical result


def test_e17_changed_profile_creates_a_new_run_and_keeps_the_old_one(tmp_path):
    db = tmp_path / "w.db"
    _, o1 = cli(K / "f01.klf", db, tmp_path, name="a.json")
    d = yaml.safe_load(open(PROFILE, encoding="utf-8"))
    d["clock"]["boundary_tolerance_deg"] = 3.0
    p2 = tmp_path / "p2.yaml"
    p2.write_text(yaml.safe_dump(d), encoding="utf-8")
    _, o2 = cli(K / "f01.klf", db, tmp_path, profile=p2, name="b.json")
    assert o2["store"]["created"] is True and o2["store"]["analysis_key"] != o1["store"]["analysis_key"]
    con = store.connect(db)
    assert store.get_run(con, o1["store"]["analysis_key"])["boundary_tolerance_deg"] == 5.0   # old kept
    assert store.get_run(con, o2["store"]["analysis_key"])["boundary_tolerance_deg"] == 3.0
    assert counts(db)["runs"] == 2


def test_e18_failed_job_is_logged_but_never_stored_then_retry_succeeds(tmp_path):
    db = tmp_path / "w.db"
    code, o = cli(K / "bad_truncated.klf", db, tmp_path, name="a.json")
    assert code == 3 and "store" not in o
    assert counts(db) == {"runs": 0, "attempts": 1, "reviews": 0}
    code, o = cli(K / "f01.klf", db, tmp_path, name="b.json")        # "retry" with the completed file
    assert code == 0 and o["store"]["created"] is True and counts(db)["runs"] == 1


def test_e18_concurrent_writers_store_exactly_one_result(tmp_path):
    db = tmp_path / "w.db"
    store.connect(db).close()
    errors = []

    def worker(i):
        try:
            cli(K / "f01.klf", db, tmp_path, name=f"t{i}.json")
        except Exception as e:   # pragma: no cover - surfaced below
            errors.append(e)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert counts(db)["runs"] == 1 and counts(db)["attempts"] == 4


def _e06_run(con, case="intact"):
    """Store a synthetic result whose clusters are the E06 fixture supports (local blob + line chain)."""
    sup = E06["cases"][case]["expected"]["support_ids"]
    result = {"provenance": {"source_sha256": "e06-" + case, "profile_sha256": "p", "code_version": "t",
                             "parser": "t", "adapter": "t", "seed": 1, "schema_version": "s",
                             "rule_version": "r", "coverage": {"status": "unknown"}},
              "detect": {"clusters": {"0": {"ids": sup["local"], "same_as": None},
                                      "1": {"ids": sup["line"], "same_as": "line"}}}}
    return store.save_run(con, result)[0], sup


def test_e19_reviews_are_append_only_and_keep_the_prediction(tmp_path):
    con = store.connect(tmp_path / "w.db")
    key, sup = _e06_run(con)
    before = store.get_run(con, key)
    r1 = store.add_review(con, key, "correct_label", {"target": "0", "axis": "morphology", "label": "edge_local"},
                          reason="looks edge-local", reviewer="qa1")
    r2 = store.add_review(con, key, "merge_clusters", {"clusters": ["0", "1"]}, reason="same event", reviewer="qa1")
    assert (r1, r2) == (1, 2)
    assert store.get_run(con, key) == before                         # prediction untouched
    merged = store.reviewed_clusters(con, key)
    assert list(merged) == ["0+1"]
    assert merged["0+1"] == set(sup["local"]) | set(sup["line"])    # unique ids preserved (12 + 15 = 27)
    assert len(merged["0+1"]) == 27
    assert store.reviewed_clusters(con, key, upto=1) == {"0": set(sup["local"]), "1": set(sup["line"])}


def test_e19_split_must_partition_exactly_and_works_on_merged_clusters(tmp_path):
    con = store.connect(tmp_path / "w.db")
    key, sup = _e06_run(con)
    blob = sorted(sup["local"])
    with pytest.raises(ValueError):                                  # loses an id
        store.add_review(con, key, "split_cluster", {"cluster": "0", "parts": [blob[:5], blob[5:-1]]})
    with pytest.raises(ValueError):                                  # duplicates an id
        store.add_review(con, key, "split_cluster", {"cluster": "0", "parts": [blob[:6], blob[5:]]})
    store.add_review(con, key, "merge_clusters", {"clusters": ["0", "1"]})
    allids = sorted(set(sup["local"]) | set(sup["line"]))
    store.add_review(con, key, "split_cluster", {"cluster": "0+1", "parts": [allids[:10], allids[10:]]})
    after = store.reviewed_clusters(con, key)
    assert sorted(len(v) for v in after.values()) == [10, 17]
    assert set().union(*after.values()) == set(allids)               # nothing lost or duplicated
    assert [r["action"] for r in store.reviews(con, key)] == ["merge_clusters", "split_cluster"]


def test_e19_reanalysis_does_not_touch_reviews(tmp_path):
    db = tmp_path / "w.db"
    con = store.connect(db)
    key, _ = _e06_run(con)
    store.add_review(con, key, "defer", {"reason_code": "needs_sem_review"})
    _e06_run(con)                                                    # same analysis again (retry)
    _e06_run(con, "broken_ring")                                     # a different analysis
    assert len(store.reviews(con, key)) == 1 and counts(db)["runs"] == 2


def test_review_validation():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        con = store.connect(Path(d) / "w.db")
        key, _ = _e06_run(con)
        for action, payload in [("bogus", {}), ("merge_clusters", {"clusters": ["0"]}),
                                ("merge_clusters", {"clusters": ["0", "9"]}), ("correct_label", {}),
                                ("merge_clusters", {"clusters": ["0", "0"]}),           # duplicate id
                                ("split_cluster", {"cluster": "0", "parts": [[], sorted(E06["cases"]["intact"]["expected"]["support_ids"]["local"])]}),
                                ("correct_label", {"target": "0", "label": "x"}),        # no axis
                                ("correct_label", {"target": "zz", "axis": "zone", "label": "x"}),
                                ("defer", {})]:
            with pytest.raises(ValueError):
                store.add_review(con, key, action, payload)
        with pytest.raises(ValueError):
            store.add_review(con, "nope", "confirm", {})
        with pytest.raises(ValueError):
            store.reviewed_clusters(con, "nope")
        assert store.reviews(con, key) == []          # every invalid review was refused, nothing stored
        con.close()



def test_same_key_with_a_different_result_is_refused_not_silently_kept(tmp_path):
    con = store.connect(tmp_path / "w.db")
    key, _ = _e06_run(con)
    changed = store.get_run(con, key)
    changed["detect"]["clusters"]["0"]["ids"] = changed["detect"]["clusters"]["0"]["ids"][:-1]
    with pytest.raises(store.KeyCollision):
        store.save_run(con, changed)
    assert store.get_run(con, key)["detect"]["clusters"]["0"]["ids"] != changed["detect"]["clusters"]["0"]["ids"]
    row = con.execute("SELECT status, detail FROM attempts ORDER BY attempt_id DESC LIMIT 1").fetchone()
    assert row == ("failed", "key_collision_result_mismatch")


def test_cli_key_collision_exit_code(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    cli(K / "f01.klf", db, tmp_path, name="a.json")
    import wafer.cli as c
    real = c.analyze_file

    def drifted(*a, **k):                         # injected fault (mock): code changed, version not bumped
        res, pts = real(*a, **k)
        res["pattern_summary"] = ["drift"]
        return res, pts
    monkeypatch.setattr(c, "analyze_file", drifted)
    code, o = cli(K / "f01.klf", db, tmp_path, name="b.json")
    assert code == 7 and o["error"] == "KEY_COLLISION_RESULT_MISMATCH" and counts(db)["runs"] == 1


def test_e18_failure_while_saving_leaves_no_result(tmp_path, monkeypatch):
    db = tmp_path / "w.db"

    def boom(*a, **k):                            # injected fault (mock): storage fails right before commit
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(store, "save_run", boom)
    code, o = cli(K / "f01.klf", db, tmp_path)
    assert code == 5 and o["job_status"] == "failed" and counts(db)["runs"] == 0
    monkeypatch.undo()
    code, o = cli(K / "f01.klf", db, tmp_path, name="retry.json")
    assert code == 0 and o["store"]["created"] is True and counts(db)["runs"] == 1


def test_e18_concurrent_different_inputs_do_not_mix(tmp_path):
    db = tmp_path / "w.db"
    store.connect(db).close()
    files = ["f01.klf", "single_point.klf", "center_only.klf", "e09_unclassified_bin.klf"]
    outs = {}

    def worker(f):
        outs[f] = cli(K / f, db, tmp_path, name=f + ".json")[1]
    ts = [threading.Thread(target=worker, args=(f,)) for f in files]
    [t.start() for t in ts]
    [t.join() for t in ts]
    con = store.connect(db)
    assert counts(db)["runs"] == 4
    for f, o in outs.items():
        assert store.get_run(con, o["store"]["analysis_key"])["provenance"]["source_sha256"] == o["result"]["provenance"]["source_sha256"]
    names = {r[0] for r in con.execute("SELECT source_name FROM attempts")}
    assert names == set(files)                    # basenames only, no directory paths


def test_review_status_follows_the_latest_revision(tmp_path):
    con = store.connect(tmp_path / "w.db")
    key, _ = _e06_run(con)
    assert store.review_status(con, key) == "unreviewed"
    store.add_review(con, key, "confirm", {})
    assert store.review_status(con, key) == "confirmed"
    store.add_review(con, key, "correct_label", {"target": "wafer", "axis": "zone", "label": "E1"})
    assert store.review_status(con, key) == "corrected"
    store.add_review(con, key, "defer", {"reason_code": "needs_sem_review"})
    assert store.review_status(con, key) == "deferred"



def test_code_fingerprint_changes_with_module_content_not_line_endings(tmp_path):
    from wafer import version
    a = tmp_path / "ring.py"
    a.write_bytes(b"x = 1\n")
    f1 = version.fingerprint([a])
    a.write_bytes(b"x = 1\r\n")                       # CRLF checkout: same code
    assert version.fingerprint([a]) == f1
    a.write_bytes(b"x = 2\n")                         # result-affecting change
    assert version.fingerprint([a]) != f1


def test_provenance_carries_code_and_rule_fingerprints(tmp_path):
    _, o = cli(K / "f01.klf", tmp_path / "w.db", tmp_path)
    p = o["result"]["provenance"]
    assert p["code_version"].startswith("0.1.0-dev+") and len(p["code_version"].split("+")[1]) == 16
    assert len(p["rule_version"]) == 16
