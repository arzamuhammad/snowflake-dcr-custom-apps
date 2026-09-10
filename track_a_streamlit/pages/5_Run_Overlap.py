"""Run Overlap — configure match keys, run, view results."""

import json

import streamlit as st
from lib.facade import invoke, show_error
from lib.ui import page_header, metric_row

page_header("Run Overlap", "Measure audience overlap between you and your partner")

r = invoke("LIST_COLLABORATIONS")
joined = r["data"]["joined"] if r["ok"] else []
if not joined:
    st.warning("No joined collaborations.")
    st.stop()

collab = st.selectbox("Collaboration", [c["local_name"] for c in joined], key="ro_collab")
if not collab:
    st.stop()

pf = invoke("PREFLIGHT", {"collaboration": collab})
if not pf["ok"]:
    show_error(pf)
    st.stop()

d = pf["data"]
if not d["can_run_overlap"]:
    st.error("Cannot run overlap.")
    for b in d["blockers"]:
        st.warning(b)
    st.stop()

detail = d["detail"]

st.subheader("Data sources")
source_views = [o["view_name"] for o in detail["partner_offerings"]]
my_views = [o["view_name"] for o in detail["my_offerings"]]
source = st.selectbox("Partner dataset", source_views, key="ro_src")
mine = st.selectbox("Your dataset", my_views, key="ro_mine")

st.subheader("Match keys")
st.caption("Configure the waterfall: keys tried in order, first match wins. "
           "Use the **exposed** column name (shown in Link Data).")
common_keys = d.get("common_join_keys", [])

num_levels = st.number_input("Waterfall levels", min_value=1, max_value=10, value=1, key="ro_levels")
match_levels = []
for i in range(int(num_levels)):
    with st.expander(f"Level {i+1}", expanded=i == 0):
        key_p = st.selectbox(f"Provider key (level {i+1})", common_keys,
                             key=f"ro_kp_{i}") if common_keys else st.text_input(
                             f"Provider key (level {i+1})", key=f"ro_kpt_{i}")
        key_c = st.selectbox(f"Consumer key (level {i+1})", common_keys,
                             key=f"ro_kc_{i}") if common_keys else st.text_input(
                             f"Consumer key (level {i+1})", key=f"ro_kct_{i}")
        match_levels.append([{"provider": key_p, "consumer": key_c}])

st.subheader("Filters (optional)")
all_analysis = sorted({c for o in detail["partner_offerings"] for c in o["analysis_columns"]})
my_analysis = sorted({c for o in detail["my_offerings"] for c in o["analysis_columns"]})

source_where = st.text_input("Provider filter (e.g. p1.REGION = 'JKT')", key="ro_swhere")
my_where = st.text_input("Your filter (e.g. c1.SEGMENT = 'GOLD')", key="ro_mwhere")
source_group = st.multiselect("Provider group-by", [f"p1.{c}" for c in all_analysis], key="ro_sgb")
my_group = st.multiselect("Your group-by", [f"c1.{c}" for c in my_analysis], key="ro_mgb")

use_cache = st.checkbox("Use cached result if available", value=True, key="ro_cache")

if st.button("Run overlap analysis", type="primary"):
    config = {
        "source_tables": [source], "my_tables": [mine],
        "match_levels": match_levels,
    }
    if source_where:
        config["source_where_clause"] = source_where
    if my_where:
        config["my_where_clause"] = my_where
    if source_group:
        config["source_group_by"] = source_group
    if my_group:
        config["my_group_by"] = my_group

    with st.spinner("Running overlap analysis..."):
        r = invoke("RUN_OVERLAP", {"collaboration": collab, "config": config,
                                    "use_cache": use_cache})
    if not r["ok"]:
        show_error(r)
    else:
        data = r["data"]
        s = data.get("summary", {})

        if data.get("from_cache"):
            st.info(f"Result from cache (computed {data.get('computed_at', 'earlier')}). "
                    "Uncheck 'Use cached result' to re-run.")

        st.subheader("Results")
        matched = s.get("matched", 0)
        total = s.get("total", 0)
        unmatched = s.get("unmatched", 0)
        rate = s.get("match_rate")

        metric_row([
            ("Matched", f"{matched:,}", None),
            ("Unmatched", f"{unmatched:,}", None),
            ("Total", f"{total:,}", None),
            ("Match rate", f"{rate:.2%}" if rate else "N/A", None),
        ])

        if s.get("privacy_suppressed"):
            st.warning("Some counts were suppressed to protect privacy (fewer than 5 matches).")

        st.subheader("Waterfall detail")
        levels = data.get("levels", [])
        if levels:
            import pandas as pd
            df = pd.DataFrame(levels)
            st.dataframe(df, use_container_width=True)

        st.subheader("Raw rows")
        with st.expander("Show raw result"):
            st.json(data.get("rows", []))

        st.session_state["last_overlap"] = {
            "collaboration": collab, "config": config,
            "summary": s, "source": source, "mine": mine, "match_levels": match_levels,
        }
        st.success("Overlap complete. Proceed to **Activate** to send matched records.")
