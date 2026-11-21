# Setups to Prepare: explicit input handoff

Read the setup, then choose Continue in Prepare for a verified current 3MF job.
The action transfers host, port and explicit accessory inputs only, in memory.
It opens the normal project screen and pauses Prepare. A new explicit read is
required; the standalone report/topology is never promoted into a selection.
The OctoPrint API-key field is not transferred or stored in this draft. Enter
it again for an authenticated host. Accessory snapshot text is retained exactly
as entered, in app memory only; do not paste credentials into a snapshot.

Drafts are scoped by project path, bounded to eight projects and the existing
snapshot limit. They survive navigation, not app restart; Clear setup forgets
the current project's remembered draft. No browser storage, network, preparation
or printer action runs just because the inputs are restored. User edits still
pause the selected setup and stale answers remain rejected. A failed new read
stays failed; stock preparation is an explicit separate choice.

Evidence: fixture/mock only. A host topology read is advisory, not physical
validation. Project association uses the existing verified-job flag; it is not
a new on-disk identity check. Session/job stores are unchanged.
