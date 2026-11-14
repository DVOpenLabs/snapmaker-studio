# Passport fixtures: provenance

Synthetic and hand-written. None of these files is a capture from a real printer, a real
project, a real slicer run or a real third-party tool. Evidence label: **fixture-tested**.

| File | What it is |
|---|---|
| `recipes.json` | Three hand-written `virtual_recipe/1` documents: one usable, one with a schema version this build does not know (reported lost), one that references itself (kept, `execution_supported=false`). Shape follows `snapstudio_core/foundation/recipes.py`. |
| `mappings.json` | Four hand-written material mappings: one complete, one carrying a field that is not retained, one with an invalid slot reference, one duplicate. Provider and spool ids are made up. |

The artifact files used by the tests (original, prepared, sliced stand-ins) are small byte
strings written into a temporary directory by the tests themselves. They are not 3MF or G-code.
