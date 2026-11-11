import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 35_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: '../../../temp/doc/validation/browser/results',
  use: {
    baseURL: 'http://127.0.0.1:8765',
    viewport: { width: 1440, height: 1000 },
    locale: 'en-US',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command:
      process.platform === 'win32'
        ? '..\\..\\.venv\\Scripts\\python.exe ..\\..\\tests\\e2e_server.py'
        : '../../.venv/bin/python ../../tests/e2e_server.py',
    url: 'http://127.0.0.1:8765/healthz',
    reuseExistingServer: false,
    timeout: 25_000,
  },
});
