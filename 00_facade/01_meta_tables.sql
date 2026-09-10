-- ============================================================================
-- DCR Console — P0: META schema (audit, cache, app RBAC, saved configs)
-- Owner: DCR_CONSOLE_ROLE. Shared by Track A (Streamlit) and Track B (React),
-- so both UIs see identical history.
-- ============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE DCR_CONSOLE;
USE SCHEMA META;

-- ---------------------------------------------------------------------------
-- AUDIT_LOG — every facade invocation. This is the compliance artifact: who
-- shared what with whom, which columns were activated, and when.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS AUDIT_LOG (
    EVENT_ID        STRING      DEFAULT UUID_STRING(),
    EVENT_TS        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    ACTOR_USER      STRING,                 -- CURRENT_USER(), survives owner's rights
    ACTOR_ROLE      STRING,                 -- effective role inside the facade
    UI_TRACK        STRING,                 -- 'streamlit' | 'react' | 'sql'
    OPERATION       STRING,                 -- e.g. REGISTER_OFFERING, RUN_OVERLAP
    COLLABORATION   STRING,
    TARGET          STRING,                 -- offering id / template id / batch id
    REQUEST         VARIANT,                -- the config object the UI sent
    GENERATED_SPEC  STRING,                 -- the YAML we produced (auditable)
    OUTCOME         STRING,                 -- SUCCESS | FAILED | BLOCKED
    ERROR_RAW       STRING,
    ERROR_DECODED   VARIANT,                -- {code, cause, remediation, sql_fix}
    DURATION_MS     NUMBER,
    QUERY_ID        STRING
)
COMMENT = 'Immutable-by-convention audit trail of all DCR Console operations.';

-- ---------------------------------------------------------------------------
-- RUN_CACHE — overlap results keyed by a hash of the run config, so reopening
-- a collaboration does not re-bill a full overlap scan.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS RUN_CACHE (
    CACHE_KEY       STRING,                 -- sha2 of (collab, template, spec)
    COLLABORATION   STRING,
    TEMPLATE_ID     STRING,
    REQUEST         VARIANT,
    RESULTS         VARIANT,                -- normalised overlap result set
    ROW_COUNT       NUMBER,
    COMPUTED_AT     TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPUTED_BY     STRING,
    DURATION_MS     NUMBER
)
COMMENT = 'Overlap result cache. Safe to TRUNCATE at any time.';

-- ---------------------------------------------------------------------------
-- APP_USER_ROLE — app-level RBAC layered ON TOP OF DCR privileges.
--   VIEWER    : read dashboards and history
--   ANALYST   : + run overlap
--   ACTIVATOR : + run activation and import segments
--   BUILDER   : + register offerings, create/join collaborations, teardown
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS APP_USER_ROLE (
    USERNAME    STRING,
    APP_ROLE    STRING,                     -- VIEWER|ANALYST|ACTIVATOR|BUILDER
    GRANTED_BY  STRING,
    GRANTED_AT  TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    NOTES       STRING
)
COMMENT = 'App-level permission tiers. Absence of a row means VIEWER.';

-- ---------------------------------------------------------------------------
-- SAVED_CONFIG — reusable match-key / filter / activation-column presets.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS SAVED_CONFIG (
    CONFIG_ID       STRING      DEFAULT UUID_STRING(),
    CONFIG_NAME     STRING,
    CONFIG_KIND     STRING,                 -- 'overlap' | 'activation'
    COLLABORATION   STRING,
    PAYLOAD         VARIANT,
    CREATED_BY      STRING,
    CREATED_AT      TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Named, reusable run configurations.';

-- ---------------------------------------------------------------------------
-- ACTIVATION_IMPORT — tracks the recipient-side leg that the tutorials leave
-- as manual SQL: PROCESS_ACTIVATION + flattening SEGMENT_RECORDS.
-- Source of the only honest progress percentage in the application.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ACTIVATION_IMPORT (
    IMPORT_ID       STRING      DEFAULT UUID_STRING(),
    COLLABORATION   STRING,
    BATCH_ID        STRING,
    SEGMENT_NAME    STRING,
    TARGET_FQN      STRING,                 -- native table we materialised into
    EXPECTED_ROWS   NUMBER,                 -- matched count from the overlap run
    IMPORTED_ROWS   NUMBER,
    STATUS          STRING,                 -- PENDING|IMPORTING|READY|FAILED
    STARTED_AT      TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    FINISHED_AT     TIMESTAMP_LTZ,
    ERROR_RAW       STRING
)
COMMENT = 'Recipient-side activation import state.';

-- ---------------------------------------------------------------------------
-- Stage for the shared Python modules, imported by the facade procedure.
-- DIRECTORY + SNOWFLAKE_SSE are required for staged Python imports.
-- ---------------------------------------------------------------------------
CREATE STAGE IF NOT EXISTS DCR_CONSOLE.APP.LIB
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
    COMMENT = 'Python modules imported by the facade procedure.';

GRANT OWNERSHIP ON ALL TABLES IN SCHEMA DCR_CONSOLE.META TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON STAGE DCR_CONSOLE.APP.LIB             TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;

SHOW TABLES IN SCHEMA DCR_CONSOLE.META;
