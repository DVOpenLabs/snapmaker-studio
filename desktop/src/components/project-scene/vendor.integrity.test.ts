/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// Checks the vendored SlicerX tree against its own record (vendor/slicerx/UPDATING.md): verbatim files are byte-for-byte
// upstream, the seven patched files differ from upstream ONLY by the import path and the modification notice, every sha256
// in the table is current, and no other file carries a notice. Needs no network: the upstream blob ids are in the table.
const raw = import.meta.glob(
  ["../../vendor/slicerx/viewport/*.ts", "../../vendor/slicerx/contracts/*.ts", "../../vendor/slicerx/LICENSE-APACHE", "../../vendor/slicerx/NOTICE", "../../vendor/slicerx/UPDATING.md"],
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

const base = (p: string) => new URL(p, "file:///src/components/project-scene/").pathname.replace(/^\/src\/vendor\/slicerx\//, "");
const files: Record<string, string> = Object.fromEntries(Object.entries(raw).map(([k, v]) => [base(k), v]));

const hex = (buf: ArrayBuffer) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
const digest = async (algo: string, data: Uint8Array) => hex(await crypto.subtle.digest(algo, data as unknown as ArrayBuffer));
const bytes = (s: string) => new TextEncoder().encode(s);
async function gitBlob(text: string): Promise<string> {
  const body = bytes(text);
  const head = bytes(`blob ${body.length}\0`);
  const all = new Uint8Array(head.length + body.length);
  all.set(head, 0);
  all.set(body, head.length);
  return digest("SHA-1", all);
}

const PATCHED = ["palette", "stage", "summary", "toolchanger", "toolpaths", "types", "viewport"].map((n) => `viewport/${n}.ts`);
const NOTICE_START = "// MODIFIED BY SNAPMAKER STUDIO (DVOpenLabs/snapmaker-studio)";
const RULE = "// " + "-".repeat(111);
const NOTICE_BLOCK = [
  RULE,
  "// MODIFIED BY SNAPMAKER STUDIO (DVOpenLabs/snapmaker-studio): the only change in this file is the import path of the",
  "// contracts module ('@slicerx/contracts' -> '../contracts/index'). Upstream: slicerx-oss/slicerx @",
  "// edb521fe41306dd60d01bda8a0f6bf8aa54fcb29 (Apache-2.0). See ../UPDATING.md.",
  RULE,
  "",
].join("\n");

type Row = { file: string; blob: string; sha: string; status: string };
const rows: Row[] = [...files["UPDATING.md"].matchAll(/^\| `([^`]+)` \| `[^`]+` \| ([0-9a-f]{12}) \| ([0-9a-f]{12}) \| (.*) \|$/gm)]
  .map((m) => ({ file: m[1], blob: m[2], sha: m[3], status: m[4] }));

describe("vendored SlicerX tree", () => {
  it("has a table row for every vendored file and no row for a missing one", () => {
    const vendored = Object.keys(files).filter((k) => k !== "UPDATING.md" && k !== "contracts/index.ts").sort(); // index.ts is Studio-authored
    expect(rows.map((r) => r.file).sort()).toEqual(vendored);
    expect(rows).toHaveLength(41);
  });

  it("every sha256 in the table is the file as stored", async () => {
    for (const r of rows) expect((await digest("SHA-256", bytes(files[r.file]))).slice(0, 12), r.file).toBe(r.sha);
  });

  it("verbatim files are byte-for-byte upstream", async () => {
    for (const r of rows.filter((x) => !PATCHED.includes(x.file))) {
      expect(r.status, r.file).toBe("verbatim");
      expect((await gitBlob(files[r.file])).slice(0, 12), r.file).toBe(r.blob);
    }
  });

  it("the seven patched files keep the upstream header, carry the notice after it, and differ from upstream only by import path and notice", async () => {
    for (const file of PATCHED) {
      const text = files[file];
      const row = rows.find((r) => r.file === file)!;
      expect(row.status, file).toContain("patched");
      const lines = text.split("\n");
      expect(lines[0], file).toBe("// SPDX-License-Identifier: Apache-2.0");
      expect(lines[1], file).toBe("// Copyright (C) 2026 The SlicerX contributors");
      const at = lines.findIndex((l) => l.startsWith(NOTICE_START));
      expect(at, file).toBeGreaterThan(2); // after the upstream header, not before it
      expect(text.split(NOTICE_START).length - 1, file).toBe(1);
      expect(text, file).toContain(NOTICE_BLOCK);
      // Undo the two documented changes and the result must be the upstream file.
      const restored = text.replace(NOTICE_BLOCK, "").split("'../contracts/index'").join("'@slicerx/contracts'");
      expect((await gitBlob(restored)).slice(0, 12), file).toBe(row.blob);
    }
  });

  it("no other vendored file carries a modification notice, and none still imports the unpublished package", () => {
    for (const [file, text] of Object.entries(files)) {
      if (file === "UPDATING.md" || PATCHED.includes(file)) continue;
      expect(text.includes("MODIFIED BY SNAPMAKER STUDIO"), file).toBe(false);
    }
    for (const file of PATCHED) expect(files[file].includes("from '@slicerx/contracts'"), file).toBe(false);
  });

  it("keeps the upstream license and notice text", () => {
    expect(files["LICENSE-APACHE"]).toContain("Apache License");
    expect(files["NOTICE"]).toContain("Made possible by SlicerX");
  });
});
