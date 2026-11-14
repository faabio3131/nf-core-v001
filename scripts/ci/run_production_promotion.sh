#!/bin/sh
set -eu

sh scripts/ci/production_preflight.sh

# Production promotion is strictly code-only. Migrations and real fiscal
# approvals live in a separate N3 procedure, never inferred from deployment.
python scripts/ci/migration_guard.py --assert-current-production

revision="$NFCORE_DEPLOY_REVISION"
driver="$NFCORE_PRODUCTION_DEPLOY_DRIVER"

# Record rollback identity and prove backup BEFORE the first deployment.
# Both commands belong to the same approved, existing provider driver.
if ! sh "$driver" prepare-rollback "$revision"; then
  echo "production promotion: rollback baseline unavailable; no deploy"
  exit 42
fi
if ! sh "$driver" backup "$revision"; then
  echo "production promotion: verified pre-deploy backup unavailable; no deploy"
  exit 42
fi

rollback_release() {
  echo "production promotion: verifying rollback after failed release stage"
  if ! sh "$driver" rollback "$revision"; then
    echo "production promotion: CRITICAL rollback could not be verified"
    return 2
  fi
  return 0
}

if ! sh "$driver" deploy "$revision"; then
  echo "production promotion: deploy failed"
  rollback_release || exit 2
  exit 1
fi

# A healthy API alone does not prove the worker that processes fiscal
# outbox/inbox is running. Never mark the release passed without that proof.
if ! sh "$driver" verify-worker "$revision"; then
  echo "production promotion: worker verification failed"
  rollback_release || exit 2
  exit 1
fi

if ! sh scripts/ci/production_smoke.sh "$NFCORE_PRODUCTION_BASE_URL"; then
  echo "production promotion: post-deploy smoke failed"
  rollback_release || exit 2
  exit 1
fi

echo "production promotion: PASS revision=$revision"
