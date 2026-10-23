import { describe, expect, it } from "vitest";
import { Mesh } from "three";
import bambu from "@/test-fixtures/paintedPreview.bambu-authored.json";
import { buildModelScene, disposeModelScene, drawnColours, recolour } from "@/components/job/modelScene";
import { colourOf, legend, type PaintedPreview } from "@/lib/paintedPreview";

const real = bambu as unknown as PaintedPreview;

function floats(...v: number[]) {
  return btoa(String.fromCharCode(...new Uint8Array(new Float32Array(v).buffer)));
}
const TRI = [0, 0, 0, 10, 0, 0, 0, 10, 0];
const at = (x: number) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, 0, 0, 1];

function synthetic(over: Partial<PaintedPreview> = {}): PaintedPreview {
  return {
    schema: "paintedpreview/1", available: true, state: "ok", reason: null, kind: "painted",
    bed: { polygon_mm: [[0, 0], [270, 0], [270, 270], [0, 270]], height_mm: 270 },
    slots: [1, 2, 3, 4, 5].map((n) => ({
      slot: n, colour: ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF"][n - 1], declared: true,
      from_painting: true, from_assignment: false, painted_triangles: 1, area_mm2: 50, painted_area_mm2: 50,
    })),
    unknown_default: false,
    meshes: [{ key: "m#1", parts: [1, 2, 3, 4, 5].map((n) => ({ slot: n, triangles: 1, positions_f32le_base64: floats(...TRI.map((c, i) => c + (i % 3 === 2 ? n : 0))) })) }],
    instances: [0, 1, 2].map((i) => ({ id: `i${i}`, mesh: "m#1", world_mm: at(i * 60), label: `Object 1 · instance ${i + 1} of 3`, instance_index: i, instance_count: 3 })),
    counts: { triangles_out: 5, painted_triangles: 5, leaves: 5, malformed: 0 }, notes: [],
    ...over,
  };
}

const slotsDrawn = (s: ReturnType<typeof buildModelScene>) =>
  [...s.materials.keys()].sort((a, b) => (a ?? 99) - (b ?? 99));

describe("buildModelScene", () => {
  it("draws what the engine returned: its triangles, one material per slot, in the project's colours", () => {
    const rows = legend(real, {});
    const scene = buildModelScene(real, colourOf(rows, "original"));
    expect(scene.triangles).toBe(real.counts.triangles_out * real.instances.length);
    // Slot 3 is listed by the project but has no surface, so nothing is drawn in it.
    expect(slotsDrawn(scene)).toEqual([1, 2]);
    expect(drawnColours(scene)).toBe("1:#00AE42 2:#FFFF00");
    disposeModelScene(scene);
  });

  it("repeated instances are distinct objects at their own places sharing one geometry", () => {
    const scene = buildModelScene(synthetic(), colourOf(legend(synthetic(), {}), "original"));
    const groups = scene.root.children.filter((c) => c.userData.instance);
    expect(groups.map((g) => g.userData.label)).toEqual(["Object 1 · instance 1 of 3", "Object 1 · instance 2 of 3", "Object 1 · instance 3 of 3"]);
    expect(groups.map((g) => g.matrix.elements[12])).toEqual([0, 60, 120]);
    const firstPart = (g: (typeof groups)[number]) => (g.children[0] as Mesh).geometry;
    expect(firstPart(groups[0])).toBe(firstPart(groups[1]));
    expect(scene.geometries).toBe(1);
    expect(scene.instances).toBe(3);
    expect(scene.triangles).toBe(15);
  });

  it("more than four slots are all drawn, each in its own colour, none merged or dropped", () => {
    const p = synthetic();
    const scene = buildModelScene(p, colourOf(legend(p, {}), "original"));
    expect(slotsDrawn(scene)).toEqual([1, 2, 3, 4, 5]);
    expect(drawnColours(scene)).toBe("1:#FF0000 2:#00FF00 3:#0000FF 4:#FFFF00 5:#FF00FF");
  });

  it("unknown surface (slot null) is drawn neutral, not in slot 1's colour", () => {
    const p = synthetic({ slots: [], meshes: [{ key: "m#1", parts: [{ slot: null, triangles: 1, positions_f32le_base64: floats(...TRI) }] }], instances: [synthetic().instances[0]], kind: "geometry" });
    const scene = buildModelScene(p, colourOf(legend(p, {}), "original"));
    expect(drawnColours(scene)).toBe("none:#9AA0A6");
  });

  it("recolouring changes the chosen slot only and never the geometry", () => {
    const p = synthetic();
    const scene = buildModelScene(p, colourOf(legend(p, {}), "original"));
    const before = scene.root.children.filter((c) => c.userData.instance).map((g) => (g.children[0] as Mesh).geometry);
    recolour(scene, colourOf(legend(p, { 2: "#123456" }), "proposed"));
    expect(drawnColours(scene)).toBe("1:#FF0000 2:#123456 3:#0000FF 4:#FFFF00 5:#FF00FF");
    expect(scene.root.children.filter((c) => c.userData.instance).map((g) => (g.children[0] as Mesh).geometry)).toEqual(before);
  });

  it("highlighting a slot washes the others toward grey, makes none see-through, and restores them after", () => {
    const p = synthetic();
    const colours = colourOf(legend(p, {}), "original");
    const scene = buildModelScene(p, colours);
    recolour(scene, colours, 3);
    const hex = (s: number) => scene.materials.get(s)!.color.getHexString().toUpperCase();
    expect(hex(3)).toBe("0000FF");                                   // the chosen slot keeps its own colour
    expect(hex(1)).not.toBe("FF0000");
    expect(hex(2)).not.toBe("00FF00");
    expect([...scene.materials.values()].every((m) => !m.transparent && m.opacity === 1)).toBe(true);
    expect(scene.materials.get(3)!.emissive.getHex()).not.toBe(0);
    recolour(scene, colours, null);
    expect(drawnColours(scene)).toBe("1:#FF0000 2:#00FF00 3:#0000FF 4:#FFFF00 5:#FF00FF");
    expect([...scene.materials.values()].every((m) => m.emissive.getHex() === 0)).toBe(true);
  });

  it("an instance whose mesh was not returned is skipped, not drawn at the origin", () => {
    const p = synthetic({ instances: [{ ...synthetic().instances[0], mesh: "missing#9" }] });
    expect(buildModelScene(p, () => "#fff").instances).toBe(0);
  });

  it("frames what is placed, not the 270 mm bed around it", () => {
    const scene = buildModelScene(synthetic(), () => "#fff");
    expect(scene.box.min.x).toBe(0);
    expect(scene.box.max.x).toBe(130);                 // third instance at x = 120, 10 mm wide
    expect(scene.root.getObjectByName("bed")).toBeTruthy();
  });
});
