"""Create Collaboration — 4-step wizard."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header

page_header("Create Collaboration", "Initialize a new audience-overlap collaboration")

st.subheader("Step 1 — Collaboration details")
name = st.text_input("Collaboration name", key="cc_name")
desc = st.text_area("Description", key="cc_desc")

st.subheader("Step 2 — Collaborators")
st.caption("Add at least two collaborators. One must be the owner.")

r_acct = invoke("HEALTH_CHECK")
my_account = r_acct["data"]["checks"][0]["detail"].split(",")[0] if r_acct["ok"] else ""

num_collabs = st.number_input("Number of collaborators", min_value=2, max_value=6, value=2, key="cc_num")
collaborators = []
for i in range(int(num_collabs)):
    c1, c2 = st.columns(2)
    alias = c1.text_input(f"Alias #{i+1}", value="PROVIDER" if i == 0 else f"PARTNER_{i}",
                          key=f"cc_alias_{i}")
    account = c2.text_input(f"Account #{i+1} (ORG.ACCOUNT)",
                            value=my_account if i == 0 else "", key=f"cc_acct_{i}")
    collaborators.append({"alias": alias.upper(), "account": account})

owner = st.selectbox("Owner", [c["alias"] for c in collaborators], key="cc_owner")

st.subheader("Step 3 — Analysis runners")
st.caption("Who can run the overlap? Add each runner and map their data providers.")

r_off = invoke("LIST_OFFERINGS")
offering_ids = [o["DATA_OFFERING_ID"] for o in r_off["data"]["offerings"]] if r_off["ok"] else []

runner_alias = st.selectbox("Analysis runner", [c["alias"] for c in collaborators], key="cc_runner")
provider_alias = st.selectbox("Their data provider", [c["alias"] for c in collaborators], key="cc_dp")
provider_offerings = st.multiselect("Provider's offering IDs", offering_ids, key="cc_dp_off")

activation_dest = st.multiselect("Activation destinations",
                                 [c["alias"] for c in collaborators], key="cc_act_dest")

# If the runner's provider is not the runner itself, the provider also needs a role.
# Add the runner as a data provider of itself with an empty list as a placeholder
# when needed.
analysis_runners = [{
    "alias": runner_alias,
    "data_providers": [
        {"alias": provider_alias, "offerings": provider_offerings},
    ],
    "activation_destinations": activation_dest,
}]

# Ensure every collaborator has a role
aliases_with_roles = {owner, runner_alias, provider_alias}
roleless = [c["alias"] for c in collaborators if c["alias"] not in aliases_with_roles]
if roleless:
    st.warning(f"These collaborators have no role yet: {', '.join(roleless)}. "
               "Adding them as data providers with empty offering lists.")
    for rl in roleless:
        analysis_runners[0]["data_providers"].append({"alias": rl, "offerings": []})

st.subheader("Step 4 — Review and create")
auto_join = st.checkbox("Auto-join as owner (recommended)", value=True, key="cc_autojoin")
auto_join_wh = st.text_input("Warehouse for auto-join", value="APP_WH", key="cc_wh") if auto_join else None

config = {
    "name": name, "description": desc, "owner": owner,
    "collaborators": collaborators, "analysis_runners": analysis_runners,
}

with st.expander("Preview generated spec"):
    st.json(config)

if st.button("Create collaboration", type="primary", disabled=not name):
    payload = {"config": config}
    if auto_join_wh:
        payload["auto_join_warehouse"] = auto_join_wh
    with st.spinner("Creating collaboration (this may take a few minutes)..."):
        r = invoke("CREATE_COLLABORATION", payload)
    if r["ok"]:
        st.success(f"Created: **{r['data']['collaboration_name']}**")
        st.json(r["data"]["status"])
        st.info("If auto-join fails silently, use the Health Check or poll the status. "
                "The partner must now join from their account.")
    else:
        show_error(r)
