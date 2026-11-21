// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const spies = vi.hoisted(() => ({ generate: vi.fn(), check: vi.fn(), open: vi.fn(), setFile: vi.fn() }));
vi.mock("@/store/session", () => ({ useSession: { getState: () => ({ setFile: spies.setFile }) } }));
vi.mock("./luminaApi", async original => ({ ...await original<typeof import("./luminaApi")>(),
  fetchLuminaFormats: vi.fn(async () => ({ formats: [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }] })),
  checkLuminaService: spies.check, generateWithLumina: spies.generate, openGeneratedModel: spies.open,
}));
import LuminaView from "./LuminaView";
import { useLuminaSession } from "./session";
const result = { generated: true as const, file_name: "synthetic-model.3mf", sha256: "a".repeat(64), size_bytes: 10, kind: "3mf", generated_by: "Synthetic", location_label: "Synthetic folder", advisory: "Inspect", progress: "unknown" as const, cancel: "unknown" as const, evidence: "fixture-tested" };
function Shell() { const [here, setHere] = useState(true); return <MemoryRouter><button onClick={() => setHere(!here)}>Switch tool</button>{here ? <LuminaView /> : <p>Another tool</p>}</MemoryRouter>; }
beforeEach(() => { vi.clearAllMocks(); useLuminaSession.getState().clear(); });
afterEach(cleanup);
async function start() {
  await act(async () => render(<Shell />));
  for (const [label, value] of [["Service address", "http://127.0.0.1:8123"], ["Image file path", "synthetic.png"], ["LUT name", "Synthetic"], ["Output format", "3mf"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate" })));
}
it("retains a completion while another tool is open, without reissuing or auto-opening", async () => {
  let resolve!: (r: typeof result) => void; spies.generate.mockReturnValue(new Promise(r => { resolve = r; }));
  await start(); fireEvent.click(screen.getByText("Switch tool"));
  await act(async () => resolve(result));
  expect(spies.open).not.toHaveBeenCalled(); expect(spies.setFile).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Switch tool"));
  expect(await screen.findByRole("button", { name: "Open generated model in Studio" })).toBeTruthy();
  expect(spies.generate).toHaveBeenCalledTimes(1);
  expect((screen.getByLabelText("Image file path") as HTMLInputElement).value).toBe("synthetic.png");
});
it("serializes requests across unmount/remount, then preserves the completed result", async () => {
  let resolve!: (r: typeof result) => void; spies.generate.mockReturnValue(new Promise(r => { resolve = r; }));
  await start(); fireEvent.click(screen.getByText("Switch tool")); fireEvent.click(screen.getByText("Switch tool"));
  expect(screen.getByRole("button", { name: "Working..." }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Clear Lumina session" }).hasAttribute("disabled")).toBe(true);
  await useLuminaSession.getState().run("generate", [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }]);
  expect(spies.generate).toHaveBeenCalledTimes(1); await act(async () => resolve(result));
});
it("keeps the original output folder with a stale result and allows only explicit checked open", async () => {
  let resolve!: (r: typeof result) => void; spies.generate.mockReturnValue(new Promise(r => { resolve = r; }));
  await act(async () => render(<Shell />));
  await act(async () => { useLuminaSession.getState().change({ serviceUrl: "http://127.0.0.1:8123", imagePath: "synthetic.png", lutName: "Synthetic", format: "3mf", outDir: "synthetic-first" }); });
  await act(async () => { void useLuminaSession.getState().run("generate", [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }]); });
  fireEvent.change(screen.getByLabelText("Output folder"), { target: { value: "synthetic-second" } });
  await act(async () => resolve(result));
  expect(useLuminaSession.getState().result).toBeNull(); expect(spies.open).not.toHaveBeenCalled();
  spies.open.mockRejectedValue(new Error("Synthetic changed-file refusal"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open earlier generated model in Studio" })));
  expect(spies.open).toHaveBeenCalledWith(result, "synthetic-first"); expect(spies.setFile).not.toHaveBeenCalled();
});

it("archives an already completed result when inputs change and clear forgets memory only", async () => {
  const storage = vi.spyOn(Storage.prototype, "setItem"); spies.generate.mockResolvedValue(result);
  await start();
  fireEvent.change(screen.getByLabelText("LUT name"), { target: { value: "Another palette" } });
  expect(useLuminaSession.getState().result).toBeNull(); expect(useLuminaSession.getState().earlierFiles).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Open earlier generated model in Studio" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear Lumina session" }));
  expect(useLuminaSession.getState().earlierFiles).toHaveLength(0); expect(useLuminaSession.getState().form.imagePath).toBe("");
  expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
});
it("retains at most ten earlier results with stable distinct entry identities", async () => {
  spies.generate.mockResolvedValue(result);
  const formats = [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }];
  for (let i = 0; i < 12; i++) {
    useLuminaSession.getState().change({ serviceUrl: "http://127.0.0.1:8123", imagePath: `synthetic-${i}.png`, lutName: "Synthetic", format: "3mf" });
    await useLuminaSession.getState().run("generate", formats);
  }
  const history = useLuminaSession.getState().earlierFiles;
  expect(history).toHaveLength(10); expect(new Set(history.map(entry => entry.id)).size).toBe(10);
  expect(useLuminaSession.getState().result).toEqual(result);
});
it("retains a generation error after navigation without automatically retrying", async () => {
  let reject!: (error: Error) => void; spies.generate.mockReturnValue(new Promise((_, no) => { reject = no; }));
  await start(); fireEvent.click(screen.getByText("Switch tool"));
  await act(async () => reject(new Error("Synthetic generation refusal")));
  fireEvent.click(screen.getByText("Switch tool"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Synthetic generation refusal");
  expect(spies.generate).toHaveBeenCalledTimes(1);
});

it.each(["check", "generate"] as const)("archives success before a subsequent %s, including its failure", async kind => {
  spies.generate.mockResolvedValueOnce(result);
  await start();
  // The output belongs to the original generation, not a future form value.
  const directory = useLuminaSession.getState().resultDirectory;
  let reject!: (error: Error) => void;
  const pending = new Promise((_, no) => { reject = no; });
  (kind === "check" ? spies.check : spies.generate).mockReturnValueOnce(pending);
  let operation!: Promise<void>;
  await act(async () => { operation = useLuminaSession.getState().run(kind, [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }]); });
  const archived = useLuminaSession.getState().earlierFiles[0];
  expect(archived).toMatchObject({ result, outDir: directory });
  expect(screen.getByRole("button", { name: "Open earlier generated model in Studio" })).toBeTruthy();
  await act(async () => { reject(new Error("Synthetic subsequent refusal")); await operation; });
  expect(useLuminaSession.getState().earlierFiles[0]).toEqual(archived);
  expect(useLuminaSession.getState().error).toBe("Synthetic subsequent refusal");
  spies.open.mockRejectedValueOnce(new Error("Synthetic checked-open refusal"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open earlier generated model in Studio" })));
  expect(spies.open).toHaveBeenCalledWith(result, directory);
  expect(spies.setFile).not.toHaveBeenCalled();
});
it("repeated generation without edits keeps ten stable history entries with their original directories", async () => {
  spies.generate.mockResolvedValue(result);
  const form = { serviceUrl: "http://127.0.0.1:8123", imagePath: "synthetic.png", lutName: "Synthetic", format: "3mf", outDir: "synthetic-original" };
  useLuminaSession.getState().change(form);
  const formats = [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }];
  for (let i=0; i<12; i++) await useLuminaSession.getState().run("generate", formats);
  const entries = useLuminaSession.getState().earlierFiles;
  expect(entries).toHaveLength(10);
  expect(new Set(entries.map(entry => entry.id)).size).toBe(10);
  expect(entries.every(entry => entry.outDir === "synthetic-original")).toBe(true);
  await useLuminaSession.getState().run("generate", formats);
  expect(useLuminaSession.getState().earlierFiles.slice(0,9)).toEqual(entries.slice(1));
  expect(useLuminaSession.getState().result).toEqual(result);
});

it("a successful service check also retains the earlier generated model and original folder", async () => {
  spies.generate.mockResolvedValueOnce(result);
  useLuminaSession.getState().change({ serviceUrl: "http://127.0.0.1:8123", imagePath: "synthetic.png", lutName: "Synthetic", format: "3mf", outDir: "synthetic-original" });
  const formats = [{ kind: "3mf", meaning: "Synthetic", evidence: "fixture-tested" }];
  await useLuminaSession.getState().run("generate", formats);
  spies.check.mockResolvedValueOnce({ status: "ok", progress: "unknown", cancel: "unknown", evidence: "fixture-tested" });
  await useLuminaSession.getState().run("check", formats);
  expect(useLuminaSession.getState().status?.status).toBe("ok");
  expect(useLuminaSession.getState().earlierFiles).toMatchObject([{ result, outDir: "synthetic-original" }]);
  expect(useLuminaSession.getState().result).toBeNull();
});
