# Foundation fixtures

Synthetic, anonymised documents. No real printer, host, path or model names.

Every `*.json` file here was produced from the `to_dict()` output of the matching
`snapstudio_core.foundation` class (topology, material_view, observation, artifact_ref,
derivation, virtual_recipe, capability_set) with fixed timestamps, then frozen. The tests
decode each file with `from_dict` and assert that `to_dict()` returns the same document
(round trip). `unknown_schema_version.json` is hand-written: a future `schema_version`
that must be preserved opaquely and never evaluated.

The desktop (P0b) mirrors parse these same files; do not change them without updating both.
