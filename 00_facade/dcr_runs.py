"""
DCR Console — run, activation, import and admin operations.

Split from ``dcr_facade`` purely for readability: that module covers setup and
lifecycle (health, register, create, join, link), this one covers execution
(overlap, activation, the recipient-side import, history and admin). Both share
the same envelope, audit and error-decoding helpers.

The recipient-side import here is the step the Snowflake tutorials leave as
manual SQL. Without it an activation reports success while the marketer has
nothing usable: the payload sits in a VARIANT column inside a share.

Collaboration API v2 only.
"""

from __future__ import annotations

import json
import re
from typing import Any

import dcr_specs as specs
from dcr_facade import (
    COLLAB,
    META,
    _dcr_name,
    _fqn,
    _rows,
    _run,
    _scalar,
    _sql_array,
    get_collaboration_detail,
)

#: Waterfall levels beyond this are almost always a misconfigured UI loop.
MAX_MATCH_LEVELS = 10


# ---------------------------------------------------------------------------
# Module 5 — run the overlap
# ---------------------------------------------------------------------------


def _normalise_overlap(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn the template's raw output into something a dashboard can render.

    The standard template returns a waterfall shaped roughly as
    ``WATERFALL_LEVEL | METRIC_TYPE | COUNT_VALUE | TOTAL_COUNT | MATCH_CRITERIA``.
    Column names are not treated as guaranteed: unknown shapes are passed
    through untouched rather than silently mangled, and ``summary`` is simply
    absent when it cannot be derived honestly.
    """
    out: dict[str, Any] = {"rows": rows, "row_count": len(rows)}
    if not rows:
        return out

    keys = {k.upper() for k in rows[0]}
    if not {"COUNT_VALUE", "TOTAL_COUNT"} <= keys:
        return out

    def _num(v: Any) -> int | None:
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    matched = 0
    total = 0
    non_overlap = 0
    levels: list[dict[str, Any]] = []
    suppressed = False

    for r in rows:
        upper = {k.upper(): v for k, v in r.items()}
        count = _num(upper.get("COUNT_VALUE"))
        tot = _num(upper.get("TOTAL_COUNT"))
        metric_type = str(upper.get("METRIC_TYPE") or "").upper()
        # A NULL count is the privacy threshold engaging, not a zero.
        if upper.get("COUNT_VALUE") is None:
            suppressed = True
        # Only sum OVERLAP rows — the result set also contains NON_OVERLAP and
        # summary-level rows whose counts must NOT be aggregated into the match.
        if metric_type == "OVERLAP" and count:
            matched += count
        elif metric_type == "NON_OVERLAP" and count:
            non_overlap += count
        if tot and tot > total:
            total = tot
        levels.append({
            "level": upper.get("WATERFALL_LEVEL"),
            "metric_type": metric_type,
            "count": count,
            "total": tot,
            "match_criteria": upper.get("MATCH_CRITERIA"),
        })

    # Unmatched: prefer the explicit total - matched calculation over summing
    # NON_OVERLAP rows, because the template emits a summary row at waterfall
    # level 999 that duplicates the level-specific NON_OVERLAP count.
    unmatched = (total - matched) if total and total >= matched else None

    summary = {
        "matched": matched,
        "unmatched": unmatched,
        "total": total or None,
        "match_rate": round(matched / total, 6) if total else None,
        "privacy_suppressed": suppressed,
    }
    out["summary"] = summary
    out["levels"] = levels
    return out


def run_overlap(session, collaboration: str, config: dict[str, Any], use_cache: bool = True,
                ui_track: str = "sql") -> dict[str, Any]:
    """Run ``standard_audience_overlap_v0``.

    ``COLLABORATION.RUN`` is synchronous and blocking: there is no progress
    callback and no percentage to report while it executes. The UI shows a phase
    stepper and an elapsed timer, never a fabricated percentage.

    A cache hit returns instantly, which matters because reopening a saved
    configuration is otherwise a full re-scan and a real bill.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")

        levels = config.get("match_levels") or []
        if len(levels) > MAX_MATCH_LEVELS:
            raise specs.SpecError(
                f"{len(levels)} waterfall levels requested; the limit is {MAX_MATCH_LEVELS}.",
                field="match_levels")

        built = specs.build_overlap_spec(config)
        key = built["cache_key"]

        if use_cache:
            cached = _rows(session, f"""
                SELECT RESULTS, COMPUTED_AT, DURATION_MS FROM {META}.RUN_CACHE
                WHERE CACHE_KEY = ? AND COLLABORATION = ?
                ORDER BY COMPUTED_AT DESC LIMIT 1
            """, [key, collab])
            if cached:
                payload = cached[0]["RESULTS"]
                results = json.loads(payload) if isinstance(payload, str) else payload
                return {
                    "from_cache": True,
                    "computed_at": str(cached[0]["COMPUTED_AT"]),
                    "cache_key": key,
                    "join_clauses": built["join_clauses"],
                    **(results or {}),
                }

        raw = _rows(session, f"CALL {COLLAB}.RUN(?, ?)", [collab, built["spec_yaml"]])
        results = _normalise_overlap(raw)

        session.sql(f"""
            INSERT INTO {META}.RUN_CACHE
              (CACHE_KEY, COLLABORATION, TEMPLATE_ID, REQUEST, RESULTS, ROW_COUNT, COMPUTED_BY)
            SELECT ?, ?, ?, TRY_PARSE_JSON(?), TRY_PARSE_JSON(?), ?, CURRENT_USER()
        """, params=[key, collab, specs.STANDARD_OVERLAP_TEMPLATE,
                     json.dumps(config), json.dumps(results, default=str),
                     results["row_count"]]).collect()

        return {
            "from_cache": False,
            "cache_key": key,
            "join_clauses": built["join_clauses"],
            "_spec": built["spec_yaml"],
            **results,
        }

    return _run(session, "RUN_OVERLAP", _work, ui_track=ui_track,
                collaboration=collaboration, target=specs.STANDARD_OVERLAP_TEMPLATE,
                request=config)


# ---------------------------------------------------------------------------
# Module 6 — activation
# ---------------------------------------------------------------------------


def run_activation(session, collaboration: str, config: dict[str, Any],
                   ui_track: str = "sql") -> dict[str, Any]:
    """Run ``standard_audience_overlap_activation_v0``.

    Column selection is enforced twice on purpose. The UI offers only columns the
    data owner marked ``activation_allowed``, and this function re-checks the
    request against ``ACTIVATION_ALLOWED_COLUMNS`` from the live collaboration.
    A caller bypassing the UI must not be able to exfiltrate a column the owner
    withheld, and DCR's own policy filter is the third and final gate.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")

        detail = get_collaboration_detail(session, collab, ui_track=ui_track)
        if not detail["ok"]:
            raise RuntimeError(detail["error"]["cause"])
        d = detail["data"]

        allowed = {c.upper() for o in d["partner_offerings"] + d["my_offerings"]
                   for c in o["activation_columns"]}
        requested = [str(c) for c in (config.get("activation_columns") or [])]

        if allowed:
            # Compare on the bare column name: allow-lists are unqualified while
            # the request must be alias-qualified.
            illegal = [c for c in requested
                       if c.split(".", 1)[-1].upper() not in allowed]
            if illegal:
                raise specs.SpecError(
                    "These columns are not permitted for activation by their owner: "
                    f"{', '.join(illegal)}. Permitted: {', '.join(sorted(allowed))}.",
                    field="activation_columns")

        destinations = config.get("allowed_destinations")
        if destinations:
            dest = str(config.get("destination", "")).upper()
            if dest not in {str(x).upper() for x in destinations}:
                raise specs.SpecError(
                    f"'{dest}' is not a declared activation destination for this "
                    f"collaboration. Allowed: {', '.join(destinations)}.",
                    field="destination")

        built = specs.build_activation_spec(config)
        raw = _rows(session, f"CALL {COLLAB}.RUN(?, ?)", [collab, built["spec_yaml"]])

        # DCR returns a batch id and results table under varying column names.
        batch_id = results_table = None
        if raw:
            first = {k.upper(): v for k, v in raw[0].items()}
            batch_id = first.get("BATCH_ID") or first.get("ACTIVATION_ID")
            results_table = first.get("RESULTS_TABLE") or first.get("TABLE_NAME")

        return {
            "batch_id": batch_id,
            "results_table": results_table,
            "segment_name": built["segment_name"],
            "destination": built["destination"],
            "activation_columns": built["activation_columns"],
            "raw": raw,
            "_spec": built["spec_yaml"],
        }

    return _run(session, "RUN_ACTIVATION", _work, ui_track=ui_track,
                collaboration=collaboration, target=config.get("segment_name"),
                request=config)


def list_activations(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    """Activation batches for this collaboration, with real delivery status.

    This is genuine state from DCR, and is what the UI's status badges show —
    as opposed to the RUN itself, which exposes no progress at all.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        rows = _rows(session, f"CALL {COLLAB}.VIEW_ACTIVATIONS(?)", [collab])

        imports = {}
        for r in _rows(session, f"""
            SELECT BATCH_ID, IMPORT_ID, TARGET_FQN, STATUS, EXPECTED_ROWS, IMPORTED_ROWS,
                   STARTED_AT, FINISHED_AT
            FROM {META}.ACTIVATION_IMPORT WHERE COLLABORATION = ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY BATCH_ID ORDER BY STARTED_AT DESC) = 1
        """, [collab]):
            imports[str(r["BATCH_ID"])] = {
                "import_id": r["IMPORT_ID"], "target_fqn": r["TARGET_FQN"],
                "status": r["STATUS"], "expected_rows": r["EXPECTED_ROWS"],
                "imported_rows": r["IMPORTED_ROWS"],
                "started_at": str(r["STARTED_AT"]) if r["STARTED_AT"] else None,
                "finished_at": str(r["FINISHED_AT"]) if r["FINISHED_AT"] else None,
            }

        batches = []
        for r in rows:
            upper = {k.upper(): v for k, v in r.items()}
            bid = str(upper.get("BATCH_ID") or upper.get("ACTIVATION_ID") or "")
            batches.append({
                "batch_id": bid,
                "segment_name": upper.get("SEGMENT_NAME"),
                "status": upper.get("STATUS"),
                "updated_on": str(upper.get("UPDATED_ON")) if upper.get("UPDATED_ON") else None,
                "raw": r,
                "import": imports.get(bid),
                "imported": bool(imports.get(bid) and imports[bid]["status"] == "READY"),
            })
        return {"collaboration": collab, "activations": batches}

    return _run(session, "LIST_ACTIVATIONS", _work, ui_track=ui_track,
                collaboration=collaboration)


# ---------------------------------------------------------------------------
# Module 7 — activation inbox: import and flatten
# ---------------------------------------------------------------------------


def import_activation(session, collaboration: str, batch_id: str, target_fqn: str,
                      activation_columns: list[str] | None = None,
                      expected_rows: int | None = None,
                      ui_track: str = "sql") -> dict[str, Any]:
    """Import an activated segment and materialise it as a usable table.

    Three steps, none of which the recipient should have to do by hand:
      1. PROCESS_ACTIVATION, so the batch lands in the share.
      2. Discover the activated column names from the VARIANT payload, if the
         caller did not supply them.
      3. Flatten ``SEGMENT_RECORDS`` into a flat, de-aliased native table.

    Progress is tracked in ``META.ACTIVATION_IMPORT``, which is where the one
    honest percentage in the whole application comes from: rows landed divided
    by rows expected.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        target = _fqn(target_fqn, "target_fqn")
        batch = str(batch_id)
        if not re.match(r"^[A-Za-z0-9_\-]+$", batch):
            raise specs.SpecError(f"batch_id '{batch}' has an unexpected format.",
                                  field="batch_id")

        import_id = _scalar(session, "SELECT UUID_STRING()")
        session.sql(f"""
            INSERT INTO {META}.ACTIVATION_IMPORT
              (IMPORT_ID, COLLABORATION, BATCH_ID, TARGET_FQN, EXPECTED_ROWS, STATUS)
            SELECT ?, ?, ?, ?, ?, 'IMPORTING'
        """, params=[import_id, collab, batch, target, expected_rows]).collect()

        try:
            # 1. Ask DCR to process the batch. Older versions auto-process, so a
            #    failure here is not necessarily fatal — the share may already
            #    hold the rows. Proceed and let the flatten step be the judge.
            process_note = None
            try:
                _rows(session, f"CALL {COLLAB}.PROCESS_ACTIVATION(?, ?)", [collab, batch])
            except Exception as e:  # noqa: BLE001
                process_note = str(e)
                try:
                    _rows(session, f"CALL {COLLAB}.PROCESS_ACTIVATION(?)", [collab])
                except Exception as e2:  # noqa: BLE001
                    process_note = f"{process_note} | {e2}"

            share_db = f"SFDCR_{collab.upper()}"
            records = f"{share_db}.ACTIVATION.SEGMENT_RECORDS"

            # 2. Derive the activated columns from the payload when not supplied.
            columns = [str(c) for c in (activation_columns or [])]
            if not columns:
                keys = _rows(session, f"""
                    SELECT DISTINCT f.KEY AS K
                    FROM {records}, LATERAL FLATTEN(input => RECORDS:ID) f
                    WHERE BATCH_ID = ?
                """, [batch])
                columns = [r["K"] for r in keys if r["K"] != "join_clause"]
            if not columns:
                raise RuntimeError(
                    f"No activated columns found in {records} for batch {batch}. The batch "
                    "may not have been delivered yet — check the status in Activation "
                    "History and retry.")

            # 3. Flatten into a native table.
            flatten_sql = specs.build_flatten_sql(collab, target, columns, batch_id=batch)
            session.sql(flatten_sql).collect()
            imported = int(_scalar(session, f"SELECT COUNT(*) FROM {target}") or 0)

            session.sql(f"""
                UPDATE {META}.ACTIVATION_IMPORT
                SET STATUS = 'READY', IMPORTED_ROWS = ?, FINISHED_AT = CURRENT_TIMESTAMP()
                WHERE IMPORT_ID = ?
            """, params=[imported, import_id]).collect()

            return {
                "import_id": import_id, "collaboration": collab, "batch_id": batch,
                "target_fqn": target, "imported_rows": imported,
                "activation_columns": columns, "flatten_sql": flatten_sql,
                "process_note": process_note,
            }

        except Exception as e:
            session.sql(f"""
                UPDATE {META}.ACTIVATION_IMPORT
                SET STATUS = 'FAILED', ERROR_RAW = ?, FINISHED_AT = CURRENT_TIMESTAMP()
                WHERE IMPORT_ID = ?
            """, params=[str(e), import_id]).collect()
            raise

    return _run(session, "IMPORT_ACTIVATION", _work, ui_track=ui_track,
                collaboration=collaboration, target=batch_id,
                request={"target_fqn": target_fqn, "expected_rows": expected_rows})


def get_import_progress(session, import_id: str, ui_track: str = "sql") -> dict[str, Any]:
    """Real import progress: rows landed versus rows expected.

    This is the only place in the application that reports a genuine percentage.
    The overlap RUN cannot, because the API exposes no progress for it.
    """
    def _work() -> dict[str, Any]:
        rows = _rows(session, f"""
            SELECT IMPORT_ID, COLLABORATION, BATCH_ID, TARGET_FQN, STATUS,
                   EXPECTED_ROWS, IMPORTED_ROWS, STARTED_AT, FINISHED_AT, ERROR_RAW
            FROM {META}.ACTIVATION_IMPORT WHERE IMPORT_ID = ?
        """, [str(import_id)])
        if not rows:
            raise specs.SpecError(f"No import found with id {import_id}.", field="import_id")

        r = rows[0]
        landed = r["IMPORTED_ROWS"]
        # While IMPORTING, count the target table live rather than trusting the
        # not-yet-written final count.
        if r["STATUS"] == "IMPORTING" and r["TARGET_FQN"]:
            try:
                landed = int(_scalar(session, f"SELECT COUNT(*) FROM {r['TARGET_FQN']}") or 0)
            except Exception:  # noqa: BLE001 - table may not exist yet
                landed = 0

        expected = r["EXPECTED_ROWS"]
        pct = None
        if expected and int(expected) > 0 and landed is not None:
            pct = min(round(int(landed) / int(expected) * 100, 2), 100.0)

        return {
            "import_id": r["IMPORT_ID"], "status": r["STATUS"],
            "target_fqn": r["TARGET_FQN"], "expected_rows": expected,
            "imported_rows": landed, "percent_complete": pct,
            "started_at": str(r["STARTED_AT"]) if r["STARTED_AT"] else None,
            "finished_at": str(r["FINISHED_AT"]) if r["FINISHED_AT"] else None,
            "error_raw": r["ERROR_RAW"],
        }

    return _run(session, "GET_IMPORT_PROGRESS", _work, ui_track=ui_track)


# ---------------------------------------------------------------------------
# Module 8 — history
# ---------------------------------------------------------------------------


def activity_history(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    """DCR's own activity history plus the console's audit log, side by side."""
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        try:
            dcr_history = _rows(session, f"CALL {COLLAB}.VIEW_ACTIVITY_HISTORY(?)", [collab])
        except Exception as e:  # noqa: BLE001 - history is informational
            dcr_history = [{"error": str(e)}]

        console = _rows(session, f"""
            SELECT EVENT_TS, ACTOR_USER, UI_TRACK, OPERATION, TARGET, OUTCOME,
                   DURATION_MS, ERROR_DECODED:title::STRING AS ERROR_TITLE
            FROM {META}.AUDIT_LOG WHERE COLLABORATION = ?
            ORDER BY EVENT_TS DESC LIMIT 200
        """, [collab])

        return {"collaboration": collab, "dcr_history": dcr_history,
                "console_history": [{k: (str(v) if hasattr(v, "isoformat") else v)
                                     for k, v in r.items()} for r in console]}

    return _run(session, "ACTIVITY_HISTORY", _work, ui_track=ui_track,
                collaboration=collaboration)


# ---------------------------------------------------------------------------
# Module 9 — admin
# ---------------------------------------------------------------------------


def list_update_requests(session, collaboration: str, ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        return {"requests": _rows(session, f"CALL {COLLAB}.VIEW_UPDATE_REQUESTS(?)", [collab])}

    return _run(session, "LIST_UPDATE_REQUESTS", _work, ui_track=ui_track,
                collaboration=collaboration)


def approve_update_request(session, collaboration: str, request_id: str,
                           ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        result = _scalar(session, f"CALL {COLLAB}.APPROVE_UPDATE_REQUEST(?, ?)",
                         [collab, str(request_id)])
        return {"request_id": request_id, "result": result}

    return _run(session, "APPROVE_UPDATE_REQUEST", _work, ui_track=ui_track,
                collaboration=collaboration, target=request_id)


def reject_update_request(session, collaboration: str, request_id: str, reason: str,
                          ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        result = _scalar(session, f"CALL {COLLAB}.REJECT_UPDATE_REQUEST(?, ?, ?)",
                         [collab, str(request_id), str(reason)])
        return {"request_id": request_id, "result": result}

    return _run(session, "REJECT_UPDATE_REQUEST", _work, ui_track=ui_track,
                collaboration=collaboration, target=request_id)


def add_template(session, collaboration: str, template_id: str, runners: list[str],
                 ui_track: str = "sql") -> dict[str, Any]:
    """Share a template with runners in an EXISTING collaboration.

    Not part of the audience-overlap happy path — both standard templates are
    declared when the collaboration is created. This exists because it is the
    only way to add a template to a live collaboration, and it requires the
    runner and all their data providers to approve.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        tid = _dcr_name(template_id, "template_id")
        if not runners:
            raise specs.SpecError("Select at least one analysis runner.", field="runners")
        arr = _sql_array(runners, "runners")
        result = _rows(session, f"CALL {COLLAB}.ADD_TEMPLATE_REQUEST(?, ?, {arr})", [collab, tid])
        return {"template_id": tid, "runners": runners, "result": result}

    return _run(session, "ADD_TEMPLATE", _work, ui_track=ui_track,
                collaboration=collaboration, target=template_id)


def teardown_or_leave(session, collaboration: str, mode: str,
                      ui_track: str = "sql") -> dict[str, Any]:
    """Remove a collaboration, hiding the asynchronous two-call protocol.

    TEARDOWN (owner) and LEAVE (collaborator) are both asynchronous and must be
    called TWICE: the first call starts the drop and the status becomes
    LOCAL_DROP_PENDING, and a second call finishes it. Users should not have to
    know that, so this does both and reports the end state.

    Irreversible: teardown removes the collaboration for every participant, and
    a collaborator who leaves cannot rejoin.
    """
    def _work() -> dict[str, Any]:
        collab = _dcr_name(collaboration, "collaboration")
        m = str(mode).lower()
        if m not in ("teardown", "leave"):
            raise specs.SpecError("mode must be 'teardown' or 'leave'.", field="mode")
        proc = "TEARDOWN" if m == "teardown" else "LEAVE"

        first = _rows(session, f"CALL {COLLAB}.{proc}(?)", [collab])

        status_rows = _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [collab])
        status_text = json.dumps(status_rows, default=str).upper()

        second = None
        if "LOCAL_DROP_PENDING" in status_text:
            second = _rows(session, f"CALL {COLLAB}.{proc}(?)", [collab])
            try:
                status_rows = _rows(session, f"CALL {COLLAB}.GET_STATUS(?)", [collab])
            except Exception:  # noqa: BLE001 - fully removed, status is gone
                status_rows = [{"STATUS": "REMOVED"}]

        return {"collaboration": collab, "mode": m, "first_call": first,
                "second_call": second, "final_status": status_rows,
                "two_call_completed": second is not None}

    return _run(session, "TEARDOWN_OR_LEAVE", _work, ui_track=ui_track,
                collaboration=collaboration, request={"mode": mode})


# ---------------------------------------------------------------------------
# App-level RBAC
# ---------------------------------------------------------------------------


def get_app_role(session, username: str | None = None, ui_track: str = "sql") -> dict[str, Any]:
    """Resolve a user's app permission tier.

    This narrows what the UI offers; it is not a security boundary. DCR's own
    privileges remain the authority, so a user who talks to the API directly is
    still constrained by DCR regardless of what this returns.
    """
    def _work() -> dict[str, Any]:
        user = str(username) if username else _scalar(session, "SELECT CURRENT_USER()")
        rows = _rows(session, f"""
            SELECT APP_ROLE FROM {META}.APP_USER_ROLE WHERE UPPER(USERNAME) = UPPER(?)
            ORDER BY GRANTED_AT DESC LIMIT 1
        """, [user])
        role = rows[0]["APP_ROLE"] if rows else "VIEWER"
        rank = {r: i for i, r in enumerate(specs.APP_ROLES)}
        level = rank.get(str(role).upper(), 0)
        return {
            "username": user, "app_role": role,
            "can_view": True,
            "can_run_overlap": level >= rank["ANALYST"],
            "can_activate": level >= rank["ACTIVATOR"],
            "can_build": level >= rank["BUILDER"],
        }

    return _run(session, "GET_APP_ROLE", _work, ui_track=ui_track)


def set_app_role(session, username: str, app_role: str, notes: str | None = None,
                 ui_track: str = "sql") -> dict[str, Any]:
    def _work() -> dict[str, Any]:
        role = str(app_role).upper()
        if role not in specs.APP_ROLES:
            raise specs.SpecError(
                f"app_role must be one of {', '.join(specs.APP_ROLES)}.", field="app_role")
        session.sql(f"""
            INSERT INTO {META}.APP_USER_ROLE (USERNAME, APP_ROLE, GRANTED_BY, NOTES)
            SELECT ?, ?, CURRENT_USER(), ?
        """, params=[str(username).upper(), role, notes]).collect()
        return {"username": username, "app_role": role}

    return _run(session, "SET_APP_ROLE", _work, ui_track=ui_track, target=username)
