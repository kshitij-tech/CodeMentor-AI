# Production secrets

The production Compose file expects these host-only files:

- `db_password.txt` — PostgreSQL application password.
- `jwt_secret_key.txt` — randomly generated JWT signing secret.
- `mistral_api_key.txt` — provider key when `AI_PROVIDER=mistral`.

Compose mounts them under `/run/secrets/`; they are not copied into image layers.

Restrict permissions, for example `chmod 600 deploy/secrets/*.txt`, and manage these values through an organizational secret-management system. Never commit real secret contents.