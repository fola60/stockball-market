#!/usr/bin/env bash
# Executed over SSH. Stdout is a secret-bearing JSON response for the launcher.
set +x
set -Eeuo pipefail
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Do not serve a mixture of old and new runtime configuration during deployment.
exec 9>.deploy.lock
flock --shared --nonblock 9 || exit 75
release="$(<.current-release)"
[[ "$release" =~ ^[0-9a-f]{40}$ ]] || exit 1
export IMAGE_TAG="$release" COMPOSE_PROFILES=server
compose=(docker compose --profile server -f docker-compose.yml -f compose.prod.yml)
container_id="$("${compose[@]}" ps -q worker)"
[[ -n "$container_id" ]] || exit 1
image="$(docker inspect --format '{{.Config.Image}}' "$container_id")"
[[ "$image" == *":$release" ]] || exit 75

loopback_port() {
  local binding
  binding="$("${compose[@]}" port "$1" "$2")"
  [[ "$binding" =~ ^127\.0\.0\.1:([0-9]+)$ ]] || {
    echo "Expected a loopback-only port for $1; deploy the updated production configuration." >&2
    return 1
  }
  printf '%s' "${BASH_REMATCH[1]}"
}

db_port="$(loopback_port postgres 5432)"
redis_port="$(loopback_port redis 6379)"
engine_port="$(loopback_port trading-engine 3000)"
api_port="$(loopback_port api 8000)"
# Reading only the worker configuration avoids returning unrelated container secrets.
docker exec -i "$container_id" python - "$image" "$release" \
  "$db_port" "$redis_port" "$engine_port" "$api_port" <<'PY'
import json
import os
import sys

print(json.dumps({
    "version": 1,
    "image": sys.argv[1],
    "release": sys.argv[2],
    "ports": dict(zip(("database", "redis", "engine", "api"), map(int, sys.argv[3:]))),
    "environment": {
        key: value for key, value in os.environ.items()
        if key.startswith("STOCKBALL_") or key == "TZ"
    },
}))
PY
