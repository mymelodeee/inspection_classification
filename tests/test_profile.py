"""Profile tests: plan 9, 16.1, E12, E08 (disabled stays disabled, no 101.6 substitution)."""
import copy
from pathlib import Path

import pytest

from wafer.profile import ConfigInvalid, load_profile, parse_profile, validate_for_run

F01_YAML = Path(__file__).parent / "profiles" / "f01_test_profile.yaml"


def base():
    return {"profile_id": "t", "wafer_radius_mm": 150}


def test_load_f01_test_profile():
    p = load_profile(F01_YAML)
    assert p.wafer_radius_mm == 150
    assert p.clock.center_exclusion_radius_mm == 1
    assert p.zones.E1.interval_mm == [0, 2] and p.zones.E2.interval_mm == [2, 5]
    assert p.zones.zone_8inch_inside.interval_mm == [0, 100]
    assert p.zones.zone_8inch_boundary.center_radius_mm == 100  # not 101.6
    assert p.zones.zone_8inch_boundary.band_width_mm == 2
    assert p.feature_status("lift_pin") == "disabled"
    assert p.feature_status("E1") == "enabled"
    validate_for_run(p)


def test_minimal_profile_all_features_disabled_by_default():
    p = parse_profile(base())
    for f in ("E1", "E2", "zone_8inch_inside", "zone_8inch_boundary", "lift_pin"):
        assert p.feature_status(f) == "disabled"
    assert p.zones.zone_8inch_boundary.center_radius_mm == 100
    assert p.zones.zone_8inch_inside.interval_mm == [0, 100]


def test_draft_profile_loads_but_not_runnable():  # E12: eps missing
    # E12-UP (T-02, approved 2026-10-09): an explicit coordinates.adapter_id is required before analysis.
    # Was ["clustering.eps_mm", "clustering.min_samples"]; the draft also has no adapter_id, so its key is added.
    p = parse_profile(base())
    with pytest.raises(ConfigInvalid) as e:
        validate_for_run(p)
    assert e.value.code == "CONFIG_INVALID"
    assert e.value.keys == ["clustering.eps_mm", "clustering.min_samples", "coordinates.adapter_id"]


def test_e12_up_missing_adapter_id_alone_blocks_the_run():
    """E12-UP (T-02): a profile complete except for adapter_id reports exactly that key."""
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["coordinates"]["adapter_id"] = None
    p = parse_profile(d)                     # loads (draft), but is not runnable
    with pytest.raises(ConfigInvalid) as e:
        validate_for_run(p)
    assert e.value.keys == ["coordinates.adapter_id"]


def test_enabled_E1_missing_interval():  # E12
    d = base() | {"zones": {"E1": {"enabled": True, "interval_mm": None}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.E1.interval_mm"]


def test_same_E1_values_disabled_stays_disabled():  # E12: same null config, disabled
    d = base() | {"zones": {"E1": {"enabled": False, "interval_mm": None}}}
    assert parse_profile(d).feature_status("E1") == "disabled"


def test_inverted_interval():  # E12
    d = base() | {"zones": {"E1": {"enabled": True, "interval_mm": [5, 2]}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.E1.interval_mm"]


def test_inverted_interval_disabled_is_not_error():
    d = base() | {"zones": {"E1": {"enabled": False, "interval_mm": [5, 2]}}}
    assert parse_profile(d).feature_status("E1") == "disabled"


def test_negative_band_width():
    d = base() | {"zones": {"zone_8inch_boundary": {"enabled": True, "band_width_mm": -1}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.zone_8inch_boundary.band_width_mm"]


def test_boundary_enabled_without_width():  # plan 8.3: width undecided -> rule must not be enabled
    d = base() | {"zones": {"zone_8inch_boundary": {"enabled": True}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.zone_8inch_boundary.band_width_mm"]


def test_boundary_disabled_null_width_ok():
    d = base() | {"zones": {"zone_8inch_boundary": {"enabled": False, "band_width_mm": None}}}
    assert parse_profile(d).feature_status("zone_8inch_boundary") == "disabled"


def test_zone_larger_than_wafer():
    d = base() | {"zones": {"E2": {"enabled": True, "interval_mm": [2, 151]}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.E2.interval_mm"]
    # exactly R is allowed
    d["zones"]["E2"]["interval_mm"] = [2, 150]
    parse_profile(d)


def test_inside_zone_larger_than_wafer():
    d = base() | {"wafer_radius_mm": 50,
                  "zones": {"zone_8inch_inside": {"enabled": True, "metric": "radius_mm",
                                                   "interval_mm": [0, 100]}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.zone_8inch_inside.interval_mm"]


def test_same_hierarchy_overlap_E1_E2():  # E12
    d = base() | {"zones": {"E1": {"enabled": True, "interval_mm": [0, 3]},
                             "E2": {"enabled": True, "interval_mm": [2, 5]}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["zones.E2.interval_mm"]


def test_adjacent_E1_E2_half_open_not_overlap():
    d = base() | {"zones": {"E1": {"enabled": True, "interval_mm": [0, 2]},
                             "E2": {"enabled": True, "interval_mm": [2, 5]}}}
    parse_profile(d)


def test_cross_hierarchy_overlap_allowed():  # plan 8.3: E1 vs 100mm zones; inside vs band
    p = load_profile(F01_YAML)  # band [99,101] overlaps inside [0,100)
    assert p.feature_status("zone_8inch_inside") == "enabled"
    assert p.feature_status("zone_8inch_boundary") == "enabled"


def test_lift_pin_enabled_missing_phase():  # E12
    d = base() | {"signatures": {"lift_pin": {
        "enabled": True, "template_id": "x", "radius_band_mm": [55, 65],
        "angular_tolerance_deg": 5, "radial_tolerance_mm": 3, "min_support_per_lobe": 3,
        "min_lobe_contrast": 3}}}  # min_lobe_contrast: required since T-25 (E07-UP)
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == ["signatures.lift_pin.phase_deg"]


def test_lift_pin_enabled_lists_all_missing_keys():
    d = base() | {"signatures": {"lift_pin": {"enabled": True}}}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert e.value.keys == [
        "signatures.lift_pin." + k for k in (
            "template_id", "radius_band_mm", "phase_deg", "angular_tolerance_deg",
            "radial_tolerance_mm", "min_support_per_lobe", "min_lobe_contrast")]  # + T-25 key


def test_lift_pin_disabled_with_nulls_stays_disabled():
    d = base() | {"signatures": {"lift_pin": {"enabled": False, "phase_deg": None}}}
    assert parse_profile(d).feature_status("lift_pin") == "disabled"


def test_lift_pin_fully_specified_enabled():
    d = base() | {"signatures": {"lift_pin": {
        "enabled": True, "template_id": "t", "radius_band_mm": [55, 65], "phase_deg": 0,
        "angular_tolerance_deg": 5, "radial_tolerance_mm": 3, "min_support_per_lobe": 3,
        "min_lobe_contrast": 3}}}
    p = parse_profile(d)
    assert p.feature_status("lift_pin") == "enabled" and p.signatures.lift_pin.phase_deg == 0


def test_unknown_key_and_wrong_type_are_config_invalid():
    with pytest.raises(ConfigInvalid):
        parse_profile(base() | {"zonez": {}})
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(base() | {"clustering": {"eps_mm": "abc"}})
    assert e.value.keys == ["clustering.eps_mm"]


def test_non_mm_units_rejected():
    with pytest.raises(ConfigInvalid):
        parse_profile(base() | {"units": "inch"})


def test_100mm_never_converted(tmp_path):
    d = copy.deepcopy(base()) | {"zones": {"zone_8inch_boundary": {"enabled": True, "band_width_mm": 2}}}
    p = parse_profile(d)
    assert p.zones.zone_8inch_boundary.center_radius_mm == 100
    assert p.zones.zone_8inch_boundary.center_radius_mm != 101.6


def test_non_mapping_yaml(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigInvalid):
        load_profile(f)


def test_edge_metric_zone_without_wafer_radius_is_config_invalid():
    import yaml
    d = yaml.safe_load(open(Path(__file__).parent / "profiles/f01_test_profile.yaml", encoding="utf-8"))
    d["wafer_radius_mm"] = None
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "wafer_radius_mm" in e.value.keys


def test_clock_sector_definition_is_fixed():
    import yaml
    d = yaml.safe_load(open(Path(__file__).parent / "profiles/f01_test_profile.yaml", encoding="utf-8"))
    d["clock"]["sector_width_deg"] = 15
    with pytest.raises(ConfigInvalid):
        parse_profile(d)


def test_e1_must_use_edge_distance_metric():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["zones"]["E1"]["metric"] = "radius_mm"
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "zones.E1.metric" in e.value.keys


def test_disabled_e1_with_wrong_metric_is_still_config_invalid():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["zones"]["E1"]["enabled"] = False
    d["zones"]["E1"]["metric"] = "radius_mm"
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "zones.E1.metric" in e.value.keys


@pytest.mark.parametrize("bad", [-1.0, 15.0, 20.0])
def test_boundary_tolerance_must_be_below_half_sector(bad):
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["clock"]["boundary_tolerance_deg"] = bad
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "clock.boundary_tolerance_deg" in e.value.keys


def test_enabled_ring_rule_with_missing_threshold_is_config_invalid_but_disabled_is_not():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["shapes"]["ring"]["max_relative_thickness"] = None
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "shapes.ring.max_relative_thickness" in e.value.keys
    d["shapes"]["ring"]["enabled"] = False
    assert parse_profile(d).feature_status("ring") == "disabled"


def test_ring_rule_value_ranges():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["shapes"]["ring"]["arc_min_occupancy"] = 0.9   # above ring_min_occupancy 0.8
    with pytest.raises(ConfigInvalid):
        parse_profile(d)


def test_enabled_line_rule_with_missing_threshold_is_config_invalid():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["shapes"]["line"]["max_gap_ratio"] = None
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "shapes.line.max_gap_ratio" in e.value.keys
    d["shapes"]["line"]["enabled"] = False
    assert parse_profile(d).feature_status("line") == "disabled"


def test_enabled_detect_with_missing_parameter_is_config_invalid():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["detect"]["line_inlier_mm"] = None
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "detect.line_inlier_mm" in e.value.keys
    d["detect"]["enabled"] = False
    parse_profile(d)


@pytest.mark.parametrize("key,val", [("eps_mm", 0), ("eps_mm", -1), ("min_samples", 0)])
def test_enabled_detect_requires_valid_clustering_values(key, val):
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["clustering"][key] = val
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert f"clustering.{key}" in e.value.keys


def test_radial_density_requires_wafer_radius_e12_up():
    """E12-UP: enabled radial density without wafer_radius_mm is a config error, not insufficient_data."""
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["wafer_radius_mm"] = None
    for z in ("E1", "E2"):
        d["zones"][z]["enabled"] = False
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "wafer_radius_mm" in e.value.keys


def test_blocking_on_non_significance_is_rejected_c07():
    import yaml
    d = yaml.safe_load(open(F01_YAML, encoding="utf-8"))
    d["randomness"] = {"block_downstream_on_non_significance": True}
    with pytest.raises(ConfigInvalid) as e:
        parse_profile(d)
    assert "randomness.block_downstream_on_non_significance" in e.value.keys
