import { describe, expect, it } from "vitest";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import * as fs from "node:fs";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import { dirname, resolve } from "node:path";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const backendFixtures = resolve(repoRoot, "backend/tests/foundation/fixtures");
const desktopFixtures = resolve(dirname(fileURLToPath(import.meta.url)), "__fixtures__/foundation");
const fixtureNames = [
  "topology.json",
  "material_view.json",
  "observation.json",
  "artifact_ref.json",
  "derivation.json",
  "virtual_recipe.json",
  "capability_set.json",
];

describe("desktop foundation fixture copies", () => {
  it.skipIf(!fs.existsSync(backendFixtures))(
    `match backend fixtures byte-for-byte (skipped: ${backendFixtures} is absent)`,
    () => {
      for (const filename of fixtureNames) {
        expect(fs.readFileSync(resolve(desktopFixtures, filename)), filename)
          .toEqual(fs.readFileSync(resolve(backendFixtures, filename)));
      }
    },
  );
});
