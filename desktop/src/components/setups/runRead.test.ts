import { describe, expect, it } from "vitest";
import { buildEvaluateBody } from "@/lib/setupsApi";
import type { EvaluateResponse } from "@/lib/setupsTypes";
import { runRead, type ReadState } from "./runRead";
import { SAMPLE_REPORT } from "./sampleReport";

const response = (label: string): EvaluateResponse =>
  ({ report: { ...SAMPLE_REPORT, advisory: label }, read: {} } as unknown as EvaluateResponse);

function screen(initial: Partial<ReadState> = {}) {
  const state: ReadState = { busy: false, error: null, result: null, ...initial };
  const history: ReadState[] = [];
  return { state, history, set: (patch: Partial<ReadState>) => { Object.assign(state, patch); history.push({ ...state }); } };
}

describe("a Setups read", () => {
  it("clears an earlier host's report before the request goes out and keeps it cleared when the read fails", async () => {
    const s = screen({ result: response("old host") });
    await runRead(() => Promise.reject(new Error("The host did not answer.")), s.set, () => true);
    expect(s.history[0]).toEqual({ busy: true, error: null, result: null });
    expect(s.state).toEqual({ busy: false, error: "The host did not answer.", result: null });
  });

  it("shows a bad port as an error with no report, before any request is made", async () => {
    const s = screen({ result: response("old host") });
    let sent = false;
    await runRead(async () => {
      const body = buildEvaluateBody({ host: "h", port: "abc" });   // throws before a request exists
      sent = true;
      return response(JSON.stringify(body));
    }, s.set, () => true);
    expect(sent).toBe(false);
    expect(s.state.result).toBeNull();
    expect(s.state.error).toMatch(/port must be a whole number/i);
  });

  it("replaces the report with the new answer on success", async () => {
    const s = screen({ result: response("old host") });
    await runRead(async () => response("new host"), s.set, () => true);
    expect(s.state.result?.report.advisory).toBe("new host");
    expect(s.state.busy).toBe(false);
  });

  it("lets a stale read change nothing after the view is left or a newer read started", async () => {
    const s = screen();
    let current = true;
    const slow = runRead(async () => { current = false; return response("late"); }, s.set, () => current);
    await slow;
    expect(s.state.result).toBeNull();
    expect(s.history).toHaveLength(1);
    const f = screen();
    await runRead(async () => { throw new Error("late failure"); }, f.set, () => false);
    expect(f.state.error).toBeNull();
  });
});
