"use client";

/**
 * Invitations — review and join a collaboration.
 *
 * JOIN runs as the CALLER (the person logged in), not as the app's service
 * identity. This is the one operation that uses caller's rights, because:
 *
 *   1. COLLABORATION.JOIN calls SYSTEM$ACCEPT_LEGAL_TERMS, which requires a
 *      user with first_name, last_name and email — a real person.
 *   2. It needs SAMOOHA_APP_ROLE, which the caller must hold.
 *
 * Every other operation continues through the facade with owner's rights.
 *
 * If caller's rights is unavailable (missing token, local dev), the page falls
 * back to showing copy-ready SQL.
 */

import { useEffect, useState } from "react";

import { getStatus, listCollaborations, reviewAndJoin } from "@/lib/facade";
import type { CollaborationSummary, DcrError } from "@/lib/types";

import { Alert, Card, CopyBlock, ErrorPanel, PageHeader, Spinner, StatusBadge } from "@/components/ui";

const DCR_COLLAB = "SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION";

function joinSql(source: string, owner: string, local: string) {
  return [
    "-- Prerequisites: SAMOOHA_APP_ROLE + first_name, last_name, email on your profile",
    "USE ROLE ACCOUNTADMIN;",
    "USE WAREHOUSE APP_WH;",
    "USE SECONDARY ROLES NONE;",
    "",
    `CALL ${DCR_COLLAB}.REVIEW('${source}', '${owner}', '${local}');`,
    `CALL ${DCR_COLLAB}.JOIN('${local}');`,
    "",
    "-- Poll until every row reads exactly JOINED:",
    `CALL ${DCR_COLLAB}.GET_STATUS('${local}');`,
  ].join("\n");
}

export default function InvitationsPage() {
  const [invited, setInvited] = useState<CollaborationSummary[]>([]);
  const [joined, setJoined] = useState<CollaborationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [localNames, setLocalNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [statuses, setStatuses] = useState<Record<string, Record<string, unknown>[]>>({});

  async function load() {
    setLoading(true);
    const r = await listCollaborations();
    if (r.ok) {
      // in_review rows are actionable, not done: a local name has been assigned
      // but the join has not completed, and DCR refuses every operation until it
      // reads JOINED. Listing them as "already joined" hides the only button
      // that can finish them.
      const actionable = [...r.data.invited, ...r.data.in_review];
      setInvited(actionable);
      setJoined(r.data.joined);
      setLocalNames((prev) => {
        const next = { ...prev };
        actionable.forEach((i) => {
          if (!i.source_name) return;
          // Once reviewed, the local name is fixed and cannot be changed.
          if (i.local_name) next[i.source_name] = i.local_name;
          else if (!next[i.source_name]) next[i.source_name] = i.source_name;
        });
        return next;
      });
    }
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function join(inv: CollaborationSummary) {
    const source = inv.source_name!;
    setBusy(source);
    setError(null);

    const r = await reviewAndJoin({
      source_name: source,
      owner_account: inv.owner_account ?? "",
      local_name: localNames[source] ?? source,
    });

    if (!r.ok) {
      setError(r.error);
      setErrorRaw(r.error_raw);
      setBusy(null);
      return;
    }

    // Poll to JOINED. Matching is exact to avoid confusing JOINING with JOINED.
    const local = localNames[source] ?? source;
    for (let i = 0; i < 20; i++) {
      const s = await getStatus(local);
      if (s.ok) {
        setStatuses((p) => ({ ...p, [source]: s.data.status }));
        const states = s.data.status.map((r) => String(r.STATUS ?? "").trim().toUpperCase());
        if (states.length && states.every((st) => st === "JOINED")) break;
        if (states.some((st) => st.endsWith("_FAILED"))) break;
      }
      await new Promise((res) => setTimeout(res, 12000));
    }

    setBusy(null);
    await load();
  }

  if (loading) return <Spinner label="Loading invitations…" />;

  return (
    <>
      <PageHeader title="Invitations" sub="Review what you are agreeing to, then join." />

      <Alert kind="info" title="Prerequisites for joining">
        Joining accepts legal terms, so <strong>you</strong> (the person logged in) must have:
        <ul style={{ marginTop: 6, marginBottom: 0 }}>
          <li><code>SAMOOHA_APP_ROLE</code> granted to your user</li>
          <li><code>first_name</code>, <code>last_name</code>, <code>email</code> set on your profile</li>
        </ul>
        If either is missing the join will fail with a clear error — not a 504.
        This is the only operation that needs these; everything else runs through the facade.
      </Alert>

      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}

      {!invited.length ? (
        <Alert kind="info" title="No pending invitations">
          If you expected one: the provider may not have created it yet, the account identifier in
          their spec may be wrong, or the collaboration may be cross-region without Cross-Cloud
          Auto-Fulfillment enabled.
        </Alert>
      ) : null}

      {invited.map((inv) => {
        const source = inv.source_name!;
        const local = localNames[source] ?? source;
        const reviewed = Boolean(inv.local_name);
        return (
          <Card key={source} title={source}>
            <p className="muted" style={{ marginTop: 0 }}>
              From <code>{inv.owner_account}</code>
              {inv.status ? (
                <>
                  {" — "}
                  <StatusBadge status={inv.status} />
                </>
              ) : null}
            </p>

            {reviewed ? (
              <Alert kind="info" title="Reviewed, but not joined yet">
                A local name is already assigned, which is why this is not a fresh
                invitation — but the join has not completed, so DCR will still refuse
                every operation with <em>“requires the collaboration status to be one
                of: JOINED”</em>. Click <strong>Review and join</strong> to finish it;
                the review step is skipped automatically.
              </Alert>
            ) : null}

            <details>
              <summary>Collaboration spec — read this before joining</summary>
              <pre>{inv.spec ?? "(no spec returned)"}</pre>
            </details>

            <div className="field" style={{ maxWidth: 340, marginTop: 12 }}>
              <label>Your local name for this collaboration</label>
              <input
                value={local}
                readOnly={reviewed}
                onChange={(e) => setLocalNames((p) => ({ ...p, [source]: e.target.value }))}
              />
              <div className="hint">
                {reviewed
                  ? "Fixed at review time and cannot be changed now."
                  : "May differ from the name the owner chose."}
              </div>
            </div>

            <button className="primary" onClick={() => join(inv)} disabled={busy === source}>
              {busy === source ? "Joining…" : "Review and join"}
            </button>
            {busy === source ? (
              <div className="flex" style={{ marginTop: 10 }}>
                <Spinner label="This takes 1–2 minutes…" />
              </div>
            ) : null}

            {statuses[source]?.length ? (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead><tr><th>Collaborator</th><th>Status</th></tr></thead>
                  <tbody>
                    {statuses[source].map((s, i) => (
                      <tr key={i}>
                        <td>{String(s.COLLABORATOR_NAME ?? "—")}</td>
                        <td><StatusBadge status={String(s.STATUS ?? "")} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            <details style={{ marginTop: 12 }}>
              <summary>Alternative: run manually in a worksheet</summary>
              <CopyBlock sql={joinSql(source, inv.owner_account ?? "", local)} />
            </details>
          </Card>
        );
      })}

      {joined.length ? (
        <Card title="Already joined">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Local name</th><th>Owner</th><th>Your role</th></tr></thead>
              <tbody>
                {joined.map((c) => (
                  <tr key={c.local_name}>
                    <td><strong>{c.local_name}</strong></td>
                    <td className="mono">{c.owner_account}</td>
                    <td><StatusBadge status={c.is_owner ? "OWNER" : "COLLABORATOR"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Alert kind="info" title="Next step">
            Whoever runs the analysis must link their <strong>own</strong> table on the{" "}
            <strong>Link Data</strong> page. Receiving the partner&apos;s data is not enough.
          </Alert>
        </Card>
      ) : null}
    </>
  );
}
