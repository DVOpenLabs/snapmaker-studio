// @vitest-environment jsdom
import React from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({ watchFolder: vi.fn(), doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));

import { watchFolder } from "@/api";
import { OrcaRoundTrip } from "@/components/OrcaRoundTrip";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { useWatch } from "@/store/watch";

const FOLDER_1 = "C:\\exports";
const FOLDER_2 = "C:\\other-exports";
const file = (name: string) => ({ path: `C:\\projects\\${name}.3mf`, name: `${name}.3mf`, ext: "3mf" });
const reply = (best: string | null) =>
  ({ schema_version: "watch/1", available: true, folder: FOLDER_1, best, best_verdict: best ? "confirmed" : null, candidates: [], summary: "" }) as any;

/** A watch call the test settles by hand, keyed by the (folder, project) it was made for. */
function deferred() {
  const pending: Record<string, (value: any) => void> = {};
  vi.mocked(watchFolder).mockImplementation((folder, project) =>
    new Promise((resolve) => { pending[`${folder}|${project}`] = resolve; }));
  return pending;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  localStorage.clear();
  useSession.setState({ file: file("A") });
  useSliced.setState({ path: null, name: null });
  useWatch.setState({ folder: FOLDER_1, autoOpen: true });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("the watch response only ever applies to the job it was asked about", () => {
  it("control: a current response opens its matched job", async () => {
    vi.mocked(watchFolder).mockResolvedValue(reply("C:\\exports\\A.gcode"));
    render(<OrcaRoundTrip />);
    await act(async () => {});
    expect(useSliced.getState().path).toBe("C:\\exports\\A.gcode");
  });

  it("control: an ambiguous response chooses nothing", async () => {
    vi.mocked(watchFolder).mockResolvedValue(reply(null));
    render(<OrcaRoundTrip />);
    await act(async () => {});
    expect(useSliced.getState().path).toBeNull();
  });

  it("R1: a late answer for project A cannot open A's job once B is selected", async () => {
    const pending = deferred();
    render(<OrcaRoundTrip />);
    await act(async () => {});
    act(() => useSession.setState({ file: file("B") }));
    await act(async () => {});
    await act(async () => pending[`${FOLDER_1}|${file("A").path}`](reply("C:\\exports\\A.gcode")));
    expect(useSliced.getState().path).toBeNull();
    await act(async () => pending[`${FOLDER_1}|${file("B").path}`](reply("C:\\exports\\B.gcode")));
    expect(useSliced.getState().path).toBe("C:\\exports\\B.gcode");
  });

  it("a late answer for the old folder cannot open a job after the folder changes", async () => {
    const pending = deferred();
    render(<OrcaRoundTrip />);
    await act(async () => {});
    act(() => useWatch.setState({ folder: FOLDER_2 }));
    await act(async () => {});
    await act(async () => pending[`${FOLDER_1}|${file("A").path}`](reply("C:\\exports\\A.gcode")));
    expect(useSliced.getState().path).toBeNull();
  });

  it("a late answer after the page is left opens nothing", async () => {
    const pending = deferred();
    const view = render(<OrcaRoundTrip />);
    await act(async () => {});
    view.unmount();
    await act(async () => pending[`${FOLDER_1}|${file("A").path}`](reply("C:\\exports\\A.gcode")));
    expect(useSliced.getState().path).toBeNull();
  });

  it("a slow scan is not starved: the timer does not stack a second scan on it", async () => {
    let calls = 0;
    const settle: Array<(value: any) => void> = [];
    vi.mocked(watchFolder).mockImplementation(() => new Promise((resolve) => { calls += 1; settle.push(resolve); }));
    render(<OrcaRoundTrip />);
    await act(async () => {});
    await act(async () => { vi.advanceTimersByTime(15000); });
    expect(calls).toBe(1);
    await act(async () => settle[0](reply("C:\exports\slow.gcode")));
    expect(useSliced.getState().path).toBe("C:\exports\slow.gcode");
  });

  it("switching A to B and back does not reuse A's old answer", async () => {
    const settle: Record<string, Array<(value: any) => void>> = {};
    vi.mocked(watchFolder).mockImplementation((_f, project) => new Promise((resolve) => { (settle[project as string] ||= []).push(resolve); }));
    render(<OrcaRoundTrip />);
    await act(async () => {});
    await act(async () => settle[file("A").path][0](reply(null)));
    act(() => useSession.setState({ file: file("B") }));
    await act(async () => {});
    act(() => useSession.setState({ file: file("A") }));
    await act(async () => {});
    expect(useSliced.getState().path).toBeNull();
    expect(settle[file("A").path].length).toBe(2);
  });

  it("N5a: an older scan of the SAME project, released after a newer one was asked, opens nothing", async () => {
    const asked: Array<(value: any) => void> = [];
    vi.mocked(watchFolder).mockImplementation(() => new Promise((resolve) => { asked.push(resolve); }));
    render(<OrcaRoundTrip />);
    await act(async () => {});                                        // A1 asked
    act(() => useSession.setState({ file: file("B") }));
    await act(async () => {});                                        // B asked
    act(() => useSession.setState({ file: file("A") }));
    await act(async () => {});                                        // A2 asked
    expect(asked.length).toBe(3);
    await act(async () => asked[2](reply(null)));
    await act(async () => asked[0](reply("C:\\exports\\old-A.gcode")));   // matches folder+project: only the ticket can stop it
    expect(useSliced.getState().path).toBeNull();
  });

  it("N5b: switching project in the same render that turns auto-open on does not open the old project's matched job", async () => {
    useWatch.setState({ autoOpen: false });
    const asked: Record<string, Array<(value: any) => void>> = {};
    vi.mocked(watchFolder).mockImplementation((_f, project) => new Promise((resolve) => { (asked[project as string] ||= []).push(resolve); }));
    render(<OrcaRoundTrip />);
    await act(async () => {});
    await act(async () => asked[file("A").path][0](reply("C:\\exports\\A.gcode")));   // matched, but auto-open is off
    expect(useSliced.getState().path).toBeNull();
    act(() => { useSession.setState({ file: file("B") }); useWatch.setState({ autoOpen: true }); });
    await act(async () => {});
    expect(useSliced.getState().path).toBeNull();
  });

  it("auto-open off: a matched job is listed, never opened", async () => {
    useWatch.setState({ autoOpen: false });
    vi.mocked(watchFolder).mockResolvedValue(reply("C:\\exports\\A.gcode"));
    render(<OrcaRoundTrip />);
    await act(async () => {});
    expect(useSliced.getState().path).toBeNull();
  });
});
