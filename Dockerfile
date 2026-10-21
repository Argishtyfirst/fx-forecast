# One image serves the API and the built dashboard (Render / Fly.io free tier).
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /app/frontend/dist /app/frontend/dist
ENV PORT=8000
CMD ["sh", "-c", "uv run --no-sync fxf init-db && uv run --no-sync uvicorn fxf.api.main:app --host 0.0.0.0 --port ${PORT}"]
