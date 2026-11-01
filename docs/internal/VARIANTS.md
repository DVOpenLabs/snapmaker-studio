# Variant comparison

**Evidence: fixture-tested.** This first version compares two user-selected local
sliced 3MF or G-code files. It does not slice or modify source files.

The view displays byte-backed ArtifactRefs, settings differences, explicit time
and tool-use evidence, and advisory values where a bounded G-code scan can
compute them. Material grams are grouped by logical tool unless a valid complete
foundation topology verifies a direct slot-to-head binding. A selected output
whose bytes change during inspection is marked stale.

Unknown values remain unknown. A truncated G-code scan cannot report tool-change
counts. Waste/tower values stay unknown unless tool use is known. Requirement
results use the foundation capability evaluator; differing ArtifactRef identities
invalidate a shared result and leave it unknown.

The scan reads at most 8 MiB of G-code body. 3MF metadata reads are limited to
2 MiB per recognized settings entry and 2,048 archive entries. The current
parser recognizes a focused set of setting names and the common G-code headers;
other slicer metadata may remain unknown. CI uses synthetic fixtures only.

## Acceptance status

P6 tests 1–10 are implemented as focused pytest cases. A no-write synthetic
fixture smoke check passed for artifact references, tool indexes and changes,
grams, time, waste, and settings. Full test execution remains unverified because
the shared pytest isolation fixture could not create its temp directory in this
environment. UI screenshots are not yet captured.
