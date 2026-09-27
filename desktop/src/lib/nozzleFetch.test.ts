import { describe, expect, it, vi } from "vitest";
import { createGenerationGuard, nozzleDataStale, runNozzleFetch } from "./nozzleFetch";
import type { NozzleStatus } from "@/api";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function status(overrides: Partial<NozzleStatus> = {}): NozzleStatus {
  return {
    host: "u1.local", port: 7125, reachable: true, live: null, live_error: null,
    toolhead_count: 0, toolhead_count_source: "printer", revision: 1,
    observed_at: "2026-09-01T00:00:00Z", count_mismatch: false, storage_error: null,
    toolheads: [], ...overrides,
  };
}

describe("runNozzleFetch (F3: phase-1 probe:false then phase-2 probe:true)", () => {
  it("applies phase-2's live result after phase-1's quick result (N5 regression)", async () => {
    const quick = deferred<NozzleStatus>();
    const live = deferred<NozzleStatus>();
    const api = { nozzleStatus: vi.fn((_h: string, _p: number, probe: boolean) => (probe ? live.promise : quick.promise)) };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    const run = runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on });

    quick.resolve(status({ revision: 1 }));
    await Promise.resolve(); await Promise.resolve();
    expect(on.quick).toHaveBeenCalledTimes(1);
    expect(on.live).not.toHaveBeenCalled();

    live.resolve(status({ revision: 2 }));
    await run;
    expect(on.live).toHaveBeenCalledTimes(1);
    expect(on.live.mock.calls[0][0].revision).toBe(2);
  });

  it("never launches phase-2 once isCurrent() goes false after phase-1 resolves", async () => {
    const quick = deferred<NozzleStatus>();
    let current = true;
    const api = { nozzleStatus: vi.fn().mockResolvedValue(status()) };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    const run = runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => current, api, on });
    current = false; // host change / unmount happens before phase-1 even resolves
    quick.resolve(status());
    await run;

    expect(on.quick).not.toHaveBeenCalled();
    expect(on.live).not.toHaveBeenCalled();
    // Only one call was ever made (phase-1); phase-2 must never have been launched.
    expect(api.nozzleStatus).toHaveBeenCalledTimes(1);
  });

  it("drops a newer fetch's phase-2 from being confused with an older one (A's phase-2 after B's phase-1)", async () => {
    // Simulates two overlapping runs sharing one isCurrent() that flips
    // ownership between them, the way a component's own token would.
    let owner: "A" | "B" = "A";
    const aQuick = deferred<NozzleStatus>();
    const aLive = deferred<NozzleStatus>();
    const bQuick = deferred<NozzleStatus>();
    const bLive = deferred<NozzleStatus>();
    const apiA = { nozzleStatus: vi.fn((_h: string, _p: number, probe: boolean) => (probe ? aLive.promise : aQuick.promise)) };
    const apiB = { nozzleStatus: vi.fn((_h: string, _p: number, probe: boolean) => (probe ? bLive.promise : bQuick.promise)) };
    const onA = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };
    const onB = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    const runA = runNozzleFetch({ host: "a", port: 7125, isCurrent: () => owner === "A", api: apiA, on: onA });
    const runB = runNozzleFetch({ host: "b", port: 7125, isCurrent: () => owner === "B", api: apiB, on: onB });

    aQuick.resolve(status({ host: "a" }));
    await Promise.resolve(); await Promise.resolve();
    owner = "B"; // B takes over before A's phase-2 resolves
    bQuick.resolve(status({ host: "b" }));
    await Promise.resolve(); await Promise.resolve();

    aLive.resolve(status({ host: "a", revision: 99 })); // A's stale phase-2 arrives last
    bLive.resolve(status({ host: "b", revision: 2 }));
    await Promise.all([runA, runB]);

    expect(onA.live).not.toHaveBeenCalled(); // A no longer current when its phase-2 landed
    expect(onB.live).toHaveBeenCalledTimes(1);
    expect(onB.live.mock.calls[0][0].host).toBe("b");
  });

  it("shows the quick status with no error when phase-1 fails but phase-2 succeeds", async () => {
    const api = {
      nozzleStatus: vi.fn((_h: string, _p: number, probe: boolean) =>
        probe ? Promise.resolve(status({ revision: 2 })) : Promise.reject(new Error("network"))),
    };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on });

    expect(on.quick).not.toHaveBeenCalled();
    expect(on.live).toHaveBeenCalledTimes(1);
    expect(on.liveFailed).not.toHaveBeenCalled();
    expect(on.allFailed).not.toHaveBeenCalled();
  });

  it("reports allFailed with settled flags when both phases fail", async () => {
    const api = { nozzleStatus: vi.fn().mockRejectedValue(new Error("network")) };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on });

    expect(on.allFailed).toHaveBeenCalledTimes(1);
    expect(on.liveFailed).not.toHaveBeenCalled();
  });

  it("calls liveFailed (not allFailed) when phase-1 succeeds but phase-2 fails", async () => {
    const api = {
      nozzleStatus: vi.fn((_h: string, _p: number, probe: boolean) =>
        probe ? Promise.reject(new Error("network")) : Promise.resolve(status())),
    };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on });

    expect(on.quick).toHaveBeenCalledTimes(1);
    expect(on.liveFailed).toHaveBeenCalledTimes(1);
    expect(on.allFailed).not.toHaveBeenCalled();
  });

  it("applies a degraded (storage_error) response like any other — never dropped", async () => {
    const degraded = status({ revision: 0, storage_error: "storage_unavailable" });
    const api = { nozzleStatus: vi.fn().mockResolvedValue(degraded) };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on });

    expect(on.quick).toHaveBeenCalledWith(degraded);
    expect(on.live).toHaveBeenCalledWith(degraded);
  });

  describe("liveDelayMs (R4-D6: live probe not per keystroke)", () => {
    it("does not delay phase-1 at all, only phase-2", async () => {
      const api = { nozzleStatus: vi.fn().mockResolvedValue(status()) };
      const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };
      const wait = vi.fn().mockResolvedValue(undefined);

      await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on, liveDelayMs: 800, wait });

      expect(on.quick).toHaveBeenCalledTimes(1);
      expect(wait).toHaveBeenCalledWith(800);
      expect(on.live).toHaveBeenCalledTimes(1);
    });

    it("never launches phase-2 if isCurrent() goes false during the debounce wait", async () => {
      const api = { nozzleStatus: vi.fn().mockResolvedValue(status()) };
      const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };
      let current = true;
      const wait = vi.fn().mockImplementation(async () => { current = false; }); // host changes mid-wait

      await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => current, api, on, liveDelayMs: 800, wait });

      expect(on.quick).toHaveBeenCalledTimes(1);
      expect(on.live).not.toHaveBeenCalled();
      expect(api.nozzleStatus).toHaveBeenCalledTimes(1); // only phase-1 — phase-2 never even requested
    });

    it("skips the wait entirely when liveDelayMs is 0 (Refresh / read-only consumers)", async () => {
      const api = { nozzleStatus: vi.fn().mockResolvedValue(status()) };
      const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };
      const wait = vi.fn();

      await runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => true, api, on, liveDelayMs: 0, wait });

      expect(wait).not.toHaveBeenCalled();
      expect(on.live).toHaveBeenCalledTimes(1);
    });

    it("three host changes within the debounce window produce exactly one live probe, for the final host", async () => {
      vi.useFakeTimers();
      try {
        const generation = { current: 0 };
        const calls: { host: string; probe: boolean }[] = [];
        const api = {
          nozzleStatus: vi.fn((h: string, _p: number, probe: boolean) => {
            calls.push({ host: h, probe });
            return Promise.resolve(status({ host: h }));
          }),
        };
        const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

        function start(host: string) {
          const gen = ++generation.current;
          void runNozzleFetch({
            host, port: 7125, isCurrent: () => gen === generation.current,
            api, on, liveDelayMs: 800,
          });
        }

        start("h1");
        await vi.advanceTimersByTimeAsync(300);
        start("h2");
        await vi.advanceTimersByTimeAsync(300);
        start("h3"); // final host, within 800ms of both prior starts
        await vi.advanceTimersByTimeAsync(900); // let the debounce elapse

        const liveCalls = calls.filter((c) => c.probe);
        expect(liveCalls).toHaveLength(1);
        expect(liveCalls[0].host).toBe("h3");
      } finally {
        vi.useRealTimers();
      }
    });
  });
});

describe("createGenerationGuard (R4-D2: a reusable, testable freshness primitive)", () => {
  it("isCurrent() is true for the generation just issued, until something invalidates it", () => {
    const guard = createGenerationGuard();
    const gen = guard.next();
    expect(guard.isCurrent(gen)).toBe(true);
  });

  it("next() invalidates every previously-issued generation", () => {
    const guard = createGenerationGuard();
    const gen1 = guard.next();
    const gen2 = guard.next();
    expect(guard.isCurrent(gen1)).toBe(false);
    expect(guard.isCurrent(gen2)).toBe(true);
  });

  it("invalidate() (unmount / !connected) makes even the latest generation stale", () => {
    const guard = createGenerationGuard();
    const gen = guard.next();
    guard.invalidate();
    expect(guard.isCurrent(gen)).toBe(false);
  });

  it("unmount between phase-1 and phase-2: no callback, no phase-2 launch (the exact R4-D2 scenario)", async () => {
    const guard = createGenerationGuard();
    const quick = deferred<NozzleStatus>();
    const api = { nozzleStatus: vi.fn().mockReturnValue(quick.promise) };
    const on = { quick: vi.fn(), live: vi.fn(), liveFailed: vi.fn(), allFailed: vi.fn() };

    const gen = guard.next();
    const run = runNozzleFetch({ host: "u1.local", port: 7125, isCurrent: () => guard.isCurrent(gen), api, on });

    guard.invalidate(); // effect cleanup fires: component unmounted between phases
    quick.resolve(status());
    await run;

    expect(on.quick).not.toHaveBeenCalled();
    expect(on.live).not.toHaveBeenCalled();
    expect(api.nozzleStatus).toHaveBeenCalledTimes(1); // phase-2 never even requested
  });
});

describe("nozzleDataStale (CodeRabbit PR #41 #5: never show a stale host's sizes)", () => {
  it("is true when the host changed, so the old host's data must be cleared", () => {
    expect(nozzleDataStale("printer-a.local", "printer-b.local")).toBe(true);
  });

  it("is false for the same host, so a manual Refresh doesn't flash empty", () => {
    expect(nozzleDataStale("printer-a.local", "printer-a.local")).toBe(false);
  });

  it("is true from no host connected to a host (first connect)", () => {
    expect(nozzleDataStale(null, "printer-a.local")).toBe(true);
  });
});
