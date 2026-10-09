"""Strict KLARF reader + SYNTHETIC adapter.

klarfrs 0.2.1 silently drops/shifts records (see TBD.md T-01), so the DefectList is
parsed here and any inconsistency raises KlarfError (INVALID_INPUT). Raw fields are kept.

Two syntaxes are read strictly: the flat 1.2-style list (tests/fixtures/klarf) and the KLARF 1.8
Record/Field/List syntax (klarf_dummy_data). Two SYNTHETIC adapters exist, selected explicitly by
profile coordinates.adapter_id; neither is a real tool-export rule (TBD T-02/T-03). Unsupported header
values raise AdapterUnsupported instead of being guessed.
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


_FIELD = re.compile(r'^Field\s+(\w+)\s+(\d+)\s*\{(.*)\}$')
_COLUMNS = re.compile(r'^Columns\s+(\d+)\s*\{(.*)\}$')


def _values(body):
    vals = [v.strip() for v in body.split(",")] if body.strip() else []
    return [v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v for v in vals]


def _read_18(lines, sha, path):
    """Strict KLARF 1.8 Record/List reader: one FileRecord > LotRecord > WaferRecord with one DefectList.
    Declared counts (Field n, Columns n, Data n) must match what is read; braces must balance."""
    m = re.match(r'^Record\s+FileRecord\s+"([^"]*)"$', lines[0])
    if not m:
        raise KlarfError("line 1: expected Record FileRecord \"<version>\"")
    if m.group(1) != "1.8":
        raise KlarfError(f"unsupported FileVersion {m.group(1)!r}")
    header = {"FileVersion": "1 8"}
    depth, wafers, cols, records, data_left, eof = 0, 0, None, [], None, False
    in_list, data_seen = False, False
    for n, ln in enumerate(lines, start=1):
        if not ln:
            continue
        if eof:
            raise KlarfError(f"line {n}: content after EndOfFile")
        if data_left is not None and ln not in ("{", "}"):   # inside Data { ... }
            if not ln.endswith(";"):
                raise KlarfError(f"line {n}: data row not terminated by ';'")
            toks = ln[:-1].split()
            if len(toks) != len(cols):
                raise KlarfError(f"record {len(records) + 1}: {len(toks)} fields, expected {len(cols)}")
            records.append({c: _num(t, len(records) + 1, c) for c, t in zip(cols, toks)})
            continue
        if ln == "{":
            depth += 1
        elif ln == "}":
            depth -= 1
            if data_left is not None:
                if len(records) != data_left:
                    raise KlarfError(f"Data declares {data_left} rows, read {len(records)}")
                data_left = None
            if depth < 0:
                raise KlarfError(f"line {n}: unbalanced braces")
        elif ln == "EndOfFile;":
            if depth != 0:
                raise KlarfError("EndOfFile before all records are closed (truncated)")
            eof = True
        elif ln.startswith("Record "):
            if ln.startswith("Record WaferRecord"):
                wafers += 1
                if wafers > 1:
                    raise KlarfError("more than one WaferRecord: multi-wafer files unsupported (T-12)")
        elif ln.startswith("Field "):
            f = _FIELD.match(ln)
            if not f:
                raise KlarfError(f"line {n}: malformed Field")
            vals = _values(f.group(3))
            if len(vals) != int(f.group(2)):
                raise KlarfError(f"line {n}: Field {f.group(1)} declares {f.group(2)} values, has {len(vals)}")
            if f.group(1) in header:
                raise KlarfError(f"line {n}: duplicate Field {f.group(1)} (would overwrite silently)")
            header[f.group(1)] = " ".join(vals)
        elif ln.startswith("List "):
            if ln.split()[1] != "DefectList" or cols is not None:
                raise KlarfError(f"line {n}: only one DefectList is supported")
            in_list = True
        elif ln.startswith("Columns ") and in_list:
            if cols is not None:
                raise KlarfError(f"line {n}: second Columns statement")
            c = _COLUMNS.match(ln)
            if not c:
                raise KlarfError(f"line {n}: malformed Columns")
            specs = [v.split() for v in c.group(2).split(",")]
            if len(specs) != int(c.group(1)) or any(len(sp) != 2 for sp in specs):
                raise KlarfError(f"line {n}: Columns count does not match its list")
            cols = [sp[1] for sp in specs]
            missing = [x for x in REQUIRED_COLUMNS if x not in cols]
            if missing:
                raise KlarfError(f"required columns missing: {missing}")
        elif ln.startswith("Data ") and cols is not None:
            if data_seen:
                raise KlarfError(f"line {n}: second Data block")
            data_seen = True
            parts = ln.split()
            if len(parts) != 2 or not parts[1].isdigit():
                raise KlarfError(f"line {n}: malformed Data")
            data_left = int(parts[1])
            nxt = next((x for x in lines[n:] if x), None)
            if nxt != "{":
                raise KlarfError(f"line {n}: Data must be followed by '{{'")
        else:
            raise KlarfError(f"line {n}: unrecognized KLARF 1.8 statement")
    if not eof:
        raise KlarfError("EndOfFile missing (truncated file)")
    if wafers != 1 or cols is None or not data_seen:
        raise KlarfError("no WaferRecord with a DefectList and Data block")
    return Klarf(header, cols, records, sha, str(path))


def read_klarf(path):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise KlarfError("file is not valid UTF-8 text")
    lines = [ln.strip() for ln in text.splitlines()]
    first = next((ln for ln in lines if ln), "")
    if first.startswith("Record "):
        return _read_18(lines[lines.index(first):], sha, path)

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


def to_standard(k, coords=None):
    """SYNTHETIC adapter 'synthetic-um-die00-notch-down' -> (orientation, (ids, x_mm, y_mm, bins, dies)).
    Notch absent -> orientation 'unknown' (coordinates kept, clock withheld downstream); a notch other
    than DOWN is a convention this adapter has not verified -> AdapterUnsupported."""
    h = k.header
    if coords is not None and coords.source_units != "um":
        raise AdapterUnsupported("synthetic-um-die00-notch-down reads XREL/YREL as um; profile source_units must be um")
    if h.get("CoordinatesMirrored") != "NO":
        raise AdapterUnsupported("CoordinatesMirrored != NO: side/mirror rule is TBD (T-03)")
    notch = h.get("OrientationMarkLocation")
    if notch not in (None, "DOWN"):
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
        bins.append(bin_label(r["CLASSNUMBER"]))
        dies.append((int(r.get("XINDEX", 0)), int(r.get("YINDEX", 0))))
    return ("notch_registered" if notch == "DOWN" else "unknown"), (ids, xs, ys, bins, dies)


def bin_label(classnumber):
    """Single bin naming for every adapter (T-04 decision): the CLASSNUMBER value as text; 0 -> unknown."""
    n = int(classnumber)
    return None if n == 0 else str(n)


ADAPTERS = ("synthetic-um-die00-notch-down", "synthetic-die-local-v1")


def to_standard_die_local(k, coords):
    """SYNTHETIC adapter 'synthetic-die-local-v1' (klarf_dummy_data/synthetic_profile.json):
    raw_mm = (die_index * pitch + rel_um - sample_center_um) / 1000, front side, +X right / +Y up,
    then ONE clockwise rotation from the file's notch position to notch-down. Not a real tool rule."""
    h = k.header
    if coords.source_units != "um" or coords.side_convention != "front":
        raise AdapterUnsupported("synthetic-die-local-v1 needs profile coordinates.source_units=um and side_convention=front")
    try:
        px, py = (float(v) for v in h["DiePitch"].split())
        cx, cy = (float(v) for v in h["SampleCenterLocation"].split())
    except (KeyError, ValueError):
        raise AdapterUnsupported("DiePitch / SampleCenterLocation missing or malformed (T-02)")
    notch = h.get("OrientationMarkLocation")   # absent -> orientation unknown, partial results (16.1)
    if h.get("DieOrigin", "").split() != ["0", "0"]:
        raise AdapterUnsupported("non-zero DieOrigin: rule is TBD (T-02)")
    if not all(math.isfinite(v) for v in (px, py, cx, cy)) or px <= 0 or py <= 0:
        raise AdapterUnsupported("DiePitch must be finite and > 0, SampleCenterLocation finite")
    if h.get("CoordinatesMirrored", "NO") != "NO":
        raise AdapterUnsupported("CoordinatesMirrored present and not NO: side/mirror rule is TBD (T-03)")
    mark = h.get("SampleOrientationMarkType")
    if (notch is not None or mark is not None) and mark != "NOTCH":   # a flat mark is not this contract
        raise AdapterUnsupported("SampleOrientationMarkType must be NOTCH for synthetic-die-local-v1 (T-03)")
    if notch is not None and notch not in ("DOWN", "UP", "LEFT", "RIGHT"):
        raise AdapterUnsupported(f"notch {notch!r} not supported (T-03)")
    for col in ("XINDEX", "YINDEX"):
        if col not in k.columns:
            raise AdapterUnsupported(f"{col} column required by synthetic-die-local-v1")
    ids, rx, ry, bins, dies = [], [], [], [], []
    for rec_no, r in enumerate(k.records, start=1):
        if not (0 <= r["XREL"] < px and 0 <= r["YREL"] < py):   # die-local offsets by this contract
            raise AdapterUnsupported(f"record {rec_no}: XREL/YREL outside [0, DiePitch): not die-local coordinates")
        ids.append(f"{rec_no}:{int(r['DEFECTID'])}")
        rx.append((r["XINDEX"] * px + r["XREL"] - cx) / 1000.0)
        ry.append((r["YINDEX"] * py + r["YREL"] - cy) / 1000.0)
        bins.append(bin_label(r["CLASSNUMBER"]))
        dies.append((int(r["XINDEX"]), int(r["YINDEX"])))
    if notch is None:   # unit and center are verified, orientation is not: no rotation is guessed
        return "unknown", (ids, rx, ry, bins, dies)
    from .geometry import rotate_notch_to_down   # single rotation; already-normalized exports are not this adapter
    xs, ys = rotate_notch_to_down(rx, ry, notch)
    return "notch_registered", (ids, [float(v) for v in xs], [float(v) for v in ys], bins, dies)


def standardize(k, coords):
    """Dispatch on the explicit profile adapter id (required, T-02) -> (adapter_id, orientation, columns)."""
    aid = coords.adapter_id
    if aid == "synthetic-um-die00-notch-down":
        return (aid, *to_standard(k, coords))
    if aid == "synthetic-die-local-v1":
        return (aid, *to_standard_die_local(k, coords))
    raise AdapterUnsupported(f"unknown or missing adapter_id {aid!r}")
