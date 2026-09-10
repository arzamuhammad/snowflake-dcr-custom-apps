"use client";

/**
 * My Data — register a table or view as a data offering.
 *
 * The two things this screen exists to get right:
 *   1. `join_standard` columns are RENAMED in the shared view to their
 *      column_type, so the exposed name is previewed live and reported after
 *      registration. Using the source name in a join clause is the number one
 *      cause of "unauthorized column".
 *   2. `activation_allowed` defaults to FALSE for every column. Activating a PII
 *      column cannot be undone once the data leaves the account, so the safe
 *      option is the default and the user opts in explicitly.
 */

import { useEffect, useState } from "react";

import {
  describeColumns,
  listDataObjects,
  listOfferings,
  registerOffering,
  unregisterOffering,
} from "@/lib/facade";
import type {
  ColumnInfo,
  DataObjectItem,
  RegisterOfferingData,
  ResolvedColumn,
} from "@/lib/types";

import { Alert, Card, ErrorPanel, PageHeader, Spinner } from "@/components/ui";
import type { DcrError } from "@/lib/types";

type Tab = "register" | "existing";

export default function MyDataPage() {
  const [tab, setTab] = useState<Tab>("register");
  return (
    <>
      <PageHeader
        title="My Data"
        sub="Register tables and views as data offerings so they can be used in a clean room."
      />
      <div className="flex" style={{ marginBottom: 16 }}>
        <button className={tab === "register" ? "primary" : ""} onClick={() => setTab("register")}>
          Register new offering
        </button>
        <button className={tab === "existing" ? "primary" : ""} onClick={() => setTab("existing")}>
          Existing offerings
        </button>
      </div>
      {tab === "register" ? <RegisterTab /> : <ExistingTab />}
    </>
  );
}

// ---------------------------------------------------------------------------

function RegisterTab() {
  const [databases, setDatabases] = useState<string[]>([]);
  const [schemas, setSchemas] = useState<string[]>([]);
  const [objects, setObjects] = useState<DataObjectItem[]>([]);
  const [db, setDb] = useState("");
  const [schema, setSchema] = useState("");
  const [fqn, setFqn] = useState("");

  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [columnTypes, setColumnTypes] = useState<string[]>([]);
  const [loadingCols, setLoadingCols] = useState(false);

  const [name, setName] = useState("");
  const [version, setVersion] = useState("v1_0");
  const [description, setDescription] = useState("");
  const [alias, setAlias] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [done, setDone] = useState<RegisterOfferingData | null>(null);

  useEffect(() => {
    listDataObjects().then((r) => {
      if (r.ok) setDatabases(r.data.items as string[]);
    });
  }, []);

  useEffect(() => {
    setSchema("");
    setObjects([]);
    setFqn("");
    if (!db) return setSchemas([]);
    listDataObjects(db).then((r) => {
      if (r.ok) setSchemas(r.data.items as string[]);
    });
  }, [db]);

  useEffect(() => {
    setFqn("");
    if (!db || !schema) return setObjects([]);
    listDataObjects(db, schema).then((r) => {
      if (r.ok) setObjects(r.data.items as DataObjectItem[]);
    });
  }, [db, schema]);

  useEffect(() => {
    setColumns([]);
    setDone(null);
    if (!fqn) return;
    setLoadingCols(true);
    describeColumns(fqn).then((r) => {
      if (r.ok) {
        setColumns(r.data.columns);
        setCategories(r.data.categories);
        setColumnTypes(r.data.column_types);
        const leaf = fqn.split(".").pop() ?? "";
        setAlias(leaf.toLowerCase());
      } else {
        setError(r.error);
        setErrorRaw(r.error_raw);
      }
      setLoadingCols(false);
    });
  }, [fqn]);

  function updateColumn(i: number, patch: Partial<ColumnInfo>) {
    setColumns((prev) => prev.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  }

  const joinKeys = columns.filter(
    (c) => c.category === "join_standard" || c.category === "join_custom",
  );

  async function submit() {
    setBusy(true);
    setError(null);
    setDone(null);
    const r = await registerOffering({
      name,
      version,
      description,
      datasets: [
        {
          alias,
          data_object_fqn: fqn,
          columns: columns.map((c) => ({
            name: c.name,
            category: c.category,
            column_type: c.category === "join_standard" ? c.column_type : null,
            activation_allowed: c.activation_allowed,
          })),
        },
      ],
    });
    if (r.ok) setDone(r.data);
    else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setBusy(false);
  }

  return (
    <>
      <Card title="1. Pick a table or view">
        <div className="row">
          <div className="field">
            <label>Database</label>
            <select value={db} onChange={(e) => setDb(e.target.value)}>
              <option value="">Select…</option>
              {databases.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Schema</label>
            <select value={schema} onChange={(e) => setSchema(e.target.value)} disabled={!db}>
              <option value="">Select…</option>
              {schemas.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Table or view</label>
            <select value={fqn} onChange={(e) => setFqn(e.target.value)} disabled={!schema}>
              <option value="">Select…</option>
              {objects.map((o) => (
                <option key={o.fqn} value={o.fqn}>
                  {o.name}{o.row_count != null ? ` — ${o.row_count.toLocaleString()} rows` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {loadingCols ? <Spinner label="Reading columns…" /> : null}

      {columns.length ? (
        <Card title="2. Configure columns">
          <Alert kind="info">
            Every column starts as <code>passthrough</code> with activation{" "}
            <strong>not</strong> allowed. That is deliberate — opt in only to what may leave your
            account. A <code>join_standard</code> column is <strong>renamed</strong> in the shared
            view to its column type.
          </Alert>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Type</th>
                  <th style={{ minWidth: 150 }}>Category</th>
                  <th style={{ minWidth: 190 }}>Column type (PII)</th>
                  <th>Exposed as</th>
                  <th>Activation</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((c, i) => {
                  const exposed =
                    c.category === "join_standard"
                      ? (c.column_type ?? "").toUpperCase() || "—"
                      : c.category === "timestamp"
                        ? "TIMESTAMP"
                        : c.name.toUpperCase();
                  return (
                    <tr key={c.name}>
                      <td><strong>{c.name}</strong></td>
                      <td className="muted mono">{c.data_type}</td>
                      <td>
                        <select
                          value={c.category}
                          onChange={(e) => {
                            const category = e.target.value;
                            updateColumn(i, {
                              category,
                              column_type:
                                category === "join_standard"
                                  ? c.column_type ?? c.suggested_column_type ?? columnTypes[0]
                                  : null,
                            });
                          }}
                        >
                          {categories.map((k) => <option key={k} value={k}>{k}</option>)}
                        </select>
                      </td>
                      <td>
                        {c.category === "join_standard" ? (
                          <select
                            value={c.column_type ?? ""}
                            onChange={(e) => updateColumn(i, { column_type: e.target.value })}
                          >
                            {columnTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                          </select>
                        ) : (
                          <span className="muted">n/a</span>
                        )}
                      </td>
                      <td className="mono">
                        {exposed !== c.name.toUpperCase() ? (
                          <span className="badge warn">{exposed}</span>
                        ) : (
                          <span className="muted">{exposed}</span>
                        )}
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={c.activation_allowed}
                          onChange={(e) => updateColumn(i, { activation_allowed: e.target.checked })}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {!joinKeys.length ? (
            <Alert kind="warn" title="No join key configured">
              Audience overlap needs at least one column with category{" "}
              <code>join_standard</code> (PII identifier) or <code>join_custom</code>.
            </Alert>
          ) : null}
        </Card>
      ) : null}

      {columns.length ? (
        <Card title="3. Name and register">
          <div className="row">
            <div className="field">
              <label>Offering name</label>
              <input value={name} onChange={(e) => setName(e.target.value)}
                     placeholder="telco_provider_offering" />
            </div>
            <div className="field">
              <label>Version</label>
              <input value={version} onChange={(e) => setVersion(e.target.value)} />
              <div className="hint">Offering ID becomes <code>{name || "<name>"}_{version}</code></div>
            </div>
            <div className="field">
              <label>Dataset alias</label>
              <input value={alias} onChange={(e) => setAlias(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label>Description (optional)</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <button className="primary" onClick={submit}
                  disabled={busy || !name || !alias || !joinKeys.length}>
            {busy ? "Registering…" : "Register offering"}
          </button>
          <div className="hint" style={{ marginTop: 8 }}>
            Re-registering the same name and version overwrites the previous definition.
          </div>
        </Card>
      ) : null}

      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}

      {done ? (
        <Alert kind="ok" title={`Registered: ${done.offering_id}`}>
          {done.datasets.flatMap((ds) =>
            ds.columns.filter((c: ResolvedColumn) => c.is_join_key),
          ).map((c: ResolvedColumn) => (
            <div key={c.name}>
              Join column <code>{c.name}</code> is exposed to partners as{" "}
              <strong><code>{c.exposed_name}</code></strong> — use that name in join clauses.
            </div>
          ))}
        </Alert>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------

function ExistingTab() {
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    const r = await listOfferings();
    if (r.ok) setRows(r.data.offerings);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function remove(id: string) {
    const r = await unregisterOffering(id);
    setMsg(r.ok ? `Unregistered ${id}` : r.error.cause);
    await load();
  }

  if (loading) return <Spinner label="Loading offerings…" />;
  if (!rows.length) return <Alert kind="info">No offerings registered yet.</Alert>;

  return (
    <>
      {msg ? <Alert kind="info">{msg}</Alert> : null}
      {rows.map((o) => (
        <details key={o.DATA_OFFERING_ID}>
          <summary>
            <strong>{o.DATA_OFFERING_ID}</strong>{" "}
            <span className="muted">— {String(o.CREATED_ON ?? "").slice(0, 19)}</span>
          </summary>
          <pre>{o.DATA_OFFERING_SPEC}</pre>
          <button className="danger" onClick={() => remove(o.DATA_OFFERING_ID)}>
            Unregister
          </button>
        </details>
      ))}
    </>
  );
}
