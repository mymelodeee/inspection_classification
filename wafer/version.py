"""Code fingerprints recorded in provenance and used in the analysis key (plan 16.4, TBD T-24).

A content hash of the modules that can change a result replaces a hand-bumped version string, so a
code change can never reuse a stored result silently. Line endings are normalized so a CRLF/LF
checkout does not change the hash. The UI (app.py) does not affect results and is excluded.
"""
import hashlib
from pathlib import Path

BASE_VERSION = "0.1.0-dev"
PKG = Path(__file__).resolve().parent
RULE_MODULES = ("ring.py", "line.py", "lift_pin.py", "detect.py", "groups.py", "clustering.py")
EXCLUDED = ("app.py",)


def fingerprint(paths):
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda q: Path(q).name):
        h.update(Path(p).name.encode())
        h.update(Path(p).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def code_version():
    return f"{BASE_VERSION}+{fingerprint(p for p in PKG.glob('*.py') if p.name not in EXCLUDED)}"


def rule_version():
    return fingerprint(PKG / m for m in RULE_MODULES)
