"""Object-spacing / collision honesty for the readiness model.

Studio does NOT yet faithfully resolve object-to-object placement for Bambu
instanced / multi-part 3MF layouts: source_object_id mesh reuse, per-part
matrices, and assemble-vs-build coordinate semantics are not implemented. So
Studio cannot tell whether objects on a plate are too close or colliding.

A wrong collision guess is worse than admitting we don't know — an earlier
bounding-box attempt mis-placed instanced objects (it flagged the wrong objects
and missed the real Orca-reported collision), so it is intentionally NOT shipped.
Instead we report an honest status that callers use to avoid any "ready / no
issues / collision-free" wording. Real, Orca-equivalent collision detection is
deferred to a later release.
"""
from __future__ import annotations

SPACING_MESSAGE = (
    "Object spacing / collisions are not verified by Studio yet — open in "
    "Snapmaker Orca and check for too-close / collision warnings before slicing."
)


def assess_spacing(object_count: int | None, is_stl: bool) -> dict:
    """Honest object-spacing status (pure; no geometry — Studio does not verify it).

    - STL is wrapped into a fresh single-object project — nothing to collide with.
    - A single-object 3MF cannot collide with other objects.
    - Any multi-object 3MF, and any 3MF whose object count is unknown (None or 0),
      is 'unknown': spacing is not checked and must be verified in Snapmaker Orca.

    Returns {"status": "pass" | "unknown", "messages": [...]}.
    """
    if is_stl or object_count == 1:
        return {"status": "pass", "messages": []}
    return {"status": "unknown", "messages": [SPACING_MESSAGE]}
