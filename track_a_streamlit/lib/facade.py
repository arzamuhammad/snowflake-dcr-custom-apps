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
