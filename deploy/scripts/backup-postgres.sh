#!/bin/sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-deploy/backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${1:-${BACKUP_DIR}/codementor-${TIMESTAMP}.dump}"

mkdir -p "$(dirname "$OUTPUT")"
docker compose -f "$COMPOSE_FILE" exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$OUTPUT"
echo "Created PostgreSQL backup: $OUTPUT"
