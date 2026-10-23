// The three.js scene for the painted preview, built from `paintedpreview/1` and nothing else.
//
// No WebGL here: this only creates geometry, materials and objects, so it runs (and is tested) without a
// graphics context. ModelViewer owns the renderer. The scene is read-only by construction: there is no
// picking, no transform control and no edit tool, and an instance's matrix is the one the engine placed it at.
import {
  BufferGeometry, Color, DirectionalLight, DoubleSide, Float32BufferAttribute, Group, HemisphereLight,
  LineBasicMaterial, LineLoop, Matrix4, Mesh, MeshStandardMaterial, Vector3,
} from "three";
import { NEUTRAL, decodeFloat32, type PaintedPreview } from "@/lib/paintedPreview";

export interface ModelScene {
  root: Group;
  /** One material per slot actually drawn (null = surface the project states nothing for). */
  materials: Map<number | null, MeshStandardMaterial>;
  /** Triangles drawn, for the "what you are looking at" line. */
  triangles: number;
  /** The extent of what is placed, in mm, for framing the camera (the bed outline is context, not framed). */
  box: { min: Vector3; max: Vector3 };
  instances: number;
  /** Distinct geometries: repeated instances share one. */
  geometries: number;
}

export function buildModelScene(preview: PaintedPreview, colourFor: (slot: number | null) => string, bedColour = "#c8ced6"): ModelScene {
  const root = new Group();
  root.name = "painted-preview";
  const materials = new Map<number | null, MeshStandardMaterial>();
  const material = (slot: number | null) => {
    let m = materials.get(slot);
    if (!m) {
      m = new MeshStandardMaterial({ color: new Color(colourFor(slot)), roughness: 0.65, metalness: 0, side: DoubleSide });
      materials.set(slot, m);
    }
    return m;
  };

  const geometry = new Map<string, { slot: number | null; geometry: BufferGeometry }[]>();
  let triangles = 0;
  for (const mesh of preview.meshes) {
    const parts = mesh.parts.map((part) => {
      const g = new BufferGeometry();
      g.setAttribute("position", new Float32BufferAttribute(decodeFloat32(part.positions_f32le_base64), 3));
      g.computeVertexNormals();
      return { slot: part.slot, geometry: g };
    });
    geometry.set(mesh.key, parts);
  }

  const min = new Vector3(Infinity, Infinity, Infinity);
  const max = new Vector3(-Infinity, -Infinity, -Infinity);
  let instances = 0;
  for (const inst of preview.instances) {
    const parts = geometry.get(inst.mesh);
    if (!parts) continue;
    instances += 1;
    const matrix = new Matrix4().fromArray(inst.world_mm);          // column-major, millimetres, as the engine placed it
    const group = new Group();
    group.name = inst.label;
    group.userData = { instance: inst.id, label: inst.label };
    group.matrixAutoUpdate = false;
    group.matrix.copy(matrix);
    for (const part of parts) {
      const m = new Mesh(part.geometry, material(part.slot));
      m.userData = { slot: part.slot };
      group.add(m);
      triangles += part.geometry.getAttribute("position").count / 3;
      part.geometry.computeBoundingBox();
      const b = part.geometry.boundingBox!.clone().applyMatrix4(matrix);
      min.min(b.min); max.max(b.max);
    }
    root.add(group);
  }

  const polygon = preview.bed?.polygon_mm;
  if (polygon && polygon.length >= 3) {
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(polygon.flatMap(([x, y]) => [x, y, 0]), 3));
    const bed = new LineLoop(g, new LineBasicMaterial({ color: new Color(bedColour) }));
    bed.name = "bed";
    root.add(bed);
  }
  if (!Number.isFinite(min.x)) { min.set(0, 0, 0); max.set(1, 1, 1); }

  const sky = new HemisphereLight(0xffffff, 0x8a8f98, 1.1);
  sky.name = "light-sky";
  const key = new DirectionalLight(0xffffff, 1.6);
  key.position.set(-1, -2, 3);
  key.name = "light-key";
  root.add(sky, key);

  return { root, materials, triangles, box: { min, max }, instances, geometries: geometry.size };
}

/** Recolour in place (Original ↔ Proposed, or a new choice) without touching the geometry. A highlighted slot keeps its
 *  colour and glows a little; every other slot is washed toward grey, so the eye finds it without any surface turning see-through. */
export function recolour(scene: ModelScene, colourFor: (slot: number | null) => string, highlight: number | null = null) {
  for (const [slot, m] of scene.materials) {
    const base = new Color(colourFor(slot));
    const dim = highlight !== null && slot !== highlight;
    m.color.copy(dim ? base.lerp(WASH, 0.78) : base);
    m.emissive.copy(highlight !== null && slot === highlight ? base.clone().multiplyScalar(0.3) : new Color(0x000000));
    m.needsUpdate = true;
  }
}

const WASH = new Color(0x8a8f98);

/** "slot:colour" pairs as drawn, for tests and for the page to expose what the canvas shows. */
export function drawnColours(scene: ModelScene): string {
  return [...scene.materials.entries()]
    .sort(([a], [b]) => (a ?? 99) - (b ?? 99))
    .map(([slot, m]) => `${slot ?? "none"}:#${m.color.getHexString().toUpperCase()}`)
    .join(" ");
}

export function disposeModelScene(scene: ModelScene) {
  const seen = new Set<BufferGeometry>();
  scene.root.traverse((o) => {
    const g = (o as Mesh).geometry as BufferGeometry | undefined;
    if (g && !seen.has(g)) { seen.add(g); g.dispose(); }
  });
  for (const m of scene.materials.values()) m.dispose();
}

export { NEUTRAL };
