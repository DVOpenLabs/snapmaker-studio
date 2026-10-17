from __future__ import annotations
import json
from importlib.resources import files
from .preserve import CATEGORY_A

# never overwrite per-design / per-filament data during a profile swap
_PROTECTED_PREFIXES = ("filament_colour", "filament_type", "filament_settings_id")

# Where the prime tower sits is placement, not tuning: the profile's value is a constant written for no
# particular model, so a project that states its own position keeps it (Studio never moves a tower).
_PLACEMENT_KEYS = frozenset({"wipe_tower_x", "wipe_tower_y"})


# The tower's shape settings Studio writes from the starter profile. Orca resets an undeclared value to its
# own preset, so Recommended declares these (and only these) so the values it lists are the ones Orca opens with.
TOWER_SHAPE_KEYS = frozenset({"wipe_tower_wall_type", "wipe_tower_extra_spacing",
                              "wipe_tower_extra_rib_length", "wipe_tower_cone_angle"})


def tower_shape_keys(profile: dict) -> set[str]:
    """Tower-shape keys the starter profile writes, for Recommended to declare.

    Taken from the profile, not from the changed-values report: a source that already equals the starter
    still needs the declaration, or Orca resets the value to its preset."""
    return TOWER_SHAPE_KEYS & set(profile["keys"])


# Written from the starter, but Studio has not verified that Orca takes them from the project file.
UNVERIFIED_KEYS = {"z_hop_when_prime": (
    "Studio wrote the U1 value; whether Snapmaker Orca applies it from the project file is unverified")}


def kept_placement_keys(cfg: dict, profile: dict) -> set[str]:
    """Placement keys the project states itself that differ from the profile's constant."""
    return {k for k in _PLACEMENT_KEYS
            if cfg.get(k) not in (None, "", []) and k in profile["keys"] and cfg.get(k) != profile["keys"][k]}


def load_profile(name: str) -> dict:
    return json.loads((files("snapstudio_core.data.profiles") / f"{name}.json").read_text("utf-8"))

def apply_swap(cfg: dict, profile: dict, *, preserve_creator_settings: bool = False) -> list[dict]:
    """Apply U1 profile-owned settings.

    Preserve mode intentionally leaves category-A creator settings alone; the
    bundled policy is the single source of truth for that boundary.
    """
    changes = []
    for k, v in profile["keys"].items():
        if k.startswith(_PROTECTED_PREFIXES):
            continue
        if preserve_creator_settings and k in CATEGORY_A:
            continue
        if k in _PLACEMENT_KEYS and cfg.get(k) not in (None, "", []):
            continue
        if cfg.get(k) != v:
            changes.append({"key": k, "old": cfg.get(k), "new": v,
                            "reason": UNVERIFIED_KEYS.get(k, "U1 machine profile setting applied")})
            cfg[k] = v
    return changes
