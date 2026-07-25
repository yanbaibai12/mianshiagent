import { defineConfig, devices } from '@playwright/test'

const apiPort = process.env.E2E_API_PORT || '8002'
const webPort = process.env.E2E_WEB_PORT || '5177'
const pythonCommand = process.env.E2E_PYTHON || 'python'
const apiBaseURL = `http://127.0.0.1:${apiPort}`
const webBaseURL = `http://127.0.0.1:${webPort}`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: webBaseURL,
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command:
        `cd ../backend && ${pythonCommand} -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiBaseURL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DATABASE_URL: 'sqlite+aiosqlite:///./e2e_test.db',
        SECRET_KEY: 'e2e-secret-key-that-is-long-enough-123456',
        DEBUG: 'false',
        APP_ENV: 'local',
        AUTO_CREATE_DB: 'true',
        LLM_PROVIDER: 'local',
        LLM_ALLOW_FALLBACK: 'false',
        ADMIN_EMAILS: 'admin@example.com',
        PAYMENT_WEBHOOK_SECRET: 'e2e-webhook-secret',
        CORS_ALLOW_ORIGINS: JSON.stringify([webBaseURL, `http://localhost:${webPort}`]),
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      url: webBaseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        VITE_API_BASE_URL: apiBaseURL,
      },
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
