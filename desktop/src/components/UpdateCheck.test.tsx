import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({
  checkForUpdate: vi.fn(),
  getUpdateCheckPref: vi.fn().mockResolvedValue({ auto_check: false, last_checked_at_unix: null }),
  setAutoCheckUpdates: vi.fn().mockResolvedValue(undefined),
  maybeAutoCheckUpdate: vi.fn().mockResolvedValue(null),
}));

import { UpdateCheck } from "./UpdateCheck";

describe("UpdateCheck", () => {
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
