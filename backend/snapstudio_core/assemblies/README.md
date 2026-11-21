# Guided Assemblies

Choose a local file or an existing library project, edit tile names, source plate
identifiers, scale, slot roles and shared spool references, then check or save the
assembly. Advanced JSON uses the same backend validation and supports existing
slot_usage/gcode_facts documents; applying it does not save a record.

The importer reads at most 128 MiB. 3MF metadata members are limited to 2 MiB,
archives to 2048 entries and assemblies to 64 tiles/slots, with at most
32 roles per tile. File imports generate one role per slot and refuse a plate
with more than 32 slots rather than truncating it. Duplicate slice metadata,
DTD/entity XML and duplicate/out-of-range filament IDs are refused. Each sliced
plate becomes a tile. Missing or invalid gram quantities stay unknown, including
slots without a reported quantity. G-code usage comes from the existing bounded
head/tail reader. STL/OBJ files are references only: geometry and material use are
not measured. Studio does not slice or rewrite originals.

Imported source hashes and usage origin are retained in attribution. Direct file
imports are snapshots of reported figures, not live file watchers. Library imports
also carry the library ID/hash and use the existing changed/missing checks. No
local path is embedded in an assembly document by the importer. Editing grams
changes their origin to user-declared. Changing scale clears usage because the
previous slice no longer establishes the required grams. Remove the obsolete
tile and import its replacement slice, or explicitly enter new estimates.

Provider inventory uses the existing Project Materials API and an explicit unique
provider-instance ID. Provider keys stay in component memory and never enter the
assembly or saved readings. The inventory API supplies no observation timestamp,
so imported weights stay historical/unusable for an enough verdict. A user may
explicitly enter and record their own current measurement with a visible five-minute
lifetime. This is a declaration, not a sensor reading or a printing guarantee.

New imports/opening saved assemblies clear spool readings; new assemblies also
clear cached inventory. Synthetic sample figures are marked and cannot silently
mix with real file imports. Saved assemblies omit observations. All editable
inputs invalidate displayed results and late evaluate/save/open/import replies.
An already-started save may finish on the server after editing; stale responses
do not attach its identity to the newer editor. Reopen the saved version to edit it.

Evidence uses synthetic files, local-source services and mock providers. No printer,
slicer round-trip or physical spool measurement is verified by these tests.


Review repair: independent imports receive distinct unbound role names when labels
collide; roles stay shared only across plates in the same import. Explicitly rename
roles to share a spool across files. Scale changes clear all readings as well as
usage. Historical inventory values cannot be dated by one click: type the current
measurement, then record it; another recording requires editing it again. Provider
unavailability/unsupported input is a visible refusal, never a successful empty
inventory. G-code gram parsing preserves malformed/blank positions as unknown and
never shifts a later quantity into an earlier tool. Archive entry bounds apply after
ZIP central-directory parsing (128 MiB input cap), not before allocation of that
directory. No preallocation-safety claim is made.


ASM-05: G-code slots independently established by filament types, millimetre
usage or nozzle metadata are retained with unknown grams. Only the separately
parsed, position-preserving gram vector may fill those values. Missing entries
never disappear from the material plan and are never treated as zero. The
existing reader's compacted grams are not reused. Slot and assembly role caps
remain refusals. This does not establish that any unreported tool is unused.

Complete bounded declaration positions are counted before invoking the general
reader, including malformed millimetre/nozzle vectors and colour/name metadata.
These declare only slot existence, never grams or toolhead topology. An extra
separator may conservatively leave an unknown slot; it cannot make the plan
appear complete. Existing shared gcode.py is unchanged.
