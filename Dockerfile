FROM python:3.11-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies: WeasyPrint PDF (needs pango/cairo), procps (pkill), curl (healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        procps \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf2.0-0 \
        libffi-dev \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Copy source
COPY backend/ ./backend/

# Non-root user
RUN adduser --disabled-password --gecos "" morai && \
    mkdir -p /app/data && chown -R morai:morai /app/data
USER morai

EXPOSE 5001
CMD ["uvicorn", "backend.run:app", "--host", "0.0.0.0", "--port", "5001"]
