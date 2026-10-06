// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useReducer } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversionResult } from "@/api";
import { candidate, mapping, slot } from "@/lib/projectMaterials.fixtures";
import {
  KEEP_OWN_NOTICE, buildSelections, choiceReduce, type Choices, type MaterialPresetList, type ProjectMaterialsAnalysis,
} from "@/lib/projectMaterials";
import { useProvider } from "@/store/provider";

const api = vi.hoisted(() => ({
  projectMaterials: vi.fn(), materialPresets: vi.fn(), convert: vi.fn(), confirmMaterialMapping: vi.fn(),
}));
vi.mock("@/api", () => api);

import { ProjectMaterialsCard, ProjectMaterialsView, ReviewPanel, type ReviewState, type ViewProps } from "./ProjectMaterialsCard";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  useProvider.setState({ kind: "spoolease", url: "192.168.1.50", slotMap: {}, slotBase: 1, key: "" });
});

const PROVEN = mapping({ status: "proven", match_source: "saved_spool", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "" });
const NAMED = mapping({ status: "needs_confirmation", match_source: "exact_name", preset_name: "Snapmaker PLA Matte @U1",
  base_name: "Snapmaker PLA Matte @U1", reason: "The provider names this installed preset. Confirm it to use it and to remember it." });

const PRESETS: MaterialPresetList = {
  available: true, nozzle: "0.4",
  presets: [
    { base_name: "Generic PETG @U1", preset_name: "Generic PETG @U1 0.4 nozzle", vendor: "Generic", filament_type: "PETG", fingerprint: "a" },
    { base_name: "Snapmaker PLA Matte @U1", preset_name: "Snapmaker PLA Matte @U1", vendor: "Snapmaker", filament_type: "PLA", fingerprint: "b" },
    { base_name: "Snapmaker PLA SnapSpeed @U1", preset_name: "Snapmaker PLA SnapSpeed @U1", vendor: "Snapmaker", filament_type: "PLA", fingerprint: "c" },
  ],
};

function analysis(over: Partial<ProjectMaterialsAnalysis> = {}): ProjectMaterialsAnalysis {
  return { schema: "project-materials/1", supported: true, nozzle: "0.4",
    catalog: { available: true, source: { profiles_version: "2.3.6" }, fingerprint: "x" },
    provider: { kind: "spoolease", available: true, error_code: null }, slots: [slot()], ...over };
}

/** The view driven by the real reducer, so a click really changes what is shown. */
function Harness({ a, review = { status: "idle" }, presets = PRESETS, extra }: {
  a: ProjectMaterialsAnalysis; review?: ReviewState; presets?: MaterialPresetList | null; extra?: Partial<ViewProps>;
}) {
  const [choices, dispatch] = useReducer(choiceReduce, {} as Choices);
  return (
    <div className="dark">
      <ProjectMaterialsView load={{ status: "ready" }} analysis={a} presets={presets} providerLabel="SpoolEase" choices={choices}
        dispatch={dispatch} review={review} onReview={() => {}} onBack={() => {}} onPrepare={() => {}} {...extra} />
      <output data-testid="request">{JSON.stringify(buildSelections(choices))}</output>
    </div>
  );
}

const request = () => JSON.parse(screen.getByTestId("request").textContent || "[]");
const choose = (name: RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const reviewButton = () => screen.getByRole("button", { name: /Review & prepare/ }) as HTMLButtonElement;

describe("one slot, happy path", () => {
  it("shows the source, the candidate and its facts, and nothing is selected until the person chooses", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: PROVEN, loaded_slot: 2,
      reasons: [{ code: "material_exact", text: "Material matches: PLA" }, { code: "preset_proven", text: "Preset proven: Snapmaker PLA Matte @U1" },
        { code: "weight_enough", text: "Enough filament: 412 g available / 180 g needed" }, { code: "loaded", text: "Already loaded in slot 3" }] })] })] })} />);
    expect(screen.getByText("Slot 1")).toBeTruthy();                                   // 1-based
    expect(screen.getByText("180 g needed (the source file's own slice)")).toBeTruthy();
    expect(screen.getByText(/now “Generic PLA @BBL H2D”/)).toBeTruthy();
    const row = screen.getByRole("button", { name: /Yoopai PLA Matte/ });
    expect(row.getAttribute("aria-pressed")).toBe("false");                           // no auto-selection
    expect(within(row).getByText("Red")).toBeTruthy();
    expect(within(row).getByText("#124")).toBeTruthy();
    expect(within(row).getByText("412 g tracked")).toBeTruthy();
    expect(within(row).getByText("Proven")).toBeTruthy();
    expect(within(row).getByTestId("swatch").getAttribute("style")).toContain("rgb(255, 0, 0)");
    expect(screen.queryByTestId("selected-spool")).toBeNull();
    expect(request()).toEqual([]);
    expect(reviewButton().disabled).toBe(true);
  });

  it("choosing the spool selects it with its remembered, proven preset, and Review becomes available", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: PROVEN })] })] })} />);
    choose(/Yoopai PLA Matte/);
    const selected = screen.getByTestId("selected-spool");
    expect(selected.textContent).toContain("Selected spool · from SpoolEase at selection time");
    expect(within(screen.getByTestId("preset-area")).getByText("Snapmaker PLA Matte @U1")).toBeTruthy();
    expect(within(screen.getByTestId("preset-area")).getByText("Proven")).toBeTruthy();
    expect(screen.getByTestId("match-source").textContent).toBe("Saved for this spool");
    expect(reviewButton().disabled).toBe(false);
    expect(request()).toEqual([expect.objectContaining({ slot: 0, preset: "Snapmaker PLA Matte @U1", colour: "#FF0000" })]);
  });
});

describe("a multi-colour model", () => {
  it("lists every slot, 1-based, and keeps the choices apart", () => {
    const slots = [
      slot({ slot: 0, colour: "#FF0000", candidates: [candidate({ spool_id: "1", colour: "#FF0000", mapping: PROVEN })] }),
      slot({ slot: 1, colour: "#00FF00", candidates: [candidate({ spool_id: "2", colour: "#00FF00", color_name: "green", mapping: PROVEN })] }),
      slot({ slot: 2, colour: "#0000FF", material: "PETG", family: "PETG", candidates: [] }),
    ];
    render(<Harness a={analysis({ slots })} />);
    expect(["Slot 1", "Slot 2", "Slot 3"].every((t) => screen.queryByText(t))).toBe(true);
    fireEvent.click(within(document.querySelector('[data-slot="2"]') as HTMLElement).getByRole("button", { name: /Yoopai/ }));
    expect(request().map((r: any) => r.slot)).toEqual([1]);
    fireEvent.click(within(document.querySelector('[data-slot="1"]') as HTMLElement).getByRole("button", { name: /Yoopai/ }));
    expect(request().map((r: any) => [r.slot, r.colour])).toEqual([[0, "#FF0000"], [1, "#00FF00"]]);
    expect(within(document.querySelector('[data-slot="3"]') as HTMLElement).getByTestId("no-candidates")).toBeTruthy();
  });
});

describe("no candidates", () => {
  it("says so and still offers an installed preset and Keep project's filament", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [], candidate_count: 0 })] })} />);
    expect(screen.getByTestId("no-candidates").textContent).toBe("No spool in your inventory matches this material.");
    expect(screen.getByRole("button", { name: "Choose an installed preset" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Keep project's filament/ })).toBeTruthy();
  });
});

describe("a preset that needs confirmation", () => {
  it("is obvious, holds Review back, and is only sent once the person confirms it", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: NAMED })] })] })} />);
    choose(/Yoopai PLA Matte/);
    const area = screen.getByTestId("preset-area");
    expect(within(area).getByText("Needs confirmation").getAttribute("data-status")).toBe("needs_confirmation");
    expect(within(area).getByText(NAMED.reason)).toBeTruthy();                         // the engine's words, verbatim
    expect(reviewButton().disabled).toBe(true);
    expect(screen.getByTestId("confirm-first").textContent).toBe("Confirm the highlighted preset first.");
    expect(request()[0].preset).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Confirm this preset/ }));
    expect(reviewButton().disabled).toBe(false);
    expect(request()[0].preset).toBe("Snapmaker PLA Matte @U1");
    expect(screen.queryByTestId("confirm-first")).toBeNull();
  });

  it("a stale saved mapping is called out on the candidate and never applied by itself", () => {
    const stale = mapping({ status: "needs_confirmation", match_source: "saved_spool", stale: true, preset_name: "Snapmaker PLA Matte @U1",
      base_name: "Snapmaker PLA Matte @U1", reason: "The installed preset with this name is no longer the one you confirmed." });
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: stale })] })] })} />);
    const row = screen.getByRole("button", { name: /Yoopai PLA Matte/ });
    expect(within(row).getByText("Saved mapping is out of date")).toBeTruthy();
    expect(within(row).getByText("Needs confirmation")).toBeTruthy();
    expect(within(row).getByText(stale.reason)).toBeTruthy();
    choose(/Yoopai PLA Matte/);
    expect(request()[0].preset).toBeNull();
    expect(reviewButton().disabled).toBe(true);
  });
});

describe("choosing a preset by hand", () => {
  it("searches the installed presets the engine returned and takes the pick as the confirmation", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate()] })] })} />);
    choose(/Yoopai PLA Matte/);
    expect(within(screen.getByTestId("preset-area")).getByText("No match")).toBeTruthy();
    expect(request()[0].preset).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Choose an installed preset" }));
    const options = () => screen.getAllByRole("option").map((o) => o.textContent);
    expect(options().length).toBe(3);
    expect(options()[0]).toContain("fits 0.4 mm nozzle");
    fireEvent.change(screen.getByLabelText(/Search installed presets for slot 1/), { target: { value: "snapspeed" } });
    expect(options()).toEqual([expect.stringContaining("Snapmaker PLA SnapSpeed @U1")]);
    fireEvent.click(screen.getAllByRole("option")[0].querySelector("button")!);
    expect(request()[0].preset).toBe("Snapmaker PLA SnapSpeed @U1");
    expect(screen.getByTestId("match-source").textContent).toBe("Chosen by you");
    expect(within(screen.getByTestId("preset-area")).getByText("Proven")).toBeTruthy();
  });

  it("offers the engine's suggestion as Needs confirmation, to be used only on request", () => {
    const suggestion = { status: "needs_confirmation" as const, preset_name: "Generic PETG @U1 0.4 nozzle", base_name: "Generic PETG @U1",
      reason: "Generic PETG is installed for this nozzle. Studio suggests it but does not choose between presets for you." };
    render(<Harness a={analysis({ slots: [slot({ candidates: [], suggestion })] })} />);
    expect(screen.getByText(suggestion.reason)).toBeTruthy();
    expect(request()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Use this preset" }));
    expect(screen.getByText("Generic PETG @U1", { selector: "span" })).toBeTruthy();
  });

  it("does not offer a picker when no installed Orca presets were found", () => {
    render(<Harness presets={{ available: false, nozzle: "0.4", presets: [] }} a={analysis({ catalog: { available: false, source: null, fingerprint: null } })} />);
    expect(screen.getByTestId("no-orca").textContent).toContain("could not find Snapmaker Orca's installed filament presets");
    expect(screen.queryByRole("button", { name: /installed preset/ })).toBeNull();
  });
});

describe("Remember this mapping", () => {
  it("is offered only for a confirmed pair, saves nothing itself, and offers the two scopes", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate()] })] })} />);
    choose(/Yoopai PLA Matte/);
    expect(screen.queryByTestId("remember")).toBeNull();                               // no confirmed preset yet
    fireEvent.click(screen.getByRole("button", { name: "Choose an installed preset" }));
    fireEvent.click(screen.getAllByRole("option")[2].querySelector("button")!);
    const box = screen.getByLabelText("Remember this mapping") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect((screen.getByLabelText("For this spool only") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByLabelText("For similar spools"));
    expect((screen.getByLabelText("For similar spools") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId("remember").textContent).toContain("Saved on this computer only when you prepare.");
    expect(api.confirmMaterialMapping).not.toHaveBeenCalled();
  });

  it("is not offered for Keep project's filament", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: PROVEN })] })] })} />);
    choose(/Yoopai PLA Matte/);
    fireEvent.click(screen.getByRole("button", { name: /Keep project's filament/ }));
    expect(screen.queryByTestId("remember")).toBeNull();
  });
});

describe("Keep project's filament", () => {
  it("shows the exact notice and sends no preset", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: PROVEN })] })] })} />);
    choose(/Yoopai PLA Matte/);
    fireEvent.click(screen.getByRole("button", { name: /Keep project's filament/ }));
    expect(screen.getByTestId("keep-own-notice").textContent).toBe(KEEP_OWN_NOTICE);
    expect(request()).toEqual([expect.objectContaining({ slot: 0, preset: null, colour: "#FF0000" })]);   // only the spool's colour
    fireEvent.click(screen.getByRole("button", { name: "Clear preset choice" }));
    expect(screen.queryByTestId("keep-own-notice")).toBeNull();
  });
});

describe("a close call", () => {
  it("shows the hint when the engine says the top choices are close, and not otherwise", () => {
    const two = [candidate({ spool_id: "1" }), candidate({ spool_id: "2" })];
    const { unmount } = render(<Harness a={analysis({ slots: [slot({ candidates: two, close_call: true })] })} />);
    expect(screen.getByTestId("close-call").textContent).toContain("very close");
    unmount();
    render(<Harness a={analysis({ slots: [slot({ candidates: two, close_call: false })] })} />);
    expect(screen.queryByTestId("close-call")).toBeNull();
  });
});

describe("states", () => {
  it("shows loading, a read error, and an unsupported project", () => {
    const base = { analysis: null, presets: null, providerLabel: null, choices: {}, dispatch: () => {}, review: { status: "idle" } as ReviewState,
      onReview: () => {}, onBack: () => {}, onPrepare: () => {} };
    const { unmount } = render(<ProjectMaterialsView {...base} load={{ status: "loading" }} />);
    expect(screen.getByText(/Reading your project and your spool list/)).toBeTruthy();
    unmount();
    const second = render(<ProjectMaterialsView {...base} load={{ status: "error", error: "boom" }} />);
    expect(screen.getByRole("alert").textContent).toContain("boom");
    second.unmount();
    const third = render(<ProjectMaterialsView {...base} load={{ status: "ready" }} analysis={{ schema: "x", supported: false, reason: "An STL has no filament slots. Open a 3MF project." }} />);
    expect(third.container.innerHTML).toBe("");          // no empty picker for a project with nothing to map
    third.unmount();
    const fourth = render(<ProjectMaterialsView {...base} load={{ status: "ready" }} analysis={{ schema: "x", supported: true, slots: [] }} />);
    expect(fourth.container.innerHTML).toBe("");
  });

  it("says when the provider could not be read, and when none is set up", () => {
    const { unmount } = render(<Harness a={analysis({ provider: { kind: "spoolease", available: false, error_code: "unreachable" }, slots: [slot({ candidates: [] })] })} />);
    expect(screen.getByTestId("provider-down").textContent).toContain("could not read your spool provider");
    expect(screen.getByRole("button", { name: /Keep project's filament/ })).toBeTruthy();   // still usable
    unmount();
    render(<Harness a={analysis({ provider: null, slots: [slot({ candidates: [] })] })} />);
    expect(screen.getByTestId("no-provider").textContent).toContain("No spool provider is set up");
  });
});

describe("what the engine says is shown as it was sent", () => {
  it("reasons are rendered verbatim, in the engine's order, with nothing added or recomputed", () => {
    const reasons = [
      { code: "zz", text: "Zebra-9 quartz reason that no desktop would write" },
      { code: "colour_distance", text: "Colour distance: 8", data: { distance: 8 } },
      { code: "weight_enough", text: "Enough filament: 412 g available / 180 g needed" },
    ];
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ reasons })] })] })} />);
    const row = screen.getByRole("button", { name: /Yoopai PLA Matte/ });
    const items = within(row).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(reasons.map((r) => r.text));
  });

  it("the order of candidates is the engine's, even when another order would look tidier", () => {
    const list = [candidate({ spool_id: "9", vendor: "Zed" }), candidate({ spool_id: "1", vendor: "Acme" })];
    render(<Harness a={analysis({ slots: [slot({ candidates: list })] })} />);
    const names = screen.getAllByRole("button", { name: /#/ }).map((b) => b.textContent);
    expect(names[0]).toContain("Zed");
    expect(names[1]).toContain("Acme");
  });

  it("the physical spool is labelled as selected and provider data, never as verified", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: PROVEN })] })] })} />);
    choose(/Yoopai PLA Matte/);
    const text = screen.getByTestId("selected-spool").textContent ?? "";
    expect(text).toContain("Selected spool");
    expect(text).toContain("from SpoolEase at selection time");
    expect(text).toContain("They are not read from the project file");
    expect(text).not.toMatch(/verified|file-checked|confirmed by the file/i);
  });
});

describe("review and blocked", () => {
  const result = (over: Partial<ConversionResult> = {}): ConversionResult => ({
    schema_version: "convert/2", prepare_mode: "preserve", output_path: "", output_name: "", validated_ok: true, errors: [],
    settings_summary: {} as any, ...over });

  it("shows the engine's plain-language lines, and says spool facts are not file-verified", () => {
    const lines = ["Slot 1: Yoopai PLA+ Red #124 mapped to 'Generic PLA @U1'. Colour changed to Red. Temperature, flow and cooling come from the installed Generic PLA @U1 preset."];
    render(<ReviewPanel review={{ status: "done", result: result({ settings_summary: { project_materials: { fidelity: {
      schema: "x", mode: "preserve", lines, slots: [{ slot: 0, label: "Slot 1", involved: true, line: lines[0], discrepancies: [
        { code: "vendor_mismatch", text: "The provider lists Yoopai; the installed preset's vendor is Generic. Studio did not override it." }] }] } } } as any }) }}
      providerLabel="SpoolEase" onPrepare={() => {}} onBack={() => {}} />);
    expect(screen.getByText(lines[0])).toBeTruthy();
    expect(screen.getByText(/Slot 1: The provider lists Yoopai/)).toBeTruthy();
    expect(screen.getByTestId("review").textContent).toContain("from SpoolEase at selection time; they are not read from the file");
    expect(screen.getByRole("button", { name: "Prepare with these choices" })).toBeTruthy();
  });

  it("a blocked Prepare shows the slots, the shared preset, the conflicting key and the engine's own resolution", () => {
    const blocked = result({ blocked: true, errors: ["Prepare stopped: slots 1, 2 share “Snapmaker PLA Matte @U1” but disagree on filament_vendor."],
      settings_summary: { project_materials: { guard: { applies: true, blocking: true, shared: [], warnings: [],
        resolution: "Choose a different installed preset for each slot, or remove the declaration in the source project.",
        conflicts: [{ key: "filament_vendor", preset: "Snapmaker PLA Matte @U1", slots: [0, 1], declared_in: [0], values: {} }] } } } as any });
    render(<ReviewPanel review={{ status: "done", result: blocked }} providerLabel={null} onPrepare={() => {}} onBack={() => {}} />);
    const box = screen.getByTestId("blocked");
    expect(box.textContent).toContain("Prepare stopped");
    expect(screen.getByText(/disagree on filament_vendor/)).toBeTruthy();
    expect(screen.getByTestId("blocked-conflict").textContent).toBe("Slots 1, 2 share “Snapmaker PLA Matte @U1” · conflicting: filament_vendor");
    expect(screen.getByTestId("blocked-resolution").textContent).toBe("Choose a different installed preset for each slot, or remove the declaration in the source project.");
    expect(screen.queryByRole("button", { name: "Prepare with these choices" })).toBeNull();   // nothing to prepare
  });

  it("says the resolution once when the engine's message already carries it", () => {
    const resolution = "Choose a different installed preset for each slot.";
    const blocked = result({ blocked: true, errors: [`Prepare stopped: slots 1, 2 share P. ${resolution}`],
      settings_summary: { project_materials: { guard: { applies: true, blocking: true, shared: [], warnings: [], resolution,
        conflicts: [{ key: "filament_type", preset: "P @U1", slots: [0, 1], declared_in: [0], values: {} }] } } } as any });
    render(<ReviewPanel review={{ status: "done", result: blocked }} providerLabel={null} onPrepare={() => {}} onBack={() => {}} />);
    expect(screen.getByTestId("blocked").textContent?.split(resolution).length).toBe(2);   // appears exactly once
    expect(screen.queryByTestId("blocked-resolution")).toBeNull();
  });

  it("shows a check in progress and a check that failed", () => {
    const { unmount } = render(<ReviewPanel review={{ status: "loading" }} providerLabel={null} onPrepare={() => {}} onBack={() => {}} />);
    expect(screen.getByText(/Checking your choices/)).toBeTruthy();
    unmount();
    render(<ReviewPanel review={{ status: "error", error: "no answer" }} providerLabel={null} onPrepare={() => {}} onBack={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain("no answer");
  });
});

describe("the card end to end", () => {
  const ready = () => {
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [candidate()] })] }));
    api.materialPresets.mockResolvedValue(PRESETS);
  };

  it("asks for nothing to be saved or prepared until the person says so", async () => {
    ready();
    const onPrepare = vi.fn();
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={onPrepare} />);
    expect(screen.getByText(/Reading your project/)).toBeTruthy();                        // loading first
    await screen.findByText("Slot 1");
    expect(api.projectMaterials).toHaveBeenCalledWith("C:/p/x.3mf", expect.objectContaining({ provider: "spoolease", provider_url: "192.168.1.50" }), 3);
    expect(api.materialPresets).toHaveBeenCalledWith("0.4");
    expect(onPrepare).not.toHaveBeenCalled();
    expect(api.convert).not.toHaveBeenCalled();
    expect(api.confirmMaterialMapping).not.toHaveBeenCalled();
  });

  it("reviews with a dry run, then saves a ticked mapping only after a copy was made, and hands over the selections", async () => {
    ready();
    const lines = ["Slot 1: Yoopai PLA Matte Red #124 mapped to 'Snapmaker PLA SnapSpeed @U1'."];
    api.convert.mockResolvedValue({ schema_version: "convert/2", prepare_mode: "preserve", output_path: "", output_name: "", validated_ok: true,
      settings_summary: { project_materials: { fidelity: { schema: "x", mode: "preserve", lines, slots: [] } } } });
    api.confirmMaterialMapping.mockResolvedValue({ ok: true });
    const order: string[] = [];
    const onPrepare = vi.fn(async () => { order.push("prepare"); return { output_path: "C:/p/out.3mf", blocked: false } as any; });
    api.confirmMaterialMapping.mockImplementation(async () => { order.push("save"); return { ok: true }; });
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="recommended" onPrepare={onPrepare} />);
    await screen.findByText("Slot 1");
    choose(/Yoopai PLA Matte/);
    fireEvent.click(screen.getByRole("button", { name: "Choose an installed preset" }));
    fireEvent.click(screen.getAllByRole("option")[2].querySelector("button")!);
    fireEvent.click(screen.getByLabelText("Remember this mapping"));
    fireEvent.click(screen.getByLabelText("For similar spools"));
    await act(async () => { fireEvent.click(reviewButton()); });
    await screen.findByText(lines[0]);
    expect(api.convert).toHaveBeenCalledWith("C:/p/x.3mf", undefined, "recommended", true,
      [expect.objectContaining({ slot: 0, preset: "Snapmaker PLA SnapSpeed @U1", colour: "#FF0000" })]);
    expect(api.confirmMaterialMapping).not.toHaveBeenCalled();                            // reviewing saves nothing
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Prepare with these choices" })); });
    await waitFor(() => expect(api.confirmMaterialMapping).toHaveBeenCalledTimes(1));
    expect(order).toEqual(["prepare", "save"]);                                           // saved only once the copy exists
    expect(api.confirmMaterialMapping).toHaveBeenCalledWith({ scope: "signature", provider: "spoolease", vendor: "Yoopai", material: "PLA",
      subtype: "Matte", preset: "Snapmaker PLA SnapSpeed @U1", nozzle: "0.4", origin: "manual" });
    expect(onPrepare).toHaveBeenCalledWith([expect.objectContaining({ slot: 0, preset: "Snapmaker PLA SnapSpeed @U1" })]);
  });

  it("an unticked Remember saves nothing, and backing out of the review does not prepare", async () => {
    ready();
    api.convert.mockResolvedValue({ schema_version: "convert/2", prepare_mode: "preserve", output_path: "", output_name: "", validated_ok: true,
      settings_summary: { project_materials: { fidelity: { schema: "x", mode: "preserve", lines: ["A line."], slots: [] } } } });
    const onPrepare = vi.fn();
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={onPrepare} />);
    await screen.findByText("Slot 1");
    choose(/Yoopai PLA Matte/);
    fireEvent.click(screen.getByRole("button", { name: /Keep project's filament/ }));
    await act(async () => { fireEvent.click(reviewButton()); });
    await screen.findByText("A line.");
    fireEvent.click(screen.getByRole("button", { name: "Back to choices" }));
    expect(onPrepare).not.toHaveBeenCalled();
    expect(api.confirmMaterialMapping).not.toHaveBeenCalled();
    expect(screen.queryByTestId("review")).toBeNull();
  });

  it("a blocked dry run shows the engine's explanation and offers no Prepare", async () => {
    ready();
    api.convert.mockResolvedValue({ schema_version: "convert/2", prepare_mode: "preserve", output_path: "", output_name: "", validated_ok: false, blocked: true,
      errors: ["Prepare stopped: conflict."], settings_summary: { project_materials: { guard: { applies: true, blocking: true, shared: [], warnings: [],
        resolution: "Engine resolution text.", conflicts: [{ key: "filament_type", preset: "P @U1", slots: [0, 2], declared_in: [0], values: {} }] } } } });
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={vi.fn()} />);
    await screen.findByText("Slot 1");
    choose(/Yoopai PLA Matte/);
    fireEvent.click(screen.getByRole("button", { name: /Keep project's filament/ }));
    await act(async () => { fireEvent.click(reviewButton()); });
    await screen.findByTestId("blocked");
    expect(screen.getByTestId("blocked-resolution").textContent).toBe("Engine resolution text.");
    expect(screen.getByTestId("blocked-conflict").textContent).toContain("Slots 1, 3 share “P @U1”");
    expect(screen.queryByRole("button", { name: "Prepare with these choices" })).toBeNull();
  });

  it("shows a read failure from the engine", async () => {
    api.projectMaterials.mockRejectedValue(new Error("engine down"));
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={vi.fn()} />);
    await screen.findByText(/engine down/);
  });

  it("reports whether it holds choices so a plain Prepare is not offered beside them", async () => {
    ready();
    const active = vi.fn();
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={vi.fn()} onActiveChange={active} />);
    await screen.findByText("Slot 1");
    expect(active).toHaveBeenLastCalledWith(false);
    choose(/Yoopai PLA Matte/);
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(true));
  });

  it("does not ask the engine for a provider read when none is configured", async () => {
    useProvider.setState({ kind: "none", url: "" });
    api.projectMaterials.mockResolvedValue(analysis({ provider: null, slots: [slot({ candidates: [] })] }));
    api.materialPresets.mockResolvedValue(PRESETS);
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={vi.fn()} />);
    await screen.findByTestId("no-provider");
    expect(api.projectMaterials).toHaveBeenCalledWith("C:/p/x.3mf", {}, 3);
  });
});


describe("the card after the review repairs", () => {
  const stage = async (onPrepare: (s: any) => any, mode: "preserve" | "recommended" = "preserve") => {
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ candidates: [candidate()] })] }));
    api.materialPresets.mockResolvedValue(PRESETS);
    api.convert.mockResolvedValue({ schema_version: "convert/2", prepare_mode: mode, output_path: "", output_name: "", validated_ok: true,
      settings_summary: { project_materials: { fidelity: { schema: "x", mode, lines: ["A line."], slots: [] } } } });
    api.confirmMaterialMapping.mockResolvedValue({ ok: true });
    const view = render(<ProjectMaterialsCard path="C:/p/x.3mf" mode={mode} onPrepare={onPrepare} />);
    await screen.findByText("Slot 1");
    choose(/Yoopai PLA Matte/);
    fireEvent.click(screen.getByRole("button", { name: "Choose an installed preset" }));
    fireEvent.click(screen.getAllByRole("option")[2].querySelector("button")!);
    fireEvent.click(screen.getByLabelText("Remember this mapping"));
    await act(async () => { fireEvent.click(reviewButton()); });
    await screen.findByText("A line.");
    return view;
  };

  it("saves nothing when Prepare was blocked, wrote no file, or failed", async () => {
    for (const outcome of [
      async () => ({ blocked: true, output_path: "" }),
      async () => ({ blocked: false, output_path: "" }),
      async () => { throw new Error("prepare failed"); },
      () => undefined,
    ]) {
      api.confirmMaterialMapping.mockClear();
      const { unmount } = await stage(outcome);
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Prepare with these choices" })); });
      await new Promise((r) => setTimeout(r, 20));
      expect(api.confirmMaterialMapping).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("a review does not survive a change of preparation mode", async () => {
    const view = await stage(async () => ({ output_path: "C:/o.3mf" }), "recommended");
    expect(screen.getByTestId("review")).toBeTruthy();
    view.rerender(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={async () => undefined} />);
    await waitFor(() => expect(screen.queryByTestId("review")).toBeNull());
    expect(reviewButton().disabled).toBe(false);                                           // review again for the new mode
  });
});
