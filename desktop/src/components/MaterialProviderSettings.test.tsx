// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MaterialProviderSettings from "./MaterialProviderSettings";
import { providerTest } from "@/api";
import { useProvider } from "@/store/provider";

vi.mock("@/api", async () => {
  const actual = await vi.importActual<typeof import("@/api")>("@/api");
  return { ...actual, providerTest: vi.fn().mockResolvedValue({ ok: true, spools: 3, with_weight: 2, choices: [] }) };
});

const providerTestMock = vi.mocked(providerTest);
const sessionCopy = "Kept in memory for this session only. You will enter it again after restarting Studio. SpoolEase shows a new key each time it restarts unless you set a fixed key in its settings.";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("MaterialProviderSettings SpoolEase", () => {
  beforeEach(() => { useProvider.getState().clear(); window.localStorage.clear(); });

  function click(name: string) {
    act(() => { fireEvent.click(screen.getByRole("button", { name })); });
  }
  function change(element: HTMLElement, value: string) {
    act(() => { fireEvent.change(element, { target: { value } }); });
  }
  function selectSpoolEase() {
    click("SpoolEase");
    const url = screen.getByPlaceholderText("192.168.1.50");
    change(url, "192.168.1.50");
    return { url, key: screen.getByLabelText("Security key") as HTMLInputElement };
  }
  async function pressTest() {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Test connection" })); });
  }

  it("renders the exact session-only copy only for SpoolEase", () => {
    render(<MaterialProviderSettings />);
    expect(screen.queryByText(sessionCopy)).toBeNull();
    click("SpoolEase");
    expect(screen.getByText(sessionCopy)).toBeTruthy();
    click("Spoolman");
    expect(screen.queryByText(sessionCopy)).toBeNull();
  });

  it("F-M2a clears a committed key when switching providers and sends no empty key", async () => {
    render(<MaterialProviderSettings />);
    const { key } = selectSpoolEase();
    change(key, "committed-key");
    act(() => { fireEvent.blur(key); });
    expect(useProvider.getState().key).toBe("committed-key");
    click("Spoolman");
    click("SpoolEase");
    expect(useProvider.getState().key).toBe("");
    expect((screen.getByLabelText("Security key") as HTMLInputElement).value).toBe("");
    change(screen.getByPlaceholderText("192.168.1.50"), "192.168.1.50");
    await pressTest();
    expect(providerTestMock).toHaveBeenCalledWith("192.168.1.50", "spoolease", undefined);
  });

  it("F-M2b discards an uncommitted draft when switching providers", () => {
    render(<MaterialProviderSettings />);
    const { key } = selectSpoolEase();
    change(key, "draft-only");
    click("Spoolman");
    click("SpoolEase");
    expect((screen.getByLabelText("Security key") as HTMLInputElement).value).toBe("");
  });

  it("F-M2c clears then reselects SpoolEase without a key", async () => {
    render(<MaterialProviderSettings />);
    const { key } = selectSpoolEase();
    change(key, "draft-only");
    act(() => { useProvider.getState().clear(); });
    expect(screen.queryByLabelText("Security key")).toBeNull();
    click("SpoolEase");
    change(screen.getByPlaceholderText("192.168.1.50"), "192.168.1.50");
    expect((screen.getByLabelText("Security key") as HTMLInputElement).value).toBe("");
    await pressTest();
    expect(providerTestMock).toHaveBeenCalledWith("192.168.1.50", "spoolease", undefined);
  });

  it("F-M2d restores the provider configuration but never the key on remount", () => {
    useProvider.getState().setKind("spoolease");
    useProvider.getState().setUrl("192.168.1.50");
    useProvider.getState().setKey("abc");
    const firstMount = render(<MaterialProviderSettings />);
    firstMount.unmount();
    const { unmount } = render(<MaterialProviderSettings />);
    const key = screen.getByLabelText("Security key") as HTMLInputElement;
    expect(key.value).toBe("abc");
    expect(key.type).toBe("password");
    expect([...Array(window.localStorage.length)].every((_, i) => {
      const storageKey = window.localStorage.key(i)!;
      return !storageKey.includes("abc") && !window.localStorage.getItem(storageKey)!.includes("abc");
    })).toBe(true);
    unmount();
  });

  it("discards a stale success after the URL changes and re-enables Test", async () => {
    let resolveA!: (value: unknown) => void;
    providerTestMock.mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }) as never);
    render(<MaterialProviderSettings />);
    const { url } = selectSpoolEase();
    await pressTest();
    change(url, "192.168.1.51");
    await act(async () => { resolveA({ ok: true, spools: 1, with_weight: 1 }); });
    expect(screen.queryByText(/Connected\./)).toBeNull();
    expect((screen.getByRole("button", { name: "Test connection" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("discards a stale rejection after the URL changes", async () => {
    let rejectA!: (reason?: unknown) => void;
    providerTestMock.mockReturnValueOnce(new Promise((_, reject) => { rejectA = reject; }) as never);
    render(<MaterialProviderSettings />);
    const { url } = selectSpoolEase();
    await pressTest();
    change(url, "192.168.1.51");
    await act(async () => { rejectA(new Error("stale failure")); });
    expect(screen.queryByText("stale failure")).toBeNull();
  });

  it("keeps busy state owned by the superseding request", async () => {
    let resolveA!: (value: unknown) => void;
    let resolveB!: (value: unknown) => void;
    providerTestMock
      .mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }) as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveB = resolve; }) as never);
    render(<MaterialProviderSettings />);
    const { url } = selectSpoolEase();
    await pressTest();
    change(url, "192.168.1.51");
    await pressTest();
    await act(async () => { resolveA({ ok: true, spools: 1, with_weight: 1 }); });
    expect((screen.getByRole("button", { name: "Test connection" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { resolveB({ ok: true, spools: 2, with_weight: 1 }); });
    expect((screen.getByRole("button", { name: "Test connection" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows provider errors without exposing the key", async () => {
    providerTestMock.mockResolvedValueOnce({ ok: false, reason: "authentication failed", error_code: "authentication_failed", spools: 0, with_weight: 0 });
    render(<MaterialProviderSettings />);
    const { key } = selectSpoolEase();
    change(key, "super-secret-key");
    await pressTest();
    expect(screen.getByText("authentication failed")).toBeTruthy();
    expect(document.body.textContent).not.toContain("super-secret-key");
    for (const input of Array.from(document.querySelectorAll("input"))) {
      if (input !== key) expect(input.value).not.toContain("super-secret-key");
    }
  });

  it("formats success without exposing the key", async () => {
    providerTestMock.mockResolvedValueOnce({ ok: true, spools: 4, with_weight: 3, choices: [] });
    render(<MaterialProviderSettings />);
    const { key } = selectSpoolEase();
    change(key, "success-secret");
    await pressTest();
    expect(screen.getByText("Connected. 4 spools. 3 with usable remaining weight.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("success-secret");
  });

  it("simulates relaunch with kind and URL persisted but key cleared", async () => {
    useProvider.getState().setKind("spoolease");
    useProvider.getState().setUrl("192.168.1.50");
    useProvider.getState().setKey("relaunch-secret");
    vi.resetModules();
    const fresh = await import("@/store/provider");
    expect(fresh.useProvider.getState().kind).toBe("spoolease");
    expect(fresh.useProvider.getState().url).toBe("192.168.1.50");
    expect(fresh.useProvider.getState().key).toBe("");
  });

  it("labels SpoolEase as a provider, never as tracked", () => {
    render(<MaterialProviderSettings />);
    expect(screen.getByRole("button", { name: "SpoolEase" })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/\btracked\b/i);
  });
});
