"""Admin — update requests, template management, leave/teardown."""

import streamlit as st
from lib.facade import invoke, invoke_direct, show_error
from lib.ui import page_header, status_badge

page_header("Admin", "Template requests, collaboration management, and app RBAC")

r = invoke("LIST_COLLABORATIONS")
joined = r["data"]["joined"] if r["ok"] else []
if not joined:
    st.warning("No joined collaborations.")
    st.stop()

collab = st.selectbox("Collaboration", [c["local_name"] for c in joined], key="adm_collab")
if not collab:
    st.stop()

tab_requests, tab_templates, tab_lifecycle, tab_rbac = st.tabs([
    "Update requests", "Add template", "Leave / Teardown", "App RBAC"])

with tab_requests:
    r = invoke("LIST_UPDATE_REQUESTS", {"collaboration": collab})
    if r["ok"]:
        reqs = r["data"]["requests"]
        if reqs:
            for req in reqs:
                rid = req.get("REQUEST_ID", req.get("UPDATE_REQUEST_ID", "?"))
                status = req.get("STATUS", "PENDING")
                st.markdown(f"{status_badge(status)} Request `{rid}`")
                with st.expander("Details"):
                    st.json(req)
                c1, c2 = st.columns(2)
                if c1.button(f"Approve {rid}", key=f"app_{rid}"):
                    r2 = invoke("APPROVE_UPDATE_REQUEST",
                                {"collaboration": collab, "request_id": str(rid)})
                    st.success("Approved.") if r2["ok"] else show_error(r2)
                reason = c2.text_input("Reason", key=f"rej_reason_{rid}")
                if c2.button(f"Reject {rid}", key=f"rej_{rid}"):
                    r2 = invoke("REJECT_UPDATE_REQUEST",
                                {"collaboration": collab, "request_id": str(rid),
                                 "reason": reason or "No reason given."})
                    st.success("Rejected.") if r2["ok"] else show_error(r2)
        else:
            st.info("No pending update requests.")
    else:
        show_error(r)

with tab_templates:
    st.caption("Add a template to a live collaboration. Requires approval from all affected parties.")
    template_id = st.text_input("Template ID", key="adm_tid")
    runners = st.text_input("Runner aliases (comma-separated)", key="adm_runners")
    if st.button("Add template request", disabled=not (template_id and runners)):
        runner_list = [r.strip().upper() for r in runners.split(",") if r.strip()]
        r = invoke("ADD_TEMPLATE", {"collaboration": collab, "template_id": template_id,
                                     "runners": runner_list})
        st.success("Request submitted.") if r["ok"] else show_error(r)

with tab_lifecycle:
    is_owner = any(c.get("is_owner") for c in joined if c.get("local_name") == collab)
    if is_owner:
        st.warning("You are the **owner**. Teardown removes the collaboration for ALL participants. "
                   "This cannot be undone.")
        if st.button("Teardown collaboration", type="primary", key="adm_teardown"):
            with st.spinner("Tearing down (two-call protocol)..."):
                r = invoke("TEARDOWN_OR_LEAVE", {"collaboration": collab, "mode": "teardown"})
            if r["ok"]:
                st.success(f"Teardown complete. Two-call: {r['data'].get('two_call_completed')}")
            else:
                show_error(r)
    else:
        st.info("You are a **collaborator**. Leave removes your data but does not delete the collaboration.")
        if st.button("Leave collaboration", type="primary", key="adm_leave"):
            with st.spinner("Leaving..."):
                r = invoke("TEARDOWN_OR_LEAVE", {"collaboration": collab, "mode": "leave"})
            if r["ok"]:
                st.success("Left the collaboration.")
            else:
                show_error(r)

with tab_rbac:
    st.caption("App-level permission tiers (layered on top of DCR privileges).")
    r = invoke("GET_APP_ROLE")
    if r["ok"]:
        me = r["data"]
        st.markdown(f"Your role: **{me['app_role']}** | "
                    f"View: {'yes' if me['can_view'] else 'no'} | "
                    f"Run: {'yes' if me['can_run_overlap'] else 'no'} | "
                    f"Activate: {'yes' if me['can_activate'] else 'no'} | "
                    f"Build: {'yes' if me['can_build'] else 'no'}")

    st.subheader("Assign role")
    username = st.text_input("Username", key="rbac_user")
    role = st.selectbox("App role", ["VIEWER", "ANALYST", "ACTIVATOR", "BUILDER"], key="rbac_role")
    if st.button("Assign", disabled=not username, key="rbac_assign"):
        r = invoke("SET_APP_ROLE", {"username": username, "app_role": role})
        st.success(f"Assigned {role} to {username}.") if r["ok"] else show_error(r)
