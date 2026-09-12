# ---- frontend build (bun) ----
FROM oven/bun:1 AS frontend
WORKDIR /app
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

# ---- backend runtime (uv) ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DATA_AGENT_STATIC_DIR=/app/static

WORKDIR /app

# dependency layer (cached independently of source)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# project layer
COPY backend/ ./
RUN uv sync --frozen --no-dev

# static frontend (FastAPI StaticFiles mounts it when the dir exists)
COPY --from=frontend /app/dist /app/static

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "data_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
