// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({ detectOrca: vi.fn(), openInOrca: vi.fn() }));
vi.mock("@/components/EcosystemPanel", () => ({ EcosystemPanel: () => null }));
vi.mock("@/components/FidelityCard", () => ({ FidelityCard: () => null }));
vi.mock("@/components/FixLedgerCard", () => ({ FixLedgerCard: () => null }));

import * as api from "@/api";
import { OrcaHandoff } from "@/components/OrcaHandoff";

const PATH = "C:\\work\\a-long-prepared-copy-name-with-many-parts-U1-v12.3mf";
const view = () => render(<MemoryRouter><OrcaHandoff outputPath={PATH} /></MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.detectOrca).mockResolvedValue("C:\\Orca\\orca.exe");
  vi.mocked(api.openInOrca).mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("the Orca handoff", () => {
  it("names the exact file it opens, whole, with the full path on hover", async () => {
    view();
    await act(async () => {});
    const target = screen.getByTestId("orca-target");
    expect(target.textContent).toBe("a-long-prepared-copy-name-with-many-parts-U1-v12.3mf");
    expect(target.getAttribute("title")).toBe(PATH);
    expect(target.className).toContain("break-all");
  });

  it("opens that file, and only that file", async () => {
    view();
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Open in Snapmaker Orca" })); });
    expect(api.openInOrca).toHaveBeenCalledTimes(1);
    expect(api.openInOrca).toHaveBeenCalledWith(PATH);
  });
});
