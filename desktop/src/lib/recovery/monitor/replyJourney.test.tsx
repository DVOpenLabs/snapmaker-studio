// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MonitoringPanel from "./MonitoringPanel";
vi.mock("@/api",()=>({apiInfo:vi.fn(async()=>({port:4321,token:"synthetic-monitor-token"}))}));
vi.mock("@/store/printer",()=>({usePrinter:(select:(s:{host:string})=>unknown)=>select({host:"synthetic.local"})}));
const original=globalThis.fetch;
let malformedRead=true, malformedHistory=false;
beforeEach(()=>{
 malformedRead=true;malformedHistory=false;
 globalThis.fetch=vi.fn(async url=>new Response(JSON.stringify(String(url).endsWith("/read")
  ? malformedRead ? {status:"ok",print_state:"standby",reconciliation:{state:"standby",source:"polling",events:{}}} : {status:"ok",print_state:"standby"}
  : {status:"ok",last_job:{filename:malformedHistory?{name:"bad"}:"synthetic.gcode",outcome:"completed"}})));
});
afterEach(()=>{cleanup();globalThis.fetch=original;});
function read(){fireEvent.click(screen.getByText("Read status"));}
it("real transport refuses a malformed status, keeps independent history and recovers on explicit retry",async()=>{
 render(<MonitoringPanel/>); fireEvent.change(screen.getByLabelText("Configured printer host"),{target:{value:"synthetic.local"}}); read();
 expect(await screen.findByRole("alert")).toHaveProperty("textContent",expect.stringContaining("status reply was not usable"));
 expect(await screen.findByText("synthetic.gcode: completed")).toBeTruthy();
 malformedRead=false;read();expect(await screen.findByText("Printer state reported: standby")).toBeTruthy();expect(screen.queryByRole("alert")).toBeNull();
 for(const call of vi.mocked(fetch).mock.calls) expect(String(call[0])).toMatch(/^http:\/\/127\.0\.0\.1:4321\/monitoring\/(read|history)$/);
});
it("real transport refuses malformed history without hiding usable status",async()=>{
 malformedRead=false;malformedHistory=true;render(<MonitoringPanel/>);fireEvent.change(screen.getByLabelText("Configured printer host"),{target:{value:"synthetic.local"}});read();
 expect(await screen.findByText("Printer state reported: standby")).toBeTruthy();expect(await screen.findByText("Last-job history is unavailable for this read.")).toBeTruthy();
 expect(screen.queryByRole("heading",{name:"Last job"})).toBeNull();
});
