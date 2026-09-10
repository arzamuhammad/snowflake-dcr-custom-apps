# Track A vs Track B — comparison from building both

Both tracks were built, deployed, and drive the identical façade
(`DCR_CONSOLE.APP.INVOKE`, 30 operations). This document records what actually
differed in practice, not what the docs predicted.

| | Track A | Track B |
|---|---|---|
| Runtime | Streamlit in Snowflake | React (Next.js 14) on Snowflake App Runtime → SPCS |
| Object | `DCR_CONSOLE.UI.DCR_OVERLAP_CONSOLE` | `SNOWFLAKE_APPS.PUBLIC.DCR_OVERLAP_CONSOLE_WEB` |
| URL | Snowsight → Streamlit | `https://<hash>-<org>-<account>.snowflakecomputing.app` |
| Status | Deployed | Deployed, service RUNNING |

---

## 1. Measured facts

| Metric | Track A | Track B |
|---|---|---|
| Files written | 14 | 24 |
| Lines of app code (excl. façade) | ~640 | ~2,600 |
| Deploy command | `bash deploy_streamlit.sh` | `bash deploy.sh` |
| Deploy duration (first) | ~25 s | ~4 min (image build + endpoint provisioning) |
| Deploy duration (redeploy) | ~20 s | ~2–3 min |
| Build step | none | `tsc --noEmit` + `next build` |
| Bundle | n/a | 87 kB shared + 1–104 kB per route |
| Account prerequisites | none beyond DCR | `FEATURE_SNOWFLAKE_APPS`, App Runtime setup, `BIND SERVICE ENDPOINT` |
| Idle cost | warehouse only | warehouse + managed compute pool for the service |

Endpoint provisioning on the first Track B deploy took **~2 minutes on its own**,
polling `Endpoints provisioning in progress` 18 times. Worth setting expectations
before a live demo.

---

## 2. Where Track B is genuinely better

**Long-running RUN.** This is the decisive difference, not cosmetics.
`COLLABORATION.RUN` blocks for 25–40 s in testing, and much longer on real data.
In Track B this is an `async` handler with a live elapsed counter and a spinner
that never blocks interaction. In Track A the script re-runs top-to-bottom on
every widget interaction, so a blocking call freezes the page and any partially
filled wizard state has to be defended with `st.session_state`.

**Multi-step wizards.** Create Collaboration has variable-length collaborator and
runner lists that cross-reference each other (owner must be one of the aliases;
roleless collaborators need placeholder roles). In React this is ordinary derived
state. In Streamlit every widget needs a stable `key`, and adding a row re-runs
the whole page.

**Enforcing the field-level contract.** `lib/types.ts` mirrors the façade
envelope, so a change to the contract surfaces as a compile error. Track A finds
the same mistake at runtime, in front of the user.

**Charts.** Recharts donut + per-level bar chart matched the target design
directly. Streamlit's chart primitives are adequate but the layout control is not
comparable.

---

## 3. Where Track A is genuinely better

**Time to working software.** Track A was complete and deployed before Track B's
first `npm install` finished. For an internal enablement session or a POC, that
ratio is hard to argue with.

**No account prerequisites.** Track A needs nothing beyond DCR itself. Track B
needs `FEATURE_SNOWFLAKE_APPS` enabled, a one-time App Runtime admin setup, and
`BIND SERVICE ENDPOINT`. In an account without those, Track B cannot be deployed
at all — and enabling them is not always a same-day request.

**Maintainability by the likely owner.** Track A is Python and SQL, which the
data team already owns. Track B needs someone comfortable with TypeScript, React
Server/Client component boundaries, and a build pipeline.

**Debuggability.** A Track A stack trace appears in the app. Track B failures
require `snow app events --last 100`, and a container that fails to start gives no
in-app signal at all.

---

## 4. Things that surprised us

**The session-level JOIN constraint costs Track B more.** `COLLABORATION.JOIN`
cannot run inside a stored procedure (`SYSTEM$ACCEPT_LEGAL_TERMS` is
side-effecting). Track A gets this for free — Streamlit statements already run at
session level. Track B needed a **separate API route** (`/api/direct`) that
deliberately bypasses the façade, plus a comment explaining why, or a future
maintainer would "fix" it by routing it through `INVOKE` and break joining.

**`@types/snowflake-sdk` made `account` required.** The copied plumbing failed
`tsc` on a field that is genuinely optional inside SPCS (it comes from the
environment). One-line fix, but it is the kind of friction Track A does not have.

**Recharts is 104 kB on the analyze route** versus 1–5 kB elsewhere. Fine here,
but it is the single largest thing in the bundle.

**Owner's-rights model is identical in both**, which was not obvious up front.
Both run every DCR call as the app's role; business users never hold DCR
privileges. The React app additionally receives the caller's identity token via
`executeAsCaller`, but only for the audit trail.

---

## 5. What did NOT differ

Everything that matters for correctness, because both call the same façade:

- YAML generation, the `column_type` whitelist, and the join-column rename rule
- Error decoding, including the `sql_fix` that powers "grant and retry"
- Preflight blockers (missing local link, no shared join key, missing template)
- Three-layer activation column enforcement
- Audit log and result cache — **both UIs write to and read the same tables**
- The overlap number itself: 249,778, matching the SQL ground truth exactly

This was the point of the façade. Building the second UI cost no DCR logic at all.

---

## 6. Recommendation

**Ship Track A for internal use and demos. Ship Track B to the customer.**

The customer's stated requirement was a UI replacement for the deprecated legacy
DCR web app, for business users who do not write SQL. That is Track B: the
wizards, the non-blocking long-running analysis, and the visual fidelity are what
make it a credible replacement rather than a form over an API.

Track A remains valuable and is not throwaway:

- It is the **fallback** if `FEATURE_SNOWFLAKE_APPS` is unavailable in a target
  account. This is a real risk and the reason building both was worthwhile.
- It is the **reference implementation** — the shortest readable path from façade
  operation to screen.
- It is the faster surface for internal enablement and for SEs demoing the API.

Neither is wasted work, because the expensive part — the façade — is shared.

---

## 7. Honest gaps

Recorded rather than glossed over:

| Gap | Affects | Note |
|---|---|---|
| No in-browser functional test of Track B | Track B | Service is RUNNING and Next.js started cleanly, but the app is behind Snowflake OAuth. End-to-end click-through needs your login. |
| Activation destination list is hardcoded to `PROVIDER`/`CONSUMER`/`PARTNER` | Track B | The façade rejects an undeclared destination, so this is safe but not driven from the spec. Should read `activation_destinations` from `GET_CONFIGURATION`. |
| Track A wizard state is not defended against rerun | Track A | Acceptable for a reference implementation; would need work for daily use. |
| Neither app polls query-level scan progress | Both | Possible via async query + `GET_QUERY_OPERATOR_STATS`, deliberately deferred — the phase indicator and elapsed timer are honest without it. |
| Spec/error unit tests cover generation, not execution | Façade | 62 tests pass against golden fixtures taken from real runs. They verify the YAML and the error decoder; they do not call DCR. |
| Cross-region not validated | Both | Both test accounts are same-region. Cross-Cloud Auto-Fulfillment is untested. |
