"use client";

/**
 * Shared presentational pieces. Kept deliberately small: these exist to make the
 * facade's error contract and DCR's status vocabulary render consistently on
 * every page, not to build a component library.
 */

import type { DcrError, FacadeResult, HealthCheckItem } from "@/lib/types";

// ---------------------------------------------------------------------------

export function PageHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <>
      <h1 className="page-title">{title}</h1>
      {sub ? <p className="page-sub">{sub}</p> : null}
    </>
  );
}

export function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="card">
      {title ? <h3>{title}</h3> : null}
      {children}
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------

const STATUS_CLASS: Record<string, string> = {
  JOINED: "ok", READY: "ok", SUCCESS: "ok", COMPLETED: "ok", OK: "ok",
  CREATED: "info", CREATING: "info", JOINING: "info", IMPORTING: "info", INFO: "info",
  INVITED: "warn", PENDING: "warn", LOCAL_DROP_PENDING: "warn", WARN: "warn",
  FAILED: "err", FAIL: "err", BLOCKED: "err", ERROR: "err",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = String(status ?? "unknown").toUpperCase();
  return <span className={`badge ${STATUS_CLASS[s] ?? "muted"}`}>{s}</span>;
}

// ---------------------------------------------------------------------------

/**
 * Render a facade error.
 *
 * Every decoded error carries a remediation, and some carry a ready-to-run
 * `sql_fix` derived from the identifiers DCR itself named — that is what makes a
 * missing REFERENCE_USAGE grant a copy-paste fix instead of a research task.
 */
export function ErrorPanel({ error, raw }: { error: DcrError; raw?: string }) {
  const cls = error.severity === "warning" ? "warn" : "err";
  return (
    <div className={`alert ${cls}`}>
      <div className="alert-title">{error.title}</div>
      <div>{error.cause}</div>
      {error.remediation ? <div style={{ marginTop: 8 }}>{error.remediation}</div> : null}
      {error.sql_fix ? (
        <>
          <div style={{ marginTop: 8, fontSize: 12, fontWeight: 500 }}>Run this to fix it:</div>
          <pre>{error.sql_fix}</pre>
        </>
      ) : null}
      {raw ? (
        <details style={{ marginTop: 10, background: "transparent" }}>
          <summary>Raw error</summary>
          <pre>{raw}</pre>
        </details>
      ) : null}
    </div>
  );
}

/** Render whichever half of the result envelope is populated. */
export function ResultPanel<T>({
  result,
  children,
}: {
  result: FacadeResult<T> | null;
  children?: (data: T) => React.ReactNode;
}) {
  if (!result) return null;
  if (!result.ok) return <ErrorPanel error={result.error} raw={result.error_raw} />;
  return <>{children ? children(result.data) : null}</>;
}

// ---------------------------------------------------------------------------

export function Alert({
  kind,
  title,
  children,
}: {
  kind: "ok" | "warn" | "err" | "info";
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`alert ${kind}`}>
      {title ? <div className="alert-title">{title}</div> : null}
      <div>{children}</div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="flex">
      <span className="spinner" />
      {label ? <span className="muted">{label}</span> : null}
    </span>
  );
}

export function Progress({ percent, label }: { percent: number; label?: string }) {
  const p = Math.max(0, Math.min(100, percent));
  return (
    <div>
      <div className="progress">
        <div className="progress-bar" style={{ width: `${p}%` }} />
      </div>
      {label ? <div className="hint">{label}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------

const CHECK_ICON: Record<string, string> = { ok: "✓", fail: "✗", warn: "!", info: "i" };
const CHECK_CLASS: Record<string, string> = { ok: "ok", fail: "err", warn: "warn", info: "info" };

export function HealthCheckList({ checks }: { checks: HealthCheckItem[] }) {
  return (
    <div>
      {checks.map((c) => (
        <div key={c.name} style={{ padding: "9px 0", borderBottom: "1px solid var(--border)" }}>
          <div className="flex">
            <span className={`badge ${CHECK_CLASS[c.status] ?? "muted"}`}>
              {CHECK_ICON[c.status] ?? "?"}
            </span>
            <strong style={{ fontSize: 13 }}>{c.name}</strong>
            {!c.blocking && c.status !== "ok" ? (
              <span className="badge muted">non-blocking</span>
            ) : null}
          </div>
          <div className="hint" style={{ marginLeft: 30 }}>{c.detail}</div>
          {c.fix ? (
            <details style={{ marginLeft: 30, marginTop: 6 }}>
              <summary>How to fix</summary>
              <pre>{c.fix}</pre>
            </details>
          ) : null}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------

/** Simple auto-columned table for arbitrary row shapes returned by DCR. */
export function DataTable({ rows, max = 100 }: { rows: Record<string, unknown>[]; max?: number }) {
  if (!rows?.length) return <p className="muted">No rows.</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, max).map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c} className={typeof r[c] === "number" ? "right mono" : undefined}>
                  {r[c] === null || r[c] === undefined
                    ? <span className="muted">—</span>
                    : typeof r[c] === "object"
                      ? JSON.stringify(r[c])
                      : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > max ? <p className="hint">Showing {max} of {rows.length} rows.</p> : null}
    </div>
  );
}

export const fmt = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n.toLocaleString();

export const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(2)}%`;
