# Snowflake DCR Custom Apps

Two working user interfaces for **Snowflake Data Clean Rooms (Collaboration API v2)** —
one in Streamlit in Snowflake, one in React on Snowflake App Runtime (SPCS).

Both drive the same backend and produce identical results. They exist so you can
pick the one that fits your account and your team, and so you can see the
trade-offs measured rather than guessed.

> **This repository uses Collaboration API v2 exclusively.** It does not call any
> legacy DCR v1 object (`PROVIDER.*` / `CONSUMER.*` procedures,
> `SAMOOHA_BY_SNOWFLAKE_APP_SHARE`, `register_db()`). The legacy DCR web app is
> being deprecated; nothing here depends on it.

---

## What these apps do

An audience overlap and activation workflow for business users who do not write SQL:

1. See which of your datasets are registered and shareable
2. Create a collaboration and invite a partner account
3. Accept an invitation and join
4. Link an analysis template and link data — both the partner's offering and your own
5. Run an audience overlap with waterfall (multi-level) identity matching
6. Activate the matched audience into a table in your own account
7. Review history and an audit trail of every operation

---

## Repository layout

```
00_facade/            Backend: one dispatcher, 30 whitelisted operations
  dcr_specs.py          The only place DCR YAML is generated
  dcr_facade.py         Setup and lifecycle operations
  dcr_runs.py           Analysis and activation execution
  dcr_errors.py         Turns raw DCR errors into cause + remediation + sql_fix
  test_dcr_specs.py     62 unit tests against golden fixtures from real runs
  test_dcr_errors.py
  00_setup_role_and_db.sql
  01_meta_tables.sql
  03_facade_procs.sql   CREATE PROCEDURE DCR_CONSOLE.APP.INVOKE(...)

track_a_streamlit/    Streamlit in Snowflake  (14 files, ~640 lines)
track_b_react/        Next.js 14 on App Runtime / SPCS  (24 files, ~2,600 lines)

91_grants/            Grants for source data and for business users
docs/
  dcr-apps-tutorial.md  Full build tutorial (Bahasa Indonesia)
  COMPARISON.md         Track A vs Track B, measured from building both
```

---

## Architecture: why there is a façade

Both UIs call exactly one database object:

```sql
DCR_CONSOLE.APP.INVOKE(operation VARCHAR, payload VARIANT) RETURNS VARIANT
```

It runs with **owner's rights**, so DCR privileges live on the app's role and
never on your business users. They get `USAGE` on one procedure — nothing else.
`SAMOOHA_APP_ROLE` is never granted to an end user.

Everything correctness-critical lives behind that boundary: YAML generation, the
`column_type` whitelist, the join-column rename rule, error decoding, preflight
checks, and activation column enforcement. Building the second UI required no DCR
logic at all — which was the point.

```
Streamlit  ─┐
            ├─→  DCR_CONSOLE.APP.INVOKE  ─→  SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.*
React      ─┘         (owner's rights)          REGISTRY / COLLABORATION
                                                 ADMIN / LIBRARY
```

**One deliberate exception.** `COLLABORATION.JOIN` calls
`SYSTEM$ACCEPT_LEGAL_TERMS`, which cannot run inside a stored procedure. Joining
must happen at session level. Streamlit gets this for free; the React app has a
separate `/api/direct` route that bypasses the façade for this single operation.
Do not "fix" it by routing it through `INVOKE` — joining will break.

---

## Quick start

### Prerequisites

- Snowflake account with Data Clean Rooms installed and the standard templates
  registered (`standard_audience_overlap_v0`,
  `standard_audience_overlap_activation_v0`)
- `ACCOUNTADMIN` for the one-time setup
- Snowflake CLI (`snow`) with a configured connection
- Track B only: `FEATURE_SNOWFLAKE_APPS` enabled, App Runtime set up, and
  `BIND SERVICE ENDPOINT`

### 1. Deploy the façade

```bash
snow sql -f 00_facade/00_setup_role_and_db.sql -c <your-connection>
snow sql -f 00_facade/01_meta_tables.sql       -c <your-connection>

snow stage copy 00_facade/dcr_specs.py  @DCR_CONSOLE.APP.LIB/ -c <your-connection>
snow stage copy 00_facade/dcr_facade.py @DCR_CONSOLE.APP.LIB/ -c <your-connection>
snow stage copy 00_facade/dcr_runs.py   @DCR_CONSOLE.APP.LIB/ -c <your-connection>
snow stage copy 00_facade/dcr_errors.py @DCR_CONSOLE.APP.LIB/ -c <your-connection>

snow sql -f 00_facade/03_facade_procs.sql -c <your-connection>
```

Verify:

```sql
SELECT DCR_CONSOLE.APP.INVOKE('HEALTH_CHECK', {}::VARIANT);
```

### 2. Grant access to your source data

DCR needs `REFERENCE_USAGE ... WITH GRANT OPTION` on the database holding the
data you intend to share. Edit and run:

```bash
snow sql -f 91_grants/grants_source_data.sql -c <your-connection>
```

### 3. Deploy a UI

**Track A — Streamlit in Snowflake:**

```bash
cd track_a_streamlit && bash deploy_streamlit.sh
```

Open Snowsight → Streamlit → `DCR_OVERLAP_CONSOLE`. About 25 seconds.

**Track B — React on SPCS:**

```bash
cd track_b_react && npm install && bash deploy.sh
```

First deploy is about 4 minutes; roughly 2 of those are endpoint provisioning
alone. Worth knowing before a live demo.

### 4. Grant your business users

```bash
snow sql -f 91_grants/grants_business_users.sql -c <your-connection>
```

---

## Which track should you use?

`docs/COMPARISON.md` has the measured detail. The short version:

| | Track A (Streamlit) | Track B (React) |
|---|---|---|
| Time to working software | Much faster | Slower |
| Account prerequisites | None beyond DCR | App Runtime + feature flag |
| Long-running analysis UX | Blocks the page | Async, non-blocking |
| Multi-step wizards | Fights the rerun model | Ordinary derived state |
| Contract safety | Runtime errors | Compile errors |
| Maintainable by | Data team (Python/SQL) | Needs TypeScript/React |
| Debuggability | Stack trace in app | `snow app events` |

**Use Track A** for internal enablement, demos, POCs, and as your fallback when
App Runtime is not available in the target account.

**Use Track B** when you are replacing the legacy DCR web app for business users
and the wizards, non-blocking analysis, and visual fidelity matter.

The expensive part — the façade — is shared, so neither is wasted work.

---

## Running the tests

```bash
python3 -m venv .venv && .venv/bin/pip install pyyaml pytest
cd 00_facade && ../.venv/bin/python -m pytest -q
```

62 tests. Golden fixtures are real specs and real error strings captured from
live runs. They verify YAML generation and error decoding; they do not call DCR.

---

## Validation status

Exercised end to end on two accounts in the same region:

- 10M-row provider dataset × 1M-row consumer dataset, matched on hashed email
- Overlap: **249,778 (24.98%)** — matching a plain-SQL ground-truth query exactly
- Activation: 249,778 rows imported into the consumer's own table

**Known gaps**, recorded rather than glossed over:

- Track B has not been click-tested in a browser (it sits behind Snowflake OAuth)
- Track B's activation destination list is hardcoded rather than read from the
  collaboration spec
- Cross-region and Cross-Cloud Auto-Fulfillment are untested — both accounts were
  same-region

---

## Traps worth knowing

Learned the hard way while building this; all six are handled in the code.

| Trap | Consequence |
|---|---|
| Joining requires an identifiable *person* | `JOIN` accepts legal terms, so DCR demands `first_name`, `last_name` and `email` on the acting user. An SPCS service identity is not a user object and cannot have them; a business user has them but deliberately lacks `SAMOOHA_APP_ROLE`. **No app can join** — it is a one-time admin act in a worksheet |
| Owner auto-join does not work | The DCR auto-join task runs `JOIN` inside a procedure, so it dies on `SYSTEM$ACCEPT_LEGAL_TERMS` and leaves the collaboration at `INSTALLATION_FAILED` |
| `LEAVE` is rejected from `INSTALLATION_FAILED` | Recover with `REVIEW` again, then `JOIN`. `LEAVE` only works from `LOCAL_DROP_PENDING` / `LEAVING` |
| Secondary roles are enabled on the session | DCR refuses to register or link data. `USE SECONDARY ROLES NONE` fixes it — but `USE` is barred inside a procedure, so it must be set on the session. Both UIs do this at startup |
| `COLLABORATION.JOIN` is side-effecting | Cannot run in a stored procedure; must be session level |
| Auto-join can fail **silently** | Status stays `CREATED` with `auto_join.phase = failed` in `DETAILS` |
| `SHARED_WITH` is the local/partner discriminator | View-name prefix is *not* reliable — in a single-account test both get `PROVIDER.` |
| Every collaborator needs a role | `CREATE_COLLABORATION` fails with "collaborators … have no role" |
| `ADMIN.CHECK_PRIVILEGES` issues a `USE` statement | Also cannot run in a stored procedure |
| `REFERENCE_USAGE` needs `WITH GRANT OPTION` | DCR's own error message suggests `register_db()`, which is v1 — do not use it |

Also: DCR renames `join_standard` columns to their `column_type`. A column called
`HASHED_MSISDN` becomes `HASHED_PHONE_SHA256` inside the clean room. Write your
join clauses against the exposed name, not the source name.

---

## Related

- **SQL and notebook tutorial:** [dcr-collaboration-api-tutorial](https://github.com/arzamuhammad/dcr-collaboration-api-tutorial)
  — the same workflow without any app, plus the Snowsight DCR UI and the
  Audience Overlap & Activation app
- [Snowflake Data Clean Rooms documentation](https://docs.snowflake.com/en/user-guide/cleanrooms/about)

---

## License

Sample code provided for reference and enablement. Not an officially supported
Snowflake product. Review and test before any production use.
