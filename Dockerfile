# Production Dockerfile for OpenSource Guardian
FROM python:3.12-slim AS production

# Set environment variables for production execution
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Copy package manifests first for optimal layer caching
COPY pyproject.toml README.md ./

# Copy source tree and install dependencies
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Copy operational scripts
COPY scripts/ ./scripts/

# Create non-root system user for secure container execution
RUN useradd -u 1000 -m -s /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Document container port (Railway overrides this via $PORT at runtime)
EXPOSE 8000

# Container health check using built-in Python standard library
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')" || exit 1

# Launch application server binding to 0.0.0.0 and respecting Railway's dynamic $PORT
CMD ["sh", "-c", "exec uvicorn src.guardian.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
