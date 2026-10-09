import { describe, expect, it } from "vitest";
import { createReadOnlyViewport, ViewerUnavailableError, type ReadOnlyViewport } from "./readOnlyViewport";
import { makeFakeFactory } from "./fakeViewport";
import { buildModel, buildViewScene } from "./sceneModel";
import { offBedScene } from "./sceneFixtures";

const canvas = () => ({ addEventListener() {}, removeEventListener() {} }) as unknown as HTMLCanvasElement;

describe("read-only viewport facade", () => {
  it("fixes the tool to probe and calls nothing that edits", () => {
    const { factory, stats } = makeFakeFactory();
    const vp = createReadOnlyViewport(canvas(), factory, "dark");
    const s = offBedScene();
    vp.show(buildViewScene(s, buildModel(s)));
    vp.setSelected(["b1"]);
    vp.setCamera("top");
    vp.setSlopeView(true);
    vp.setSlopeView(false);
    vp.setTheme("light");
    const tools = stats.calls.filter((c) => c.startsWith("setTool"));
    expect(tools).toEqual(["setTool:probe"]);
    const editing = /paint|cut|scale|rotate|transform|arrange|sketch|push|brim|setPaint|setCutPlane|setTransforms|setPartStyle/i;
    expect(stats.calls.filter((c) => editing.test(c))).toEqual([]);
    expect(stats.calls).toContain("view:top");
    expect(stats.calls).toContain("setRenderMode:overhang");
  });

  it("exposes exactly the inspection surface and never the raw viewport", () => {
    const { factory } = makeFakeFactory();
    const vp = createReadOnlyViewport(canvas(), factory, "light");
    expect(Object.keys(vp).sort()).toEqual(
      ["dispose", "onPick", "onTrouble", "setCamera", "setSelected", "setSlopeView", "setTheme", "show"],
    );
    for (const value of Object.values(vp)) expect(typeof value).toBe("function");
  });

  it("does not type-check any editing call (type-level test)", () => {
    const vp = null as unknown as ReadOnlyViewport;
    const never = () => {
      // @ts-expect-error no setTool on the facade
      vp.setTool("move");
      // @ts-expect-error no setPlate on the facade
      vp.setPlate({});
      // @ts-expect-error no paint settings on the facade
      vp.setPaintSettings({});
      // @ts-expect-error no cut plane on the facade
      vp.setCutPlane(null);
      // @ts-expect-error no transforms on the facade
      vp.setTransforms({});
      // @ts-expect-error no arrange on the facade
      vp.arrange();
      // @ts-expect-error no raw handle
      vp.viewport;
      // @ts-expect-error camera presets are a closed set
      vp.setCamera("paint");
    };
    expect(typeof never).toBe("function");
  });

  it("turns a failed WebGL start into ViewerUnavailableError", () => {
    const { factory } = makeFakeFactory({ failCreate: () => true });
    expect(() => createReadOnlyViewport(canvas(), factory, "dark")).toThrow(ViewerUnavailableError);
  });

  it("forwards picks and trouble, stops after unsubscribe, and disposes once", () => {
    const { factory, stats, emit } = makeFakeFactory();
    const vp = createReadOnlyViewport(canvas(), factory, "dark");
    const picks: (string | null)[] = [];
    const fatals: boolean[] = [];
    const off = vp.onPick((id) => picks.push(id));
    vp.onTrouble((t) => fatals.push(t.fatal));
    emit("pick", { objectId: "b1" });
    emit("error", { message: "x" });
    emit("degrade", { message: "slow" });
    off();
    emit("pick", { objectId: "b0" });
    expect(picks).toEqual(["b1"]);
    expect(fatals).toEqual([true, false]);
    vp.dispose();
    vp.dispose();
    expect(stats.disposed).toBe(1);
    expect(stats.liveListeners).toBe(0);
    vp.setCamera("top");
    expect(stats.calls.filter((c) => c === "view:top")).toEqual([]);
  });
});
