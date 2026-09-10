-- ============================================================================
-- DCR Console — P0 Foundation: role, grants, database, schemas
-- Collaboration API v2 ONLY. No v1 / Native App / legacy DCR identifiers.
-- Run as ACCOUNTADMIN, once per account (provider AND consumer).
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- ---------------------------------------------------------------------------
-- 1. Dedicated application role.
--    We deliberately do NOT run the app as SAMOOHA_APP_ROLE: DCR upgrades can
--    reset that role's grants, which would silently break the app.
-- ---------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS DCR_CONSOLE_ROLE
  COMMENT = 'Owner role for the DCR Audience Overlap Console (Collaboration API v2).';

-- Raw account privileges a collaboration creator needs. INITIALIZE creates an
-- application, a database, a listing and a share behind the scenes.
GRANT CREATE APPLICATION        ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT CREATE DATABASE           ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT CREATE SHARE              ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT IMPORT SHARE              ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT MANAGE SHARE TARGET       ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT APPLY ROW ACCESS POLICY   ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT EXECUTE TASK              ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT CREATE COMPUTE POOL       ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;
GRANT BIND SERVICE ENDPOINT     ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;

-- ---------------------------------------------------------------------------
-- 2. DCR capability privileges, granted through the DCR ADMIN procedures.
--    These are DCR's own privilege model, separate from Snowflake RBAC.
-- ---------------------------------------------------------------------------
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('CREATE COLLABORATION',   'DCR_CONSOLE_ROLE');
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('JOIN COLLABORATION',     'DCR_CONSOLE_ROLE');
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('REVIEW COLLABORATION',   'DCR_CONSOLE_ROLE');
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('VIEW COLLABORATIONS',    'DCR_CONSOLE_ROLE');
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('REGISTER DATA OFFERING', 'DCR_CONSOLE_ROLE');
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('REGISTER TEMPLATE',      'DCR_CONSOLE_ROLE');
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('CREATE REGISTRY',        'DCR_CONSOLE_ROLE');

-- Usage on the Collaboration API itself.
GRANT USAGE ON DATABASE SAMOOHA_BY_SNOWFLAKE_LOCAL_DB              TO ROLE DCR_CONSOLE_ROLE;
GRANT USAGE ON SCHEMA   SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.REGISTRY      TO ROLE DCR_CONSOLE_ROLE;
GRANT USAGE ON SCHEMA   SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION TO ROLE DCR_CONSOLE_ROLE;
GRANT USAGE ON SCHEMA   SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN         TO ROLE DCR_CONSOLE_ROLE;
GRANT USAGE ON SCHEMA   SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.LIBRARY       TO ROLE DCR_CONSOLE_ROLE;

-- The health check reads the DCR version from this view.
GRANT SELECT ON VIEW SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.VERSION TO ROLE DCR_CONSOLE_ROLE;

-- ---------------------------------------------------------------------------
-- 3. Console database. APP = facade procedures, META = state, UI = Streamlit.
-- ---------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS DCR_CONSOLE
  COMMENT = 'DCR Audience Overlap Console: facade over Collaboration API v2.';

CREATE SCHEMA IF NOT EXISTS DCR_CONSOLE.APP  COMMENT = 'Facade procedures. The only code that talks to DCR.';
CREATE SCHEMA IF NOT EXISTS DCR_CONSOLE.META COMMENT = 'Audit log, run cache, app RBAC, saved configs.';
CREATE SCHEMA IF NOT EXISTS DCR_CONSOLE.UI   COMMENT = 'Streamlit object + stages (Track A).';

GRANT OWNERSHIP ON DATABASE DCR_CONSOLE   TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA DCR_CONSOLE.APP  TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA DCR_CONSOLE.META TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA DCR_CONSOLE.UI   TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;

-- ---------------------------------------------------------------------------
-- 4. Warehouse. APP_WH (XS) is created by the DCR install and is sufficient
--    for API calls; large overlap RUNs may want something bigger.
-- ---------------------------------------------------------------------------
GRANT USAGE ON WAREHOUSE APP_WH TO ROLE DCR_CONSOLE_ROLE;

-- ---------------------------------------------------------------------------
-- 5. Assign the role. Replace with the literal admin username.
--    GRANT does not evaluate functions: TO USER CURRENT_USER() is a syntax error.
-- ---------------------------------------------------------------------------
GRANT ROLE DCR_CONSOLE_ROLE TO ROLE ACCOUNTADMIN;
-- GRANT ROLE DCR_CONSOLE_ROLE TO USER <ADMIN_USERNAME>;

-- ---------------------------------------------------------------------------
-- 6. Verify. Must be run in a session that CAN switch roles: the 3-argument
--    CHECK_PRIVILEGES is for DCR objects (COLLABORATION / REGISTRY), not roles.
-- ---------------------------------------------------------------------------
-- USE ROLE DCR_CONSOLE_ROLE;
-- CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.CHECK_PRIVILEGES(
--   ['CREATE COLLABORATION','JOIN COLLABORATION','REVIEW COLLABORATION',
--    'VIEW COLLABORATIONS','REGISTER DATA OFFERING','REGISTER TEMPLATE','CREATE REGISTRY']);
