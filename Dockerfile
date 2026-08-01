# syntax=docker/dockerfile:1
# CodeCompass — multi-stage image (plan-v3-codecompass.md §5).
# Stage 1 builds the React SPA; stage 2 is the slim Python runtime that
# serves the API and the built static assets with uvicorn.

# --- Stage 1: build the web frontend ----------------------------------------
FROM node:20-alpine AS web
WORKDIR /app/web

# Install dependencies first so source edits don't bust the npm cache layer.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# --- Stage 2: Python runtime -------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root runtime user (uid 10001, matches the Helm chart securityContext).
RUN useradd --uid 10001 --user-group --create-home --shell /usr/sbin/nologin app

WORKDIR /opt/codecompass

# pyproject reads README.md for package metadata — it must be present.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[web]"

# Built SPA from stage 1; served by airx_server via STATIC_DIR.
COPY --from=web /app/web/dist /opt/codecompass/static

ENV STATIC_DIR=/opt/codecompass/static \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

USER app

CMD ["uvicorn", "airx_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
