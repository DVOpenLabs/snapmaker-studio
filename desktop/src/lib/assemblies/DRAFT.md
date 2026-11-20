# Assembly editing across navigation

Tiles, role and spool bindings, editable grams, file path, sample flag and saved
revision stay in app memory. This is not a saved assembly or fresh observation.
Spool observation times/TTLs remain unchanged; evaluation still enforces expiry.
The sample flag remains attached, preventing real imports into synthetic tiles.
Reports are discarded on navigation; checking spools is always explicit.
Provider address/key and inventory response are not retained. Advanced JSON text
not yet applied stays local to the page. New assembly clears the editor as before.
Opening a saved assembly still clears observations. App restart loses the draft.
In-flight operations may finish at the engine after navigation; their late UI
responses are ignored. A completed saved assembly can be found in the saved list.
