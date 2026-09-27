import { describe, expect, it, vi } from "vitest";
import { createNozzleSettingsController } from "./nozzleSettingsController";
import { ApiError } from "@/api";
import type { NozzleStatus } from "@/api";
import type { NozzleFetchApi } from "./nozzleFetch";
import type { NozzleMutationResult } from "./nozzleMutations";
import { showsNothingReportedBanner } from "./nozzleRows";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function status(overrides: Partial<NozzleStatus> = {}): NozzleStatus {
  return {
    host: "u1.local", port: 7125, reachable: true, live: null, live_error: null,
    toolhead_count: 1, toolhead_count_source: "printer", revision: 1,
    observed_at: "2026-09-01T00:00:00Z", count_mismatch: false, storage_error: null,
    toolheads: [{ toolhead: 0, diameter: 0.4, source: "printer", confirmed_at: null, confirmed: null, conflict: false, out_of_range: false }],
    ...overrides,
  };
}

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) await Promise.resolve();
}

describe("createNozzleSettingsController (F4)", () => {
  it("N12: save triggers exactly one live (probe:true) fetch afterward, and it is applied", async () => {
    // Backend R4-B1: confirm/clear return a probe:false snapshot instantly
    // (reachable:false, live_error:"not_checked") — not a live reading. If the
    // controller stopped there, a save on a perfectly reachable printer would
    // show "Unknown"/no-conflict/"nothing reported" until a manual Refresh.
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const clearNozzles = vi.fn();
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles, wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    const callsAfterStart = nozzleStatus.mock.calls.length; // 2: phase-1 + phase-2

    const liveAfterSave = status({ revision: 2, reachable: true, live_error: null });
    nozzleStatus.mockResolvedValueOnce(liveAfterSave);
    await controller.saveAll();
    await settle();

    expect(confirmNozzles).toHaveBeenCalledTimes(1);
    expect(nozzleStatus.mock.calls.length).toBe(callsAfterStart + 1); // exactly one live fetch
    expect(nozzleStatus.mock.calls[callsAfterStart]).toEqual(["u1.local", 7125, true]); // probe:true, no debounce
    expect(controller.getState().status).toEqual(liveAfterSave); // live reading applied
    expect(controller.getState().checkingLive).toBe(false);
  });

  it("N12: checkingLive is true immediately after a successful mutation, until the live fetch settles", async () => {
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();

    const liveAfterSave = deferred<NozzleStatus>();
    nozzleStatus.mockReturnValueOnce(liveAfterSave.promise); // held pending — precise control over timing
    await controller.saveAll();

    expect(controller.getState().status).toEqual(mutationSnapshot); // applied immediately, not held back
    expect(controller.getState().checkingLive).toBe(true);

    liveAfterSave.resolve(status({ revision: 2, reachable: true, live_error: null }));
    await settle();
    expect(controller.getState().status?.reachable).toBe(true);
    expect(controller.getState().checkingLive).toBe(false);
  });

  it("(a) offline-printer path: the post-mutation live fetch answers 200 reachable:false/unreachable — a real, honest 'nothing reported' (lock this in)", async () => {
    // /nozzles/status?probe=true never REJECTS for an offline printer — it
    // answers 200 with reachable:false, live_error:"unreachable". That is a
    // real answer about the printer, applied exactly like any other live
    // result, and the banner is allowed to show immediately.
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    nozzleStatus.mockResolvedValueOnce(status({ revision: 2, reachable: false, live_error: "unreachable" }));
    await controller.saveAll();
    await settle();

    expect(controller.getState().checkingLive).toBe(false);
    expect(controller.getState().liveCheckFailed).toBe(false);
    expect(controller.getState().status?.live_error).toBe("unreachable");
    expect(showsNothingReportedBanner(controller.getState().status)).toBe(true);
  });

  it("(b) request-failure path: the live-only REQUEST itself fails — status (and 'not_checked') is untouched, liveCheckFailed is set, no banner, no 'unreachable' claim", async () => {
    // This branch is reached only when the request never got an answer at
    // all (local service down / network error / 500) — the printer was
    // never actually asked, so nothing here may claim "unreachable" or
    // "nothing reported by this printer" about it.
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    nozzleStatus.mockRejectedValueOnce(new Error("Studio's local service is unavailable"));
    await controller.saveAll();
    await settle();

    expect(controller.getState().status).toEqual(mutationSnapshot); // completely untouched
    expect(controller.getState().status?.live_error).toBe("not_checked"); // never claims "unreachable"
    expect(controller.getState().checkingLive).toBe(false);
    expect(controller.getState().liveCheckFailed).toBe(true);
    expect(showsNothingReportedBanner(controller.getState().status)).toBe(false); // no "nothing reported" claim
  });

  it("liveCheckFailed clears on the next fetch start (host change)", async () => {
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    nozzleStatus.mockRejectedValueOnce(new Error("network"));
    await controller.saveAll();
    await settle();
    expect(controller.getState().liveCheckFailed).toBe(true);

    controller.start("other.local", 7125);
    expect(controller.getState().liveCheckFailed).toBe(false);
  });

  it("liveCheckFailed clears on the next successful live check", async () => {
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    nozzleStatus.mockRejectedValueOnce(new Error("network"));
    await controller.saveAll();
    await settle();
    expect(controller.getState().liveCheckFailed).toBe(true);

    nozzleStatus.mockResolvedValueOnce(status({ revision: 3, reachable: true, live_error: null }));
    await controller.saveAll();
    await settle();
    expect(controller.getState().liveCheckFailed).toBe(false);
  });

  it("v1.2.0 release polish: no banner flash while checkingLive is still true (existing guarantee preserved)", async () => {
    const liveAfterSave = deferred<NozzleStatus>();
    const nozzleStatus = vi.fn()
      .mockResolvedValueOnce(status()) // start(): phase-1
      .mockResolvedValueOnce(status()) // start(): phase-2
      .mockReturnValueOnce(liveAfterSave.promise); // the post-mutation live fetch, held pending
    const mutationSnapshot = status({ revision: 2, reachable: false, live_error: "not_checked" });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: mutationSnapshot });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    await controller.saveAll(); // fires the post-mutation live fetch, held pending

    expect(controller.getState().checkingLive).toBe(true);
    expect(showsNothingReportedBanner(controller.getState().status)).toBe(false);
    liveAfterSave.resolve(status({ revision: 2, reachable: true, live_error: null })); // clean up
    await settle();
  });

  it("N12: a host change during the post-mutation live fetch applies nothing from it", async () => {
    const liveAfterSaveA = deferred<NozzleStatus>();
    let call = 0;
    const nozzleStatus = vi.fn((_h: string, _p: number, _probe: boolean) => {
      call += 1;
      if (call <= 2) return Promise.resolve(status({ host: "A" })); // start("A"): phase-1, phase-2
      if (call === 3) return liveAfterSaveA.promise; // the post-save live-only fetch (N12)
      return Promise.resolve(status({ host: "B" })); // start("B")'s own phase-1/phase-2
    });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>()
      .mockResolvedValue({ ok: true, status: status({ host: "A", revision: 2, reachable: false, live_error: "not_checked" }) });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("A", 7125);
    await settle();
    await controller.saveAll(); // applies A's snapshot, fires call 3 (pending)
    expect(controller.getState().checkingLive).toBe(true);

    controller.start("B", 7125); // host change while the post-save live fetch is still in flight
    await settle();

    liveAfterSaveA.resolve(status({ host: "A", revision: 99 })); // resolves late — must apply nothing
    await settle();

    expect(controller.getState().status?.host).toBe("B");
    expect(controller.getState().status?.revision).not.toBe(99);
  });

  it("applies the mutation response immediately, ignoring a stale phase-2 from BEFORE the mutation — and still applies the mutation's own post-save live fetch (N12)", async () => {
    const quick1 = status({ revision: 1 });
    const live1 = deferred<NozzleStatus>(); // the ORIGINAL phase-2, invalidated by the mutation's token bump
    const live2 = deferred<NozzleStatus>(); // the post-mutation live-only fetch (N12) — current, must apply
    let call = 0;
    const nozzleStatus = vi.fn((_h: string, _p: number, probe: boolean) => {
      call += 1;
      if (!probe) return Promise.resolve(quick1);
      return call === 2 ? live1.promise : live2.promise;
    });
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({ ok: true, status: status({ revision: 5, reachable: false, live_error: "not_checked" }) });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    expect(controller.getState().status?.revision).toBe(1); // phase-1 applied

    await controller.saveAll(); // succeeds, bumps the token, fires the post-save live fetch (call 3)
    expect(controller.getState().status?.revision).toBe(5);

    live1.resolve(status({ revision: 1 })); // the now-obsolete PRE-mutation phase-2 response
    await settle();
    expect(controller.getState().status?.revision).toBe(5); // still the mutation's result — unaffected

    live2.resolve(status({ revision: 7, reachable: true, live_error: null })); // the post-mutation live fetch
    await settle();
    expect(controller.getState().status?.revision).toBe(7); // now applied
    void call;
  });

  it("on a 409 stale write: exactly one recovery fetch, and the message survives it", async () => {
    const nozzleStatus = vi.fn()
      .mockResolvedValueOnce(status()) // start(): phase-1
      .mockResolvedValueOnce(status()) // start(): phase-2
      .mockResolvedValueOnce(status({ revision: 9 })); // the 409 recovery fetch
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({
      ok: false, error: new ApiError("Nozzle notes changed elsewhere. Reload and try again.", "stale", { current_revision: 9 }),
    });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    const callsBeforeSave = nozzleStatus.mock.calls.length;

    await controller.saveAll();
    expect(nozzleStatus.mock.calls.length).toBe(callsBeforeSave + 1); // exactly one recovery fetch
    expect(controller.getState().errorMessage).toBe("Changed elsewhere — reloaded, try again.");
    expect(controller.getState().status?.revision).toBe(9);
  });

  it("distinguishes a failed recovery: the stale message stays, but loadError is also set", async () => {
    const nozzleStatus = vi.fn()
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status())
      .mockRejectedValueOnce(new Error("network down"));
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({
      ok: false, error: new ApiError("Nozzle notes changed elsewhere. Reload and try again.", "stale"),
    });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    await controller.saveAll();

    expect(controller.getState().errorMessage).toBe("Changed elsewhere — reloaded, try again.");
    expect(controller.getState().loadError).toBe(true);
  });

  it("serialises rapid row actions: a second mutation while one is in flight is a no-op", async () => {
    const nozzleStatus = vi.fn().mockResolvedValue(status());
    const first = deferred<NozzleMutationResult>();
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockReturnValue(first.promise);
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();

    const p1 = controller.saveAll();
    const p2 = controller.saveAll(); // must be ignored — busy
    expect(controller.getState().busy).toBe(true);
    first.resolve({ ok: true, status: status({ revision: 2 }) });
    await Promise.all([p1, p2]);

    expect(confirmNozzles).toHaveBeenCalledTimes(1);
    expect(controller.getState().busy).toBe(false);
  });

  it("host A -> B -> A between phases applies nothing obsolete", async () => {
    // Two visits to "A" (same host string) need distinguishing by call order,
    // not just by host — a per-host, per-phase queue of deferreds does that.
    const aQuick1 = deferred<NozzleStatus>();
    const aLive1 = deferred<NozzleStatus>();
    const aQuick2 = deferred<NozzleStatus>();
    const aLive2 = deferred<NozzleStatus>();
    const bQuick = deferred<NozzleStatus>();
    const bLive = deferred<NozzleStatus>();
    const queues = {
      A: { quick: [aQuick1, aQuick2], live: [aLive1, aLive2] },
      B: { quick: [bQuick], live: [bLive] },
    };
    const counters = { A: { quick: 0, live: 0 }, B: { quick: 0, live: 0 } };
    const nozzleStatus = vi.fn((h: "A" | "B", _p: number, probe: boolean) => {
      const kind = probe ? "live" : "quick";
      const d = queues[h][kind][counters[h][kind]++];
      return d.promise;
    });
    const controller = createNozzleSettingsController({
      nozzleStatus: nozzleStatus as unknown as NozzleFetchApi["nozzleStatus"],
      confirmNozzles: vi.fn(), clearNozzles: vi.fn(), wait: async () => {},
    });

    // Visit 1 (A) legitimately reaches phase-2 (its phase-1 resolves while
    // still current) before the host changes out from under it — the
    // interesting race is its already-launched phase-2 resolving late, well
    // after two more host switches have moved on.
    controller.start("A", 7125);
    aQuick1.resolve(status({ host: "A", revision: 1 }));
    await settle();

    controller.start("B", 7125); // invalidates visit 1's in-flight phase-2
    bQuick.resolve(status({ host: "B", revision: 10 }));
    await settle();

    controller.start("A", 7125); // visit 2; invalidates B's in-flight phase-2
    aQuick2.resolve(status({ host: "A", revision: 20 }));
    await settle();

    // Now resolve every still-pending phase-2, oldest first: B's (stale),
    // then visit 2's (current — must win), then visit 1's (very stale).
    bLive.resolve(status({ host: "B", revision: 11 }));
    aLive2.resolve(status({ host: "A", revision: 21 }));
    await settle();
    aLive1.resolve(status({ host: "A", revision: 2 }));
    await settle();

    expect(controller.getState().status?.host).toBe("A");
    expect(controller.getState().status?.revision).toBe(21);
  });

  it("R4-D1: host change during a pending save applies nothing from A's outcome to B, and B's own fetch is not cancelled", async () => {
    const nozzleStatus = vi.fn().mockResolvedValue(status({ host: "B" }));
    const aSave = deferred<NozzleMutationResult>();
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>()
      .mockReturnValueOnce(aSave.promise);
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("A", 7125);
    await settle();
    const savePromise = controller.saveAll(); // A's save is now in flight (busy=true, epoch=1)

    controller.start("B", 7125); // host change: new epoch, fresh non-busy state for B
    await settle();
    expect(controller.getState().busy).toBe(false);
    expect(controller.getState().status?.host).toBe("B"); // B's own fetch was NOT cancelled

    // A new mutation on B is allowed even while A's old save is still pending.
    // (N12: this also fires B's own post-mutation live fetch, which the
    // shared mock happily answers — that's correct, unrelated behaviour;
    // this test only cares that none of it is EVER A's revision 99.)
    confirmNozzles.mockResolvedValueOnce({ ok: true, status: status({ host: "B", revision: 42 }) });
    await controller.saveAll();
    await settle();
    expect(controller.getState().status?.host).toBe("B");
    expect(controller.getState().status?.revision).not.toBe(99);

    // Now A's stale save resolves successfully — must change nothing on B's
    // displayed state (no status overwrite, no busy flip, no message), but
    // the mutation helper's global bump already happened (host-agnostic).
    aSave.resolve({ ok: true, status: status({ host: "A", revision: 99 }) });
    await settle();
    expect(controller.getState().status?.host).toBe("B");
    expect(controller.getState().status?.revision).not.toBe(99);
    expect(controller.getState().busy).toBe(false);
    expect(controller.getState().errorMessage).toBeNull();
    void savePromise;
  });

  it("R4-D1: a stale (409) outcome for A after a host change to B also changes nothing on B", async () => {
    const nozzleStatus = vi.fn().mockResolvedValue(status({ host: "B" }));
    const aSave = deferred<NozzleMutationResult>();
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>()
      .mockReturnValueOnce(aSave.promise);
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("A", 7125);
    await settle();
    const p = controller.saveAll();
    controller.start("B", 7125);
    await settle();
    const callsOnB = nozzleStatus.mock.calls.length;

    aSave.resolve({ ok: false, error: new ApiError("Nozzle notes changed elsewhere. Reload and try again.", "stale") });
    await settle();

    // No recovery fetch launched for the abandoned A epoch, and B's state
    // (status/message/busy) is completely untouched by A's 409.
    expect(nozzleStatus.mock.calls.length).toBe(callsOnB);
    expect(controller.getState().status?.host).toBe("B");
    expect(controller.getState().errorMessage).toBeNull();
    void p;
  });

  it("R4-D3: an uncertain write outcome runs exactly one recovery fetch and the message persists through it", async () => {
    const nozzleStatus = vi.fn()
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ revision: 7 })); // the recovery fetch
    const confirmNozzles = vi.fn<(host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>>().mockResolvedValue({
      ok: false, error: new ApiError("Studio couldn't reach its local service. Try again."), // no `code`: uncertain
    });
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles, clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    await settle();
    const callsBeforeSave = nozzleStatus.mock.calls.length;

    await controller.saveAll();

    expect(nozzleStatus.mock.calls.length).toBe(callsBeforeSave + 1); // exactly one recovery fetch
    expect(controller.getState().errorMessage).toBe("Studio couldn't reach its local service. Try again.");
    expect(controller.getState().status?.revision).toBe(7); // reconciled from the recovery fetch
  });

  it("unmount stops any in-flight fetch from ever being applied", async () => {
    const quick = deferred<NozzleStatus>();
    const nozzleStatus = vi.fn().mockReturnValue(quick.promise);
    const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles: vi.fn(), clearNozzles: vi.fn(), wait: async () => {} });

    controller.start("u1.local", 7125);
    controller.unmount();
    quick.resolve(status());
    await settle();

    expect(controller.getState().status).toBeNull();
  });

  it("R4-D6: start() debounces the live probe, but refresh() does not", async () => {
    vi.useFakeTimers();
    try {
      const nozzleStatus = vi.fn().mockResolvedValue(status());
      const controller = createNozzleSettingsController({ nozzleStatus, confirmNozzles: vi.fn(), clearNozzles: vi.fn() });

      controller.start("u1.local", 7125);
      await vi.advanceTimersByTimeAsync(0);
      expect(nozzleStatus).toHaveBeenCalledTimes(1); // phase-1 only — phase-2 is waiting
      expect(controller.getState().checkingLive).toBe(true);

      await vi.advanceTimersByTimeAsync(799);
      expect(nozzleStatus).toHaveBeenCalledTimes(1); // still waiting, one ms short
      await vi.advanceTimersByTimeAsync(1);
      expect(nozzleStatus).toHaveBeenCalledTimes(2); // phase-2 now fires

      controller.refresh();
      await vi.advanceTimersByTimeAsync(0);
      expect(nozzleStatus).toHaveBeenCalledTimes(4); // refresh: phase-1 AND phase-2 immediately, no wait
    } finally {
      vi.useRealTimers();
    }
  });
});
