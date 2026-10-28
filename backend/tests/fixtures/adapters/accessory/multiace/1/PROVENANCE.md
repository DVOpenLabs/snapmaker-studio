# multiACE fixtures
Shape source: decay71/multiACE `GET /multiace/api/preflight/livedata`. `docs_example.json` follows
docs/LOADOUT_API.md blob bac8805b (sec 1, 2, 4). `normal`, `code_manual_heads`, `head_mode`, `normal_mode`,
`derived_omitted` follow web/backend/main.py blob d19bc7a2 (`_live_slots_async` lines 1204-1229,
`_head_mode_context` lines 1256-1330). `docs_409_manual.json` is the HTTP 409 the docs describe while a head is
manual; the code returns 200 with `manual_heads` instead (documented drift, both are read).
These files were written by hand to the published shape. They were not captured from any device or service.
Values (colours, nozzle sizes, spool contents) are synthetic. Evidence label: fixture-tested.
