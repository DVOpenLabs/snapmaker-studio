# Workspace recovery

P8 saves a revision-checked local `recovery.json` checkpoint, then offers a preview of tracked file identities and interrupted work. Restored observations are historical and require a fresh read before they can inform loadout conclusions. Interrupted jobs are recorded and never replayed. A filename match is always `unverified`.

The legacy desktop `snapstudio.job.v1` record is sent one way with a checkpoint and retained as an imported snapshot. It is never written back. Workspace recovery does not automatically restore application state or resume work.

## Monitoring context

Monitoring uses two bounded, read-only GETs through `foundation.netguard.local_request`, to a host the user configured: `/printer/objects/query` (state) and `/server/history/list` (last job). It sends no control request. There is **no websocket**: events are derived by **polling**. `reconcile` compares the last state a caller saw with a fresh status. The fresh status is the truth; states that occurred between two polls are reported as unknown, never invented. Camera state is `unknown` because no camera endpoint is read.

## Evidence and limits

Evidence: **fixture-tested** and **mock-service-tested** (in-process loopback mock that counts requests). All names and values are synthetic. No real printer or local monitoring service was queried.

Roadmap, not a capability: the end-to-end chain (generate, inspect, compare, passport, checkpoint, terminate, restore; test 11) is not built or tested. Camera context and websocket event streams are not implemented.
