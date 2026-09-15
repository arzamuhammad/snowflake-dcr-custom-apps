"""
DCR Console — facade operations.

This is the ONLY module that calls the Snowflake Data Clean Rooms Collaboration
API v2. Both UI tracks (Streamlit, React) reach DCR exclusively through the thin
stored-procedure wrappers in 03_facade_procs.sql, which delegate here. The
benefit is that the tricky, easy-to-get-wrong logic exists once rather than
twice in two languages.

Every operation:
  * validates input and builds specs via ``dcr_specs`` (never string YAML),
  * decodes failures via ``dcr_errors`` into an actionable structure,
  * writes an audit row to ``DCR_CONSOLE.META.AUDIT_LOG``,
  * returns a uniform envelope: ``{"ok", "data"|"error", "duration_ms", ...}``.

Collaboration API v2 only. No reference anywhere to the deprecated v1 Native App
interface (``PROVIDER.*`` / ``CONSUMER.*`` procedures, ``register_db``,
``SAMOOHA_BY_SNOWFLAKE_APP_SHARE``).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import dcr_errors
import dcr_specs as specs

DCR = "SAMOOHA_BY_SNOWFLAKE_LOCAL_DB"
REGISTRY = f"{DCR}.REGISTRY"
COLLAB = f"{DCR}.COLLABORATION"
ADMIN = f"{DCR}.ADMIN"
LIBRARY = f"{DCR}.LIBRARY"

META = "DCR_CONSOLE.META"

#: Minimum Data Clean Rooms version this console is validated against.
MIN_DCR_VERSION = 14.6

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
#: Collaboration names and offering ids are lowercase-ish identifiers.
_DCR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Guards. UI input reaches SQL, so identifiers are whitelisted rather than
# escaped: an identifier that fails these checks cannot be made safe by quoting.
# ---------------------------------------------------------------------------


def _ident(value: str, what: str) -> str:
    v = str(value)
    if not _IDENT.match(v):
        raise specs.SpecError(f"{what} '{v}' is not a valid Snowflake identifier.", field=what)
    return v


def _dcr_name(value: str, what: str) -> str:
    v = str(value)
    if not _DCR_NAME.match(v):
        raise specs.SpecError(f"{what} '{v}' contains characters that are not allowed.", field=what)
    return v


def _fqn(value: str, what: str) -> str:
    v = str(value)
    parts = v.split(".")
    if len(parts) != 3:
        raise specs.SpecError(f"{what} must be DATABASE.SCHEMA.OBJECT, got '{v}'.", field=what)
    for p in parts:
        _ident(p, what)
    return v


def _sql_array(values: list[str], what: str) -> str:
    """Render a validated identifier list as an ARRAY_CONSTRUCT literal.

    DCR takes ARRAY arguments that cannot be bound as parameters, so the values
    are validated as identifiers first and then interpolated.
    """
    safe = [_ident(v, what) for v in values]
    inner = ", ".join(f"'{v}'" for v in safe)
    return f"ARRAY_CONSTRUCT({inner})"


# ---------------------------------------------------------------------------
# Result envelope + audit
# ---------------------------------------------------------------------------


def _rows(session, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    result = session.sql(sql, params=params) if params else session.sql(sql)
    return [r.as_dict() for r in result.collect()]


def _scalar(session, sql: str, params: list[Any] | None = None) -> Any:
    rows = _rows(session, sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def _audit(
    session,
    *,
    operation: str,
    outcome: str,
    ui_track: str = "sql",
    collaboration: str | None = None,
    target: str | None = None,
    request: Any = None,
    generated_spec: str | None = None,
    error_raw: str | None = None,
    error_decoded: Any = None,
    duration_ms: int | None = None,
) -> None:
    """Write one audit row. Never allowed to break the operation it records."""
    try:
        session.sql(
            f"""
            INSERT INTO {META}.AUDIT_LOG
              (ACTOR_USER, ACTOR_ROLE, UI_TRACK, OPERATION, COLLABORATION, TARGET,
               REQUEST, GENERATED_SPEC, OUTCOME, ERROR_RAW, ERROR_DECODED, DURATION_MS, QUERY_ID)
            SELECT CURRENT_USER(), CURRENT_ROLE(), ?, ?, ?, ?,
                   TRY_PARSE_JSON(?), ?, ?, ?, TRY_PARSE_JSON(?), ?, ?
            """,
            params=[
                ui_track, operation, collaboration, target,
                json.dumps(request) if request is not None else None,
                generated_spec, outcome, error_raw,
                json.dumps(error_decoded) if error_decoded is not None else None,
                duration_ms, session.sql("SELECT LAST_QUERY_ID()").collect()[0][0],
            ],
        ).collect()
    except Exception:  # pragma: no cover - auditing must never mask a real error
        pass


def _run(
    session,
    operation: str,
    fn: Callable[[], Any],
    *,
    ui_track: str = "sql",
    collaboration: str | None = None,
    target: str | None = None,
    request: Any = None,
) -> dict[str, Any]:
    """Execute an operation, audit it, and return a uniform envelope."""
    started = time.time()
    generated_spec: str | None = None
    try:
        data = fn()
        if isinstance(data, dict):
            generated_spec = data.get("_spec")
            data = {k: v for k, v in data.items() if k != "_spec"}
        elapsed = int((time.time() - started) * 1000)
        _audit(
            session, operation=operation, outcome="SUCCESS", ui_track=ui_track,
            collaboration=collaboration, target=target, request=request,
            generated_spec=generated_spec, duration_ms=elapsed,
        )
        return {"ok": True, "operation": operation, "data": data, "duration_ms": elapsed}

    except specs.SpecError as e:
        elapsed = int((time.time() - started) * 1000)
        decoded = {
            "code": "INVALID_INPUT", "title": "The request is not valid",
            "cause": e.message, "remediation": e.hint or "Correct the highlighted field.",
            "sql_fix": None, "retryable": False, "severity": "error", "field": e.field,
        }
        _audit(
            session, operation=operation, outcome="BLOCKED", ui_track=ui_track,
            collaboration=collaboration, target=target, request=request,
            error_raw=e.message, error_decoded=decoded, duration_ms=elapsed,
        )
        return {"ok": False, "operation": operation, "error": decoded, "duration_ms": elapsed}

    except Exception as e:  # noqa: BLE001 - deliberately broad: decode and report
        elapsed = int((time.time() - started) * 1000)
        raw = str(e)
        decoded = dcr_errors.decode_error(raw)
        _audit(
            session, operation=operation, outcome="FAILED", ui_track=ui_track,
            collaboration=collaboration, target=target, request=request,
            generated_spec=generated_spec, error_raw=raw, error_decoded=decoded,
            duration_ms=elapsed,
        )
        return {
            "ok": False, "operation": operation, "error": decoded,
            "error_raw": raw, "duration_ms": elapsed,
        }


# ---------------------------------------------------------------------------
# Module 0 — health / prerequisites
# ---------------------------------------------------------------------------


def health_check(session, ui_track: str = "sql") -> dict[str, Any]:
    """Traffic-light prerequisite report.

    Deliberately does not raise: a red light is data the UI renders, not an
    exception. Each failing check carries its own fix.
    """

    def _work() -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(name, status, detail, fix=None, blocking=True):
            checks.append({"name": name, "status": status, "detail": detail,
                           "fix": fix, "blocking": blocking})

        # Account identity — needed verbatim by the partner.
        try:
            row = _rows(session, """
                SELECT CURRENT_ORGANIZATION_NAME()||'.'||CURRENT_ACCOUNT_NAME() AS ACCOUNT,
                       CURRENT_REGION() AS REGION, CURRENT_USER() AS USR, CURRENT_ROLE() AS ROL
            """)[0]
            add("Account identity", "ok",
                f"{row['ACCOUNT']} in {row['REGION']}, running as {row['ROL']}", blocking=False)
            account = row["ACCOUNT"]
        except Exception as e:
            add("Account identity", "fail", str(e))
            account = None

        # Is the Collaboration API mounted at all?
        try:
            mounted = _scalar(session, f"CALL {LIBRARY}.CHECK_MOUNT_STATUS()")
            if str(mounted).lower() == "true":
                add("Collaboration API mounted", "ok", "CHECK_MOUNT_STATUS returned true")
            else:
                add("Collaboration API mounted", "fail",
                    f"CHECK_MOUNT_STATUS returned {mounted}",
                    "Re-run the mount as ACCOUNTADMIN: "
                    "CALL SAMOOHA_BY_SNOWFLAKE.APP_SCHEMA.PREPARE_MOUNT_SCRIPT(); then "
                    "EXECUTE IMMEDIATE FROM @SAMOOHA_BY_SNOWFLAKE.APP_SCHEMA.MOUNT_CODE_STAGE/dcr_loader.sql;")
        except Exception as e:
            add("Collaboration API mounted", "fail", str(e),
                "Install 'Snowflake Data Clean Rooms' from the Marketplace, then mount the API.")

        # Version floor.
        try:
            version = float(_scalar(session, f"SELECT VERSION FROM {DCR}.ADMIN.VERSION"))
            if version >= MIN_DCR_VERSION:
                add("Data Clean Rooms version", "ok", f"{version} (minimum {MIN_DCR_VERSION})")
            else:
                add("Data Clean Rooms version", "fail",
                    f"{version} is below the required {MIN_DCR_VERSION}",
                    f"CALL {LIBRARY}.ENABLE_LOCAL_DB_AUTO_UPGRADES();")
        except Exception as e:
            add("Data Clean Rooms version", "warn", str(e), blocking=False)

        # DCR capability privileges for the role the facade runs as.
        #
        # ADMIN.CHECK_PRIVILEGES cannot be called from inside a stored procedure:
        # it issues a USE statement internally, and Snowflake rejects that in a
        # nested context with "Unsupported statement type 'USE'". Verified on DCR
        # 17.5. So we attempt it, and on that specific failure we fall back to a
        # functional check plus the exact SQL to run in a worksheet, rather than
        # reporting a scary error for something that is merely unverifiable here.
        needed = ["CREATE COLLABORATION", "JOIN COLLABORATION", "REVIEW COLLABORATION",
                  "VIEW COLLABORATIONS", "REGISTER DATA OFFERING", "REGISTER TEMPLATE"]
        arr = ", ".join(f"'{p}'" for p in needed)
        worksheet_sql = f"CALL {ADMIN}.CHECK_PRIVILEGES(ARRAY_CONSTRUCT({arr}));"
        try:
            privs = _rows(session, f"CALL {ADMIN}.CHECK_PRIVILEGES(ARRAY_CONSTRUCT({arr}))")
            missing = [p["PRIVILEGE"] for p in privs if not p["HAS_PRIVILEGE"]]
            if missing:
                add("DCR privileges", "fail", f"Missing: {', '.join(missing)}",
                    "Grant each with "
                    f"CALL {ADMIN}.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE('<privilege>', CURRENT_ROLE());")
            else:
                add("DCR privileges", "ok", "All required capability privileges held")
        except Exception as e:
            if "Unsupported statement type 'USE'" in str(e):
                add("DCR privileges", "info",
                    "Cannot be verified from inside the console: CHECK_PRIVILEGES issues a "
                    "USE statement, which Snowflake does not allow in a nested procedure. "
                    "The read privileges are proven by the checks below succeeding.",
                    f"To verify explicitly, run this in a worksheet: {worksheet_sql}",
                    blocking=False)
            else:
                add("DCR privileges", "warn", str(e), worksheet_sql, blocking=False)

        # The two standard templates. Not installed automatically — this is the
        # most common day-one failure, and it is one click to fix.
        try:
            tmpl = {t["TEMPLATE_ID"] for t in _rows(session, f"CALL {REGISTRY}.VIEW_REGISTERED_TEMPLATES()")}
            missing = [t for t in (specs.STANDARD_OVERLAP_TEMPLATE, specs.STANDARD_ACTIVATION_TEMPLATE)
                       if t not in tmpl]
            if missing:
                add("Standard overlap templates", "fail", f"Not registered: {', '.join(missing)}",
                    f"CALL {REGISTRY}.REGISTER_STANDARD_DCR_TEMPLATES();")
            else:
                add("Standard overlap templates", "ok", "Both standard templates registered")
        except Exception as e:
            add("Standard overlap templates", "fail", str(e),
                f"CALL {REGISTRY}.REGISTER_STANDARD_DCR_TEMPLATES();")

        # Registered offerings — informational, but zero means nothing to share.
        try:
            offerings = _rows(session, f"CALL {REGISTRY}.VIEW_REGISTERED_DATA_OFFERINGS()")
            add("Registered data offerings", "ok" if offerings else "warn",
                f"{len(offerings)} registered",
                None if offerings else "Register a table on the My Data screen.",
                blocking=False)
        except Exception as e:
            add("Registered data offerings", "warn", str(e), blocking=False)

        # Collaborations visible to this role. Zero is normal on a fresh account,
        # but is also what a missing object-level grant looks like.
        try:
            collabs = _rows(session, f"CALL {COLLAB}.VIEW_COLLABORATIONS()")
            add("Visible collaborations", "ok" if collabs else "warn",
                f"{len(collabs)} visible to {_scalar(session, 'SELECT CURRENT_ROLE()')}",
                None if collabs else
                "If you expect collaborations here, they were created by a different role. "
                "DCR privileges are per-role: grant this role READ/RUN/UPDATE/VIEW DATA "
                "OFFERINGS/VIEW TEMPLATES on each collaboration via "
                f"{ADMIN}.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE.",
                blocking=False)
        except Exception as e:
            add("Visible collaborations", "warn", str(e), blocking=False)

        blocking_failures = [c for c in checks if c["status"] == "fail" and c["blocking"]]
        return {
            "account": account,
            "ready": not blocking_failures,
            "checks": checks,
            "blocking_failures": [c["name"] for c in blocking_failures],
        }

    return _run(session, "HEALTH_CHECK", _work, ui_track=ui_track)


def register_standard_templates(session, ui_track: str = "sql") -> dict[str, Any]:
    """Register the two standard audience-overlap templates. Idempotent."""

    def _work() -> dict[str, Any]:
        _rows(session, f"CALL {REGISTRY}.REGISTER_STANDARD_DCR_TEMPLATES()")
        tmpl = [t["TEMPLATE_ID"] for t in _rows(session, f"CALL {REGISTRY}.VIEW_REGISTERED_TEMPLATES()")]
        return {"templates": tmpl}

    return _run(session, "REGISTER_STANDARD_TEMPLATES", _work, ui_track=ui_track)


# ---------------------------------------------------------------------------
# Module 1 — my data / register resources
# ---------------------------------------------------------------------------

#: Heuristics that pre-select a sensible column_type in the UI. Suggestions only;
#: the user always confirms, because guessing wrong about PII is unacceptable.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    (r"(hashed|sha256|sha_256).*(email|mail)", "hashed_email_sha256"),
    (r"(email|mail).*(hash|sha)", "hashed_email_sha256"),
    (r"(hashed|sha256).*(phone|msisdn|mobile|hp)", "hashed_phone_sha256"),
    (r"(phone|msisdn|mobile).*(hash|sha)", "hashed_phone_sha256"),
    (r"^(email|email_address)$", "email"),
    (r"^(phone|phone_number|msisdn|mobile_number)$", "phone"),
    (r"(device|maid|idfa|gaid|adid)", "device_id"),
    (r"ip_?address", "ip_address"),
    (r"first_?name", "first_name"),
    (r"last_?name|surname", "last_name"),
)


def _suggest_column_type(name: str) -> str | None:
    lowered = name.lower()
    for pattern, ctype in _TYPE_HINTS:
        if re.search(pattern, lowered):
            return ctype
    return None


def list_data_objects(session, database: str | None = None, schema: str | None = None,
                      ui_track: str = "sql") -> dict[str, Any]:
    """Browse databases, then schemas, then tables and views."""

    def _work() -> dict[str, Any]:
        if not database:
            rows = _rows(session, """
                SELECT DATABASE_NAME AS NAME FROM SNOWFLAKE.INFORMATION_SCHEMA.DATABASES
                WHERE DATABASE_NAME NOT IN ('SNOWFLAKE')
                  AND DATABASE_NAME NOT LIKE 'SAMOOHA%'
                  AND DATABASE_NAME NOT LIKE 'SFDCR%'
                ORDER BY 1
            """)
            return {"level": "database", "items": [r["NAME"] for r in rows]}

        db = _ident(database, "database")
        if not schema:
            rows = _rows(session, f"""
                SELECT SCHEMA_NAME AS NAME FROM {db}.INFORMATION_SCHEMA.SCHEMATA
                WHERE SCHEMA_NAME <> 'INFORMATION_SCHEMA' ORDER BY 1
            """)
            return {"level": "schema", "database": db, "items": [r["NAME"] for r in rows]}

        sch = _ident(schema, "schema")
        rows = _rows(session, f"""
            SELECT TABLE_NAME AS NAME, TABLE_TYPE AS KIND, ROW_COUNT
            FROM {db}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = ? ORDER BY 1
        """, [sch])
        return {
            "level": "object", "database": db, "schema": sch,
            "items": [{"name": r["NAME"], "kind": r["KIND"],
                       "row_count": r["ROW_COUNT"], "fqn": f"{db}.{sch}.{r['NAME']}"} for r in rows],
        }

    return _run(session, "LIST_DATA_OBJECTS", _work, ui_track=ui_track)


def describe_columns(session, fqn: str, ui_track: str = "sql") -> dict[str, Any]:
    """Column list for the offering builder, with suggested categories.

    Every column defaults to ``passthrough`` with ``activation_allowed`` FALSE.
    Defaulting to the most restrictive option is deliberate: an accidental
    activation of a PII column cannot be undone once it leaves the account.
    """

    def _work() -> dict[str, Any]:
        db, sch, tbl = _fqn(fqn, "fqn").split(".")
        rows = _rows(session, f"""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION
            FROM {db}.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION
        """, [sch, tbl])
        if not rows:
            raise specs.SpecError(f"{fqn} has no visible columns, or the role cannot see it.",
                                  field="fqn")

        columns = []
        for r in rows:
            name = r["COLUMN_NAME"]
            hint = _suggest_column_type(name)
            columns.append({
                "name": name,
                "data_type": r["DATA_TYPE"],
                "suggested_category": "join_standard" if hint else "passthrough",
                "suggested_column_type": hint,
                # Restrictive by default. The user opts in.
                "category": "passthrough",
                "column_type": None,
                "activation_allowed": False,
                "exposed_name_preview": specs.exposed_column_name(name, "join_standard", hint)
                if hint else name.upper(),
            })
        return {"fqn": fqn, "columns": columns, "column_types": sorted(specs.COLUMN_TYPES),
                "categories": sorted(specs.CATEGORIES)}

    return _run(session, "DESCRIBE_COLUMNS", _work, ui_track=ui_track, target=fqn)


def register_offering(session, config: dict[str, Any], ui_track: str = "sql") -> dict[str, Any]:
    """Build and register a ``data_offering`` from a UI config."""
    built: dict[str, Any] = {}

    def _work() -> dict[str, Any]:
        nonlocal built
        built = specs.build_offering_spec(config)
        _rows(session, f"CALL {REGISTRY}.REGISTER_DATA_OFFERING(?)", [built["spec_yaml"]])
        return {
            "offering_id": built["offering_id"],
            "datasets": built["datasets"],
            "_spec": built["spec_yaml"],
        }

    return _run(session, "REGISTER_OFFERING", _work, ui_track=ui_track,
                target=config.get("name"), request=config)


def list_offerings(session, ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        rows = _rows(session, f"CALL {REGISTRY}.VIEW_REGISTERED_DATA_OFFERINGS()")
        return {"offerings": rows}

    return _run(session, "LIST_OFFERINGS", _work, ui_track=ui_track)


def unregister_offering(session, offering_id: str, ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        oid = _dcr_name(offering_id, "offering_id")
        _rows(session, f"CALL {REGISTRY}.UNREGISTER_DATA_OFFERING(?)", [oid])
        return {"offering_id": oid, "unregistered": True}

    return _run(session, "UNREGISTER_OFFERING", _work, ui_track=ui_track, target=offering_id)


# ---------------------------------------------------------------------------
# Module 2 — create collaboration
# ---------------------------------------------------------------------------


def create_collaboration(session, config: dict[str, Any], auto_join_warehouse: str | None = None,
                         ui_track: str = "sql") -> dict[str, Any]:
    """Build a ``collaboration`` spec and INITIALIZE it.

    Passing ``auto_join_warehouse`` makes the owner auto-join via a task, which
    removes a manual step. It requires EXECUTE TASK on the role.
    """
    def _work() -> dict[str, Any]:
        built = specs.build_collaboration_spec(config)
        if auto_join_warehouse:
            wh = _ident(auto_join_warehouse, "auto_join_warehouse")
            _rows(session, f"CALL {COLLAB}.INITIALIZE(?, ?)", [built["spec_yaml"], wh])
        else:
            _rows(session, f"CALL {COLLAB}.INITIALIZE(?)", [built["spec_yaml"]])
        status = _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [built["collaboration_name"]])
        return {
            "collaboration_name": built["collaboration_name"],
            "auto_join": bool(auto_join_warehouse),
            "status": status,
            "_spec": built["spec_yaml"],
        }

    return _run(session, "CREATE_COLLABORATION", _work, ui_track=ui_track,
                collaboration=config.get("name"), request=config)


def list_collaborations(session, with_status: bool = True, ui_track: str = "sql") -> dict[str, Any]:
    """List collaborations, split into joined, in-review, and pending invitations.

    ``COLLABORATION_NAME`` is NOT a join indicator, which is the trap this
    function exists to absorb. It is populated as soon as a local name is
    assigned, which happens at REVIEW for a collaborator and at INITIALIZE for
    the owner -- both long before the join completes. Bucketing on it reports
    "already joined" for a collaboration that is merely reviewed, which then
    hides the very button the user needs and leaves them stuck at REVIEWING.

    So the status comes from GET_STATUS, for the row describing THIS account.
    That costs one extra call per named collaboration; pass
    ``with_status=False`` to skip it when a caller only needs the names.
    """
    def _work() -> dict[str, Any]:
        rows = _rows(session, f"CALL {COLLAB}.VIEW_COLLABORATIONS()")
        me = _scalar(session, "SELECT CURRENT_ORGANIZATION_NAME()||'.'||CURRENT_ACCOUNT_NAME()")
        joined, in_review, invited = [], [], []
        for r in rows:
            item = {
                "source_name": r.get("SOURCE_NAME"),
                "local_name": r.get("COLLABORATION_NAME"),
                "owner_account": r.get("OWNER_ACCOUNT"),
                "updated_on": str(r.get("UPDATED_ON")) if r.get("UPDATED_ON") else None,
                "spec": r.get("COLLABORATION_SPEC"),
                "is_owner": r.get("OWNER_ACCOUNT") == me,
                "status": None,
            }

            if not item["local_name"]:
                invited.append(item)
                continue

            if not with_status:
                joined.append(item)
                continue

            # GET_STATUS raises if the collaboration is not visible to this role,
            # which is a status answer of its own rather than a failure to report.
            try:
                status_rows = _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [item["local_name"]])
            except Exception:
                status_rows = []

            mine = [s for s in status_rows if s.get("COLLABORATOR_ACCOUNT") == me]
            item["status"] = str((mine or status_rows or [{}])[0].get("STATUS") or "").upper() or None

            # Match exactly: JOINING and JOINED differ by one letter and by
            # several minutes of provisioning.
            if item["status"] == "JOINED":
                joined.append(item)
            else:
                in_review.append(item)

        return {"account": me, "joined": joined, "in_review": in_review, "invited": invited}

    return _run(session, "LIST_COLLABORATIONS", _work, ui_track=ui_track)


def get_status(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        name = _dcr_name(collaboration, "collaboration")
        return {"collaboration": name,
                "status": _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [name])}

    return _run(session, "GET_STATUS", _work, ui_track=ui_track, collaboration=collaboration)


def _interpret_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce GET_STATUS rows to a single state plus the auto-join verdict.

    GET_STATUS returns one row per collaborator with a STATUS and a DETAILS blob.
    The auto-join outcome hides inside DETAILS, and it is possible for auto-join
    to fail while the call that requested it reported success.
    """
    blob = json.dumps(rows, default=str)
    statuses = [str(r.get("STATUS") or "").upper() for r in rows]

    auto_join_failed = '"phase": "failed"' in blob or '"phase":"failed"' in blob
    auto_join_enabled = '"enabled": true' in blob or '"enabled":true' in blob

    if "LOCAL_DROP_PENDING" in blob.upper():
        state = "LOCAL_DROP_PENDING"
    elif any(s == "JOINED" for s in statuses):
        state = "JOINED"
    elif any(s == "JOINING" for s in statuses):
        state = "JOINING"
    elif any(s == "CREATED" for s in statuses):
        state = "CREATED"
    elif any(s == "CREATING" for s in statuses):
        state = "CREATING"
    else:
        state = statuses[0] if statuses else "UNKNOWN"

    return {
        "state": state,
        "collaborator_statuses": statuses,
        "auto_join_enabled": auto_join_enabled,
        "auto_join_failed": auto_join_failed,
        "rows": rows,
    }


def ensure_joined(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    """Advance the owner towards JOINED, one non-blocking step at a time.

    Auto-join is best effort. It runs as a task and can fail while INITIALIZE
    itself reports success, leaving the collaboration at CREATED with
    ``"auto_join": {"phase": "failed"}`` buried in the status details. Observed
    on DCR 17.5 during validation. Nothing works until someone calls JOIN, so
    this inspects the state and calls JOIN when that is the right move.

    Returns a state the UI can poll rather than blocking inside the procedure.
    """
    def _work() -> dict[str, Any]:
        name = _dcr_name(collaboration, "collaboration")
        status = _interpret_status(_rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [name]))

        action = "none"
        if status["state"] == "JOINED":
            action = "already_joined"
        elif status["state"] == "CREATED":
            # Ready for the owner to join, whether auto-join was never requested
            # or was requested and failed.
            _rows(session, f"CALL {COLLAB}.JOIN(?)", [name])
            action = "join_called"
            status = _interpret_status(_rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [name]))
        elif status["state"] in ("CREATING", "JOINING"):
            action = "wait"
        elif status["state"] == "LOCAL_DROP_PENDING":
            action = "blocked_drop_pending"

        return {
            "collaboration": name,
            "action": action,
            "joined": status["state"] == "JOINED",
            "keep_polling": status["state"] in ("CREATING", "JOINING"),
            **status,
        }

    return _run(session, "ENSURE_JOINED", _work, ui_track=ui_track, collaboration=collaboration)


# ---------------------------------------------------------------------------
# Module 3 — review and join
# ---------------------------------------------------------------------------


def join_collaboration(session, source_name: str, owner_account: str,
                       local_name: str | None = None, ui_track: str = "sql") -> dict[str, Any]:
    """REVIEW then JOIN, in one user-visible action.

    ``source_name`` is the SOURCE_NAME column from the invitation, which is not
    always the same as the collaboration name.
    """
    def _work() -> dict[str, Any]:
        src = _dcr_name(source_name, "source_name")
        local = _dcr_name(local_name or source_name, "local_name")
        owner = str(owner_account)
        if not re.match(r"^[A-Za-z0-9][\w-]*\.[A-Za-z0-9][\w-]*$", owner):
            raise specs.SpecError(f"owner_account '{owner}' is not ORG.ACCOUNT.",
                                  field="owner_account")

        review = _rows(session, f"CALL {COLLAB}.REVIEW(?, ?, ?)", [src, owner, local])
        _rows(session, f"CALL {COLLAB}.JOIN(?)", [local])
        status = _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [local])
        return {"source_name": src, "local_name": local, "review": review, "status": status}

    return _run(session, "JOIN_COLLABORATION", _work, ui_track=ui_track,
                collaboration=local_name or source_name,
                request={"source_name": source_name, "owner_account": owner_account,
                         "local_name": local_name})


def review_collaboration(session, source_name: str, owner_account: str,
                         local_name: str | None = None, ui_track: str = "sql") -> dict[str, Any]:
    """REVIEW only, so the UI can show the spec before committing to a join."""
    def _work() -> dict[str, Any]:
        src = _dcr_name(source_name, "source_name")
        local = _dcr_name(local_name or source_name, "local_name")
        return {"review": _rows(session, f"CALL {COLLAB}.REVIEW(?, ?, ?)",
                                [src, str(owner_account), local])}

    return _run(session, "REVIEW_COLLABORATION", _work, ui_track=ui_track,
                collaboration=source_name)


# ---------------------------------------------------------------------------
# Module 4 — link data
# ---------------------------------------------------------------------------


def link_data(session, collaboration: str, offering_id: str, mode: str,
              runners: list[str] | None = None, ui_track: str = "sql") -> dict[str, Any]:
    """Link a data offering into a collaboration.

    ``mode`` distinguishes the two operations that both look like "linking data"
    and that the official UI conflates:

      ``partner`` -> LINK_DATA_OFFERING: I am a data provider sharing MY offering
                     TO the named analysis runners. Becomes ``source_table`` /
                     ``p1``, and is policy-enforced.

      ``local``   -> LINK_LOCAL_DATA_OFFERING: I am an analysis runner attaching
                     MY OWN table so it can be matched against the partner's.
                     Becomes ``my_table`` / ``c1``. Without this there is no
                     overlap to compute, and no way to fix it later from a UI
                     that does not expose it.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        oid = _dcr_name(offering_id, "offering_id")
        m = str(mode).lower()
        if m not in ("partner", "local"):
            raise specs.SpecError("mode must be 'partner' or 'local'.", field="mode")

        if m == "local":
            _rows(session, f"CALL {COLLAB}.LINK_LOCAL_DATA_OFFERING(?, ?)", [collab, oid])
        else:
            if not runners:
                raise specs.SpecError(
                    "Sharing an offering to a collaboration requires at least one analysis "
                    "runner alias to share it with.", field="runners")
            arr = _sql_array(runners, "runners")
            _rows(session, f"CALL {COLLAB}.LINK_DATA_OFFERING(?, ?, {arr})", [collab, oid])

        return {"collaboration": collab, "offering_id": oid, "mode": m, "runners": runners or []}

    return _run(session, "LINK_DATA", _work, ui_track=ui_track, collaboration=collaboration,
                target=offering_id, request={"mode": mode, "runners": runners})


def unlink_data(session, collaboration: str, offering_id: str, mode: str,
                runners: list[str] | None = None, ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        oid = _dcr_name(offering_id, "offering_id")
        m = str(mode).lower()
        if m == "local":
            _rows(session, f"CALL {COLLAB}.UNLINK_LOCAL_DATA_OFFERING(?, ?)", [collab, oid])
        else:
            arr = _sql_array(runners or [], "runners")
            _rows(session, f"CALL {COLLAB}.UNLINK_DATA_OFFERING(?, ?, {arr})", [collab, oid])
        return {"collaboration": collab, "offering_id": oid, "mode": m}

    return _run(session, "UNLINK_DATA", _work, ui_track=ui_track,
                collaboration=collaboration, target=offering_id)


def get_collaboration_detail(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    """Everything the analysis and activation screens need to build a valid run.

    Splits the linked offerings into the partner side (``source_tables`` / ``p1``)
    and my own side (``my_tables`` / ``c1``), and surfaces the allow-lists so the
    UI can offer only legal columns instead of letting a run fail.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        offerings = _rows(session, f"CALL {COLLAB}.VIEW_DATA_OFFERINGS(?)", [collab])
        templates = _rows(session, f"CALL {COLLAB}.VIEW_TEMPLATES(?)", [collab])

        def _split(value: Any) -> list[str]:
            """DCR returns these as JSON arrays or comma-joined strings."""
            if value is None:
                return []
            if isinstance(value, list):
                return [str(v) for v in value]
            text = str(value).strip()
            if text.startswith("["):
                try:
                    return [str(v) for v in json.loads(text)]
                except Exception:
                    pass
            return [p.strip().strip('"') for p in text.strip("[]").split(",") if p.strip()]

        partner, mine = [], []
        for o in offerings:
            view = o.get("TEMPLATE_VIEW_NAME") or ""
            item = {
                "view_name": view,
                "offering_id": o.get("DATA_OFFERING_ID"),
                "shared_by": o.get("SHARED_BY"),
                "shared_with": o.get("SHARED_WITH"),
                "join_columns": _split(o.get("TEMPLATE_JOIN_COLUMNS")),
                "analysis_columns": _split(o.get("ANALYSIS_ALLOWED_COLUMNS")),
                "activation_columns": _split(o.get("ACTIVATION_ALLOWED_COLUMNS")),
            }
            # SHARED_WITH determines partner vs local. DCR returns it as a JSON
            # array string like '["LOCAL"]' or '["PROVIDER"]'. When it contains
            # "LOCAL" this is the runner's own linked table (the c1 side). The
            # view name prefix is NOT reliable: in a single-account scenario both
            # the provider and the local offering get PROVIDER. as prefix.
            shared_with = str(o.get("SHARED_WITH") or "")
            is_local = '"LOCAL"' in shared_with.upper() or "'LOCAL'" in shared_with.upper()
            (mine if is_local else partner).append(item)

        template_ids = [t.get("TEMPLATE_ID") for t in templates]

        # Which roles does THIS account hold in this collaboration?
        #
        # It decides which link operation is even legal here. Attempting
        # LINK_DATA_OFFERING as a pure analysis runner fails with
        # ProviderNotServingAnalysisRunner, which reads like a bug rather than
        # "that operation is not yours to perform", so the UI needs to know in
        # advance and offer only what applies.
        my_roles: list[str] = []
        my_alias: str | None = None
        serves_runners: list[str] = []
        try:
            status = _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [collab])
            here = str(
                _scalar(session, "SELECT CURRENT_ORGANIZATION_NAME()||'.'||CURRENT_ACCOUNT_NAME()")
                or ""
            ).upper()
            for row in status:
                acct = str(row.get("COLLABORATOR_ACCOUNT") or "").upper()
                if acct and acct == here:
                    my_roles = [r.lower() for r in _split(row.get("ROLES"))]
                    my_alias = row.get("COLLABORATOR_NAME") or None
                    break
        except Exception:
            # Role detection is advisory. If GET_STATUS is unavailable the UI
            # simply shows both link operations, as it did before.
            pass

        # A data provider may only link FOR the runners it actually serves.
        for o in partner + mine:
            if str(o.get("shared_by") or "").upper() == str(my_alias or "").upper():
                serves_runners.extend(_split(o.get("shared_with")))
        serves_runners = sorted({r for r in serves_runners if r.upper() != "LOCAL"})

        return {
            "collaboration": collab,
            "partner_offerings": partner,
            "my_offerings": mine,
            "templates": template_ids,
            "has_overlap_template": specs.STANDARD_OVERLAP_TEMPLATE in template_ids,
            "has_activation_template": specs.STANDARD_ACTIVATION_TEMPLATE in template_ids,
            "my_alias": my_alias,
            "my_roles": my_roles,
            "is_data_provider": "data provider" in my_roles or "data_provider" in my_roles,
            "is_analysis_runner": "analysis runner" in my_roles or "analysis_runner" in my_roles,
            "is_owner": "owner" in my_roles,
            "serves_runners": serves_runners,
        }

    return _run(session, "GET_COLLABORATION_DETAIL", _work, ui_track=ui_track,
                collaboration=collaboration)


def preflight(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    """Answer "can I run an overlap, and can I activate?" before the user tries.

    Failing early with a specific reason is far better than surfacing a DCR
    traceback after a user has filled in a whole wizard.
    """
    def _work() -> dict[str, Any]:
        detail = get_collaboration_detail(session, collaboration, ui_track=ui_track)
        if not detail["ok"]:
            return {"can_run_overlap": False, "can_activate": False,
                    "blockers": [detail["error"]["cause"]], "detail": None}

        d = detail["data"]
        blockers, warnings = [], []

        if not d["partner_offerings"]:
            blockers.append(
                "No partner dataset is available. The data provider must share an offering "
                "with you (Link Data, 'share to runner').")
        if not d["my_offerings"]:
            blockers.append(
                "You have not linked any dataset of your own. Audience overlap needs both "
                "sides. Use Link Data -> 'my own data', which calls "
                "LINK_LOCAL_DATA_OFFERING.")
        if not d["has_overlap_template"]:
            blockers.append(
                f"The template {specs.STANDARD_OVERLAP_TEMPLATE} is not available in this "
                "collaboration. The owner must add and approve it.")
        if not d["has_activation_template"]:
            warnings.append(
                f"{specs.STANDARD_ACTIVATION_TEMPLATE} is not available, so results can be "
                "measured but not activated.")

        # Do the two sides share a join column? Without an intersection there is
        # no clause that can be built, whatever the user picks in the UI.
        partner_keys = {k.upper() for o in d["partner_offerings"] for k in o["join_columns"]}
        my_keys = {k.upper() for o in d["my_offerings"] for k in o["join_columns"]}
        common = sorted(partner_keys & my_keys)
        if d["partner_offerings"] and d["my_offerings"] and not common:
            blockers.append(
                f"No shared join key. Partner exposes {sorted(partner_keys) or 'nothing'}; "
                f"you expose {sorted(my_keys) or 'nothing'}. Remember that a 'join_standard' "
                "column is renamed to its column_type, so both sides must use the SAME "
                "column_type to match.")

        activatable = sorted({c for o in d["partner_offerings"] + d["my_offerings"]
                              for c in o["activation_columns"]})
        if d["has_activation_template"] and not activatable:
            warnings.append(
                "No column is marked activation_allowed, so an activation would carry only "
                "the match key. The data owner must re-register with activation_allowed.")

        return {
            "can_run_overlap": not blockers,
            "can_activate": not blockers and d["has_activation_template"] and bool(activatable),
            "blockers": blockers,
            "warnings": warnings,
            "common_join_keys": common,
            "activatable_columns": activatable,
            "detail": d,
        }

    return _run(session, "PREFLIGHT", _work, ui_track=ui_track, collaboration=collaboration)
