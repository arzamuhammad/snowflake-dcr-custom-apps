"use client";

/**
 * Invitations — review and join.
 *
 * This is the one workflow that bypasses the facade. COLLABORATION.JOIN installs
 * the clean room application, which calls SYSTEM$ACCEPT_LEGAL_TERMS, and
 * Snowflake refuses side-effecting functions inside a stored procedure. So the
 * work happens in /api/direct at session level. See lib/facade.ts:reviewAndJoin.
 */

import { useEffect, useState } from "react";

import { getStatus, listCollaborations, reviewAndJoin } from "@/lib/facade";
import type { CollaborationSummary, DcrError } from "@/lib/types";

import { Alert, Card, ErrorPanel, PageHeader, Spinner, StatusBadge } from "@/components/ui";

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
      setInvited(r.data.invited);
      setJoined(r.data.joined);
      setLocalNames((prev) => {
        const next = { ...prev };
        r.data.invited.forEach((i) => {
          if (i.source_name && !next[i.source_name]) next[i.source_name] = i.source_name;
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

    // JOIN is asynchronous; poll rather than block the request.
    const local = localNames[source] ?? source;
    for (let i = 0; i < 20; i++) {
      const s = await getStatus(local);
      if (s.ok) {
        setStatuses((p) => ({ ...p, [source]: s.data.status }));
        if (JSON.stringify(s.data.status).toUpperCase().includes("JOINED")) break;
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
        return (
          <Card key={source} title={source}>
            <p className="muted" style={{ marginTop: 0 }}>
              From <code>{inv.owner_account}</code>
            </p>

            <details>
              <summary>Collaboration spec — read this before joining</summary>
              <pre>{inv.spec ?? "(no spec returned)"}</pre>
            </details>

            <div className="field" style={{ maxWidth: 340, marginTop: 12 }}>
              <label>Your local name for this collaboration</label>
              <input
                value={localNames[source] ?? source}
                onChange={(e) => setLocalNames((p) => ({ ...p, [source]: e.target.value }))}
              />
              <div className="hint">May differ from the name the owner chose.</div>
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
