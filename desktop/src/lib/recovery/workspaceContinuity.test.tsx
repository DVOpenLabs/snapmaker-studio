// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- a fake local service over a fake disk: every call goes through the same extApi seam the real views use ------
const disk: Record<string, string | null> = {};
const calls: Array<{ path: string; body: any }> = [];
const verifyGates: Array<Promise<void>> = [];
const prepareGates: Record<string, Promise<void>> = {};
const svc = { revision: 0, tracked: [] as Array<{ name: string; path: string; content: string | null }>, failCheckpoint: false };
const hashOf = (c: string | null) => (c === null ? "" : `h:${c}`);

vi.mock("@/lib/extApi", () => ({
  callExt: vi.fn(async (path: string, body: any) => {
    calls.push({ path, body });
    if (path === "/recovery/checkpoint") {
      if (svc.failCheckpoint) throw new Error("The checkpoint could not be written");
      if (body.expected_revision !== svc.revision) throw new Error("The checkpoint changed in another window");
      svc.revision += 1;
      svc.tracked = body.files.map((f: any) => ({ name: f.name, path: f.path, content: disk[f.path] ?? null }));
      return { revision: svc.revision, checkpointed_at: "2026-01-01T00:00:00Z", file_count: svc.tracked.length };
    }
    if (path === "/recovery/restore") {
      return {
        missing_checkpoint: svc.revision === 0, revision: svc.revision, checkpointed_at: "2026-01-01T00:00:00Z",
        workspace: { name: "w" }, observations: [], jobs: [], fresh_read_required: true,
        files: svc.tracked.map((f) => ({ name: f.name, association: "unverified",
          state: disk[f.path] == null ? "missing" : disk[f.path] === f.content ? "same" : "changed" })),
      };
    }
    if (path === "/passport/build") {
      const artifacts = body.entries.map((e: any) => ({ artifact_id: `id:${e.role}`, role: e.role, name: e.path.split("/").pop(),
        bytes: { sha256: hashOf(disk[e.path] ?? null), size_bytes: (disk[e.path] ?? "").length }, content: disk[e.path] ?? null, path: e.path }));
      if (artifacts.some((a: any) => a.content === null)) return { passport: null, paths: {}, diagnostics: [{ code: "file_missing", field: "x", severity: "error" }], losses: [] };
      return { passport: { schema_version: "passport/1", passport_id: `pp:${artifacts.map((a: any) => a.name).join("+")}`, created_at: "t",
        artifacts: artifacts.map(({ content, path: _p, ...a }: any) => ({ ...a, _content: content })), derivations: [], recipes: [], material_mappings: [], losses: [] },
        paths: Object.fromEntries(artifacts.map((a: any) => [`id:${a.role}`, a.path])), diagnostics: [], losses: [] };
    }
    if (path === "/passport/verify") {
      const gate = verifyGates.shift();
      const arts = body.passport.artifacts.map((a: any) => {
        const now = disk[body.paths[a.artifact_id]] ?? null;
        const bytes = now === null ? "missing" : now === a._content ? "same" : "changed";
        return { artifact_id: a.artifact_id, name: a.name, role: a.role, size_bytes: a.bytes.size_bytes, sha256: a.bytes.sha256, bytes,
          chain: bytes === "same" ? "intact" : "invalidated", reasons: [] };
      });
      const answer = { verification: { passport_id: body.passport.passport_id, artifacts: arts, derivations: [], recipes_retained: [], material_mappings_retained: [], losses: [], note: "n",
        summary: { all_intact: arts.every((a: any) => a.bytes === "same"), intact: [], invalidated: [], unverified: [], declared_mismatch: [] } }, diagnostics: [] };
      if (gate) await gate;   // the answer reflects the disk when it was asked, however late it is delivered
      return answer;
    }
    throw new Error(`unexpected call ${path}`);
  }),
}));
vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  jobCheck: vi.fn(async (entries: any[]) => ({ files: entries.map((e) => ({ role: e.role, status: "recorded", observed: { size_bytes: 1, sha256: hashOf(disk[e.path] ?? null) } })) })),
}));
// Creative's prepare goes through its own client; the report/preview panels are presentation only here.
const responses: Record<string, any> = {};
vi.mock("@/lib/creativeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/creativeApi")>()),
  fetchCreativeFormats: vi.fn(async () => ({ formats: [] })),
  inspectCreative: vi.fn(async () => ({ origin: { status: "detected" } })),
  prepareCreative: vi.fn(async (path: string) => {
    const key = String(path).trim().replace(/^"(.*)"$/, "$1");
    const answer = responses[key];                       // what the service answers to THIS request
    const gate = prepareGates[key] as Promise<void> | undefined;
    if (gate) await gate;
    return answer;
  }),
}));
vi.mock("@/components/creative/CreativeReportView", () => ({ default: () => <div>report</div> }));
vi.mock("@/components/creative/CreativePreparePanel", () => ({ default: () => <div>prepare-panel</div> }));
vi.mock("@/components/creative/CreativeFormatChooser", () => ({ default: () => <div>chooser</div> }));

import CreativeView from "@/components/creative/CreativeView";
import PassportView from "@/lib/passport/PassportView";
import { usePassportSession } from "@/lib/passport/session";
import { RecoveryView } from "@/lib/recovery/RecoveryView";
import { __resetRecoverySubscriberForTests } from "@/lib/recovery/subscriber";
import { trackJob, useJob, useUnlinkedCopies } from "@/store/job";
import { useSession } from "@/store/session";

const PROJECT_A = "C:/work/bracket.3mf", COPY_A = "C:/studio/creative-prepared/bracket_SnapmakerU1.3mf";
const PROJECT_B = "C:/work/vase.3mf", COPY_B = "C:/studio/creative-prepared/vase_SnapmakerU1.3mf";

const done = (name: string, local_path: string, validated_ok = true) => ({
  prepared: true, origin: { generator: "kromacut", status: "detected", candidates: [] },
  output: { name, local_path, location: "studio_default", location_label: "Studio's creative-prepared folder", in_source_folder: false },
  prepare: { mode: "preserve", validated_ok, errors: [], compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [] },
});

function Shell({ start = "creative" }: { start?: string }) {
  const [route, setRoute] = useState(start);
  return <div>
    <nav>{["creative", "passport", "recovery"].map((r) => <button key={r} onClick={() => setRoute(r)}>{`go ${r}`}</button>)}</nav>
    {route === "creative" && <CreativeView />}{route === "passport" && <PassportView />}{route === "recovery" && <RecoveryView />}
  </div>;
}
const go = (r: string) => fireEvent.click(screen.getByText(`go ${r}`));
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

/** Journey step through the real Creative view: inspect, then Prepare. Nothing is injected into the stores. */
async function startPrepare(project: string, copy: string, copyName: string, validated = true) {
  go("creative");
  type("Project file path", project);
  fireEvent.click(screen.getByText("Inspect project"));
  await screen.findByLabelText("Prepare a U1 copy");
  responses[project.replace(/^"(.*)"$/, "$1")] = done(copyName, copy, validated);
  fireEvent.click(screen.getByRole("button", { name: "Prepare a U1 copy" }));
}
async function prepareThroughCreative(project: string, copy: string, copyName: string) {
  await startPrepare(project, copy, copyName);
  await screen.findByText("prepare-panel");
  await waitFor(() => expect(useJob.getState().record?.prepared?.path).toBe(copy));
}
const refreshPreview = async () => { fireEvent.click(screen.getByText("Refresh restore preview")); await waitFor(() => expect((screen.getByRole("button", { name: "Checkpoint this workspace" }) as HTMLButtonElement).disabled).toBe(false)); };

beforeEach(() => {
  for (const k of Object.keys(disk)) delete disk[k];
  Object.assign(disk, { [PROJECT_A]: "a-original", [COPY_A]: "a-copy", [PROJECT_B]: "b-original", [COPY_B]: "b-copy" });
  verifyGates.length = 0; for (const k of Object.keys(prepareGates)) delete prepareGates[k];
  calls.length = 0; Object.assign(svc, { revision: 0, tracked: [], failCheckpoint: false });
  window.localStorage.clear(); useJob.getState().forget(); useUnlinkedCopies.getState().clear();
  untrack = trackJob();   // the real session -> job linking, as the app starts it usePassportSession.getState().resetForTests(); __resetRecoverySubscriberForTests();
});
afterEach(() => { untrack(); cleanup(); });

let untrack: () => void = () => undefined;
describe("workspace checkpoint and passport continuity (jsdom, real views, fake local service)", () => {
  it("Prepare output becomes checkpoint input; only linked files are tracked and the rest is explained", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("recovery");
    const tracked = screen.getByTestId("tracked-files");
    expect(tracked.textContent).toContain("Original project: bracket.3mf");
    expect(tracked.textContent).toContain("Prepared copy: bracket_SnapmakerU1.3mf");
    expect(tracked.textContent).not.toContain("Sliced");
    expect(screen.getByTestId("unavailable-files").textContent).toContain("Sliced output not tracked");
    await refreshPreview();
    fireEvent.click(screen.getByRole("button", { name: "Checkpoint this workspace" }));
    await screen.findByText(/Workspace checkpoint saved/);
    const sent = calls.find((c) => c.path === "/recovery/checkpoint")!.body;
    expect(sent.files).toEqual([{ name: "bracket.3mf", path: PROJECT_A }, { name: "bracket_SnapmakerU1.3mf", path: COPY_A }]);
    expect(sent.workspace).toEqual({ name: "bracket.3mf", stage: "prepared" });
    expect(screen.getByTestId("checkpoint-notice").textContent).toContain("2 file(s) tracked");
  });

  it("with no project open the real action is unavailable and says why; the sample is a separate, labelled action", async () => {
    render(<Shell start="recovery" />);
    expect(screen.getByTestId("no-workspace").textContent).toContain("No project is open");
    await refreshPreview().catch(() => undefined);
    fireEvent.click(screen.getByText("Refresh restore preview"));
    await waitFor(() => expect((screen.getByRole("button", { name: "Save sample checkpoint" }) as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByRole("button", { name: "Checkpoint this workspace" }) as HTMLButtonElement).disabled).toBe(true);
    const sample = screen.getByLabelText("Sample data");
    expect(within(sample).getByText("Sample data (not your workspace)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save sample checkpoint" }));
    await screen.findByText(/Sample checkpoint saved \(demo data, no files tracked\)/);
    expect(calls.find((c) => c.path === "/recovery/checkpoint")!.body.files).toEqual([]);
  });

  it("a failed checkpoint is shown as a failure and never as a success", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("recovery"); await refreshPreview();
    svc.failCheckpoint = true;
    fireEvent.click(screen.getByRole("button", { name: "Checkpoint this workspace" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Checkpoint NOT saved");
    expect(screen.queryByText(/Workspace checkpoint saved/)).toBeNull();   // ("No checkpoint saved yet" from the preview is not a success)
    expect(svc.revision).toBe(0);
  });

  it("a checkpoint saved while a tracked file is missing says that file cannot be verified later", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    disk[COPY_A] = null;   // deleted after Prepare, before the checkpoint
    go("recovery"); await refreshPreview();
    fireEvent.click(screen.getByRole("button", { name: "Checkpoint this workspace" }));
    await screen.findByText(/Workspace checkpoint saved/);
    const text = screen.getByTestId("checkpoint-notice").textContent!;
    expect(text).toContain("Not verifiable later");
    expect(text).toContain("bracket_SnapmakerU1.3mf");
    expect(text).not.toContain("bracket.3mf,");   // the intact original is not flagged
  });

  it("changed and deleted tracked files show as changed and missing in the read-only preview", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("recovery"); await refreshPreview();
    fireEvent.click(screen.getByRole("button", { name: "Checkpoint this workspace" })); await screen.findByText(/Workspace checkpoint saved/);
    await waitFor(() => expect(screen.getByTestId("restore-preview").textContent).toContain("unchanged since the checkpoint"));
    disk[PROJECT_A] = "a-original EDITED"; disk[COPY_A] = null;
    fireEvent.click(screen.getByText("Refresh restore preview"));
    await waitFor(() => {
      const text = screen.getByTestId("restore-preview").textContent!;
      expect(text).toContain("bracket.3mf: changed since the checkpoint");
      expect(text).toContain("bracket_SnapmakerU1.3mf: missing from its recorded location");
    });
    // read-only: the preview only called /recovery/restore after the one checkpoint write
    expect(calls.filter((c) => c.path !== "/recovery/restore" && c.path !== "/recovery/checkpoint")).toEqual([]);
  });

  it("Passport -> Recovery -> Passport keeps the fields and the report, and nothing about it is put in localStorage", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport");
    fireEvent.click(screen.getByText("Use this job's files"));
    expect((screen.getByLabelText("Original file path") as HTMLInputElement).value).toBe(PROJECT_A);
    expect((screen.getByLabelText("Prepared copy path") as HTMLInputElement).value).toBe(COPY_A);
    expect((screen.getByLabelText("Sliced output path") as HTMLInputElement).value).toBe("");   // nothing invented
    fireEvent.click(screen.getByText("Build passport"));
    await screen.findByTestId("passport-report");
    go("recovery"); expect(screen.queryByTestId("passport-report")).toBeNull();
    go("passport");
    expect(screen.getByTestId("passport-report")).toBeTruthy();
    expect((screen.getByLabelText("Original file path") as HTMLInputElement).value).toBe(PROJECT_A);
    expect(screen.getByTestId("passport-scope").textContent).toContain("project bracket.3mf");
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i)!;
      expect(key).not.toMatch(/passport/i);
    }
    expect(screen.getByText(/not saved across a restart/)).toBeTruthy();
  });

  it("a report built for one project is not shown after another project is opened", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport"); fireEvent.click(screen.getByText("Use this job's files")); fireEvent.click(screen.getByText("Build passport"));
    await screen.findByTestId("passport-report");
    await prepareThroughCreative(PROJECT_B, COPY_B, "vase_SnapmakerU1.3mf");   // opens a different project
    go("passport");
    expect(screen.queryByTestId("passport-report")).toBeNull();
    expect((screen.getByLabelText("Original file path") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Prepared copy path") as HTMLInputElement).value).toBe("");
    await waitFor(() => expect(screen.getByTestId("passport-notice").textContent).toContain("A different project is open now"));
    expect(document.body.textContent).not.toContain("bracket");
  });

  it("editing the file fields after a build marks the report as describing earlier files", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport"); fireEvent.click(screen.getByText("Use this job's files")); fireEvent.click(screen.getByText("Build passport"));
    await screen.findByTestId("passport-report");
    expect(screen.queryByTestId("passport-stale")).toBeNull();
    type("Prepared copy path", COPY_B);
    expect(screen.getByTestId("passport-stale").textContent).toContain("describes the earlier entries");
  });

  it("deleting a tracked file and re-checking the same passport invalidates it", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport"); fireEvent.click(screen.getByText("Use this job's files")); fireEvent.click(screen.getByText("Build passport"));
    await screen.findByTestId("passport-report");
    expect(screen.getByTestId("artifact-prepared").textContent).toContain("Same bytes");
    disk[COPY_A] = null; disk[PROJECT_A] = "a-original EDITED";
    await act(async () => { fireEvent.click(screen.getByText("Check the files again")); });
    await waitFor(() => expect(screen.getByTestId("artifact-original").textContent).not.toContain("Same bytes"));
    expect(screen.getByTestId("artifact-prepared").textContent).not.toContain("Same bytes");
  });
  it("a quoted path (Copy as path) links the file that was actually prepared, without the quotes", async () => {
    render(<Shell />);
    await startPrepare(`"${PROJECT_A}"`, COPY_A, "bracket_SnapmakerU1.3mf");
    await screen.findByText("prepare-panel");
    await waitFor(() => expect(useJob.getState().record?.prepared?.path).toBe(COPY_A));
    expect(useJob.getState().record?.original.path).toBe(PROJECT_A);
    expect(useJob.getState().record?.original.name).toBe("bracket.3mf");
  });

  it("a copy that did not pass validation is not linked, and the page says so", async () => {
    render(<Shell />);
    await startPrepare(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf", false);
    await screen.findByTestId("creative-link-note");
    expect(screen.getByTestId("creative-link-note").textContent).toContain("did not pass Studio's validation");
    expect(useJob.getState().record?.prepared ?? null).toBeNull();
    go("recovery");
    expect(screen.getByTestId("no-workspace").textContent).toContain("No project is open");
  });

  it("an older Prepare that finishes late does not take the job back from a newer project", async () => {
    render(<Shell />);
    let release!: () => void;
    prepareGates[PROJECT_A] = new Promise<void>((resolve) => { release = resolve; });
    await startPrepare(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");          // A starts and waits
    go("recovery");
    await prepareThroughCreative(PROJECT_B, COPY_B, "vase_SnapmakerU1.3mf");     // B starts and completes
    expect(useJob.getState().record?.original.path).toBe(PROJECT_B);
    await act(async () => { release(); await Promise.resolve(); });              // A completes late
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(useJob.getState().record?.original.path).toBe(PROJECT_B);
    expect(useJob.getState().record?.prepared?.path).toBe(COPY_B);
  });

  it("a saved job from an earlier session is not offered as the open workspace until it is reopened or checked", async () => {
    useJob.setState({ verified: false, record: { schema: "job/1", savedAt: "t", original: { path: PROJECT_A, name: "bracket.3mf", fingerprint: null },
      prepared: { path: COPY_A, name: "bracket_SnapmakerU1.3mf", fingerprint: null, mode: "preserve" }, sliced: null } });   // what startup reads from storage
    render(<Shell start="recovery" />);
    expect(screen.getByTestId("no-workspace").textContent).toContain("earlier session");
    expect((screen.getByRole("button", { name: "Checkpoint this workspace" }) as HTMLButtonElement).disabled).toBe(true);
    go("passport");
    expect((screen.getByRole("button", { name: "Use this job's files" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("passport-job-unverified").textContent).toContain("earlier session");
  });

  it("fields typed by hand under one project are cleared when another project is opened", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport");
    type("Original file path", PROJECT_A);              // typed, not from the job and never built
    expect((screen.getByLabelText("Original file path") as HTMLInputElement).value).toBe(PROJECT_A);
    await prepareThroughCreative(PROJECT_B, COPY_B, "vase_SnapmakerU1.3mf");
    go("passport");
    expect((screen.getByLabelText("Original file path") as HTMLInputElement).value).toBe("");
    await waitFor(() => expect(screen.getByTestId("passport-notice").textContent).toContain("different project"));
  });

  it("a late, older verification never overwrites a newer one", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport"); fireEvent.click(screen.getByText("Use this job's files"));
    let releaseOld!: () => void;
    verifyGates.push(new Promise<void>((resolve) => { releaseOld = resolve; }));   // the first check (made right after the build) is held
    fireEvent.click(screen.getByText("Build passport"));
    await waitFor(() => expect(calls.some((c) => c.path === "/passport/verify")).toBe(true));
    go("recovery"); go("passport");                    // leave and re-enter while that check is still pending
    disk[COPY_A] = null;                                // the file goes missing
    await act(async () => { fireEvent.click(screen.getByText("Check the files again")); });
    await waitFor(() => expect(screen.getByTestId("artifact-prepared").textContent).not.toContain("Same bytes"));
    await act(async () => { releaseOld(); await new Promise((r) => setTimeout(r, 30)); });   // the older "same bytes" answer arrives last
    expect(screen.getByTestId("artifact-prepared").textContent).not.toContain("Same bytes");
  });
  it("an older Prepare of the same project that finishes late does not replace the newer copy", async () => {
    render(<Shell />);
    const COPY_A2 = "C:/studio/creative-prepared/bracket_SnapmakerU1-2.3mf";
    let release!: () => void;
    prepareGates[PROJECT_A] = new Promise<void>((resolve) => { release = resolve; });
    await startPrepare(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");            // first run waits
    go("recovery");
    delete prepareGates[PROJECT_A];
    await prepareThroughCreative(PROJECT_A, COPY_A2, "bracket_SnapmakerU1-2.3mf");   // second run completes
    expect(useJob.getState().record?.prepared?.path).toBe(COPY_A2);
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 30)); });
    expect(useJob.getState().record?.prepared?.path).toBe(COPY_A2);
  });

  it("an older Creative Prepare does not replace a copy linked by an ordinary Prepare of the same project", async () => {
    render(<Shell />);
    const ORDINARY = "C:/studio/prepared/bracket_ordinary.3mf";
    let release!: () => void;
    prepareGates[PROJECT_A] = new Promise<void>((resolve) => { release = resolve; });
    await startPrepare(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");          // Creative run waits
    go("recovery");
    delete prepareGates[PROJECT_A];
    act(() => { useSession.getState().setFile(PROJECT_A); });                    // the project is opened on the main page
    act(() => { useSession.setState({ convert: { status: "done", data: { output_path: ORDINARY, blocked: false, validated_ok: true, prepare_mode: "preserve" }, error: null } as any }); });
    await waitFor(() => expect(useJob.getState().record?.prepared?.path).toBe(ORDINARY));
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 30)); });
    expect(useJob.getState().record?.prepared?.path).toBe(ORDINARY);              // not replaced by the older Creative copy
    go("creative");
    expect(screen.getByTestId("creative-unlinked").textContent).toContain("bracket_SnapmakerU1.3mf");   // and it says so
  });

  it("A -> B -> A on the main page while a Creative Prepare of A runs: the late result is not linked", async () => {
    render(<Shell />);
    let release!: () => void;
    prepareGates[PROJECT_A] = new Promise<void>((resolve) => { release = resolve; });
    await startPrepare(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("recovery");
    act(() => { useSession.getState().setFile(PROJECT_A); });
    act(() => { useSession.getState().setFile(PROJECT_B); });
    act(() => { useSession.getState().setFile(PROJECT_A); });                    // back to the same path
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 30)); });
    expect(useJob.getState().record?.original.path).toBe(PROJECT_A);
    expect(useJob.getState().record?.prepared ?? null).toBeNull();
  });

  it("a newer Prepare that is refused does not stop an older valid copy from being linked", async () => {
    render(<Shell />);
    let release!: () => void;
    prepareGates[PROJECT_A] = new Promise<void>((resolve) => { release = resolve; });
    await startPrepare(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("recovery");
    go("creative"); type("Project file path", PROJECT_B);
    fireEvent.click(screen.getByText("Inspect project")); await screen.findByLabelText("Prepare a U1 copy");
    responses[PROJECT_B] = { prepared: false, refusal: { kind: "x", seen: "", not_supported: "", what_to_do: [] }, origin: { status: "detected" } };
    fireEvent.click(screen.getByRole("button", { name: "Prepare a U1 copy" }));
    await screen.findByText("prepare-panel");                                      // B was refused: nothing written, nothing linked
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 30)); });
    expect(useJob.getState().record?.prepared?.path).toBe(COPY_A);
  });

  it("a project change while the Passport page is not open still clears it (A -> B -> A)", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport"); fireEvent.click(screen.getByText("Use this job's files")); fireEvent.click(screen.getByText("Build passport"));
    await screen.findByTestId("passport-report");
    go("recovery");
    act(() => { useSession.getState().setFile(PROJECT_B); });
    act(() => { useSession.getState().setFile(PROJECT_A); });                    // back to A before returning to the page
    go("passport");
    expect(screen.queryByTestId("passport-report")).toBeNull();
    expect((screen.getByLabelText("Original file path") as HTMLInputElement).value).toBe("");
  });

  it("a build and its check still running when the project changes off-page cannot land afterwards", async () => {
    render(<Shell />);
    await prepareThroughCreative(PROJECT_A, COPY_A, "bracket_SnapmakerU1.3mf");
    go("passport"); fireEvent.click(screen.getByText("Use this job's files"));
    let releaseCheck!: () => void;
    verifyGates.push(new Promise<void>((resolve) => { releaseCheck = resolve; }));
    fireEvent.click(screen.getByText("Build passport"));
    await waitFor(() => expect(calls.some((c) => c.path === "/passport/verify")).toBe(true));
    go("recovery");
    act(() => { useSession.getState().setFile(PROJECT_B); });
    act(() => { useSession.getState().setFile(PROJECT_A); });
    await act(async () => { releaseCheck(); await new Promise((r) => setTimeout(r, 30)); });
    go("passport");
    expect(screen.queryByTestId("passport-report")).toBeNull();
  });
});
