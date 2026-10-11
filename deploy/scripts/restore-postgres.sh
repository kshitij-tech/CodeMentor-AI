#!/bin/sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
INPUT="${1:-}"

if [ -z "$INPUT" ]; then echo "Usage: sh $0 /path/to/codementor.dump" >&2; exit 2; fi
if [ ! -f "$INPUT" ]; then echo "Backup file not found: $INPUT" >&2; exit 2; fi

echo "WARNING: this replaces data in the production database."
docker compose -f "$COMPOSE_FILE" exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$INPUT"
echo "Restore completed from: $INPUT"
