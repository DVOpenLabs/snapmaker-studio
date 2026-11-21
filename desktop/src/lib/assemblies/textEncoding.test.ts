import { expect,it } from "vitest";
const sources=import.meta.glob<string>("./*.{ts,tsx}",{query:"?raw",import:"default",eager:true});
it("keeps UTF-8 UI source free of encoding-round-trip damage",()=>{
 const bad=String.fromCodePoint(0xe2,0x20ac,0xa6);
 for(const [name,source] of Object.entries(sources)){
  expect(source,name).not.toContain(bad);expect(source,name).not.toContain(String.fromCodePoint(0xfffd));
 }
});
