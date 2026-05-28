#!/usr/bin/env bash
# Smoke test (T085, FR-028): brings up the Docker Compose stack and asserts
# /health on backend (8000), modelserver (8020), guardrails (8010) all return
# 200 within the timeout. Tears down on exit (success or failure) so CI
# runners stay clean.
#
# Exit non-zero on any failure; in CI this short-circuits the eval gate jobs
# (see .github/workflows/ci.yml -> the "smoke" job is a hard `needs:` of every
# gate job).
#
# Usage:
#   scripts/smoke_test.sh                  # default 120s timeout per service
#   SMOKE_TIMEOUT_SECONDS=60 scripts/smoke_test.sh

set -euo pipefail

TIMEOUT="${SMOKE_TIMEOUT_SECONDS:-120}"
SERVICES=(
  "backend:8000"
  "modelserver:8020"
  "guardrails:8010"
)

cleanup() {
  echo "::group::smoke teardown"
  docker compose logs --tail=50 || true
  docker compose down -v --remove-orphans || true
  echo "::endgroup::"
}
trap cleanup EXIT

echo "::group::smoke up"
docker compose up -d --build
echo "::endgroup::"

poll_health() {
  local name="$1"
  local port="$2"
  local url="http://localhost:${port}/health"
  local deadline=$(( $(date +%s) + TIMEOUT ))
  echo "polling ${name} at ${url} (timeout ${TIMEOUT}s)"
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" || true)"; [ "$status" = "200" ]; then
      echo "  ${name} OK (HTTP 200)"
      return 0
    fi
    sleep 2
  done
  echo "  ${name} FAILED (last status: ${status:-none})" >&2
  return 1
}

failed=0
for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  if ! poll_health "$name" "$port"; then
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "SMOKE FAIL: one or more services did not become healthy" >&2
  exit 1
fi

echo "SMOKE PASS: all services healthy"
