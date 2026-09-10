#!/usr/bin/env bash
# Deploy DCR Console (Track B) as a Snowflake App Runtime app on SPCS.
#
# Prerequisites:
#   - FEATURE_SNOWFLAKE_APPS enabled on the account
#   - Snowflake App Runtime set up once by an admin:
#       Snowsight > your name > Settings > Account > Apps > Begin Setup
#   - Snowflake CLI 3.20+
#   - The facade already deployed (dcr-console/00_facade)
#   - BIND SERVICE ENDPOINT ON ACCOUNT granted to the deploying role
#
# Usage:
#   bash deploy.sh [connection-name]

set -eo pipefail

CONNECTION="${1:-}"
# Kept as a plain string rather than an array: under `set -u`, expanding an empty
# array is an error on older bash (macOS ships bash 3.2).
CONN_ARG=""
if [[ -n "$CONNECTION" ]]; then
  CONN_ARG="--connection $CONNECTION"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 1. Verifying the facade is reachable ==="
snow sql $CONN_ARG -q \
  "CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL);" > /dev/null
echo "    facade OK"

echo "=== 2. Type checking ==="
npx tsc --noEmit
echo "    types OK"

echo "=== 3. Building ==="
npm run build > /dev/null
echo "    build OK"

echo "=== 4. Deploying to Snowflake App Runtime ==="
# Uploads the source, builds the image on managed compute, and creates the
# service. No custom compute pool, network rule or external access integration
# is required.
snow app deploy $CONN_ARG

echo "=== 5. Opening ==="
# SHOW ENDPOINTS IN SERVICE returns the wrong URL for a SAR app; use `snow app open`.
snow app open $CONN_ARG || {
  echo "    Could not open automatically. Find it under Snowsight > Apps."
}

cat <<'EOF'

=== Grant access to business users ===

The app runs with owner's rights: every DCR call executes as the app's role, so
end users must NOT be granted SAMOOHA_APP_ROLE. Run as ACCOUNTADMIN:

  CREATE ROLE IF NOT EXISTS DCR_BUSINESS_USER;

  -- All three USAGE grants are required; the object hierarchy must be complete.
  GRANT USAGE ON DATABASE SNOWFLAKE_APPS                    TO ROLE DCR_BUSINESS_USER;
  GRANT USAGE ON SCHEMA   SNOWFLAKE_APPS.PUBLIC             TO ROLE DCR_BUSINESS_USER;
  GRANT USAGE ON APPLICATION SERVICE
        SNOWFLAKE_APPS.PUBLIC.DCR_OVERLAP_CONSOLE_WEB       TO ROLE DCR_BUSINESS_USER;
  GRANT USAGE ON WAREHOUSE APP_WH                           TO ROLE DCR_BUSINESS_USER;

  GRANT ROLE DCR_BUSINESS_USER TO USER <USERNAME>;   -- literal username

To revoke, use REVOKE USAGE ON APPLICATION SERVICE — not REVOKE ON SERVICE,
which targets a different SPCS object and silently has no effect.

=== Troubleshooting ===

  snow app events --last 100          # build and runtime logs
  snow app teardown                   # removes the service only; DCR data is untouched

404 or unreachable endpoint  -> missing BIND SERVICE ENDPOINT; grant it and redeploy.
Deploy fails on warehouse    -> edit query_warehouse in snowflake.yml.
Build stuck over 3 minutes   -> package-lock.json out of sync; run npm install and re-check tsc.
EOF
