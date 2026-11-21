// @vitest-environment jsdom
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AccessorySetupFields, { accessoryBody, EMPTY_ACCESSORY } from "./AccessorySetupFields";
import { useSession } from "@/store/session";
import { setupFor, prepareBlockedBy } from "@/lib/prepareSetup";
import SetupsView from "./SetupsView";
import { PrepareSetupSelector } from "../PrepareSetupSelector";
import { buildEvaluateBody } from "@/lib/setupsApi";
const mock = vi.hoisted(() => ({ evaluate: vi.fn() }));
vi.mock("@/lib/setupsApi", async original => ({ ...await original<typeof import("@/lib/setupsApi")>(), evaluateSetup: mock.evaluate }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("explicit accessory setup inputs", () => {
  it("keeps legacy host requests unchanged and forwards only explicit choices", () => {
    expect(buildEvaluateBody({ host: "synthetic.local" })).toEqual({ host: "synthetic.local" });
    const accessory = accessoryBody({ ...EMPTY_ACCESSORY, adapter: "multiace", host: "127.0.0.1", port: "8123", mapping: "lane:unit:multiace:ace0:0\nlane:unit:multiace:ace1:0" });
    expect(buildEvaluateBody({ host: "", accessory }).accessory).toEqual({ adapter_id: "multiace", source_version: "1", mode: "live", host: "127.0.0.1", port: 8123, slot_map: ["lane:unit:multiace:ace0:0", "lane:unit:multiace:ace1:0"] });
  });
  it("imports BMCU commands as text, never executes them or guesses slots", () => {
    const value = accessoryBody({ ...EMPTY_ACCESSORY, adapter: "bmcu", snapshot: "BMCU_PRINT_BEGIN SCHEMA=1" });
    expect(value).toEqual({ adapter_id: "bmcu", source_version: "1", mode: "snapshot", payload: { kind: "klipper_text", text: "BMCU_PRINT_BEGIN SCHEMA=1" } });
  });
  it("passes the accessory selection through the actual Prepare selector", async () => {
    const onRead=vi.fn(), onClear=vi.fn();
    render(<PrepareSetupSelector selection={{ status: "none", token: 1 }} onRead={onRead} onClear={onClear} />);
    fireEvent.change(screen.getByLabelText("Accessory adapter"), { target: { value: "multiace" } });
    fireEvent.change(screen.getByLabelText("Accessory service host"), { target: { value: "127.0.0.1" } });
    fireEvent.change(screen.getByLabelText("Accessory service port"), { target: { value: "8123" } });
    await act(async () => fireEvent.click(screen.getByTestId("setup-read")));
    expect(onRead).toHaveBeenCalledWith(expect.objectContaining({ host: "", accessory: expect.objectContaining({ adapter_id: "multiace", mode: "live" }) }));
    expect(onClear).toHaveBeenCalled();
  });
  it("rejects a late host answer after inputs change in Setups", async () => {
    let resolve!: (value: unknown) => void;
    mock.evaluate.mockReturnValue(new Promise(r => { resolve=r; }));
    render(<MemoryRouter><SetupsView /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Host address"), { target: { value: "synthetic.local" } });
    await act(async () => fireEvent.click(screen.getByRole("button",{ name:"Read setup" })));
    fireEvent.change(screen.getByLabelText("Host address"), { target: { value: "different.local" } });
    await act(async () => resolve({ report: { entries: [] }, topology: null }));
    expect(screen.queryByText("Setup report")).toBeNull();
    expect(screen.getByRole("button",{name:"Read setup"}).hasAttribute("disabled")).toBe(false);
  });
});


it("an edited setup remains paused until re-read or an explicit clear", () => {
  useSession.getState().invalidatePrepareSetup("synthetic.3mf");
  const edited = setupFor(useSession.getState().prepareSetup, "synthetic.3mf");
  expect(edited.status).toBe("unknown");
  expect(prepareBlockedBy(edited, "synthetic.3mf")).toBeTruthy();
  useSession.getState().clearPrepareSetup();
  expect(setupFor(useSession.getState().prepareSetup, "synthetic.3mf").status).toBe("none");
});


it("exposes published Sidecar load-cell and BMCU transport snapshot envelopes without converting them to commands", () => {
  for (const [adapter, payload] of [["sidecar", {kind:"loadcell",unit:1,body:{ok:true,lanes:{"1":{net_g:12,raw_g:14}}}}], ["bmcu", {kind:"transport_status",body:{schema:1,devices:[]}}]] as const) {
    expect(accessoryBody({...EMPTY_ACCESSORY,adapter,snapshotKind:"json",snapshot:JSON.stringify(payload)})?.payload).toEqual(payload);
  }
});

it.each(["bmcu","sidecar"])("%s does not offer a replacement mapping and rejects one in a stale draft", adapter => {
  render(<AccessorySetupFields value={{...EMPTY_ACCESSORY,adapter}} onChange={()=>undefined}/>);
  expect(screen.queryByLabelText("Accessory logical slot map")).toBeNull();
  expect(screen.getByText(/does not accept a replacement declared map/)).toBeTruthy();
  expect(()=>accessoryBody({...EMPTY_ACCESSORY,adapter,snapshot:"synthetic text",mapping:"lane:synthetic:one"})).toThrow(/cannot be overridden/);
});
