# Creative Prepare context

Creative inspection remains source-specific and read-only. After inspection the
same existing setup selector and Project Materials card used by normal Prepare
let the user choose setup/material context. Creative forwards validated optional
topology and explicit selections to the existing convert service; no shared
service, state store, preset picker or provider client is modified.

With no choices the request/service call remains the legacy shape. Invalid or
pending selected setups pause Prepare. Preparing without a setup is a separate
action; material choices use their review flow, and clearing the setup requires
a fresh review. The final response exposes the engine's setup/settings summary,
not an assumption that a selected setup was used. Invalid topology is refused
by the existing core and produces no copy.

Project/format edits invalidate inspections. Changes to output folder, actual
material choices or setup invalidate prepared results. Equivalent empty material
callbacks do not cancel work. Written copies remain accounted for: a valid copy
may still join its unchanged job after navigating away, while the existing job
revision guard prevents an older copy from replacing a newer project/copy.
Written stale/unvalidated copies are reported as unlinked, not silently adopted.

Preset mappings are remembered by the existing card only after the actual engine
reports a validated copy, using the real schema/mode/settings summary. Paths are
kept in the existing local-only output field; no extra file-path response field
is added. Originals remain unchanged.

Regression evidence: synthetic eight-filament project, four physical heads/eight
logical slots, actual route/convert service and saved archive; explicit material
colour/preset choices; invalid setup/no-copy; existing job/Recovery/Passport
continuity suite. Browser proof uses a mock host on loopback and an installed
Generic PLA preset; it is not genuine-device or Orca round-trip evidence.


Review delta is based on PR #144 head 343d90ccedea4bdd6d7ad15a0e0915ef1a8a7deb,
which contains merged #138's not_evaluated outcome. A real-selector regression
covers unknown-origin, material-validation and material-guard refusals: none may
blame a ready setup. A cleanup-contract regression covers a pending material
Prepare while leaving: the material card's unmount [] callback is ignored once the
parent has unmounted, so a valid unchanged job still links its written copy. The
backend tests exercise real material-guard and unproven-preset refusals through
Creative. No shared selector, job, Passport or material-card code is edited here.
