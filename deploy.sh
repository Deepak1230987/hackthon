#!/usr/bin/env bash
# Brings the VM up to date with origin/main. Run by the GitHub Actions deploy job.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# Records the last commit that deployed successfully, so a failed deploy is retried.
MARKER=.deployed-commit
last=$(cat "$MARKER" 2>/dev/null || true)

git fetch --quiet origin main
git merge --quiet --ff-only origin/main
head=$(git rev-parse HEAD)

changed() {
  [ -z "$last" ] || ! git diff --quiet "$last" "$head" -- "$@"
}

# Rebuilding restarts running jobs, so frontend and docs changes must not trigger it.
if changed backend docker-compose.yml Caddyfile; then
  # The old container keeps serving if the build or a migration fails.
  docker compose build api
  docker compose run --rm api alembic upgrade head
  docker compose up -d
  if changed Caddyfile; then
    docker compose restart caddy
  fi

  for _ in $(seq 1 30); do
    if docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).read().decode())" 2>/dev/null | grep -q '"status":"ok"'; then
      healthy=1
      break
    fi
    sleep 2
  done
  if [ -z "${healthy:-}" ]; then
    echo "Deployed ${head:0:7}, but the backend isn't healthy:" >&2
    docker compose logs api --tail 30 >&2
    exit 1
  fi
  echo "Deployed ${head:0:7}"
else
  echo "No backend changes in ${head:0:7}"
fi

echo "$head" > "$MARKER"
