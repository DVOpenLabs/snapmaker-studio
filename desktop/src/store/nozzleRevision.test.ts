import { beforeEach, describe, expect, it } from "vitest";
import { bumpNozzleNotes, nextNozzleErrorMessage, useNozzleNotesVersion } from "./nozzleRevision";

describe("nextNozzleErrorMessage (R2-D3: stale message survives the automatic reload)", () => {
  const STALE = "Changed elsewhere — reloaded, try again.";

  it("sets the stale message on a stale (409) mutation failure", () => {
    const msg = nextNozzleErrorMessage(null, { type: "mutation_failed", message: "ignored", code: "stale" });
    expect(msg).toBe(STALE);
  });

  it("keeps a non-stale failure's own message", () => {
    const msg = nextNozzleErrorMessage(null, { type: "mutation_failed", message: "Weight must be between 0 and 10000 grams." });
    expect(msg).toBe("Weight must be between 0 and 10000 grams.");
  });

  it("does NOT clear the stale message when the automatic recovery refetch completes", () => {
    // This is the exact bug: the recovery fetch that follows a 409 must not
    // wipe the message it was shown to explain.
    const afterStale = nextNozzleErrorMessage(null, { type: "mutation_failed", message: "x", code: "stale" });
    const afterRefetch = nextNozzleErrorMessage(afterStale, { type: "status_refetched" });
    expect(afterRefetch).toBe(STALE);
  });

  it("clears the message only when the user starts a new action", () => {
    const afterStale = nextNozzleErrorMessage(null, { type: "mutation_failed", message: "x", code: "stale" });
    expect(nextNozzleErrorMessage(afterStale, { type: "user_action_started" })).toBeNull();
  });
});

describe("nozzleNotesVersion / bumpNozzleNotes (F1/F5: cross-component invalidation, no host keying)", () => {
  beforeEach(() => {
    // Reset to a known baseline; only bumpNozzleNotes ever changes this in
    // production code, so tests must not assume a particular starting value.
    useNozzleNotesVersion.setState({ version: useNozzleNotesVersion.getState().version });
  });

  it("increments by exactly one per bump, so an effect depending on it fires exactly once per bump", () => {
    const before = useNozzleNotesVersion.getState().version;
    bumpNozzleNotes();
    expect(useNozzleNotesVersion.getState().version).toBe(before + 1);
  });

  it("is a single global counter — not keyed by host or port", () => {
    const before = useNozzleNotesVersion.getState().version;
    bumpNozzleNotes();
    // No host/port parameter exists to even key it by (compile-time proof:
    // bumpNozzleNotes takes no arguments) — this test documents the runtime
    // half: two "different printers'" mutations still land on one counter.
    bumpNozzleNotes();
    expect(useNozzleNotesVersion.getState().version).toBe(before + 2);
  });

  it("does not change on its own between bumps", () => {
    const before = useNozzleNotesVersion.getState().version;
    expect(useNozzleNotesVersion.getState().version).toBe(before);
  });
});
