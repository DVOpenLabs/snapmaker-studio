# BMCU-Klipper fixtures
Shape source: jarczakpawel/BMCU-Klipper docs/COMMANDS.md blob 2bc051ed (print plan, `BMCU_MAP_TOOL` alias,
`BMCU_SET_ENDPOINT`, `BMCU_SET_ROUTE`, `BMCU_ROUTE_CONFIRM`), printers/Snapmaker_U1/README.md blob eac7b8c3 and
web/bmcu_panel_server.py blob bd2d86ae lines 1973-2047 (`/api/transport-status`, schema 1). The `kind`/`text`/`body`
wrapper is a Studio transport envelope; text and body are upstream formats. The panel's per-device `status`
object and BMCU_STATUS output are not published, so no channel state is derived from them.
Written by hand; not captured from a device. Values are synthetic. Evidence label: fixture-tested.
