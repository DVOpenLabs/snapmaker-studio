// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ProviderStatusNote from "./ProviderStatusNote";

describe("ProviderStatusNote", () => {
  it("explains an unavailable provider", () => {
    render(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: false, error: "key missing", error_code: "key_missing", spools: 0, with_weight: 0 }} />);
    expect(screen.getByText(/Studio could not read SpoolEase: key missing/)).toBeTruthy();
    expect(screen.getByText(/Spool weights from SpoolEase are unknown until it answers/)).toBeTruthy();
  });

  it("renders nothing for an available or absent status", () => {
    const { container, rerender } = render(<ProviderStatusNote status={null} />);
    expect(container.firstChild).toBeNull();
    rerender(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: true, error: null, error_code: null, spools: 1, with_weight: 1 }} />);
    expect(container.firstChild).toBeNull();
  });
});
