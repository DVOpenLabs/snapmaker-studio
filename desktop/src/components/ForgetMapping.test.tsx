// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { candidate, mapping, slot } from "@/lib/projectMaterials.fixtures";
import {
  forgetRequest, forgetWording, savedScope, slotsCoveredBy, choiceReduce, type Choices, type ProjectMaterialsAnalysis,
} from "@/lib/projectMaterials";
import { useProvider } from "@/store/provider";

// Every call is a mock: no provider, printer, Orca file or project file is touched.
const api = vi.hoisted(() => ({
  projectMaterials: vi.fn(), materialPresets: vi.fn(), convert: vi.fn(), confirmMaterialMapping: vi.fn(),
  removeMaterialMapping: vi.fn(),
}));
vi.mock("@/api", () => api);

import { ProjectMaterialsCard } from "./ProjectMaterialsCard";

// jsdom has no <dialog> methods; this stands in for showModal()/close(). What the browser adds beyond that (inertness,
// Escape as a "cancel" event) is covered by the ConfirmDialog's own browser checks.
beforeAll(() => {
  const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
  proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
});
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  useProvider.setState({ kind: "spoolease", url: "192.168.1.50", slotMap: {}, slotBase: 1, key: "" });
  api.materialPresets.mockResolvedValue({ available: true, nozzle: "0.4", presets: [] });
});

const SAVED_SPOOL = mapping({ status: "proven", match_source: "saved_spool", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "", saved: { preset_base: "Snapmaker PLA Matte @U1", ref: "r1", fingerprint: "f1" } });
const SAVED_SIG = mapping({ status: "proven", match_source: "saved_signature", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "", saved: { preset_base: "Snapmaker PLA Matte @U1", ref: "r1", fingerprint: "f1" } });
const NAMED = mapping({ status: "needs_confirmation", match_source: "exact_name", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "named" });

const A = candidate({ spool_id: "124", label: "Yoopai PLA Matte", mapping: SAVED_SPOOL });
const B = candidate({ spool_id: "125", label: "Yoopai PLA Matte", colour: "#0000FF", color_name: "blue", mapping: SAVED_SPOOL });
const analysis = (cands = [A, B], over: Partial<ProjectMaterialsAnalysis> = {}): ProjectMaterialsAnalysis => ({
  schema: "project-materials/1", supported: true, nozzle: "0.4",
  catalog: { available: true, source: { profiles_version: "2.3.6" }, fingerprint: "x" },
  provider: { kind: "spoolease", available: true, error_code: null },
  slots: [slot({ candidates: cands, candidate_count: cands.length })], ...over,
});

const forgetButtons = () => screen.queryAllByTestId("forget-mapping") as HTMLButtonElement[];
const dialog = () => screen.queryByRole("alertdialog");
const deferred = <T,>() => {
  let resolve!: (v: T) => void; let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};
async function mount(first = analysis()) {
  api.projectMaterials.mockResolvedValueOnce(first);
  render(<ProjectMaterialsCard path="C:/p/x.3mf" mode="preserve" onPrepare={vi.fn()} />);
  await screen.findByText("Slot 1");
}
const openFor = (index: number) => { const b = forgetButtons()[index]; b.focus(); fireEvent.click(b); return b; };
const confirm = () => within(screen.getByRole("alertdialog")).getByRole("button", { name: "Confirm" });

describe("the Forget control", () => {
  it("appears beside a saved mapping and nowhere else", async () => {
    await mount(analysis([A, candidate({ spool_id: "9", mapping: SAVED_SIG }), candidate({ spool_id: "8", mapping: NAMED }), candidate({ spool_id: "7", mapping: mapping() })]));
    expect(forgetButtons()).toHaveLength(2);                       // the spool-saved one and the signature-saved one
    expect(forgetButtons()[0].textContent).toBe("Forget saved mapping");
    expect(forgetButtons()[1].textContent).toBe("Forget saved mapping (similar spools)");
    expect(forgetButtons()[1].getAttribute("aria-label")).toContain("Forget saved mapping (similar spools)");
  });

  it("is a separate button from the spool row, so choosing a spool and forgetting its mapping stay distinct", async () => {
    await mount();
    const row = screen.getAllByRole("button", { name: /Yoopai PLA Matte/ })[0];
    expect(row.contains(forgetButtons()[0])).toBe(false);
  });
});

describe("asking first", () => {
  it("opens a named, described prompt that says exactly what is affected, with focus on Cancel, and sends nothing", async () => {
    await mount();
    openFor(0);
    const d = screen.getByRole("alertdialog", { name: "Forget the saved mapping for this spool?" });
    expect(d.getAttribute("aria-describedby")).toBeTruthy();
    expect(d.textContent).toContain("Spool: Yoopai PLA Matte #124");
    expect(d.textContent).toContain("Saved preset: Snapmaker PLA Matte @U1");
    expect(d.textContent).toContain("Your spool inventory, your Orca presets and this project are not changed");
    expect(document.activeElement).toBe(within(d).getByRole("button", { name: "Cancel" }));
    expect(api.removeMaterialMapping).not.toHaveBeenCalled();
  });

  it("says a similar-spools mapping reaches every such spool", async () => {
    await mount(analysis([candidate({ spool_id: "9", mapping: SAVED_SIG })]));
    openFor(0);
    const d = screen.getByRole("alertdialog", { name: "Forget the saved mapping for similar spools?" });
    expect(d.textContent).toContain("mapping saved for every Yoopai PLA Matte spool");
  });

  it("Cancel removes nothing, closes the prompt and gives focus back to the Forget control", async () => {
    await mount();
    const opener = openFor(0);
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(dialog()).toBeNull();
    expect(api.removeMaterialMapping).not.toHaveBeenCalled();
    expect(api.projectMaterials).toHaveBeenCalledTimes(1);          // no re-analysis for a cancellation
    expect(document.activeElement).toBe(opener);
    expect(forgetButtons()).toHaveLength(2);
  });

  it("Escape does the same", async () => {
    await mount();
    const opener = openFor(0);
    fireEvent(screen.getByRole("alertdialog"), new Event("cancel", { cancelable: true }));
    expect(dialog()).toBeNull();
    expect(api.removeMaterialMapping).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
  });

  it("offers no second prompt while one is open", async () => {
    await mount();
    openFor(0);
    expect(forgetButtons().every((b) => b.disabled)).toBe(true);
  });
});

describe("forgetting", () => {
  it("removes exactly the identified spool mapping, re-reads the project, and shows the refreshed state", async () => {
    await mount();
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "124", mapping: mapping() }), B]));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    expect(api.removeMaterialMapping).toHaveBeenCalledTimes(1);
    expect(api.removeMaterialMapping).toHaveBeenCalledWith({ scope: "spool", provider: "spoolease", spool_id: "124", expect_preset_base: "Snapmaker PLA Matte @U1", expect_ref: "r1", expect_fingerprint: "f1" });
    await waitFor(() => expect(api.projectMaterials).toHaveBeenCalledTimes(2));
    expect(api.projectMaterials).toHaveBeenLastCalledWith("C:/p/x.3mf", expect.objectContaining({ provider: "spoolease" }), 3);
    await waitFor(() => expect(dialog()).toBeNull());
    expect(forgetButtons()).toHaveLength(1);                         // 124 no longer shows a saved mapping; 125 still does
    expect(screen.getByTestId("forget-note").textContent).toBe("Saved mapping forgotten.");
    // nothing else was asked of the engine: no mapping saved, no Prepare, no review
    expect(api.confirmMaterialMapping).not.toHaveBeenCalled();
    expect(api.convert).not.toHaveBeenCalled();
  });

  it("sends the signature, not a spool id, for a similar-spools mapping", async () => {
    await mount(analysis([candidate({ spool_id: "9", mapping: SAVED_SIG })]));
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "9", mapping: mapping() })]));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    expect(api.removeMaterialMapping).toHaveBeenCalledWith({ scope: "signature", provider: "spoolease", vendor: "Yoopai", material: "PLA", subtype: "Matte", expect_preset_base: "Snapmaker PLA Matte @U1", expect_ref: "r1", expect_fingerprint: "f1" });
  });

  it("leaves other saved mappings alone", async () => {
    await mount(analysis([A, candidate({ spool_id: "9", mapping: SAVED_SIG })]));
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "124", mapping: mapping() }), candidate({ spool_id: "9", mapping: SAVED_SIG })]));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(dialog()).toBeNull());
    expect(api.removeMaterialMapping).toHaveBeenCalledTimes(1);
    expect(api.removeMaterialMapping.mock.calls[0][0]).not.toHaveProperty("vendor");   // only the spool-scoped one was named
    expect(forgetButtons()).toHaveLength(1);
    expect(forgetButtons()[0].textContent).toContain("similar spools");               // the signature mapping is still there
  });

  it("puts focus on that spool's row when the Forget control it came from is gone", async () => {
    await mount();
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "124", mapping: mapping() }), B]));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(dialog()).toBeNull());
    expect((document.activeElement as HTMLElement)?.getAttribute("data-candidate-key")).toBe("spoolease:124");
  });

  it("says so when the mapping was already gone", async () => {
    await mount();
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: false });
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "124", mapping: mapping() }), B]));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(screen.getByTestId("forget-note").textContent).toBe("That saved mapping was already gone."));
  });

  it("sends one request however many times confirm is pressed while it runs", async () => {
    await mount();
    const pending = deferred<{ ok: boolean; removed: boolean }>();
    api.removeMaterialMapping.mockReturnValue(pending.promise);
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "124", mapping: mapping() }), B]));
    openFor(0);
    const yes = confirm();
    await act(async () => { yes.click(); yes.click(); yes.click(); });                // three native clicks inside one batch
    expect(api.removeMaterialMapping).toHaveBeenCalledTimes(1);
    expect(dialog()).not.toBeNull();                                                    // the prompt stays while it runs
    expect((screen.getByRole("alertdialog").querySelector("button") as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { pending.resolve({ ok: true, removed: true }); });
    await waitFor(() => expect(dialog()).toBeNull());
    expect(api.removeMaterialMapping).toHaveBeenCalledTimes(1);
    expect(api.projectMaterials).toHaveBeenCalledTimes(2);
  });

  it("reports a failure it cannot confirm, then reads the project again so the list is what the engine now says", async () => {
    await mount();
    api.removeMaterialMapping.mockRejectedValue(new Error("disk is read-only"));
    api.projectMaterials.mockResolvedValueOnce(analysis());
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(dialog()).toBeNull());
    const note = screen.getByTestId("forget-note");
    expect(note.getAttribute("role")).toBe("alert");
    expect(note.textContent).toBe("Couldn't confirm the saved mapping was forgotten: disk is read-only. The list shows what Studio read afterwards.");
    expect(api.projectMaterials).toHaveBeenCalledTimes(2);
    expect(forgetButtons()).toHaveLength(2);                                            // still shown: it is still saved
    // and it can be tried again
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockResolvedValueOnce(analysis([candidate({ spool_id: "124", mapping: mapping() }), B]));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(forgetButtons()).toHaveLength(1));
  });

  it("says so when the mapping was forgotten but the project could not be read again", async () => {
    await mount();
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockRejectedValueOnce(new Error("project moved"));
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(screen.getByTestId("forget-note").textContent).toContain("was forgotten, but Studio could not read the project again"));
    expect(screen.getByTestId("forget-note").getAttribute("role")).toBe("alert");
  });
});

describe("choices that rested on the forgotten mapping", () => {
  it("clears the slot that chose that spool and keeps the others", async () => {
    const two: ProjectMaterialsAnalysis = analysis([A], {
      slots: [slot({ slot: 0, candidates: [A], candidate_count: 1 }), slot({ slot: 1, candidates: [candidate({ spool_id: "300", mapping: NAMED })], candidate_count: 1 })],
    });
    await mount(two);
    fireEvent.click(screen.getAllByRole("button", { name: /Yoopai PLA Matte/ })[0]);     // slot 1 chooses spool 124 (proven via its saved mapping)
    const rows = screen.getAllByRole("button", { name: /Yoopai PLA Matte/ });
    fireEvent.click(rows[rows.length - 1]);                                             // slot 2 chooses spool 300
    expect(screen.getAllByTestId("selected-spool")).toHaveLength(2);
    api.removeMaterialMapping.mockResolvedValue({ ok: true, removed: true });
    api.projectMaterials.mockResolvedValueOnce({ ...two, slots: [slot({ slot: 0, candidates: [candidate({ spool_id: "124", mapping: mapping() })], candidate_count: 1 }), two.slots![1]] });
    openFor(0);
    await act(async () => { fireEvent.click(confirm()); });
    await waitFor(() => expect(screen.getAllByTestId("selected-spool")).toHaveLength(1));
    expect(screen.getByTestId("forget-note").textContent).toBe("Saved mapping forgotten. Your choice for slot 1 was cleared.");
  });
});

describe("the rules in the library", () => {
  it("names a request only for a preset that came from a saved mapping", () => {
    expect(forgetRequest(candidate({ mapping: NAMED }))).toBeNull();
    expect(forgetRequest(candidate({ mapping: mapping() }))).toBeNull();
    expect(savedScope(candidate({ mapping: SAVED_SPOOL }))).toBe("spool");
    expect(forgetRequest(candidate({ spool_id: "5", mapping: SAVED_SPOOL }))).toEqual({ scope: "spool", provider: "spoolease", spool_id: "5", expect_preset_base: "Snapmaker PLA Matte @U1", expect_ref: "r1", expect_fingerprint: "f1" });
  });

  const held = (spool: ReturnType<typeof candidate>, name = "Snapmaker PLA Matte @U1") =>
    ({ spool, preset: { name, confirmed: true, fingerprint: spool.mapping.fingerprint ?? null }, keepOwn: false, remember: "off" as const });

  it("covers a spool by id for a spool mapping and by kind for a signature mapping, ignoring case and spacing", () => {
    const sig = candidate({ spool_id: "1", vendor: "Yoopai", material: "PLA", subtype: "Matte", mapping: SAVED_SIG });
    const choices: Choices = {
      0: held(candidate({ spool_id: "2", vendor: "  yoopai ", subtype: "matte", mapping: SAVED_SIG })),
      1: held(candidate({ spool_id: "3", vendor: "Other", subtype: "Matte", mapping: SAVED_SIG })),
      2: held(candidate({ spool_id: "4", provider: "spoolman", vendor: "Yoopai", subtype: "Matte", mapping: SAVED_SIG })),
    };
    expect(slotsCoveredBy(choices, sig)).toEqual([0]);
    const byId: Choices = { 1: held(candidate({ spool_id: "3", mapping: SAVED_SPOOL })), 0: held(candidate({ spool_id: "9", mapping: SAVED_SPOOL })) };
    expect(slotsCoveredBy(byId, candidate({ spool_id: "3", mapping: SAVED_SPOOL }))).toEqual([1]);
    expect(slotsCoveredBy(choices, candidate({ mapping: NAMED }))).toEqual([]);
    expect(choiceReduce(choices, { type: "discardSlots", slots: [0, 2] })).toEqual({ 1: choices[1] });
  });

  it("leaves a slot alone when its preset was changed by hand or its spool has a mapping of its own", () => {
    const sig = candidate({ spool_id: "1", vendor: "Yoopai", material: "PLA", subtype: "Matte", mapping: SAVED_SIG });
    const own = candidate({ spool_id: "2", vendor: "Yoopai", material: "PLA", subtype: "Matte", mapping: SAVED_SPOOL });
    const changedByHand = held(candidate({ spool_id: "3", vendor: "Yoopai", material: "PLA", subtype: "Matte", mapping: SAVED_SIG }), "Some other preset");
    const choices: Choices = { 0: held(own), 1: changedByHand, 2: { ...held(sig), preset: null } };
    expect(slotsCoveredBy(choices, sig)).toEqual([]);
  });

  it("matches a signature by the engine's own key, so a ligature the engine folds is still covered", () => {
    const sig = (vendor: string) => ({ vendor, family: "pla", subtype: "matte" });
    const forgotten = candidate({ spool_id: "1", vendor: "Acme", mapping: SAVED_SIG, signature: sig("acme") });
    const other = candidate({ spool_id: "2", vendor: "Aﬀme", mapping: SAVED_SIG, signature: sig("acme") });   // the engine folds ﬀ to ff
    const different = candidate({ spool_id: "3", vendor: "Acme", mapping: SAVED_SIG, signature: sig("zzz") });
    const choices: Choices = { 0: held(other), 1: held(different) };
    expect(slotsCoveredBy(choices, forgotten)).toEqual([0]);
  });

  it("refers the engine to the preset the person was shown, so a mapping replaced since is not removed", () => {
    expect(forgetRequest(candidate({ spool_id: "5", mapping: SAVED_SPOOL }))?.expect_preset_base).toBe("Snapmaker PLA Matte @U1");
  });

  it("describes only what the control does", () => {
    const w = forgetWording(candidate({ spool_id: "124", mapping: SAVED_SPOOL }));
    expect(w.details).toEqual(["Spool: Yoopai PLA Matte #124", "Saved preset: Snapmaker PLA Matte @U1"]);
    expect(w.body).not.toMatch(/guarantee|always|never fails/i);
  });
});
