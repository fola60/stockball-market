#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env ]]; then
  echo "missing production environment file: $repo_root/.env" >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      sub(/\r$/, "", value)
      print value
      exit
    }
  ' .env
}

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-$(read_env_value BACKUP_RETENTION_DAYS)}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

if [[ ! "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  echo "BACKUP_RETENTION_DAYS must be a non-negative integer" >&2
  exit 1
fi

if [[ -z "${IMAGE_TAG:-}" && -f .current-release ]]; then
  IMAGE_TAG="$(<.current-release)"
  export IMAGE_TAG
fi
: "${IMAGE_TAG:?IMAGE_TAG is required until the first release has been recorded}"

compose=(docker compose -f docker-compose.yml -f compose.prod.yml)
backup_dir="$repo_root/backups"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/stockball-${timestamp}.dump"
partial_file="${backup_file}.partial"

install -d -m 0700 "$backup_dir"
trap '[[ ! -e "$partial_file" ]] || unlink "$partial_file"' EXIT

"${compose[@]}" up -d postgres
"${compose[@]}" exec -T postgres \
  sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format custom' \
  > "$partial_file"

if [[ ! -s "$partial_file" ]]; then
  echo "PostgreSQL backup is empty" >&2
  exit 1
fi

chmod 0600 "$partial_file"
mv "$partial_file" "$backup_file"
find "$backup_dir" -type f -name 'stockball-*.dump' -mtime "+$BACKUP_RETENTION_DAYS" -delete
echo "$backup_file"
