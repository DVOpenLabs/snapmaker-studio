// @vitest-environment jsdom
import { useCreativeDraft } from "./draft";
// Real Creative view + real selector + real session/job linking. Service replies
// are mocked. The card stub emits the real card's empty cleanup callback.
import React, { useEffect } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CreativeView from "./CreativeView";
import { inspectCreative, prepareCreative, fetchCreativeFormats } from "@/lib/creativeApi";
import { NO_SETUP, selectionFromEvaluate } from "@/lib/prepareSetup";
import { useSession } from "@/store/session";
import { useJob, useUnlinkedCopies } from "@/store/job";
import type { MaterialSelection } from "@/lib/projectMaterials";

vi.mock("@/api",async original=>({...await original<typeof import("@/api")>(),jobCheck:vi.fn().mockResolvedValue({files:[]})}));
vi.mock("@/lib/creativeApi",async original=>({...await original<typeof import("@/lib/creativeApi")>(),inspectCreative:vi.fn(),prepareCreative:vi.fn(),fetchCreativeFormats:vi.fn()}));
vi.mock("./CreativeReportView",()=>({default:()=> <p>Synthetic inspected project</p>}));
vi.mock("./CreativePreparePanel",()=>({default:()=> <p>Synthetic prepare response</p>}));
vi.mock("@/components/ProjectMaterialsCard",()=>({ProjectMaterialsCard:({onSelectionsChange,onPrepare,busy}:{onSelectionsChange:(v:MaterialSelection[])=>void;onPrepare:(v:MaterialSelection[])=>void;busy:boolean})=>{
  useEffect(()=>()=>onSelectionsChange([]),[onSelectionsChange]);
  return <button disabled={busy} onClick={()=>{const selected=[{slot:0,preset:null,colour:"#123456"}];onSelectionsChange(selected);onPrepare(selected);}}>Prepare selected materials</button>;
}}));

function ready(){
  const topology={schema_version:"topology/1",snapshot_id:"synthetic",received_at:"2026-11-14T10:00:00Z",observed_at:null,mapping_revision:null,complete:true,evidence:[],diagnostics:[],units:[],
    heads:Array.from({length:4},(_,i)=>({id:`head:${i}`,index:i,nozzle_mm:0.4,evidence:[]})),
    slots:Array.from({length:8},(_,i)=>({id:`slot:${i}`,index:i,binding:null,nozzle_mm:null})),
    bindings:Array.from({length:8},(_,i)=>({slot_id:`slot:${i}`,target:`head:${i%4}`,evidence:[]}))};
  useSession.setState({prepareSetup:selectionFromEvaluate({token:101,projectPath:"synthetic.3mf",label:"Synthetic host"},{topology})});
}
async function inspected(){
  const view=render(<CreativeView/>);
  fireEvent.change(screen.getByLabelText("Project file path"),{target:{value:"synthetic.3mf"}});
  await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Inspect project"})));
  await screen.findByText("Synthetic inspected project");
  act(ready);
  expect(screen.getByTestId("setup-status").getAttribute("data-state")).toBe("ready");
  return view;
}
beforeEach(()=>{useCreativeDraft.getState().reset();
  vi.clearAllMocks();useJob.getState().forget();useUnlinkedCopies.getState().clear();useSession.getState().reset();
  useSession.setState({prepareSetup:NO_SETUP(100)});
  vi.mocked(fetchCreativeFormats).mockResolvedValue({formats:[],manual_only:[],note:""});
  vi.mocked(inspectCreative).mockResolvedValue({origin:{status:"detected"}} as never);
});
afterEach(cleanup);

it.each(["unknown_origin","prepare_refused_material_value","prepare_blocked_material_guard"])("a ready real selector reports not_evaluated for non-setup refusal %s",async kind=>{
  vi.mocked(prepareCreative).mockResolvedValue({prepared:false,refusal:{kind,seen:"Synthetic refusal",not_supported:"Stopped for a reason unrelated to the setup.",what_to_do:[]},setup:null} as never);
  await inspected();await act(async()=>fireEvent.click(screen.getByRole("button",{name:"Prepare a U1 copy"})));
  const outcome=await screen.findByTestId("setup-outcome");
  expect(outcome.getAttribute("data-state")).toBe("not_evaluated");
  expect(outcome.textContent).toContain("stopped for another reason");
  expect(screen.queryByText(/could not use this printer setup/i)).toBeNull();
});

it("material cleanup after navigation does not orphan a valid in-flight copy",async()=>{
  let finish!: (v:never)=>void;vi.mocked(prepareCreative).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
  const view=await inspected();
  fireEvent.click(screen.getByText("Prepare selected materials"));
  await waitFor(()=>expect(prepareCreative).toHaveBeenCalledTimes(1));
  view.unmount();
  await act(async()=>finish({prepared:true,output:{name:"synthetic-copy.3mf",local_path:"synthetic-copy.3mf"},prepare:{mode:"preserve",validated_ok:true}} as never));
  expect(useJob.getState().record?.prepared?.path).toBe("synthetic-copy.3mf");
  expect(useUnlinkedCopies.getState().items).toEqual([]);
});
