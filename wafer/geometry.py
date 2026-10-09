"""Pure geometry helpers in the standard frame (mm, origin at wafer center,
+X right, +Y up, notch at 6 o'clock). Vectorized over numpy arrays; scalars work too."""
import numpy as np

# notch direction in the SOURCE frame -> map (x, y) so the notch ends up DOWN
_NOTCH_ROTATION = {
    "DOWN": lambda x, y: (x, y),
    "UP": lambda x, y: (-x, -y),    # rotate 180 deg
    "LEFT": lambda x, y: (-y, x),   # rotate +90 deg (CCW): (-1,0) -> (0,-1)
    "RIGHT": lambda x, y: (y, -x),  # rotate -90 deg (CW):  (1,0)  -> (0,-1)
}
_UNIT_TO_MM = {"mm": 1.0, "um": 1e-3}


def r_mm(x, y):
    return np.hypot(np.asarray(x, dtype=float), np.asarray(y, dtype=float))


def theta_clock_deg(x, y):
    """0=12h, 90=3h, 180=6h, 270=9h; result in [0, 360)."""
    t = np.degrees(np.arctan2(np.asarray(x, dtype=float), np.asarray(y, dtype=float))) % 360.0
    return np.where(t >= 360.0, 0.0, t)  # guards (-1e-18) % 360 == 360.0


def sector_index(theta_deg, sector_width_deg=30.0, start_deg=0.0):
    """Sector k is centered on start_deg + k*width and covers [center-w/2, center+w/2).
    Default: index 0 = 12h (345..15), 1 = 1h (15..45), ..."""
    t = np.asarray(theta_deg, dtype=float)
    n = int(round(360.0 / sector_width_deg))
    idx = np.floor(((t - start_deg + sector_width_deg / 2.0) % 360.0) / sector_width_deg)
    return idx.astype(int) % n


def boundary_distance_deg(theta_deg, sector_width_deg=30.0, start_deg=0.0):
    """Angular distance (deg) from each angle to the nearest sector boundary (boundaries at
    start + w/2 + k*w, i.e. 15, 45, ... 345 by default)."""
    t = np.asarray(theta_deg, dtype=float)
    d = (t - start_deg - sector_width_deg / 2.0) % sector_width_deg
    return np.minimum(d, sector_width_deg - d)


def near_sector_boundary(theta_deg, tol_deg, sector_width_deg=30.0, start_deg=0.0):
    """True where the angle lies within +-tol_deg of a sector boundary (angle uncertainty flag).
    Flag only: the sector assignment itself is never changed, so counts are conserved."""
    return boundary_distance_deg(theta_deg, sector_width_deg, start_deg) <= tol_deg + 1e-9


def neighbor_hour(theta_deg, tol_deg):
    """Clock hour (1..12) of the adjacent sector for angles within +-tol_deg of a sector boundary,
    0 elsewhere. A point near a boundary therefore belongs to its own sector AND this neighbor in
    tolerant counts. Same predicate as near_sector_boundary. Hard-wired to the 12 default 30-degree
    sectors; profile validation rejects any other clock definition. Valid for tol_deg < 15
    (at >= 15 a point is within tol of both boundaries but only the lower neighbor is reported)."""
    t = np.asarray(theta_deg, dtype=float)
    w = 30.0
    idx = sector_index(t)
    offset = (t + w / 2.0) % w                      # position inside the sector, 0 = lower edge
    near_lo = offset <= tol_deg + 1e-9
    near_hi = (w - offset) <= tol_deg + 1e-9
    nb = np.where(near_lo, (idx - 1) % 12, np.where(near_hi, (idx + 1) % 12, -1))
    return np.where(nb < 0, 0, np.where(nb == 0, 12, nb))


def clock_hour(theta_deg):
    """1..12 clock hour for the default 12 sectors (index 0 -> 12)."""
    idx = sector_index(theta_deg)
    return np.where(idx == 0, 12, idx)


def is_center(r, center_exclusion_radius_mm):
    return np.asarray(r, dtype=float) < center_exclusion_radius_mm


def edge_distance_mm(r, wafer_radius_mm):
    return wafer_radius_mm - np.asarray(r, dtype=float)


def in_wafer(r, wafer_radius_mm, tol_mm=0.0):
    """r <= R + tol. Points are never clipped or snapped."""
    return np.asarray(r, dtype=float) <= wafer_radius_mm + tol_mm


def in_interval(v, lo, hi):
    """Half-open [lo, hi)."""
    v = np.asarray(v, dtype=float)
    return (v >= lo) & (v < hi)


def in_band(r, center_mm, width_mm):
    """|r - c| <= w/2, both ends inclusive."""
    return np.abs(np.asarray(r, dtype=float) - center_mm) <= width_mm / 2.0


def rotate_notch_to_down(x, y, source_notch, already_normalized=False):
    """Rotate points so the notch moves from source_notch to DOWN.
    already_normalized=True means the export is already notch-DOWN: no rotation
    is applied (prevents double rotation). Returns (x, y) as new arrays."""
    key = str(source_notch).upper()
    if key not in _NOTCH_ROTATION:
        raise ValueError(f"unknown notch direction: {source_notch!r}")
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if already_normalized:
        return x.copy(), y.copy()
    return _NOTCH_ROTATION[key](x, y)


def to_mm(values, source_units):
    if source_units not in _UNIT_TO_MM:
        raise ValueError(f"unsupported source unit: {source_units!r}")
    return np.asarray(values, dtype=float) * _UNIT_TO_MM[source_units]
