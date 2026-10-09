import { describe, expect, it } from "vitest";
import { createReadOnlyViewport, type InspectionPort, type ReadOnlyViewport } from "./readOnlyViewport";
import { makeFakeFactory, makeFakePort, type FakeStats } from "./fakeViewport";
import { buildModel, buildViewScene } from "./sceneModel";
import { offBedScene } from "./sceneFixtures";

const canvas = () => ({ addEventListener() {}, removeEventListener() {}, isConnected: true }) as unknown as HTMLCanvasElement;
const fresh = () => {
  const stats: FakeStats = { created: 0, disposed: 0, liveContexts: 0, peakContexts: 0, liveListeners: 0, disposedDetached: 0, calls: [] };
  const handlers = new Map<string, Set<(p: never) => void>>();
  const emit = (event: string, payload: unknown) => { for (const h of [...(handlers.get(event) ?? [])]) (h as (p: unknown) => void)(payload); };
  return { stats, emit, port: makeFakePort(canvas(), stats, handlers) };
};

describe("read-only viewport facade", () => {
  it("calls only inspection members of the port", () => {
    const { port, stats } = fresh();
    const vp = createReadOnlyViewport(port, "dark");
    const s = offBedScene();
    vp.show(buildViewScene(s, buildModel(s)));
    vp.setSelected(["b1"]);
    vp.setCamera("top");
    vp.setSlopeView(true);
    vp.setSlopeView(false);
    vp.setTheme("light");
    const editing = /paint|cut|scale|rotate|transform|arrange|sketch|push|brim|setTool|setPartStyle/i;
    expect(stats.calls.filter((c) => editing.test(c))).toEqual([]);
    expect(stats.calls).toContain("view:top");
    expect(stats.calls).toContain("setRenderMode:overhang");
  });

  it("exposes exactly the inspection surface and never the port or the raw viewport", () => {
    const vp = createReadOnlyViewport(fresh().port, "light");
    expect(Object.keys(vp).sort()).toEqual(
      ["dispose", "onPick", "onSelect", "onTrouble", "setCamera", "setSelected", "setSlopeView", "setTheme", "show"],
    );
    for (const value of Object.values(vp)) expect(typeof value).toBe("function");
  });

  it("does not type-check any editing call, setTool or a generic subscription (type-level test)", () => {
    const vp = null as unknown as ReadOnlyViewport;
    const port = null as unknown as InspectionPort;
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
      // @ts-expect-error no generic event subscription on the facade
      vp.on("transform", () => undefined);
      // @ts-expect-error no raw handle
      vp.viewport;
      // @ts-expect-error camera presets are a closed set
      vp.setCamera("paint");
      // @ts-expect-error the port has no setTool either
      port.setTool("move");
      // @ts-expect-error the port has no generic on
      port.on("transform", () => undefined);
      // @ts-expect-error the port has no editing calls
      port.setCutPlane(null);
    };
    expect(typeof never).toBe("function");
  });

  it("forwards picks, selection clears and trouble, stops after unsubscribe, and disposes once", () => {
    const { port, stats, emit } = fresh();
    const vp = createReadOnlyViewport(port, "dark");
    const picks: (string | null)[] = [];
    const selects: string[][] = [];
    const fatals: boolean[] = [];
    const off = vp.onPick((id) => picks.push(id));
    vp.onSelect((ids) => selects.push(ids));
    vp.onTrouble((t) => fatals.push(t.fatal));
    emit("pick", { objectId: "b1" });
    emit("select", { ids: [] });
    emit("error", { message: "x" });
    emit("degrade", { message: "slow" });
    off();
    emit("pick", { objectId: "b0" });
    expect(picks).toEqual(["b1"]);
    expect(selects).toEqual([[]]);
    expect(fatals).toEqual([true, false]);
    vp.dispose();
    vp.dispose();
    expect(stats.disposed).toBe(1);
    expect(stats.liveListeners).toBe(0);
    vp.setCamera("top");
    expect(stats.calls.filter((c) => c === "view:top")).toEqual([]);
  });

  it("the fake factory builds the same facade", () => {
    const { factory, stats } = makeFakeFactory();
    const vp = factory(canvas(), { theme: "dark" });
    vp.dispose();
    expect(stats.created).toBe(1);
    expect(stats.disposed).toBe(1);
  });
});
