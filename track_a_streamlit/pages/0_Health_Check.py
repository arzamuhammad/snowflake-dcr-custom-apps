"""Health Check — prerequisite traffic lights."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header, check_list

page_header("Health Check", "Verify prerequisites before using the console")

if st.button("Run health check", type="primary"):
    with st.spinner("Checking prerequisites..."):
        r = invoke("HEALTH_CHECK")
    if not r["ok"]:
        show_error(r)
    else:
        d = r["data"]
        if d["ready"]:
            st.success("All prerequisites met. You are ready to go.")
        else:
            st.error(f"Blocking issues: {', '.join(d['blocking_failures'])}")
        check_list(d["checks"])

st.divider()
if st.button("Register standard templates"):
    with st.spinner("Registering..."):
        r = invoke("REGISTER_STANDARD_TEMPLATES")
    if r["ok"]:
        st.success(f"Templates: {', '.join(r['data']['templates'])}")
    else:
        show_error(r)
