"use client";

import { useEffect, useState } from "react";

import { activityHistory } from "@/lib/facade";
import type { DcrError } from "@/lib/types";

import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Alert, Card, DataTable, ErrorPanel, PageHeader, Spinner } from "@/components/ui";

type Tab = "console" | "dcr";

export default function HistoryPage() {
  const [collab, setCollab] = useState("");
  const [tab, setTab] = useState<Tab>("console");
  const [consoleRows, setConsoleRows] = useState<Record<string, unknown>[]>([]);
  const [dcrRows, setDcrRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();

  async function load(name: string) {
    if (!name) {
      setConsoleRows([]);
      setDcrRows([]);
      return;
    }
    setLoading(true);
    const r = await activityHistory(name);
    if (r.ok) {
      setConsoleRows(r.data.console_history);
      setDcrRows(r.data.dcr_history);
    } else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setLoading(false);
  }

  useEffect(() => {
    load(collab);
  }, [collab]);

  return (
    <>
      <PageHeader title="History" sub="Every run and activation, with duration, outcome, and decoded errors." />

      <CollaborationPicker value={collab} onChange={(n) => setCollab(n)} />

      <div className="flex" style={{ marginBottom: 16 }}>
        <button className={tab === "console" ? "primary" : ""} onClick={() => setTab("console")}>
          Console audit log
        </button>
        <button className={tab === "dcr" ? "primary" : ""} onClick={() => setTab("dcr")}>
          DCR activity history
        </button>
        <button onClick={() => load(collab)} disabled={!collab || loading}>Refresh</button>
        {loading ? <Spinner /> : null}
      </div>

      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}

      {tab === "console" ? (
        <Card title="Console audit log">
          <p className="muted" style={{ marginTop: 0 }}>
            Written by the facade for every operation, including failures and the generated spec.
            This is the compliance artifact: who shared what with whom, and when.
          </p>
          <DataTable rows={consoleRows} />
        </Card>
      ) : (
        <Card title="DCR activity history">
          <p className="muted" style={{ marginTop: 0 }}>
            Returned by <code>VIEW_ACTIVITY_HISTORY</code> — DCR&apos;s own record, independent of
            this console.
          </p>
          <DataTable rows={dcrRows} />
        </Card>
      )}

      {collab ? (
        <Alert kind="info" title="Querying the audit log directly">
          <pre>{`SELECT EVENT_TS, ACTOR_USER, OPERATION, OUTCOME, DURATION_MS,
       ERROR_DECODED:title::STRING       AS ERROR_TITLE,
       ERROR_DECODED:remediation::STRING AS FIX
FROM DCR_CONSOLE.META.AUDIT_LOG
WHERE COLLABORATION = '${collab}'
ORDER BY EVENT_TS DESC;`}</pre>
        </Alert>
      ) : null}
    </>
  );
}
