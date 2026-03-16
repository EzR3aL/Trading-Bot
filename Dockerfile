# Bitget Trading Bot v2.0 - Production Dockerfile
# Multi-stage build: Frontend (Node) + Backend (Python)

# Stage 1: Frontend Build
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ .
ENV NODE_OPTIONS=--max-old-space-size=1536
RUN npm run build

# Stage 2: Python Dependencies
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Production
FROM python:3.11-slim
WORKDIR /app

# Install PostgreSQL client library (runtime dependency for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN useradd --create-home --shell /bin/bash botuser

# Build version (passed via --build-arg or defaults to "unknown")
ARG BUILD_COMMIT=unknown
ENV BUILD_COMMIT=${BUILD_COMMIT}

# Copy application code
COPY --chown=botuser:botuser . .

# Copy built frontend from stage 1
COPY --from=frontend /app/static/frontend /app/static/frontend

# Create data directories
RUN mkdir -p data logs \
    && chown -R botuser:botuser data logs static

# Switch to non-root user
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

EXPOSE 8000

# Ensure container stops cleanly on SIGTERM from Docker
STOPSIGNAL SIGTERM

# Run FastAPI backend (serves React frontend via StaticFiles)
CMD ["python", "-m", "uvicorn", "src.api.main_app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "25"]
