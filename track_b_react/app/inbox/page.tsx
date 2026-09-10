"use client";

/**
 * Activation Inbox — the step the official tutorials leave as manual SQL.
 *
 * Without it an activation reports success while the recipient has nothing
 * usable: the payload is a VARIANT column shaped as
 *   {"ID": {"p1.TOP_GENRE": "...", "c1.SEGMENT": "...", "join_clause": "..."}}
 * sitting inside a share. This page runs PROCESS_ACTIVATION, discovers the
 * activated column names, and flattens SEGMENT_RECORDS into a typed table with
 * the alias prefixes stripped.
 *
 * This is also the only place in the application that shows a real percentage,
 * because here the rows can actually be counted.
 */

import { useCallback, useEffect, useState } from "react";

import { getImportProgress, importActivation, listActivations } from "@/lib/facade";
import type { ActivationBatch, DcrError, ImportProgressData } from "@/lib/types";

import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Alert, Card, ErrorPanel, PageHeader, Progress, Spinner, StatusBadge, fmt } from "@/components/ui";

export default function InboxPage() {
  const [collab, setCollab] = useState("");
  const [batches, setBatches] = useState<ActivationBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [progress, setProgress] = useState<Record<string, ImportProgressData>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async (name: string) => {
    if (!name) return setBatches([]);
    setLoading(true);
    const r = await listActivations(name);
    if (r.ok) {
      setBatches(r.data.activations);
      setTargets((prev) => {
        const next = { ...prev };
        r.data.activations.forEach((b) => {
          if (!next[b.batch_id]) {
            const seg = (b.segment_name ?? b.batch_id.slice(0, 8)).toUpperCase();
            next[b.batch_id] = b.import?.target_fqn ?? `MY_DB.ACTIVATED.${seg}`;
          }
        });
        return next;
      });
    } else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load(collab);
  }, [collab, load]);

  async function doImport(b: ActivationBatch) {
    setBusy(b.batch_id);
    setError(null);
    setMsg(null);

    const r = await importActivation({
      collaboration: collab,
      batch_id: b.batch_id,
      target_fqn: targets[b.batch_id],
    });

    if (r.ok) {
      setMsg(`Imported ${r.data.imported_rows.toLocaleString()} rows into ${r.data.target_fqn}`);
      const p = await getImportProgress(r.data.import_id);
      if (p.ok) setProgress((prev) => ({ ...prev, [b.batch_id]: p.data }));
      await load(collab);
    } else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setBusy(null);
  }

  return (
    <>
      <PageHeader
        title="Activation Inbox"
        sub="Import activated segments and materialise them as tables you can query."
      />

      <CollaborationPicker value={collab} onChange={(n) => setCollab(n)} />

      {loading ? <Spinner label="Loading activations…" /> : null}
      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}
      {msg ? <Alert kind="ok">{msg}</Alert> : null}

      {collab && !loading && !batches.length ? (
        <Alert kind="info" title="No activations for this collaboration">
          Once someone runs an activation targeting your account, the batch appears here.
        </Alert>
      ) : null}

      {batches.map((b) => {
        const p = progress[b.batch_id] ?? null;
        return (
          <Card key={b.batch_id}>
            <div className="flex" style={{ marginBottom: 10 }}>
              <StatusBadge status={b.status ?? "unknown"} />
              <strong className="grow">{b.segment_name ?? "(unnamed segment)"}</strong>
              {b.imported ? <span className="badge ok">imported</span> : null}
            </div>

            <div className="hint" style={{ marginBottom: 12 }}>
              Batch <code>{b.batch_id}</code>
              {b.updated_on ? <> · updated {b.updated_on.slice(0, 19)}</> : null}
            </div>

            {b.import?.status === "FAILED" ? (
              <Alert kind="err" title="A previous import failed">
                Retry below. If the batch has not been delivered yet, the flatten step finds no rows
                and fails — wait and retry.
              </Alert>
            ) : null}

            {b.imported && b.import ? (
              <Alert kind="ok" title="Already imported">
                <code>{b.import.target_fqn}</code> — {fmt(b.import.imported_rows)} rows.
              </Alert>
            ) : null}

            <div className="row">
              <div className="field">
                <label>Target table (DATABASE.SCHEMA.TABLE)</label>
                <input
                  value={targets[b.batch_id] ?? ""}
                  onChange={(e) => setTargets((prev) => ({ ...prev, [b.batch_id]: e.target.value }))}
                />
                <div className="hint">
                  The schema must exist and the console role needs CREATE TABLE on it.
                </div>
              </div>
            </div>

            <button
              className="primary"
              onClick={() => doImport(b)}
              disabled={busy === b.batch_id || !targets[b.batch_id]}
            >
              {busy === b.batch_id ? "Importing…" : b.imported ? "Re-import" : "Import and flatten"}
            </button>

            {busy === b.batch_id ? (
              <div style={{ marginTop: 12 }}>
                <Spinner label="Processing the batch and flattening SEGMENT_RECORDS…" />
              </div>
            ) : null}

            {p?.percent_complete != null ? (
              <div style={{ marginTop: 12 }}>
                <Progress
                  percent={p.percent_complete}
                  label={`${p.percent_complete.toFixed(1)}% — ${fmt(p.imported_rows)} of ${fmt(p.expected_rows)} rows`}
                />
              </div>
            ) : null}
          </Card>
        );
      })}

      {batches.length ? (
        <Card title="What the flatten step does">
          <p style={{ marginTop: 0 }}>The activation payload arrives as a VARIANT column:</p>
          <pre>{`{"ID": {"p1.TOP_GENRE": "Action", "c1.CUSTOMER_SEGMENT": "Medium Buyer", "join_clause": "..."}}`}</pre>
          <p>Which is turned into a normal table with the alias prefixes removed:</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>TOP_GENRE</th><th>CUSTOMER_SEGMENT</th><th>MATCH_CRITERIA</th><th>BATCH_ID</th><th>SEGMENT_NAME</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Action</td><td>Medium Buyer</td>
                  <td className="mono">p1.HASHED_EMAIL_SHA256 = c1.HASHED_EMAIL_SHA256</td>
                  <td className="mono">202ba43b…</td><td>q3_overlap</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="hint">
            If both sides expose a column with the same name, the second keeps its side prefix so the
            output has no duplicate column names.
          </p>
        </Card>
      ) : null}
    </>
  );
}
