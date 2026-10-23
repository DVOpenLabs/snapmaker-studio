import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PlacementCheck } from "@/api";
import { PlacementView } from "./PlacementCard";

const NOTE = "Each plate fits on its own, but Studio cannot check where the plates sit. In our test with a two-plate project made for a larger-bed printer, Snapmaker Orca listed one object as Outside and would not slice until it was moved by hand; Arrange all plates did not fix that in our test. Review the project in Snapmaker Orca before slicing.";

const check = (over: Partial<PlacementCheck> = {}): PlacementCheck => ({
  schema_version: "placement/1", available: true, items: [], off_plate: [], fixable: false,
  item_count: 2, plate_count: 1, ...over,
});

const render = (c: PlacementCheck) =>
  renderToStaticMarkup(<PlacementView check={c} fix={null} fixing={false} onFix={() => {}} />);

describe("PlacementCard", () => {
  it("never says every object is inside for a multi-plate project", () => {
    const html = render(check({ plate_count: 2, placement_established: false, summary: NOTE }));
    expect(html).toContain("Each plate fits on its own, but Studio cannot check where the plates sit.");
    expect(html).toContain("Arrange all plates did not fix that in our test");
    expect(html).not.toContain("use Arrange all plates");
    expect(html).not.toContain("Every object sits inside");
    expect(html).not.toContain("text-ready");   // no green check
  });

  it("still passes a single-plate project that is on the plate", () => {
    const html = render(check());
    expect(html).toContain("Every object sits inside the U1&#x27;s printable area.");
    expect(html).toContain("text-ready");
  });

  it("looks finished, not loading, when the check came back unable to judge", () => {
    const html = render(check({ available: false, reason: "This file could not be read." }));
    expect(html).toContain("This file could not be read.");
    expect(html).not.toContain("animate-spin");
  });

  it("looks loading only while there is no answer yet", () => {
    const html = renderToStaticMarkup(<PlacementView check={null} fix={null} fixing={false} onFix={() => {}} />);
    expect(html).toContain("animate-spin");
  });
});
