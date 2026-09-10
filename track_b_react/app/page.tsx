"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { listCollaborations } from "@/lib/facade";
import type { ListCollaborationsData } from "@/lib/types";

import { Alert, Card, Metric, PageHeader, Spinner, StatusBadge } from "@/components/ui";

export default function Home() {
  const [data, setData] = useState<ListCollaborationsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCollaborations().then((r) => (r.ok ? setData(r.data) : setError(r.error.cause)));
  }, []);

  if (error) return <Alert kind="err" title="Could not load collaborations">{error}</Alert>;
  if (!data) return <Spinner label="Loading…" />;

  const { joined, invited, account } = data;

  return (
    <>
      <PageHeader
        title="DCR Audience Overlap Console"
        sub={`Collaboration API v2 · running as ${account}`}
      />

      <div className="metrics" style={{ marginBottom: 20 }}>
        <Metric label="Joined" value={joined.length} />
        <Metric label="Pending invitations" value={invited.length} />
        <Metric label="Total" value={joined.length + invited.length} />
      </div>

      {invited.length ? (
        <Alert kind="info" title={`${invited.length} invitation awaiting review`}>
          Go to <Link href="/invitations">Invitations</Link> to review the spec and join.
        </Alert>
      ) : null}

      {joined.length ? (
        <Card title="Joined collaborations">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Your role</th>
                  <th>Owner account</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {joined.map((c) => (
                  <tr key={c.local_name}>
                    <td><strong>{c.local_name}</strong></td>
                    <td><StatusBadge status={c.is_owner ? "OWNER" : "COLLABORATOR"} /></td>
                    <td className="mono">{c.owner_account}</td>
                    <td className="muted">{c.updated_on?.slice(0, 19) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {!joined.length && !invited.length ? (
        <Card>
          <p>No collaborations yet. Two ways to start:</p>
          <ol>
            <li>
              Run <Link href="/health">Health Check</Link> to confirm prerequisites, then register a
              table on <Link href="/my-data">My Data</Link> and create a collaboration.
            </li>
            <li>Ask a partner to invite your account, then accept it on Invitations.</li>
          </ol>
        </Card>
      ) : null}

      <Card title="How the workflow fits together">
        <ol className="stack" style={{ paddingLeft: 18, margin: 0 }}>
          <li><strong>Health Check</strong> — confirm DCR is installed, mounted, and the two standard templates are registered.</li>
          <li><strong>My Data</strong> — register a table: pick the join key, its PII type, and which columns may be activated.</li>
          <li><strong>Create</strong> — declare collaborators, who may run analysis, and where activations may be sent.</li>
          <li><strong>Invitations</strong> — the partner reviews and joins.</li>
          <li><strong>Link Data</strong> — whoever runs the analysis must link their <em>own</em> table too, not just receive the partner&apos;s.</li>
          <li><strong>Run Overlap</strong> → <strong>Activate</strong> → <strong>Activation Inbox</strong> to import the result as a usable table.</li>
        </ol>
      </Card>
    </>
  );
}
