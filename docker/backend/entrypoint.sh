#!/bin/sh
set -eu

read_secret() {
  variable_name="$1"
  secret_file="$2"
  if [ -f "$secret_file" ]; then
    secret_value="$(cat "$secret_file")"
    export "$variable_name=$secret_value"
  fi
}

read_secret JWT_SECRET_KEY "${JWT_SECRET_KEY_FILE:-}"
read_secret MISTRAL_API_KEY "${MISTRAL_API_KEY_FILE:-}"

if [ -f "${DB_PASSWORD_FILE:-}" ]; then
  DB_PASSWORD_VALUE="$(cat "$DB_PASSWORD_FILE")"
  export DB_PASSWORD_VALUE
  export DATABASE_URL="$(python - <<'PY'
import os
from urllib.parse import quote

password=os.environ['DB_PASSWORD_VALUE']
user=os.getenv('DATABASE_USER','codementor')
database=os.getenv('DATABASE_NAME','codementor')
host=os.getenv('DATABASE_HOST','db')
port=os.getenv('DATABASE_PORT','5432')
print(f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(database, safe='')}")
PY
)"
  unset DB_PASSWORD_VALUE
fi

if [ "${SKIP_DB_MIGRATIONS:-false}" != 'true' ]; then
  alembic upgrade head
fi

exec "$@"
