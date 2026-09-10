"""Invitations — review and join pending collaborations."""

import streamlit as st
from lib.facade import invoke, invoke_direct, show_error
from lib.ui import page_header, status_badge

page_header("Invitations", "Review and join collaborations you have been invited to")

r = invoke("LIST_COLLABORATIONS")
if not r["ok"]:
    show_error(r)
    st.stop()

invited = r["data"].get("invited", [])
if not invited:
    st.info("No pending invitations. If you expect one, the provider may not have "
            "created the collaboration yet, or it may be cross-region without "
            "Cross-Cloud Auto-Fulfillment enabled.")
    st.stop()

for inv in invited:
    src = inv.get("source_name")
    owner = inv.get("owner_account")
    st.subheader(f"{src}")
    st.markdown(f"From: `{owner}`")

    with st.expander("Collaboration spec"):
        st.text(inv.get("spec", "")[:3000])

    local_name = st.text_input("Local name for this collaboration",
                               value=src, key=f"ln_{src}")

    if st.button(f"Review and join", key=f"join_{src}", type="primary"):
        with st.spinner("Reviewing..."):
            try:
                # REVIEW + JOIN must run at session level (JOIN is nest-unsafe).
                invoke_direct(
                    "CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION.REVIEW(?, ?, ?)",
                    [src, owner, local_name])
                st.success("Review complete.")
            except Exception as e:
                st.error(f"Review failed: {e}")
                st.stop()

        with st.spinner("Joining (this may take a few minutes)..."):
            try:
                invoke_direct(
                    "CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION.JOIN(?)",
                    [local_name])
                st.success(f"Joined as **{local_name}**. Refresh to see it in the sidebar.")
            except Exception as e:
                st.error(f"Join failed: {e}")

    st.divider()

st.subheader("Check collaboration status")
status_name = st.text_input("Collaboration name", key="status_name")
if st.button("Check status", disabled=not status_name):
    r = invoke("GET_STATUS", {"collaboration": status_name})
    if r["ok"]:
        for s in r["data"]["status"]:
            st.markdown(f"{status_badge(s.get('STATUS', 'unknown'))} "
                        f"**{s.get('COLLABORATOR_NAME', '')}** — {s.get('ROLES', '')}")
    else:
        show_error(r)
