"use client";

/**
 * Run Overlap.
 *
 * Preflight runs first so a user is told exactly why an overlap cannot run,
 * instead of filling in a whole form and then reading a DCR traceback.
 *
 * On progress: COLLABORATION.RUN is synchronous and blocking. There is no
 * progress callback and no percentage available, so this shows an honest phase
 * indicator and an elapsed timer rather than a fabricated percentage.
 */

import { useEffect, useRef, useState } from "react";
import {
  Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { preflight, runOverlap } from "@/lib/facade";
import type { DcrError, MatchLevels, OverlapConfig, OverlapData, PreflightData } from "@/lib/types";

import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Alert, Card, ErrorPanel, DataTable, Metric, PageHeader, Spinner, fmt, pct } from "@/components/ui";

interface Level {
  keys: { provider: string; consumer: string }[];
}

export default function AnalyzePage() {
  const [collab, setCollab] = useState("");
  const [pf, setPf] = useState<PreflightData | null>(null);
  const [pfLoading, setPfLoading] = useState(false);

  const [source, setSource] = useState("");
  const [mine, setMine] = useState("");
  const [levels, setLevels] = useState<Level[]>([{ keys: [{ provider: "", consumer: "" }] }]);
  const [sourceWhere, setSourceWhere] = useState("");
  const [myWhere, setMyWhere] = useState("");
  const [sourceGroup, setSourceGroup] = useState<string[]>([]);
  const [myGroup, setMyGroup] = useState<string[]>([]);
  const [useCache, setUseCache] = useState(true);

  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [data, setData] = useState<OverlapData | null>(null);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setPf(null);
    setData(null);
    if (!collab) return;
    setPfLoading(true);
    preflight(collab).then((r) => {
      if (r.ok) {
        setPf(r.data);
        const d = r.data.detail;
        if (d) {
          setSource(d.partner_offerings[0]?.view_name ?? "");
          setMine(d.my_offerings[0]?.view_name ?? "");
        }
        const k = r.data.common_join_keys[0] ?? "";
        if (k) setLevels([{ keys: [{ provider: k, consumer: k }] }]);
      } else {
        setError(r.error);
        setErrorRaw(r.error_raw);
      }
      setPfLoading(false);
    });
  }, [collab]);

  function buildConfig(): OverlapConfig {
    const match_levels: MatchLevels = levels
      .map((l) => l.keys.filter((k) => k.provider && k.consumer))
      .filter((l) => l.length > 0);
    const cfg: OverlapConfig = { source_tables: [source], my_tables: [mine], match_levels };
    if (sourceWhere) cfg.source_where_clause = sourceWhere;
    if (myWhere) cfg.my_where_clause = myWhere;
    if (sourceGroup.length) cfg.source_group_by = sourceGroup;
    if (myGroup.length) cfg.my_group_by = myGroup;
    return cfg;
  }

  async function run() {
    setRunning(true);
    setError(null);
    setData(null);
    setElapsed(0);
    timer.current = setInterval(() => setElapsed((e) => e + 1), 1000);

    const r = await runOverlap(collab, buildConfig(), useCache);

    if (timer.current) clearInterval(timer.current);
    if (r.ok) setData(r.data);
    else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setRunning(false);
  }

  const detail = pf?.detail;
  const commonKeys = pf?.common_join_keys ?? [];
  const analysisCols = detail
    ? Array.from(new Set(detail.partner_offerings.flatMap((o) => o.analysis_columns)))
    : [];
  const myAnalysisCols = detail
    ? Array.from(new Set(detail.my_offerings.flatMap((o) => o.analysis_columns)))
    : [];

  return (
    <>
      <PageHeader title="Run Overlap" sub="Measure how much of your audience your partner also has." />

      <CollaborationPicker value={collab} onChange={(n) => setCollab(n)} />

      {pfLoading ? <Spinner label="Running preflight…" /> : null}
      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}

      {pf && !pf.can_run_overlap ? (
        <Alert kind="err" title="Overlap cannot run yet">
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {pf.blockers.map((b) => <li key={b}>{b}</li>)}
          </ul>
        </Alert>
      ) : null}

      {pf?.warnings?.length ? (
        <Alert kind="warn" title="Worth knowing">
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {pf.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </Alert>
      ) : null}

      {pf?.can_run_overlap && detail ? (
        <>
          <Card title="Data sources">
            <div className="row">
              <div className="field">
                <label>Partner dataset (p1)</label>
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  {detail.partner_offerings.map((o) => (
                    <option key={o.view_name} value={o.view_name}>{o.view_name}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Your dataset (c1)</label>
                <select value={mine} onChange={(e) => setMine(e.target.value)}>
                  {detail.my_offerings.map((o) => (
                    <option key={o.view_name} value={o.view_name}>{o.view_name}</option>
                  ))}
                </select>
              </div>
            </div>
          </Card>

          <Card title="Match keys (waterfall)">
            <p className="muted" style={{ marginTop: 0 }}>
              Levels are tried in order and the first match wins. Multiple keys inside one level are
              ANDed together. Example: level 1 email, level 2 phone means &quot;match on email first,
              then try phone for the remainder&quot;.
            </p>

            {levels.map((lvl, li) => (
              <div key={li} style={{ borderTop: li ? "1px solid var(--border)" : "none", paddingTop: li ? 12 : 0, marginBottom: 12 }}>
                <label>Level {li + 1}</label>
                {lvl.keys.map((k, ki) => (
                  <div className="row" key={ki}>
                    <div className="field">
                      <label>Partner key</label>
                      <select
                        value={k.provider}
                        onChange={(e) =>
                          setLevels((p) => p.map((l, j) => j === li
                            ? { keys: l.keys.map((x, y) => y === ki ? { ...x, provider: e.target.value } : x) }
                            : l))
                        }
                      >
                        <option value="">Select…</option>
                        {commonKeys.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                    <div className="field">
                      <label>Your key</label>
                      <select
                        value={k.consumer}
                        onChange={(e) =>
                          setLevels((p) => p.map((l, j) => j === li
                            ? { keys: l.keys.map((x, y) => y === ki ? { ...x, consumer: e.target.value } : x) }
                            : l))
                        }
                      >
                        <option value="">Select…</option>
                        {commonKeys.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  </div>
                ))}
                <button
                  onClick={() =>
                    setLevels((p) => p.map((l, j) => j === li
                      ? { keys: [...l.keys, { provider: "", consumer: "" }] } : l))
                  }
                >
                  Add ANDed key to level {li + 1}
                </button>
              </div>
            ))}

            <div className="flex">
              <button onClick={() => setLevels((p) => [...p, { keys: [{ provider: "", consumer: "" }] }])}>
                Add fallback level
              </button>
              {levels.length > 1 ? (
                <button onClick={() => setLevels((p) => p.slice(0, -1))}>Remove last level</button>
              ) : null}
            </div>

            {!commonKeys.length ? (
              <Alert kind="err" title="No shared join key">
                The two sides expose no key in common. Remember a <code>join_standard</code> column
                is renamed to its column type, so both sides must use the <strong>same</strong>{" "}
                column type.
              </Alert>
            ) : null}
          </Card>

          <Card title="Filters and segmentation (optional)">
            <div className="row">
              <div className="field">
                <label>Partner filter</label>
                <input value={sourceWhere} onChange={(e) => setSourceWhere(e.target.value)}
                       placeholder="p1.REGION = 'JKT'" />
              </div>
              <div className="field">
                <label>Your filter</label>
                <input value={myWhere} onChange={(e) => setMyWhere(e.target.value)}
                       placeholder="c1.SEGMENT = 'GOLD'" />
              </div>
            </div>
            <div className="row">
              <div className="field">
                <label>Partner group-by</label>
                <select multiple size={4} value={sourceGroup}
                        onChange={(e) => setSourceGroup(Array.from(e.target.selectedOptions, (o) => o.value))}>
                  {analysisCols.map((c) => <option key={c} value={`p1.${c}`}>{c}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Your group-by</label>
                <select multiple size={4} value={myGroup}
                        onChange={(e) => setMyGroup(Array.from(e.target.selectedOptions, (o) => o.value))}>
                  {myAnalysisCols.map((c) => <option key={c} value={`c1.${c}`}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="hint">Only columns the data owner permitted for analysis are listed.</div>
          </Card>

          <Card>
            <label className="checkbox-row">
              <input type="checkbox" checked={useCache} onChange={(e) => setUseCache(e.target.checked)} />
              Use a cached result if the configuration is identical
            </label>
            <div className="hint" style={{ marginBottom: 12 }}>
              An overlap is a full scan and a real cost. Uncheck to force a fresh run.
            </div>

            <details style={{ marginBottom: 12 }}>
              <summary>Preview the configuration</summary>
              <pre>{JSON.stringify(buildConfig(), null, 2)}</pre>
            </details>

            <button className="primary" onClick={run} disabled={running || !source || !mine}>
              {running ? "Running…" : "Run overlap analysis"}
            </button>

            {running ? (
              <div style={{ marginTop: 12 }}>
                <div className="flex">
                  <Spinner />
                  <span className="muted">
                    Executing — {elapsed}s elapsed. No percentage is shown because{" "}
                    <code>COLLABORATION.RUN</code> is blocking and exposes no progress.
                  </span>
                </div>
              </div>
            ) : null}
          </Card>
        </>
      ) : null}

      {data ? <OverlapResults data={data} /> : null}
    </>
  );
}

// ---------------------------------------------------------------------------

function OverlapResults({ data }: { data: OverlapData }) {
  const s = data.summary;

  return (
    <>
      {data.from_cache ? (
        <Alert kind="info" title="Served from cache">
          Computed {data.computed_at ?? "earlier"}. Uncheck &quot;Use a cached result&quot; to re-run.
        </Alert>
      ) : null}

      {s?.privacy_suppressed ? (
        <Alert kind="warn" title="Some counts were suppressed">
          Fewer than 5 distinct records matched in at least one bucket, so the clean room returned
          NULL. That is the privacy guarantee working, not a failure. Broaden the audience: add a
          fallback match level, remove a filter, or drop a group-by dimension.
        </Alert>
      ) : null}

      {s ? (
        <>
          <div className="metrics" style={{ marginBottom: 16 }}>
            <Metric label="Matched" value={fmt(s.matched)} />
            <Metric label="Unmatched" value={fmt(s.unmatched)} />
            <Metric label="Your total" value={fmt(s.total)} />
            <Metric label="Match rate" value={pct(s.match_rate)} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Card title="Match rate">
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={[
                      { name: "Matched", value: s.matched },
                      { name: "Unmatched", value: s.unmatched ?? 0 },
                    ]}
                    dataKey="value"
                    innerRadius={58}
                    outerRadius={88}
                    paddingAngle={2}
                  >
                    <Cell fill="#29b5e8" />
                    <Cell fill="#e3e6ea" />
                  </Pie>
                  <Tooltip formatter={(v: number) => v.toLocaleString()} />
                </PieChart>
              </ResponsiveContainer>
              <p className="right muted" style={{ margin: 0 }}>
                {pct(s.match_rate)} of your audience
              </p>
            </Card>

            <Card title="Per-level contribution">
              {data.levels?.length ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={data.levels
                      .filter((l) => l.metric_type === "OVERLAP")
                      .map((l) => ({ name: `L${l.level}`, matched: l.count ?? 0 }))}
                  >
                    <XAxis dataKey="name" fontSize={11} />
                    <YAxis fontSize={11} tickFormatter={(v) => v.toLocaleString()} />
                    <Tooltip formatter={(v: number) => v.toLocaleString()} />
                    <Bar dataKey="matched" fill="#29b5e8" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="muted">No level detail returned.</p>
              )}
            </Card>
          </div>
        </>
      ) : (
        <Alert kind="info" title="Result shape not recognised">
          The template returned columns the console does not know how to summarise, so the raw rows
          are shown untouched below rather than guessing.
        </Alert>
      )}

      <Card title="Waterfall detail">
        <DataTable rows={(data.levels ?? []) as unknown as Record<string, unknown>[]} />
        <p className="hint">
          Only rows with <code>METRIC_TYPE = OVERLAP</code> count towards the match. The result set
          also contains <code>NON_OVERLAP</code> rows and a summary row at waterfall level 999;
          summing everything would exceed the total.
        </p>
      </Card>

      <details>
        <summary>Raw result rows</summary>
        <pre>{JSON.stringify(data.rows, null, 2)}</pre>
      </details>

      <Alert kind="ok" title="Next step">
        Go to <strong>Activate</strong> to send the matched records to a collaborator.
      </Alert>
    </>
  );
}
