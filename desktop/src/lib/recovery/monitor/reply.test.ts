import { expect, it } from "vitest";
import { validateMonitoringReply } from "./reply";
it.each([
  {note:{text:"bad"}}, {association:[]}, {filename:{name:"bad"}}, {camera:{state:{}}}, {camera:[]},
  {reconciliation:{state:"standby",source:"polling",events:{}}},
  {reconciliation:{state:"standby",source:"polling",events:[{kind:"change",from:{},to:"standby"}]}},
  {reconciliation:{state:"standby",source:"polling",events:Array(33).fill({kind:"change",from:"printing",to:"standby"})}},
])("refuses nested status fields React cannot safely render: %j", extra => {
  expect(()=>validateMonitoringReply("read",{status:"ok",print_state:"standby",...extra})).toThrow(/not usable/);
});
it.each([
  {filename:{}}, {filename:[]}, {outcome:{}}, {outcome:[]},
])("refuses malformed history text: %j", extra => {
  expect(()=>validateMonitoringReply("history",{status:"ok",last_job:{filename:"synthetic.gcode",outcome:"completed",...extra}})).toThrow(/not usable/);
});
it("keeps valid unknown states, absent camera and empty history without inventing a job",()=>{
  expect(validateMonitoringReply("read",{status:"unavailable",reason:"invalid_reply"})).toEqual({status:"unavailable",reason:"invalid_reply"});
  expect(validateMonitoringReply("history",{status:"ok",last_job:null})).toEqual({status:"ok",last_job:null});
  expect(validateMonitoringReply("read",{status:"ok",print_state:"unknown",camera:{state:"unknown"},reconciliation:{state:"unknown",source:"polling",events:[]}})).toMatchObject({print_state:"unknown"});
});
