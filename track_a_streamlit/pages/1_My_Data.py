"""My Data — browse tables, configure columns, register offerings."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header

page_header("My Data", "Register tables and views as data offerings")

tab_register, tab_existing = st.tabs(["Register new offering", "Existing offerings"])

with tab_register:
    st.subheader("1. Pick a table or view")
    c1, c2, c3 = st.columns(3)
    r_db = invoke("LIST_DATA_OBJECTS")
    databases = r_db["data"]["items"] if r_db["ok"] else []
    db = c1.selectbox("Database", databases, key="reg_db")

    schemas, tables = [], []
    if db:
        r_sch = invoke("LIST_DATA_OBJECTS", {"database": db})
        schemas = r_sch["data"]["items"] if r_sch["ok"] else []
    sch = c2.selectbox("Schema", schemas, key="reg_sch")

    if db and sch:
        r_tbl = invoke("LIST_DATA_OBJECTS", {"database": db, "schema": sch})
        tables = r_tbl["data"]["items"] if r_tbl["ok"] else []
    tbl_names = [t["name"] for t in tables]
    tbl_idx = c3.selectbox("Table / View", range(len(tbl_names)),
                           format_func=lambda i: f"{tbl_names[i]} ({tables[i]['row_count']} rows)",
                           key="reg_tbl") if tbl_names else None
    fqn = tables[tbl_idx]["fqn"] if tbl_idx is not None else None

    if fqn:
        st.subheader("2. Configure columns")
        r_cols = invoke("DESCRIBE_COLUMNS", {"fqn": fqn})
        if not r_cols["ok"]:
            show_error(r_cols)
            st.stop()
        columns = r_cols["data"]["columns"]
        categories = r_cols["data"]["categories"]
        column_types = r_cols["data"]["column_types"]

        configured = []
        for col in columns:
            with st.expander(f"**{col['name']}** ({col['data_type']})" +
                             (f" — suggested: {col['suggested_column_type']}" if col["suggested_column_type"] else "")):
                cat = st.selectbox(
                    "Category", categories, key=f"cat_{col['name']}",
                    index=categories.index(col["suggested_category"]) if col["suggested_category"] in categories else
                          categories.index("passthrough"))
                ct = None
                if cat == "join_standard":
                    default_ct = col["suggested_column_type"] or column_types[0]
                    ct = st.selectbox("Column type (PII identifier)", column_types,
                                     index=column_types.index(default_ct) if default_ct in column_types else 0,
                                     key=f"ct_{col['name']}")
                    st.caption(f"Exposed in shared view as: **{ct.upper()}**")
                act = st.checkbox("Activation allowed", value=col["activation_allowed"],
                                  key=f"act_{col['name']}")
                configured.append({
                    "name": col["name"], "category": cat,
                    "column_type": ct, "activation_allowed": act,
                })

        st.subheader("3. Name and register")
        c_name, c_ver = st.columns(2)
        off_name = c_name.text_input("Offering name", key="off_name")
        off_ver = c_ver.text_input("Version", value="v1_0", key="off_ver")
        off_desc = st.text_input("Description (optional)", key="off_desc")

        if st.button("Register offering", type="primary", disabled=not off_name):
            config = {
                "name": off_name, "version": off_ver, "description": off_desc,
                "datasets": [{"alias": tbl_names[tbl_idx].lower(),
                              "data_object_fqn": fqn, "columns": configured}],
            }
            with st.spinner("Registering..."):
                r = invoke("REGISTER_OFFERING", {"config": config})
            if r["ok"]:
                st.success(f"Registered: **{r['data']['offering_id']}**")
                for ds in r["data"]["datasets"]:
                    join_cols = [c for c in ds["columns"] if c["is_join_key"]]
                    for jc in join_cols:
                        st.info(f"Join column `{jc['name']}` is exposed as "
                                f"**`{jc['exposed_name']}`** in the shared view.")
            else:
                show_error(r)

with tab_existing:
    if st.button("Refresh", key="refresh_offerings"):
        st.rerun()
    r = invoke("LIST_OFFERINGS")
    if r["ok"]:
        offerings = r["data"]["offerings"]
        if offerings:
            for o in offerings:
                with st.expander(f"**{o['DATA_OFFERING_ID']}** — registered {o.get('CREATED_ON','')}"):
                    st.text(o.get("DATA_OFFERING_SPEC", "")[:2000])
                    if st.button(f"Unregister {o['DATA_OFFERING_ID']}", key=f"unreg_{o['DATA_OFFERING_ID']}"):
                        r2 = invoke("UNREGISTER_OFFERING", {"offering_id": o["DATA_OFFERING_ID"]})
                        if r2["ok"]:
                            st.success("Unregistered.")
                            st.rerun()
                        else:
                            show_error(r2)
        else:
            st.info("No offerings registered yet.")
    else:
        show_error(r)
