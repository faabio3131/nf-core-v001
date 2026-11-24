#!/bin/sh
set -eu

sh scripts/ci/production_preflight.sh

# Production promotion is code-only. Database DDL (including fiscal DPS v22)
# is a separate N3-approved operation with independent backup/recovery proof.
# Never synthesize schema-migration approval from the deploy approval token.
python scripts/ci/migration_guard.py --assert-current-production

revision="$NFCORE_DEPLOY_REVISION"
sh "$NFCORE_PRODUCTION_DEPLOY_DRIVER" deploy "$revision"
if ! sh scripts/ci/production_smoke.sh "$NFCORE_PRODUCTION_BASE_URL"; then
  echo "production promotion: post-deploy smoke failed; invoking provider rollback"
  sh "$NFCORE_PRODUCTION_DEPLOY_DRIVER" rollback "$revision"
  exit 1
fi

echo "production promotion: PASS revision=$revision"
