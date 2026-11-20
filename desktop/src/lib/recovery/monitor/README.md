# Read-only monitoring

No network request occurs on mount. The user can type an endpoint or copy the
configured printer address, then explicitly read status and last-job history.
Automatic refresh is opt-in: one cycle runs only after the previous cycle finishes,
followed by a five-second delay. Leaving the view, stopping, changing endpoint or
toggling automatic refresh cancels requests/timers and rejects late responses.
After editing the endpoint, starting again is required. No printer-control route,
upload, slicing, heat or motion request is made.

The track-local transport uses the existing local engine identity without changing
shared API callers. Discovery and fetch share a four-second timeout and an abort
signal. Status/history have independent outcomes. Reconciliation uses only the
last observed state of this endpoint; inferred transitions never claim knowledge
of intervening events. A filename match remains unverified.

The screen shows receipt time, not a fabricated printer observation timestamp.
After 15 seconds the receipt is labelled stale. Stopping keeps the last result
visible with its ageing receipt time; changing the endpoint clears it entirely.
Camera context is still unknown. This is not workspace restoration, and no jobs
or observations are replayed or made fresh by monitoring.

Tests cover delayed replies, host changes, cancellation/unmount, serial refresh,
status/history failures, stale receipts, invalid replies and discovery timeout.
The browser journey uses an owned loopback mock and the real Studio engine.
No actual printer or camera has been validated by this repair.


Review repair: history has its own receipt/age/stale label even when status fails
or monitoring stops. Unusable status replies are named explicitly. Engine refusal
messages are bounded and displayed. Manual abort/deadline composition does not
require AbortSignal.any/timeout on older WebKitGTK. The capture sentinel permits
both existing read-only GET paths; its documentation and syntax check are updated.
