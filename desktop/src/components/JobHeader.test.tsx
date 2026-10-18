// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockResolvedValue({ port: 1, token: "t" }) }));
vi.mock("@/api", () => ({ doctor: vi.fn(), convert: vi.fn(), diff: vi.fn() }));

import { JobHeader } from "@/components/JobHeader";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const FILE = { path: "C:\\work\\Benchy.3mf", name: "Benchy.3mf", ext: "3mf" };
const doctorDone = (over: object = {}) => ({ status: "done" as const, data: { verdict: "READY", ...over }, error: null });
const idle = { status: "idle" as const, data: null, error: null };
const runDoctor = vi.fn();

const view = () => render(<MemoryRouter><JobHeader /></MemoryRouter>);
const steps = () => within(screen.getByRole("list", { name: "Job progress" })).getAllByRole("listitem");

beforeEach(() => {
  runDoctor.mockReset();
  useSession.setState({ file: FILE as any, doctor: doctorDone() as any, convert: idle as any, runDoctor: runDoctor as any });
  useSliced.setState({ path: null, name: null });
});
afterEach(cleanup);

describe("the job header", () => {
  it("renders nothing without a project", () => {
    useSession.setState({ file: null });
    expect(view().container.innerHTML).toBe("");
  });

  it("keeps the project's name in view, whole, with its path on hover", () => {
    const long = "a-very-long-project-name-with-many-parts-and-a-version-number-v12-final-final.3mf";
    useSession.setState({ file: { path: `C:\\work\\${long}`, name: long, ext: "3mf" } as any });
    view();
    const name = screen.getByRole("heading", { name: new RegExp(long.slice(0, 20)) }).querySelector("span")!;
    expect(name.textContent).toBe(long);
    expect(name.className).toContain("break-all");
    expect(name.getAttribute("title")).toBe(`C:\\work\\${long}`);
  });

  it("shows five action-named steps and marks exactly the current one", () => {
    view();
    expect(steps().map((s) => s.textContent?.replace(/:.*$/, "").trim())).toEqual(
      ["Open project", "Check", "Prepare copy", "Slice in Orca", "Compare slice"]);
    const current = steps().filter((s) => s.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toContain("Prepare copy");
  });

  it("a check with findings says so in words, not a bare tick", () => {
    useSession.setState({ doctor: doctorDone({ verdict: "REPAIRABLE" }) as any });
    view();
    expect(steps()[1].textContent).toContain("needs review");
  });

  it("offers one next action, and it is preparing, not an Orca handoff, before a copy exists", () => {
    view();
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Prepare a U1 copy");
    expect(within(status).getByRole("link", { name: /Prepare a copy/ }).getAttribute("href")).toBe("/workspace");
    expect(status.textContent).not.toMatch(/Orca/);
  });

  it("names the exact prepared copy once one is validated", () => {
    useSession.setState({ convert: { status: "done", error: null, data: { validated_ok: true, blocked: false, output_name: "Benchy_U1.3mf", output_path: "C:\\work\\Benchy_U1.3mf" } } as any });
    view();
    expect(screen.getByRole("status").textContent).toContain("Open Benchy_U1.3mf in Snapmaker Orca");
  });

  it("an unvalidated copy is not offered to Orca", () => {
    useSession.setState({ convert: { status: "done", error: null, data: { validated_ok: false, blocked: false, output_name: "x_U1.3mf" } } as any });
    view();
    expect(screen.getByRole("status").textContent).not.toMatch(/Open .* in Snapmaker Orca/);
    expect(screen.queryByRole("button", { name: "Go to the Orca step" })).toBeNull();
  });

  it("a failed check can be retried", () => {
    useSession.setState({ doctor: { status: "error", data: null, error: "x" } as any });
    view();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Check again" })); });
    expect(runDoctor).toHaveBeenCalledTimes(1);
  });

  it("does not offer a retry that would drop an in-flight prepare", () => {
    useSession.setState({ doctor: { status: "error", data: null, error: "x" } as any, convert: { status: "loading", data: null, error: null } as any });
    view();
    expect((screen.getByRole("button", { name: "Check again" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("while checking it says so and offers no button", () => {
    useSession.setState({ doctor: { status: "loading", data: null, error: null } as any });
    view();
    expect(screen.getByRole("status").textContent).toContain("Checking the project…");
    expect(within(screen.getByRole("status")).queryByRole("button")).toBeNull();
    expect(within(screen.getByRole("status")).queryByRole("link")).toBeNull();
  });

  it("with a slice open the next action is to compare it", () => {
    useSliced.setState({ path: "C:\\out\\Benchy.gcode", name: "Benchy.gcode" });
    view();
    expect(within(screen.getByRole("status")).getByRole("link", { name: /Compare slice/ }).getAttribute("href")).toBe("/after-slicing");
  });

  it("moves focus to the Orca step it points at", () => {
    useSession.setState({ convert: { status: "done", error: null, data: { validated_ok: true, blocked: false, output_name: "p.3mf" } } as any });
    render(<MemoryRouter><JobHeader /><section id="job-stage-prepared" tabIndex={-1}>prepared</section></MemoryRouter>);
    Element.prototype.scrollIntoView = vi.fn();
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Go to the Orca step" })); });
    expect(document.activeElement?.id).toBe("job-stage-prepared");
  });
});
