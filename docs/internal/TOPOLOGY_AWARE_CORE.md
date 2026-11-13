# Topology-aware core wiring

Evidence label: **fixture-tested**.

The core now accepts a decoded printer topology in preflight and firmware
capability interpretation. Preflight evaluates each project's logical material
slot against feeder lanes and physical heads. Its result distinguishes a
supported assignment, a reported contention, and incomplete reach or head
information. Firmware capability details report physical toolheads separately
from feeder lanes. When no valid topology is supplied, both functions retain
their previous behavior.

Preserved per-extruder vectors can now remain intact when a caller identifies a
matching logical-slot count greater than four. G-code facts keep the existing
`slot_count`, report a separately supplied FOrcaSlicer physical nozzle vector,
and leave physical head count unknown when a longer nozzle vector may be
indexed per filament.

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

Known limit. The preservation keyword `logical_slots` exists, but the repair
path does not pass it. `conform_filament_arrays` skips the per-extruder vectors
(`PER_EXTRUDER_VECTORS`: nozzle temperatures, their range limits, z-hop and its
types), so they reach `prepare_preserved_values` unchanged. `repair.py` then
calls it without `logical_slots`, and that call cuts any such vector longer than
four to four entries. A test runs both steps and records the result. Per-logical
vectors are therefore kept only when a caller of `prepare_preserved_values`
supplies the slot count; wiring the repair path is part of the integration PR.
Nothing here is hardware-verified.

This branch does not wire adapter output into the core. Callers must supply the
topology; end-to-end adapter-to-core wiring is planned for the integration PR.
The fixtures verify the core's handling of complete head lists, known and
unknown feeder reach, material contention, incomplete topology, and the
FOrcaSlicer physical nozzle vector. They do not establish that a particular
printer adapter reports a topology correctly or that a physical printer can
execute a particular assignment.
