// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- a fake local service over a fake disk: every call goes through the same extApi seam the real views use ------
const disk: Record<string, string | null> = {};
const calls: Array<{ path: string; body: any }> = [];
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
      const arts = body.passport.artifacts.map((a: any) => {
        const now = disk[body.paths[a.artifact_id]] ?? null;
        const bytes = now === null ? "missing" : now === a._content ? "same" : "changed";
        return { artifact_id: a.artifact_id, name: a.name, role: a.role, size_bytes: a.bytes.size_bytes, sha256: a.bytes.sha256, bytes,
          chain: bytes === "same" ? "intact" : "invalidated", reasons: [] };
      });
      return { verification: { passport_id: body.passport.passport_id, artifacts: arts, derivations: [], recipes_retained: [], material_mappings_retained: [], losses: [], note: "n",
        summary: { all_intact: arts.every((a: any) => a.bytes === "same"), intact: [], invalidated: [], unverified: [], declared_mismatch: [] } }, diagnostics: [] };
    }
    throw new Error(`unexpected call ${path}`);
  }),
}));
vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  jobCheck: vi.fn(async (entries: any[]) => ({ files: entries.map((e) => ({ role: e.role, status: "recorded", observed: { size_bytes: 1, sha256: hashOf(disk[e.path] ?? null) } })) })),
}));
// Creative's prepare goes through its own client; the report/preview panels are presentation only here.
let nextPrepare: any = null;
vi.mock("@/lib/creativeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/creativeApi")>()),
  fetchCreativeFormats: vi.fn(async () => ({ formats: [] })),
  inspectCreative: vi.fn(async () => ({ origin: { status: "detected" } })),
  prepareCreative: vi.fn(async () => nextPrepare),
}));
vi.mock("@/components/creative/CreativeReportView", () => ({ default: () => <div>report</div> }));
vi.mock("@/components/creative/CreativePreparePanel", () => ({ default: () => <div>prepare-panel</div> }));
vi.mock("@/components/creative/CreativeFormatChooser", () => ({ default: () => <div>chooser</div> }));

import CreativeView from "@/components/creative/CreativeView";
import PassportView from "@/lib/passport/PassportView";
import { usePassportSession } from "@/lib/passport/session";
import { RecoveryView } from "@/lib/recovery/RecoveryView";
import { __resetRecoverySubscriberForTests } from "@/lib/recovery/subscriber";
import { useJob } from "@/store/job";

const PROJECT_A = "C:/work/bracket.3mf", COPY_A = "C:/studio/creative-prepared/bracket_SnapmakerU1.3mf";
const PROJECT_B = "C:/work/vase.3mf", COPY_B = "C:/studio/creative-prepared/vase_SnapmakerU1.3mf";

const done = (name: string, local_path: string) => ({
  prepared: true, origin: { generator: "kromacut", status: "detected", candidates: [] },
  output: { name, local_path, location: "studio_default", location_label: "Studio's creative-prepared folder", in_source_folder: false },
  prepare: { mode: "preserve", validated_ok: true, errors: [], compat_changed: [], mapped_to_u1: [], could_not_carry: [], warnings: [] },
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
async function prepareThroughCreative(project: string, copy: string, copyName: string) {
  go("creative");
  type("Project file path", project);
  fireEvent.click(screen.getByText("Inspect project"));
  await screen.findByLabelText("Prepare a U1 copy");
  nextPrepare = done(copyName, copy);
  fireEvent.click(screen.getByRole("button", { name: "Prepare a U1 copy" }));
  await screen.findByText("prepare-panel");
  await waitFor(() => expect(useJob.getState().record?.prepared?.path).toBe(copy));
}
const refreshPreview = async () => { fireEvent.click(screen.getByText("Refresh restore preview")); await waitFor(() => expect((screen.getByRole("button", { name: "Checkpoint this workspace" }) as HTMLButtonElement).disabled).toBe(false)); };

beforeEach(() => {
  for (const k of Object.keys(disk)) delete disk[k];
  Object.assign(disk, { [PROJECT_A]: "a-original", [COPY_A]: "a-copy", [PROJECT_B]: "b-original", [COPY_B]: "b-copy" });
  calls.length = 0; Object.assign(svc, { revision: 0, tracked: [], failCheckpoint: false });
  window.localStorage.clear(); useJob.getState().forget(); usePassportSession.getState().resetForTests(); __resetRecoverySubscriberForTests();
});
afterEach(cleanup);

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
    expect(screen.getByTestId("passport-stale").textContent).toContain("describes the earlier files");
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
});
