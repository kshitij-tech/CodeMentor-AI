# Database migration strategy

CodeMentor-AI keeps SQLite as the zero-configuration development database, while PostgreSQL is the production database path.

## New environment

Set DATABASE_URL to PostgreSQL, keep AUTO_CREATE_SCHEMA=0 (the PostgreSQL default), and run:

    python -m alembic -c backend/alembic.ini upgrade head

Run migrations before starting FastAPI. The application no longer calls Base.metadata.create_all() for PostgreSQL. This prevents startup-time schema drift and makes schema changes reviewable and reversible.

## Existing SQLite / legacy database

Back up the database first. Continue using the application's development bootstrap for legacy SQLite databases. When adopting Alembic for an existing database, verify its schema against the baseline, then stamp the matching baseline revision and upgrade:

    python -m alembic -c backend/alembic.ini stamp 0001_baseline
    python -m alembic -c backend/alembic.ini upgrade head

Do not stamp a database that does not already match the baseline. For an old schema, make a dedicated additive migration or rebuild/restore from a controlled backup.

## Large-table migration rules

Workload indexes in 0002_scalability_indexes use PostgreSQL concurrent index creation to avoid holding a long table lock. Future large-table migrations should prefer additive changes, backfill in batches, then add constraints/indexes. Avoid long-running data rewrites inside the application startup path.

## Retention

backend/database_retention.py provides an explicit operator-controlled purge for high-volume activity. The default policy retains coding attempts for 730 days and mentor messages for 365 days. Problems and current workspace code are retained; they are user/application state rather than disposable telemetry. Run retention after backup and only from a scheduled maintenance job with an agreed policy.
