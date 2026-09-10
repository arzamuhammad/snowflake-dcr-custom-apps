"""
DCR Console — spec builders for Snowflake Data Clean Rooms Collaboration API v2.

This module is the ONLY place that produces DCR YAML. Both UI tracks (Streamlit
and React) call facade procedures, and those procedures call this module. That
gives one place to encode the rules that are easy to get wrong:

  * ``column_type`` is a PII-only whitelist. ``dimension`` / ``date`` / ``custom``
    are rejected by the API, so we reject them earlier with a better message.
  * ``category: join_standard`` RENAMES the column in the shared view to the
    ``column_type`` value. Join clauses must use the renamed alias, not the
    source column name. This is the single most common cause of
    "unauthorized column" failures, so the resolved name is computed here and
    handed to the UI.
  * Specs are emitted with PyYAML, never string concatenation. That structurally
    eliminates the "missing space after colon" and unquoted-scalar failures.
  * Specs are returned as strings to be passed as procedure ARGUMENTS. They are
    never assigned to a SQL session variable, which has a 256-byte cap that a
    real offering with 100+ columns blows through instantly.

Collaboration API v2 only. Nothing here references the deprecated v1 Native App
interface (``provider.*`` / ``consumer.*`` procedures, ``SAMOOHA_BY_SNOWFLAKE_APP_SHARE``).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

import yaml

API_VERSION = "2.0.0"

STANDARD_OVERLAP_TEMPLATE = "standard_audience_overlap_v0"
STANDARD_ACTIVATION_TEMPLATE = "standard_audience_overlap_activation_v0"

# ---------------------------------------------------------------------------
# Vocabulary accepted by the API. Anything outside these sets is rejected here
# with an actionable message instead of a schema-validation stack trace.
# ---------------------------------------------------------------------------

#: Valid ``column_type`` values for ``category: join_standard``. PII types only.
COLUMN_TYPES: frozenset[str] = frozenset(
    {
        "email", "hashed_email_sha256", "hashed_email_b64_encoded",
        "phone", "hashed_phone_sha256", "hashed_phone_b64_encoded",
        "device_id", "hashed_device_id_sha256", "hashed_device_b64_encoded",
        "ip_address", "hashed_ip_address_sha256", "hashed_ip_address_b64_encoded",
        "first_name", "hashed_first_name_sha256", "hashed_first_name_b64_encoded",
        "last_name", "hashed_last_name_sha256", "hashed_last_name_b64_encoded",
    }
)

#: Valid ``category`` values in ``schema_and_template_policies``.
CATEGORIES: frozenset[str] = frozenset(
    {"join_standard", "join_custom", "timestamp", "passthrough", "event_type"}
)

JOIN_CATEGORIES: frozenset[str] = frozenset({"join_standard", "join_custom"})

ALLOWED_ANALYSES: frozenset[str] = frozenset({"template_only", "template_and_freeform_sql"})
OBJECT_CLASSES: frozenset[str] = frozenset({"custom", "ads_log"})

APP_ROLES: tuple[str, ...] = ("VIEWER", "ANALYST", "ACTIVATOR", "BUILDER")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_FQN_RE = re.compile(r"^[A-Za-z_][\w$]*\.[A-Za-z_][\w$]*\.[A-Za-z_][\w$]*$")
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][\w-]*\.[A-Za-z0-9][\w-]*$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SpecError(ValueError):
    """Raised when a UI-supplied config cannot produce a valid DCR spec.

    Carries a ``field`` so the UI can highlight the offending input rather than
    showing a generic error banner.
    """

    def __init__(self, message: str, field: str | None = None, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.hint = hint

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.message, "field": self.field, "hint": self.hint}


# ---------------------------------------------------------------------------
# YAML emission
# ---------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    """Block-style dumper that keeps nested lists indented under their key."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):  # noqa: D102
        return super().increase_indent(flow, False)


def _dump(spec: dict[str, Any]) -> str:
    """Serialise a spec dict to YAML.

    ``sort_keys=False`` preserves our intentional key order so a human
    reviewing the raw spec in the UI reads it top-down the way the docs present
    it. ``api_version`` is forced to a quoted string because the API is strict
    about it being a string, not the float 2.0.
    """
    return yaml.dump(
        spec,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        width=10_000,          # never wrap: a wrapped join clause is a broken join clause
        allow_unicode=True,
    )


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------


def _require(cfg: dict[str, Any], key: str, field: str | None = None) -> Any:
    if key not in cfg or cfg[key] in (None, "", [], {}):
        raise SpecError(f"'{key}' is required.", field=field or key)
    return cfg[key]


def _check_identifier(value: str, field: str) -> str:
    if not _IDENT_RE.match(value):
        raise SpecError(
            f"'{value}' is not a valid identifier. Use letters, digits and underscores, "
            "starting with a letter or underscore.",
            field=field,
        )
    return value


def _check_account(value: str, field: str) -> str:
    """Validate an ORG.ACCOUNT data-sharing identifier.

    A very common mistake is pasting the Snowsight URL locator
    (``xy12345.ap-southeast-3.aws``) instead of ``ORG.ACCOUNT``. That produces a
    collaboration the partner never sees, with no error at create time — so we
    reject it up front.
    """
    if not _ACCOUNT_RE.match(value):
        raise SpecError(
            f"'{value}' is not an ORG.ACCOUNT identifier. Run "
            "SELECT CURRENT_ORGANIZATION_NAME()||'.'||CURRENT_ACCOUNT_NAME() in the "
            "partner account to get it. An account locator or URL will not work.",
            field=field,
        )
    return value


# ---------------------------------------------------------------------------
# Column policy resolution
# ---------------------------------------------------------------------------


def exposed_column_name(column: str, category: str, column_type: str | None) -> str:
    """Return the name a column has in the shared template view.

    ``join_standard`` is renamed to its ``column_type``; ``timestamp`` is renamed
    to ``TIMESTAMP``; everything else keeps its source name. The UI must show
    this so users build join clauses against the name that actually exists.
    """
    if category == "join_standard":
        return (column_type or "").upper()
    if category == "timestamp":
        return "TIMESTAMP"
    return column.upper()


def resolve_columns(columns: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a UI column list and annotate each entry with its exposed name.

    Each input item: ``{"name", "category", "column_type"?, "activation_allowed"?}``.
    Returns the same items plus ``exposed_name`` and ``is_join_key``.
    """
    resolved: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_types: dict[str, str] = {}

    for item in columns:
        name = str(_require(item, "name", field="columns.name")).upper()
        category = str(_require(item, "category", field=f"columns.{name}.category"))

        if name in seen_names:
            raise SpecError(f"Column '{name}' is listed twice.", field=f"columns.{name}")
        seen_names.add(name)

        if category not in CATEGORIES:
            raise SpecError(
                f"Column '{name}': category '{category}' is not valid. "
                f"Choose one of: {', '.join(sorted(CATEGORIES))}.",
                field=f"columns.{name}.category",
            )

        column_type = item.get("column_type")
        if category == "join_standard":
            if not column_type:
                raise SpecError(
                    f"Column '{name}' uses category 'join_standard', which requires a "
                    "column_type. If none of the PII types describe this column, use "
                    "category 'join_custom' instead.",
                    field=f"columns.{name}.column_type",
                )
            column_type = str(column_type).lower()
            if column_type not in COLUMN_TYPES:
                raise SpecError(
                    f"Column '{name}': column_type '{column_type}' is not accepted. "
                    "Valid values are PII types only "
                    f"({', '.join(sorted(COLUMN_TYPES))}). "
                    "For a non-PII join key use category 'join_custom'.",
                    field=f"columns.{name}.column_type",
                )
            if column_type in seen_types:
                raise SpecError(
                    f"column_type '{column_type}' is already used by column "
                    f"'{seen_types[column_type]}'. A dataset cannot assign the same "
                    "column_type twice.",
                    field=f"columns.{name}.column_type",
                )
            seen_types[column_type] = name
        elif column_type:
            raise SpecError(
                f"Column '{name}': column_type only applies to category "
                f"'join_standard', not '{category}'.",
                field=f"columns.{name}.column_type",
            )
            
        resolved.append(
            {
                "name": name,
                "category": category,
                "column_type": column_type,
                "activation_allowed": bool(item.get("activation_allowed", False)),
                "exposed_name": exposed_column_name(name, category, column_type),
                "is_join_key": category in JOIN_CATEGORIES,
            }
        )

    if not resolved:
        raise SpecError("At least one column must be configured.", field="columns")
    if not any(c["is_join_key"] for c in resolved):
        raise SpecError(
            "No join key configured. Audience overlap needs at least one column with "
            "category 'join_standard' or 'join_custom'.",
            field="columns",
        )
    return resolved


# ---------------------------------------------------------------------------
# 1. data_offering
# ---------------------------------------------------------------------------


def build_offering_spec(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build a ``data_offering`` spec.

    Config::

        {
          "name": "telco_provider_offering",
          "version": "v1_0",
          "description": "...",
          "datasets": [
            {
              "alias": "subscribers",
              "data_object_fqn": "DCR_PROVIDER.DATA.TELCO_SUBSCRIBERS",
              "allowed_analyses": "template_only",     # optional
              "object_class": "custom",                # optional
              "columns": [ {"name","category","column_type","activation_allowed"}, ... ]
            }
          ]
        }

    Returns ``{"offering_id", "spec_yaml", "datasets": [...resolved columns...]}``.
    """
    name = _check_identifier(str(_require(cfg, "name")), "name")
    version = str(_require(cfg, "version"))
    if len(name) > 75:
        raise SpecError("Offering name must be 75 characters or fewer.", field="name")
    if len(version) > 20:
        raise SpecError("Offering version must be 20 characters or fewer.", field="version")

    datasets_cfg = _require(cfg, "datasets")
    if not isinstance(datasets_cfg, list):
        raise SpecError("'datasets' must be a list.", field="datasets")

    datasets_yaml: list[dict[str, Any]] = []
    datasets_meta: list[dict[str, Any]] = []
    seen_aliases: set[str] = set()

    for ds in datasets_cfg:
        alias = _check_identifier(str(_require(ds, "alias", "datasets.alias")), "datasets.alias")
        if alias in seen_aliases:
            raise SpecError(f"Dataset alias '{alias}' is used twice.", field="datasets.alias")
        seen_aliases.add(alias)

        fqn = str(_require(ds, "data_object_fqn", "datasets.data_object_fqn"))
        if not _FQN_RE.match(fqn):
            raise SpecError(
                f"'{fqn}' is not a DATABASE.SCHEMA.OBJECT name.",
                field="datasets.data_object_fqn",
            )
        if len(fqn) > 773:
            raise SpecError("data_object_fqn exceeds 773 characters.", field="datasets.data_object_fqn")

        allowed = str(ds.get("allowed_analyses", "template_only"))
        if allowed not in ALLOWED_ANALYSES:
            raise SpecError(
                f"allowed_analyses must be one of {sorted(ALLOWED_ANALYSES)}.",
                field="datasets.allowed_analyses",
            )
        obj_class = str(ds.get("object_class", "custom"))
        if obj_class not in OBJECT_CLASSES:
            raise SpecError(
                f"object_class must be one of {sorted(OBJECT_CLASSES)}.",
                field="datasets.object_class",
            )

        columns = resolve_columns(_require(ds, "columns", "datasets.columns"))

        policies: dict[str, Any] = {}
        for col in columns:
            entry: dict[str, Any] = {"category": col["category"]}
            if col["column_type"]:
                entry["column_type"] = col["column_type"]
            entry["activation_allowed"] = col["activation_allowed"]
            policies[col["name"]] = entry

        datasets_yaml.append(
            {
                "alias": alias,
                "data_object_fqn": fqn,
                "allowed_analyses": allowed,
                "object_class": obj_class,
                "schema_and_template_policies": policies,
            }
        )
        datasets_meta.append({"alias": alias, "data_object_fqn": fqn, "columns": columns})

    spec: dict[str, Any] = {
        "api_version": API_VERSION,
        "spec_type": "data_offering",
        "name": name,
        "version": version,
    }
    if cfg.get("description"):
        spec["description"] = str(cfg["description"])
    spec["datasets"] = datasets_yaml

    return {
        "offering_id": f"{name}_{version}",
        "spec_yaml": _dump(spec),
        "datasets": datasets_meta,
    }


# ---------------------------------------------------------------------------
# 2. collaboration
# ---------------------------------------------------------------------------


def build_collaboration_spec(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build a ``collaboration`` spec.

    Config::

        {
          "name": "telco_audience_overlap",
          "description": "...",
          "owner": "PROVIDER",
          "collaborators": [
            {"alias": "PROVIDER", "account": "MYORG.PROVIDER_ACCOUNT"},
            {"alias": "CONSUMER", "account": "MYORG.CONSUMER_ACCOUNT"}
          ],
          "analysis_runners": [
            {
              "alias": "CONSUMER",
              "data_providers": [{"alias": "PROVIDER", "offerings": ["telco_provider_offering_v1_0"]}],
              "templates": ["standard_audience_overlap_v0", "standard_audience_overlap_activation_v0"],
              "activation_destinations": ["CONSUMER"]
            }
          ]
        }

    ``templates`` defaults to both standard audience-overlap templates, which is
    what makes the tutorial's separate "link a template" step unnecessary.
    """
    name = _check_identifier(str(_require(cfg, "name")), "name")

    collaborators = _require(cfg, "collaborators")
    aliases: dict[str, str] = {}
    for c in collaborators:
        alias = str(_require(c, "alias", "collaborators.alias")).upper()
        if len(alias) > 25:
            raise SpecError("Collaborator alias must be 25 characters or fewer.", field="collaborators.alias")
        _check_identifier(alias, "collaborators.alias")
        if alias in aliases:
            raise SpecError(f"Collaborator alias '{alias}' is used twice.", field="collaborators.alias")
        aliases[alias] = _check_account(
            str(_require(c, "account", "collaborators.account")), "collaborators.account"
        )

    if len(aliases) < 2:
        raise SpecError("A collaboration needs at least two collaborators.", field="collaborators")

    owner = str(_require(cfg, "owner")).upper()
    if owner not in aliases:
        raise SpecError(
            f"owner '{owner}' is not one of the collaborator aliases ({', '.join(aliases)}).",
            field="owner",
        )

    runners_cfg = _require(cfg, "analysis_runners")
    if not isinstance(runners_cfg, list) or not runners_cfg:
        raise SpecError(
            "At least one analysis runner is required, otherwise nobody can run an "
            "overlap. Note that a collaborator who is not listed here can NEVER run an "
            "analysis — add both sides now if both should be able to.",
            field="analysis_runners",
        )

    runners: dict[str, Any] = {}
    for r in runners_cfg:
        r_alias = str(_require(r, "alias", "analysis_runners.alias")).upper()
        if r_alias not in aliases:
            raise SpecError(
                f"Analysis runner '{r_alias}' is not a declared collaborator.",
                field="analysis_runners.alias",
            )
        if r_alias in runners:
            raise SpecError(f"Analysis runner '{r_alias}' is listed twice.", field="analysis_runners.alias")

        providers: dict[str, Any] = {}
        for p in r.get("data_providers") or []:
            p_alias = str(_require(p, "alias", "data_providers.alias")).upper()
            if p_alias not in aliases:
                raise SpecError(
                    f"Data provider '{p_alias}' is not a declared collaborator.",
                    field="data_providers.alias",
                )
            offerings = [str(o) for o in (p.get("offerings") or [])]
            # An empty list is a legitimate placeholder: offerings can be linked later.
            providers[p_alias] = {"data_offerings": [{"id": o} for o in offerings]}

        entry: dict[str, Any] = {"data_providers": providers}

        templates = r.get("templates") or [STANDARD_OVERLAP_TEMPLATE, STANDARD_ACTIVATION_TEMPLATE]
        entry["templates"] = [{"id": str(t)} for t in templates]

        destinations = [str(d).upper() for d in (r.get("activation_destinations") or [])]
        for d in destinations:
            if d not in aliases:
                raise SpecError(
                    f"Activation destination '{d}' is not a declared collaborator.",
                    field="activation_destinations",
                )
        if destinations:
            entry["activation_destinations"] = {"snowflake_collaborators": destinations}

        runners[r_alias] = entry

    # Every declared collaborator must hold a role. The API rejects a spec where
    # an alias appears in collaborator_identifier_aliases but is neither the
    # owner, an analysis runner, nor a data provider:
    #   SpecValidationError: The following collaborators are declared in
    #   collaborator_identifier_aliases but have no role ...
    # Catching it here names the fix instead of surfacing that message.
    with_roles = {owner} | set(runners)
    for entry in runners.values():
        with_roles |= set(entry["data_providers"])
    roleless = sorted(set(aliases) - with_roles)
    if roleless:
        raise SpecError(
            f"These collaborators have no role: {', '.join(roleless)}. Every collaborator "
            "must be the owner, an analysis runner, or a data provider. To include a "
            "partner who will contribute data later, add them as a data provider with an "
            "empty offering list as a placeholder.",
            field="collaborators",
        )

    spec: dict[str, Any] = {
        "api_version": API_VERSION,
        "spec_type": "collaboration",
        "name": name,
    }
    if cfg.get("description"):
        spec["description"] = str(cfg["description"])
    spec["collaborator_identifier_aliases"] = aliases
    spec["owner"] = owner
    spec["analysis_runners"] = runners

    return {"collaboration_name": name, "spec_yaml": _dump(spec)}


# ---------------------------------------------------------------------------
# 3. analysis — overlap and activation
# ---------------------------------------------------------------------------


def build_join_clauses(match_levels: list[list[dict[str, str]]]) -> list[str]:
    """Turn the UI's waterfall match builder into ``join_clauses``.

    ``match_levels`` is an ordered list of waterfall levels. Each level is a list
    of equalities that are ANDed together; the levels themselves are tried in
    order (the template ORs them as a waterfall, first match wins).

    Each equality is ``{"provider": "HASHED_PHONE_SHA256", "consumer": "HASHED_PHONE_SHA256"}``
    and must use the **exposed** column names, not the source names.
    """
    if not match_levels:
        raise SpecError("At least one match key is required.", field="match_levels")

    clauses: list[str] = []
    for i, level in enumerate(match_levels):
        if not level:
            raise SpecError(f"Match level {i + 1} is empty.", field="match_levels")
        parts = []
        for eq in level:
            p = _check_identifier(str(_require(eq, "provider", "match_levels.provider")).upper(), "match_levels.provider")
            c = _check_identifier(str(_require(eq, "consumer", "match_levels.consumer")).upper(), "match_levels.consumer")
            parts.append(f"p1.{p} = c1.{c}")
        clauses.append(" AND ".join(parts))
    return clauses


def _view_mappings(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract and sanity-check the source/local view mappings.

    Both keys are PLURAL ARRAYS in the spec even though the template documents
    the parameters as ``source_table`` / ``my_table`` singular. Passing a bare
    string fails validation, and passing an empty ``my_tables`` when a local
    offering exists silently makes the template fall back to ``p2`` aliases,
    which then breaks every ``c1.`` reference.
    """
    source_tables = [str(t) for t in (cfg.get("source_tables") or [])]
    my_tables = [str(t) for t in (cfg.get("my_tables") or [])]
    if not source_tables:
        raise SpecError(
            "No partner dataset selected. Pick the partner's TEMPLATE_VIEW_NAME.",
            field="source_tables",
        )
    if not my_tables:
        raise SpecError(
            "No dataset of your own selected. You must link your own table with "
            "LINK_LOCAL_DATA_OFFERING before an overlap is possible — the app's "
            "Link Data screen does this.",
            field="my_tables",
            hint="LINK_LOCAL_DATA_OFFERING",
        )
    return source_tables, my_tables


def build_overlap_spec(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build an ``analysis`` spec for ``standard_audience_overlap_v0``.

    Config::

        {
          "name": "overlap_count",                       # optional
          "source_tables": ["PROVIDER.off_v1_0.subscribers"],
          "my_tables":     ["LOCAL.off_v1_0.audience"],
          "match_levels":  [[{"provider": "HASHED_PHONE_SHA256", "consumer": "HASHED_PHONE_SHA256"}]],
          "count_column":  ["HASHED_PHONE_SHA256"],      # optional, derived from level 1
          "my_where_clause": "...",                      # optional
          "source_where_clause": "...",                  # optional
          "my_group_by": ["c1.SEGMENT"],                 # optional
          "source_group_by": ["p1.REGION"]               # optional
        }
    """
    source_tables, my_tables = _view_mappings(cfg)
    join_clauses = build_join_clauses(_require(cfg, "match_levels"))

    # count_column identifies a record for distinct counting and is resolved
    # against the consumer (c1) side by the template, so it carries NO alias
    # prefix. Default to the first key of the first waterfall level.
    count_column = [str(c).upper() for c in (cfg.get("count_column") or [])]
    if not count_column:
        first = _require(cfg, "match_levels")[0][0]
        count_column = [str(first["consumer"]).upper()]
    for c in count_column:
        if "." in c:
            raise SpecError(
                f"count_column '{c}' must not be alias-qualified. Use the bare exposed "
                "column name, e.g. HASHED_PHONE_SHA256.",
                field="count_column",
            )

    arguments: dict[str, Any] = {
        "join_clauses": join_clauses,
        "count_column": count_column,
        "my_group_by": [str(g) for g in (cfg.get("my_group_by") or [])],
        "source_group_by": [str(g) for g in (cfg.get("source_group_by") or [])],
    }
    if cfg.get("my_where_clause"):
        arguments["my_where_clause"] = str(cfg["my_where_clause"])
    if cfg.get("source_where_clause"):
        arguments["source_where_clause"] = str(cfg["source_where_clause"])

    spec = {
        "api_version": API_VERSION,
        "spec_type": "analysis",
        "name": str(cfg.get("name") or "overlap_count"),
        "template": STANDARD_OVERLAP_TEMPLATE,
        "template_configuration": {
            "view_mappings": {"source_tables": source_tables},
            "local_view_mappings": {"my_tables": my_tables},
            "arguments": arguments,
        },
    }
    return {"spec_yaml": _dump(spec), "join_clauses": join_clauses, "cache_key": cache_key(spec)}


def build_activation_spec(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build an ``analysis`` spec for ``standard_audience_overlap_activation_v0``.

    Config adds to the overlap config::

        {
          "activation_columns": ["p1.ARPU_BAND", "c1.SEGMENT"],
          "where_clause": "...",                # optional
          "destination": "CONSUMER",
          "segment_name": "q3_high_value_overlap"
        }

    ``activation_columns`` MUST be alias-qualified (``p1.``/``c1.``) and every
    column must be one the data owner marked ``activation_allowed: true``. The
    caller is expected to have filtered the picker against
    ``ACTIVATION_ALLOWED_COLUMNS``; we re-check the shape here.
    """
    source_tables, my_tables = _view_mappings(cfg)
    join_clauses = build_join_clauses(_require(cfg, "match_levels"))

    activation_columns = [str(c) for c in _require(cfg, "activation_columns")]
    for col in activation_columns:
        if not re.match(r"^(p\d+|c\d+)\.[A-Za-z_][\w$]*$", col):
            raise SpecError(
                f"activation column '{col}' must be alias-qualified, e.g. 'p1.ARPU_BAND' "
                "for partner data or 'c1.SEGMENT' for your own.",
                field="activation_columns",
            )

    segment_name = str(_require(cfg, "segment_name"))
    if not _SEGMENT_RE.match(segment_name):
        raise SpecError(
            "Segment name may only contain letters, digits, underscores and hyphens. "
            "Spaces are rejected by the API.",
            field="segment_name",
        )

    destination = str(_require(cfg, "destination")).upper()

    arguments: dict[str, Any] = {
        "join_clauses": join_clauses,
        "activation_column": activation_columns,
    }
    if cfg.get("where_clause"):
        arguments["where_clause"] = str(cfg["where_clause"])

    spec = {
        "api_version": API_VERSION,
        "spec_type": "analysis",
        "name": str(cfg.get("name") or f"activate_{segment_name}"),
        "template": STANDARD_ACTIVATION_TEMPLATE,
        "template_configuration": {
            "view_mappings": {"source_tables": source_tables},
            "local_view_mappings": {"my_tables": my_tables},
            "arguments": arguments,
            "activation": {
                "snowflake_collaborator": destination,
                "segment_name": segment_name,
            },
        },
    }
    return {
        "spec_yaml": _dump(spec),
        "segment_name": segment_name,
        "destination": destination,
        "activation_columns": activation_columns,
    }


# ---------------------------------------------------------------------------
# 4. Flattening the activated segment
# ---------------------------------------------------------------------------


def build_flatten_sql(
    collaboration: str,
    target_fqn: str,
    activation_columns: list[str],
    batch_id: str | None = None,
) -> str:
    """Generate the SQL that turns ``SEGMENT_RECORDS`` into a usable table.

    The activation output is a VARIANT ``RECORDS`` column shaped as
    ``{"ID": {"p1.ARPU_BAND": "...", "c1.SEGMENT": "...", "join_clause": "..."}}``.
    Marketers cannot use that, so the Activation Inbox materialises a flat,
    typed table. Column names are de-aliased: ``p1.ARPU_BAND`` becomes ``ARPU_BAND``.
    """
    if not _FQN_RE.match(target_fqn):
        raise SpecError(f"'{target_fqn}' is not a DATABASE.SCHEMA.TABLE name.", field="target_fqn")

    share_db = f"SFDCR_{collaboration.upper()}"
    selects: list[str] = []
    used: set[str] = set()

    for col in activation_columns:
        alias = col.split(".", 1)[1].upper()
        # Two collaborators can both expose e.g. PLAN_TYPE; keep the side prefix
        # in that case so the output has no duplicate column names.
        if alias in used:
            alias = col.replace(".", "_").upper()
        used.add(alias)
        selects.append(f'    RECORDS:ID:"{col}"::STRING AS {alias}')

    selects.append('    RECORDS:ID:"join_clause"::STRING AS MATCH_CRITERIA')
    selects.append("    BATCH_ID")
    selects.append("    SEGMENT_NAME")
    selects.append("    UPDATED_ON")

    where = f"\nWHERE BATCH_ID = '{batch_id}'" if batch_id else ""
    body = ",\n".join(selects)
    return (
        f"CREATE OR REPLACE TABLE {target_fqn} AS\nSELECT\n{body}\n"
        f"FROM {share_db}.ACTIVATION.SEGMENT_RECORDS{where}"
    )


# ---------------------------------------------------------------------------
# 5. Cache key
# ---------------------------------------------------------------------------


def cache_key(spec: dict[str, Any]) -> str:
    """Stable hash of a spec, used to look up a previous identical overlap run."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
