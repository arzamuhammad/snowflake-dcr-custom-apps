#!/usr/bin/env bash
set -eo pipefail

C="${1:-consumer-connection}"
D="$(cd "$(dirname "$0")" && pwd)/../track_a_streamlit"
S="@DCR_CONSOLE.UI.STREAMLIT_STAGE"

echo "=== Creating stage ==="
snow sql --connection "$C" -q "CREATE STAGE IF NOT EXISTS DCR_CONSOLE.UI.STREAMLIT_STAGE DIRECTORY=(ENABLE=TRUE) ENCRYPTION=(TYPE='SNOWFLAKE_SSE')"
snow sql --connection "$C" -q "GRANT ALL ON STAGE DCR_CONSOLE.UI.STREAMLIT_STAGE TO ROLE ACCOUNTADMIN"

echo "=== Uploading files ==="
snow stage copy "$D/streamlit_app.py" "$S/" --connection "$C" --overwrite
snow stage copy "$D/environment.yml"  "$S/" --connection "$C" --overwrite

for f in "$D"/lib/*.py; do
  snow stage copy "$f" "$S/lib/" --connection "$C" --overwrite
done

for f in "$D"/pages/*.py; do
  snow stage copy "$f" "$S/pages/" --connection "$C" --overwrite
done

echo "=== Refreshing ==="
snow sql --connection "$C" -q "ALTER STAGE DCR_CONSOLE.UI.STREAMLIT_STAGE REFRESH"

echo "=== Creating Streamlit ==="
snow sql --connection "$C" -q "CREATE OR REPLACE STREAMLIT DCR_CONSOLE.UI.DCR_OVERLAP_CONSOLE ROOT_LOCATION='$S' MAIN_FILE='streamlit_app.py' QUERY_WAREHOUSE='APP_WH' COMMENT='DCR Audience Overlap Console';"

echo "=== Done (Streamlit) ==="
