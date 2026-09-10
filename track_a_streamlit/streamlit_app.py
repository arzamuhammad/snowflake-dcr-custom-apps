"""
DCR Audience Overlap Console

A point-and-click application for Snowflake Data Clean Rooms (Collaboration API v2).
Navigate using the sidebar pages.
"""

import streamlit as st
from lib.facade import invoke
from lib.ui import page_header, collaboration_picker

page_header("DCR Audience Overlap Console",
            "Collaboration API v2 — zero SQL, zero YAML")

r = invoke("LIST_COLLABORATIONS")
if not r["ok"]:
    st.error("Could not load collaborations.")
    st.json(r.get("error"))
    st.stop()

data = r["data"]
account = data.get("account", "unknown")
st.sidebar.markdown(f"**Account:** `{account}`")

joined = data.get("joined", [])
invited = data.get("invited", [])

col1, col2, col3 = st.columns(3)
col1.metric("Joined", len(joined))
col2.metric("Pending invitations", len(invited))
col3.metric("Total", len(joined) + len(invited))

st.divider()

if joined:
    st.subheader("Joined collaborations")
    for c in joined:
        name = c.get("local_name") or c.get("source_name")
        owner = c.get("owner_account")
        badge = "Owner" if c.get("is_owner") else "Collaborator"
        with st.expander(f"**{name}** — {badge} (owner: `{owner}`)"):
            st.text(f"Updated: {c.get('updated_on')}")

if invited:
    st.subheader("Pending invitations")
    for c in invited:
        name = c.get("source_name")
        owner = c.get("owner_account")
        st.info(f"**{name}** from `{owner}` — go to **Invitations** to review and join.")

if not joined and not invited:
    st.info("No collaborations yet. Create one on the **Create Collaboration** page, "
            "or ask a partner to invite you.")
