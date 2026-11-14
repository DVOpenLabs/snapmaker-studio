# Topology-aware core wiring

Evidence label: **fixture-tested**.

The core now accepts a decoded printer topology in preflight and firmware
capability interpretation. Preflight evaluates each project's logical material
slot against feeder lanes and physical heads. Its result distinguishes a
supported assignment, a reported contention, and incomplete reach or head
information. Firmware capability details report physical toolheads separately
from feeder lanes. When no valid topology is supplied, both functions retain
their previous behavior.

Preserved per-slot vectors are handled by setting scope (see "Setting scopes" below), not by length.
G-code facts keep the existing `slot_count`, report a separately supplied FOrcaSlicer physical nozzle vector,
and leave physical head count unknown when a longer nozzle vector may be indexed per filament.

`color_plan` is unchanged. Using several materials at once needs physical heads, so
color planning continues to use the physical-head model rather than treating
feeder lanes as independent print heads. A test compares the file with the
committed bytes.

What "assignable" means here. The preflight check asks whether each project
material has a feeder lane that reaches a physical toolhead over the course of
the job. Lanes that share a toolhead take turns at tool changes, so eight
materials on four toolheads with eight lanes is reported as a fit, and the text
names four physical toolheads and eight feeder lanes. It never reports eight
toolheads. If a material count was not measured, the check is unknown, not a
fit for zero materials. If the topology has no feeder lanes, each material
needs its own physical toolhead, and eight materials on four toolheads is
reported as a conflict. An incomplete head list or an unknown lane reach gives
unknown and never falls back to comparing the filament count with a head count.

An unreadable physical nozzle list in G-code (a non-number or a non-positive
entry) leaves the physical head count unknown and records an unknown, so a
partly read list never produces a smaller invented count.

Self-contradicting topology. Preflight and firmware capability text run the
foundation `validate` check first. A topology with an error, such as a lane that
reaches a head that is not listed, gives unknown and no head count, never a fit.

Setting scopes. A per-slot project setting is addressed by one of three things, and a vector's length
is never evidence of which. Read from the Snapmaker Orca source (commit b1831e5, Preset.cpp and
PrintConfig.cpp; not measured in a running Orca): `nozzle_temperature`, `nozzle_temperature_initial_layer`
and the two range limits are filament options, one entry per project filament; `z_hop`, `z_hop_types`
and `z_hop_when_prime` belong to the printer's extruder options, one entry per physical head. The table is
`data/u1_setting_scopes.json`. With a valid setup, `prepare_preserved_values(physical_heads=H)` keeps each
vector at its own length (filament vectors at the project filament count, head vectors at H) and resizes
only a vector that does not match, with a warning. With no setup the old behaviour is unchanged: every
such vector is mapped to the four U1 toolheads.

Setup states. `preserve.assess_setup` returns absent, invalid or valid. Absent is stock behaviour. Invalid
(unreadable, a contradiction, an unknown head, an incomplete head list, slots not numbered from zero)
blocks `convert_to_u1` with an actionable message and writes nothing; preparing without a setup is a
separate request. Valid but partly bound lists the unbound slots; they stay unresolved and nothing assigns
them a head.

Callers must supply the topology. `/setups/evaluate` returns the one read from a host and `/convert`
accepts it, but no desktop screen sends it yet.
The fixtures verify the core's handling of complete head lists, known and
unknown feeder reach, material contention, incomplete topology, and the
FOrcaSlicer physical nozzle vector. They do not establish that a particular
printer adapter reports a topology correctly or that a physical printer can
execute a particular assignment.
