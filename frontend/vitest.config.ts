// P-9 — the frontend unit runner (owner sign-off: the P-9 brief asks
// for vitest). Unit tests live next to the module they pin, as
// `src/**/*.test.ts`. The Playwright suites under `tests/` are NOT
// vitest files and are excluded here, or vitest would try to run them.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    exclude: ["tests/**", "node_modules/**", "dist/**"],
    environment: "node",
  },
});
