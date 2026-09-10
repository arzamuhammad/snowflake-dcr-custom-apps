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

import { createCollaboration, ensureJoined, getStatus, healthCheck, listOfferings } from "@/lib/facade";
import type { DcrError } from "@/lib/types";

import { Alert, Card, ErrorPanel, PageHeader, Spinner, StatusBadge } from "@/components/ui";

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
  const [autoJoin, setAutoJoin] = useState(true);
  const [warehouse, setWarehouse] = useState("APP_WH");

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
    const r = await createCollaboration(buildConfig(), autoJoin ? warehouse : undefined);
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
   * Poll to JOINED.
   *
   * ENSURE_JOINED is used rather than plain GET_STATUS because auto-join is best
   * effort: the task can fail while INITIALIZE reports success, leaving the
   * collaboration at CREATED with the failure buried in the DETAILS blob.
   * ENSURE_JOINED detects that and calls JOIN.
   */
  async function poll(collab: string) {
    setPolling(true);
    for (let i = 0; i < 30; i++) {
      const s = await getStatus(collab);
      if (s.ok) setStatusRows(s.data.status);
      const text = JSON.stringify(s.ok ? s.data.status : "").toUpperCase();
      if (text.includes("JOINED")) break;
      if (text.includes("CREATED") && !text.includes("JOINING")) {
        await ensureJoined(collab);
      }
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
              <label>Offerings that provider shares to this runner</label>
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
              <div className="hint">
                Leave empty as a placeholder if the data is registered later.
              </div>
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
        <label className="checkbox-row">
          <input type="checkbox" checked={autoJoin} onChange={(e) => setAutoJoin(e.target.checked)} />
          Auto-join as owner (recommended)
        </label>
        {autoJoin ? (
          <div className="field" style={{ maxWidth: 260, marginTop: 8 }}>
            <label>Warehouse for the auto-join task</label>
            <input value={warehouse} onChange={(e) => setWarehouse(e.target.value)} />
          </div>
        ) : null}

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
          <Alert kind="info" title="If the status stays at CREATED">
            Auto-join can fail silently — the task fails while INITIALIZE reports success. This page
            calls <code>ENSURE_JOINED</code> automatically when it sees that state, which performs
            the JOIN for you.
          </Alert>
        </Card>
      ) : null}
    </>
  );
}
