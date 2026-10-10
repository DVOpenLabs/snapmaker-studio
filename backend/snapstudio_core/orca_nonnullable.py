r"""Options Snapmaker Orca 2.4.0 declares as non-nullable vectors.

Orca loads a per-part `<metadata key=... value=...>` into the part's config. A vector
option that was declared with plain `add()` (not `add_nullable()`) throws
"Deserializing nil into a non-nullable object" on a `nil` entry, and the whole project
fails to load (Config.hpp, ConfigOptionVector deserialize):
https://github.com/Snapmaker/OrcaSlicer/blob/b1831e5dcb464172de33783142425aafda834fbc/src/libslic3r/Config.hpp#L665-L675

DERIVED, not hand-listed: every `this->add("<key>", coFloats | coInts | coPercents |
coFloatsOrPercents | coBools)` in PrintConfig.cpp at Snapmaker/OrcaSlicer commit
b1831e5dcb464172de33783142425aafda834fbc (v2.4.0):
https://github.com/Snapmaker/OrcaSlicer/blob/b1831e5dcb464172de33783142425aafda834fbc/src/libslic3r/PrintConfig.cpp
The only `add_nullable()` use is the `filament_<retraction option>` loop
(PrintConfig.cpp L6465-L6500); those keys are not in this set and may carry `nil`.
Regenerate with:
  grep -oE 'add\("[a-z0-9_]+",\s*co(Floats|Ints|Percents|FloatsOrPercents|Bools)\)' PrintConfig.cpp
"""
from __future__ import annotations

NON_NULLABLE_VECTORS = frozenset({
    "accel_to_decel_enable", "accel_to_decel_factor", "activate_air_filtration",
    "activate_chamber_temp_control", "adaptive_pressure_advance",
    "adaptive_pressure_advance_bridges", "adaptive_pressure_advance_overhangs",
    "additional_cooling_fan_speed", "bridge_acceleration", "bridge_speed",
    "chamber_temperature", "clone_objects", "close_fan_the_first_x_layers",
    "complete_print_exhaust_fan_speed", "cool_plate_temp",
    "cool_plate_temp_initial_layer", "default_acceleration", "default_jerk",
    "default_junction_deviation", "deretraction_speed", "dont_slow_down_outer_wall",
    "during_print_exhaust_fan_speed", "e_position", "e_restart_extra", "e_retracted",
    "enable_overhang_bridge_fan", "enable_overhang_speed", "enable_pressure_advance",
    "eng_plate_temp", "eng_plate_temp_initial_layer", "extruded_volume",
    "extruded_weight", "extrusion_rate_smoothing_external_perimeter_only",
    "fan_cooling_layer_time", "fan_max_speed", "fan_min_speed", "filament_colour_mode",
    "filament_cooling_final_speed", "filament_cooling_initial_speed",
    "filament_cooling_moves", "filament_cost", "filament_density", "filament_diameter",
    "filament_flow_ratio", "filament_flow_step_size", "filament_is_high_temperature",
    "filament_is_support", "filament_loading_speed", "filament_loading_speed_start",
    "filament_max_volumetric_speed", "filament_minimal_purge_on_wipe_tower",
    "filament_multitool_ramming", "filament_multitool_ramming_flow",
    "filament_multitool_ramming_volume", "filament_shrink",
    "filament_shrinkage_compensation_z", "filament_soluble",
    "filament_stamping_distance", "filament_stamping_loading_speed",
    "filament_toolchange_delay", "filament_tower_ironing_area",
    "filament_unloading_speed", "filament_unloading_speed_start",
    "first_layer_print_max", "first_layer_print_min", "first_layer_print_sequence",
    "first_layer_print_size", "flush_volumes_matrix", "flush_volumes_vector",
    "full_fan_speed_layer", "gap_infill_speed", "graphic_effect_plate_temp",
    "graphic_effect_plate_temp_initial_layer", "hot_plate_temp",
    "hot_plate_temp_initial_layer", "idle_temperature", "infill_jerk",
    "initial_layer_acceleration", "initial_layer_infill_speed", "initial_layer_jerk",
    "initial_layer_speed", "initial_layer_travel_speed", "inner_wall_acceleration",
    "inner_wall_jerk", "inner_wall_speed", "internal_bridge_fan_speed",
    "internal_bridge_speed", "internal_solid_infill_acceleration",
    "internal_solid_infill_speed", "ironing_fan_speed", "ironing_speed",
    "is_extruder_used", "load_filament_ids", "long_retractions_when_cut",
    "machine_max_acceleration_extruding", "machine_max_acceleration_retracting",
    "machine_max_acceleration_travel", "machine_max_junction_deviation",
    "machine_min_extruding_rate", "machine_min_travel_rate", "material_correction",
    "max_layer_height", "max_volumetric_extrusion_rate_slope",
    "max_volumetric_extrusion_rate_slope_segment_length", "min_layer_height",
    "nozzle_diameter", "nozzle_temperature", "nozzle_temperature_initial_layer",
    "nozzle_temperature_range_high", "nozzle_temperature_range_low",
    "other_layers_print_sequence", "outer_wall_acceleration", "outer_wall_jerk",
    "outer_wall_speed", "overhang_1_4_speed", "overhang_2_4_speed",
    "overhang_3_4_speed", "overhang_4_4_speed", "overhang_fan_speed",
    "pellet_flow_coefficient", "position", "pressure_advance", "print_bed_max",
    "print_bed_min", "print_bed_size", "reduce_fan_stop_start_freq",
    "relative_correction", "retract_before_wipe", "retract_length_toolchange",
    "retract_lift_above", "retract_lift_below", "retract_restart_extra",
    "retract_restart_extra_toolchange", "retract_when_changing_layer",
    "retraction_distances_when_cut", "retraction_length", "retraction_minimum_travel",
    "retraction_speed", "skip_objects", "slow_down_for_layer_cooling",
    "slow_down_layer_time", "slow_down_layers", "slow_down_min_speed",
    "slowdown_for_curled_perimeters", "small_perimeter_speed",
    "small_perimeter_threshold", "sparse_infill_acceleration", "sparse_infill_speed",
    "supertack_plate_temp", "supertack_plate_temp_initial_layer",
    "support_interface_speed", "support_material_interface_fan_speed", "support_speed",
    "temperature_vitrification", "textured_cool_plate_temp",
    "textured_cool_plate_temp_initial_layer", "textured_plate_temp",
    "textured_plate_temp_initial_layer", "top_surface_acceleration", "top_surface_jerk",
    "top_surface_speed", "travel_acceleration", "travel_jerk", "travel_slope",
    "travel_speed", "wipe", "wipe_distance", "wipe_tower_x", "wipe_tower_y",
    "wiping_volumes_extruders", "z_hop", "z_hop_when_prime"
})
