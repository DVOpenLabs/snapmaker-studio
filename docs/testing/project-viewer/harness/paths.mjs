// Where things are. No dependencies, so the collect and table scripts can use it without playwright installed.
import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// The repository root, found from this file (docs/testing/project-viewer/harness/).
export const REPO = fileURLToPath(new URL("../../../../", import.meta.url)).replace(/[\\/]$/, "");
export const OUT_DIR = process.env.P3B_OUT ?? join(tmpdir(), "p3b-out");
export const FIXTURES = process.env.P3B_FIXTURES ?? join(tmpdir(), "p3b-fixtures");
mkdirSync(OUT_DIR, { recursive: true });
