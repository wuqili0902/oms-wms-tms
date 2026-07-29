# Project Conventions

## Monorepo Structure
- `frontend/` - Vue 3 + Element Plus SPA (Vite + TypeScript)
- `src/` - FastAPI backend (Python 3.10+)
- `tests/` - Backend tests (pytest)
- `.github/` - CI/CD

## Frontend Conventions
- Import alias `@/` maps to `frontend/src/`
- State management: Pinia
- HTTP client: Axios instance at `@/api/index.ts` with auto-refresh 401 interceptor
- Auth store: `@/stores/auth.ts` (login, logout, fetchMe, refreshAccessToken)
- Pagination: `usePagination()` composable from `@/composables/usePagination.ts`
- Routing: lazy-loaded components, `beforeEach` guard redirects to `/login` if unauth
- All list pages must have `<template #empty><el-empty description="暂无数据" /></template>` on `<el-table>`
- All list pages must have `v-loading` on every `<el-table>`
- API responses: backend uses FastAPI `response_model` (no ApiResponse wrapper). Read defensively: `res.data?.data ?? res.data`
- Forms: reset via `@closed` event on `<el-dialog>`
- Destructive actions: use `ElMessageBox.confirm` before executing

## Backend Conventions
- FastAPI with SQLAlchemy 2.0 async
- Auth: JWT via `python-jose` + OAuth2 password flow
- DB: asyncpg + SQLAlchemy async session
- Tests: pytest + pytest-asyncio + httpx AsyncClient
- All E2E tests in `tests/test_e2e/`

## Commands
```bash
# Frontend
cd frontend && npm run dev          # start dev server
cd frontend && npm run build        # production build
cd frontend && npm run test         # vitest
cd frontend && npm run typecheck    # vue-tsc type check

# Backend
cd src && uvicorn main:app --reload # start dev server
pytest tests/ -v                    # run all tests
pytest tests/test_e2e/ -v --tb=short  # E2E tests
```
