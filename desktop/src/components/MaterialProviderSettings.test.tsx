// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MaterialProviderSettings from "./MaterialProviderSettings";
import { useProvider } from "@/store/provider";

vi.mock("@/api", async () => {
  const actual = await vi.importActual<typeof import("@/api")>("@/api");
  return { ...actual, providerTest: vi.fn().mockResolvedValue({ ok: true, spools: 3, with_weight: 2, choices: [] }) };
});

afterEach(cleanup);

describe("MaterialProviderSettings SpoolEase", () => {
  beforeEach(() => {
    useProvider.getState().clear();
    window.localStorage.clear();
  });

  it("shows the masked session-only key and sends safe facts", async () => {
    render(<MaterialProviderSettings />);
    fireEvent.click(screen.getByRole("button", { name: "SpoolEase" }));
    const key = screen.getByLabelText("Security key") as HTMLInputElement;
    expect(key.type).toBe("password");
    fireEvent.change(key, { target: { value: "session-key" } });
    expect(useProvider.getState().key).toBe("");
    fireEvent.blur(key);
    expect(useProvider.getState().key).toBe("session-key");
    expect([...Array(window.localStorage.length)].some((_, i) => window.localStorage.getItem(window.localStorage.key(i)!)?.includes("session-key"))).toBe(false);
  });

  it("clears a draft when clear resets the provider", () => {
    render(<MaterialProviderSettings />);
    fireEvent.click(screen.getByRole("button", { name: "SpoolEase" }));
    const key = screen.getByLabelText("Security key");
    fireEvent.change(key, { target: { value: "draft-only" } });
    act(() => {
      useProvider.getState().clear();
    });
    expect((screen.queryByLabelText("Security key") as HTMLInputElement | null)).toBeNull();
  });
});
