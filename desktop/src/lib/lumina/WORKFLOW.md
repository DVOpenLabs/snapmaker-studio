# Lumina generated-model workflow

Choose an image, explicit format, LUT and service. Requests are serialized per
mounted view. Input edits invalidate status/results. A late generation is listed
separately as a saved earlier file rather than attached to new inputs. Editing or
leaving does not cancel the service: progress and service cancellation stay unknown.
Generation does not automatically open or prepare anything.

Only a generated 3MF gets an explicit Open generated model in Studio action.
The new local endpoint checks the generated basename, full hash, bounded regular
file, descriptor/path identity and supported 3MF container, with UTF-8-only model
XML and entity/DTD refusal. PNG/GLB stay previews with no printable-model handoff.
Normal generation/status responses remain path-free. This separate user action
returns output.local_path to the local desktop only, using the same convention as
Creative output, then calls the existing session setFile and opens This print.
Normal Doctor/setup/material review and Prepare are reused without shared edits.

Checks are best effort, not a filesystem sandbox: another process can change a
path after verification, and Doctor/Prepare read it again. Existing local-path
guards still cannot distinguish mapped drives/mounted network filesystems from
local storage. No promise of race-free publication is made; Passport code is not
used or modified. This task changes only the read handoff, not generation writes.

Evidence is an owned synthetic Lumina-shaped HTTP service, valid synthetic model,
actual saved-file inspection and conversion, plus UI interaction tests. No real
Lumina installation, physical printer, slicer or Orca round-trip is verified.


## Final generation contract repair (2026-11-14)

The previous Studio route asked only for a preview even when the user chose 3MF.
Current upstream separates preview from final generation. The 3MF path now creates
a preview session, POSTs the documented session_id + params JSON to the advertised
/api/convert/generate route, and fetches only its validated download_url file ID.
PNG/GLB continue to fetch preview locators. A missing generation route is refused;
a preview 3MF or service-side disk path is never used as a fallback. The user sees
an explicit model width (60 mm initially, 10–270 accepted); other generation
settings are service defaults. Studio does not claim those defaults suit a print.

Contract-only research, no upstream implementation copied. Pinned source:
https://github.com/lumina-layer-studio/Lumina-Layers/blob/9d94bae454c1e614e0280509c8ea55b53e21bd87/api/routers/converter/generate.py
(_GenerateBody, /generate, GenerateResponse.download_url),
https://github.com/lumina-layer-studio/Lumina-Layers/blob/9d94bae454c1e614e0280509c8ea55b53e21bd87/api/schemas/converter.py
(ConvertGenerateRequest), and converter/__init__.py (route prefix).
The pinned generate source matched the initially observed source bytes. The mock
is independently hand-written to these JSON fields, with separate preview/model
IDs; a test requires POST generate and rejects downloading preview as the model.
Real Lumina compatibility is still unverified. No real Lumina was run.


Generation requests are synchronous in this version, with at most 120 seconds per
network request and a shared 240-second network budget across discovery, health,
preview, generation and artifact retrieval. The budget is not multiplied per
request; exhaustion refuses further requests. Status checks retain their previous
shorter client timeout. A timeout cannot cancel work already accepted by Lumina;
the UI states that explicitly. There is no progress-percentage invention, service
retry or automatic start. Local input checking/writing is outside the network
budget. The extension dispatcher can log a handler exceeding its advisory
five-second target. Moving this to local background-job UI remains a usability
follow-up, not a service-side cancellation claim.


## Navigation continuation (in-memory session)

The track-local session now owns form, pending request, error and result. Leaving
the route does not forget the result or permit a duplicate generation from a
remounted view. It is not a durable queue: closing/restarting Studio loses this
memory, and it does not promise service cancellation or published progress.

Editing inputs archives an already completed result; a completion for edited
inputs is also retained separately. At most ten earlier results are held, each
with its original output-directory context and stable identity. Opening an
earlier 3MF requires a separate explicit identity-checked action. No file is
opened automatically. Clearing the session forgets memory only, deletes no file,
and is disabled while work is pending. The state is never written to browser
storage. Endpoint/image/folder strings remain local UI memory.

Synthetic service tests prove navigation/serialization/stale-result accounting,
not compatibility or quality on a real Lumina installation.
