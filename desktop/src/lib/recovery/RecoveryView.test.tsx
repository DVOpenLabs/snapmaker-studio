import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { RecoveryView } from "./RecoveryView";

describe("RecoveryView monitoring port", () => {
  it("renders a configured port field with the default and browser range", () => {
    const html = renderToStaticMarkup(<RecoveryView />);
    expect(html).toContain('aria-label="Configured printer port"');
    expect(html).toContain('type="number"');
    expect(html).toContain('min="1"');
    expect(html).toContain('max="65535"');
    expect(html).toContain('value="7125"');
  });
});
