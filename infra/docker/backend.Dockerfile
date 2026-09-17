# syntax=docker/dockerfile:1
# Multi-stage: the runtime image carries no build toolchain and no dev/eval dependencies.

FROM python:3.11-slim-bookworm AS builder
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml ./
COPY backend/app ./app
# Only the base dependency set: the `dev`, `eval` and `voice-local` extras never reach production
# (ADR-0015).
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir .

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root: a container that does not need root should not have it.
RUN groupadd --gid 10001 vaanios \
    && useradd --uid 10001 --gid vaanios --create-home --shell /usr/sbin/nologin vaanios

COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=vaanios:vaanios backend/app ./app
COPY --chown=vaanios:vaanios backend/migrations ./migrations
COPY --chown=vaanios:vaanios backend/alembic.ini ./alembic.ini
COPY --chown=vaanios:vaanios backend/scripts ./scripts

USER vaanios
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
