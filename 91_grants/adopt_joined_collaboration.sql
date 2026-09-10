-- ============================================================================
-- Adopt a collaboration that was JOINED by a DIFFERENT role.
--
-- WHY THIS EXISTS
-- The role that calls JOIN OWNS everything the join creates:
--     SFDCR_<collab>        (application, one app role per operation)
--     SFDCR_LOCAL_<collab>  (database holding the local views)
--
-- JOIN cannot be called from inside a stored procedure — it invokes
-- SYSTEM$ACCEPT_LEGAL_TERMS, and Snowflake rejects side-effecting functions in
-- nested context. So if an admin joins from a worksheet while the app runs as
-- DCR_CONSOLE_ROLE, the console cannot see or operate on the collaboration and
-- you get, in order:
--     Database 'SFDCR_LOCAL_<collab>' does not exist or not authorized
--     003102 (42501): Grant not executed: Insufficient privileges.
--
-- IN PRODUCTION, PREFER: have DCR_CONSOLE_ROLE perform the JOIN itself (the
-- Streamlit app does this, because Streamlit statements run at session level).
-- Then none of this is needed.
--
-- Replace <COLLAB> with the UPPERCASE collaboration name.
-- ============================================================================

USE ROLE ACCOUNTADMIN;

SET COLLAB_APP = 'SFDCR_<COLLAB>';          -- <-- change me
SET COLLAB_DB  = 'SFDCR_LOCAL_<COLLAB>';    -- <-- change me

-- ---------------------------------------------------------------------------
-- 1. The local views database.
-- ---------------------------------------------------------------------------
-- GRANT ALL ON DATABASE SFDCR_LOCAL_<COLLAB>                   TO ROLE DCR_CONSOLE_ROLE;
-- GRANT ALL ON ALL SCHEMAS    IN DATABASE SFDCR_LOCAL_<COLLAB> TO ROLE DCR_CONSOLE_ROLE;
-- GRANT ALL ON FUTURE SCHEMAS IN DATABASE SFDCR_LOCAL_<COLLAB> TO ROLE DCR_CONSOLE_ROLE;

-- ---------------------------------------------------------------------------
-- 2. The collaboration application exposes one application role per operation.
--    DCR's ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE is a wrapper over these, but
--    it only accepts a subset of names (READ, RUN, UPDATE, VIEW DATA OFFERINGS,
--    VIEW TEMPLATES) — so grant the application roles directly to cover
--    LINK LOCAL and PROCESS ACTIVATION too.
--
--    List them first:
--      SHOW APPLICATION ROLES IN APPLICATION SFDCR_<COLLAB>;
-- ---------------------------------------------------------------------------

-- Read and status
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.READ_COLLABORATION_ROLE                 TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.GET_COLLABORATION_STATUS_ROLE           TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.CLEANROOM_PUBLIC_ROLE                   TO ROLE DCR_CONSOLE_ROLE;

-- Discover resources (drives the analysis and activation pickers)
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.COLLABORATION_VIEW_DATA_OFFERINGS_ROLE  TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.COLLABORATION_VIEW_TEMPLATES_ROLE       TO ROLE DCR_CONSOLE_ROLE;

-- Link data: both the partner-facing and the local variety
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.LINK_DATA_OFFERINGS_ROLE                TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.LINK_LOCAL_DATA_OFFERINGS_ROLE          TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.UNLINK_DATA_OFFERINGS_ROLE              TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.UNLINK_LOCAL_DATA_OFFERINGS_ROLE        TO ROLE DCR_CONSOLE_ROLE;

-- Run and activate
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.COLLABORATION_RUN_ROLE                  TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.COLLABORATION_RUN_ACTIVATION_ROLE       TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.VIEW_ACTIVATIONS_ROLE                   TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.PROCESS_ACTIVATION_ROLE                 TO ROLE DCR_CONSOLE_ROLE;

-- History and admin
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.VIEW_ACTIVITY_HISTORY_ROLE              TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.VIEW_UPDATE_REQUESTS_ROLE               TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.MANAGE_UPDATE_REQUEST_ROLE              TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.ADD_TEMPLATE_REQUEST_ROLE               TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.UPDATE_COLLABORATION_ROLE               TO ROLE DCR_CONSOLE_ROLE;
-- GRANT APPLICATION ROLE SFDCR_<COLLAB>.SET_CONFIGURATION_ROLE                  TO ROLE DCR_CONSOLE_ROLE;

-- ---------------------------------------------------------------------------
-- 3. For a collaboration created by another role, also grant the DCR
--    object-level privileges (the supported wrapper path).
-- ---------------------------------------------------------------------------
-- CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE('READ','COLLABORATION','<collab>','DCR_CONSOLE_ROLE');
-- CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE('RUN','COLLABORATION','<collab>','DCR_CONSOLE_ROLE');
-- CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE('UPDATE','COLLABORATION','<collab>','DCR_CONSOLE_ROLE');
-- CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE('VIEW DATA OFFERINGS','COLLABORATION','<collab>','DCR_CONSOLE_ROLE');
-- CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE('VIEW TEMPLATES','COLLABORATION','<collab>','DCR_CONSOLE_ROLE');
