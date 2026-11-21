// @vitest-environment jsdom
import { act,cleanup,fireEvent,render,screen } from "@testing-library/react";
import { afterEach,beforeEach,expect,it,vi } from "vitest";
import CreativeView from "./CreativeView";
import { useCreativeDraft } from "./draft";
import { useJob,useUnlinkedCopies } from "@/store/job";
import { useSession } from "@/store/session";
import { NO_SETUP } from "@/lib/prepareSetup";
import { openProject } from "@/lib/jobRecord";
import { fetchCreativeFormats,inspectCreative,prepareCreative } from "@/lib/creativeApi";
vi.mock("@/lib/creativeApi",async original=>({...await original<object>(),fetchCreativeFormats:vi.fn(),inspectCreative:vi.fn(),prepareCreative:vi.fn()}));
vi.mock("@/api",async original=>({...await original<object>(),jobCheck:vi.fn(async()=>({files:[]}))}));
vi.mock("./CreativeReportView",()=>({default:()=> <p>Synthetic inspected</p>}));
vi.mock("./CreativePreparePanel",()=>({default:()=> <p>Synthetic prepared</p>}));
vi.mock("@/components/ProjectMaterialsCard",()=>({ProjectMaterialsCard:()=>null}));
vi.mock("@/components/PrepareSetupSelector",()=>({ConnectedPrepareSetupSelector:()=>null}));
beforeEach(()=>{
 vi.clearAllMocks();useCreativeDraft.getState().reset();useUnlinkedCopies.getState().clear();
 useSession.setState({prepareSetup:NO_SETUP(100)});
 useJob.setState({record:openProject(null,"synthetic.3mf","2026-11-14T12:00:00Z"),verified:true});
 vi.mocked(fetchCreativeFormats).mockResolvedValue({formats:[],manual_only:[],note:""});
 vi.mocked(inspectCreative).mockResolvedValue({origin:{status:"detected"}} as never);
});
afterEach(cleanup);
async function pending(){
 let resolve!:(value:never)=>void;vi.mocked(prepareCreative).mockReturnValueOnce(new Promise(r=>{resolve=r;}));
 const view=render(<CreativeView/>);fireEvent.change(screen.getByLabelText("Project file path"),{target:{value:"synthetic.3mf"}});fireEvent.click(screen.getByText("Inspect project"));await screen.findByText("Synthetic inspected");
 fireEvent.click(screen.getByRole("button",{name:"Prepare a U1 copy"}));view.unmount();render(<CreativeView/>);
 return async()=>{await act(async()=>resolve({prepared:true,output:{local_path:"synthetic-output.3mf",name:"synthetic-output.3mf"},prepare:{validated_ok:true,mode:"preserve"}} as never));};
}
it.each(["clear","path","format","output"])("navigation followed by %s prevents the older written copy from linking",async edit=>{
 const complete=await pending();
 if(edit==="clear")fireEvent.click(screen.getByText("Clear creative inputs"));
 else if(edit==="path")fireEvent.change(screen.getByLabelText("Project file path"),{target:{value:"new-synthetic.3mf"}});
 else if(edit==="format")fireEvent.change(screen.getByLabelText("Project format"),{target:{value:"kromacut"}});
 else {fireEvent.click(screen.getByText("Inspect project"));await screen.findByText("Synthetic inspected");fireEvent.change(screen.getByLabelText("Output folder (optional)"),{target:{value:"new-output"}});}
 await complete();expect(useJob.getState().record?.prepared).toBeNull();
 expect(useUnlinkedCopies.getState().items).toHaveLength(1);expect(screen.getByTestId("creative-unlinked").textContent).toContain("synthetic-output.3mf");
 expect(screen.queryByText("Synthetic prepared")).toBeNull();
});
it("navigation alone still links the valid completion to the real job store",async()=>{
 const complete=await pending();await complete();expect(useJob.getState().record?.prepared?.path).toBe("synthetic-output.3mf");expect(useUnlinkedCopies.getState().items).toEqual([]);
});

it("a newer refused Prepare cannot undo the invalidation caused by an explicit source edit",async()=>{
 const complete=await pending();
 fireEvent.change(screen.getByLabelText("Project file path"),{target:{value:"new-synthetic.3mf"}});
 fireEvent.click(screen.getByText("Inspect project"));await screen.findByText("Synthetic inspected");
 vi.mocked(prepareCreative).mockResolvedValueOnce({prepared:false,refusal:{kind:"synthetic"}} as never);
 fireEvent.click(screen.getByRole("button",{name:"Prepare a U1 copy"}));await screen.findByText("Synthetic prepared");
 await complete();expect(useJob.getState().record?.prepared).toBeNull();expect(useUnlinkedCopies.getState().items).toHaveLength(1);
});
