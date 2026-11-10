# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-lock.txt requirements-extensions.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt -r requirements-extensions.txt \
    && groupadd --gid 10001 happyclass \
    && useradd --uid 10001 --gid happyclass --no-create-home happyclass
COPY backend/ ./backend/
COPY ai_service/ ./ai_service/
COPY database/ ./database/
COPY scripts/ ./scripts/
COPY --from=frontend /build/dist/ ./frontend/dist/
RUN mkdir -p data && chown -R happyclass:happyclass /app
USER happyclass
EXPOSE 18080
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "18080"]

FROM base AS runtime

FROM base AS ai
USER root
RUN pip install --no-cache-dir -r ai_service/requirements-ai-lock.txt \
    && python -c "from scripts.prepare_ai import ensure_model; ensure_model()"
USER happyclass
EXPOSE 18081
CMD ["python", "-m", "uvicorn", "ai_service.main:app", "--host", "0.0.0.0", "--port", "18081"]
