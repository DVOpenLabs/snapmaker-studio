// What to capture, and which on-screen controls get a numbered hotspot.
// The hotspot TEXT is not here: it lives in content/shots.json so lesson authors never touch capture code.
// Each target is a function returning a Playwright locator for the control the hotspot points at.
export const SIZE = { width: 1230, height: 960 };

const T = (re) => (p) => p.getByText(re).filter({ visible: true }).first();
const waitText = (re, timeout = 90000) => async (page) => { await page.getByText(re).first().waitFor({ timeout }); };
const btn = (name) => (p) => p.getByRole("button", { name }).first();
const link = (name) => (p) => p.getByRole("link", { name }).first();
const DEMO = "demo_offplate_foreign.3mf";

export const SHOTS = [
  /* ---- lesson 1 / 2 / 3 : first look ---- */
  {
    id: "home", file: "home.png", route: "/",
    targets: {
      "open-main": (p) => p.getByRole("button", { name: /Open a model/ }).nth(1),
      "open-sidebar": btn(/Open a model/),
      "view-toggle": (p) => p.getByText("VIEW").locator(".."),
      "help": link("Help"),
      "local-only": T(/Local-only · nothing leaves your network/),
    },
  },
  {
    id: "workspace-stl", file: "workspace-stl.png", open: "sample_cube.stl",
    setup: waitText(/Can prepare a U1 copy/),
    targets: {
      "file": T("sample_cube.stl"), "verdict": T("Can prepare a U1 copy"), "prepare": btn(/^Prepare U1 copy/),
      "fix-plan": T("Your fix plan"), "contents": T("What's in this design"),
    },
  },
  {
    id: "workspace-3mf", file: "workspace-3mf.png", open: DEMO, size: { width: 1230, height: 1100 },
    setup: waitText(/Hangs 55\.0 mm past the right edge/),
    targets: {
      "mode": T("Preparation mode"), "preserve": T("Preserve creator settings"), "prepare": btn(/^Prepare U1 copy/),
      "placement": T("Object placement"),
    },
  },
  {
    id: "this-print-top", file: "this-print-top.png", open: DEMO, route: "/this-print", size: { width: 1230, height: 1480 },
    setup: waitText(/Printer not found/),
    targets: {
      "header": T(/^This print — /), "stage-one": T("1. Before slicing"), "placement": T("Object placement"),
      "printer-check": T("Before you slice"), "colours": T("Colours and toolheads"),
    },
  },
  {
    id: "nav-advanced", file: "nav-advanced.png", route: "/", size: { width: 1230, height: 1100 },
    setup: async (p) => { await p.getByRole("button", { name: "Advanced" }).click(); await p.waitForTimeout(800); },
    targets: {
      "view-toggle": (p) => p.getByText("VIEW").locator(".."), "compat": link("Compatibility"),
      "colors": link("Colors & Materials"), "printer-hub": link("Printer Hub"),
    },
  },

  /* ---- lesson 4 / 5 : the checks, the fix ---- */
  {
    id: "compat-top", file: "compat-top.png", open: DEMO, route: "/compatibility", size: { width: 1230, height: 1000 },
    setup: waitText(/Hangs 55\.0 mm past the right edge/),
    targets: {
      "title": T("Compatibility Doctor"), "placement": T("1 object is outside the U1's printable area."),
      "move": btn(/Move onto the plate/), "before-slice": T("Before you slice"),
    },
  },
  {
    id: "compat-findings", file: "compat-findings.png", open: DEMO, route: "/compatibility", size: { width: 1230, height: 1000 },
    setup: waitText(/Found \d+ invalid-value issue/),
    scroll: T(/Found \d+ invalid-value issue/),
    targets: {
      "summary": T(/Found \d+ invalid-value issue/), "attention": T("NEEDS ATTENTION"), "do-this": T(/^Do this:/),
     
    },
  },
  {
    id: "move-result", file: "move-result.png", open: DEMO, route: "/compatibility", size: { width: 1230, height: 900 },
    setup: async (p) => {
      await p.getByRole("button", { name: /Move onto the plate/ }).click();
      await p.getByText(/Your original file was not changed/).first().waitFor({ timeout: 60000 });
    },
    scroll: T("Object placement"),
    targets: {
      "summary": T(/moved onto the U1 plate in a new copy/),
      "copy-location": btn("Copy file location"),
    },
  },
  /* ---- lesson 6 : what changed ---- */
  {
    id: "fidelity", file: "fidelity.png", open: DEMO, size: { width: 1230, height: 1000 },
    setup: async (p) => {
      await p.getByRole("button", { name: /^Prepare U1 copy/ }).first().click();
      await p.getByText(/U1 copy created/).first().waitFor({ timeout: 90000 });
      await p.getByText("What survived preparing this copy").first().waitFor({ timeout: 60000 });
    },
    scroll: T("What survived preparing this copy"),
    targets: {
      "survived": T("What survived preparing this copy"),
      "changed": T(/What Studio changed \(\d+\)/), "ledger": T("Changes Studio made"), "return": btn("Return to the original"),
    },
  },

  /* ---- lesson 7 : colours, toolheads, materials ---- */
  {
    id: "colours-overview", file: "colours-overview.png", open: "demo_u1_showcase.3mf", route: "/colors", size: { width: 1230, height: 1000 },
    setup: waitText(/\d+ colours?, \d+ toolheads?/),
    targets: {
      "remap": T("Plate Color Remap"), "verdict": T(/\d+ colours?, \d+ toolheads?/), "explain": T(/^A toolhead is the part/),
    },
  },
  {
    id: "pm-recs", file: "pm-recs.png", open: "demo_u1_showcase.3mf", route: "/compatibility", provider: true, size: { width: 1230, height: 1100 },
    setup: waitText(/Acme Filaments PLA Matte|Northwind PLA/),
    scroll: T("Project materials"),
    targets: {
      "title": T("Project materials"), "candidate": (p) => p.getByRole("button", { name: /#1[12]\b|#2[12]\b/ }).first(),
      "preset": (p) => p.getByText("Orca preset", { exact: true }).first(),
    },
  },
  {
    id: "pm-review", file: "pm-review.png", open: "demo_u1_showcase.3mf", route: "/compatibility", provider: true, size: { width: 1230, height: 1100 },
    setup: async (p) => {
      await p.getByText(/Acme Filaments PLA Matte|Northwind PLA/).first().waitFor({ timeout: 60000 });
      await p.getByRole("button", { name: /#\d+/ }).first().click();
      await p.getByRole("button", { name: "Use this preset" }).first().click();
      await p.getByRole("button", { name: /Review & prepare/ }).click();
      await p.getByText("Review before preparing").first().waitFor({ timeout: 60000 });
    },
    scroll: T("Review before preparing"),
    targets: { "review": T("Review before preparing"), "prepare": btn("Prepare with these choices"), "back": btn("Back to choices") },
  },

  /* ---- lesson 9 : after slicing ---- */
  {
    id: "after-empty", file: "after-empty.png", open: DEMO, route: "/after-slicing",
    targets: {
      "watch": T("Pick up sliced jobs automatically"), "watch-btn": btn("Watch this folder"),
      "open-gcode": T("Open the G-code your slicer produced"), "check": btn("Check this job"),
    },
  },
  {
    id: "after-result", file: "after-result.png", open: DEMO, route: "/after-slicing", size: { width: 1230, height: 1500 },
    setup: async (p, env) => {
      await p.locator("input").last().fill(env.inputs + "\\example_sliced_job.gcode");
      await p.getByRole("button", { name: "Check this job" }).click();
      await p.getByText("Tools this job needs").first().waitFor({ timeout: 90000 });
    },
    targets: {
      "ready": T("Ready to send?"), "cant-check": T(/studio can.t check this/i), "facts": T("What the printer will actually do"),
      "choose-another": btn("Choose another file"),
    },
  },
  {
    id: "after-facts", file: "after-facts.png", open: DEMO, route: "/after-slicing", size: { width: 1230, height: 900 },
    setup: async (p, env) => {
      await p.locator("input").last().fill(env.inputs + "\\example_sliced_job.gcode");
      await p.getByRole("button", { name: "Check this job" }).click();
      await p.getByText("Tools this job needs").first().waitFor({ timeout: 90000 });
    },
    scroll: T("What the printer will actually do"),
    targets: {
      "facts": T("What the printer will actually do"), "sliced-by": T(/sliced by/i), "estimate": T(/estimated time/i),
      "filament": T(/^filament$/i),
    },
  },

  /* ---- lesson 10 : printer ---- */
  {
    id: "printer-hub", file: "printer-hub.png", route: "/printers",
    targets: {
      "connect-title": T("Connect to your U1"), "connect": btn("Connect"), "auto": btn("Auto-detect my U1"),
      "controls": T("Printer controls"),
    },
  },
  {
    id: "settings-printer", file: "settings-printer.png", route: "/settings", size: { width: 1230, height: 1000 },
    scroll: T("Your Snapmaker U1"),
    targets: {
      "address": T(/^Network name or IP\./), "confirmed": T("Confirmed control"),
      "nozzles": T(/Toolhead 1 feeds slot 1/),
    },
  },
  {
    id: "settings-top", file: "settings-top.png", route: "/settings", size: { width: 1230, height: 1000 },
    targets: { "provider": T("Materials provider"), "spoolman": btn("Spoolman"), "spoolease": btn("SpoolEase"), "notes": T(/Your spool notes/) },
  },
  {
    id: "ready-now", file: "ready-now.png", open: DEMO, route: "/ready-now",
    targets: { "title": T("What can I print on my U1 right now?"), "check": btn("Check my library"), "advisory": T(/^Advisory only\./) },
  },

  /* ---- lesson 11 : more tools ---- */
  {
    id: "projects", file: "projects.png", open: DEMO, route: "/projects",
    setup: waitText(DEMO),
    targets: { "title": T("My Designs"), "filters": btn("Needs prep"), "card": T(DEMO) },
  },
  {
    id: "cost", file: "cost.png", open: DEMO, route: "/doctor/cost",
    setup: waitText(/estimated cost/),
    targets: { "cost": T("Cost Doctor"), "price": T(/Pricing Doctor/i), "profit": T(/Profit Doctor/i), "details": T("Show details & assumptions") },
  },
  {
    id: "scale", file: "scale.png", open: "sample_cube.stl", route: "/scale",
    targets: { "title": T("Scale Doctor"), "preview": btn("Preview"), "options": T("Size options for Snapmaker U1") },
  },
  {
    id: "print-quality", file: "print-quality.png", open: DEMO, route: "/print-quality",
    targets: { "title": T("Print Quality Doctor"), "symptom": T("Stringing / wisps"), "model": T(/Using your open model/) },
  },
  {
    id: "batch", file: "batch.png", route: "/batch",
    targets: { "title": T("Prepare a whole batch at once"), "add": btn("Add files") },
  },
  {
    id: "find-models", file: "find-models.png", route: "/find-models", size: { width: 1230, height: 1000 },
    targets: {
      "sites": T("Printables"), "steps": T("Use the site's normal download button"), "open-file": btn("Open downloaded file"),
      "clear": btn(/Clear site data/),
    },
  },

  /* ---- lesson 12 : when something goes wrong ---- */
  {
    id: "help-updates", file: "help-updates.png", route: "/help", size: { width: 1230, height: 1000 },
    scroll: T("Check for a newer version"),
    targets: {
      "update": T("Check for a newer version"), "auto": T("Automatically check for updates"), "now": btn("Check GitHub now"),
      "report": T("Reporting something Studio got wrong"), "show": btn("Show me what it contains"), "save": btn("Save it to a file"),
    },
  },

  /* ---- lesson 8 : needs the INSTALLED app (the desktop shell finds Snapmaker Orca) — see capture-installed.mjs ---- */
  {
    id: "handoff", file: "handoff.png", installed: true, route: "/workspace", size: { width: 1230, height: 1100 },
    setup: async (p) => {
      await p.getByRole("button", { name: /^Prepare U1 copy/ }).first().click();
      await p.getByText(/U1 copy created/).first().waitFor({ timeout: 90000 });
      await p.getByRole("button", { name: /Open in Snapmaker Orca/ }).first().waitFor({ timeout: 30000 });
    },
    targets: {
      "created": T(/U1 copy created/), "what-now": T("What now?"), "open-orca": btn(/Open in Snapmaker Orca/),
      "next-line": (p) => p.getByText(/Next:\s*slice in Snapmaker Orca/).first(),
    },
  },

  /* ---- decision examples: real placement refusals and a real job sliced for another printer ---- */
  {
    id: "placement-oversized", file: "placement-oversized.png", open: "example_oversized.3mf", route: "/compatibility", size: { width: 1230, height: 640 },
    setup: waitText(/Moving the objects as one piece/, 120000),
    scroll: T("Object placement"),
    targets: {
      "object": T(/^Object 1 · 320/), "overhang": T(/Hangs 1\.0 mm past the left edge/), "refusal": T(/Moving the objects as one piece/),
    },
  },
  {
    id: "placement-spread", file: "placement-spread.png", open: "example_spread.3mf", route: "/compatibility", size: { width: 1230, height: 640 },
    setup: waitText(/Moving the objects as one piece/, 120000),
    scroll: T("Object placement"),
    targets: {
      "object": T(/^Object 2 · 10/), "overhang": T(/Hangs 35\.0 mm past the right edge/), "refusal": T(/Moving the objects as one piece/),
    },
  },
  {
    id: "job-other-printer", file: "job-other-printer.png", open: DEMO, route: "/after-slicing", size: { width: 1230, height: 1000 },
    setup: async (p, env) => {
      await p.locator("input").last().fill(env.inputs + "\\example_other_printer.gcode");
      await p.getByRole("button", { name: "Check this job" }).click();
      await p.getByText("Sliced for a different printer").first().waitFor({ timeout: 120000 });
    },
    targets: {
      "ready": T("Ready to send?"), "different": T("Sliced for a different printer"), "do-this": T(/Re-slice this model in Snapmaker Orca/),
      "cant-check": T(/studio can.t check this/i),
    },
  },
];
