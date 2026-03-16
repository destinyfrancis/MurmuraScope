# =============================================================
# Stage 1: Build Vue frontend
# =============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --frozen-lockfile || npm install

COPY frontend/ ./
RUN npm run build

# =============================================================
# Stage 2: Python backend + serve frontend static files
# =============================================================
FROM python:3.11-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for aiosqlite / WeasyPrint / etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy backend source code
COPY backend/ ./backend/

# Copy frontend build output into backend static directory
COPY --from=frontend-builder /app/frontend/dist ./backend/static

# Copy data directory (schemas, prompts, etc.)
COPY data/ ./data/

EXPOSE 5001

CMD ["uvicorn", "backend.run:app", "--host", "0.0.0.0", "--port", "5001"]
