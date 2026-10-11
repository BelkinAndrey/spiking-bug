import { defineConfig } from "vite";
export default defineConfig({
  root: "apps/environment",
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: { allow: ["../.."] },
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "../../dist/environment", emptyOutDir: true },
});
