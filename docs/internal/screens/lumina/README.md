# Lumina service screenshots

Captured by `capture.mjs` (real engine process, vite dev UI, headless Edge) against a synthetic stand-in service on loopback (`backend/tests/mocks/lumina_server.py`, `LuminaHttpMock`). The service is not Lumina and serves fixed synthetic bytes; the image is a few synthetic bytes. File names are relative, no local paths: the capture fails if the rendered page text contains the throwaway folder or a user-profile path. Evidence: `mock-service-tested`. No real Lumina installation was exercised.

| File | Shows |
| --- | --- |
| `form-empty.png` | The form as first opened: empty fields, no preselected format, Generate unavailable until one is chosen, the "tested only against a synthetic stand-in" statement |
| `form-filled-service-checked.png` | Fields filled, `png` chosen (its meaning and evidence label shown), identity check answered, with the note that this is not proof of what the service is |
| `result-success.png` | A new file saved: name, kind, size, SHA-256, "Saved in Studio's lumina-output folder", "Made by a user-configured local Lumina-compatible service (not verified)", progress and cancel shown as unknown, the not-watched advisory, original unchanged |
| `refusal-format-not-produced.png` | `3mf` chosen but the service returned `glb, png`: nothing saved, the supported list named |
| `refusal-non-local-address.png` | A non-local address (a public IP literal, no lookup) refused before anything is sent |

A format outside the list cannot be picked in the UI (the selector offers only the listed formats and Generate stays unavailable without one); the backend refusal for an unlisted format is covered by `backend/tests/test_routes_engines_lumina.py`.

Run: `PYTHON=<python 3.13+> ACCEPTANCE_DIR=<folder with node_modules/playwright-core> node docs/internal/screens/lumina/capture.mjs`.
