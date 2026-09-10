"""Activate — send matched records to a collaborator."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header

page_header("Activate", "Send matched audience records to a collaborator")

r = invoke("LIST_COLLABORATIONS")
joined = r["data"]["joined"] if r["ok"] else []
if not joined:
    st.warning("No joined collaborations.")
    st.stop()

collab = st.selectbox("Collaboration", [c["local_name"] for c in joined], key="act_collab")
if not collab:
    st.stop()

pf = invoke("PREFLIGHT", {"collaboration": collab})
if not pf["ok"]:
    show_error(pf)
    st.stop()

d = pf["data"]
if not d["can_activate"]:
    st.warning("Activation is not available for this collaboration.")
    for b in d["blockers"]:
        st.error(b)
    for w in d["warnings"]:
        st.warning(w)
    st.stop()

detail = d["detail"]
source_views = [o["view_name"] for o in detail["partner_offerings"]]
my_views = [o["view_name"] for o in detail["my_offerings"]]

# Pre-fill from the last overlap run if available.
last = st.session_state.get("last_overlap", {})
default_src = last.get("source", source_views[0] if source_views else "")
default_mine = last.get("mine", my_views[0] if my_views else "")

st.subheader("Data sources")
source = st.selectbox("Partner dataset", source_views,
                      index=source_views.index(default_src) if default_src in source_views else 0,
                      key="act_src")
mine = st.selectbox("Your dataset", my_views,
                    index=my_views.index(default_mine) if default_mine in my_views else 0,
                    key="act_mine")

st.subheader("Match keys")
common_keys = d.get("common_join_keys", [])
key_p = st.selectbox("Provider key", common_keys, key="act_kp") if common_keys else st.text_input("Provider key", key="act_kpt")
key_c = st.selectbox("Consumer key", common_keys, key="act_kc") if common_keys else st.text_input("Consumer key", key="act_kct")

st.subheader("Columns to activate")
st.caption("Only columns the data owner marked as activation-allowed are shown. "
           "Deselect any you want to withhold (e.g. PII).")

partner_act = sorted({c for o in detail["partner_offerings"] for c in o["activation_columns"]})
my_act = sorted({c for o in detail["my_offerings"] for c in o["activation_columns"]})

selected_p = st.multiselect("Partner columns", partner_act, default=partner_act, key="act_pcols")
selected_c = st.multiselect("Your columns", my_act, default=my_act, key="act_ccols")

activation_columns = [f"p1.{c}" for c in selected_p] + [f"c1.{c}" for c in selected_c]

st.subheader("Destination and segment")
# Derive allowed destinations from the collaboration config.
dest_options = list({c["alias"] for c in joined[0:1]} | {"PROVIDER", "CONSUMER"})
destination = st.selectbox("Send results to", dest_options, key="act_dest")
segment_name = st.text_input("Segment name (no spaces)", key="act_seg")

where_clause = st.text_input("Filter (optional, e.g. p1.REGION = 'JKT')", key="act_where")

if st.button("Activate", type="primary", disabled=not (segment_name and activation_columns)):
    config = {
        "source_tables": [source], "my_tables": [mine],
        "match_levels": [[{"provider": key_p, "consumer": key_c}]],
        "activation_columns": activation_columns,
        "destination": destination, "segment_name": segment_name,
    }
    if where_clause:
        config["where_clause"] = where_clause

    with st.spinner("Running activation..."):
        r = invoke("RUN_ACTIVATION", {"collaboration": collab, "config": config})
    if r["ok"]:
        st.success(f"Activation complete. Batch: **{r['data'].get('batch_id')}**")
        st.markdown(f"Segment: `{r['data']['segment_name']}` sent to `{r['data']['destination']}`")
        st.info("The recipient can now import the segment in the **Activation Inbox**.")
    else:
        show_error(r)
