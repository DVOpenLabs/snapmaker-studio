# Sliced-output comparison

Studio compares existing local sliced outputs; it does not slice or contact a
printer. Orca/Bambu `Metadata/slice_info.config` XML plate summaries are read
alongside JSON project settings. The earlier synthetic JSON slice-summary
representation remains readable.

Usage is aggregated by one-based filament ID across plates. Missing or invalid
usage on any plate makes the aggregate unknown, rather than presenting a partial
sum as complete. Missing/invalid plate predictions make total time unknown.
Repeated filament IDs within a plate are rejected. XML is bounded by the existing
2 MiB member limit; only UTF-8 (optional BOM) is evaluated, with DTDs/entities
refused. XML summaries do not establish tool-change counts or physical bindings.

G-code material/time summaries are accepted in header or footer comments. The
body scan remains limited to 8 MiB, with a separate 256 KiB tail read for large
files. Tool changes remain unknown when the body scan is truncated. The tail
does not prove that no tool changes occurred in the unscanned middle. A summary
outside these windows remains unknown. Slicer-reported numbers are advisory.

Changing either selected file clears the screen and invalidates an outstanding
comparison, including late errors. Original files are never rewritten. Existing
snapshot/freshness and validated physical-binding checks remain in force.

Regression evidence uses synthetic XML/JSON archives and G-code, plus UI
interaction tests. This repair does not claim a new slicer round-trip or any
hardware verification.
