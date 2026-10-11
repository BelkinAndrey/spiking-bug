import { defineConfig } from "vite";
export default defineConfig({
  root: "apps/editor",
  server: {
    host: "127.0.0.1",
    port: Number(process.env.BUG_CLIENT_PORT || 5174),
    strictPort: true,
    fs: { allow: ["../.."] },
    proxy: { "/api": process.env.BUG_API_URL || "http://127.0.0.1:8000" },
  },
  build: { outDir: "../../dist/editor", emptyOutDir: true },
});
