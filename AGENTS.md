# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NAGA is a fork of [Open WebUI](https://github.com/open-webui/open-webui) (v0.5.14), customized by NYU-ITS as a self-hosted AI platform. It adds NYU-specific features including a grant-writing assistant (`facilities` router), async file processing via Redis Queue, and OpenTelemetry integration for OpenShift Observe.

## Development Commands

### Frontend (SvelteKit + Vite)
```bash
npm install           # Install dependencies (Node 18–22 required)
npm run dev           # Start dev server (port 5173, proxies /api to :8080)
npm run build         # Production build → build/
npm run lint          # Lint all (ESLint + svelte-check + pylint)
npm run format        # Prettier format
npm run test:frontend # Vitest unit tests
npm run cy:open       # Cypress e2e
```

### Backend (FastAPI + Python 3.11/3.12)
```bash
pip install uv && uv pip install -r backend/requirements.txt
cd backend && uvicorn open_webui.main:app --port 8080 --host 0.0.0.0 --forwarded-allow-ips '*' --reload
# or: ./backend/dev.sh (sets CORS_ALLOW_ORIGIN=http://localhost:5173 automatically)
pytest backend/open_webui/test/   # Run backend tests
```

### Local Testing (Docker)
Use `docker-compose.local.yaml` for all local application testing — it spins up the full stack with PostgreSQL + pgvector:
```bash
docker compose -f docker-compose.local.yaml up        # Start
docker compose -f docker-compose.local.yaml up --build # Rebuild and start
docker compose -f docker-compose.local.yaml down       # Stop
```

The other compose files (`docker-compose.yaml`, `make install`, etc.) are for production/CI use — do not use them locally.

## Architecture

This is a monorepo: SvelteKit SPA frontend + FastAPI backend. The frontend builds to static files served by the Python app.

### Frontend (`src/`)
- `src/routes/` — SvelteKit file-based routing (chat, admin, auth, workspace, channel pages)
- `src/lib/components/` — UI components organized by domain (chat, admin, workspace, common, layout)
- `src/lib/apis/` — One module per backend resource (auths, chats, models, ollama, openai, files, knowledge, retrieval, etc.)
- `src/lib/stores/` — Global Svelte stores
- `src/lib/i18n/` — i18next localization
- `src/lib/pyodide/` — Python-in-browser (Pyodide) for code execution

### Backend (`backend/open_webui/`)
- **Entry point:** `main.py` — assembles FastAPI app, mounts Socket.IO ASGI, registers all routers
- `routers/` — FastAPI route handlers, one file per resource. NAGA additions: `facilities.py` (NYU grant-writing RAG endpoint)
- `models/` — SQLAlchemy ORM models
- `retrieval/` — RAG subsystem:
  - `vector/connector.py` — selects active vector DB (ChromaDB default, pgvector, Milvus, Qdrant, OpenSearch)
  - `vector/dbs/` — Vector DB connector implementations
  - `loaders/` — Document loaders (PDF, DOCX, etc.)
  - `web/` — Web search backends (Tavily, Brave, Bing, DuckDuckGo, etc.)
- `workers/` — **NAGA custom:** RQ (Redis Queue) async file processor (`file_processor.py`). Enabled via `ENABLE_JOB_QUEUE=true`
- `socket/main.py` — Socket.IO server; supports Redis manager for horizontal scaling
- `storage/provider.py` — Pluggable file storage: Local, S3, GCS, Azure Blob
- `migrations/` — Alembic migrations (run automatically on startup)
- `config.py` — All configuration, driven entirely by environment variables
- `utils/` — Auth (JWT), audit logging, OpenTelemetry instrumentation

### Database
- **Primary DB:** SQLAlchemy ORM; SQLite by default, PostgreSQL in production (`DATABASE_URL` env var)
- **Vector DB:** ChromaDB by default; switched via `VECTOR_DB` env var
- **WebSocket/Queue state:** Redis (optional; required for RQ worker and horizontal Socket.IO scaling)

## NAGA-Specific Customizations

| Feature | Location | Activation |
|---|---|---|
| Grant-writing assistant | `routers/facilities.py` | Always on |
| Async file processing | `workers/file_processor.py` | `ENABLE_JOB_QUEUE=true` |
| OpenTelemetry | `utils/` + `main.py` | `OTEL_ENABLED=true` |
| NYU timezone | `main.py` | Hardcoded `America/New_York` |

## Key Setup Requirements

1. Copy `.env.example` to `.env` before starting — backend reads it automatically via `env.py`
2. Pyodide assets are downloaded automatically during `npm run dev` or `npm run build`
3. For local full-stack dev: backend must run on port 8080; Vite proxies `/api` to it
4. The `facilities` router uses Tavily for web search — requires `TAVILY_API_KEY` in env
5. Python 3.13+ is explicitly unsupported (enforced in `pyproject.toml`)
