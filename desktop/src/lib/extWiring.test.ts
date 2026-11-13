import { describe, expect, it } from "vitest";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import * as fs from "node:fs";
// @ts-expect-error Node builtin is used at runtime; this checkout omits @types/node.
import { resolve } from "node:path";

describe("extension app wiring", () => {
  it("installs app lifecycle exactly once in App.tsx", () => {
    const appSource = fs.readFileSync(resolve((globalThis as any).process.cwd(), "src/App.tsx"), "utf8");
    const installCalls = appSource.match(/\binstallAppLifecycle\s*\(/g) ?? [];
    expect(installCalls).toHaveLength(1);
  });
});
