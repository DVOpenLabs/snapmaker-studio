// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useReducer, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { candidate, mapping, slot } from "@/lib/projectMaterials.fixtures";
import {
  buildSelections, choiceReduce, splitReasons, type Choices, type MaterialPresetList, type ProjectMaterialsAnalysis,
} from "@/lib/projectMaterials";

vi.mock("@/api", () => ({
  projectMaterials: vi.fn(), materialPresets: vi.fn(), convert: vi.fn(), confirmMaterialMapping: vi.fn(),
  projectMaterialsInventory: vi.fn(), removeMaterialMapping: vi.fn(),
}));

import { ProjectMaterialsView } from "@/components/ProjectMaterialsCard";
import { PaneTabs } from "./PaneTabs";
import { CompactSlotRow } from "./CompactSlot";

afterEach(cleanup);

const PRESETS: MaterialPresetList = {
  available: true, nozzle: "0.4",
  presets: [{ base_name: "Snapmaker PLA Matte @U1", preset_name: "Snapmaker PLA Matte @U1", vendor: "Snapmaker", filament_type: "PLA", fingerprint: "b" }],
};
const NAMED = mapping({ status: "needs_confirmation", match_source: "exact_name", preset_name: "Snapmaker PLA Matte @U1",
  base_name: "Snapmaker PLA Matte @U1", reason: "The provider names this installed preset. Confirm it to use it." });

function analysis(slots = [slot()]): ProjectMaterialsAnalysis {
  return { schema: "project-materials/1", supported: true, nozzle: "0.4",
    catalog: { available: true, source: { profiles_version: "2.3.6" }, fingerprint: "x" },
    provider: { kind: "spoolease", available: true, error_code: null }, slots };
}

function Harness({ a, withTabs = false }: { a: ProjectMaterialsAnalysis; withTabs?: boolean }) {
  const [choices, dispatch] = useReducer(choiceReduce, {} as Choices);
  const [tab, setTab] = useState("materials");
  const view = (
    <ProjectMaterialsView load={{ status: "ready" }} analysis={a} presets={PRESETS} providerLabel="SpoolEase" choices={choices}
      dispatch={dispatch} review={{ status: "idle" }} onReview={() => {}} onBack={() => {}} onPrepare={() => {}} bare slotView={CompactSlotRow} />
  );
  return (
    <div>
      {withTabs
        ? <PaneTabs label="Job" active={tab} onChange={setTab} tabs={[{ id: "materials", label: "Materials", el: view }, { id: "other", label: "Other", el: <p>other</p> }]} />
        : view}
      <output data-testid="request">{JSON.stringify(buildSelections(choices))}</output>
    </div>
  );
}
const request = () => JSON.parse(screen.getByTestId("request").textContent || "[]");

describe("compact slot row", () => {
  it("shows one row per slot with the source material and a Choose control, and no candidates until asked", () => {
    render(<Harness a={analysis([slot({ slot: 0 }), slot({ slot: 1, colour: "#0000FF", candidates: [candidate({ spool_id: "9" })] })])} />);
    expect(screen.getAllByTestId("slot-choice")).toHaveLength(2);
    expect(screen.getAllByTestId("slot-toggle").map((b) => b.textContent)).toEqual(["Choose", "Choose"]);
    expect(screen.queryByLabelText(/Spool candidates for slot 1/)).toBeNull();
    for (const el of screen.getAllByTestId("slot-choice")) expect(el.textContent).toContain("No spool chosen");
    expect(screen.getAllByText(/180 g needed/)).toHaveLength(2);
  });

  it("reveals candidates on request with the toggle exposing its state, and choosing changes the request", () => {
    render(<Harness a={analysis()} />);
    const toggle = screen.getByTestId("slot-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.getAttribute("aria-controls")).toBe(screen.getByTestId("slot-panel").id);
    fireEvent.click(screen.getByRole("button", { name: /Yoopai/ }));
    expect(request()).toEqual([expect.objectContaining({ slot: 0, spool: expect.objectContaining({ id: "124" }) })]);
    expect(screen.getByTestId("slot-toggle").textContent).toBe("Done");
    fireEvent.click(screen.getByTestId("slot-toggle"));
    // collapsed again: the choice is still held and the control now says Change
    expect(screen.getByTestId("slot-toggle").textContent).toBe("Change");
    expect(screen.getByTestId("slot-choice").textContent).toContain("Yoopai PLA Matte");
    expect(request()).toHaveLength(1);
  });

  it("keeps technical reasons and the raw distance in a collapsed details, not in the candidate line", () => {
    const c = candidate({ reasons: [
      { code: "material_exact", text: "Material matches: PLA" },
      { code: "colour_distance", text: "Colour distance 12.4 (close)" },
      { code: "weight_short", text: "Only 40 g left; this slot needs 180 g" },
    ] });
    render(<Harness a={analysis([slot({ candidates: [c] })])} />);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    const details = screen.getByText("Why this match").closest("details")!;
    expect(details.open).toBe(false);
    expect(within(details).getByText(/Colour distance 12.4/)).toBeTruthy();
    expect(within(details).getByText(/Material matches/)).toBeTruthy();
    // the shortfall is a decision: visible outside the details
    const short = screen.getByText(/Only 40 g left/);
    expect(details.contains(short)).toBe(false);
    expect(splitReasons(c).decision.map((r) => r.code)).toEqual(["weight_short"]);
  });

  it("keeps blockers visible while the row is collapsed: unknown amount, close call, stale mapping", () => {
    const stale = candidate({ remaining_g: null, remaining_quality: null, mapping: mapping({ stale: true, status: "needs_confirmation", match_source: "saved_spool" }),
      reasons: [{ code: "amount_unknown", text: "Remaining amount is not known" }] });
    render(<Harness a={analysis([slot({ candidates: [stale], close_call: true })])} />);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByRole("button", { name: /Yoopai/ }));
    fireEvent.click(screen.getByTestId("slot-toggle")); // collapse
    expect(screen.queryByTestId("slot-panel")).toBeNull();
    expect(screen.getByTestId("close-call")).toBeTruthy();
    expect(screen.getByTestId("spool-flags").textContent).toContain("Remaining amount is not known");
    expect(screen.getByTestId("stale-mapping")).toBeTruthy();
  });

  it("does not turn a suggestion into a choice, and a preset needing confirmation stays a visible, separate step", () => {
    render(<Harness a={analysis([slot({ candidates: [candidate({ mapping: NAMED })],
      suggestion: { status: "needs_confirmation", preset_name: "Snapmaker PLA Matte @U1", base_name: "Snapmaker PLA Matte @U1", reason: "Name matches." } })])} />);
    expect(screen.getByTestId("suggestion")).toBeTruthy();
    expect(request()).toEqual([]);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByRole("button", { name: /Yoopai/ }));
    fireEvent.click(screen.getByTestId("slot-toggle")); // collapsed: the confirmation is still on the line
    const needs = screen.getByTestId("needs-confirmation");
    // chosen but unconfirmed: Review is still blocked until the person confirms it
    expect((screen.getByRole("button", { name: /Review/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(needs).getByRole("button", { name: /Confirm/ }));
    expect(screen.queryByTestId("needs-confirmation")).toBeNull();
    expect((screen.getByRole("button", { name: /Review/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps the engine's long wording in details: the line stays short, the words stay available", () => {
    const sug = { status: "needs_confirmation" as const, preset_name: "P", base_name: "Generic PLA", reason: "Generic PLA is installed for this nozzle. Studio suggests it but does not choose between presets for you." };
    render(<Harness a={analysis([slot({ suggestion: sug, close_call: true })])} />);
    const box = screen.getByTestId("suggestion");
    const d = within(box).getByText("Why this suggestion").closest("details")!;
    expect(d.open).toBe(false);
    expect(d.textContent).toContain("does not choose between presets for you");
    expect(box.textContent).toContain("Suggested preset: Generic PLA");
    // close call: a chip on the line, the sentence once the person opens the row to choose
    expect(screen.getByTestId("close-call").textContent).toBe("Close call");
    expect(screen.queryByTestId("close-call-note")).toBeNull();
    fireEvent.click(screen.getByTestId("slot-toggle"));
    expect(screen.getByTestId("close-call-note").textContent).toMatch(/very close/);
  });

  it("says a spool without a preset leaves the project's preset alone, collapsed or not", () => {
    render(<Harness a={analysis()} />);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByRole("button", { name: /Yoopai/ }));
    fireEvent.click(screen.getByTestId("slot-toggle"));
    expect(screen.getByTestId("spool-without-preset").textContent).toMatch(/no Orca preset selected/);
  });

  it("holds no interactive control inside another interactive control", () => {
    const withSaved = candidate({ mapping: mapping({ status: "proven", match_source: "saved_spool", preset_name: "P", base_name: "P", reason: "" }) });
    const { container } = render(<Harness a={analysis([slot({ candidates: [withSaved] })])} />);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByText(/Choose an installed preset/));
    const interactive = "button, a[href], input, select, textarea, summary, [role=button], [role=option], [tabindex]";
    for (const el of container.querySelectorAll(interactive)) {
      expect(el.parentElement?.closest("button, a[href], summary, [role=button]")).toBeNull();
    }
  });

  it("leaves forgetting a saved mapping available on the candidate, as its own control", () => {
    const onForget = vi.fn();
    const saved = candidate({ mapping: mapping({ status: "proven", match_source: "saved_spool", preset_name: "P", base_name: "P", reason: "" }) });
    const { rerender } = render(<div />);
    rerender(<ProjectMaterialsView load={{ status: "ready" }} analysis={analysis([slot({ candidates: [saved] })])} presets={PRESETS} providerLabel="SpoolEase"
      choices={{}} dispatch={() => {}} review={{ status: "idle" }} onReview={() => {}} onBack={() => {}} onPrepare={() => {}} bare
      slotView={CompactSlotRow} onForget={onForget} />);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByTestId("forget-mapping"));
    expect(onForget).toHaveBeenCalledTimes(1);
    expect(onForget.mock.calls[0][0].spool_id).toBe("124");
  });

  it("keeps drafts across a tab switch and across expanding and collapsing the row", () => {
    render(<Harness a={analysis()} withTabs />);
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByRole("button", { name: /Yoopai/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Other" }));
    fireEvent.click(screen.getByRole("tab", { name: "Materials" }));
    expect(request()).toHaveLength(1);
    expect(screen.getByTestId("slot-choice").textContent).toContain("#124");
    fireEvent.click(screen.getByTestId("slot-toggle"));
    fireEvent.click(screen.getByTestId("slot-toggle"));
    expect(request()).toHaveLength(1);
  });

  it("the detailed row stays the default outside the job view", () => {
    render(
      <ProjectMaterialsView load={{ status: "ready" }} analysis={analysis()} presets={PRESETS} providerLabel="SpoolEase" choices={{}}
        dispatch={() => {}} review={{ status: "idle" }} onReview={() => {}} onBack={() => {}} onPrepare={() => {}} />,
    );
    expect(screen.queryByTestId("slot-toggle")).toBeNull();
    expect(screen.getByLabelText(/Spool candidates for slot 1/)).toBeTruthy();
  });
});
