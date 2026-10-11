import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests",
  testMatch: "*.spec.ts",
  workers: 1,
  use: { browserName: "chromium", viewport: { width: 1440, height: 1000 } },
  reporter: "list",
  webServer: [
    {
      command: `${process.env.CI ? "python" : ".venv/bin/python"} -m server.app --port 8010 --ephemeral`,
      url: "http://127.0.0.1:8010/api/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev:environment",
      url: "http://127.0.0.1:5183",
      env: { BUG_CLIENT_PORT: "5183", BUG_API_URL: "http://127.0.0.1:8010" },
      reuseExistingServer: false,
    },
    {
      command: "npm run dev:editor",
      url: "http://127.0.0.1:5184",
      env: { BUG_CLIENT_PORT: "5184", BUG_API_URL: "http://127.0.0.1:8010" },
      reuseExistingServer: false,
    },
  ],
});
