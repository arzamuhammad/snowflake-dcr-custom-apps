"use client";

/**
 * Link Data.
 *
 * The screen that exists because the official Snowsight UI conflates two
 * different operations:
 *
 *   LINK_DATA_OFFERING       a data provider shares ITS data TO runners  -> p1
 *   LINK_LOCAL_DATA_OFFERING an analysis runner attaches its OWN table   -> c1
 *
 * Only the first is exposed in the official UI. If the second was never called,
 * the runner has no my_table, no overlap is possible, and there is no way to fix
 * it from inside the AO&A app. Hence the red banner below.
 */

import { useEffect, useState } from "react";

import { getCollaborationDetail, linkData, listOfferings, unlinkData } from "@/lib/facade";
import type { CollaborationDetail, CollaborationSummary, DcrError, OfferingRef } from "@/lib/types";

import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Alert, Card, ErrorPanel, PageHeader, Spinner } from "@/components/ui";

export default function LinkDataPage() {
  const [collab, setCollab] = useState("");
  const [summary, setSummary] = useState<CollaborationSummary | undefined>();
  const [detail, setDetail] = useState<CollaborationDetail | null>(null);
  const [offeringIds, setOfferingIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const [localOffering, setLocalOffering] = useState("");
  const [partnerOffering, setPartnerOffering] = useState("");
  const [runnersText, setRunnersText] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    listOfferings().then((r) => {
      if (r.ok) setOfferingIds(r.data.offerings.map((o) => o.DATA_OFFERING_ID));
    });
  }, []);

  async function load(name: string) {
    if (!name) return setDetail(null);
    setLoading(true);
    const r = await getCollaborationDetail(name);
    if (r.ok) setDetail(r.data);
    else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setLoading(false);
  }

  useEffect(() => {
    load(collab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collab]);

  async function doLink(mode: "local" | "partner") {
    setBusy(true);
    setError(null);
    setMsg(null);
    const offering = mode === "local" ? localOffering : partnerOffering;
    const runners = mode === "partner"
      ? runnersText.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean)
      : undefined;

    const r = await linkData(collab, offering, mode, runners);
    if (r.ok) {
      setMsg(mode === "local"
        ? `Linked ${offering} as your own data (the c1 side).`
        : `Shared ${offering} to ${runners?.join(", ")}.`);
      await load(collab);
    } else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setBusy(false);
  }

  async function doUnlink(offering: string, mode: "local" | "partner") {
    setBusy(true);
    const r = await unlinkData(collab, offering, mode);
    if (r.ok) {
      setMsg(`Unlinked ${offering}.`);
      await load(collab);
    } else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setBusy(false);
  }

  return (
    <>
      <PageHeader title="Link Data" sub="Connect your data and your partner's data to a collaboration." />

      <CollaborationPicker value={collab} onChange={(n, c) => { setCollab(n); setSummary(c); }} />

      {loading ? <Spinner label="Loading collaboration…" /> : null}
      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}
      {msg ? <Alert kind="ok">{msg}</Alert> : null}

      {detail ? (
        <>
          {!detail.my_offerings.length ? (
            <Alert kind="err" title="You have not linked any data of your own">
              Audience overlap needs both sides. Until you link your own table with{" "}
              <code>LINK_LOCAL_DATA_OFFERING</code>, no overlap can run — and this is the step the
              official Snowsight UI does not expose. Use <strong>Link my own data</strong> below.
            </Alert>
          ) : null}

          <Card title="Partner offerings — the source_table / p1 side">
            <OfferingTable
              rows={detail.partner_offerings}
              empty="No partner data available yet. The data provider must share an offering with you."
              onUnlink={(id) => doUnlink(id, "partner")}
              busy={busy}
            />
          </Card>

          <Card title="Your linked data — the my_table / c1 side">
            <OfferingTable
              rows={detail.my_offerings}
              empty="Nothing linked yet."
              onUnlink={(id) => doUnlink(id, "local")}
              busy={busy}
            />
          </Card>

          <Card title="Link my own data (LINK_LOCAL_DATA_OFFERING)">
            <p className="muted" style={{ marginTop: 0 }}>
              Attach one of your registered offerings so it becomes the <code>c1</code> side of the
              match. Required for whoever runs the analysis.
            </p>
            <div className="row">
              <div className="field">
                <label>My offering</label>
                <select value={localOffering} onChange={(e) => setLocalOffering(e.target.value)}>
                  <option value="">Select…</option>
                  {offeringIds.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            </div>
            <button className="primary" onClick={() => doLink("local")} disabled={busy || !localOffering}>
              {busy ? "Linking…" : "Link my data"}
            </button>
          </Card>

          {/* LINK_DATA_OFFERING belongs to a data provider. Offering it to a pure
              analysis runner only produces ProviderNotServingAnalysisRunner, so
              the operation is disclosed rather than presented as a step. */}
          {detail.is_data_provider === false ? (
            <Card title="Share my offering to runners (LINK_DATA_OFFERING)">
              <Alert kind="info" title="Not your operation in this collaboration">
                You are{" "}
                {detail.my_roles?.length ? (
                  <strong>{detail.my_roles.join(", ")}</strong>
                ) : (
                  "not a data provider"
                )}{" "}
                here{detail.my_alias ? <> (alias <code>{detail.my_alias}</code>)</> : null}, so there
                is nothing for you to share outward. Sharing is done by the data provider, in their
                own account. Attempting it here fails with{" "}
                <code>ProviderNotServingAnalysisRunner</code>.
                <div style={{ marginTop: 8 }}>
                  What you need on this side is <strong>Link my own data</strong> above — the{" "}
                  <code>c1</code> side of the match.
                </div>
              </Alert>
            </Card>
          ) : (
            <Card title="Share my offering to runners (LINK_DATA_OFFERING)">
              <p className="muted" style={{ marginTop: 0 }}>
                As a data provider, share one of your offerings with named analysis runners. Usually
                already done at creation time.
              </p>
              {detail.serves_runners?.length ? (
                <div className="hint" style={{ marginBottom: 10 }}>
                  You already serve: <code>{detail.serves_runners.join(", ")}</code>. You may only
                  link for runners the collaboration assigns to you.
                </div>
              ) : null}
              <div className="row">
                <div className="field">
                  <label>Offering to share</label>
                  <select value={partnerOffering} onChange={(e) => setPartnerOffering(e.target.value)}>
                    <option value="">Select…</option>
                    {offeringIds.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Runner aliases (comma-separated)</label>
                  <input value={runnersText} onChange={(e) => setRunnersText(e.target.value)}
                         placeholder="CONSUMER" />
                </div>
              </div>
              <button onClick={() => doLink("partner")} disabled={busy || !partnerOffering || !runnersText}>
                {busy ? "Sharing…" : "Share offering"}
              </button>
              <Alert kind="info" title="If this fails with 'Grant not executed'">
                These procedures do not merely read your data — they <em>grant</em> access on it to the
                collaboration application. A role can only pass on a privilege it holds{" "}
                <code>WITH GRANT OPTION</code>, so plain <code>SELECT</code> is not enough.
              </Alert>
            </Card>
          )}
        </>
      ) : null}
    </>
  );
}

function OfferingTable({
  rows,
  empty,
  onUnlink,
  busy,
}: {
  rows: OfferingRef[];
  empty: string;
  onUnlink: (id: string) => void;
  busy: boolean;
}) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Offering</th>
            <th>View name (use verbatim)</th>
            <th>Join columns</th>
            <th>Activatable</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.offering_id + o.view_name}>
              <td><strong>{o.offering_id}</strong></td>
              <td className="mono">{o.view_name}</td>
              <td>
                {o.join_columns.map((j) => (
                  <span className="badge warn" key={j} style={{ marginRight: 4 }}>
                    {j.toUpperCase()}
                  </span>
                ))}
              </td>
              <td className="muted">{o.activation_columns.length} columns</td>
              <td className="right">
                <button onClick={() => onUnlink(o.offering_id)} disabled={busy}>Unlink</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">
        Join columns are shown as their <strong>exposed</strong> names. A{" "}
        <code>join_standard</code> column is renamed to its column type, so both sides must use the
        same column type for a match to be possible.
      </p>
    </div>
  );
}
