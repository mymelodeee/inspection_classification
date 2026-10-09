"""Strict KLARF reader + SYNTHETIC adapter.

klarfrs 0.2.1 silently drops/shifts records (see TBD.md T-01), so the DefectList is
parsed here and any inconsistency raises KlarfError (INVALID_INPUT). Raw fields are kept.

The adapter only supports the documented synthetic convention (tests/fixtures/klarf/README.md).
Real tool-export coordinate rules are TBD: unsupported header values raise
AdapterUnsupported instead of being guessed.
"""
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_VERSIONS = {"1 2", "1 8"}
INT_COLUMNS = {"DEFECTID", "XINDEX", "YINDEX", "CLASSNUMBER"}
REQUIRED_COLUMNS = ("DEFECTID", "XREL", "YREL", "CLASSNUMBER")


class KlarfError(Exception):
    code = "INVALID_INPUT"


class AdapterUnsupported(KlarfError):
    """Header says the coordinate convention is not one the adapter has verified."""


@dataclass
class Klarf:
    header: dict
    columns: list
    records: list  # list[dict] raw, column name -> float/int (as parsed)
    source_sha256: str
    path: str = ""


def _num(tok, rec_no, col):
    try:
        v = float(tok)
    except ValueError:
        raise KlarfError(f"record {rec_no}: column {col}: not a number")
    if not math.isfinite(v):
        raise KlarfError(f"record {rec_no}: column {col}: not finite")
    if col in INT_COLUMNS and v != int(v):
        raise KlarfError(f"record {rec_no}: column {col}: not an integer")
    return v


def read_klarf(path):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise KlarfError("file is not valid UTF-8 text")
    lines = [ln.strip() for ln in text.splitlines()]

    header, spec, i = {}, None, 0
    while i < len(lines):
        ln = lines[i]
        if ln == "DefectList":
            break
        m = re.match(r"(\w+)\s*(.*?);?$", ln)
        if ln and m:
            key, val = m.group(1), m.group(2)
            if key == "DefectRecordSpec":
                spec = val
            else:
                header[key] = val
        i += 1
    else:
        raise KlarfError("DefectList section not found (truncated or not KLARF)")

    ver = header.get("FileVersion")
    if ver is None:
        raise KlarfError("FileVersion missing")
    if ver not in SUPPORTED_VERSIONS:
        raise KlarfError(f"unsupported FileVersion {ver!r}")
    if spec is None:
        raise KlarfError("DefectRecordSpec missing")
    parts = spec.split()
    if not parts or not parts[0].isdigit() or int(parts[0]) != len(parts) - 1:
        raise KlarfError("DefectRecordSpec count does not match its column list")
    cols = parts[1:]
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise KlarfError(f"required columns missing: {missing}")

    records, closed, eof = [], False, False
    for rec_no, ln in enumerate(lines[i + 1:], start=1):
        if not closed and ln == ";":
            closed = True
            continue
        if closed and ln == "EndOfFile;" and not eof:
            eof = True
            continue
        if closed:
            if ln:
                raise KlarfError(f"unexpected content after DefectList end (multi-wafer/list unsupported, T-12): line {i + 1 + rec_no}")
            continue
        if not ln:
            continue
        if ln.endswith(";"):
            closed = True  # record carrying the list terminator
        toks = ln.rstrip(";").split()
        if len(toks) != len(cols):
            raise KlarfError(f"record {rec_no}: {len(toks)} fields, expected {len(cols)}")
        records.append({c: _num(t, rec_no, c) for c, t in zip(cols, toks)})
    if not closed:
        raise KlarfError("DefectList not terminated (truncated file)")
    return Klarf(header, cols, records, sha, str(path))


def to_standard(k, bin_prefix="B"):
    """SYNTHETIC adapter -> parallel lists (ids, x_mm, y_mm, bins, dies)."""
    h = k.header
    if h.get("CoordinatesMirrored") != "NO":
        raise AdapterUnsupported("CoordinatesMirrored != NO: side/mirror rule is TBD (T-03)")
    if h.get("OrientationMarkLocation") != "DOWN":
        raise AdapterUnsupported("notch != DOWN: rotation rule for this export is TBD (T-03)")
    if h.get("SampleCenterLocation", "").split() != ["0", "0"] or h.get("DieOrigin", "").split() != ["0", "0"]:
        raise AdapterUnsupported("non-zero SampleCenterLocation/DieOrigin: TBD (T-02)")
    ids, xs, ys, bins, dies = [], [], [], [], []
    for rec_no, r in enumerate(k.records, start=1):
        if r.get("XINDEX", 0) != 0 or r.get("YINDEX", 0) != 0:
            raise AdapterUnsupported(f"defect {int(r['DEFECTID'])}: die index != (0,0); die pitch/origin rule is TBD (T-02)")
        ids.append(f"{rec_no}:{int(r['DEFECTID'])}")  # event key = record order + original DEFECTID
        xs.append(r["XREL"] / 1000.0)  # synthetic: um -> mm, single die at wafer center
        ys.append(r["YREL"] / 1000.0)
        n = int(r["CLASSNUMBER"])
        bins.append(None if n == 0 else f"{bin_prefix}{n}")
        dies.append((int(r.get("XINDEX", 0)), int(r.get("YINDEX", 0))))
    return ids, xs, ys, bins, dies
