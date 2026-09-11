-- ============================================================================
-- Grant business users access to the DCR Console apps.
--
-- Both tracks run with OWNER'S RIGHTS for all operations except JOIN: every
-- DCR call executes as the app's role, whatever role the end user holds.
--
-- JOIN is the exception. It accepts legal terms via SYSTEM$ACCEPT_LEGAL_TERMS,
-- which Snowflake requires a named person to do. The app therefore runs JOIN
-- as the CALLER (the person logged in), using caller's rights. For this to
-- work, the caller needs SAMOOHA_APP_ROLE — see the grant below.
--
-- This is safe: SAMOOHA_APP_ROLE alone does not bypass the facade. The app
-- only offers one caller's-rights path (REVIEW + JOIN), and all other
-- operations still go through DCR_CONSOLE.APP.INVOKE with owner's rights.
-- A determined user could open a worksheet and call DCR directly, but that is
-- true of any privilege on any system and is outside the app's control.
--
-- Access is controlled at two independent layers, and BOTH must pass:
--   1. App grant           — can this role open the app at all?
--   2. DCR collaboration   — which collaborations can it see and query?
-- A user with the app grant but no collaboration privilege gets an empty list.
-- ============================================================================

USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS DCR_BUSINESS_USER
  COMMENT = 'Business users of the DCR Audience Overlap Console.';

-- ---------------------------------------------------------------------------
-- Track A — Streamlit in Snowflake
-- ---------------------------------------------------------------------------
GRANT USAGE ON DATABASE  DCR_CONSOLE                          TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON SCHEMA    DCR_CONSOLE.UI                       TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON STREAMLIT DCR_CONSOLE.UI.DCR_OVERLAP_CONSOLE   TO ROLE DCR_BUSINESS_USER;

-- ---------------------------------------------------------------------------
-- Track B — React on Snowflake App Runtime (SPCS)
--
-- All three USAGE grants are required: the object hierarchy must be complete or
-- the app URL returns a permission error.
--
-- To revoke later use REVOKE USAGE ON APPLICATION SERVICE — NOT
-- REVOKE ON SERVICE, which targets a different SPCS object and silently does
-- nothing.
-- ---------------------------------------------------------------------------
GRANT USAGE ON DATABASE SNOWFLAKE_APPS                        TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON SCHEMA   SNOWFLAKE_APPS.PUBLIC                 TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON APPLICATION SERVICE
      SNOWFLAKE_APPS.PUBLIC.DCR_OVERLAP_CONSOLE_WEB           TO ROLE DCR_BUSINESS_USER;

-- ---------------------------------------------------------------------------
-- Warehouse for the queries the app issues on the user's behalf.
-- ---------------------------------------------------------------------------
GRANT USAGE ON WAREHOUSE APP_WH                               TO ROLE DCR_BUSINESS_USER;

-- ---------------------------------------------------------------------------
-- SAMOOHA_APP_ROLE — needed for JOIN (the only caller's-rights operation).
--
-- Without this, the user can do everything EXCEPT accept invitations. All
-- other DCR operations go through the facade and do not need this role.
-- ---------------------------------------------------------------------------
GRANT ROLE SAMOOHA_APP_ROLE TO ROLE DCR_BUSINESS_USER;

-- ---------------------------------------------------------------------------
-- Assign to people. GRANT does not evaluate functions, so the username must be
-- a literal: TO USER CURRENT_USER() is a syntax error.
--
-- Also ensure each user's profile is complete (first_name, last_name, email),
-- because JOIN will reject a user without one.
-- ---------------------------------------------------------------------------
-- GRANT ROLE DCR_BUSINESS_USER TO USER <USERNAME>;

-- ---------------------------------------------------------------------------
-- Optional: app-level permission tier. Narrows what the UI offers; DCR remains
-- the real authority.
--   VIEWER    dashboards and history
--   ANALYST   + run overlap
--   ACTIVATOR + activate and import segments
--   BUILDER   + register offerings, create/join collaborations, teardown
-- ---------------------------------------------------------------------------
-- CALL DCR_CONSOLE.APP.INVOKE('SET_APP_ROLE',
--   OBJECT_CONSTRUCT('username', '<USERNAME>', 'app_role', 'ANALYST'));

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
SHOW GRANTS TO ROLE DCR_BUSINESS_USER;
