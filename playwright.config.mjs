import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  use: { baseURL: "http://127.0.0.1:8091", channel: "chrome" },
  webServer: {
    command:
      ".venv/bin/python -m uvicorn scout.app:create_app --factory --host 127.0.0.1 --port 8091",
    url: "http://127.0.0.1:8091",
    env: { SCOUT_DATA_DIR: "./test-results/browser-data" },
    reuseExistingServer: false,
  },
  workers: 1,
});
