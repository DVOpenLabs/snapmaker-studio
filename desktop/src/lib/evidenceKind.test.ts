import { describe, expect, it } from "vitest";
import { evidenceKindLabel } from "./evidenceKind";

describe("evidence kind labels", () => {
  it.each([
    ["file", "Read from your file"], ["engine", "Studio's check"],
    ["estimate", "Estimate"], ["orca", "Verify in Snapmaker Orca"],
  ])("maps %s", (kind, label) => expect(evidenceKindLabel(kind)).toBe(label));
  it("does not invent a label for unknown evidence", () => expect(evidenceKindLabel("unknown")).toBeNull());
});
