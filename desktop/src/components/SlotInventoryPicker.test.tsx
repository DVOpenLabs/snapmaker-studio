// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useReducer } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { candidate, mapping, slot } from "@/lib/projectMaterials.fixtures";
import {
  SPOOL_WITHOUT_PRESET, buildSelections, choiceReduce, type Choices, type MaterialInventory, type ProjectMaterialsAnalysis,
} from "@/lib/projectMaterials";
import { useProvider } from "@/store/provider";

const api = vi.hoisted(() => ({
  projectMaterials: vi.fn(), materialPresets: vi.fn(), convert: vi.fn(), confirmMaterialMapping: vi.fn(),
  projectMaterialsInventory: vi.fn(),
}));
vi.mock("@/api", () => api);

import { ProjectMaterialsCard, ProjectMaterialsView } from "./ProjectMaterialsCard";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  useProvider.setState({ kind: "spoolease", url: "192.168.1.50", slotMap: {}, slotBase: 1, key: "" });
});

const PROVEN = mapping({ status: "proven", match_source: "saved_spool", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "" });
const PETG_WARNING = "This spool is PETG; the model asks for PLA. Choosing it is allowed, but check that you really want a different material.";

// The model asks for red PLA. The person's inventory also holds blue PLA, and a PETG spool.
const RED = candidate({ spool_id: "1", colour: "#FF0000", color_name: "red", family_match: true, warnings: [] });
const BLUE = candidate({ spool_id: "2", colour: "#0000FF", color_name: "blue", subtype: "Basic", label: "Yoopai PLA Basic", family_match: true, warnings: [],
  reasons: [{ code: "colour_distance", text: "Colour distance: 360" }], mapping: PROVEN });
const PETG = candidate({ spool_id: "3", colour: "#00FF00", color_name: "green", material: "PETG", subtype: null, label: "Yoopai PETG", family_match: false,
  warnings: [{ code: "material_family_differs", requires_confirmation: true, text: PETG_WARNING }],
  reasons: [{ code: "material_differs", text: PETG_WARNING }] });
const INVENTORY: MaterialInventory = { supported: true, slot: 0, provider: { kind: "spoolease", available: true, error_code: null },
  entries: [RED, BLUE, PETG], count: 3, same_family_count: 2 };

function analysis(over: Partial<ProjectMaterialsAnalysis> = {}): ProjectMaterialsAnalysis {
  return { schema: "project-materials/1", supported: true, nozzle: "0.4",
    catalog: { available: true, source: { profiles_version: "2.3.6" }, fingerprint: "x" },
    provider: { kind: "spoolease", available: true, error_code: null }, slots: [slot({ candidates: [RED], candidate_count: 1 })], ...over };
}

function Harness({ a, load }: { a: ProjectMaterialsAnalysis; load?: (slot: number) => Promise<MaterialInventory> }) {
  const [choices, dispatch] = useReducer(choiceReduce, {} as Choices);
  return (
    <div className="dark">
      <ProjectMaterialsView load={{ status: "ready" }} analysis={a} presets={null} providerLabel="SpoolEase" choices={choices}
        dispatch={dispatch} review={{ status: "idle" }} onReview={() => {}} onBack={() => {}} onPrepare={() => {}} loadInventory={load} />
      <output data-testid="request">{JSON.stringify(buildSelections(choices))}</output>
    </div>
  );
}
const request = () => JSON.parse(screen.getByTestId("request").textContent || "[]");
const open = async (load = vi.fn().mockResolvedValue(INVENTORY)) => {
  render(<Harness a={analysis()} load={load} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose another spool" }));
  await screen.findByTestId("inventory-picker");
  await screen.findByLabelText(/Find a spool for slot 1/);
  return load;
};

describe("Choose another spool", () => {
  it("is offered only when the provider could be read", () => {
    const load = vi.fn();
    const { unmount } = render(<Harness a={analysis()} load={load} />);
    expect(screen.getByRole("button", { name: "Choose another spool" })).toBeTruthy();
    unmount();
    render(<Harness a={analysis({ provider: { kind: "spoolease", available: false, error_code: "unreachable" } })} load={load} />);
    expect(screen.queryByRole("button", { name: "Choose another spool" })).toBeNull();
    cleanup();
    render(<Harness a={analysis({ provider: null })} load={load} />);
    expect(screen.queryByRole("button", { name: "Choose another spool" })).toBeNull();
    expect(load).not.toHaveBeenCalled();                    // nothing is read until the person asks
  });

  it("lists the whole inventory for that slot, not only the engine's short list, with the facts that tell spools apart", async () => {
    const load = await open();
    expect(load).toHaveBeenCalledWith(0);
    const picker = screen.getByTestId("inventory-picker");
    const rows = within(picker).getAllByRole("button", { name: /Yoopai/ });
    expect(rows).toHaveLength(3);                                    // red, blue and the PETG
    const blue = within(picker).getByRole("button", { name: /Blue/ });
    expect(blue.textContent).toContain("Yoopai PLA Basic");          // vendor, material, subtype
    expect(blue.textContent).toContain("Blue");                      // colour name
    expect(blue.textContent).toContain("#2");                        // spool id
    expect(blue.textContent).toContain("412 g tracked");             // weight status
    expect(blue.textContent).toContain("Orca preset: Proven · Snapmaker PLA Matte @U1");
    expect(within(picker).getAllByTestId("preset-status")).toHaveLength(3);
    // same-material spools are listed first, the other material under its own heading
    expect(within(picker).getByText("Same material")).toBeTruthy();
    expect(within(picker).getByText(/Different material — you will be asked to confirm/)).toBeTruthy();
  });

  it("narrows by what is typed", async () => {
    await open();
    fireEvent.change(screen.getByLabelText(/Find a spool for slot 1/), { target: { value: "petg" } });
    const picker = screen.getByTestId("inventory-picker");
    expect(within(picker).getAllByRole("button", { name: /Yoopai/ })).toHaveLength(1);
    fireEvent.change(screen.getByLabelText(/Find a spool for slot 1/), { target: { value: "#2" } });
    expect(within(picker).getByRole("button", { name: /Blue/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Find a spool for slot 1/), { target: { value: "zzzz" } });
    expect(within(picker).getByText(/No spool matches/)).toBeTruthy();
  });

  it("lets the person choose a different colour of the same material without a warning or a blocker", async () => {
    await open();
    fireEvent.click(within(screen.getByTestId("inventory-picker")).getByRole("button", { name: /Blue/ }));
    expect(screen.queryByTestId("family-confirm")).toBeNull();
    expect(screen.queryByTestId("inventory-picker")).toBeNull();      // closed once chosen
    expect(screen.getByTestId("selected-spool").textContent).toContain("#2");
    // the model's red slot now takes the blue spool's colour, and the proven preset it carried
    expect(request()).toEqual([expect.objectContaining({ slot: 0, colour: "#0000FF", preset: "Snapmaker PLA Matte @U1" })]);
  });

  it("never selects a spool of another material until the person confirms, and shows the engine's warning first", async () => {
    await open();
    fireEvent.click(within(screen.getByTestId("inventory-picker")).getByRole("button", { name: /Green/ }));
    const confirm = screen.getByTestId("family-confirm");
    expect(confirm.textContent).toContain(PETG_WARNING);
    expect(request()).toEqual([]);                                    // nothing chosen yet
    expect(screen.queryByTestId("selected-spool")).toBeNull();
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("family-confirm")).toBeNull();
    expect(request()).toEqual([]);                                    // cancelling chooses nothing
    fireEvent.click(within(screen.getByTestId("inventory-picker")).getByRole("button", { name: /Green/ }));
    fireEvent.click(within(screen.getByTestId("family-confirm")).getByRole("button", { name: "Use this spool anyway" }));
    expect(screen.getByTestId("selected-spool").textContent).toContain("#3");
    expect(request()).toEqual([expect.objectContaining({ slot: 0, colour: "#00FF00" })]);
  });

  it("says why when the inventory could not be read, and chooses nothing", async () => {
    const load = vi.fn().mockRejectedValue(new Error("provider went away"));
    render(<Harness a={analysis()} load={load} />);
    fireEvent.click(screen.getByRole("button", { name: "Choose another spool" }));
    expect((await screen.findByRole("alert")).textContent).toContain("provider went away");
    expect(request()).toEqual([]);
  });

  it("can be closed without choosing", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Close the spool list" }));
    expect(screen.queryByTestId("inventory-picker")).toBeNull();
    expect(request()).toEqual([]);
  });
});

describe("a spool with no Orca preset", () => {
  it("says the project's existing filament preset will remain, in the exact words", () => {
    render(<Harness a={analysis()} />);
    fireEvent.click(screen.getByRole("button", { name: /Yoopai PLA Matte/ }));
    expect(screen.getByTestId("spool-without-preset").textContent).toBe(SPOOL_WITHOUT_PRESET);
    expect(SPOOL_WITHOUT_PRESET).toBe("Spool selected, but no Orca preset selected. The project's existing filament preset will remain.");
    expect(request()).toEqual([expect.objectContaining({ slot: 0, preset: null, colour: "#FF0000" })]);   // colour only
  });

  it("is not shown once a preset is chosen, or when the project's filament is kept on purpose", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ mapping: PROVEN })] })] })} />);
    fireEvent.click(screen.getByRole("button", { name: /Yoopai PLA Matte/ }));          // arrives with its proven preset
    expect(screen.queryByTestId("spool-without-preset")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear preset choice" }));
    expect(screen.getByTestId("spool-without-preset")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep project's filament" }));
    expect(screen.queryByTestId("spool-without-preset")).toBeNull();
  });

  it("says nothing will change when the spool has no colour either", () => {
    render(<Harness a={analysis({ slots: [slot({ candidates: [candidate({ colour: null, color_name: null })] })] })} />);
    fireEvent.click(screen.getByRole("button", { name: /Yoopai PLA Matte/ }));
    expect(screen.getByTestId("spool-without-preset").textContent).toContain("nothing about this slot will change");
    expect(request()).toEqual([]);
  });
});

describe("the card reads the inventory through the engine", () => {
  it("asks for the slot the person is browsing, with the provider they set up", async () => {
    api.projectMaterials.mockResolvedValue(analysis({ slots: [slot({ slot: 2, candidates: [RED], candidate_count: 1 })] }));
    api.materialPresets.mockResolvedValue({ available: true, nozzle: "0.4", presets: [] });
    api.projectMaterialsInventory.mockResolvedValue(INVENTORY);
    render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={vi.fn()} />);
    await screen.findByText("Slot 3");
    expect(api.projectMaterialsInventory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Choose another spool" }));
    await waitFor(() => expect(api.projectMaterialsInventory).toHaveBeenCalledWith(
      "C:/p/x.3mf", 2, expect.objectContaining({ provider: "spoolease", provider_url: "192.168.1.50" })));
    await act(async () => {});
  });
});
