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

# Captured from the Streamlit console when registering an offering while the
# session still had secondary roles enabled.
REAL_SECONDARY_ROLES = (
    "(1304): 01c6fdc3-0001-a065-0000-04dd0dbc865e: 100357 (P0000): "
    "Python Interpreter Error:\n"
    "Traceback (most recent call last):\n"
    '  File "_udf_code.py", line 23, in main\n'
    "    raise e.with_traceback(None) from None\n"
    "navlib.app.collaboration.exceptions.SecondaryRolesNotSupported: "
    "Secondary roles must be disabled before calling this procedure. "
    "Run 'USE SECONDARY ROLES NONE' and try again.\n"
    " in function REGISTER_DATA_OFFERING with handler main"
)

# Captured from GET_STATUS DETAILS after the React app's service identity tried
# to JOIN on the consumer account.
REAL_USER_PROFILE_INCOMPLETE = (
    "**FAILURE**: Received error: snowflake.snowpark.exceptions.SnowparkSQLException: "
    "(1304): 01c6fe42-0001-a065-0000-31d5083915fe: 090655 (P0002): "
    "Please add your first/last name and email to your user profile in the Snowsight UI "
    "or use the SQL command ALTER USER <user name> to set first_name, last_name, and email."
)

# Captured when LEAVE was attempted to recover a failed install.
REAL_WRONG_STATUS = (
    "navlib.app.collaboration.exceptions.InvalidCollaborationStatusError: This action "
    "requires the collaboration status to be one of the following: LOCAL_DROP_PENDING, "
    "LEAVING. Current status: INSTALLATION_FAILED.\n"
    " in function LEAVE with handler main"
)

# Captured when an analysis runner tried LINK_DATA_OFFERING for itself, having
# mistaken it for LINK_LOCAL_DATA_OFFERING.
REAL_WRONG_LINK_SIDE = (
    "(1304): 01c6fe7f-0001-a065-0000-31d50839587a: 100357 (P0000): "
    "Python Interpreter Error:\n"
    "Traceback (most recent call last):\n"
    '  File "_udf_code.py", line 25, in main\n'
    "    raise e.with_traceback(None) from None\n"
    "navlib.app.collaboration.exceptions.ProviderNotServingAnalysisRunner: "
    "A data provider can link data offerings only for their analysis runners. "
    "Current account: CONSUMER; analysis runner: CONSUMER.\n"
    " in function LINK_DATA_OFFERING with handler main"
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


def test_secondary_roles_error_is_classified_with_the_exact_remedy():
    """This one reached a user as "Unrecognised", which is how it got a case.

    The remedy is a single statement, so the decoder must surface it as sql_fix
    rather than leaving the operator to read a Python traceback.
    """
    out = decode_error(REAL_SECONDARY_ROLES)
    assert out["code"] == "SECONDARY_ROLES_ACTIVE"
    assert out["sql_fix"] == "USE SECONDARY ROLES NONE;"
    assert out["retryable"] is True


def test_secondary_roles_remediation_says_why_the_facade_cannot_self_heal():
    """USE is rejected inside a stored procedure, so the fix is session-level.

    If this explanation is lost, the obvious "fix" is to add the statement to
    INVOKE, which cannot work.
    """
    out = decode_error(REAL_SECONDARY_ROLES)
    assert "stored procedure" in out["remediation"]


def test_incomplete_user_profile_is_classified_and_names_alter_user():
    out = decode_error(REAL_USER_PROFILE_INCOMPLETE)
    assert out["code"] == "USER_PROFILE_INCOMPLETE"
    assert "ALTER USER" in (out["sql_fix"] or "")


def test_incomplete_user_profile_says_to_join_outside_the_app():
    """The point that saves the next person hours.

    A service identity cannot be given a profile, so retrying in the app can
    never work. If the remediation loses this, the obvious next step is to hunt
    for a grant that does not exist.
    """
    out = decode_error(REAL_USER_PROFILE_INCOMPLETE)
    assert "worksheet" in out["remediation"]
    assert out["retryable"] is False


def test_failed_install_recovery_is_review_then_join_not_leave():
    """LEAVE is rejected from INSTALLATION_FAILED, which is counter-intuitive."""
    out = decode_error(REAL_WRONG_STATUS)
    assert out["code"] == "WRONG_COLLABORATION_STATUS"
    assert "INSTALLATION_FAILED" in out["title"]
    assert "REVIEW" in out["remediation"] and "JOIN" in out["remediation"]


def test_wrong_link_side_points_at_the_local_variant():
    """The whole value of this case is naming the operation they actually wanted.

    LINK_DATA_OFFERING and LINK_LOCAL_DATA_OFFERING are trivially confusable, and
    the raw DCR message never mentions the local variant.
    """
    out = decode_error(REAL_WRONG_LINK_SIDE)
    assert out["code"] == "NOT_A_DATA_PROVIDER_FOR_RUNNER"
    assert "LINK_LOCAL_DATA_OFFERING" in out["remediation"]


def test_wrong_link_side_notices_the_runner_is_the_caller():
    """CONSUMER sharing to CONSUMER deserves a plainer explanation than a
    generic 'not a provider for that runner'."""
    out = decode_error(REAL_WRONG_LINK_SIDE)
    assert "yourself" in out["cause"]


def test_every_decoded_error_has_the_full_contract():
    """The UI renders these keys unconditionally, so none may be missing."""
    required = {"code", "title", "cause", "remediation", "sql_fix", "retryable", "severity"}
    for raw in [REAL_REFERENCE_USAGE, REAL_RESTRICTED_SESSION, REAL_NESTED_JOIN,
                REAL_GRANT_NOT_EXECUTED, REAL_SECONDARY_ROLES,
                REAL_USER_PROFILE_INCOMPLETE, REAL_WRONG_STATUS,
                REAL_WRONG_LINK_SIDE, "novel error", ""]:
        assert required <= set(decode_error(raw))
