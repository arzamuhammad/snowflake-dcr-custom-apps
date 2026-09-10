-- ============================================================================
-- Grants for data that will be REGISTERED and LINKED into a clean room.
--
-- Two distinct requirements, and the second one is easy to miss:
--
--   1. REGISTER_DATA_OFFERING needs REFERENCE_USAGE ... WITH GRANT OPTION on
--      the database holding the source table. Without it:
--        DatasetReferenceUsageWithGrantOptionMissingError
--
--   2. LINK_DATA_OFFERING / LINK_LOCAL_DATA_OFFERING do not merely READ the
--      source data: they GRANT access on it to the collaboration application.
--      A role can only pass on a privilege it holds WITH GRANT OPTION, so plain
--      SELECT/USAGE is not enough. Without it:
--        003102 (42501): Grant not executed: Insufficient privileges.
--
-- Apply this for EVERY database whose tables are offered into a clean room.
-- Replace <MY_DB> / <MY_SCHEMA> with your own.
-- ============================================================================

USE ROLE ACCOUNTADMIN;

SET DCR_DB     = 'MY_DB';        -- <-- change me
SET DCR_SCHEMA = 'MY_SCHEMA';    -- <-- change me

-- Basic read access
GRANT USAGE  ON DATABASE IDENTIFIER($DCR_DB)                        TO ROLE DCR_CONSOLE_ROLE;
GRANT USAGE  ON SCHEMA   IDENTIFIER($DCR_DB || '.' || $DCR_SCHEMA)  TO ROLE DCR_CONSOLE_ROLE;

-- WITH GRANT OPTION: required because the DCR procedures re-grant on your behalf
GRANT USAGE  ON DATABASE IDENTIFIER($DCR_DB)                        TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
GRANT USAGE  ON SCHEMA   IDENTIFIER($DCR_DB || '.' || $DCR_SCHEMA)  TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;

-- REFERENCE_USAGE on the database, to BOTH the console role and the role that
-- will call the procedures interactively.
GRANT REFERENCE_USAGE ON DATABASE IDENTIFIER($DCR_DB) TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
GRANT REFERENCE_USAGE ON DATABASE IDENTIFIER($DCR_DB) TO ROLE ACCOUNTADMIN     WITH GRANT OPTION;

-- ---------------------------------------------------------------------------
-- Table-level SELECT WITH GRANT OPTION. Session variables cannot be used in
-- GRANT ... ON ALL TABLES IN SCHEMA, so spell the schema out literally here.
-- ---------------------------------------------------------------------------
-- GRANT SELECT ON ALL TABLES    IN SCHEMA MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
-- GRANT SELECT ON FUTURE TABLES IN SCHEMA MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
-- GRANT SELECT ON ALL VIEWS     IN SCHEMA MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
-- GRANT SELECT ON FUTURE VIEWS  IN SCHEMA MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;

-- ---------------------------------------------------------------------------
-- Landing schema for imported (flattened) activated segments.
-- ---------------------------------------------------------------------------
-- CREATE SCHEMA IF NOT EXISTS MY_DB.ACTIVATED;
-- GRANT USAGE, CREATE TABLE ON SCHEMA MY_DB.ACTIVATED TO ROLE DCR_CONSOLE_ROLE;
