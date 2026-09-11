"use client";

/**
 * Invitations — review the spec, then join outside the app.
 *
 * Joining is deliberately NOT performed here, and that is a platform constraint
 * rather than a missing feature. COLLABORATION.JOIN calls
 * SYSTEM$ACCEPT_LEGAL_TERMS, and Snowflake requires the acting user to have a
 * real profile — first_name, last_name and email — because somebody is agreeing
 * to legal terms. That leaves no viable path from a deployed app:
 *
 *   - Owner's rights (what this app uses) acts as an SPCS managed service
 *     identity. It holds the DCR privileges but is not a user object at all, so
 *     it cannot be given a profile. JOIN fails during installation, the request
 *     hangs, and the caller sees a gateway 504.
 *   - Caller's rights acts as the signed-in person, who has a profile but
 *     deliberately does not hold SAMOOHA_APP_ROLE — that separation is the
 *     entire point of the owner's-rights design. JOIN fails on privileges.
 *
 * So this page shows the spec to review and hands over ready-to-run SQL. Joining
 * is a one-time administrative act per collaboration, not a recurring business-
 * user task, and the person doing it should be identifiable. Everything after
 * joining works normally in the app.
 */

import { useEffect, useState } from "react";

import { listCollaborations } from "@/lib/facade";
import type { CollaborationSummary } from "@/lib/types";

import { Alert, Card, CopyBlock, PageHeader, Spinner, StatusBadge } from "@/components/ui";

const DCR = "SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION";

function joinSql(source: string, owner: string, local: string) {
  return [
    "-- Run as a user whose profile has first_name, last_name and email set,",
    "-- and whose role can use Data Clean Rooms. Check yours with:",
    "--   SELECT CURRENT_USER();",
    "--   SHOW USERS LIKE CURRENT_USER();      -- first_name / last_name / email",
    "",
    "USE ROLE ACCOUNTADMIN;",
    "USE WAREHOUSE APP_WH;",
    "USE SECONDARY ROLES NONE;   -- required; registering and linking fail without it",
    "",
    `CALL ${DCR}.REVIEW(`,
    `  '${source}',   -- source_name, as the owner published it`,
    `  '${owner}',   -- owner_account`,
    `  '${local}'    -- your local name for it`,
    ");",
    "",
    `CALL ${DCR}.JOIN('${local}');`,
    "",
    "-- Joining takes a few minutes. Poll until STATUS reads exactly JOINED:",
    `CALL ${DCR}.GET_STATUS('${local}');`,
  ].join("\n");
}

export default function InvitationsPage() {
  const [invited, setInvited] = useState<CollaborationSummary[]>([]);
  const [joined, setJoined] = useState<CollaborationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [localNames, setLocalNames] = useState<Record<string, string>>({});

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

  if (loading) return <Spinner label="Loading invitations…" />;

  return (
    <>
      <PageHeader title="Invitations" sub="Review what you are agreeing to, then join from a worksheet." />

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
                value={local}
                onChange={(e) => setLocalNames((p) => ({ ...p, [source]: e.target.value }))}
              />
              <div className="hint">
                May differ from the name the owner chose. The SQL below updates as you type.
              </div>
            </div>

            <Alert kind="warn" title="Joining has to be done by a person, not by this app">
              Joining accepts legal terms, so Snowflake requires the acting user to have a profile
              with first name, last name and email. This app runs as a service identity, which is
              not a user object and cannot be given one — attempting it here fails during
              installation and returns a gateway timeout. Run the statements below once in a
              Snowsight worksheet, then reload this page.
            </Alert>

            <CopyBlock sql={joinSql(source, inv.owner_account ?? "", local)} label="Run once in a worksheet" />

            <div className="hint" style={{ marginTop: 8 }}>
              If <code>GET_STATUS</code> reports <code>INSTALLATION_FAILED</code>, the usual cause is
              an incomplete user profile. Fix it with{" "}
              <code>ALTER USER &lt;name&gt; SET first_name=&apos;…&apos;, last_name=&apos;…&apos;, email=&apos;…&apos;</code>, then
              call <code>REVIEW</code> again followed by <code>JOIN</code>. <code>LEAVE</code> will
              not work from that state.
            </div>
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
