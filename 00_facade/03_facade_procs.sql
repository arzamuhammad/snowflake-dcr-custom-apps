-- ============================================================================
-- DCR Console — P2: facade entry point (single dispatcher).
--
-- Both UI tracks call ONLY this procedure. Operations resolve through an
-- explicit whitelist, never getattr on a caller-supplied name.
--
-- Collaboration API v2 only.
-- ============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE DCR_CONSOLE;
USE SCHEMA APP;

CREATE OR REPLACE PROCEDURE DCR_CONSOLE.APP.INVOKE(OPERATION STRING, PAYLOAD VARIANT)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python','pyyaml')
HANDLER = 'main'
IMPORTS = ('@DCR_CONSOLE.APP.LIB/dcr_specs.py','@DCR_CONSOLE.APP.LIB/dcr_errors.py','@DCR_CONSOLE.APP.LIB/dcr_facade.py','@DCR_CONSOLE.APP.LIB/dcr_runs.py')
COMMENT='Single entry point for the DCR Audience Overlap Console. See OPERATIONS for the whitelist.'
EXECUTE AS OWNER
AS
$$

import json

import dcr_facade as f
import dcr_runs as r

# Explicit operation whitelist: name -> (callable, required keys, optional keys).
# Everything the UI can ask for is enumerated here.
OPERATIONS = {
    # -- 0. health / prerequisites -------------------------------------------
    "HEALTH_CHECK":              (f.health_check,              (), ()),
    "REGISTER_STANDARD_TEMPLATES":(f.register_standard_templates,(), ()),

    # -- 1. my data / register resources ------------------------------------
    "LIST_DATA_OBJECTS":         (f.list_data_objects,          (), ("database", "schema")),
    "DESCRIBE_COLUMNS":          (f.describe_columns,           ("fqn",), ()),
    "REGISTER_OFFERING":         (f.register_offering,          ("config",), ()),
    "LIST_OFFERINGS":            (f.list_offerings,             (), ()),
    "UNREGISTER_OFFERING":       (f.unregister_offering,        ("offering_id",), ()),

    # -- 2. create collaboration -------------------------------------------
    "CREATE_COLLABORATION":      (f.create_collaboration,       ("config",), ("auto_join_warehouse",)),
    "LIST_COLLABORATIONS":       (f.list_collaborations,        (), ()),
    "GET_STATUS":                (f.get_status,                 ("collaboration",), ()),
    "ENSURE_JOINED":             (f.ensure_joined,              ("collaboration",), ()),

    # -- 3. review / join ---------------------------------------------------
    "REVIEW_COLLABORATION":      (f.review_collaboration,       ("source_name", "owner_account"), ("local_name",)),
    "JOIN_COLLABORATION":        (f.join_collaboration,         ("source_name", "owner_account"), ("local_name",)),

    # -- 4. link data -------------------------------------------------------
    "LINK_DATA":                 (f.link_data,                  ("collaboration", "offering_id", "mode"), ("runners",)),
    "UNLINK_DATA":               (f.unlink_data,                ("collaboration", "offering_id", "mode"), ("runners",)),
    "GET_COLLABORATION_DETAIL":  (f.get_collaboration_detail,   ("collaboration",), ()),
    "PREFLIGHT":                 (f.preflight,                  ("collaboration",), ()),

    # -- 5. overlap ---------------------------------------------------------
    "RUN_OVERLAP":               (r.run_overlap,                ("collaboration", "config"), ("use_cache",)),

    # -- 6. activation ------------------------------------------------------
    "RUN_ACTIVATION":            (r.run_activation,             ("collaboration", "config"), ()),
    "LIST_ACTIVATIONS":          (r.list_activations,           ("collaboration",), ()),

    # -- 7. activation inbox ------------------------------------------------
    "IMPORT_ACTIVATION":         (r.import_activation,          ("collaboration", "batch_id", "target_fqn"),
                                                                ("activation_columns", "expected_rows")),
    "GET_IMPORT_PROGRESS":       (r.get_import_progress,        ("import_id",), ()),

    # -- 8. history ---------------------------------------------------------
    "ACTIVITY_HISTORY":          (r.activity_history,           ("collaboration",), ()),

    # -- 9. admin -----------------------------------------------------------
    "LIST_UPDATE_REQUESTS":      (r.list_update_requests,       ("collaboration",), ()),
    "APPROVE_UPDATE_REQUEST":    (r.approve_update_request,     ("collaboration", "request_id"), ()),
    "REJECT_UPDATE_REQUEST":     (r.reject_update_request,      ("collaboration", "request_id", "reason"), ()),
    "ADD_TEMPLATE":              (r.add_template,               ("collaboration", "template_id", "runners"), ()),
    "TEARDOWN_OR_LEAVE":         (r.teardown_or_leave,          ("collaboration", "mode"), ()),

    # -- app RBAC -----------------------------------------------------------
    "GET_APP_ROLE":              (r.get_app_role,               (), ("username",)),
    "SET_APP_ROLE":              (r.set_app_role,               ("username", "app_role"), ("notes",)),
}


def main(session, operation, payload):
    op = (operation or "").strip().upper()

    if op in ("", "LIST_OPERATIONS", "HELP"):
        return {
            "ok": True,
            "operation": "LIST_OPERATIONS",
            "data": {
                "operations": sorted(
                    {"name": k, "required": list(v[1]), "optional": list(v[2])}["name"]
                    for k, v in OPERATIONS.items()
                ),
                "signatures": {
                    k: {"required": list(v[1]), "optional": list(v[2])}
                    for k, v in sorted(OPERATIONS.items())
                },
            },
        }

    if op not in OPERATIONS:
        close = sorted(k for k in OPERATIONS if k.startswith(op[:4]))
        return {
            "ok": False,
            "operation": op,
            "error": {
                "code": "UNKNOWN_OPERATION",
                "title": f"'{op}' is not a facade operation",
                "cause": "The operation name is not in the whitelist.",
                "remediation": (f"Did you mean: {', '.join(close)}? " if close else "")
                               + "Call INVOKE('LIST_OPERATIONS', NULL) for the full list.",
                "sql_fix": None,
                "retryable": False,
                "severity": "error",
            },
        }

    fn, required, optional = OPERATIONS[op]

    # Payload arrives as a VARIANT; Snowpark may hand it over already parsed.
    if payload is None:
        args = {}
    elif isinstance(payload, dict):
        args = dict(payload)
    elif isinstance(payload, str):
        try:
            args = json.loads(payload)
        except Exception:
            return {
                "ok": False, "operation": op,
                "error": {
                    "code": "INVALID_PAYLOAD",
                    "title": "Payload is not valid JSON",
                    "cause": "The payload string could not be parsed as a JSON object.",
                    "remediation": "Pass an OBJECT_CONSTRUCT(...) or PARSE_JSON('{...}') value.",
                    "sql_fix": None, "retryable": False, "severity": "error",
                },
            }
    else:
        args = dict(payload)

    # Normalise keys so callers may use either case.
    args = {str(k).lower(): v for k, v in args.items()}

    missing = [k for k in required if args.get(k) in (None, "")]
    if missing:
        return {
            "ok": False, "operation": op,
            "error": {
                "code": "MISSING_ARGUMENT",
                "title": f"{op} is missing: {', '.join(missing)}",
                "cause": f"{op} requires {', '.join(required) or 'no arguments'}.",
                "remediation": f"Add {', '.join(missing)} to the payload. "
                               f"Optional arguments: {', '.join(optional) or 'none'}.",
                "sql_fix": None, "retryable": False, "severity": "error",
            },
        }

    # Pass only recognised keys, plus ui_track for the audit trail.
    accepted = set(required) | set(optional)
    call_args = {k: v for k, v in args.items() if k in accepted}
    ui_track = str(args.get("ui_track") or "sql")

    return fn(session, ui_track=ui_track, **call_args)
';
$$;

-- Production: the console role must own this so it executes with DCR_CONSOLE_ROLE
-- privileges. NOTE: the role that owns this must also be the role that JOINed
-- each collaboration, because JOIN creates objects owned by the calling role.
-- GRANT OWNERSHIP ON PROCEDURE DCR_CONSOLE.APP.INVOKE(STRING, VARIANT)
--     TO ROLE DCR_CONSOLE_ROLE COPY CURRENT GRANTS;

CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL);
