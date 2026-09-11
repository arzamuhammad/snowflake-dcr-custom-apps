"""
DCR Console — error decoder.

Collaboration API failures surface as Python tracebacks from inside DCR's own
stored procedures. The useful part is buried, and the remediation is rarely
obvious. This module turns a raw error string into something a UI can act on:

    {
      "code": "REFERENCE_USAGE_MISSING",
      "title": "A grant is missing on the shared database",
      "cause": "...",
      "remediation": "...",
      "sql_fix": "GRANT REFERENCE_USAGE ON DATABASE ... ;",
      "retryable": true,
      "severity": "blocked"
    }

``sql_fix`` is what powers the app's one-click "Grant and retry" — it is derived
from the identifiers DCR itself names in the message, never guessed.

Collaboration API v2 only. The v1 remedy of granting to the named share
``SAMOOHA_BY_SNOWFLAKE_APP_SHARE`` is obsolete and is never emitted.
"""

from __future__ import annotations

import re
from typing import Any

UNKNOWN = {
    "code": "UNKNOWN",
    "title": "Unrecognised Data Clean Rooms error",
    "cause": "The Collaboration API returned an error the console does not recognise.",
    "remediation": (
        "Read the raw message below. If it names a missing grant, apply it and retry. "
        "Otherwise capture the query id and check the collaboration status."
    ),
    "sql_fix": None,
    "retryable": False,
    "severity": "error",
}


def _last_line(msg: str) -> str:
    """DCR re-raises with the real exception on the final traceback line."""
    lines = [ln.strip() for ln in msg.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else msg


def decode_error(raw: str) -> dict[str, Any]:
    """Classify a raw DCR error string into an actionable structure."""
    if not raw:
        return dict(UNKNOWN)

    msg = str(raw)
    tail = _last_line(msg)

    # -- Missing WITH GRANT OPTION on the source data -----------------------
    # LINK_DATA_OFFERING and LINK_LOCAL_DATA_OFFERING do not merely READ the
    # source data: they GRANT access on it to the collaboration application. A
    # role can only pass on a privilege it holds WITH GRANT OPTION, so plain
    # SELECT/USAGE produces a bare "Grant not executed" with no hint as to which
    # grant is missing. Checked before the REFERENCE_USAGE branch because that
    # message can also mention the word "grant".
    if "Grant not executed" in msg:
        proc = None
        m = re.search(r"in function ([A-Z_]+) with handler", msg)
        if m:
            proc = m.group(1)
        return {
            "code": "GRANT_OPTION_MISSING",
            "title": "The console cannot pass on access to your data",
            "cause": (
                f"{proc or 'The operation'} does not just read the source data — it grants "
                "access on it to the collaboration application. A role can only grant a "
                "privilege it holds WITH GRANT OPTION, and this role does not."
            ),
            "remediation": (
                "Grant USAGE and SELECT on the source database, schema and tables to the "
                "console role WITH GRANT OPTION, then retry. Replace MY_DB.MY_SCHEMA below. "
                "A second possibility: the collaboration was joined by a different role, "
                "which now owns the collaboration application — see "
                "91_grants/adopt_joined_collaboration.sql."
            ),
            "sql_fix": (
                "GRANT USAGE  ON DATABASE MY_DB           TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;\n"
                "GRANT USAGE  ON SCHEMA   MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;\n"
                "GRANT SELECT ON ALL TABLES IN SCHEMA MY_DB.MY_SCHEMA "
                "TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;"
            ),
            "retryable": True,
            "severity": "blocked",
        }

    # -- Side-effecting function inside a stored procedure -------------------
    # COLLABORATION.JOIN calls SYSTEM$ACCEPT_LEGAL_TERMS. The console routes JOIN
    # at session level for exactly this reason, so hitting it means something is
    # calling JOIN through the facade.
    if "function with side effects" in msg or "SYSTEM$ACCEPT_LEGAL_TERMS" in msg:
        return {
            "code": "NEST_UNSAFE_OPERATION",
            "title": "This operation cannot run inside a stored procedure",
            "cause": (
                "The operation calls a function with side effects "
                "(SYSTEM$ACCEPT_LEGAL_TERMS for JOIN), and Snowflake rejects those in a "
                "nested procedure context."
            ),
            "remediation": (
                "Console bug: JOIN must be issued at session level, not through "
                "DCR_CONSOLE.APP.INVOKE. The Invitations screen does this correctly."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "error",
        }

    # -- Secondary roles active ----------------------------------------------
    # DCR refuses to run REGISTER_DATA_OFFERING (and other REGISTRY/COLLABORATION
    # procedures) while the session has secondary roles enabled, because it cannot
    # determine which role is granting access to the underlying data.
    #
    # The facade cannot fix this itself: the remedy is USE SECONDARY ROLES NONE,
    # a USE statement, and those are rejected inside a stored procedure. So this
    # has to be set on the session before INVOKE is called. Both UIs do that at
    # startup; reaching this branch means it did not take effect.
    if "SecondaryRolesNotSupported" in msg or "Secondary roles must be disabled" in msg:
        return {
            "code": "SECONDARY_ROLES_ACTIVE",
            "title": "Secondary roles must be disabled for this operation",
            "cause": (
                "Data Clean Rooms refuses to register or link data while the session has "
                "secondary roles enabled, because the effective privilege set is then "
                "ambiguous. The session that called the console still has them active."
            ),
            "remediation": (
                "Run USE SECONDARY ROLES NONE on the session, then retry. This cannot be "
                "done inside DCR_CONSOLE.APP.INVOKE — USE is not a permitted statement in "
                "a stored procedure — so both UIs issue it at session level on startup. "
                "If you are seeing this in an app, reload the page to re-run startup; if "
                "you are calling INVOKE from a worksheet, run the statement yourself first."
            ),
            "sql_fix": "USE SECONDARY ROLES NONE;",
            "retryable": True,
            "severity": "blocked",
        }

    # -- Acting user has no profile -------------------------------------------
    # DCR requires first_name, last_name and email on whoever performs a JOIN,
    # because joining accepts legal terms and the agreement needs a named person.
    #
    # This is unfixable from a deployed app rather than merely inconvenient: an
    # SPCS managed service identity is not a user object, so ALTER USER has
    # nothing to target. It surfaces as INSTALLATION_FAILED, and to an app caller
    # as a gateway timeout, because installation stalls rather than returning.
    if "add your first/last name and email" in msg or "090655" in msg:
        return {
            "code": "USER_PROFILE_INCOMPLETE",
            "title": "The user performing this action has no profile",
            "cause": (
                "Joining a collaboration accepts legal terms, so Data Clean Rooms requires "
                "first_name, last_name and email on the acting user. The identity used here "
                "has none. If this came from an app, the identity is an SPCS managed service "
                "account, which is not a user object and cannot be given a profile at all."
            ),
            "remediation": (
                "Run REVIEW and JOIN as a person, in a worksheet, not through an app. Set the "
                "profile first if it is missing. Afterwards the collaboration is usable from "
                "the app as normal — this only blocks joining."
            ),
            "sql_fix": (
                "-- Check what is missing:\n"
                "SHOW USERS LIKE CURRENT_USER();\n"
                "\n"
                "ALTER USER <username> SET\n"
                "    first_name = '<first>',\n"
                "    last_name  = '<last>',\n"
                "    email      = '<email>';"
            ),
            "retryable": False,
            "severity": "blocked",
        }

    # -- Wrong collaboration status for the requested action ------------------
    # Most often LEAVE attempted from INSTALLATION_FAILED, which DCR rejects. The
    # way out is REVIEW again followed by JOIN; LEAVE only works once the
    # collaboration is already on its way out.
    if "InvalidCollaborationStatusError" in msg or "action requires the collaboration status" in msg:
        current = None
        m = re.search(r"Current status:\s*([A-Z_]+)", msg)
        if m:
            current = m.group(1)
        stuck_installing = current in {"INSTALLATION_FAILED", "CREATE_FAILED", "JOIN_FAILED"}
        return {
            "code": "WRONG_COLLABORATION_STATUS",
            "title": (
                f"The collaboration is {current} and cannot do this yet"
                if current
                else "The collaboration is in the wrong state for this action"
            ),
            "cause": (
                "Each operation is only valid from certain statuses. "
                + (
                    f"{current} is a failure state: the local install did not complete, so there "
                    "is nothing consistent to leave or run against."
                    if stuck_installing
                    else "DCR listed the statuses it will accept in the message below."
                )
            ),
            "remediation": (
                "Recover by calling REVIEW again with the same source name, then JOIN. LEAVE is "
                "rejected from a failed install, so it is not the way out. Read the DETAILS "
                "column of GET_STATUS first — an incomplete user profile and a nested "
                "SYSTEM$ACCEPT_LEGAL_TERMS are the two causes seen in practice."
                if stuck_installing
                else "Check GET_STATUS, wait for a valid status, then retry."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "blocked",
        }

    # -- Missing REFERENCE_USAGE on the shared database ----------------------
    # Two variants: plain REFERENCE_USAGE (JOIN) and WITH GRANT OPTION
    # (REGISTER/LINK). DCR names the database, and sometimes the SCO share.
    if "ReferenceUsage" in msg or "REFERENCE_USAGE" in msg:
        db = None
        m = re.search(r"on database '([^']+)'", msg, re.IGNORECASE)
        if m:
            db = m.group(1)
        else:
            m = re.search(r"databases?:?\s*\[?'?([A-Za-z_][\w$]*)", msg)
            if m:
                db = m.group(1)

        role = None
        m = re.search(r"role '\"?([A-Za-z_][\w$]*)\"?'", msg)
        if m:
            role = m.group(1)

        share = None
        m = re.search(r"TO SHARE ([A-Za-z_][\w$]*)", msg, re.IGNORECASE)
        if m:
            share = m.group(1)

        needs_grant_option = "WITH GRANT OPTION" in msg.upper()

        if share:
            fix = f"GRANT REFERENCE_USAGE ON DATABASE {db} TO SHARE {share};"
            target = f"share {share}"
        elif db and role:
            suffix = " WITH GRANT OPTION" if needs_grant_option else ""
            fix = f'GRANT REFERENCE_USAGE ON DATABASE {db} TO ROLE "{role}"{suffix};'
            target = f"role {role}"
        else:
            fix = None
            target = "the role or share named in the raw message"

        return {
            "code": "REFERENCE_USAGE_MISSING",
            "title": "A grant is missing on the shared database",
            "cause": (
                f"Data Clean Rooms needs REFERENCE_USAGE"
                f"{' WITH GRANT OPTION' if needs_grant_option else ''} on "
                f"{db or 'the source database'} for {target}. This is expected the first "
                "time a database is shared into a clean room — it is not a bug."
            ),
            "remediation": (
                "Apply the grant below as ACCOUNTADMIN (or the database owner), then retry. "
                "Do NOT grant to SAMOOHA_BY_SNOWFLAKE_APP_SHARE — that named share belongs "
                "to the deprecated v1 interface and does not exist here."
            ),
            "sql_fix": fix,
            "retryable": True,
            "severity": "blocked",
        }

    # -- Invitation not found ----------------------------------------------
    if "CollaborationInvitationNotFound" in msg or "Pending invitation for collaboration" in msg:
        return {
            "code": "INVITATION_NOT_FOUND",
            "title": "No pending invitation to review",
            "cause": (
                "Three things produce this. (1) You have already joined — the collaboration "
                "row has a local name, so Review/Join is complete. (2) A Leave was started "
                "and is stuck at LOCAL_DROP_PENDING; Review is impossible mid-drop. "
                "(3) A previous join failed and left the state unusable."
            ),
            "remediation": (
                "Check the status first. If it is LOCAL_DROP_PENDING, finish the Leave (call "
                "it a second time) — a fresh invitation reappears afterwards and you can "
                "join again without the owner recreating anything. If a join genuinely "
                "failed, the owner must tear down and recreate."
            ),
            "sql_fix": None,
            "retryable": True,
            "severity": "warning",
        }

    # -- Templates not registered ------------------------------------------
    if re.search(r"[Tt]emplates? '?standard_audience_overlap", msg) and "do not exist" in msg:
        return {
            "code": "STANDARD_TEMPLATES_MISSING",
            "title": "The standard audience-overlap templates are not registered",
            "cause": (
                "standard_audience_overlap_v0 and standard_audience_overlap_activation_v0 "
                "are NOT installed automatically with Data Clean Rooms. They must be "
                "registered once per account, in every participating account."
            ),
            "remediation": "Register them, then retry. The Health Check screen does this for you.",
            "sql_fix": "CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.REGISTRY.REGISTER_STANDARD_DCR_TEMPLATES();",
            "retryable": True,
            "severity": "blocked",
        }

    # -- Privacy threshold --------------------------------------------------
    if "threshold" in msg.lower() and ("privacy" in msg.lower() or "below" in msg.lower()):
        return {
            "code": "BELOW_PRIVACY_THRESHOLD",
            "title": "Result suppressed to protect privacy",
            "cause": (
                "Fewer than 5 distinct records matched, so the clean room returns NULL "
                "rather than a count. This is the privacy guarantee working as designed, "
                "not a failure."
            ),
            "remediation": (
                "Broaden the audience: add a fallback match key as another waterfall level, "
                "remove restrictive filters, drop a group-by dimension, or use a larger "
                "input segment."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "warning",
        }

    # -- Unauthorised column ------------------------------------------------
    m = re.search(r"[Uu]nauthorized columns?:?\s*([^\n]+)", msg)
    if m:
        cols = m.group(1).strip()
        return {
            "code": "UNAUTHORIZED_COLUMN",
            "title": f"Column not permitted by policy: {cols}",
            "cause": (
                "The column is not allowed for this operation. The usual reason is the "
                "join-column rename: a column declared 'join_standard' is exposed in the "
                "shared view under its column_type (HASHED_MSISDN becomes "
                "HASHED_PHONE_SHA256), so the source name is rejected. Otherwise the data "
                "owner did not mark the column analysis- or activation-allowed."
            ),
            "remediation": (
                "Use the exposed column name shown in the Link Data screen "
                "(TEMPLATE_JOIN_COLUMNS / ANALYSIS_ALLOWED_COLUMNS / "
                "ACTIVATION_ALLOWED_COLUMNS). If the column genuinely should be permitted, "
                "the data owner must re-register the offering with the right flag."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "error",
        }

    # -- Spec validation ----------------------------------------------------
    if "SpecValidationError" in msg or "Invalid YAML format" in msg:
        detail = tail.split(":", 1)[-1].strip() if ":" in tail else tail
        return {
            "code": "SPEC_VALIDATION",
            "title": "The generated spec was rejected",
            "cause": f"The API could not validate the spec: {detail}",
            "remediation": (
                "This should not happen — the console generates specs with a YAML "
                "serialiser precisely to avoid formatting faults. Treat it as a console "
                "bug and report the request payload from the audit log."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "error",
        }

    # -- Duplicate registrations -------------------------------------------
    if "AlreadyExists" in msg:
        return {
            "code": "ALREADY_EXISTS",
            "title": "That name and version is already registered",
            "cause": "Registry entries are keyed by name plus version.",
            "remediation": (
                "Bump the version to publish a change, or re-register the same name and "
                "version deliberately to overwrite it."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "warning",
        }

    # -- Teardown before join ----------------------------------------------
    if "must join it before you can tear it down" in msg:
        return {
            "code": "TEARDOWN_BEFORE_JOIN",
            "title": "Join the collaboration before tearing it down",
            "cause": "You initialised the collaboration but never joined it, so there is nothing local to remove.",
            "remediation": "Join first, then tear down.",
            "sql_fix": None,
            "retryable": True,
            "severity": "warning",
        }

    # -- Region / fulfilment ------------------------------------------------
    if "not fulfilled to your current region" in msg:
        return {
            "code": "CROSS_REGION_NOT_FULFILLED",
            "title": "The collaboration is not available in your region",
            "cause": (
                "Either the Data Clean Rooms installation is out of date, or this is a "
                "cross-region collaboration without Cross-Cloud Auto-Fulfillment enabled."
            ),
            "remediation": (
                "Update the Data Clean Rooms installation in both accounts, and enable "
                "Cross-Cloud Auto-Fulfillment if the collaborators are in different regions."
            ),
            "sql_fix": None,
            "retryable": True,
            "severity": "blocked",
        }

    # -- Restricted session -------------------------------------------------
    if "Current session is restricted" in msg and "USE ROLE" in msg:
        return {
            "code": "SESSION_ROLE_RESTRICTED",
            "title": "This session cannot switch roles",
            "cause": (
                "The connection (typically a programmatic access token) is pinned to a "
                "single role, so USE ROLE is refused."
            ),
            "remediation": (
                "No role switch is needed: the console's procedures already execute with "
                "the privileges of DCR_CONSOLE_ROLE as their owner."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "warning",
        }

    # -- Session variable size (should be impossible here) ------------------
    if "exceeds size limit for variables" in msg:
        return {
            "code": "SPEC_TOO_LARGE_FOR_VARIABLE",
            "title": "Spec assigned to a session variable",
            "cause": (
                "A SQL session variable caps at 256 bytes, far below a real offering spec."
            ),
            "remediation": (
                "Console bug: specs must be passed as procedure arguments, never via SET."
            ),
            "sql_fix": None,
            "retryable": False,
            "severity": "error",
        }

    out = dict(UNKNOWN)
    out["cause"] = f"{UNKNOWN['cause']} Last line: {tail}"
    return out
