"""
DCR Console — Streamlit facade client.

Every page calls this module, never the Snowflake procedures directly. It wraps
``DCR_CONSOLE.APP.INVOKE`` through the active Snowpark session and returns
plain dicts.
"""

from __future__ import annotations

import json
from typing import Any

import streamlit as st
from snowflake.snowpark.context import get_active_session


def _session():
    return _prepared_session()


@st.cache_resource(show_spinner=False)
def _secondary_roles_disabled() -> str:
    """Disable secondary roles once per Streamlit session.

    Data Clean Rooms refuses REGISTER_DATA_OFFERING and the link operations while
    secondary roles are active. The fix is USE SECONDARY ROLES NONE, which cannot
    live inside DCR_CONSOLE.APP.INVOKE because USE is not a permitted statement in
    a stored procedure. It therefore has to be issued here, at session level,
    before any facade call.

    Cached so it runs once rather than on every Streamlit rerun. Failures are
    swallowed deliberately: a session that cannot run USE at all (a restricted
    token, for example) may still have no secondary roles to begin with, and the
    decoder reports SECONDARY_ROLES_ACTIVE with the exact remedy if it matters.
    """
    try:
        get_active_session().sql("USE SECONDARY ROLES NONE").collect()
        return "disabled"
    except Exception as exc:  # noqa: BLE001 - see docstring
        return f"unavailable: {exc}"


def _prepared_session():
    _secondary_roles_disabled()
    return get_active_session()


def invoke(operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the facade dispatcher and return the parsed result."""
    p = json.dumps({**(payload or {}), "ui_track": "streamlit"})
    rows = _session().sql(
        "CALL DCR_CONSOLE.APP.INVOKE(?, PARSE_JSON(?))",
        params=[operation, p],
    ).collect()
    raw = rows[0][0] if rows else "{}"
    return json.loads(raw) if isinstance(raw, str) else raw


def invoke_direct(sql: str, params: list | None = None) -> list[dict[str, Any]]:
    """Run a raw SQL statement and return rows as dicts.

    Used exclusively for operations that are nest-unsafe (JOIN) and must be
    issued at session level.
    """
    result = _session().sql(sql, params=params) if params else _session().sql(sql)
    return [r.as_dict() for r in result.collect()]


def show_error(result: dict[str, Any]) -> None:
    """Render a facade error as a Streamlit error + expander."""
    err = result.get("error", {})
    st.error(f"**{err.get('title', 'Error')}**")
    st.markdown(err.get("cause", ""))
    if err.get("remediation"):
        st.info(err["remediation"])
    if err.get("sql_fix"):
        st.code(err["sql_fix"], language="sql")
    if result.get("error_raw"):
        with st.expander("Raw error"):
            st.code(result["error_raw"], language="text")
