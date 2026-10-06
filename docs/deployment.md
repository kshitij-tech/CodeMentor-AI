# CodeMentor AI Deployment Guide

The supported deployment model is containerized FastAPI + PostgreSQL + Nginx, with the existing multi-runtime Docker image consumed by the execution layer.

## Architecture

Public traffic terminates TLS at a host-level reverse proxy or load balancer and forwards to the frontend container on localhost. Nginx serves static HTML and proxies `/api/*` to FastAPI. FastAPI connects to PostgreSQL and uses the existing Docker-based execution boundary.

## Local development

```sh
docker compose up --build
```
Open `http://127.0.0.1:8080`. PostgreSQL data persists in the `codementor-postgres` named volume. Use `docker compose down` to retain it or `docker compose down -v` to reset it.

For host Ollama, the Compose default is `http://host.docker.internal:11434`.

## Production

Create `.env` from `deploy/env/production.env.example`, create the Docker secret files in `deploy/secrets/`, then run:
```sh
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
```
Verify:
```sh
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
```

Only the frontend port is published; PostgreSQL and FastAPI remain internal.

## Frontend strategy

The frontend is packaged as a static Nginx image. The image rewrites the existing localhost API URL to `/api`, and Nginx proxies `/api/*` to FastAPI. This provides same-origin browser requests in the standard deployment.

For a separately hosted frontend, use `--build-arg API_BASE_URL=https://api.example.com` when building `docker/frontend/Dockerfile`.

## PostgreSQL and migrations

Production installs Alembic and `psycopg`. The backend entrypoint runs `alembic upgrade head` before Uvicorn.

`migrations/versions/0001_initial_schema.py` is the baseline revision. Future schema changes must be new Alembic revisions.

The historical `create_all()` and SQLite compatibility migration path remains for development only. Production database initialization is migration-driven.

For an existing populated database created by the old startup path, inspect the schema first, then after confirming it matches the baseline run `alembic stamp head`. Do not blindly run the baseline against populated production data.

## Environment, CORS and secrets

Production requires `APP_ENV=production`, PostgreSQL settings, `CORS_ORIGINS`, and `EXECUTION_SANDBOX=docker`. CORS is an explicit allow-list and production startup fails if it is empty.

Database password, JWT secret and provider key are supplied as Docker secrets. Never commit real `.env` files or secrets, print secrets in CI, or pass them as Docker build arguments.

## Health probes

`/health` and `/health/live` are process/liveness checks. `/health/ready` performs `SELECT 1` against the configured database and is the readiness check.

The frontend exposes `/health` and `/ready` through Nginx so an external load balancer can probe the container boundary.

## Logging and error monitoring

Containers write stdout/stderr normally. Compose bounds local Docker JSON logs. Forward logs to centralized logging and never put credentials, tokens or sensitive request bodies in logs.

In-process logging, metrics, tracing, request IDs and error-monitoring SDK integration remain the Observability workstream responsibility. This branch defines the deployment transport boundary.

## HTTPS / reverse proxy

Terminate public TLS at a trusted reverse proxy and keep the frontend published only on localhost. Example:
```nginx
server {
    listen 443 ssl http2;
    server_name codementor.example.com;
    ssl_certificate /etc/letsencrypt/live/codementor.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/codementor.example.com/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Use automatic certificate renewal, redirect HTTP to HTTPS, and enable HSTS only after validating the HTTPS deployment.

## Resource limits and security boundary

Production Compose applies CPU, memory and PID limits, read-only backend filesystem, dropped capabilities and `no-new-privileges`.

The backend still mounts `/var/run/docker.sock` because the existing execution implementation requires it. Treat Docker socket access as a high-trust boundary and run the platform on a dedicated host. The execution implementation owns runtime network isolation and code sandboxing.

## CI/CD

CI installs dependencies, compiles Python, runs backend tests, exercises the Alembic upgrade/downgrade/upgrade lifecycle, builds backend/frontend/execution images, performs runtime smoke checks, audits Python dependencies with `pip-audit`, runs Bandit, scans images with Trivy for HIGH/CRITICAL issues, and runs GitHub Dependency Review on pull requests.

Images are verified but not automatically pushed or deployed.

## Backups and restore

Create a PostgreSQL custom-format backup with `sh ./deploy/scripts/backup-postgres.sh`. Restore during a controlled maintenance window with `sh ./deploy/scripts/restore-postgres.sh /path/to/codementor.dump`.

Backups should be daily, retained at multiple recovery points, stored in at least one encrypted off-host location, and periodically restored in an isolated environment.

## Rollback

Record the Git commit SHA and immutable image tags for every deployment. Take a PostgreSQL backup before schema-changing releases.

For an application-only rollback, set `BACKEND_IMAGE`, `FRONTEND_IMAGE` and `EXECUTION_IMAGE` to the previous known-good images and run:
```sh
docker compose --env-file .env -f docker-compose.prod.yml up -d
```

Never assume a database downgrade is safe. Use the migration's explicit downgrade plan or restore a verified backup under maintenance control.

## Ownership boundaries

This branch does not modify files owned by authentication/security, database engine configuration, problem catalogue, code execution implementation/runtime, AI Mentor, adaptive learning, profile/preferences, dashboard/analytics, practice UI, career, or observability instrumentation.

The shared `backend/main.py` change is limited to production-safe startup initialization, environment-driven CORS, `APP_VERSION`, and health-router wiring.