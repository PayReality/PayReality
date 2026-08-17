import { defineConfig } from "vite";
import path from "path";
import react from "@vitejs/plugin-react";

// Separate from vite.config.ts deliberately: that file carries Figma/Make
// build-only plugins (figma:asset/ resolution) that have nothing to do
// with running tests, and a comment marking it as managed by that
// tooling. This repo had no test runner at all before Milestone 14.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
