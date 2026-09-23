#!/bin/sh
set -eu

database_url="${STOCKBALL_MIGRATION_DATABASE_URL:-${STOCKBALL_WORKER_DATABASE_URL:-}}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
migrations_dir="${STOCKBALL_MIGRATIONS_DIR:-$script_dir/../infra/postgres/migrations}"
lock_key="7643428110923981"

if [ -z "$database_url" ]; then
  echo "set STOCKBALL_MIGRATION_DATABASE_URL before running migrations" >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required to apply migrations" >&2
  exit 1
fi

if [ ! -d "$migrations_dir" ]; then
  echo "migration directory does not exist: $migrations_dir" >&2
  exit 1
fi

set -- "$migrations_dir"/*.sql
if [ ! -f "$1" ]; then
  echo "no SQL migrations found in $migrations_dir" >&2
  exit 1
fi

checksum_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
    return
  fi

  echo "sha256sum or shasum is required to verify migrations" >&2
  exit 1
}

existing_schema="$(
  psql "$database_url" -X -At -v ON_ERROR_STOP=1 \
    -c "SELECT to_regclass('public.accounts') IS NOT NULL"
)"

psql "$database_url" -X -q -v ON_ERROR_STOP=1 -v "lock_key=$lock_key" <<'SQL'
BEGIN;
SELECT pg_advisory_xact_lock(:lock_key) AS migration_lock \gset

CREATE TABLE IF NOT EXISTS stockball_schema_migrations (
    filename text PRIMARY KEY,
    checksum text,
    applied_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE stockball_schema_migrations
    ADD COLUMN IF NOT EXISTS checksum text;

COMMIT;
SQL

applied_count="$(
  psql "$database_url" -X -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM stockball_schema_migrations"
)"

if [ "$existing_schema" = "t" ] && [ "$applied_count" = "0" ]; then
  echo "database has Stockball tables but no migration history" >&2
  echo "refusing to apply non-idempotent migrations to an untracked schema" >&2
  echo "recreate disposable databases or explicitly baseline a verified database" >&2
  exit 1
fi

for migration in "$@"; do
  migration_name="$(basename "$migration")"
  migration_checksum="$(checksum_file "$migration")"
  recorded="$(
    printf '%s\n' \
      "SELECT 'applied|' || COALESCE(checksum, '')" \
      "FROM stockball_schema_migrations" \
      "WHERE filename = :'migration_name';" \
      | psql "$database_url" -X -At -v ON_ERROR_STOP=1 \
          -v "migration_name=$migration_name"
  )"

  case "$recorded" in
    "applied|$migration_checksum")
      echo "skipping $migration_name"
      continue
      ;;
    "applied|")
      printf '%s\n' \
        "UPDATE stockball_schema_migrations" \
        "SET checksum = :'migration_checksum'" \
        "WHERE filename = :'migration_name' AND checksum IS NULL;" \
        | psql "$database_url" -X -q -v ON_ERROR_STOP=1 \
            -v "migration_name=$migration_name" \
            -v "migration_checksum=$migration_checksum"
      echo "recorded checksum for previously tracked migration $migration_name"
      continue
      ;;
    applied\|*)
      recorded_checksum="${recorded#applied|}"
      echo "migration checksum mismatch: $migration_name" >&2
      echo "recorded: $recorded_checksum" >&2
      echo "current:  $migration_checksum" >&2
      exit 1
      ;;
  esac

  echo "applying $migration_name"
  {
    printf '%s\n' 'BEGIN;'
    printf 'SELECT pg_advisory_xact_lock(%s) AS migration_lock \\gset\n' "$lock_key"
    printf '%s\n' \
      "SELECT EXISTS (" \
      "    SELECT 1 FROM stockball_schema_migrations" \
      "    WHERE filename = :'migration_name'" \
      ") AS migration_already_applied \gset"
    printf '%s\n' '\if :migration_already_applied'
    printf '%s\n' '\echo migration was applied by another runner'
    printf '%s\n' '\else'
    printf '%s\n' '\i :migration_file'
    printf '%s\n' \
      "INSERT INTO stockball_schema_migrations(filename, checksum)" \
      "VALUES (:'migration_name', :'migration_checksum');"
    printf '%s\n' '\endif'
    printf '%s\n' 'COMMIT;'
  } | psql "$database_url" -X -q -v ON_ERROR_STOP=1 \
      -v "migration_name=$migration_name" \
      -v "migration_checksum=$migration_checksum" \
      -v "migration_file=$migration"

  final_checksum="$(
    printf '%s\n' \
      "SELECT checksum FROM stockball_schema_migrations" \
      "WHERE filename = :'migration_name';" \
      | psql "$database_url" -X -At -v ON_ERROR_STOP=1 \
          -v "migration_name=$migration_name"
  )"
  if [ "$final_checksum" != "$migration_checksum" ]; then
    echo "migration checksum mismatch after concurrent apply: $migration_name" >&2
    exit 1
  fi
done

missing_checksum_count="$(
  psql "$database_url" -X -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM stockball_schema_migrations WHERE checksum IS NULL"
)"
if [ "$missing_checksum_count" != "0" ]; then
  echo "migration history contains $missing_checksum_count entries without checksums" >&2
  exit 1
fi

psql "$database_url" -X -q -v ON_ERROR_STOP=1 \
  -c "ALTER TABLE stockball_schema_migrations ALTER COLUMN checksum SET NOT NULL"

applied_count="$(
  psql "$database_url" -X -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM stockball_schema_migrations"
)"
echo "database migrations are current ($applied_count applied)"
