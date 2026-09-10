"""
Tests for dcr_errors.decode_error.

The fixtures below are REAL error strings captured from
MYORG.PROVIDER_ACCOUNT on DCR 17.5, not invented examples. That matters: DCR
wraps its exceptions in a Python traceback, and a decoder written against
imagined text will not match production output.

Run:  .venv/bin/python -m pytest test_dcr_errors.py -q
"""

from __future__ import annotations

import pytest

from dcr_errors import decode_error

# Captured from CALL DCR_CONSOLE.APP._SPIKE_WRITE(...) before the
# REFERENCE_USAGE grant was applied.
REAL_REFERENCE_USAGE = (
    "(1304): 01c6ee3b-0001-9ffb-0000-04dd0da17cee: 100357 (P0000): Python Interpreter Error:\n"
    "Traceback (most recent call last):\n"
    '  File "_udf_code.py", line 23, in main\n'
    "    raise e.with_traceback(None) from None\n"
    "navlib.app.collaboration.exceptions.DatasetReferenceUsageWithGrantOptionMissingError: "
    "The current role '\"ACCOUNTADMIN\"' does not have REFERENCE_USAGE WITH GRANT OPTION on "
    "database 'dcr_provider'. To proceed, switch to a role with sufficient privileges (such as "
    "the database owner or ACCOUNTADMIN) and either register the database by calling "
    "register_db('dcr_provider') or run: GRANT REFERENCE_USAGE ON DATABASE dcr_provider TO ROLE "
    '"ACCOUNTADMIN" WITH GRANT OPTION;\n in function REGISTER_DATA_OFFERING with handler main'
)

# Captured from a restricted programmatic-access-token session.
REAL_RESTRICTED_SESSION = (
    "003107 (42501): 01c6ee36-0001-9fd5-0000-04dd0da1f82a: SQL execution error: "
    "Current session is restricted. USE ROLE not allowed."
)

# Captured when calling COLLABORATION.JOIN from inside a stored procedure.
REAL_NESTED_JOIN = (
    "Exception: **FAILURE**: Received error, observed: 090237 (42601): SQL compilation error:\n"
    "Query called from a stored procedure contains a function with side effects "
    "[SYSTEM$ACCEPT_LEGAL_TERMS]."
)

# Captured when LINK_LOCAL_DATA_OFFERING lacked WITH GRANT OPTION.
REAL_GRANT_NOT_EXECUTED = (
    "Exception: **FAILURE**: Received error, observed: 003102 (42501): "
    "Grant not executed: Insufficient privileges.\n"
    " in function LINK_LOCAL_DATA_OFFERING with handler main"
)


def test_real_reference_usage_error_is_decoded():
    out = decode_error(REAL_REFERENCE_USAGE)
    assert out["code"] == "REFERENCE_USAGE_MISSING"
    assert out["retryable"] is True
    assert out["severity"] == "blocked"


def test_real_reference_usage_error_yields_an_applicable_grant():
    """The sql_fix must be built from the identifiers DCR named, not guessed."""
    fix = decode_error(REAL_REFERENCE_USAGE)["sql_fix"]
    assert fix == (
        'GRANT REFERENCE_USAGE ON DATABASE dcr_provider TO ROLE "ACCOUNTADMIN" '
        "WITH GRANT OPTION;"
    )


def test_reference_usage_remediation_warns_against_the_v1_share():
    """SAMOOHA_BY_SNOWFLAKE_APP_SHARE belongs to the deprecated v1 interface."""
    out = decode_error(REAL_REFERENCE_USAGE)
    assert "Do NOT grant to SAMOOHA_BY_SNOWFLAKE_APP_SHARE" in out["remediation"]
    assert "SAMOOHA_BY_SNOWFLAKE_APP_SHARE" not in (out["sql_fix"] or "")


def test_reference_usage_never_recommends_the_v1_register_db_helper():
    """DCR's own message suggests register_db(), which is a v1 PROVIDER/CONSUMER proc."""
    out = decode_error(REAL_REFERENCE_USAGE)
    assert "register_db" not in (out["sql_fix"] or "")
    assert "register_db" not in out["remediation"]


def test_reference_usage_to_share_variant_targets_the_sco_share():
    raw = (
        "ReferenceUsageGrantMissingException: Reference usage grants are required for "
        "databases: ['DCR_PROVIDER']. Run: GRANT REFERENCE_USAGE ON DATABASE DCR_PROVIDER "
        "TO SHARE SCO_DATA_OFFERINGS_ABC123;"
    )
    out = decode_error(raw)
    assert out["code"] == "REFERENCE_USAGE_MISSING"
    assert out["sql_fix"] == (
        "GRANT REFERENCE_USAGE ON DATABASE DCR_PROVIDER TO SHARE SCO_DATA_OFFERINGS_ABC123;"
    )


def test_real_restricted_session_is_decoded_as_harmless():
    out = decode_error(REAL_RESTRICTED_SESSION)
    assert out["code"] == "SESSION_ROLE_RESTRICTED"
    assert out["severity"] == "warning"
    assert "DCR_CONSOLE_ROLE" in out["remediation"]


def test_invitation_not_found_explains_the_local_drop_pending_trap():
    raw = ("navlib.app.collaboration.exceptions.CollaborationInvitationNotFound: Pending "
           "invitation for collaboration: telco_audience_overlap not found")
    out = decode_error(raw)
    assert out["code"] == "INVITATION_NOT_FOUND"
    assert "LOCAL_DROP_PENDING" in out["cause"]
    assert out["retryable"] is True


def test_missing_standard_templates_offers_the_registration_call():
    raw = "SpecValidationError: Templates 'standard_audience_overlap_v0' do not exist"
    out = decode_error(raw)
    assert out["code"] == "STANDARD_TEMPLATES_MISSING"
    assert "REGISTER_STANDARD_DCR_TEMPLATES" in out["sql_fix"]


def test_privacy_threshold_is_a_warning_not_a_failure():
    raw = "Result below privacy threshold: fewer than 5 distinct matches"
    out = decode_error(raw)
    assert out["code"] == "BELOW_PRIVACY_THRESHOLD"
    assert out["severity"] == "warning"
    assert out["retryable"] is False


def test_unauthorized_column_points_at_the_rename():
    raw = "AnalysisError: Unauthorized columns: p1.HASHED_MSISDN"
    out = decode_error(raw)
    assert out["code"] == "UNAUTHORIZED_COLUMN"
    assert "HASHED_PHONE_SHA256" in out["cause"]
    assert "p1.HASHED_MSISDN" in out["title"]


def test_teardown_before_join():
    assert decode_error("You must join it before you can tear it down")["code"] == \
        "TEARDOWN_BEFORE_JOIN"


def test_already_exists_suggests_a_version_bump():
    out = decode_error("CodeSpecAlreadyExistsException: spec exists")
    assert out["code"] == "ALREADY_EXISTS"
    assert "version" in out["remediation"]


def test_cross_region_not_fulfilled():
    raw = "Listing 'SFDCR: SCO abc' is not fulfilled to your current region"
    out = decode_error(raw)
    assert out["code"] == "CROSS_REGION_NOT_FULFILLED"
    assert "Cross-Cloud Auto-Fulfillment" in out["remediation"]


def test_spec_validation_is_treated_as_a_console_bug():
    """The console generates YAML with a serialiser, so this should be impossible."""
    out = decode_error("SpecValidationError: Invalid YAML format: mapping values are not allowed here")
    assert out["code"] == "SPEC_VALIDATION"
    assert "console" in out["remediation"].lower()


@pytest.mark.parametrize("raw", ["", None])
def test_empty_input_is_safe(raw):
    assert decode_error(raw)["code"] == "UNKNOWN"


def test_unknown_error_preserves_the_last_traceback_line():
    raw = "Traceback (most recent call last):\n  File 'x'\nSomeNovelError: the actual problem"
    out = decode_error(raw)
    assert out["code"] == "UNKNOWN"
    assert "SomeNovelError: the actual problem" in out["cause"]


def test_nested_join_error_is_at_least_reported_verbatim():
    """Not specially classified, but the operator must still see the real cause.

    JOIN is never routed through the facade precisely because of this error, so a
    dedicated code would be dead weight — but the message must survive.
    """
    out = decode_error(REAL_NESTED_JOIN)
    assert "SYSTEM$ACCEPT_LEGAL_TERMS" in out["cause"] or out["code"] != "UNKNOWN"


def test_grant_not_executed_survives_decoding():
    out = decode_error(REAL_GRANT_NOT_EXECUTED)
    assert "Grant not executed" in out["cause"] or out["code"] != "UNKNOWN"


def test_every_decoded_error_has_the_full_contract():
    """The UI renders these keys unconditionally, so none may be missing."""
    required = {"code", "title", "cause", "remediation", "sql_fix", "retryable", "severity"}
    for raw in [REAL_REFERENCE_USAGE, REAL_RESTRICTED_SESSION, REAL_NESTED_JOIN,
                REAL_GRANT_NOT_EXECUTED, "novel error", ""]:
        assert required <= set(decode_error(raw))
