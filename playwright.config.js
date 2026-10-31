import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
    ignoreHTTPSErrors: true, // Only the generated loopback certificate in the test fixture.
  },
  webServer: [{
    command: "python -m http.server 4173 --directory portal",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 20_000,
  }, {
    command: "python tests/e2e/fiscal_http_server.py",
    url: "https://127.0.0.1:4174/",
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 20_000,
  }, {
    command: "NFCORE_E2E_PORT=4175 python tests/e2e/fiscal_http_server.py",
    url: "https://127.0.0.1:4175/",
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 20_000,
  }, {
    command: "NFCORE_E2E_TRIAL=1 NFCORE_E2E_PORT=4176 python tests/e2e/fiscal_http_server.py",
    url: "https://127.0.0.1:4176/__test/health",
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 30_000,
  }],
});
