-- ---------------------------------------------------------------------------
-- Caller grants for the deployed app's caller's-rights path (REVIEW + JOIN)
--
-- Run once per account that will JOIN through the app. ACCOUNTADMIN, or a role
-- with MANAGE CALLER GRANTS.
--
-- WHY THIS FILE EXISTS
-- /api/direct runs REVIEW and JOIN as the caller, because JOIN accepts legal
-- terms and Snowflake requires a named person to do that. But a Snowflake App
-- Runtime service does not get unrestricted caller's rights -- it gets
-- RESTRICTED caller's rights. Under that model the caller's privileges are not
-- automatically usable: an administrator must first declare, per object, which
-- of the caller's privileges the service may borrow. Those declarations are
-- caller grants.
--
-- Without them the failure does NOT look like a permission error. DCR's
-- procedures simply resolve to nothing and you get:
--
--   Unknown user-defined function SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION.REVIEW.
--   This executable runs with restricted caller's rights. The owner role
--   ACCOUNTADMIN must have CALLER USAGE or any other CALLER privilege granted
--   on DATABASE SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.
--
-- A caller grant grants NO privilege of its own. The person joining still needs
-- SAMOOHA_APP_ROLE and a profile with first name, last name and email. This
-- file only unblocks privileges the caller already holds.
--
-- WHO TO GRANT TO
-- The role that OWNS the service, not the user and not the app. Find it with:
--
--   SHOW APPLICATION SERVICES IN ACCOUNT;   -- read the "owner" column
--
-- Substitute that role below if yours is not ACCOUNTADMIN. Note the blast
-- radius: these grants apply to EVERY executable owned by that role, so a
-- dedicated owner role is preferable to ACCOUNTADMIN in production.
--
-- Verify afterwards with:  SHOW CALLER GRANTS TO ROLE <owner_role>;
-- ---------------------------------------------------------------------------

USE ROLE ACCOUNTADMIN;

SET owner_role = 'ACCOUNTADMIN';   -- the service owner from SHOW APPLICATION SERVICES

-- --- 1. Reach the DCR API itself -------------------------------------------
-- USAGE on the database and its schemas is not enough on its own: procedures
-- and functions are separate object types and need their own caller grants,
-- which is exactly what the "Unknown user-defined function" error is about.
-- Granted across the whole database because the API spans several schemas
-- (COLLABORATION, REGISTRY, ADMIN, LIBRARY) and calls between them.

GRANT CALLER USAGE ON DATABASE SAMOOHA_BY_SNOWFLAKE_LOCAL_DB
  TO ROLE IDENTIFIER($owner_role);

GRANT INHERITED CALLER USAGE ON ALL SCHEMAS IN DATABASE SAMOOHA_BY_SNOWFLAKE_LOCAL_DB
  TO ROLE IDENTIFIER($owner_role);

GRANT INHERITED CALLER USAGE ON ALL PROCEDURES IN DATABASE SAMOOHA_BY_SNOWFLAKE_LOCAL_DB
  TO ROLE IDENTIFIER($owner_role);

GRANT INHERITED CALLER USAGE ON ALL FUNCTIONS IN DATABASE SAMOOHA_BY_SNOWFLAKE_LOCAL_DB
  TO ROLE IDENTIFIER($owner_role);

-- The local DB is a mount over the native app, and the API calls back into it.
GRANT CALLER USAGE ON APPLICATION SAMOOHA_BY_SNOWFLAKE
  TO ROLE IDENTIFIER($owner_role);

-- --- 2. Let JOIN actually build the clean room -----------------------------
-- JOIN is not a metadata update. It installs an application (SFDCR_<collab>),
-- creates a database of local views (SFDCR_LOCAL_<collab>), and wires up the
-- shares and listing that move data between accounts. Each of those needs its
-- own account-level caller grant, or JOIN fails partway and leaves the
-- collaboration in a state LEAVE will not accept.

GRANT CALLER CREATE APPLICATION       ON ACCOUNT TO ROLE IDENTIFIER($owner_role);
GRANT CALLER CREATE DATABASE          ON ACCOUNT TO ROLE IDENTIFIER($owner_role);
GRANT CALLER CREATE SHARE             ON ACCOUNT TO ROLE IDENTIFIER($owner_role);
GRANT CALLER IMPORT SHARE             ON ACCOUNT TO ROLE IDENTIFIER($owner_role);
GRANT CALLER MANAGE SHARE TARGET      ON ACCOUNT TO ROLE IDENTIFIER($owner_role);
GRANT CALLER CREATE LISTING           ON ACCOUNT TO ROLE IDENTIFIER($owner_role);
GRANT CALLER APPLY ROW ACCESS POLICY  ON ACCOUNT TO ROLE IDENTIFIER($owner_role);

-- Only needed if you pass auto_join_warehouse to INITIALIZE, which creates a
-- <collab>_<hash>_OWNER_AUTO_JOIN task. Harmless otherwise.
GRANT CALLER EXECUTE TASK             ON ACCOUNT TO ROLE IDENTIFIER($owner_role);

-- --- 3. Confirm ------------------------------------------------------------
SHOW CALLER GRANTS TO ROLE ACCOUNTADMIN;
