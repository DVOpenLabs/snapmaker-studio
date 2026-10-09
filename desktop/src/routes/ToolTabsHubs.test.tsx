// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The four panels call the engine on mount. Stubs keep this a test of the tab wiring only.
vi.mock("@/routes/Compatibility", () => ({ default: () => <h2>Compatibility panel</h2> }));
vi.mock("@/routes/SourceCompatibility", () => ({ default: () => <h2>Source Check panel</h2> }));
vi.mock("@/routes/PrintQuality", () => ({ default: () => <h2>Print Quality panel</h2> }));
vi.mock("@/routes/FirstLayer", () => ({ default: () => <h2>First Layer panel</h2> }));

import CompatibilityHub from "./CompatibilityHub";
import PrintQualityHub from "./PrintQualityHub";

afterEach(cleanup);

describe("tool hubs", () => {
  it("Compatibility has an accessible tab row with its two tabs", () => {
    render(<CompatibilityHub />);
    expect(screen.getByRole("tablist", { name: "Compatibility tools" })).toBeTruthy();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Compatibility", "Source Check"]);
    expect(screen.queryByText("Compatibility panel")).not.toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Source Check" }));
    expect(screen.queryByText("Source Check panel")).not.toBeNull();
    expect(screen.queryByText("Compatibility panel")).toBeNull();
  });

  it("Print Quality has an accessible tab row with its two tabs", () => {
    render(<PrintQualityHub />);
    expect(screen.getByRole("tablist", { name: "Print quality tools" })).toBeTruthy();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Print Quality", "First Layer"]);
    fireEvent.click(screen.getByRole("tab", { name: "First Layer" }));
    expect(screen.queryByText("First Layer panel")).not.toBeNull();
  });
});
