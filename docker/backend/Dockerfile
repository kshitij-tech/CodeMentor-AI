FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    WEB_CONCURRENCY=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       docker.io \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 codementor \
    && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin codementor

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements-production.txt /tmp/requirements-production.txt
RUN python -m pip install -r /tmp/requirements-production.txt

COPY backend /app/backend
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY docker/backend/entrypoint.sh /usr/local/bin/codementor-entrypoint

RUN chmod 0555 /usr/local/bin/codementor-entrypoint \
    && chown -R 65532:65532 /app

USER 65532:65532
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"

ENTRYPOINT ["/usr/local/bin/codementor-entrypoint"]
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
