import { useEffect, useRef } from "react";
import { Box3, Color, PerspectiveCamera, Scene, Vector3, WebGLRenderer } from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { PaintedPreview } from "@/lib/paintedPreview";
import { buildModelScene, disposeModelScene, drawnColours, recolour, type ModelScene } from "@/components/job/modelScene";

export type ViewerLoss = "no-graphics" | "context-lost" | "failed";

interface Props {
  preview: PaintedPreview;
  colourFor: (slot: number | null) => string;
  highlightSlot: number | null;
  /** Bumped by "Reset view". */
  resetKey: number;
  /** Called once if drawing is impossible or stops; the parent shows the plate and says why. */
  onLost: (why: ViewerLoss) => void;
  label: string;
}

const tokenColour = (name: string, fallback: string) => {
  try {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const m = /^(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%$/.exec(raw);
    if (!m) return fallback;
    return `#${new Color().setHSL(Number(m[1]) / 360, Number(m[2]) / 100, Number(m[3]) / 100).getHexString()}`;
  } catch { return fallback; }
};

/**
 * A read-only 3D view of the project: orbit, zoom and pan, nothing else. It draws only what `paintedpreview/1`
 * carries, at the positions the engine placed it. It renders on demand (no animation loop), so a still view uses
 * no GPU time and reduced-motion needs no special case.
 */
export default function ModelViewer({ preview, colourFor, highlightSlot, resetKey, onLost, label }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef<{ scene: ModelScene; render: () => void; frame: () => void } | null>(null);
  const colours = useRef(colourFor);
  colours.current = colourFor;
  const lost = useRef(onLost);
  lost.current = onLost;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      lost.current("no-graphics");
      return;
    }
    const canvas = renderer.domElement;
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", label);
    canvas.dataset.testid = "model-canvas";
    canvas.style.cssText = "display:block;width:100%;height:100%;touch-action:none;outline-offset:2px";
    el.appendChild(canvas);
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    let scene: ModelScene;
    try {
      scene = buildModelScene(preview, colours.current, tokenColour("--border", "#c8ced6"));
    } catch {
      renderer.dispose();
      canvas.remove();
      lost.current("failed");
      return;
    }
    const three = new Scene();
    three.add(scene.root);
    const camera = new PerspectiveCamera(35, 1, 1, 5000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = false;
    controls.screenSpacePanning = true;
    controls.listenToKeyEvents(canvas);
    controls.keyPanSpeed = 20;

    const render = () => { renderer.render(three, camera); };
    const frame = () => {
      const box = new Box3(scene.box.min, scene.box.max);
      const size = box.getSize(new Vector3());
      const center = box.getCenter(new Vector3());
      const radius = Math.max(size.length() / 2, 10);
      // Fit the narrower of the two view angles, so a tall, narrow canvas does not crop the model.
      const vfov = (camera.fov * Math.PI) / 180;
      const fit = Math.min(vfov, 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect));
      const distance = (radius / Math.sin(fit / 2)) * 1.12;
      camera.position.copy(center).add(new Vector3(-0.55, -1, 0.75).normalize().multiplyScalar(distance));
      camera.near = Math.max(distance / 100, 0.5);
      camera.far = distance * 10;
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      controls.update();
      render();
    };
    controls.addEventListener("change", render);

    const size = () => {
      const w = Math.max(el.clientWidth, 1), h = Math.max(el.clientHeight, 1);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    };
    const ro = new ResizeObserver(size);
    ro.observe(el);
    const onContextLost = (e: Event) => { e.preventDefault(); lost.current("context-lost"); };
    canvas.addEventListener("webglcontextlost", onContextLost);

    size();
    frame();
    live.current = { scene, render, frame };
    el.dataset.drawn = drawnColours(scene);
    el.dataset.instances = String(scene.instances);
    el.dataset.triangles = String(scene.triangles);

    return () => {
      live.current = null;
      ro.disconnect();
      canvas.removeEventListener("webglcontextlost", onContextLost);
      controls.removeEventListener("change", render);
      controls.dispose();
      disposeModelScene(scene);
      renderer.dispose();
      renderer.forceContextLoss();           // free the GPU context now rather than waiting for the browser to collect it
      canvas.remove();
      delete el.dataset.drawn;
    };
    // The scene is rebuilt only for a different preview; colours and highlight are applied in place below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview]);

  useEffect(() => {
    const l = live.current;
    if (!l || !host.current) return;
    recolour(l.scene, colourFor, highlightSlot);
    host.current.dataset.drawn = drawnColours(l.scene);
    l.render();
  }, [colourFor, highlightSlot]);

  useEffect(() => { if (resetKey > 0) live.current?.frame(); }, [resetKey]);

  return <div ref={host} className="h-full w-full" data-testid="model-viewer" />;
}
