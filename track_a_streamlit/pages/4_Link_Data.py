"""Link Data — connect offerings to a collaboration (both partner and local)."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header, status_badge

page_header("Link Data", "Connect your data and your partner's data to a collaboration")

r = invoke("LIST_COLLABORATIONS")
joined = r["data"]["joined"] if r["ok"] else []
if not joined:
    st.warning("No joined collaborations. Create or join one first.")
    st.stop()

names = [c["local_name"] for c in joined]
collab = st.selectbox("Collaboration", names, key="ld_collab")

if collab:
    detail = invoke("GET_COLLABORATION_DETAIL", {"collaboration": collab})
    if not detail["ok"]:
        show_error(detail)
        st.stop()
    d = detail["data"]

    st.subheader("Partner offerings (source tables)")
    if d["partner_offerings"]:
        for o in d["partner_offerings"]:
            st.markdown(f"- **{o['offering_id']}** — view: `{o['view_name']}` | "
                        f"join: {', '.join(o['join_columns'])}")
    else:
        st.warning("No partner data available yet. The data provider must share an offering.")

    st.subheader("Your linked data (my tables)")
    if d["my_offerings"]:
        for o in d["my_offerings"]:
            st.markdown(f"- **{o['offering_id']}** — view: `{o['view_name']}` | "
                        f"join: {', '.join(o['join_columns'])}")
    else:
        st.error("You have not linked any of your own data. Without this, no overlap "
                 "is possible. Use the form below to link your table.")

    st.divider()

    tab_local, tab_partner = st.tabs(["Link my own data", "Share my offering to runners"])

    with tab_local:
        st.caption("Attach your own registered offering so it becomes the `c1` (my_table) side.")
        r_off = invoke("LIST_OFFERINGS")
        off_ids = [o["DATA_OFFERING_ID"] for o in r_off["data"]["offerings"]] if r_off["ok"] else []
        local_off = st.selectbox("My offering ID", off_ids, key="ld_local_off")
        if st.button("Link my data", type="primary", disabled=not local_off, key="ld_link_local"):
            with st.spinner("Linking..."):
                r = invoke("LINK_DATA", {"collaboration": collab,
                                         "offering_id": local_off, "mode": "local"})
            if r["ok"]:
                st.success(f"Linked **{local_off}** as your local data.")
                st.rerun()
            else:
                show_error(r)

    with tab_partner:
        st.caption("Share one of your offerings to analysis runners in this collaboration.")
        partner_off = st.selectbox("Offering to share", off_ids, key="ld_partner_off")
        aliases = [c.get("alias", c.get("local_name", "")) for c in joined]
        runners = st.multiselect("Share with runners", aliases, key="ld_runners")
        if st.button("Share offering", disabled=not (partner_off and runners), key="ld_link_partner"):
            with st.spinner("Sharing..."):
                r = invoke("LINK_DATA", {"collaboration": collab,
                                         "offering_id": partner_off, "mode": "partner",
                                         "runners": runners})
            if r["ok"]:
                st.success("Shared.")
                st.rerun()
            else:
                show_error(r)
