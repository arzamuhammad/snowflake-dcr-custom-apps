"use client";

/**
 * Create Collaboration.
 *
 * Two rules this screen enforces because the API is unforgiving about them:
 *
 *  1. Every declared collaborator must hold a role (owner, analysis runner, or
 *     data provider). Otherwise INITIALIZE fails with
 *     "declared in collaborator_identifier_aliases but have no role".
 *     Partners who will contribute data later are added as data providers with
 *     an empty offering list as a placeholder.
 *
 *  2. Who may run an analysis is decided HERE and only here. A collaborator not
 *     listed as an analysis runner can never run an overlap in this
 *     collaboration, so if both sides should be able to, both must be added now.
 */

import { useEffect, useState } from "react";

import { createCollaboration, getStatus, healthCheck, listOfferings } from "@/lib/facade";
import type { DcrError } from "@/lib/types";

import { Alert, Card, CopyBlock, ErrorPanel, PageHeader, Spinner, StatusBadge } from "@/components/ui";

interface Collaborator {
  alias: string;
  account: string;
}

interface Runner {
  alias: string;
  providerAlias: string;
  offerings: string[];
  destinations: string[];
}

export default function CreateCollaborationPage() {
  const [myAccount, setMyAccount] = useState("");
  const [offeringIds, setOfferingIds] = useState<string[]>([]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [collaborators, setCollaborators] = useState<Collaborator[]>([
    { alias: "PROVIDER", account: "" },
    { alias: "CONSUMER", account: "" },
  ]);
  const [owner, setOwner] = useState("PROVIDER");
  const [runners, setRunners] = useState<Runner[]>([
    { alias: "CONSUMER", providerAlias: "PROVIDER", offerings: [], destinations: ["CONSUMER"] },
  ]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [created, setCreated] = useState<string | null>(null);
  const [statusRows, setStatusRows] = useState<Record<string, unknown>[]>([]);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    healthCheck().then((r) => {
      if (r.ok && r.data.account) {
        setMyAccount(r.data.account);
        setCollaborators((prev) =>
          prev.map((c, i) => (i === 0 ? { ...c, account: r.data.account! } : c)),
        );
      }
    });
    listOfferings().then((r) => {
      if (r.ok) setOfferingIds(r.data.offerings.map((o) => o.DATA_OFFERING_ID));
    });
  }, []);

  const aliases = collaborators.map((c) => c.alias).filter(Boolean);

  // Which aliases already hold a role? Anything left over needs a placeholder.
  const withRoles = new Set<string>([owner]);
  runners.forEach((r) => {
    withRoles.add(r.alias);
    withRoles.add(r.providerAlias);
  });
  const roleless = aliases.filter((a) => !withRoles.has(a));

  function buildConfig() {
    const dataProviders = (r: Runner) => {
      const list = [{ alias: r.providerAlias, offerings: r.offerings }];
      // Give every otherwise-roleless collaborator a placeholder data-provider role.
      roleless.forEach((a) => list.push({ alias: a, offerings: [] }));
      return list;
    };
    return {
      name,
      description,
      owner,
      collaborators,
      analysis_runners: runners.map((r) => ({
        alias: r.alias,
        data_providers: dataProviders(r),
        activation_destinations: r.destinations,
      })),
    };
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setCreated(null);
    const r = await createCollaboration(buildConfig());
    if (r.ok) {
      setCreated(r.data.collaboration_name);
      poll(r.data.collaboration_name);
    } else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setBusy(false);
  }

  /**
   * Poll the collaborators' statuses.
   *
   * Read-only on purpose. Earlier this called ENSURE_JOINED when it saw a stalled
   * CREATED, but joining cannot succeed from here at all: it accepts legal terms,
   * which requires a user profile the app's service identity cannot have. The
   * screen reports what it sees and hands over the SQL instead.
   *
   * Matching is exact. "JOINED" as a substring also matches "JOINING", which is
   * how a still-provisioning collaboration gets mistaken for a finished one.
   */
  async function poll(collab: string) {
    setPolling(true);
    for (let i = 0; i < 30; i++) {
      const s = await getStatus(collab);
      if (!s.ok) break;
      setStatusRows(s.data.status);
      const states = s.data.status.map((r) => String(r.STATUS ?? "").trim().toUpperCase());
      if (states.length && states.every((st) => st === "JOINED")) break;
      if (states.some((st) => st.endsWith("_FAILED"))) break;
      await new Promise((res) => setTimeout(res, 15000));
    }
    setPolling(false);
  }

  return (
    <>
      <PageHeader title="Create Collaboration" sub="Initialize a new audience-overlap collaboration." />

      <Card title="1. Details">
        <div className="row">
          <div className="field">
            <label>Collaboration name</label>
            <input value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="telco_audience_overlap" />
            <div className="hint">Letters, digits and underscores only.</div>
          </div>
        </div>
        <div className="field">
          <label>Description</label>
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
      </Card>

      <Card title="2. Collaborators">
        <Alert kind="info">
          Account identifiers must be <code>ORG.ACCOUNT</code> — not an account locator and not a
          Snowsight URL. Get it by running{" "}
          <code>SELECT CURRENT_ORGANIZATION_NAME()||&apos;.&apos;||CURRENT_ACCOUNT_NAME()</code> in
          the partner account. A wrong value creates a collaboration the partner never sees.
        </Alert>

        {collaborators.map((c, i) => (
          <div className="row" key={i}>
            <div className="field">
              <label>Alias #{i + 1}</label>
              <input
                value={c.alias}
                onChange={(e) =>
                  setCollaborators((p) =>
                    p.map((x, j) => (j === i ? { ...x, alias: e.target.value.toUpperCase() } : x)),
                  )
                }
              />
            </div>
            <div className="field">
              <label>Account (ORG.ACCOUNT){i === 0 ? " — you" : ""}</label>
              <input
                value={c.account}
                onChange={(e) =>
                  setCollaborators((p) =>
                    p.map((x, j) => (j === i ? { ...x, account: e.target.value } : x)),
                  )
                }
                placeholder={i === 0 ? myAccount : "MYORG.PARTNER_ACCOUNT"}
              />
            </div>
          </div>
        ))}

        <div className="flex">
          <button
            onClick={() =>
              setCollaborators((p) => [...p, { alias: `PARTNER_${p.length}`, account: "" }])
            }
          >
            Add collaborator
          </button>
          {collaborators.length > 2 ? (
            <button onClick={() => setCollaborators((p) => p.slice(0, -1))}>Remove last</button>
          ) : null}
        </div>

        <div className="field" style={{ marginTop: 14 }}>
          <label>Owner</label>
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            {aliases.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </Card>

      <Card title="3. Who may run the analysis">
        <Alert kind="warn" title="This decision is hard to change later">
          A collaborator not listed here can <strong>never</strong> run an overlap in this
          collaboration. If both sides should be able to, add both now.
        </Alert>

        {runners.map((r, i) => (
          <div key={i} style={{ borderTop: i ? "1px solid var(--border)" : "none", paddingTop: i ? 14 : 0 }}>
            <div className="row">
              <div className="field">
                <label>Analysis runner</label>
                <select
                  value={r.alias}
                  onChange={(e) =>
                    setRunners((p) => p.map((x, j) => (j === i ? { ...x, alias: e.target.value } : x)))
                  }
                >
                  {aliases.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Their data provider</label>
                <select
                  value={r.providerAlias}
                  onChange={(e) =>
                    setRunners((p) =>
                      p.map((x, j) => (j === i ? { ...x, providerAlias: e.target.value } : x)),
                    )
                  }
                >
                  {aliases.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
            </div>

            <div className="field">
              <label>Offerings that <strong>{r.providerAlias}</strong> shares to <strong>{r.alias}</strong></label>
              <div className="hint" style={{ marginBottom: 6 }}>
                Select only the offerings this runner should see. Hold <kbd>Ctrl</kbd> (or <kbd>Cmd</kbd>) to
                pick individual items. If nothing is selected, the provider is added with an empty list
                (you can link offerings later).
              </div>
              {offeringIds.length === 0 ? (
                <div className="muted">No offerings registered yet. Register data on the My Data page first.</div>
              ) : (
                <>
                  <select
                    multiple
                    size={Math.min(5, Math.max(3, offeringIds.length))}
                    value={r.offerings}
                    onChange={(e) =>
                      setRunners((p) =>
                        p.map((x, j) =>
                          j === i
                            ? { ...x, offerings: Array.from(e.target.selectedOptions, (o) => o.value) }
                            : x,
                        ),
                      )
                    }
                  >
                    {offeringIds.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    {r.offerings.length === 0
                      ? "None selected — provider will be added with an empty offering list."
                      : `${r.offerings.length} selected: ${r.offerings.join(", ")}`}
                  </div>
                </>
              )}
            </div>

            <div className="field">
              <label>Activation destinations for this runner</label>
              <div>
                {aliases.map((a) => (
                  <label className="checkbox-row" key={a}>
                    <input
                      type="checkbox"
                      checked={r.destinations.includes(a)}
                      onChange={(e) =>
                        setRunners((p) =>
                          p.map((x, j) =>
                            j === i
                              ? {
                                  ...x,
                                  destinations: e.target.checked
                                    ? [...x.destinations, a]
                                    : x.destinations.filter((d) => d !== a),
                                }
                              : x,
                          ),
                        )
                      }
                    />
                    {a}
                  </label>
                ))}
              </div>
              <div className="hint">Separate from analysis runners — who may receive results.</div>
            </div>
          </div>
        ))}

        <div className="flex">
          <button
            onClick={() =>
              setRunners((p) => [
                ...p,
                { alias: aliases[0] ?? "", providerAlias: aliases[1] ?? "", offerings: [], destinations: [] },
              ])
            }
          >
            Add another runner
          </button>
          {runners.length > 1 ? (
            <button onClick={() => setRunners((p) => p.slice(0, -1))}>Remove last</button>
          ) : null}
        </div>

        {roleless.length ? (
          <Alert kind="info" title="Placeholder roles will be added">
            {roleless.join(", ")} hold no role yet. The API rejects that, so they will be added as
            data providers with an empty offering list.
          </Alert>
        ) : null}
      </Card>

      <Card title="4. Review and create">
        <Alert kind="warn" title="You must join manually after this completes">
          Auto-join is not offered, because it does not work: the owner&apos;s join runs inside a
          background task, and <code>SYSTEM$ACCEPT_LEGAL_TERMS</code> cannot be called from a stored
          procedure. It fails and leaves the collaboration at <code>INSTALLATION_FAILED</code>.
          Joining also requires a user profile with first name, last name and email, which a service
          identity cannot have — so it has to be a person, in a worksheet. The SQL appears below once
          the collaboration is created.
        </Alert>

        <details style={{ marginTop: 12 }}>
          <summary>Preview the configuration sent to the facade</summary>
          <pre>{JSON.stringify(buildConfig(), null, 2)}</pre>
        </details>

        <button className="primary" style={{ marginTop: 12 }} onClick={submit}
                disabled={busy || !name || collaborators.some((c) => !c.account)}>
          {busy ? "Creating…" : "Create collaboration"}
        </button>
        <div className="hint" style={{ marginTop: 6 }}>
          Provisioning takes roughly 3–5 minutes.
        </div>
      </Card>

      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}

      {created ? (
        <Card title={`Provisioning ${created}`}>
          <div className="flex" style={{ marginBottom: 10 }}>
            {polling ? <Spinner label="Polling status…" /> : <span className="badge ok">Done polling</span>}
          </div>
          {statusRows.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Collaborator</th><th>Account</th><th>Roles</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {statusRows.map((s, i) => (
                    <tr key={i}>
                      <td>{String(s.COLLABORATOR_NAME ?? "—")}</td>
                      <td className="mono">{String(s.COLLABORATOR_ACCOUNT ?? "—")}</td>
                      <td className="muted">{String(s.ROLES ?? "—")}</td>
                      <td><StatusBadge status={String(s.STATUS ?? "")} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <Alert kind="warn" title="Now join as the owner — this app cannot do it">
            The collaboration exists, but you are not in it until you join, and joining accepts
            legal terms on your behalf. Snowflake only allows an identifiable user to do that, so it
            has to be run by a person whose profile has first name, last name and email set. Run
            this in a Snowsight worksheet, then have your partner accept their invitation the same
            way.
          </Alert>

          <CopyBlock
            label="Run once as the owner"
            sql={[
              "USE ROLE ACCOUNTADMIN;",
              "USE WAREHOUSE APP_WH;",
              "USE SECONDARY ROLES NONE;",
              "",
              `CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION.JOIN('${created}');`,
              "",
              "-- Poll until every row reads exactly JOINED (JOINING means still working):",
              `CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION.GET_STATUS('${created}');`,
            ].join("\n")}
          />

          <div className="hint" style={{ marginTop: 8 }}>
            If the status reaches <code>INSTALLATION_FAILED</code>, read the <code>DETAILS</code>{" "}
            column. An incomplete user profile and a nested{" "}
            <code>SYSTEM$ACCEPT_LEGAL_TERMS</code> are the two causes seen in practice. Recover by
            calling <code>REVIEW</code> again and then <code>JOIN</code> — <code>LEAVE</code> is
            rejected from that state.
          </div>
        </Card>
      ) : null}
    </>
  );
}
