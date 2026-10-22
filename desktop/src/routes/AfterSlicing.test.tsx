// @vitest-environment jsdom
import React, { useEffect } from "react";
import { act, cleanup, render as rtlRender, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({}));
vi.mock("@/components/JobWorkspaceCard", () => ({ JobWorkspaceCard: () => null }));
vi.mock("@/components/OrcaRoundTrip", () => ({ OrcaRoundTrip: () => null }));
vi.mock("@/components/SlicedJobCards", () => ({ SlicedJobCards: () => null }));

// Stands in for the real card: shows what AfterSlicing hands it and counts how often it is mounted.
const mounts = vi.fn();
vi.mock("@/components/SettingsReceiptCard", () => ({
  SettingsReceiptCard: (p: { original: string; prepared: string | null; sliced: string | null; revision?: number; preparedOmitted?: boolean; preparing?: boolean }) => {
    useEffect(() => { mounts(); }, []);
    return (
      <div data-testid="receipt">
        {JSON.stringify({ original: p.original, prepared: p.prepared, sliced: p.sliced, revision: p.revision, omitted: p.preparedOmitted, preparing: p.preparing })}
      </div>
    );
  },
}));

import AfterSlicing from "./AfterSlicing";
import { useJob } from "@/store/job";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";

const render = (ui: React.ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>);
const PROJECT = { path: "C:\p.3mf", name: "p.3mf", ext: "3mf" };
const done = (data: any) => ({ status: "done" as const, data, error: null });
const idleConvert = { status: "idle" as const, data: null, error: null };
const shown = () => JSON.parse(screen.getByTestId("receipt").textContent ?? "{}");

beforeEach(() => {
  mounts.mockClear();
  useSession.setState({ file: PROJECT as any, convert: idleConvert as any });
  useSliced.setState({ path: "C:\s.gcode", name: "s.gcode", revision: 0 });
  useJob.setState({ record: null });
});
afterEach(cleanup);

describe("After slicing: what the settings receipt is given", () => {
  it("passes a prepared copy that Studio wrote and validated this session", () => {
    useSession.setState({ convert: done({ blocked: false, validated_ok: true, output_path: "C:\prep.3mf" }) as any });
    render(<AfterSlicing />);
    expect(shown()).toMatchObject({ original: "C:\p.3mf", prepared: "C:\prep.3mf", sliced: "C:\s.gcode", omitted: false });
  });

  it("does not pass a prepared copy that did not validate", () => {
    useSession.setState({ convert: done({ blocked: false, validated_ok: false, output_path: "C:\prep.3mf" }) as any });
    render(<AfterSlicing />);
    expect(shown().prepared).toBeNull();
  });

  it("does not pass a prepared copy from a blocked preparation", () => {
    useSession.setState({ convert: done({ blocked: true, validated_ok: true, output_path: "C:\prep.3mf" }) as any });
    render(<AfterSlicing />);
    expect(shown().prepared).toBeNull();
  });

  it("does not pass a prepared copy while preparing or after an error", () => {
    useSession.setState({ convert: { status: "loading", data: null, error: null } as any });
    render(<AfterSlicing />);
    expect(shown().prepared).toBeNull();
  });

  it("says so when a restored job has a saved prepared copy that is not part of the comparison", () => {
    useJob.setState({ record: { schema: 1, savedAt: "t", original: { path: "C:\p.3mf" }, prepared: { path: "C:\prep.3mf", mode: "x" }, sliced: null } as any });
    render(<AfterSlicing />);
    expect(shown()).toMatchObject({ prepared: null, omitted: true });
  });

  it("does not call a saved prepared copy omitted while a new one is being made", () => {
    useJob.setState({ record: { schema: 1, savedAt: "t", original: { path: "C:p.3mf" }, prepared: { path: "C:prep.3mf", mode: "x" }, sliced: null } as any });
    useSession.setState({ convert: { status: "loading", data: null, error: null } as any });
    render(<AfterSlicing />);
    expect(shown()).toMatchObject({ prepared: null, omitted: false, preparing: true });
  });

  it("still discloses the omission when the new preparation failed", () => {
    useJob.setState({ record: { schema: 1, savedAt: "t", original: { path: "C:p.3mf" }, prepared: { path: "C:prep.3mf", mode: "x" }, sliced: null } as any });
    useSession.setState({ convert: { status: "error", data: null, error: "x" } as any });
    render(<AfterSlicing />);
    expect(shown()).toMatchObject({ omitted: true, preparing: false });
  });

  it("keeps printer connection, project compatibility, settings comparison and print readiness apart", () => {
    render(<AfterSlicing />);
    for (const name of ["Printer connection", "Project compatibility", "Settings comparison", "Print readiness"]) {
      expect(screen.getByText(name)).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: "Printer Hub" }).getAttribute("href")).toBe("/printers");
  });

  it("does not claim an omission when there is no saved prepared copy", () => {
    useJob.setState({ record: { schema: 1, savedAt: "t", original: { path: "C:\p.3mf" }, prepared: null, sliced: null } as any });
    render(<AfterSlicing />);
    expect(shown().omitted).toBe(false);
  });

  it("hands the card the slice revision and starts it afresh when Orca re-exports over the same path", () => {
    render(<AfterSlicing />);
    expect(mounts).toHaveBeenCalledTimes(1);
    expect(shown().revision).toBe(0);
    act(() => useSliced.getState().refresh());
    expect(mounts).toHaveBeenCalledTimes(2);          // remounted: the old answer is discarded
    expect(shown().revision).toBe(1);
  });
});
