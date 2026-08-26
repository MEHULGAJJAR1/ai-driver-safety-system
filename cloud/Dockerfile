# =========================================================================
# cloud/Dockerfile  -  Driver Safety Cloud (FastAPI)
# Build from the PROJECT ROOT so the shared edge modules can be copied in:
#     docker build -f cloud/Dockerfile -t driver-safety-cloud .
# (docker-compose.yml already sets the context to the repo root.)
# =========================================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) Dependencies first (better layer caching)
COPY cloud/requirements.txt /app/cloud/requirements.txt
RUN pip install --no-cache-dir -r /app/cloud/requirements.txt

# 2) Reused edge intelligence (ZERO duplication) + the service code.
#    analytics/ and config.py are pure-stdlib, so they add no dependencies.
COPY config.py /app/config.py
COPY analytics /app/analytics
COPY cloud /app/cloud

# 3) Run as a non-root user
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Liveness probe hits the public health route
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

# Production entrypoint (no --reload). Scale workers via the compose command.
CMD ["uvicorn", "cloud.main:app", "--host", "0.0.0.0", "--port", "8000"]
