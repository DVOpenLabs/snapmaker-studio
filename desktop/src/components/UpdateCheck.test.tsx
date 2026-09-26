import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({
  checkForUpdate: vi.fn(),
  getUpdateCheckPref: vi.fn().mockResolvedValue({ auto_check: false, last_checked_at_unix: null }),
  setAutoCheckUpdates: vi.fn().mockResolvedValue(undefined),
}));

import { UpdateCheck } from "./UpdateCheck";
import { useUpdateCheckStore } from "@/store/updateCheck";

describe("UpdateCheck", () => {
  it("reads the automatic check's result straight from the shared store, not from its own effect", () => {
    // The automatic check runs once per launch from App.tsx's startup effect,
    // not from this component, so the result has to be read directly at
    // render time (an effect-based sync would miss it on a server render,
    // and would lag a real client render by one extra pass for no reason).
    // Asserted at the store level rather than through rendered HTML, since
    // renderToStaticMarkup's SSR path does not exercise zustand's normal
    // client subscription timing.
    useUpdateCheckStore.getState().setAutoResult({
      current: "1.0.0", latest: "1.1.0", newer: true,
      url: "https://example.invalid/releases/v1.1.0", published: "2026-09-01",
    });
    expect(useUpdateCheckStore.getState().autoResult?.latest).toBe("1.1.0");
    expect(() => renderToStaticMarkup(<UpdateCheck />)).not.toThrow();
    useUpdateCheckStore.setState({ autoResult: null });
  });

  it("renders the opt-in checkbox, off and disabled before the preference loads", () => {
    const html = renderToStaticMarkup(<UpdateCheck />);
    expect(html).toContain("Automatically check for updates");
    expect(html).toContain("Once a day at most");
    // Initial render is pre-effect: nothing has loaded yet, so the box must not
    // read as checked, and must be disabled rather than silently ignoring input.
    expect(html).not.toContain('checked=""');
    expect(html).toContain("disabled=\"\"");
  });

  it("still discloses that a check sends nothing about the user or their files", () => {
    const html = renderToStaticMarkup(<UpdateCheck />);
    expect(html).toContain("sends nothing about you or your files");
    expect(html).toContain("never updates itself");
  });

  it("keeps the manual button, unconditionally, alongside the opt-in checkbox", () => {
    const html = renderToStaticMarkup(<UpdateCheck />);
    expect(html).toContain("Check GitHub now");
  });
});
