"""
Golden-file tests for dcr_specs.

The reference specs are the ones PROVEN to work end-to-end in this account: the
registered telco_provider_offering_v1_0 and the live telco_audience_overlap
collaboration. Comparison is SEMANTIC — parsed YAML trees, not bytes — because
flow style ({a: 1}) and block style are equivalent to the API.

Run:  .venv/bin/python -m pytest test_dcr_specs.py -q
"""

from __future__ import annotations

import pytest
import yaml

import dcr_specs as ds


def parsed(spec_yaml: str) -> dict:
    return yaml.safe_load(spec_yaml)


# ---------------------------------------------------------------------------
# data_offering
# ---------------------------------------------------------------------------

PROVIDER_COLUMNS = [
    {"name": "HASHED_MSISDN", "category": "join_standard",
     "column_type": "hashed_phone_sha256", "activation_allowed": False},
    {"name": "ARPU_BAND", "category": "passthrough", "activation_allowed": True},
    {"name": "DATA_USAGE_TIER", "category": "passthrough", "activation_allowed": True},
    {"name": "DEVICE_TYPE", "category": "passthrough", "activation_allowed": True},
    {"name": "REGION", "category": "passthrough", "activation_allowed": True},
    {"name": "TENURE_BAND", "category": "passthrough", "activation_allowed": True},
    {"name": "PLAN_TYPE", "category": "passthrough", "activation_allowed": True},
    {"name": "CHURN_RISK", "category": "passthrough", "activation_allowed": True},
]

PROVIDER_CFG = {
    "name": "telco_provider_offering",
    "version": "v1_0",
    "description": "Telco subscriber attributes for audience overlap and activation.",
    "datasets": [{
        "alias": "subscribers",
        "data_object_fqn": "DCR_PROVIDER.DATA.TELCO_SUBSCRIBERS",
        "columns": PROVIDER_COLUMNS,
    }],
}

# Verbatim from the registered telco_provider_offering_v1_0.
#
# NOTE: the keys below are deliberately NOT padded for visual alignment. Padding
# swallows the space after the colon on the longest key (`DATA_USAGE_TIER:{`),
# which is invalid YAML and fails with "mapping values are not allowed here".
# That exact mistake was made while first writing this file and caught here.
GOLDEN_PROVIDER_OFFERING = """
api_version: "2.0.0"
spec_type: data_offering
name: telco_provider_offering
version: v1_0
description: Telco subscriber attributes for audience overlap and activation.
datasets:
- alias: subscribers
  data_object_fqn: DCR_PROVIDER.DATA.TELCO_SUBSCRIBERS
  allowed_analyses: template_only
  object_class: custom
  schema_and_template_policies:
    HASHED_MSISDN:
      category: join_standard
      column_type: hashed_phone_sha256
      activation_allowed: false
    ARPU_BAND: { category: passthrough, activation_allowed: true }
    DATA_USAGE_TIER: { category: passthrough, activation_allowed: true }
    DEVICE_TYPE: { category: passthrough, activation_allowed: true }
    REGION: { category: passthrough, activation_allowed: true }
    TENURE_BAND: { category: passthrough, activation_allowed: true }
    PLAN_TYPE: { category: passthrough, activation_allowed: true }
    CHURN_RISK: { category: passthrough, activation_allowed: true }
"""


def test_offering_matches_golden():
    out = ds.build_offering_spec(PROVIDER_CFG)
    assert out["offering_id"] == "telco_provider_offering_v1_0"
    assert parsed(out["spec_yaml"]) == parsed(GOLDEN_PROVIDER_OFFERING)


def test_offering_api_version_is_a_string_not_a_float():
    """The API rejects the float 2.0; it must round-trip as the string '2.0.0'."""
    v = parsed(ds.build_offering_spec(PROVIDER_CFG)["spec_yaml"])["api_version"]
    assert v == "2.0.0" and isinstance(v, str)


def test_offering_reports_the_renamed_join_column():
    out = ds.build_offering_spec(PROVIDER_CFG)
    cols = {c["name"]: c for c in out["datasets"][0]["columns"]}
    # This rename is the #1 cause of "unauthorized column" errors downstream.
    assert cols["HASHED_MSISDN"]["exposed_name"] == "HASHED_PHONE_SHA256"
    assert cols["ARPU_BAND"]["exposed_name"] == "ARPU_BAND"


def test_large_offering_does_not_hit_the_session_variable_limit():
    """A 1000-column offering is normal for a C360. It must still be one string."""
    cols = [PROVIDER_COLUMNS[0]] + [
        {"name": f"FEATURE_{i}", "category": "passthrough", "activation_allowed": True}
        for i in range(1000)
    ]
    cfg = dict(PROVIDER_CFG)
    cfg["datasets"] = [{"alias": "wide", "data_object_fqn": "D.S.T", "columns": cols}]
    out = ds.build_offering_spec(cfg)
    assert len(out["spec_yaml"]) > 256  # far beyond the SET variable cap
    assert len(parsed(out["spec_yaml"])["datasets"][0]["schema_and_template_policies"]) == 1001


# ---------------------------------------------------------------------------
# column validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_type", ["dimension", "date", "partition", "custom", "DIMENSION"])
def test_rejects_non_pii_column_types(bad_type):
    cfg = {"name": "o", "version": "v1", "datasets": [{
        "alias": "a", "data_object_fqn": "D.S.T",
        "columns": [{"name": "C", "category": "join_standard", "column_type": bad_type}]}]}
    with pytest.raises(ds.SpecError) as e:
        ds.build_offering_spec(cfg)
    assert "join_custom" in str(e.value)  # steers the user to the right fix


def test_join_standard_requires_a_column_type():
    cfg = {"name": "o", "version": "v1", "datasets": [{
        "alias": "a", "data_object_fqn": "D.S.T",
        "columns": [{"name": "C", "category": "join_standard"}]}]}
    with pytest.raises(ds.SpecError, match="requires a column_type"):
        ds.build_offering_spec(cfg)


def test_rejects_duplicate_column_type_in_one_dataset():
    cfg = {"name": "o", "version": "v1", "datasets": [{
        "alias": "a", "data_object_fqn": "D.S.T",
        "columns": [
            {"name": "A", "category": "join_standard", "column_type": "email"},
            {"name": "B", "category": "join_standard", "column_type": "email"},
        ]}]}
    with pytest.raises(ds.SpecError, match="already used"):
        ds.build_offering_spec(cfg)


def test_rejects_offering_with_no_join_key():
    cfg = {"name": "o", "version": "v1", "datasets": [{
        "alias": "a", "data_object_fqn": "D.S.T",
        "columns": [{"name": "A", "category": "passthrough"}]}]}
    with pytest.raises(ds.SpecError, match="No join key"):
        ds.build_offering_spec(cfg)


def test_join_custom_keeps_the_original_name():
    assert ds.exposed_column_name("LOYALTY_ID", "join_custom", None) == "LOYALTY_ID"
    assert ds.exposed_column_name("EVENT_AT", "timestamp", None) == "TIMESTAMP"


def test_rejects_bad_fqn():
    cfg = {"name": "o", "version": "v1", "datasets": [{
        "alias": "a", "data_object_fqn": "just_a_table",
        "columns": [PROVIDER_COLUMNS[0]]}]}
    with pytest.raises(ds.SpecError, match="DATABASE.SCHEMA.OBJECT"):
        ds.build_offering_spec(cfg)


# ---------------------------------------------------------------------------
# collaboration
# ---------------------------------------------------------------------------

COLLAB_CFG = {
    "name": "telco_audience_overlap",
    "description": ("Provider shares telco attributes with the consumer for audience "
                    "overlap and activation."),
    "owner": "PROVIDER",
    "collaborators": [
        {"alias": "PROVIDER", "account": "MYORG.PROVIDER_ACCOUNT"},
        {"alias": "CONSUMER", "account": "MYORG.CONSUMER_ACCOUNT"},
    ],
    "analysis_runners": [{
        "alias": "CONSUMER",
        "data_providers": [{"alias": "PROVIDER", "offerings": ["telco_provider_offering_v1_0"]}],
        "activation_destinations": ["CONSUMER"],
    }],
}

# Verbatim from the live telco_audience_overlap collaboration spec.
GOLDEN_COLLAB = """
api_version: "2.0.0"
spec_type: collaboration
name: telco_audience_overlap
description: Provider shares telco attributes with the consumer for audience overlap and activation.
owner: PROVIDER
collaborator_identifier_aliases:
  PROVIDER: MYORG.PROVIDER_ACCOUNT
  CONSUMER: MYORG.CONSUMER_ACCOUNT
analysis_runners:
  CONSUMER:
    data_providers:
      PROVIDER:
        data_offerings:
        - id: telco_provider_offering_v1_0
    templates:
    - id: standard_audience_overlap_v0
    - id: standard_audience_overlap_activation_v0
    activation_destinations:
      snowflake_collaborators:
      - CONSUMER
"""


def test_collaboration_matches_the_live_spec():
    out = ds.build_collaboration_spec(COLLAB_CFG)
    assert parsed(out["spec_yaml"]) == parsed(GOLDEN_COLLAB)


def test_both_standard_templates_are_added_by_default():
    """This is what makes the tutorial's 'link a template' step unnecessary."""
    tmpl = parsed(ds.build_collaboration_spec(COLLAB_CFG)["spec_yaml"]) \
        ["analysis_runners"]["CONSUMER"]["templates"]
    assert [t["id"] for t in tmpl] == [
        "standard_audience_overlap_v0",
        "standard_audience_overlap_activation_v0",
    ]


def test_rejects_account_locator_instead_of_org_account():
    """Pasting the URL locator creates a collaboration the partner never sees."""
    cfg = {**COLLAB_CFG, "collaborators": [
        {"alias": "PROVIDER", "account": "MYORG.PROVIDER_ACCOUNT"},
        {"alias": "CONSUMER", "account": "xy12345.ap-southeast-3.aws"},
    ]}
    with pytest.raises(ds.SpecError, match="ORG.ACCOUNT"):
        ds.build_collaboration_spec(cfg)


def test_owner_must_be_a_declared_collaborator():
    with pytest.raises(ds.SpecError, match="not one of the collaborator aliases"):
        ds.build_collaboration_spec({**COLLAB_CFG, "owner": "NOBODY"})


def test_activation_destination_must_be_a_declared_collaborator():
    cfg = {**COLLAB_CFG, "analysis_runners": [{
        "alias": "CONSUMER",
        "data_providers": [{"alias": "PROVIDER", "offerings": ["o_v1_0"]}],
        "activation_destinations": ["STRANGER"]}]}
    with pytest.raises(ds.SpecError, match="Activation destination"):
        ds.build_collaboration_spec(cfg)


def test_both_sides_can_be_analysis_runners():
    """Required if provider AND consumer should each be able to run an overlap."""
    cfg = {**COLLAB_CFG, "analysis_runners": [
        {"alias": "CONSUMER",
         "data_providers": [{"alias": "PROVIDER", "offerings": ["p_v1_0"]}],
         "activation_destinations": ["CONSUMER"]},
        {"alias": "PROVIDER",
         "data_providers": [{"alias": "CONSUMER", "offerings": ["c_v1_0"]}],
         "activation_destinations": ["PROVIDER"]},
    ]}
    runners = parsed(ds.build_collaboration_spec(cfg)["spec_yaml"])["analysis_runners"]
    assert set(runners) == {"CONSUMER", "PROVIDER"}


def test_empty_offering_list_is_allowed_as_a_placeholder():
    cfg = {**COLLAB_CFG, "analysis_runners": [{
        "alias": "CONSUMER", "data_providers": [{"alias": "PROVIDER", "offerings": []}]}]}
    out = parsed(ds.build_collaboration_spec(cfg)["spec_yaml"])
    assert out["analysis_runners"]["CONSUMER"]["data_providers"]["PROVIDER"]["data_offerings"] == []


def test_every_collaborator_must_have_a_role():
    """Real API message, encountered during end-to-end validation:

    "The following collaborators are declared in collaborator_identifier_aliases
    but have no role (owner, analysis runner, or data provider): PARTNER"
    """
    cfg = {
        "name": "c", "owner": "PROVIDER",
        "collaborators": [
            {"alias": "PROVIDER", "account": "ORG.A"},
            {"alias": "PARTNER", "account": "ORG.B"},
        ],
        "analysis_runners": [{
            "alias": "PROVIDER",
            "data_providers": [{"alias": "PROVIDER", "offerings": ["o_v1_0"]}],
        }],
    }
    with pytest.raises(ds.SpecError, match="no role"):
        ds.build_collaboration_spec(cfg)


def test_placeholder_data_provider_satisfies_the_role_requirement():
    """An empty offering list is the documented way to include a partner early."""
    cfg = {
        "name": "c", "owner": "PROVIDER",
        "collaborators": [
            {"alias": "PROVIDER", "account": "ORG.A"},
            {"alias": "PARTNER", "account": "ORG.B"},
        ],
        "analysis_runners": [{
            "alias": "PROVIDER",
            "data_providers": [
                {"alias": "PROVIDER", "offerings": ["o_v1_0"]},
                {"alias": "PARTNER", "offerings": []},
            ],
        }],
    }
    providers = parsed(ds.build_collaboration_spec(cfg)["spec_yaml"]) \
        ["analysis_runners"]["PROVIDER"]["data_providers"]
    assert set(providers) == {"PROVIDER", "PARTNER"}
    assert providers["PARTNER"]["data_offerings"] == []


def test_owner_alone_counts_as_a_role():
    cfg = {
        "name": "c", "owner": "PROVIDER",
        "collaborators": [
            {"alias": "PROVIDER", "account": "ORG.A"},
            {"alias": "RUNNER", "account": "ORG.B"},
        ],
        "analysis_runners": [{
            "alias": "RUNNER",
            "data_providers": [{"alias": "PROVIDER", "offerings": ["o_v1_0"]}],
        }],
    }
    assert ds.build_collaboration_spec(cfg)["collaboration_name"] == "c"


# ---------------------------------------------------------------------------
# overlap analysis
# ---------------------------------------------------------------------------

OVERLAP_CFG = {
    "source_tables": ["PROVIDER.telco_provider_offering_v1_0.subscribers"],
    "my_tables": ["LOCAL.marketing_consumer_offering_v1_0.audience"],
    "match_levels": [[{"provider": "HASHED_PHONE_SHA256", "consumer": "HASHED_PHONE_SHA256"}]],
}

GOLDEN_OVERLAP = """
api_version: "2.0.0"
spec_type: "analysis"
name: "overlap_count"
template: "standard_audience_overlap_v0"
template_configuration:
  view_mappings:
    source_tables: ["PROVIDER.telco_provider_offering_v1_0.subscribers"]
  local_view_mappings:
    my_tables: ["LOCAL.marketing_consumer_offering_v1_0.audience"]
  arguments:
    join_clauses: ["p1.HASHED_PHONE_SHA256 = c1.HASHED_PHONE_SHA256"]
    count_column: ["HASHED_PHONE_SHA256"]
    my_group_by: []
    source_group_by: []
"""


def test_overlap_matches_golden():
    assert parsed(ds.build_overlap_spec(OVERLAP_CFG)["spec_yaml"]) == parsed(GOLDEN_OVERLAP)


def test_count_column_is_derived_and_unqualified():
    args = parsed(ds.build_overlap_spec(OVERLAP_CFG)["spec_yaml"]) \
        ["template_configuration"]["arguments"]
    assert args["count_column"] == ["HASHED_PHONE_SHA256"]


def test_rejects_alias_qualified_count_column():
    cfg = {**OVERLAP_CFG, "count_column": ["c1.HASHED_PHONE_SHA256"]}
    with pytest.raises(ds.SpecError, match="must not be alias-qualified"):
        ds.build_overlap_spec(cfg)


def test_view_mappings_are_plural_arrays():
    """Singular strings fail API validation."""
    tc = parsed(ds.build_overlap_spec(OVERLAP_CFG)["spec_yaml"])["template_configuration"]
    assert isinstance(tc["view_mappings"]["source_tables"], list)
    assert isinstance(tc["local_view_mappings"]["my_tables"], list)


def test_missing_local_table_explains_the_link_local_fix():
    with pytest.raises(ds.SpecError) as e:
        ds.build_overlap_spec({**OVERLAP_CFG, "my_tables": []})
    assert "LINK_LOCAL_DATA_OFFERING" in str(e.value)


def test_waterfall_builds_ordered_or_levels_with_anded_keys():
    levels = [
        [{"provider": "HASHED_EMAIL_SHA256", "consumer": "HASHED_EMAIL_SHA256"}],
        [{"provider": "HASHED_PHONE_SHA256", "consumer": "HASHED_PHONE_SHA256"},
         {"provider": "LAST_NAME", "consumer": "LAST_NAME"}],
    ]
    assert ds.build_join_clauses(levels) == [
        "p1.HASHED_EMAIL_SHA256 = c1.HASHED_EMAIL_SHA256",
        "p1.HASHED_PHONE_SHA256 = c1.HASHED_PHONE_SHA256 AND p1.LAST_NAME = c1.LAST_NAME",
    ]


def test_long_join_clause_is_never_line_wrapped():
    """A wrapped clause is a syntactically broken clause."""
    levels = [[{"provider": f"COL_{i}", "consumer": f"COL_{i}"} for i in range(30)]]
    out = ds.build_overlap_spec({**OVERLAP_CFG, "match_levels": levels})
    clause = parsed(out["spec_yaml"])["template_configuration"]["arguments"]["join_clauses"][0]
    assert clause == ds.build_join_clauses(levels)[0]
    assert "\n" not in clause


def test_group_by_and_filters_are_passed_through():
    cfg = {**OVERLAP_CFG, "my_group_by": ["c1.SEGMENT"], "source_group_by": ["p1.REGION"],
           "my_where_clause": "c1.SEGMENT = 'GOLD'", "source_where_clause": "p1.REGION = 'JKT'"}
    args = parsed(ds.build_overlap_spec(cfg)["spec_yaml"])["template_configuration"]["arguments"]
    assert args["my_group_by"] == ["c1.SEGMENT"]
    assert args["my_where_clause"] == "c1.SEGMENT = 'GOLD'"
    assert args["source_where_clause"] == "p1.REGION = 'JKT'"


def test_empty_match_levels_is_rejected():
    with pytest.raises(ds.SpecError, match="At least one match key"):
        ds.build_join_clauses([])


def test_cache_key_is_stable_and_config_sensitive():
    a = ds.build_overlap_spec(OVERLAP_CFG)["cache_key"]
    b = ds.build_overlap_spec(dict(OVERLAP_CFG))["cache_key"]
    c = ds.build_overlap_spec({**OVERLAP_CFG, "my_where_clause": "c1.X = 1"})["cache_key"]
    assert a == b and a != c


# ---------------------------------------------------------------------------
# activation
# ---------------------------------------------------------------------------

ACTIVATION_CFG = {
    **OVERLAP_CFG,
    "activation_columns": ["p1.ARPU_BAND", "p1.CHURN_RISK", "c1.SEGMENT"],
    "destination": "CONSUMER",
    "segment_name": "telco_overlap_all_attrs",
}


def test_activation_spec_shape():
    spec = parsed(ds.build_activation_spec(ACTIVATION_CFG)["spec_yaml"])
    assert spec["template"] == "standard_audience_overlap_activation_v0"
    tc = spec["template_configuration"]
    assert tc["arguments"]["activation_column"] == ["p1.ARPU_BAND", "p1.CHURN_RISK", "c1.SEGMENT"]
    assert tc["activation"] == {"snowflake_collaborator": "CONSUMER",
                                "segment_name": "telco_overlap_all_attrs"}


def test_activation_requires_alias_qualified_columns():
    with pytest.raises(ds.SpecError, match="alias-qualified"):
        ds.build_activation_spec({**ACTIVATION_CFG, "activation_columns": ["ARPU_BAND"]})


@pytest.mark.parametrize("bad", ["q3 high value", "seg!", "a b"])
def test_segment_name_rejects_spaces_and_punctuation(bad):
    with pytest.raises(ds.SpecError, match="letters, digits"):
        ds.build_activation_spec({**ACTIVATION_CFG, "segment_name": bad})


# ---------------------------------------------------------------------------
# flattening SEGMENT_RECORDS
# ---------------------------------------------------------------------------


def test_flatten_sql_dealiases_and_targets_the_share_db():
    sql = ds.build_flatten_sql(
        "telco_audience_overlap", "DCR_CONSUMER.DATA.ACTIVATION_RESULTS",
        ["p1.ARPU_BAND", "c1.SEGMENT"])
    assert 'RECORDS:ID:"p1.ARPU_BAND"::STRING AS ARPU_BAND' in sql
    assert 'RECORDS:ID:"c1.SEGMENT"::STRING AS SEGMENT' in sql
    assert "FROM SFDCR_TELCO_AUDIENCE_OVERLAP.ACTIVATION.SEGMENT_RECORDS" in sql
    assert "MATCH_CRITERIA" in sql


def test_flatten_sql_disambiguates_a_column_both_sides_expose():
    sql = ds.build_flatten_sql("c", "D.S.T", ["p1.PLAN_TYPE", "c1.PLAN_TYPE"])
    assert "AS PLAN_TYPE" in sql
    assert "AS C1_PLAN_TYPE" in sql


def test_flatten_sql_can_scope_to_one_batch():
    sql = ds.build_flatten_sql("c", "D.S.T", ["p1.A"], batch_id="abc-123")
    assert "WHERE BATCH_ID = 'abc-123'" in sql
