"""YAML profile (plan section 9): validation and loading.

Enabled features need their required keys (else ConfigInvalid / CONFIG_INVALID).
Disabled features may hold nulls and stay 'disabled'. The 100 mm zone radius is
never converted to 101.6 mm."""
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class ConfigInvalid(Exception):
    code = "CONFIG_INVALID"

    def __init__(self, keys, message=""):
        self.keys = list(dict.fromkeys(keys))
        self.message = message
        super().__init__(f"{self.code}: {', '.join(self.keys)}" + (f" ({message})" if message else ""))


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Coordinates(_M):
    adapter_id: Optional[str] = None
    source_units: Optional[str] = None
    target_notch: Literal["DOWN"] = "DOWN"
    target_x: Literal["RIGHT"] = "RIGHT"
    target_y: Literal["UP"] = "UP"
    side_convention: Optional[str] = None
    missing_orientation: Literal["retain_unknown"] = "retain_unknown"   # only supported policy (T-02)


class Coverage(_M):
    source: str = "required_for_density"
    missing_policy: str = "counts_only"


class Clock(_M):
    sector_width_deg: float = 30
    sector_centers_start_deg: float = 0
    center_exclusion_radius_mm: Optional[float] = None  # null -> clock analysis not active
    boundary_tolerance_deg: float = 5.0  # +- deg around sector boundaries (15, 45, ... 345); flag only


class Zone(_M):
    enabled: bool = False
    metric: Literal["distance_from_edge_mm", "radius_mm"] = "distance_from_edge_mm"
    interval_mm: Optional[list[Optional[float]]] = None
    interval_closed: Literal["left"] = "left"


class ZoneBoundary(_M):
    enabled: bool = False
    center_radius_mm: Optional[float] = 100
    band_width_mm: Optional[float] = None


class Zones(_M):
    E1: Zone = Zone()
    E2: Zone = Zone()
    zone_8inch_inside: Zone = Zone(metric="radius_mm", interval_mm=[0, 100])
    zone_8inch_boundary: ZoneBoundary = ZoneBoundary()


class LiftPin(_M):
    enabled: bool = False
    template_id: Optional[str] = None
    frame: Literal["notch_down"] = "notch_down"
    expected_lobes: int = 3
    spacing_deg: float = 120
    radius_band_mm: Optional[list[float]] = None
    phase_deg: Optional[float] = None
    angular_tolerance_deg: Optional[float] = None
    radial_tolerance_mm: Optional[float] = None
    min_support_per_lobe: Optional[int] = None
    min_lobe_contrast: Optional[float] = None   # lobe window density / rest-of-band density
    harmonic_weighting: Literal["equal_per_lobe"] = "equal_per_lobe"
    partial_match: Literal["candidate_only"] = "candidate_only"
    calibrated: bool = False   # False -> threefold match is reported as "candidate" only


class Signatures(_M):
    lift_pin: LiftPin = LiftPin()


class RingRule(_M):
    """Ring/arc classification (TBD.md T-14). No code defaults: thresholds come from a profile
    calibrated on internal labeled data. Enabled with a missing threshold -> CONFIG_INVALID."""
    enabled: bool = False
    occupancy_bin_deg: Optional[float] = None       # angular bin size for occupancy
    ring_min_occupancy: Optional[float] = None      # occupied-bin fraction for a ring
    arc_min_occupancy: Optional[float] = None       # occupied-bin fraction for an arc candidate
    max_relative_thickness: Optional[float] = None  # (P95-P5 thickness) / center radius
    min_points: Optional[int] = None
    calibrated: bool = False                        # False -> only "candidate" is ever reported


class LineRule(_M):
    """Linear-pattern classification (TBD.md T-18). No code defaults; enabled + null -> CONFIG_INVALID."""
    enabled: bool = False
    min_points: Optional[int] = None
    max_relative_width: Optional[float] = None  # (P95-P5 normal distance) / length
    max_gap_ratio: Optional[float] = None       # largest gap along the axis / length (continuity)
    calibrated: bool = False


class Shapes(_M):
    ring: RingRule = RingRule()
    line: LineRule = LineRule()


class Detect(_M):
    """Candidate-detector search parameters (TBD.md T-19). No code defaults; enabled + null -> CONFIG_INVALID."""
    enabled: bool = False
    ring_radial_tol_mm: Optional[float] = None   # ring support = points within +-tol of the densest radius
    line_inlier_mm: Optional[float] = None       # line support = points within this normal distance
    line_ransac_trials: Optional[int] = None


class Stats(_M):
    radial_bin_mm: Optional[float] = None  # null -> radial density not computed (disabled)


class Randomness(_M):
    mode: str = "conditional_monte_carlo"
    null_model_id: Optional[str] = None
    seed: int = 20261009
    nsim: int = 999
    alpha: Optional[float] = None
    block_downstream_on_non_significance: bool = False


class Clustering(_M):
    eps_mm: Optional[float] = None
    min_samples: Optional[int] = None
    retain_noise: bool = True


class BinMapping(_M):
    version: Optional[str] = None
    unknown_policy: str = "preserve"


class EquipmentSignature(_M):
    """Batch-level repeat of a spatial candidate across wafers of the same INSPECTION tool (user decision
    2026-10-12: InspectionStationID, >= 3 wafers, a different StepID never excludes a wafer). A repeat is a
    candidate, not a cause. Tolerances have no code defaults: enabled + null -> CONFIG_INVALID."""
    enabled: bool = False
    equipment_field: Literal["InspectionStationID"] = "InspectionStationID"   # inspection tool, not process tool
    min_wafers: int = 3
    ring_radius_tol_mm: Optional[float] = None      # |center radius difference|
    line_angle_tol_deg: Optional[float] = None      # direction difference (mod 180)
    line_offset_tol_mm: Optional[float] = None      # signed distance of the line from the wafer center
    local_distance_tol_mm: Optional[float] = None   # local cluster centroid distance
    local_min_points: Optional[int] = None          # ignore smaller local clusters (noise specks)


class DefectVolume(_M):
    """Excess defects vs inspection abort (user decision 2026-10-12). A tool stops reporting at its maximum
    reportable defect count (overflow / abort), so reaching inspection_defect_limit is the abort evidence; a high
    count alone is only 'excess, abort unconfirmed'. Both null -> not evaluated. No defaults: tool/recipe values."""
    excess_defect_count: Optional[int] = None       # reported events >= this -> excess_defect
    inspection_defect_limit: Optional[int] = None   # tool/recipe maximum reportable defects


class Profile(_M):
    schema_version: str = "1.0"
    profile_id: str
    units: Literal["mm"] = "mm"
    # not in the plan's section 9 example; needed for the "zone larger than wafer" check
    wafer_radius_mm: Optional[float] = None
    coordinates: Coordinates = Coordinates()
    coverage: Coverage = Coverage()
    clock: Clock = Clock()
    zones: Zones = Zones()
    signatures: Signatures = Signatures()
    shapes: Shapes = Shapes()
    detect: Detect = Detect()
    stats: Stats = Stats()
    randomness: Randomness = Randomness()
    clustering: Clustering = Clustering()
    bin_mapping: BinMapping = BinMapping()
    equipment_signature: EquipmentSignature = EquipmentSignature()
    defect_volume: DefectVolume = DefectVolume()

    def feature_status(self, name):
        """'enabled' or 'disabled' for E1/E2/zone_8inch_inside/zone_8inch_boundary/lift_pin/ring."""
        f = (getattr(self.zones, name, None) or getattr(self.signatures, name, None)
             or getattr(self.shapes, name))
        return "enabled" if f.enabled else "disabled"


def _check(p: Profile):
    bad, msgs = [], []

    def add(key, msg):
        bad.append(key)
        msgs.append(f"{key}: {msg}")

    R = p.wafer_radius_mm
    from .ingest import ADAPTERS
    if p.coordinates.adapter_id not in (None, *ADAPTERS):
        add("coordinates.adapter_id", f"unknown adapter (supported: {', '.join(ADAPTERS)})")
    if R is not None and R <= 0:
        add("wafer_radius_mm", "must be > 0")
    c = p.clock
    if c.sector_width_deg <= 0 or c.sector_width_deg > 360:
        add("clock.sector_width_deg", "must be in (0, 360]")
    if not 0 <= c.boundary_tolerance_deg < c.sector_width_deg / 2:
        add("clock.boundary_tolerance_deg", "must be in [0, sector_width/2)")
    if c.center_exclusion_radius_mm is not None and c.center_exclusion_radius_mm < 0:
        add("clock.center_exclusion_radius_mm", "negative")

    if (c.sector_width_deg, c.sector_centers_start_deg) != (30, 0):
        add("clock.sector_width_deg", "clock sectors are fixed at 30 deg starting at 12 o'clock (CLAUDE.md 4.4)")
    for name in ("E1", "E2"):  # metric is fixed regardless of enabled (user decision 2026-10-09)
        if getattr(p.zones, name).metric != "distance_from_edge_mm":
            add(f"zones.{name}.metric", "must be distance_from_edge_mm (E1/E2 use edge distance)")
    ivals = {}
    for name in ("E1", "E2", "zone_8inch_inside"):
        z = getattr(p.zones, name)
        if not z.enabled:
            continue
        key = f"zones.{name}.interval_mm"
        iv = z.interval_mm
        if iv is None or len(iv) != 2 or any(v is None for v in iv):
            add(key, "required when enabled (two numbers)")
            continue
        lo, hi = iv
        want = "radius_mm" if name == "zone_8inch_inside" else "distance_from_edge_mm"
        if z.metric != want:
            if name == "zone_8inch_inside":
                add(f"zones.{name}.metric", f"must be {want}")
            continue
        if z.metric == "distance_from_edge_mm" and R is None:
            add("wafer_radius_mm", f"required by enabled zones.{name} (distance_from_edge_mm)")
        if lo < 0:
            add(key, "negative bound")
        elif lo >= hi:
            add(key, "inverted or empty interval")
        elif R is not None and hi > R:
            add(key, f"exceeds wafer radius {R}")
        else:
            ivals[name] = (z.metric, lo, hi)
    # same hierarchy = E1/E2 (edge zones). E1 vs 100mm zones are different hierarchies and may overlap.
    if "E1" in ivals and "E2" in ivals:
        (m1, l1, h1), (m2, l2, h2) = ivals["E1"], ivals["E2"]
        if m1 == m2 and l1 < h2 and l2 < h1:
            add("zones.E2.interval_mm", "overlaps zones.E1 (same hierarchy)")

    b = p.zones.zone_8inch_boundary
    if b.enabled:
        if b.center_radius_mm is None:
            add("zones.zone_8inch_boundary.center_radius_mm", "required when enabled")
        if b.band_width_mm is None:
            add("zones.zone_8inch_boundary.band_width_mm", "required when enabled")
        elif b.band_width_mm < 0:
            add("zones.zone_8inch_boundary.band_width_mm", "negative width")
        elif R is not None and b.center_radius_mm is not None and b.center_radius_mm + b.band_width_mm / 2 > R:
            add("zones.zone_8inch_boundary.band_width_mm", f"band exceeds wafer radius {R}")
        if b.center_radius_mm is not None and R is not None and b.center_radius_mm > R:
            add("zones.zone_8inch_boundary.center_radius_mm", f"exceeds wafer radius {R}")

    rr = p.shapes.ring
    if rr.enabled:
        for k in ("occupancy_bin_deg", "ring_min_occupancy", "arc_min_occupancy",
                  "max_relative_thickness", "min_points"):
            if getattr(rr, k) is None:
                add(f"shapes.ring.{k}", "required when enabled")
        if rr.occupancy_bin_deg is not None and not 0 < rr.occupancy_bin_deg <= 360:
            add("shapes.ring.occupancy_bin_deg", "must be in (0, 360]")
        for k in ("ring_min_occupancy", "arc_min_occupancy"):
            v = getattr(rr, k)
            if v is not None and not 0 <= v <= 1:
                add(f"shapes.ring.{k}", "must be in [0, 1]")
        if None not in (rr.ring_min_occupancy, rr.arc_min_occupancy) and rr.arc_min_occupancy > rr.ring_min_occupancy:
            add("shapes.ring.arc_min_occupancy", "must not exceed ring_min_occupancy")
        if rr.max_relative_thickness is not None and rr.max_relative_thickness <= 0:
            add("shapes.ring.max_relative_thickness", "must be > 0")
        if rr.min_points is not None and rr.min_points < 3:
            add("shapes.ring.min_points", "must be >= 3")
    if p.stats.radial_bin_mm is not None and p.stats.radial_bin_mm <= 0:
        add("stats.radial_bin_mm", "must be > 0")
    if p.stats.radial_bin_mm is not None and R is None:
        add("wafer_radius_mm", "required by stats.radial_bin_mm (radial density)")
    if p.randomness.block_downstream_on_non_significance:
        add("randomness.block_downstream_on_non_significance",
            "must be false: randomness tests never gate candidate detection (plan 3/7.2, C07)")
    dt = p.detect
    if dt.enabled:
        for k in ("ring_radial_tol_mm", "line_inlier_mm", "line_ransac_trials"):
            if getattr(dt, k) is None:
                add(f"detect.{k}", "required when enabled")
            elif getattr(dt, k) <= 0:
                add(f"detect.{k}", "must be > 0")
        if p.clustering.eps_mm is None:
            add("clustering.eps_mm", "required by enabled detect (local clusters)")
        elif p.clustering.eps_mm <= 0:
            add("clustering.eps_mm", "must be > 0")
        if p.clustering.min_samples is None:
            add("clustering.min_samples", "required by enabled detect (local clusters)")
        elif p.clustering.min_samples < 1:
            add("clustering.min_samples", "must be >= 1")
    ln = p.shapes.line
    if ln.enabled:
        for k in ("min_points", "max_relative_width", "max_gap_ratio"):
            if getattr(ln, k) is None:
                add(f"shapes.line.{k}", "required when enabled")
        if ln.min_points is not None and ln.min_points < 3:
            add("shapes.line.min_points", "must be >= 3")
        for k in ("max_relative_width", "max_gap_ratio"):
            v = getattr(ln, k)
            if v is not None and v <= 0:
                add(f"shapes.line.{k}", "must be > 0")
    lp = p.signatures.lift_pin
    if lp.enabled:
        for k in ("template_id", "radius_band_mm", "phase_deg", "angular_tolerance_deg",
                  "radial_tolerance_mm", "min_support_per_lobe", "min_lobe_contrast"):
            if getattr(lp, k) is None:
                add(f"signatures.lift_pin.{k}", "required when enabled")
        rb = lp.radius_band_mm
        if rb is not None and (len(rb) != 2 or rb[0] >= rb[1] or rb[0] < 0):
            add("signatures.lift_pin.radius_band_mm", "inverted, empty or negative")
        elif rb is not None and R is not None and rb[1] > R:
            add("signatures.lift_pin.radius_band_mm", f"exceeds wafer radius {R}")
        for k in ("angular_tolerance_deg", "radial_tolerance_mm"):
            v = getattr(lp, k)
            if v is not None and v < 0:
                add(f"signatures.lift_pin.{k}", "negative")
        if lp.expected_lobes != 3:
            add("signatures.lift_pin.expected_lobes", "must be 3 (plan 9)")
        if lp.min_support_per_lobe is not None and lp.min_support_per_lobe < 1:
            add("signatures.lift_pin.min_support_per_lobe", "must be >= 1")
        if lp.min_lobe_contrast is not None and lp.min_lobe_contrast <= 0:
            add("signatures.lift_pin.min_lobe_contrast", "must be > 0")
        if lp.angular_tolerance_deg is not None and lp.angular_tolerance_deg >= lp.spacing_deg / 2:
            add("signatures.lift_pin.angular_tolerance_deg", "must be < spacing_deg / 2 (windows must not overlap)")
    es = p.equipment_signature
    if es.enabled:
        for k in ("ring_radius_tol_mm", "line_angle_tol_deg", "line_offset_tol_mm", "local_distance_tol_mm",
                  "local_min_points"):
            v = getattr(es, k)
            if v is None:
                add(f"equipment_signature.{k}", "required when enabled")
            elif v <= 0:
                add(f"equipment_signature.{k}", "must be > 0")
        if es.min_wafers < 2:
            add("equipment_signature.min_wafers", "must be >= 2 (one wafer cannot show a repeat)")
        if es.line_angle_tol_deg is not None and es.line_angle_tol_deg >= 90:
            add("equipment_signature.line_angle_tol_deg", "must be < 90")
    dv = p.defect_volume
    for k in ("excess_defect_count", "inspection_defect_limit"):
        if getattr(dv, k) is not None and getattr(dv, k) < 1:
            add(f"defect_volume.{k}", "must be >= 1")
    if None not in (dv.excess_defect_count, dv.inspection_defect_limit) and \
            dv.excess_defect_count > dv.inspection_defect_limit:
        add("defect_volume.excess_defect_count", "must not exceed inspection_defect_limit")
    if bad:
        raise ConfigInvalid(bad, "; ".join(msgs))
    return p


def parse_profile(data) -> Profile:
    try:
        p = Profile.model_validate(data)
    except ValidationError as e:
        keys = [".".join(str(s) for s in err["loc"]) for err in e.errors()]
        raise ConfigInvalid(keys, str(e)) from None
    return _check(p)


def load_profile(path) -> Profile:
    with open(path, encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigInvalid(["<yaml>"], f"invalid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ConfigInvalid(["<root>"], "profile must be a mapping")
    return parse_profile(data)


def validate_for_run(p: Profile) -> Profile:
    """Keys the analysis cannot start without (E12: eps missing). A draft profile
    loads fine but is not runnable."""
    bad = [f"clustering.{k}" for k in ("eps_mm", "min_samples") if getattr(p.clustering, k) is None]
    c = p.coordinates
    if c.adapter_id is None:      # explicit adapter required (T-01 decision, plan 16.1)
        bad.append("coordinates.adapter_id")
    if c.adapter_id is not None and c.source_units is None:     # every adapter needs the declared unit
        bad.append("coordinates.source_units")
    if c.adapter_id == "synthetic-die-local-v1" and c.side_convention is None:
        bad.append("coordinates.side_convention")
    if bad:
        raise ConfigInvalid(bad, "required before analysis")
    return p
