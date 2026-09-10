"""History — all runs and activations."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header

page_header("History", "Past overlap runs and activations")

r = invoke("LIST_COLLABORATIONS")
joined = r["data"]["joined"] if r["ok"] else []
if not joined:
    st.warning("No joined collaborations.")
    st.stop()

collab = st.selectbox("Collaboration", [c["local_name"] for c in joined], key="hist_collab")
if not collab:
    st.stop()

r = invoke("ACTIVITY_HISTORY", {"collaboration": collab})
if not r["ok"]:
    show_error(r)
    st.stop()

tab_console, tab_dcr = st.tabs(["Console audit log", "DCR activity history"])

with tab_console:
    history = r["data"].get("console_history", [])
    if history:
        import pandas as pd
        df = pd.DataFrame(history)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No console operations recorded for this collaboration.")

with tab_dcr:
    dcr_hist = r["data"].get("dcr_history", [])
    if dcr_hist:
        import pandas as pd
        df = pd.DataFrame(dcr_hist)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No DCR activity history.")
