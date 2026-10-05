import { describe, expect, it } from "vitest";
import {
  MAX_RECENT, SITE_DATA_COPY, failureMessage, familyLabel, isRegistered, pushRecent,
  refusalMessage, siteDisplayName, toAddedItem, type RegisteredModel,
} from "./modelDownloads";

const ok = (over: Partial<RegisteredModel> = {}): RegisteredModel => ({
  ok: true, project_id: 7, name: "Gearbox.3mf", filename: "Gearbox.3mf", site: "makerworld.com",
  site_name: "MakerWorld", source_family: "bambu", verdict: "REPAIRABLE", filament_count: 3, ...over,
});

describe("siteDisplayName", () => {
  it("names the approved sites, including subdomains", () => {
    expect(siteDisplayName("www.printables.com")).toBe("Printables");
    expect(siteDisplayName("makerworld.com")).toBe("MakerWorld");
    expect(siteDisplayName("files.printables.com")).toBe("Printables");
  });
  it("never invents a name or accepts a look-alike", () => {
    expect(siteDisplayName("printables.com.evil.example")).toBe("printables.com.evil.example");
    expect(siteDisplayName("notmakerworld.com")).toBe("notmakerworld.com");
    expect(siteDisplayName("")).toBe("the site");
  });
});

describe("toAddedItem", () => {
  it("heads the card with the site and states only what the engine detected", () => {
    const item = toAddedItem("C:/dl/Gearbox.3mf", ok());
    expect(item.heading).toBe("Added from MakerWorld");
    expect(item.name).toBe("Gearbox.3mf");
    expect(item.facts).toEqual([
      "Bambu Studio project",
      "3 filaments in the project",
      "Made for another printer or needs a few fixes — Studio can prepare a U1 copy.",
    ]);
    expect(item.needsPrepare).toBe(true);
  });
  it("a READY project does not push Prepare and claims no more than compatibility", () => {
    const item = toAddedItem("p", ok({ verdict: "READY", source_family: "u1", filament_count: 1 }));
    expect(item.needsPrepare).toBe(false);
    expect(item.facts).toContain("Profile compatible with the U1.");
    expect(item.facts.join(" ")).not.toMatch(/will print|guarantee|success/i);
  });
  it("unknown facts stay unknown (no family, no verdict, no filament count)", () => {
    const item = toAddedItem("p", ok({ source_family: null, verdict: null, filament_count: null }));
    expect(item.facts).toEqual([]);
  });
  it("uses singular for one filament and omits zero", () => {
    expect(toAddedItem("p", ok({ filament_count: 1 })).facts).toContain("1 filament in the project");
    expect(toAddedItem("p", ok({ filament_count: 0 })).facts.join(" ")).not.toMatch(/filament/);
  });
  it("falls back to the host when the engine sends no display name", () => {
    expect(toAddedItem("p", ok({ site_name: undefined, site: "www.printables.com" })).heading)
      .toBe("Added from Printables");
  });
});

describe("isRegistered", () => {
  it("requires ok:true AND a project id", () => {
    expect(isRegistered(ok())).toBe(true);
    expect(isRegistered({ ok: true })).toBe(false);
    expect(isRegistered({ ok: false, project_id: 3 })).toBe(false);
    expect(isRegistered(null)).toBe(false);
    expect(isRegistered(undefined)).toBe(false);
  });
});

describe("pushRecent", () => {
  it("is newest first, one per file, and capped", () => {
    let list: ReturnType<typeof toAddedItem>[] = [];
    for (let i = 0; i < MAX_RECENT + 3; i++) list = pushRecent(list, toAddedItem(`/p/${i}.3mf`, ok({ name: `${i}` })));
    expect(list).toHaveLength(MAX_RECENT);
    expect(list[0].path).toBe(`/p/${MAX_RECENT + 2}.3mf`);
    const again = pushRecent(list, toAddedItem(`/p/${MAX_RECENT + 1}.3mf`, ok()));
    expect(again).toHaveLength(MAX_RECENT);
    expect(again[0].path).toBe(`/p/${MAX_RECENT + 1}.3mf`);
  });
});

describe("messages", () => {
  it("a refused download names the file type Studio accepts", () => {
    expect(refusalMessage("model.zip")).toMatch(/"model.zip" was not added/);
    expect(refusalMessage("model.zip")).toMatch(/\.3mf and \.stl/);
    expect(refusalMessage("")).toMatch(/^That download was not added/);
  });
  it("a failure never echoes more than the engine's own detail", () => {
    expect(failureMessage()).toBe("Studio could not add that download to your library.");
    expect(failureMessage("not a valid 3MF")).toContain("not a valid 3MF");
  });
  it("sign-in copy promises exactly what the design guarantees", () => {
    const text = (SITE_DATA_COPY.signIn + " " + SITE_DATA_COPY.clear).toLowerCase();
    expect(text).toContain("never sees your password or cookies");
    expect(text).toContain("does not touch studio's own settings");
    expect(text).not.toMatch(/store.*password|save.*password/);
  });
  it("family labels exist only for families Studio knows", () => {
    expect(familyLabel("prusa")).toBe("PrusaSlicer project");
    expect(familyLabel("something_new")).toBeNull();
    expect(familyLabel(null)).toBeNull();
  });
});
