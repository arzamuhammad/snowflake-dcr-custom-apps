"""Activation Inbox — import and flatten activated segments into usable tables."""

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header, status_badge

page_header("Activation Inbox", "Import activated segments and materialise them as tables")

r = invoke("LIST_COLLABORATIONS")
joined = r["data"]["joined"] if r["ok"] else []
if not joined:
    st.warning("No joined collaborations.")
    st.stop()

collab = st.selectbox("Collaboration", [c["local_name"] for c in joined], key="inbox_collab")
if not collab:
    st.stop()

r = invoke("LIST_ACTIVATIONS", {"collaboration": collab})
if not r["ok"]:
    show_error(r)
    st.stop()

activations = r["data"]["activations"]
if not activations:
    st.info("No activations for this collaboration yet.")
    st.stop()

for act in activations:
    batch = act.get("batch_id", "unknown")
    segment = act.get("segment_name", "")
    status = act.get("status", "unknown")
    imp = act.get("import")
    imported = act.get("imported", False)

    with st.expander(f"{status_badge(status)} **{segment}** — batch `{batch[:12]}...`"):
        st.markdown(f"Status: {status} | Updated: {act.get('updated_on', '')}")

        if imported and imp:
            st.success(f"Already imported to `{imp['target_fqn']}` "
                       f"({imp['imported_rows']} rows)")
        elif imp and imp["status"] == "FAILED":
            st.error(f"Previous import failed: {imp.get('error_raw', '')[:300]}")

        st.subheader("Import into a table")
        target = st.text_input("Target table (DB.SCHEMA.TABLE)",
                               value=f"DEMO_CONSUMER_DB.ACTIVATED.{segment.upper()}" if segment else "",
                               key=f"tgt_{batch}")

        if st.button("Import and flatten", key=f"imp_{batch}", type="primary"):
            with st.spinner("Processing and flattening..."):
                r = invoke("IMPORT_ACTIVATION", {
                    "collaboration": collab, "batch_id": batch,
                    "target_fqn": target,
                })
            if r["ok"]:
                d = r["data"]
                st.success(f"Imported **{d['imported_rows']:,}** rows into `{d['target_fqn']}`")
                if d.get("process_note"):
                    with st.expander("Process note"):
                        st.text(d["process_note"])
            else:
                show_error(r)

        if imp and imp.get("import_id"):
            prog = invoke("GET_IMPORT_PROGRESS", {"import_id": imp["import_id"]})
            if prog["ok"]:
                p = prog["data"]
                pct = p.get("percent_complete")
                if pct is not None:
                    st.progress(min(pct / 100.0, 1.0),
                                text=f"{pct:.1f}% — {p.get('imported_rows', 0):,} / "
                                     f"{p.get('expected_rows', '?'):,} rows")
