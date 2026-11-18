#!/bin/sh
set -eu

require_value() {
  name="$1"
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "production preflight: BLOCKED_EXTERNAL missing=$name"
    exit 42
  fi
}

require_value NFCORE_PRODUCTION_BASE_URL
require_value NFCORE_PRODUCTION_DEPLOY_DRIVER
require_value DATABASE_URL
require_value NFCORE_DEPLOY_REVISION

# Deploy drivers must receive an immutable, audited 40-character commit.
[ "${#NFCORE_DEPLOY_REVISION}" -eq 40 ] || {
  echo "production preflight: FAIL immutable 40-hex source revision required"
  exit 1
}
case "$NFCORE_DEPLOY_REVISION" in
  *[!0-9a-fA-F]*)
    echo "production preflight: FAIL immutable 40-hex source revision required"
    exit 1
    ;;
esac

case "$NFCORE_PRODUCTION_BASE_URL" in
  https://*) ;;
  *)
    echo "production preflight: FAIL base URL must use HTTPS"
    exit 1
    ;;
esac

case "$NFCORE_PRODUCTION_DEPLOY_DRIVER" in
  scripts/deploy/drivers/*.sh) ;;
  *)
    echo "production preflight: FAIL deploy driver must live under scripts/deploy/drivers"
    exit 1
    ;;
esac

if [ ! -f "$NFCORE_PRODUCTION_DEPLOY_DRIVER" ]; then
  echo "production preflight: BLOCKED_EXTERNAL deploy driver is not provisioned"
  exit 42
fi

[ "${NFCORE_ENVIRONMENT:-}" = "production" ] || {
  echo "production preflight: FAIL NFCORE_ENVIRONMENT must be production"
  exit 1
}
[ "${NFCORE_PERSISTENCE_BACKEND:-}" = "postgres" ] || {
  echo "production preflight: FAIL PostgreSQL is mandatory"
  exit 1
}
[ "${NFCORE_SECRET_BACKEND:-}" = "external" ] || {
  echo "production preflight: FAIL external secret backend is mandatory"
  exit 1
}
[ "${NFCORE_REQUIRE_HTTPS:-}" = "true" ] || {
  echo "production preflight: FAIL HTTPS policy is mandatory"
  exit 1
}
[ "${NFCORE_PRODUCTION_APPROVAL:-}" = "PRODUCTION_APPROVED" ] || {
  echo "production preflight: FAIL explicit production approval is mandatory"
  exit 1
}

echo "production preflight: PASS"
