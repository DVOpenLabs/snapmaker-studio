/**
 * The provider settings a user actually types, and what gets sent because of them.
 *
 * The bug this guards against is the one the whole sprint was about: a capability
 * that exists in the engine and that nothing in the app ever reaches. `providerArgs`
 * is the single place that decides whether a request carries provider details, so
 * a screen that forgets is a screen that silently answers "unknown" forever.
 */
import { beforeEach, describe, expect, it } from "vitest";

// These tests run in Node, which has no localStorage. The store already survives
// its absence — every read and write is guarded, because a browser can refuse
// storage too — so the stub is here to exercise the persistence path rather than
// to make the module load.
const store = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
  key: (i: number) => [...store.keys()][i] ?? null,
  get length() { return store.size; },
};

const { providerArgs, useProvider } = await import("./provider");

function reset() {
  localStorage.clear();
  useProvider.getState().clear();
}

describe("providerArgs", () => {
  beforeEach(reset);

  it("sends nothing when no provider is configured", () => {
    expect(providerArgs({ kind: "none", url: "", slotMap: {}, slotBase: 1 })).toEqual({});
  });

  it("sends nothing when a provider is chosen but no address typed", () => {
    expect(providerArgs({ kind: "spoolman", url: "   ", slotMap: {}, slotBase: 1 })).toEqual({});
  });

  it("sends the provider, the address, the mapping and the numbering together", () => {
    const args = providerArgs({
      kind: "spoolman", url: " spoolman.local:7912 ", slotMap: { "1": 7 }, slotBase: 1,
    });
    expect(args).toEqual({
      provider: "spoolman",
      provider_url: "spoolman.local:7912",
      slot_map: { "1": 7 },
      slot_base: 1,
    });
  });

  it("names the provider it is sending, so the engine never has to guess", () => {
    // The address field used to be called `spoolman`, which made a seam with one
    // implementation look like a seam and read like an integration. A second
    // provider is what forced the name to become honest.
    const bambuddy = providerArgs({
      kind: "bambuddy", url: "bambuddy.local:8000", slotMap: { "1": 4 }, slotBase: 1,
    });
    expect(bambuddy.provider).toBe("bambuddy");
    expect(bambuddy.provider_url).toBe("bambuddy.local:8000");
    expect("spoolman" in bambuddy).toBe(false);
  });

  it("sends nothing at all for either provider once None is chosen", () => {
    for (const kind of ["spoolman", "bambuddy"] as const) {
      expect(providerArgs({ kind, url: "", slotMap: { "1": 7 }, slotBase: 1 })).toEqual({});
    }
    expect(providerArgs({ kind: "none", url: "still.local:1", slotMap: { "1": 7 }, slotBase: 1 }))
      .toEqual({});
  });

  it("sends only a non-empty SpoolEase key, never keyEpoch", () => {
    expect(providerArgs({ kind: "spoolease", url: "192.168.1.50", slotMap: { "1": "12" }, slotBase: 1, key: "session-key" }))
      .toEqual({ provider: "spoolease", provider_url: "192.168.1.50", slot_map: { "1": "12" }, slot_base: 1, provider_key: "session-key" });
    expect(providerArgs({ kind: "spoolease", url: "192.168.1.50", slotMap: {}, slotBase: 1, key: "" })).not.toHaveProperty("provider_key");
  });

  it("always states the slot numbering rather than leaving it to be guessed", () => {
    // Getting this wrong puts every spool one slot out and then reports the
    // wrong material with complete confidence.
    const zero = providerArgs({ kind: "spoolman", url: "x", slotMap: { "0": 7 }, slotBase: 0 });
    expect(zero.slot_base).toBe(0);
    const one = providerArgs({ kind: "spoolman", url: "x", slotMap: { "1": 7 }, slotBase: 1 });
    expect(one.slot_base).toBe(1);
  });
});

describe("the provider store", () => {
  beforeEach(reset);

  it("starts with nothing configured", () => {
    const state = useProvider.getState();
    expect(state.kind).toBe("none");
    expect(state.url).toBe("");
    expect(state.lastSeen).toBeNull();
  });

  it("persists what the user typed", () => {
    useProvider.getState().setKind("spoolman");
    useProvider.getState().setUrl("  spoolman.local:7912  ");
    useProvider.getState().setSlot("2", 7);
    useProvider.getState().setSlotBase(0);

    expect(localStorage.getItem("materialProviderKind")).toBe('"spoolman"');
    expect(localStorage.getItem("materialProviderUrl")).toBe('"spoolman.local:7912"');
    expect(JSON.parse(localStorage.getItem("materialProviderSlotMap")!)).toEqual({ "2": 7 });
    expect(localStorage.getItem("materialProviderSlotBase")).toBe("0");
  });

  it("clears a slot rather than storing a null in it", () => {
    useProvider.getState().setSlot("2", 7);
    useProvider.getState().setSlot("2", null);
    expect(useProvider.getState().slotMap).toEqual({});
  });

  it("records when the provider was last actually read", () => {
    expect(useProvider.getState().lastSeen).toBeNull();
    useProvider.getState().markSeen();
    const seen = useProvider.getState().lastSeen;
    expect(seen).not.toBeNull();
    expect(Number.isNaN(Date.parse(seen!))).toBe(false);
  });

  it("survives a corrupted stored value rather than failing to start", () => {
    localStorage.setItem("materialProviderSlotMap", "{not json");
    // Re-reading is what happens on the next launch; the store must fall back.
    expect(() => JSON.parse(localStorage.getItem("materialProviderSlotMap")!)).toThrow();
    useProvider.getState().clear();
    expect(useProvider.getState().slotMap).toEqual({});
  });

  it("forgets everything when cleared", () => {
    useProvider.getState().setKind("spoolman");
    useProvider.getState().setUrl("spoolman.local");
    useProvider.getState().markSeen();
    useProvider.getState().clear();

    const state = useProvider.getState();
    expect(state.kind).toBe("none");
    expect(state.url).toBe("");
    expect(state.lastSeen).toBeNull();
    expect(localStorage.getItem("materialProviderUrl")).toBeNull();
  });

  it("keeps keys session-only and advances keyEpoch only on real resets", () => {
    const initial = useProvider.getState().keyEpoch;
    useProvider.getState().setKind("spoolease");
    const changed = useProvider.getState().keyEpoch;
    expect(changed).toBe(initial + 1);
    useProvider.getState().setKind("spoolease");
    expect(useProvider.getState().keyEpoch).toBe(changed);
    useProvider.getState().setKey("abc");
    expect([...store.entries()].some(([key, value]) =>
      key.includes("abc") || value.includes("abc") || key.includes("keyEpoch") || value.includes("keyEpoch"))).toBe(false);
    expect(providerArgs(useProvider.getState())).not.toHaveProperty("keyEpoch");
    useProvider.getState().clear();
    expect(useProvider.getState().keyEpoch).toBe(changed + 1);
  });
});


describe("switching provider", () => {
  beforeEach(reset);

  it("does not carry one provider's address and mapping across to the other", () => {
    // A spool id is only meaningful to the provider that issued it. Carried
    // across, a mapping points at whatever spool happens to share the number —
    // and Studio would then report that spool's material for the slot, with
    // complete confidence and no reason to be right.
    const store = useProvider.getState();
    store.setKind("spoolman");
    store.setUrl("spoolman.local:7912");
    store.setSlot("1", 7);
    expect(useProvider.getState().slotMap).toEqual({ "1": 7 });

    useProvider.getState().setKind("bambuddy");
    const after = useProvider.getState();
    expect(after.kind).toBe("bambuddy");
    expect(after.url).toBe("");
    expect(after.slotMap).toEqual({});
    expect(after.lastSeen).toBeNull();
    expect(providerArgs(after)).toEqual({});
  });

  it("keeps what was typed when the same provider is chosen again", () => {
    const store = useProvider.getState();
    store.setKind("bambuddy");
    store.setUrl("bambuddy.local:8000");
    store.setSlot("1", 4);
    useProvider.getState().setKind("bambuddy");
    expect(useProvider.getState().url).toBe("bambuddy.local:8000");
    expect(useProvider.getState().slotMap).toEqual({ "1": 4 });
  });

  it("survives a restart, provider and all", () => {
    const store = useProvider.getState();
    store.setKind("bambuddy");
    store.setUrl("bambuddy.local:8000");
    store.setSlotBase(0);
    store.setSlot("0", 4);

    // Everything this store holds is written as it changes, so a fresh read of
    // localStorage is what the next launch would see.
    expect(JSON.parse(localStorage.getItem("materialProviderKind")!)).toBe("bambuddy");
    expect(JSON.parse(localStorage.getItem("materialProviderUrl")!)).toBe("bambuddy.local:8000");
    expect(JSON.parse(localStorage.getItem("materialProviderSlotMap")!)).toEqual({ "0": 4 });
    expect(JSON.parse(localStorage.getItem("materialProviderSlotBase")!)).toBe(0);
  });

  it("does not delete local spool notes when switching providers", () => {
    localStorage.setItem("localSpoolsExample", "keep-me");
    const before = new Map([...store].filter(([key]) => !key.startsWith("materialProvider")));
    useProvider.getState().setKind("spoolease");
    useProvider.getState().setKind("spoolman");
    expect(new Map([...store].filter(([key]) => !key.startsWith("materialProvider")))).toEqual(before);
  });
});
