// Read-only verification of the *installed* Snapmaker Studio against a real
// Snapmaker U1, driven over the Chrome DevTools Protocol.
//
// Why this exists: everything Studio says about a printer was, until beta.24,
// verified only against tests the project wrote itself. The first session against
// a real machine found a genuine bug — the U1 reports loaded filament as parallel
// arrays, and Studio was looking for a list of objects, so it told owners their
// printer does not report loaded filament while the printer was reporting all
// four spools. This script proves the shipped installer reads that firmware
// correctly, and that the honest unknowns are still honest.
//
// SAFETY. This script is read-only by construction:
//  * Only the routes in READ_ONLY_ROUTES are ever called, and the list is
//    asserted against a deny-list of every control route the engine exposes.
//  * Nothing is uploaded, nothing is queued, no temperature, motion, homing,
//    pause, resume, cancel, start, emergency stop or configuration call is made.
//
// PRIVACY. The printer's address never reaches the evidence file: it is replaced
// with a placeholder before anything is written to disk.
//
// Usage: node checks.mjs <cdpUrl> <outDir> <printerHost> <samplePath>
//
// Optional, through the environment so the positions above stay the contract
// they already were: SNAPSTUDIO_HW_SPOOLMAN and SNAPSTUDIO_HW_BAMBUDDY, plus
// the seeded spool ids, enable the provider-against-hardware checks. Without
// them everything else still runs and the provider checks say they were
// skipped rather than quietly passing.

import { chromium } from "playwright-core";
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const [, , cdpUrl, outDir, printerHost, samplePath] = process.argv;
mkdirSync(outDir, { recursive: true });

const READ_ONLY_ROUTES = [
  "/printer/status",
  "/printer/capabilities",
  "/printer/firmware",
  "/preflight",
  "/post_slice",
  // Reads the machine and the job together, and produces the fingerprint the
  // send path compares against. It uploads nothing: the engine's upload lives
  // behind a different route, which is not in this list and never will be.
  "/send_check",
  "/material_plan",
];

// Anything that could change the machine's state. Asserted, not assumed.
const FORBIDDEN = [
  "control", "start", "pause", "resume", "cancel", "emergency",
  "upload", "queue", "gcode", "config", "firmware_update", "restart",
];
for (const route of READ_ONLY_ROUTES) {
  const tail = route.split("/").pop();
  if (FORBIDDEN.some((f) => tail.includes(f) && tail !== "firmware")) {
    throw new Error(`refusing to run: ${route} is not read-only`);
  }
}

// Print the gate before the first request, so what this run is allowed to do is
// on the record rather than inferred from the code afterwards. `callRoute` is
// then held to the same list at the moment of the call: a route added to the
// script without being added here does not reach the printer.
console.log("READ-ONLY GATE — POST is the only method used, to these routes only:");
for (const route of READ_ONLY_ROUTES) console.log(`  ${route}`);
console.log(`  refused if the tail matches: ${FORBIDDEN.join(", ")}`);
console.log("  no upload, start, pause, resume, cancel, emergency stop, gcode script,");
console.log("  heating, motion, homing, configuration write, deletion or queue change.");
console.log("");

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
};

/** Replace the printer's address wherever it appears, at any depth. */
const anonymise = (value) =>
  JSON.parse(JSON.stringify(value).split(printerHost).join("<printer-on-lan>"));

async function appPage(browser) {
  const ctx = browser.contexts()[0];
  for (const page of ctx.pages()) {
    if (page.url().startsWith("http://tauri.localhost")) return page;
  }
  throw new Error("the app window was not found over CDP");
}

async function callRoute(page, route, body) {
  // The gate, enforced where it matters rather than only where it is declared.
  if (!READ_ONLY_ROUTES.includes(route)) {
    throw new Error(`refusing to call ${route}: not in the read-only list`);
  }
  return page.evaluate(
    async ([route, body]) => {
      const info = await window.__TAURI_INTERNALS__.invoke("get_api_info");
      const res = await fetch(`http://127.0.0.1:${info.port}${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Auth-Token": info.token },
        body: JSON.stringify(body),
      });
      return { status: res.status, body: await res.json() };
    },
    [route, body],
  );
}

const browser = await chromium.connectOverCDP(cdpUrl);
const page = await appPage(browser);
const evidence = {};

// --- the printer answers -----------------------------------------------------

const status = await callRoute(page, "/printer/status", { host: printerHost, port: 7125 });
evidence.status = anonymise(status.body);
const reachable = status.status === 200 && !status.body?.error;
record("Printer discovered and answering", reachable,
  `print state: ${status.body?.print_state ?? "unknown"}`);

const caps = await callRoute(page, "/printer/capabilities", { host: printerHost, port: 7125 });
evidence.capabilities = anonymise(caps.body);
const objects = caps.body?.klipper_objects ?? [];
record("Firmware object list enumerated", objects.length > 50, `${objects.length} objects`);

const bed = caps.body?.bed_mm ?? {};
record("Printer reports its own bed size",
  Number(bed.x) > 100 && Number(bed.y) > 100 && Number(bed.z) > 100,
  `${bed.x} × ${bed.y} × ${bed.z} mm`);
record("Printer reports its toolhead count", caps.body?.toolhead_count === 4,
  `${caps.body?.toolhead_count} toolheads`);

// --- the bug this release fixes ---------------------------------------------
//
// Stock U1 firmware publishes loaded filament as parallel arrays. Studio was
// looking for a list of objects, found nothing, and told the owner the printer
// does not report loaded filament. This is the shipped code path reading a real
// machine.

const pre = await callRoute(page, "/preflight",
  { path: samplePath, host: printerHost, port: 7125 });
evidence.preflight = anonymise(pre.body);
record("Preflight ran against the real machine", pre.status === 200 && !pre.body?.error);

const loaded = pre.body?.printer?.loaded_filaments ?? [];
record("Loaded filament read from the real firmware", loaded.length === 4,
  loaded.map((f) => `${f.color ?? "?"} ${f.material ?? "?"}`).join(", ") || "none");
record("Each loaded slot carries a material and a colour",
  loaded.length > 0 && loaded.every((f) =>
    typeof f.material === "string" && f.material.length > 0 &&
    typeof f.color === "string" && /^#[0-9a-f]{6}$/i.test(f.color)));

// --- the honest unknowns still hold ------------------------------------------

const rows = pre.body?.checks ?? [];
const text = JSON.stringify(rows).toLowerCase();

const nozzle = rows.find((r) => r.id === "nozzle.match");
// Stock U1 firmware DOES report the fitted nozzle diameter via
// /machine/system_info (confirmed live this session) — the nozzle check can
// now come back ok or attention, not only unknown. What must never happen,
// whichever it is, is the old "unsupported" framing, and an ok/attention
// result must cite where the reading actually came from.
record("Fitted nozzle is read from real firmware when available, never called unsupported",
  ["ok", "attention", "unknown"].includes(nozzle?.result)
    && !JSON.stringify(nozzle).toLowerCase().includes("unsupported"),
  `${nozzle?.result}: ${nozzle?.evidence ?? nozzle?.title ?? "no nozzle check"}`);
record("A matched nozzle reading is credited to the printer, not asserted with no source",
  nozzle?.result !== "ok" || /the printer reports|you confirmed/.test(nozzle?.evidence ?? ""),
  nozzle?.evidence ?? "");

record("Nothing undetected is called unsupported", !text.includes("unsupported"));

const bedCheck = rows.find((r) => r.id === "bed.fit");
record("The printer's own bed size was used in the bed check",
  Boolean(bedCheck) && bedCheck.evidence.includes(String(bed.x)),
  bedCheck?.evidence ?? "");

const toolheads = rows.find((r) => r.id === "materials.toolheads");
record("Project materials compared against the machine's toolheads",
  Boolean(toolheads) && toolheads.confidence === "confirmed",
  toolheads?.evidence ?? "");

const materials = rows.find((r) => r.id === "materials.loaded");
record("Project materials compared against what is actually loaded",
  Boolean(materials) && materials.evidence.includes("4 loaded"),
  materials?.evidence ?? "");

const reachable2 = rows.find((r) => r.id === "printer.reachable");
record("Preflight recorded the printer as found", reachable2?.result === "ok");

// --- the sliced job, joined to this machine ---------------------------------
//
// The Post-Slice Doctor is the half of the workflow that only matters against a
// real printer: a job that prints from slot 2 is fine or fatal depending on
// whether slot 2 has a spool in it. Studio does not slice, so the job is written
// here in the exact shape Snapmaker Orca produces.

const JOB = `; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-23 at 10:00:00
; total layer number: 12
; max_z_height: 2.40
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
M140 S60
T1
;LAYER_CHANGE
;Z:0.2
G1 X10 Y10 Z0.2 F1200
;LAYER_CHANGE
;Z:0.4
G1 X20 Y20 E1.0
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [mm] = 0.00, 120.00, 0.00, 0.00
; filament used [g] = 0.00, 0.36, 0.00, 0.00
; total filament used [g] = 0.36
; total layers count = 12
; estimated printing time (normal mode) = 4m 10s

; CONFIG_BLOCK_START
; filament_type = PLA;PLA;PLA;PLA
; layer_height = 0.2
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
`;

const jobPath = join(outDir, "hardware_job.gcode");
writeFileSync(jobPath, JOB);

const post = await callRoute(page, "/post_slice", { path: jobPath, host: printerHost, port: 7125 });
evidence.post_slice = anonymise(post.body);
const postChecks = post.body?.checks ?? [];
const check = (id) => postChecks.find((c) => c.id === id);

record("Sliced job joined to the real printer",
  post.status === 200 && post.body?.available === true && postChecks.length > 0,
  post.body?.summary ?? "");

record("The tool the job needs is confirmed to exist",
  check("gcode.tools")?.result === "ok", check("gcode.tools")?.evidence ?? "");

record("The slot the job prints from is confirmed loaded",
  check("gcode.loaded")?.result === "ok", check("gcode.loaded")?.evidence ?? "");

record("Loaded material checked against the job's material",
  ["ok", "attention"].includes(check("gcode.material")?.result),
  check("gcode.material")?.evidence ?? "");

record("The job's bed is compared with the printer's own bed",
  check("gcode.bed")?.result === "ok", check("gcode.bed")?.evidence ?? "");

// The JOB fixture above states nozzle_diameter = 0.4 for every toolhead, and
// a real U1's firmware reports the same (confirmed live this session), so
// this now matches — the post-slice nozzle check reads the SAME printer
// reading preflight's does, not a second, still-blind implementation.
record("Fitted nozzle after slicing matches the real firmware reading, never called unsupported",
  check("gcode.nozzle")?.result === "ok"
    && !JSON.stringify(check("gcode.nozzle")).toLowerCase().includes("unsupported"),
  check("gcode.nozzle")?.evidence ?? check("gcode.nozzle")?.title ?? "");

record("Nothing undetected is called unsupported after slicing",
  !JSON.stringify(postChecks).toLowerCase().includes("unsupported"));

// --- what this sprint added, against the real machine --------------------------

// The send fingerprint has to describe *this* printer, and notice when it stops
// describing it. Nothing here changes the machine: the "after" state is the real
// reading with one slot blanked in the copy Studio was given.
const send = await callRoute(page, "/send_check",
  { path: jobPath, host: printerHost, port: 7125 });
const state = send.body?.state;
record("The send check fingerprints what it looked at",
  Boolean(state?.token) && Boolean(state?.hashes?.printer) && Boolean(state?.hashes?.materials),
  state?.token ? `token ${String(state.token).slice(0, 8)}…` : "no fingerprint");

const sendLoadout = send.body?.printer?.loaded_filaments ?? [];
record("The fingerprint carries the machine's real loadout",
  Array.isArray(sendLoadout) && sendLoadout.some((slot) => slot && slot.material),
  `${sendLoadout.filter(Boolean).length} slot(s) with a spool`);

// A real remaining weight needs something that tracks spools; a stock U1 has
// nothing that does, and the honest answer is unknown rather than plenty.
const plan = await callRoute(page, "/material_plan",
  { path: jobPath, host: printerHost, port: 7125 });
const slots = plan.body?.slots ?? [];
const used = slots.filter((slot) => slot.needed);
record("Filament sufficiency stays unknown on a stock printer",
  used.length > 0 && used.every((slot) => slot.sufficiency?.verdict === "unknown"),
  used.map((slot) => `${slot.label}: ${slot.sufficiency?.verdict}`).join(", "));
record("Nothing on a stock printer is called short of filament",
  !slots.some((slot) => slot.state === "not_enough"));

// Extended firmware is detected only when a firmware answers for itself. This
// machine runs stock, so the correct answer is "not detected" — and that must
// not be reported as "this printer is stock", which Studio cannot know.
const firmware = await callRoute(page, "/printer/firmware",
  { host: printerHost, port: 7125 });
const firmwareBody = firmware.body ?? {};
evidence.firmware = anonymise(firmwareBody);
record("Community firmware is not claimed on a stock machine",
  firmwareBody.extended_firmware === false,
  `${firmwareBody.macro_count ?? 0} macros, many=${firmwareBody.many_custom_macros ?? false}`);
record("Not finding a firmware marker is never called stock",
  typeof firmwareBody.extended_firmware_evidence === "string"
  && /not the same as/i.test(firmwareBody.extended_firmware_evidence),
  firmwareBody.extended_firmware_evidence ?? "");

// --- what the two unreleased sprints added, against the real machine ----------
//
// `main` carries the printer-profile architecture and user-facing material
// providers. Both changed load-bearing code on the path between this machine and
// what Studio says about it, and neither had ever been run against hardware. A
// count of 26 that skipped these would be a number, not a verification.

const facts = pre.body?.printer ?? {};
evidence.identity = anonymise(facts.identity ?? null);
evidence.resolved = anonymise(facts.resolved ?? null);
evidence.profile = anonymise(facts.profile ?? null);

// Identification is inference from what the machine reported. `print_task_config`
// is not in mainline Klipper, so a machine carrying it is a Snapmaker — and this
// is the first time that inference has met a real one.
const identity = facts.identity ?? {};
record("The real machine is identified as a Snapmaker U1",
  identity.matched === true && identity.printer_id === "snapmaker_u1"
    && identity.confidence === "confirmed",
  `${identity.printer_id ?? "no match"} (${identity.confidence ?? "-"})`);
record("Identification is drawn from the printer's own vendor object",
  typeof identity.evidence === "string" && identity.evidence.includes("print_task_config"),
  identity.evidence ?? "");

// The U1 must still read as the one printer this project has put on a wire.
record("The U1 profile still reads as hardware verified",
  facts.profile?.verification_level === "hardware_verified",
  facts.profile?.verification_label ?? "no profile");

// The rule the whole abstraction stands on: the machine wins, always.
const resolved = facts.resolved ?? {};
record("The live toolhead count is used, not the profile's",
  resolved.tool_count === 4 && resolved.sources?.tool_count === "live",
  `${resolved.tool_count} from ${resolved.sources?.tool_count}`);
record("The live bed is used, not the profile's",
  resolved.sources?.build_volume_mm === "live"
    && Number(resolved.build_volume_mm?.y) > 300,
  `${resolved.build_volume_mm?.x} × ${resolved.build_volume_mm?.y} × ${resolved.build_volume_mm?.z} from ${resolved.sources?.build_volume_mm}`);

// The U1 travels 335 mm in Y over a 270 mm plate. Live axis range and profile
// printable area answer different questions, so a difference between them is not
// a disagreement — and reporting one at the user would be noise on every launch.
record("Travel beyond the printable plate is not called a conflict",
  Array.isArray(resolved.conflicts) && resolved.conflicts.length === 0,
  `${(resolved.conflicts ?? []).length} conflict(s)`);

// The U1 is unusual in reporting its own filament. That has to stay an
// observation and be marked as one, now that a provider mapping can supply the
// same shape without the machine having looked.
record("Loaded filament is recorded as the printer's own observation",
  resolved.material_state?.known === true
    && resolved.material_state?.source === "live"
    && resolved.material_state?.slots === 4,
  `${resolved.material_state?.slots ?? "?"} slot(s) from ${resolved.material_state?.source ?? "-"}`);

// The extruder objects `status()` asks for are now derived from the printer's own
// tool count rather than a fixed list of four. On a four-toolhead machine the
// answer must be unchanged — this is the truncation regression check.
const channels = status.body?.toolheads ?? [];
record("All four toolhead temperature channels still come back",
  channels.length === 4 && channels.every((t) => typeof t.temperature === "number"),
  `${channels.length} channel(s)`);

// The sliced-machine check was hard-coded to the string "u1" and now compares the
// job against the printer Studio identified. A U1 job on this U1 must still match.
record("A U1-targeted job matches this identified U1",
  check("gcode.machine")?.result === "ok",
  check("gcode.machine")?.evidence ?? "");

// Genericising the wording must not cost the U1 its name where the name is known.
record("The firmware summary names this machine, having identified it",
  typeof firmwareBody.summary === "string" && /U1/.test(firmwareBody.summary),
  firmwareBody.summary ?? "");

// Material providers are reachable in `main`. With none configured, the provider
// path must not execute at all.
//
// This is asserted on `/material_plan`, not on `/preflight`: preflight never
// consults a provider whatever the settings say, so asserting it there would
// pass without proving anything. `material_sources` and `remaining_known` are
// written onto the printer facts only when the provider path actually runs, so
// their absence is the evidence that no provider was contacted.
const planPrinter = plan.body?.printer ?? {};
record("No material provider ran, and none was contacted",
  planPrinter.material_sources === undefined && !planPrinter.remaining_known
    && plan.body?.remaining_known === false,
  `sources=${JSON.stringify(planPrinter.material_sources)} remaining_known=${plan.body?.remaining_known}`);

// And the U1's own reading still reaches the plan, marked as the machine's.
const planSlots = plan.body?.slots ?? [];
record("What the plan compares against came from the printer itself",
  planSlots.some((slot) => slot.confirmed_by === "printer")
    && !planSlots.some((slot) => slot.confirmed_by === "provider"),
  planSlots.map((slot) => `${slot.label}:${slot.confirmed_by ?? "-"}`).join(", "));

// An address that answers nothing is not this machine, and Studio must not tell
// whoever typed it to go and change a setting on a printer it has never seen.
const nowhere = await callRoute(page, "/preflight",
  { path: samplePath, host: "snapstudio-no-such-host-9f3b.invalid", port: 7125 });
const nowhereRow = (nowhere.body?.checks ?? []).find((r) => r.id === "printer.reachable");
const nowhereText = JSON.stringify(nowhere.body ?? {});
// The distinction is conditional versus unconditional, not whether the word
// "touchscreen" appears. Studio may say "if it is a Snapmaker U1, its interface
// only opens once Advanced Mode is on" about an address it knows nothing about;
// what it may not do is instruct someone to go and change a setting on a machine
// it has never seen, which is what the U1-hostname hint does and is right to do
// only there.
const nowhereAction = nowhereRow?.action ?? "";
record("An address that answers nothing gets a generic hint",
  nowhereRow?.result === "unknown"
    && !/On the U1 touchscreen/i.test(nowhereAction)
    && /If it is a Snapmaker U1/i.test(nowhereAction)
    && !nowhereText.includes(printerHost),
  nowhereAction);


// --- a material provider, against a machine that can see its own spools ------
//
// The second-provider sprint added a whole source of material facts and proved
// the seam in tests and in an installed build. Neither of those had a printer
// on the other end. The rule the design turns on only becomes real here: the
// machine is *looking* at the slot, and a provider is somebody's note about it.
//
// All of this is read-only. `/material_plan` and `/send_check` are on the
// allow-list, Studio never writes to a provider, and the providers themselves
// are session-owned containers on this machine, not the printer.

const spoolmanUrl = process.env.SNAPSTUDIO_HW_SPOOLMAN || "";
const bambuddyUrl = process.env.SNAPSTUDIO_HW_BAMBUDDY || "";
const agreeIds = {
  spoolman: Number(process.env.SNAPSTUDIO_HW_SP_AGREE || 0),
  bambuddy: Number(process.env.SNAPSTUDIO_HW_BB_AGREE || 0),
};
const conflictIds = {
  spoolman: Number(process.env.SNAPSTUDIO_HW_SP_CONFLICT || 0),
  bambuddy: Number(process.env.SNAPSTUDIO_HW_BB_CONFLICT || 0),
};
const providerUrls = { spoolman: spoolmanUrl, bambuddy: bambuddyUrl };

/** The plan for the slot this job prints from, with a provider mapped onto it. */
async function planWithProvider(provider, spoolId) {
  const out = await callRoute(page, "/material_plan", {
    path: jobPath, host: printerHost, port: 7125,
    provider, provider_url: providerUrls[provider],
    slot_map: { "2": spoolId }, slot_base: 1,
  });
  const slots = out.body?.slots ?? [];
  return { body: out.body, slot: slots.find((s) => s.needed) ?? slots[1] ?? slots[0] };
}

if (spoolmanUrl && bambuddyUrl) {
  const agreed = {};
  const conflicted = {};

  for (const provider of ["spoolman", "bambuddy"]) {
    // --- the provider agrees with what the machine can see -------------------
    const a = await planWithProvider(provider, agreeIds[provider]);
    agreed[provider] = a.slot;
    record(`The machine's own reading survives a provider that agrees (${provider})`,
      a.slot?.printer_confirmed === true && a.slot?.confirmed_by === "printer"
        && /PLA/i.test(String(a.slot?.has_material ?? "")),
      `${a.slot?.has_material} confirmed_by=${a.slot?.confirmed_by}`);
    record(`The provider supplies the weight the machine cannot know (${provider})`,
      typeof a.slot?.remaining_g === "number" && a.slot.remaining_g > 0
        && a.slot?.remaining_quality === "tracked",
      `${a.slot?.remaining_g} g ${a.slot?.remaining_quality}`);
    record(`Agreement is not reported as a disagreement (${provider})`,
      (a.slot?.conflicts ?? []).length === 0,
      `${(a.slot?.conflicts ?? []).length} conflict(s)`);

    // --- the provider disagrees ---------------------------------------------
    const c = await planWithProvider(provider, conflictIds[provider]);
    conflicted[provider] = c.slot;
    record(`The printer stays authoritative when a provider disagrees (${provider})`,
      /PLA/i.test(String(c.slot?.has_material ?? ""))
        && c.slot?.printer_confirmed === true,
      `${c.slot?.has_material}, printer_confirmed=${c.slot?.printer_confirmed}`);
    record(`The disagreement is said out loud rather than resolved (${provider})`,
      (c.slot?.conflicts ?? []).length > 0
        && (c.slot?.conflicts ?? []).some((x) => /PETG/i.test(x)),
      (c.slot?.conflicts ?? []).join(" ").slice(0, 90));
    record(`A disagreement does not throw the weight away (${provider})`,
      typeof c.slot?.remaining_g === "number" && c.slot.remaining_g > 0,
      `${c.slot?.remaining_g} g`);
  }

  // --- the two providers must decide the same about this machine -------------
  //
  // The seam was proved equal in unit tests and in an installed build. This is
  // the same claim with a real printer supplying half the facts.
  const shape = (slot) => JSON.stringify({
    material: slot?.has_material, state: slot?.state,
    confirmed_by: slot?.confirmed_by, printer_confirmed: slot?.printer_confirmed,
    remaining_g: slot?.remaining_g, quality: slot?.remaining_quality,
    conflicts: (slot?.conflicts ?? []).map((c) => c.replace(/spoolman|bambuddy/gi, "PROVIDER")),
    verdict: slot?.sufficiency?.verdict, trusted: slot?.sufficiency?.trusted,
  });
  record("Two providers agreeing with the machine decide the same",
    shape(agreed.spoolman) === shape(agreed.bambuddy),
    `${shape(agreed.spoolman)} vs ${shape(agreed.bambuddy)}`.slice(0, 160));
  record("Two providers disagreeing with the machine decide the same",
    shape(conflicted.spoolman) === shape(conflicted.bambuddy),
    `${shape(conflicted.spoolman)} vs ${shape(conflicted.bambuddy)}`.slice(0, 160));

  // --- a provider that is not there ------------------------------------------
  //
  // The machine is still there, and what it can see must be unaffected. An
  // unreachable provider subtracts a weight; it does not subtract the printer.
  const gone = await callRoute(page, "/material_plan", {
    path: jobPath, host: printerHost, port: 7125,
    provider: "spoolman", provider_url: "127.0.0.1:1",
    slot_map: { "2": 1 }, slot_base: 1,
  });
  const goneSlots = gone.body?.slots ?? [];
  const goneSlot = goneSlots.find((s) => s.needed) ?? goneSlots[1];
  record("An unreachable provider leaves the machine's own facts intact",
    goneSlot?.printer_confirmed === true
      && /PLA/i.test(String(goneSlot?.has_material ?? "")),
    `${goneSlot?.has_material} confirmed_by=${goneSlot?.confirmed_by}`);
  record("An unreachable provider claims no weight rather than none",
    goneSlot?.remaining_g == null
      && (goneSlot?.sufficiency?.verdict ?? "unknown") === "unknown",
    `remaining=${goneSlot?.remaining_g} verdict=${goneSlot?.sufficiency?.verdict}`);

  // --- and the send decision, with the machine and a provider both speaking ---
  const send = await callRoute(page, "/send_check", {
    path: jobPath, host: printerHost, port: 7125,
    provider: "bambuddy", provider_url: bambuddyUrl,
    slot_map: { "2": agreeIds.bambuddy }, slot_base: 1,
  });
  record("A real machine and a provider together reach a send decision",
    send.status === 200 && send.body?.available === true
      && typeof send.body?.verdict === "string",
    `${send.body?.verdict} ${JSON.stringify(send.body?.counts ?? {})}`);
  record("Nothing about this run claims the printer weighed anything",
    !/weighed|scale/i.test(JSON.stringify(send.body?.materials ?? {})),
    "no weighing claimed on the machine's behalf");

  evidence.provider_on_hardware = anonymise({
    agreed: { spoolman: agreed.spoolman, bambuddy: agreed.bambuddy },
    conflicted: { spoolman: conflicted.spoolman, bambuddy: conflicted.bambuddy },
  });
} else {
  console.log("no provider addresses supplied — the provider-on-hardware checks were skipped");
}

// --- report -------------------------------------------------------------------

const passed = results.filter((r) => r.ok).length;
writeFileSync(join(outDir, "hardware.json"), JSON.stringify({
  schema_version: "hardware/1",
  printer: "<printer-on-lan>",
  read_only_routes: READ_ONLY_ROUTES,
  checks: results,
  passed,
  total: results.length,
  evidence,
}, null, 2));
await page.screenshot({ path: join(outDir, "hardware.png") });

console.log(`\n${passed}/${results.length} hardware checks passed`);
await browser.close();
process.exit(passed === results.length ? 0 : 1);
