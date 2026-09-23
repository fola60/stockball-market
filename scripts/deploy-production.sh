#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <full-git-commit-sha>" >&2
  exit 2
fi

new_tag="$1"
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

DOMAIN="${DOMAIN:-$(read_env_value DOMAIN)}"
API_PORT="${API_PORT:-$(read_env_value API_PORT)}"
API_PORT="${API_PORT:-8000}"
: "${DOMAIN:?DOMAIN must be set in .env}"

exec 9>"$repo_root/.deploy.lock"
if ! flock -n 9; then
  echo "another production deployment is already running" >&2
  exit 1
fi

compose=(docker compose -f docker-compose.yml -f compose.prod.yml)
current_release_file="$repo_root/.current-release"
previous_release_file="$repo_root/.previous-release"
previous_tag=""
update_started=0

if [[ -f "$current_release_file" ]]; then
  previous_tag="$(<"$current_release_file")"
fi

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="${3:-30}"
  local delay_seconds="${4:-5}"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error --max-time 10 --output /dev/null "$url"; then
      echo "$label is healthy"
      return 0
    fi
    echo "waiting for $label ($attempt/$attempts)"
    sleep "$delay_seconds"
  done

  echo "$label did not become healthy: $url" >&2
  return 1
}

rollback_on_error() {
  local exit_code=$?
  trap - ERR

  if [[ "$update_started" == "1" && "$previous_tag" =~ ^[0-9a-f]{40}$ && "$previous_tag" != "$new_tag" ]]; then
    echo "deployment failed; rolling application containers back to $previous_tag" >&2
    export IMAGE_TAG="$previous_tag"
    "${compose[@]}" pull
    "${compose[@]}" up -d --remove-orphans
    wait_for_url "API after rollback" "http://127.0.0.1:${API_PORT}/healthz" 12 5 || true
    wait_for_url "public site after rollback" "https://${DOMAIN}/" 12 5 || true
  else
    echo "deployment failed before an application rollback was available or necessary" >&2
  fi

  exit "$exit_code"
}
trap rollback_on_error ERR

export IMAGE_TAG="$new_tag"
"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up -d postgres redis

if [[ -f "$current_release_file" ]]; then
  "$script_dir/backup-postgres.sh"
fi

"${compose[@]}" run --rm migrate

update_started=1
"${compose[@]}" up -d --remove-orphans

wait_for_url "API" "http://127.0.0.1:${API_PORT}/healthz"
wait_for_url "public site" "https://${DOMAIN}/" 36 5

if [[ -n "$previous_tag" && "$previous_tag" != "$new_tag" ]]; then
  printf '%s\n' "$previous_tag" > "${previous_release_file}.tmp"
  mv "${previous_release_file}.tmp" "$previous_release_file"
fi
printf '%s\n' "$new_tag" > "${current_release_file}.tmp"
mv "${current_release_file}.tmp" "$current_release_file"

docker image prune --force >/dev/null
trap - ERR
echo "deployed $new_tag"
