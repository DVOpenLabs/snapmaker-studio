# AFC fixtures
Shape source: AFCProject/AFC-Klipper-Add-On `GET /printer/afc/status`. Wrapper `{"status:": {"AFC": {...}}}`
(literal trailing colon) from extras/AFC.py blob 9553d159 lines 2572-2612; per-lane keys from extras/AFC_lane.py
blob f6b98e2c `get_status` lines 2183-2235; lane status strings from `AFCLaneState` lines 65-76.
`status_plain` (no colon) and `result_envelope` (Moonraker `result` wrapper) are tolerated variants, not
published shapes. Written by hand to the published shape; not captured from a device. Values are synthetic.
Evidence label: fixture-tested.
