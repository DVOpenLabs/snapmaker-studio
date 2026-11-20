# Monitoring reply boundary

The track-local transport validates all fields rendered by MonitoringPanel and
MonitorSummary, including nested transition events, camera state, history filename
and note. An unusable reply becomes the existing read-error state, rather than
reaching React with an object as text or a non-array events value. The independent
status/history result remains usable when the other is refused. Explicit retry
can recover. Unknown status strings and absent optional fields remain unknown.
No invented transition or printer state is substituted. Extra fields are ignored.
The transition list limit is 32; current engine replies contain at most one event.
This validates shape, not authenticity or a new response-byte budget. Transport
timeout/cancellation and local-only endpoint routing are unchanged.
