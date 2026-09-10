"""
DCR Console — shared UI helpers for Streamlit pages.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def page_header(title: str, subtitle: str = "") -> None:
    st.set_page_config(page_title=f"DCR Console — {title}", page_icon="🔒", layout="wide")
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def status_badge(status: str) -> str:
    s = str(status).upper()
    colors = {
        "JOINED": "green", "CREATED": "blue", "CREATING": "blue",
        "JOINING": "blue", "INVITED": "orange", "PENDING": "orange",
        "READY": "green", "IMPORTING": "blue", "FAILED": "red",
        "SUCCESS": "green", "BLOCKED": "red", "LOCAL_DROP_PENDING": "orange",
        "OK": "green", "FAIL": "red", "WARN": "orange", "INFO": "blue",
    }
    color = colors.get(s, "gray")
    return f":{color}[{s}]"


def metric_row(cols: list[tuple[str, Any, str | None]]) -> None:
    """Render a row of metric cards. Each item is (label, value, delta)."""
    columns = st.columns(len(cols))
    for col, (label, value, delta) in zip(columns, cols):
        col.metric(label, value, delta)


def collaboration_picker(collaborations: list[dict], key: str = "collab") -> dict | None:
    """Sidebar picker for a joined collaboration."""
    if not collaborations:
        st.sidebar.warning("No collaborations visible to your role.")
        return None
    names = [c.get("local_name") or c.get("source_name") for c in collaborations]
    idx = st.sidebar.selectbox("Collaboration", range(len(names)),
                               format_func=lambda i: names[i], key=key)
    return collaborations[idx] if idx is not None else None


def check_list(checks: list[dict]) -> None:
    """Render health-check items as a checklist with fix actions."""
    for c in checks:
        icon = {"ok": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️"}.get(c["status"], "❓")
        st.markdown(f"{icon} **{c['name']}** — {c['detail'][:200]}")
        if c.get("fix"):
            with st.expander("How to fix"):
                st.code(c["fix"], language="sql")
