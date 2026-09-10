"use client";

import { useEffect, useState } from "react";

import {
  addTemplate,
  approveUpdateRequest,
  getAppRole,
  listCollaborations,
  listUpdateRequests,
  rejectUpdateRequest,
  setAppRole,
  teardownOrLeave,
} from "@/lib/facade";
import type { AppRoleData, CollaborationSummary, DcrError } from "@/lib/types";

import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Alert, Card, DataTable, ErrorPanel, PageHeader, Spinner, StatusBadge } from "@/components/ui";

type Tab = "requests" | "templates" | "lifecycle" | "rbac";

export default function AdminPage() {
  const [collab, setCollab] = useState("");
  const [summary, setSummary] = useState<CollaborationSummary | undefined>();
  const [tab, setTab] = useState<Tab>("requests");
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [msg, setMsg] = useState<string | null>(null);

  function fail(e: DcrError, raw?: string) {
    setError(e);
    setErrorRaw(raw);
    setMsg(null);
  }
  function ok(m: string) {
    setMsg(m);
    setError(null);
  }

  return (
    <>
      <PageHeader title="Admin" sub="Update requests, template sharing, lifecycle, and app permissions." />

      <CollaborationPicker value={collab} onChange={(n, c) => { setCollab(n); setSummary(c); }} />

      <div className="flex" style={{ marginBottom: 16 }}>
        {(["requests", "templates", "lifecycle", "rbac"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "primary" : ""} onClick={() => setTab(t)}>
            {{ requests: "Update requests", templates: "Add template", lifecycle: "Leave / Teardown", rbac: "App RBAC" }[t]}
          </button>
        ))}
      </div>

      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}
      {msg ? <Alert kind="ok">{msg}</Alert> : null}

      {tab === "requests" ? <RequestsTab collab={collab} onOk={ok} onFail={fail} /> : null}
      {tab === "templates" ? <TemplatesTab collab={collab} onOk={ok} onFail={fail} /> : null}
      {tab === "lifecycle" ? <LifecycleTab collab={collab} summary={summary} onOk={ok} onFail={fail} /> : null}
      {tab === "rbac" ? <RbacTab onOk={ok} onFail={fail} /> : null}
    </>
  );
}

// ---------------------------------------------------------------------------

interface TabProps {
  collab: string;
  onOk: (m: string) => void;
  onFail: (e: DcrError, raw?: string) => void;
}

function RequestsTab({ collab, onOk, onFail }: TabProps) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  async function load() {
    if (!collab) return setRows([]);
    setLoading(true);
    const r = await listUpdateRequests(collab);
    if (r.ok) setRows(r.data.requests);
    else onFail(r.error, r.error_raw);
    setLoading(false);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collab]);

  function idOf(row: Record<string, unknown>) {
    return String(row.REQUEST_ID ?? row.UPDATE_REQUEST_ID ?? row.ID ?? "");
  }

  return (
    <Card title="Pending update requests">
      <p className="muted" style={{ marginTop: 0 }}>
        Sharing a template into a live collaboration requires the analysis runner and all their data
        providers to approve.
      </p>
      {loading ? <Spinner /> : null}
      {!rows.length && !loading ? <p className="muted">No update requests.</p> : null}

      {rows.map((row) => {
        const id = idOf(row);
        return (
          <details key={id} open>
            <summary>
              <StatusBadge status={String(row.STATUS ?? "PENDING")} /> Request <code>{id}</code>
            </summary>
            <pre>{JSON.stringify(row, null, 2)}</pre>
            <div className="row">
              <div className="field">
                <label>Rejection reason (if rejecting)</label>
                <input
                  value={reasons[id] ?? ""}
                  onChange={(e) => setReasons((p) => ({ ...p, [id]: e.target.value }))}
                />
              </div>
            </div>
            <div className="flex">
              <button
                className="primary"
                onClick={async () => {
                  const r = await approveUpdateRequest(collab, id);
                  r.ok ? onOk(`Approved ${id}`) : onFail(r.error, r.error_raw);
                  load();
                }}
              >
                Approve
              </button>
              <button
                className="danger"
                onClick={async () => {
                  const r = await rejectUpdateRequest(collab, id, reasons[id] || "No reason given.");
                  r.ok ? onOk(`Rejected ${id}`) : onFail(r.error, r.error_raw);
                  load();
                }}
              >
                Reject
              </button>
            </div>
          </details>
        );
      })}
    </Card>
  );
}

// ---------------------------------------------------------------------------

function TemplatesTab({ collab, onOk, onFail }: TabProps) {
  const [templateId, setTemplateId] = useState("");
  const [runners, setRunners] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Card title="Share a template with runners">
      <Alert kind="info">
        Not needed for standard audience overlap — both standard templates are declared when the
        collaboration is created. This exists because it is the only way to add a template to a{" "}
        <em>live</em> collaboration.
      </Alert>
      <div className="row">
        <div className="field">
          <label>Template ID</label>
          <input value={templateId} onChange={(e) => setTemplateId(e.target.value)}
                 placeholder="standard_audience_overlap_v0" />
        </div>
        <div className="field">
          <label>Runner aliases (comma-separated)</label>
          <input value={runners} onChange={(e) => setRunners(e.target.value)} placeholder="CONSUMER" />
        </div>
      </div>
      <button
        className="primary"
        disabled={busy || !collab || !templateId || !runners}
        onClick={async () => {
          setBusy(true);
          const list = runners.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
          const r = await addTemplate(collab, templateId, list);
          r.ok ? onOk("Request submitted — all affected parties must approve.") : onFail(r.error, r.error_raw);
          setBusy(false);
        }}
      >
        {busy ? "Submitting…" : "Submit template request"}
      </button>
    </Card>
  );
}

// ---------------------------------------------------------------------------

function LifecycleTab({
  collab,
  summary,
  onOk,
  onFail,
}: TabProps & { summary: CollaborationSummary | undefined }) {
  const [busy, setBusy] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const isOwner = Boolean(summary?.is_owner);
  const mode: "teardown" | "leave" = isOwner ? "teardown" : "leave";

  return (
    <Card title={isOwner ? "Teardown (you are the owner)" : "Leave (you are a collaborator)"}>
      {isOwner ? (
        <Alert kind="err" title="This removes the collaboration for everyone">
          Teardown is irreversible and affects <strong>all</strong> participants, not just you.
        </Alert>
      ) : (
        <Alert kind="warn" title="You cannot rejoin after leaving">
          Leaving releases your data offerings from this collaboration. Rejoining is not possible.
        </Alert>
      )}

      <p className="muted">
        Both operations are asynchronous and must be called twice in the raw API — call, wait for{" "}
        <code>LOCAL_DROP_PENDING</code>, call again. The console handles that for you.
      </p>

      <div className="field" style={{ maxWidth: 340 }}>
        <label>Type the collaboration name to confirm</label>
        <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder={collab} />
      </div>

      <button
        className="danger"
        disabled={busy || !collab || confirmText !== collab}
        onClick={async () => {
          setBusy(true);
          const r = await teardownOrLeave(collab, mode);
          r.ok
            ? onOk(`${mode} complete (two-call protocol completed: ${r.data.two_call_completed}).`)
            : onFail(r.error, r.error_raw);
          setBusy(false);
        }}
      >
        {busy ? "Working…" : isOwner ? "Teardown collaboration" : "Leave collaboration"}
      </button>
    </Card>
  );
}

// ---------------------------------------------------------------------------

function RbacTab({ onOk, onFail }: Pick<TabProps, "onOk" | "onFail">) {
  const [me, setMe] = useState<AppRoleData | null>(null);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("ANALYST");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAppRole().then((r) => {
      if (r.ok) setMe(r.data);
    });
  }, []);

  return (
    <>
      <Card title="Your app permissions">
        {me ? (
          <div className="table-wrap">
            <table>
              <tbody>
                <tr><th>User</th><td className="mono">{me.username}</td></tr>
                <tr><th>App role</th><td><StatusBadge status={me.app_role} /></td></tr>
                <tr><th>Run overlap</th><td>{me.can_run_overlap ? "yes" : "no"}</td></tr>
                <tr><th>Activate</th><td>{me.can_activate ? "yes" : "no"}</td></tr>
                <tr><th>Build / teardown</th><td>{me.can_build ? "yes" : "no"}</td></tr>
              </tbody>
            </table>
          </div>
        ) : <Spinner />}
      </Card>

      <Card title="Assign an app role">
        <Alert kind="info">
          App roles only narrow what the UI offers. DCR&apos;s own privileges remain the authority —
          a user talking to the API directly is still constrained by DCR.
        </Alert>
        <div className="row">
          <div className="field">
            <label>Username</label>
            <input value={username} onChange={(e) => setUsername(e.target.value.toUpperCase())} />
          </div>
          <div className="field">
            <label>App role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="VIEWER">VIEWER — dashboards and history</option>
              <option value="ANALYST">ANALYST — + run overlap</option>
              <option value="ACTIVATOR">ACTIVATOR — + activate and import</option>
              <option value="BUILDER">BUILDER — + register, create, teardown</option>
            </select>
          </div>
        </div>
        <button
          className="primary"
          disabled={busy || !username}
          onClick={async () => {
            setBusy(true);
            const r = await setAppRole(username, role);
            r.ok ? onOk(`${username} is now ${role}.`) : onFail(r.error, r.error_raw);
            setBusy(false);
          }}
        >
          {busy ? "Assigning…" : "Assign role"}
        </button>
      </Card>
    </>
  );
}
