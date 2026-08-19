#!/bin/sh
# The one safe way to point this Terraform directory at an environment's
# state. Required because of a real incident (BACKLOG_V1_CLOSURE.md,
# 2026-08-19): a bare `terraform init` silently reuses whatever backend
# key is cached in the local .terraform/ directory from the last time
# anyone initialized it here, regardless of which -var-file you plan to
# use next. Running `terraform plan -var-file=environments/staging.tfvars`
# against a local cache still pointed at prod's state key produced a
# plan to destroy and recreate 61 real production resources. Nothing
# was applied that time, but the mechanism for the mistake is real and
# repeatable, which is exactly what this script exists to remove.
#
# Usage: ./init-env.sh prod
#        ./init-env.sh staging
#
# Always passes -reconfigure, so it never silently keeps a stale cached
# backend from a previous run -- every invocation is a fresh, explicit
# statement of which environment's state you are about to touch.

set -e

ENV="$1"
if [ "$ENV" != "prod" ] && [ "$ENV" != "staging" ]; then
  echo "Usage: $0 <prod|staging>" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

terraform -chdir="$SCRIPT_DIR" init -reconfigure \
  -backend-config="resource_group_name=rg-payreality-tfstate" \
  -backend-config="storage_account_name=sttfstatepr8p3t4s" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=payreality-${ENV}.tfstate"

echo ""
echo "=========================================================="
echo "Initialized against payreality-${ENV}.tfstate."
echo "Only ever run plan/apply against this directory with:"
echo "  terraform plan  -var-file=environments/${ENV}.tfvars"
echo "  terraform apply -var-file=environments/${ENV}.tfvars"
echo "using the SAME environment name as above. If you need the"
echo "other environment next, re-run this script for it first --"
echo "never assume the cached backend still matches."
echo "=========================================================="
