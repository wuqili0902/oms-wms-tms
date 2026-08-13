import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  timeout: 60000,
  fullyParallel: false,
  retries: 2,
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command: 'cmd /c "python e2e/init_db.py && uvicorn src.main:app --host 127.0.0.1 --port 8000"',
      url: 'http://127.0.0.1:8000/api/v1/health',
      timeout: 60000,
      reuseExistingServer: true,
      cwd: '../',
      env: {
        SECRET_KEY: 'e2e-test-secret-key-12345678',
        DATABASE_URL: 'sqlite+aiosqlite:///./e2e_test.db',
        DEBUG: 'true',
        CORS_ORIGINS: '["*"]',
        REDIS_URL: '',
        LOG_LEVEL: 'CRITICAL',
      },
    },
    {
      command: 'npm run dev',
      cwd: '../frontend',
      url: 'http://localhost:5173',
      timeout: 60000,
      reuseExistingServer: true,
    },
  ],
})
