// Per-component nozzle-settings state machine (v1.2 round-3 F4, round-4/5
// hardening: R4-D1/R4-D3/N12/N13).
//
// Freshness has two independent layers. A monotonic request `token` owns
// in-flight-fetch freshness for this component instance: bumped on fetch
// start, host change, unmount, a manual refresh, a successful mutation
// (whose response is then applied directly — it is the server's post-commit
// state, no extra read needed — followed immediately by ONE live-only
// fetch, see below), and a 409/uncertain-write recovery fetch. Any in-flight
// work whose token no longer matches is simply never applied. Separately, an
// `epoch` (bumped ONLY by `start()`/`unmount()`, i.e. an actual host change —
// R4-D1) binds every in-flight MUTATION to the host/port it started under:
// if the host changes before a mutation's response arrives, that response
// changes nothing on the new host's state (no status, no token bump, no
// message, no busy flip) — it simply arrived for a host nobody is looking at
// anymore. The mutation helper's global `bumpNozzleNotes()` is unaffected by
// either layer; it is host-agnostic by design.
//
// N12: confirm/clear responses are now an instant snapshot (backend R4-B1;
// reachable:false, live_error:"not_checked") rather than a live reading. A
// successful mutation response is still applied immediately (so the user
// never waits on it), but is then followed by exactly one live-only
// (probe:true, no debounce) fetch bound to the same epoch/token, so a save on
// a reachable printer doesn't sit showing "Unknown"/no conflict/"nothing
// reported" until a manual Refresh. `checkingLive` is true for that window.
// This live-only fetch's outcomes are NOT symmetric (Opus follow-up): an
// offline printer is a 200 response (reachable:false, live_error:
// "unreachable"), which the success branch applies as real data — that IS
// the honest "nothing reported" case. Only the REQUEST itself failing (local
// service down, network error, 500 — the printer was never actually asked)
// hits the rejection branch; that leaves `status` untouched (still
// "not_checked") and sets `liveCheckFailed` instead, so the UI can show a
// neutral "couldn't check" note rather than claim anything about the
// printer.
//
// Deliberately not a React hook: it is plain TS holding a tiny pub/sub
// (compatible with zustand's own store shape, so a component can use it via
// zustand's `useStore(controller.store)`), so every race above is testable in
// node with deferred promises and no DOM.
import { createStore, type StoreApi } from "zustand/vanilla";
import { nozzleStatus as apiNozzleStatus, type NozzleStatus } from "@/api";
import { runNozzleFetch, type NozzleFetchApi } from "@/lib/nozzleFetch";
import { confirmNozzles as apiConfirmNozzles, clearNozzles as apiClearNozzles } from "@/lib/nozzleMutations";
import type { NozzleMutationResult } from "@/lib/nozzleMutations";
import { diametersForRemove, diametersForSaveAll, diametersForUpdate } from "@/lib/nozzleRows";
import { nextNozzleErrorMessage } from "@/store/nozzleRevision";

export interface NozzleSettingsState {
  status: NozzleStatus | null;
  checkingLive: boolean;
  loadError: boolean;
  errorMessage: string | null;
  busy: boolean;
  draft: Record<number, string>;
  /** Opus follow-up (honesty fix): true only when the post-mutation live-only
   *  REQUEST itself failed (local service down / network / 500) — never set
   *  for a printer that genuinely answered "unreachable"/offline, which is a
   *  200 response the success branch already applies as real data. `status`
   *  (and its `live_error: "not_checked"`) is left untouched in this case —
   *  the printer was never actually asked, so nothing here may claim
   *  "nothing reported by this printer". Cleared on the next fetch start
   *  (host change or Refresh) and on any subsequent success. */
  liveCheckFailed: boolean;
}

function initialState(): NozzleSettingsState {
  return {
    status: null, checkingLive: false, loadError: false, errorMessage: null, busy: false, draft: {},
    liveCheckFailed: false,
  };
}

/** R4-D6: how long the host must be unchanged before the live probe fires. */
const LIVE_DEBOUNCE_MS = 800;

export interface NozzleSettingsDeps {
  nozzleStatus: NozzleFetchApi["nozzleStatus"];
  confirmNozzles: (host: string, port: number, diameters: (number | null)[], expectedRevision: number) => Promise<NozzleMutationResult>;
  clearNozzles: (host: string, port: number, expectedRevision: number) => Promise<NozzleMutationResult>;
  /** Injectable for tests (R4-D6's debounce); defaults to a real `setTimeout`-based wait via nozzleFetch.ts. */
  wait?: (ms: number) => Promise<void>;
}

const defaultDeps: NozzleSettingsDeps = {
  nozzleStatus: apiNozzleStatus,
  confirmNozzles: apiConfirmNozzles,
  clearNozzles: apiClearNozzles,
};

export interface NozzleSettingsController {
  store: StoreApi<NozzleSettingsState>;
  getState: () => NozzleSettingsState;
  subscribe: (listener: (s: NozzleSettingsState) => void) => () => void;
  /** Begins (or re-begins, for a different host) the two-phase fetch. Resets
   *  drafts and any showing message — a host change is a fresh start. */
  start: (host: string, port: number) => void;
  /** Manual "Refresh" — same as `start` but keeps the same host/port and does
   *  not silently swallow an existing message the way a host-change would
   *  want to (still a fresh user action, so the message does clear). */
  refresh: () => void;
  unmount: () => void;
  setDraft: (toolhead0: number, value: string) => void;
  draftFor: (toolhead0: number) => string;
  saveAll: () => Promise<void>;
  removeAll: () => Promise<void>;
  updateToPrinter: (toolhead1: number, value: number) => Promise<void>;
  removeNote: (toolhead1: number) => Promise<void>;
}

export function createNozzleSettingsController(
  deps: NozzleSettingsDeps = defaultDeps,
): NozzleSettingsController {
  let token = 0;
  let host = "";
  let port = 7125;
  // R4-D1: a mutation is bound to the {host, port, epoch} it started under.
  // `epoch` bumps ONLY on start() (host change) and unmount() — never on a
  // plain refresh, never on another mutation — so a mutation that outlives a
  // host change can detect it and apply nothing, without being confused by
  // the unrelated token bumps its own eventual recovery fetch would cause.
  let epoch = 0;

  const store = createStore<NozzleSettingsState>(() => initialState());

  function isCurrent(myToken: number): boolean {
    return myToken === token;
  }

  function beginFetch(opts: { immediateLive?: boolean } = {}): void {
    const myToken = ++token;
    store.setState({ status: null, loadError: false, checkingLive: false, liveCheckFailed: false });
    void runNozzleFetch({
      host, port,
      isCurrent: () => isCurrent(myToken),
      api: { nozzleStatus: deps.nozzleStatus },
      // R4-D6: a host change debounces the live probe (typing a host
      // character by character must not fire one live probe per keystroke);
      // an explicit user Refresh does not wait.
      liveDelayMs: opts.immediateLive ? 0 : LIVE_DEBOUNCE_MS,
      wait: deps.wait,
      on: {
        quick: (s) => store.setState({ status: s, checkingLive: true }),
        live: (s) => store.setState({ status: s, checkingLive: false }),
        liveFailed: () => store.setState({ checkingLive: false }),
        allFailed: () => store.setState({ checkingLive: false, loadError: true }),
      },
    });
  }

  function start(newHost: string, newPort: number): void {
    epoch += 1; // R4-D1: any mutation still in flight for the old host is now foreign
    host = newHost;
    port = newPort;
    // A fresh, non-busy state for the new host — this does not "release" the
    // old epoch's mutation; that mutation simply no-ops when it notices the
    // epoch changed, rather than ever touching this (or any later) state.
    store.setState({ draft: {}, errorMessage: null, busy: false });
    beginFetch();
  }

  function refresh(): void {
    store.setState((s) => ({ errorMessage: nextNozzleErrorMessage(s.errorMessage, { type: "user_action_started" }) }));
    beginFetch({ immediateLive: true });
  }

  function unmount(): void {
    epoch += 1; // R4-D1: same as a host change — nothing still in flight may apply
    token += 1; // invalidates any in-flight fetch/recovery; nothing further is applied
  }

  function setDraft(toolhead0: number, value: string): void {
    store.setState((s) => ({ draft: { ...s.draft, [toolhead0]: value } }));
  }

  function draftFor(toolhead0: number): string {
    const s = store.getState();
    const stored = s.draft[toolhead0];
    if (stored !== undefined) return stored;
    const t = s.status?.toolheads.find((x) => x.toolhead === toolhead0);
    return t?.confirmed != null ? String(t.confirmed) : "";
  }

  async function runMutation(build: (status: NozzleStatus) => Promise<NozzleMutationResult>): Promise<void> {
    const before = store.getState();
    if (before.busy) return; // serialised (F4): a mutation already in flight wins
    if (!before.status) return;

    const myEpoch = epoch; // R4-D1: bind this mutation to the host/port it started under
    store.setState((s) => ({
      busy: true,
      errorMessage: nextNozzleErrorMessage(s.errorMessage, { type: "user_action_started" }),
    }));

    const result = await build(before.status);

    // The host changed (or we unmounted) while this was in flight: apply
    // NOTHING — no status, no token bump, no message, no busy change. The
    // mutation helper already bumped the global nozzleNotesVersion on
    // success regardless (host-agnostic, happens whether or not anything is
    // still here to receive it); that is the only effect this outcome is
    // still allowed to have.
    if (myEpoch !== epoch) return;

    if (result.ok) {
      // The mutation response is the server's authoritative post-commit
      // state (Fable decision) — bump the token first so any in-flight
      // phase-2 read can never overwrite it, then apply directly.
      token += 1;
      const myToken = token;
      store.setState({ status: result.status, draft: {}, busy: false, checkingLive: true, liveCheckFailed: false });
      // N12: confirm/clear now return a probe:false snapshot (backend R4-B1)
      // — reachable:false, live_error:"not_checked" — not a live reading. Left
      // there, a save on a perfectly reachable printer would show "Unknown",
      // no conflict row, and the "nothing reported" banner until a manual
      // Refresh. Immediately follow up with the live phase ALONE (no
      // debounce — the host didn't just change, a value was just written),
      // bound to the same epoch/token as everything else.
      //
      // Opus follow-up (honesty fix): /nozzles/status?probe=true never
      // REJECTS for an offline printer — it answers 200 with
      // reachable:false, live_error:"unreachable", which the success branch
      // below already applies as real data (that's the correct, honest
      // "nothing reported" case). The `.then()` rejection path is reached
      // only when the REQUEST itself failed (local service down, network
      // error, 500) — the printer was never actually asked, so nothing may
      // claim "unreachable" or "nothing reported" about it. `status` (and
      // its `live_error: "not_checked"`) is left completely untouched;
      // `liveCheckFailed` records the request failure separately so the UI
      // can show a neutral "couldn't check" note instead.
      deps.nozzleStatus(host, port, true).then(
        (live) => {
          if (myEpoch !== epoch) return;
          if (!isCurrent(myToken)) return;
          store.setState({ status: live, checkingLive: false, liveCheckFailed: false });
        },
        () => {
          if (myEpoch !== epoch) return;
          if (!isCurrent(myToken)) return;
          store.setState({ checkingLive: false, liveCheckFailed: true });
        },
      );
      return;
    }

    const code = result.error.code;
    // R4-D3: a definite 409 stale AND an uncertain failure (no code at all —
    // a network error nozzleMutations.ts couldn't attribute to a backend
    // response) both get exactly one recovery fetch, on the same fetch
    // path/token as everything else — the write might have landed even
    // though this call never learned the outcome.
    if (code === "stale" || code === undefined) {
      store.setState((s) => ({
        errorMessage: nextNozzleErrorMessage(s.errorMessage, { type: "mutation_failed", message: result.error.message, code }),
      }));
      const myToken = ++token;
      try {
        const fresh = await deps.nozzleStatus(host, port, true);
        if (myEpoch !== epoch) return;
        if (!isCurrent(myToken)) return;
        store.setState((s) => ({
          status: fresh, busy: false,
          errorMessage: nextNozzleErrorMessage(s.errorMessage, { type: "status_refetched" }),
        }));
      } catch {
        if (myEpoch !== epoch) return;
        if (!isCurrent(myToken)) return;
        // Distinguish a failed recovery from a successful one: the message
        // is left exactly as it was (never silently cleared or replaced),
        // and loadError additionally signals the read itself didn't work.
        store.setState({ busy: false, loadError: true });
      }
      return;
    }

    store.setState((s) => ({
      busy: false,
      errorMessage: nextNozzleErrorMessage(s.errorMessage, { type: "mutation_failed", message: result.error.message, code }),
    }));
  }

  return {
    store, getState: store.getState, subscribe: store.subscribe,
    start, refresh, unmount, setDraft, draftFor,
    saveAll: () => runMutation((status) =>
      deps.confirmNozzles(host, port, diametersForSaveAll(status, draftFor), status.revision)),
    removeAll: () => runMutation((status) =>
      deps.clearNozzles(host, port, status.revision)),
    updateToPrinter: (toolhead1, value) => runMutation((status) =>
      deps.confirmNozzles(host, port, diametersForUpdate(status, toolhead1, value), status.revision)),
    removeNote: (toolhead1) => runMutation((status) =>
      deps.confirmNozzles(host, port, diametersForRemove(status, toolhead1), status.revision)),
  };
}
