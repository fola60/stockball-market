#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run Stockball ingestion commands locally without Docker.

Usage:
  scripts/local-ingestion.sh setup
  scripts/local-ingestion.sh migrate
  scripts/local-ingestion.sh seed-players [--season 2026] [stockball-worker args...]
  scripts/local-ingestion.sh ingest-fixtures [--season 2026] [stockball-worker args...]
  scripts/local-ingestion.sh ingest-player-stats [--season 2026] [stockball-worker args...]
  scripts/local-ingestion.sh import-market-values [stockball-worker args...]
  scripts/local-ingestion.sh seed-player-shares [stockball-worker args...]
  scripts/local-ingestion.sh ingest-fotmob-ratings [--season 2025] [--backfill]
  scripts/local-ingestion.sh ingest-bet365-odds [stockball-worker args...]
  scripts/local-ingestion.sh sync-twitter-injury-registry --registry /path/to/registry.json
  scripts/local-ingestion.sh ingest-twitter-injuries [stockball-worker args...]

Aliases:
  players        seed-players
  fixtures       ingest-fixtures
  stats          ingest-player-stats
  market-values  import-market-values
  shares         seed-player-shares
  fotmob         ingest-fotmob-ratings
  bet365         ingest-bet365-odds
  twitter-sources      sync-twitter-injury-registry
  twitter-injuries     ingest-twitter-injuries

Defaults:
  setup installs the worker into .venv-worker.
  migrate applies infra/postgres/migrations/*.sql to STOCKBALL_WORKER_DATABASE_URL.
  --season defaults to STOCKBALL_INGESTION_SEASON, or the season in progress when unset or 0.
  import-market-values defaults to MARKET_VALUES_DIR/players.csv and
  MARKET_VALUES_DIR/player_valuations.csv.

Optional local overrides:
  Copy scripts/local-ingestion.env.example to .env.local-ingestion and edit it.

Examples:
  scripts/local-ingestion.sh setup
  scripts/local-ingestion.sh migrate
  scripts/local-ingestion.sh players
  scripts/local-ingestion.sh fixtures --from-date 2025-08-01 --to-date 2025-08-31
  scripts/local-ingestion.sh stats --stat-type standard --stat-type shooting
  scripts/local-ingestion.sh market-values
  scripts/local-ingestion.sh shares
  scripts/local-ingestion.sh bet365 --league PL
  scripts/local-ingestion.sh twitter-sources --registry ./config/twitter-injury-registry.json
  scripts/local-ingestion.sh twitter-injuries
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

env_file="${LOCAL_INGESTION_ENV_FILE:-.env.local-ingestion}"
if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$env_file"
  set +a
fi

export POSTGRES_DB="${POSTGRES_DB:-stockball}"
export POSTGRES_USER="${POSTGRES_USER:-stockball}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-stockball}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export TRADING_ENGINE_PORT="${TRADING_ENGINE_PORT:-3000}"
export MARKET_VALUES_DIR="${MARKET_VALUES_DIR:-./services/worker/app/ingestion/market_values/archive (1)}"
export LOCAL_WORKER_VENV="${LOCAL_WORKER_VENV:-.venv-worker}"

export STOCKBALL_WORKER_DATABASE_URL="${STOCKBALL_WORKER_DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}?gssencmode=disable}"
export STOCKBALL_WORKER_REDIS_URL="${STOCKBALL_WORKER_REDIS_URL:-redis://localhost:${REDIS_PORT}/0}"
export STOCKBALL_WORKER_TRADING_ENGINE_URL="${STOCKBALL_WORKER_TRADING_ENGINE_URL:-http://localhost:${TRADING_ENGINE_PORT}}"
export STOCKBALL_WORKER_LOG_LEVEL="${STOCKBALL_WORKER_LOG_LEVEL:-INFO}"

export STOCKBALL_FBREF_BASE_URL="${STOCKBALL_FBREF_BASE_URL:-https://fbref.com}"
export STOCKBALL_FBREF_USER_AGENT="${STOCKBALL_FBREF_USER_AGENT:-StockballMarketWorker/0.1;contact=engineering@stockball.local;provider=FBREF}"
export STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS="${STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS:-7.5}"
export STOCKBALL_FBREF_CACHE_TTL_SECONDS="${STOCKBALL_FBREF_CACHE_TTL_SECONDS:-86400}"
export STOCKBALL_TWITTER_REQUEST_INTERVAL_SECONDS="${STOCKBALL_TWITTER_REQUEST_INTERVAL_SECONDS:-1}"

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

command="$1"
shift

case "$command" in
  players) command="seed-players" ;;
  fixtures) command="ingest-fixtures" ;;
  stats) command="ingest-player-stats" ;;
  market-values) command="import-market-values" ;;
  shares) command="seed-player-shares" ;;
  fotmob) command="ingest-fotmob-ratings" ;;
  bet365) command="ingest-bet365-odds" ;;
  twitter-sources) command="sync-twitter-injury-registry" ;;
  twitter-injuries) command="ingest-twitter-injuries" ;;
esac

has_option() {
  local option="$1"
  shift
  if [[ $# -eq 0 ]]; then
    return 1
  fi

  for arg in "$@"; do
    if [[ "$arg" == "$option" || "$arg" == "$option="* ]]; then
      return 0
    fi
  done
  return 1
}

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return
  fi

  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi

  echo "python3.12 or python3 is required" >&2
  exit 1
}

ensure_python_version() {
  "$1" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12+ is required")
PY
}

ensure_worker_venv() {
  local venv_path="$repo_root/$LOCAL_WORKER_VENV"
  local python_bin

  if [[ ! -x "$venv_path/bin/python" ]]; then
    python_bin="$(pick_python)"
    ensure_python_version "$python_bin"
    "$python_bin" -m venv "$venv_path"
  fi

  if [[ ! -x "$venv_path/bin/stockball-worker" || "${LOCAL_INGESTION_REINSTALL:-0}" == "1" ]]; then
    "$venv_path/bin/python" -m pip install --upgrade pip setuptools wheel
    "$venv_path/bin/python" -m pip install -e "$repo_root/services/worker"

    if [[ "${LOCAL_INGESTION_INSTALL_CHROMEDRIVER:-0}" == "1" ]]; then
      "$venv_path/bin/seleniumbase" install chromedriver
    fi
  fi
}

check_database() {
  local venv_path="$repo_root/$LOCAL_WORKER_VENV"

  "$venv_path/bin/python" - <<'PY'
import os
import sys

import psycopg2

try:
    connection = psycopg2.connect(os.environ["STOCKBALL_WORKER_DATABASE_URL"])
except Exception as exc:
    print(
        "Could not connect to STOCKBALL_WORKER_DATABASE_URL. "
        "Start local Postgres or override the URL in .env.local-ingestion.",
        file=sys.stderr,
    )
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
else:
    connection.close()
PY
}

run_worker_command() {
  local needs_database="${1:-}"

  ensure_worker_venv
  if [[ "$needs_database" == "--check-db" ]]; then
    shift
    check_database
  fi

  "$repo_root/$LOCAL_WORKER_VENV/bin/stockball-worker" "$@"
}

apply_migrations() {
  STOCKBALL_MIGRATION_DATABASE_URL="$STOCKBALL_WORKER_DATABASE_URL" \
    "$repo_root/scripts/migrate.sh"
}

case "$command" in
  setup)
    ensure_worker_venv
    ;;
  migrate)
    apply_migrations
    ;;
  seed-players | ingest-fixtures | ingest-player-stats)
    # Without --season or a pinned STOCKBALL_INGESTION_SEASON the command uses the season in
    # progress.
    if has_option "--season" "$@" || [[ "${STOCKBALL_INGESTION_SEASON:-0}" == "0" ]]; then
      args=("$@")
    else
      args=("$@" --season "$STOCKBALL_INGESTION_SEASON")
    fi
    run_worker_command --check-db "$command" "${args[@]}"
    ;;
  ingest-fotmob-ratings | ingest-bet365-odds | sync-twitter-injury-registry | ingest-twitter-injuries)
    run_worker_command --check-db "$command" "$@"
    ;;
  import-market-values)
    args=("$@")
    if ! has_option "--players-csv" "$@"; then
      args+=(--players-csv "$MARKET_VALUES_DIR/players.csv")
    fi
    if ! has_option "--valuations-csv" "$@"; then
      args+=(--valuations-csv "$MARKET_VALUES_DIR/player_valuations.csv")
    fi
    run_worker_command --check-db "$command" "${args[@]}"
    ;;
  seed-player-shares)
    run_worker_command "$command" "$@"
    ;;
  *)
    echo "unsupported local ingestion command: $command" >&2
    echo >&2
    usage >&2
    exit 2
    ;;
esac
