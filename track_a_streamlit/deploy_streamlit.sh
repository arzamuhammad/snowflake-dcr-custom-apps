#!/usr/bin/env bash
# Deploy DCR Console (Track A) as a Streamlit in Snowflake app.
#
# Prerequisites:
#   - DCR_CONSOLE database and APP.INVOKE procedure already deployed (run 00_facade first)
#   - Warehouse accessible to the deploying role
#
# Usage:
#   bash deploy_streamlit.sh

set -euo pipefail

DB="DCR_CONSOLE"
SCHEMA="UI"
APP_NAME="DCR_OVERLAP_CONSOLE"
WH="APP_WH"
STAGE="${DB}.${SCHEMA}.STREAMLIT_STAGE"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Creating stage ==="
snow sql -q "
USE ROLE ACCOUNTADMIN;
CREATE STAGE IF NOT EXISTS ${STAGE}
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'DCR Console Streamlit app source files.';
GRANT ALL ON STAGE ${STAGE} TO ROLE DCR_CONSOLE_ROLE;
"

echo "=== Uploading files ==="
snow stage copy "${SCRIPT_DIR}/streamlit_app.py" "@${STAGE}/" --overwrite
snow stage copy "${SCRIPT_DIR}/environment.yml"  "@${STAGE}/" --overwrite

for f in "${SCRIPT_DIR}/lib/"*.py; do
  snow stage copy "$f" "@${STAGE}/lib/" --overwrite
done

for f in "${SCRIPT_DIR}/pages/"*.py; do
  snow stage copy "$f" "@${STAGE}/pages/" --overwrite
done

echo "=== Refreshing directory ==="
snow sql -q "ALTER STAGE ${STAGE} REFRESH;"

echo "=== Creating/replacing Streamlit object ==="
snow sql -q "
CREATE OR REPLACE STREAMLIT ${DB}.${SCHEMA}.${APP_NAME}
  ROOT_LOCATION = '@${STAGE}'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = '${WH}'
  COMMENT = 'DCR Audience Overlap Console — Collaboration API v2, zero SQL.';
GRANT USAGE ON STREAMLIT ${DB}.${SCHEMA}.${APP_NAME} TO ROLE DCR_CONSOLE_ROLE;
"

echo "=== Done ==="
echo "Open in Snowsight: Streamlit > ${DB}.${SCHEMA}.${APP_NAME}"
