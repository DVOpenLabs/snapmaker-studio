# Variant comparison screenshot evidence

Evidence label: fixture-tested (synthetic G-code fixtures under backend/tests/fixtures/variants, loopback engine, development build). No slicer or printer was involved.

- `compare-two-outputs.png`: two synthetic G-code outputs. Tool changes are labelled computed, time and tower/waste reported, and a missing time or waste value shows Unknown. The layer-height difference comes from the settings both files state.
- `compare-unknown-output.png`: the second file states nothing readable, so its tools, time and waste show Unknown and the settings difference shows an em dash rather than a guess.

Paths are typed as relative names; the engine ran with the fixture folder as its working directory so no local path appears on screen.
