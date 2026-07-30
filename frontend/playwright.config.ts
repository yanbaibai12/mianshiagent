import { defineConfig, devices } from '@playwright/test'

const apiPort = process.env.E2E_API_PORT || '8002'
const webPort = process.env.E2E_WEB_PORT || '5177'
const pythonCommand = process.env.E2E_PYTHON || 'python'
const apiBaseURL = `http://127.0.0.1:${apiPort}`
const webBaseURL = `http://127.0.0.1:${webPort}`
const e2eDbName = process.env.E2E_DB_NAME || `e2e_test_${Date.now()}.db`
const webCommand = process.env.E2E_WEB_COMMAND || `npm run dev -- --host 127.0.0.1 --port ${webPort}`
const taskQueueBackend = process.env.E2E_TASK_QUEUE_BACKEND || 'local'
const taskQueueName = process.env.E2E_TASK_QUEUE_NAME || `mianshiagent_e2e_${Date.now()}`
const quoteCommand = (command: string) =>
  command.includes(' ') && !command.startsWith('"') ? `"${command}"` : command

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
      command: `cd ../backend && ${quoteCommand(pythonCommand)} scripts/e2e_server.py --api-port ${apiPort}`,
      url: `${apiBaseURL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite+aiosqlite:///./${e2eDbName}`,
        SECRET_KEY: 'e2e-secret-key-that-is-long-enough-123456',
        DEBUG: 'false',
        APP_ENV: 'local',
        AUTO_CREATE_DB: 'true',
        LLM_PROVIDER: 'local',
        LLM_ALLOW_FALLBACK: 'false',
        ADMIN_EMAILS: 'admin@example.com',
        PAYMENT_WEBHOOK_SECRET: 'e2e-webhook-secret',
        CORS_ALLOW_ORIGINS: JSON.stringify([webBaseURL, `http://localhost:${webPort}`]),
        VECTOR_STORE_BACKEND: 'keyword',
        QDRANT_SYNC_ON_STARTUP: 'false',
        EMBEDDING_PROVIDER: 'hash',
        RERANK_PROVIDER: 'none',
        TASK_QUEUE_BACKEND: taskQueueBackend,
        TASK_ALLOW_LOCAL_FALLBACK: taskQueueBackend === 'local' ? 'true' : 'false',
        TASK_REDIS_URL: process.env.E2E_TASK_REDIS_URL || 'redis://127.0.0.1:6379/0',
        TASK_QUEUE_NAME: taskQueueName,
      },
    },
    {
      command: webCommand,
      url: webBaseURL,
      reuseExistingServer: false,
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
