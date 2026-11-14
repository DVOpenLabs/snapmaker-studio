import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

// Pure-logic unit tests (no DOM): the plate-remap wizard + navigation IA.
// Node environment keeps it fast and dependency-light. The "@" alias mirrors
// vite.config so modules that import "@/lib/..." resolve under test too.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    // Let ?raw CSS imports through unstubbed so the remote-font guard reads the real stylesheet.
    css: { include: [/\.css(\?.*)?$/] },
  },
});
