// @vitest-environment jsdom
import { render, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ProviderStatusNote from "./ProviderStatusNote";

describe("ProviderStatusNote", () => {
  it("explains an unavailable provider", () => {
    const { container } = render(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: false, error: "key missing", error_code: "key_missing", spools: 0, with_weight: 0 }} />);
    const scoped = within(container);
    expect(scoped.getByText(/Studio could not read SpoolEase: key missing/)).toBeTruthy();
    expect(scoped.getByText(/Spool weights from SpoolEase are unknown until it answers/)).toBeTruthy();
  });

  it("renders nothing for an available or absent status", () => {
    const { container, rerender } = render(<ProviderStatusNote status={null} />);
    expect(container.firstChild).toBeNull();
    rerender(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: true, error: null, error_code: null, spools: 1, with_weight: 1 }} />);
    expect(container.firstChild).toBeNull();
  });

  it("falls back to a plain sentence when the error is null", () => {
    const { container } = render(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: false, error: null, error_code: null, spools: 0, with_weight: 0 }} />);
    const scoped = within(container);
    expect(scoped.getByText(/Studio could not read SpoolEase: SpoolEase did not answer\./)).toBeTruthy();
    expect(scoped.getByText(/Spool weights from SpoolEase are unknown until it answers/)).toBeTruthy();
  });

  it("adds a full stop when the error text lacks one", () => {
    const { container } = render(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: false, error: "device offline", error_code: "transport", spools: 0, with_weight: 0 }} />);
    const scoped = within(container);
    expect(scoped.getByText(/Studio could not read SpoolEase: device offline\. Spool weights from SpoolEase are unknown until it answers/)).toBeTruthy();
  });

  it("does not double a full stop when the error text already ends with one", () => {
    const { container } = render(<ProviderStatusNote status={{ provider: "spoolease", name: "SpoolEase", available: false, error: "The connection failed.", error_code: "transport", spools: 0, with_weight: 0 }} />);
    const scoped = within(container);
    expect(scoped.getByText(/Studio could not read SpoolEase: The connection failed\. Spool weights from SpoolEase are unknown until it answers/)).toBeTruthy();
    expect(scoped.queryByText(/failed\.\./)).toBeNull();
  });
});
