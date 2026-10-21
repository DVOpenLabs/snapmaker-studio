import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 4312, token: "test" }) }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { useSession } from "./session";

describe("session conversion", () => {
  beforeEach(() => {
    vi.stubGlobal("location", { search: "" });
    useSession.setState({ file: { path: "C:/model.stl", name: "model.stl", ext: "stl" }, doctor: { status: "idle", data: null, error: null }, convert: { status: "idle", data: null, error: null }, preview: { status: "idle", data: null, error: null }, diff: { status: "idle", data: null, error: null }, prepareMode: "preserve", settingsSummary: null });
  });

  it("passes the chosen prepare mode to convert", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ output_path: "C:/out.3mf", output_name: "out.3mf", validated_ok: true, prepare_mode: "recommended", settings_summary: {} }) });
    vi.stubGlobal("fetch", fetchMock);
    await useSession.getState().runConvert("recommended");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ path: "C:/model.stl", prepare_mode: "recommended" });
  });

  it("never sends a known blocked project to Prepare or preview in either mode", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useSession.setState({ doctor: { status: "done", data: { prepare_blocked: true }, error: null } });
    await useSession.getState().runConvert("preserve");
    await useSession.getState().runConvert("recommended");
    await useSession.getState().previewConvert();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(useSession.getState().convert.status).toBe("idle");
    expect(useSession.getState().preview.status).toBe("idle");
  });

  it("defaults prepare mode to preserve", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ output_path: "C:/out.3mf", output_name: "out.3mf", validated_ok: true, prepare_mode: "preserve", settings_summary: {} }) });
    vi.stubGlobal("fetch", fetchMock);
    await useSession.getState().runConvert();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ prepare_mode: "preserve" });
  });

  it("keeps preview results separate from conversion results", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ output_path: "C:/preview.3mf", output_name: "preview.3mf", validated_ok: true, prepare_mode: "preserve", settings_summary: {} }) });
    vi.stubGlobal("fetch", fetchMock);
    await useSession.getState().previewConvert();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ prepare_mode: "preserve", dry_run: true });
    expect(useSession.getState().preview.status).toBe("done");
    expect(useSession.getState().convert).toMatchObject({ status: "idle", data: null });
  });

  it("clears file-specific settings when selecting another file", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    useSession.setState({ settingsSummary: {} as any, preview: { status: "done", data: {} as any, error: null } });
    useSession.getState().setFile("C:/other.3mf");
    expect(useSession.getState().settingsSummary).toBeNull();
    expect(useSession.getState().preview).toMatchObject({ status: "idle", data: null });
  });

  it("ignores a superseded conversion response", async () => {
    let resolveConvert!: (value: any) => void;
    const pendingConvert = new Promise((resolve) => { resolveConvert = resolve; });
    const fetchMock = vi.fn((url: string) => url.endsWith("/convert")
      ? pendingConvert
      : Promise.resolve({ ok: true, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    const conversion = useSession.getState().runConvert();
    useSession.getState().setFile("C:/other.3mf");
    resolveConvert({ ok: true, json: async () => ({ output_path: "C:/stale.3mf", output_name: "stale.3mf", validated_ok: true, prepare_mode: "preserve", settings_summary: {} }) });
    await conversion;
    expect(useSession.getState().file?.path).toBe("C:/other.3mf");
    expect(useSession.getState().convert).toMatchObject({ status: "idle", data: null });
  });
});
