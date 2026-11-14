import { afterEach, describe, expect, it, vi } from "vitest";
import type { Topology } from "@/lib/extTypes";
import { convert } from "./api";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4321, token: "test-token" }) }));
Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "" } });
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; vi.restoreAllMocks(); });

const topo = (slots: number) => ({
  schema_version: "topology/1", snapshot_id: "snap-synthetic", heads: [], units: [], bindings: [], complete: true,
  slots: Array.from({ length: slots }, (_, i) => ({ id: `slot:${i}`, index: i })),
}) as unknown as Topology;
const ok = () => vi.fn().mockResolvedValue(new Response(JSON.stringify({ output_path: "C:/p/a_U1.3mf" }), { status: 200 }));
const bodyOf = (f: ReturnType<typeof vi.fn>) => JSON.parse(f.mock.calls[0][1].body as string);

describe("convert and the chosen printer setup", () => {
  it("sends no topology key at all without a setup", async () => {
    const f = ok(); globalThis.fetch = f;
    await convert("C:/p/a.3mf", undefined, "preserve", false);
    expect(Object.keys(bodyOf(f))).not.toContain("topology");
  });
  it("sends exactly the topology it was given, for a Prepare and for a dry-run review", async () => {
    const t = topo(8);
    for (const dry of [false, true]) {
      const f = ok(); globalThis.fetch = f;
      await convert("C:/p/a.3mf", undefined, "preserve", dry, undefined, t);
      expect(String(f.mock.calls[0][0])).toBe("http://127.0.0.1:4321/convert");
      expect(bodyOf(f).topology).toEqual(t);
      expect(bodyOf(f).dry_run).toBe(dry ? true : undefined);
    }
  });
  it("keeps materials and topology together when both are given", async () => {
    const f = ok(); globalThis.fetch = f;
    await convert("C:/p/a.3mf", undefined, "recommended", false, [{ slot: 0 } as never], topo(4));
    expect(bodyOf(f).materials).toEqual({ selections: [{ slot: 0 }] });
    expect(bodyOf(f).topology.slots).toHaveLength(4);
  });
});
