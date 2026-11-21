// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const spies=vi.hoisted(() => ({ generate:vi.fn(), open:vi.fn(), check:vi.fn(), setFile:vi.fn() }));
vi.mock("@/store/session",()=>({useSession:{getState:()=>({setFile:spies.setFile})}}));
vi.mock("@tauri-apps/plugin-dialog",()=>({open:vi.fn()}));
vi.mock("./luminaApi",async original=>({...await original<typeof import("./luminaApi")>(),
  fetchLuminaFormats:vi.fn().mockResolvedValue({formats:[{kind:"3mf",meaning:"Model",evidence:"mock-service-tested"},{kind:"png",meaning:"Preview",evidence:"mock-service-tested"}]}),
  generateWithLumina:spies.generate, checkLuminaService:spies.check, openGeneratedModel:spies.open,
}));
import { buildGenerateBody } from "./luminaApi";
import LuminaView from "./LuminaView";
import { useLuminaSession } from "./session";
beforeEach(() => useLuminaSession.getState().clear());
const result={generated:true,file_name:"lumina-"+"a".repeat(12)+".3mf",sha256:"a".repeat(64),size_bytes:100,kind:"3mf",location_label:"Studio's lumina-output folder",generated_by:"synthetic service",advisory:"Inspect before use",progress:"unknown",cancel:"unknown",evidence:"mock-service-tested"};
async function mount(){
  await act(async()=>render(<MemoryRouter initialEntries={["/lumina"]}><Routes><Route path="/lumina" element={<LuminaView/>}/><Route path="/this-print" element={<p>Normal preparation workflow</p>}/></Routes></MemoryRouter>));
  fireEvent.change(screen.getByLabelText("Service address"),{target:{value:"http://127.0.0.1:8123"}});
  fireEvent.change(screen.getByLabelText("Image file path"),{target:{value:"synthetic.png"}});
  fireEvent.change(screen.getByLabelText("LUT name"),{target:{value:"Synthetic"}});
  fireEvent.change(screen.getByLabelText("Output format"),{target:{value:"3mf"}});
}
afterEach(()=>{cleanup();vi.clearAllMocks();});
describe("Lumina generated artifact workflow",()=>{
  it("requires an explicit identity-checked open before entering normal Prepare",async()=>{
    spies.generate.mockResolvedValue(result);spies.open.mockResolvedValue({output:{local_path:"synthetic-generated.3mf"},kind:"3mf",sha256:result.sha256});
    await mount(); fireEvent.change(screen.getByLabelText("Model width in millimetres"),{target:{value:"80"}}); await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Generate"})));
    expect(spies.setFile).not.toHaveBeenCalled();expect(spies.open).not.toHaveBeenCalled();
    expect(spies.generate).toHaveBeenCalledWith(expect.objectContaining({width_mm:80}));
    await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Open generated model in Studio"})));
    expect(spies.open).toHaveBeenCalledWith(result,undefined);
    expect(spies.setFile).toHaveBeenCalledWith("synthetic-generated.3mf");
    expect(screen.getByText("Normal preparation workflow")).toBeTruthy();
  });
  it("records stale generation separately and does not allow overlapping requests",async()=>{
    let resolve!: (value:unknown)=>void;spies.generate.mockReturnValue(new Promise(r=>{resolve=r;}));
    await mount();await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Generate"})));
    fireEvent.change(screen.getByLabelText("LUT name"),{target:{value:"Changed"}});
    expect(screen.getByRole("button",{name:"Working..."}).hasAttribute("disabled")).toBe(true);
    await act(async()=>resolve(result));
    expect(screen.queryByRole("button",{name:"Open generated model in Studio"})).toBeNull();
    expect(screen.getByText(/Earlier requests saved files/)).toBeTruthy();expect(spies.generate).toHaveBeenCalledTimes(1);
  });
  it("does not open a missing or changed generated model",async()=>{
    spies.generate.mockResolvedValue(result);spies.open.mockRejectedValue(new Error("File changed"));
    await mount();await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Generate"})));
    await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Open generated model in Studio"})));
    expect(screen.getByRole("alert").textContent).toBe("File changed");expect(spies.setFile).not.toHaveBeenCalled();
  });
  it("keeps preview output out of the printable model handoff",async()=>{
    spies.generate.mockResolvedValue({...result,kind:"png",file_name:"synthetic-preview.png"});
    await mount();await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Generate"})));
    expect(screen.queryByRole("button",{name:"Open generated model in Studio"})).toBeNull();
    expect(screen.getByText(/This is a preview, not a printable 3MF/)).toBeTruthy();
  });
});


it("a hidden invalid model width does not prevent requesting a PNG preview", () => {
  expect(buildGenerateBody({serviceUrl:"http://127.0.0.1:8123",imagePath:"synthetic.png",lutName:"Synthetic",format:"png",widthMm:"invalid"},[{kind:"png",meaning:"Preview",evidence:"mock-service-tested"}])).not.toHaveProperty("width_mm");
});
