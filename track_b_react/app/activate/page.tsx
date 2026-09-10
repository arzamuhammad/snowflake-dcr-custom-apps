"use client";

/**
 * Activate.
 *
 * Column selection is the privacy control that matters here, so it is enforced
 * three times over: this page only offers columns the data owner marked
 * activation_allowed, the facade re-checks the request against the live
 * ACTIVATION_ALLOWED_COLUMNS, and DCR's own activation_policy filter is the final
 * gate. A caller bypassing this UI still cannot exfiltrate a withheld column.
 */

import { useEffect, useState } from "react";

import { preflight, runActivation } from "@/lib/facade";
import type { ActivationConfig, ActivationData, DcrError, PreflightData } from "@/lib/types";

import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Alert, Card, ErrorPanel, PageHeader, Spinner } from "@/components/ui";

const SEGMENT_OK = /^[A-Za-z0-9_-]+$/;

export default function ActivatePage() {
  const [collab, setCollab] = useState("");
  const [pf, setPf] = useState<PreflightData | null>(null);
  const [loading, setLoading] = useState(false);

  const [source, setSource] = useState("");
  const [mine, setMine] = useState("");
  const [keyP, setKeyP] = useState("");
  const [keyC, setKeyC] = useState("");
  const [partnerCols, setPartnerCols] = useState<string[]>([]);
  const [myCols, setMyCols] = useState<string[]>([]);
  const [destination, setDestination] = useState("");
  const [segment, setSegment] = useState("");
  const [where, setWhere] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<DcrError | null>(null);
  const [errorRaw, setErrorRaw] = useState<string | undefined>();
  const [done, setDone] = useState<ActivationData | null>(null);

  useEffect(() => {
    setPf(null);
    setDone(null);
    if (!collab) return;
    setLoading(true);
    preflight(collab).then((r) => {
      if (r.ok) {
        setPf(r.data);
        const d = r.data.detail;
        if (d) {
          setSource(d.partner_offerings[0]?.view_name ?? "");
          setMine(d.my_offerings[0]?.view_name ?? "");
          // Default to everything permitted — the user then removes what they
          // want to withhold, which is a more natural review than opting in.
          setPartnerCols(Array.from(new Set(d.partner_offerings.flatMap((o) => o.activation_columns))));
          setMyCols(Array.from(new Set(d.my_offerings.flatMap((o) => o.activation_columns))));
        }
        const k = r.data.common_join_keys[0] ?? "";
        setKeyP(k);
        setKeyC(k);
      } else {
        setError(r.error);
        setErrorRaw(r.error_raw);
      }
      setLoading(false);
    });
  }, [collab]);

  const detail = pf?.detail;
  const allPartner = detail
    ? Array.from(new Set(detail.partner_offerings.flatMap((o) => o.activation_columns)))
    : [];
  const allMine = detail
    ? Array.from(new Set(detail.my_offerings.flatMap((o) => o.activation_columns)))
    : [];

  const activationColumns = [
    ...partnerCols.map((c) => `p1.${c}`),
    ...myCols.map((c) => `c1.${c}`),
  ];

  const segmentValid = !segment || SEGMENT_OK.test(segment);

  async function submit() {
    setBusy(true);
    setError(null);
    setDone(null);
    const config: ActivationConfig = {
      source_tables: [source],
      my_tables: [mine],
      match_levels: [[{ provider: keyP, consumer: keyC }]],
      activation_columns: activationColumns,
      destination,
      segment_name: segment,
    };
    if (where) config.where_clause = where;

    const r = await runActivation(collab, config);
    if (r.ok) setDone(r.data);
    else {
      setError(r.error);
      setErrorRaw(r.error_raw);
    }
    setBusy(false);
  }

  return (
    <>
      <PageHeader title="Activate" sub="Send the matched audience to a collaborator." />

      <CollaborationPicker value={collab} onChange={(n) => setCollab(n)} />

      {loading ? <Spinner label="Checking what is permitted…" /> : null}
      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}

      {pf && !pf.can_activate ? (
        <Alert kind="err" title="Activation is not available">
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {pf.blockers.map((b) => <li key={b}>{b}</li>)}
            {pf.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
          <p className="hint" style={{ marginBottom: 0 }}>
            Activation also requires Enterprise Edition or above.
          </p>
        </Alert>
      ) : null}

      {pf?.can_activate && detail ? (
        <>
          <Card title="Sources and match key">
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
            <div className="row">
              <div className="field">
                <label>Partner key</label>
                <select value={keyP} onChange={(e) => setKeyP(e.target.value)}>
                  {pf.common_join_keys.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Your key</label>
                <select value={keyC} onChange={(e) => setKeyC(e.target.value)}>
                  {pf.common_join_keys.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
            </div>
          </Card>

          <Card title="Columns to activate">
            <Alert kind="warn" title="This data leaves your account">
              Only columns the owner marked as activation-allowed appear here. Uncheck anything you
              want to withhold. Once activated, the data is in the recipient&apos;s account and
              cannot be recalled.
            </Alert>

            <div className="row">
              <div>
                <label>Partner columns ({partnerCols.length}/{allPartner.length})</label>
                {allPartner.length ? allPartner.map((c) => (
                  <label className="checkbox-row" key={c}>
                    <input
                      type="checkbox"
                      checked={partnerCols.includes(c)}
                      onChange={(e) =>
                        setPartnerCols((p) => e.target.checked ? [...p, c] : p.filter((x) => x !== c))
                      }
                    />
                    <code>{c}</code>
                  </label>
                )) : <p className="muted">None permitted.</p>}
              </div>
              <div>
                <label>Your columns ({myCols.length}/{allMine.length})</label>
                {allMine.length ? allMine.map((c) => (
                  <label className="checkbox-row" key={c}>
                    <input
                      type="checkbox"
                      checked={myCols.includes(c)}
                      onChange={(e) =>
                        setMyCols((p) => e.target.checked ? [...p, c] : p.filter((x) => x !== c))
                      }
                    />
                    <code>{c}</code>
                  </label>
                )) : <p className="muted">None permitted.</p>}
              </div>
            </div>
          </Card>

          <Card title="Destination and segment">
            <div className="row">
              <div className="field">
                <label>Send results to</label>
                <select value={destination} onChange={(e) => setDestination(e.target.value)}>
                  <option value="">Select…</option>
                  {/* Aliases are collaboration-scoped; the facade rejects anything
                      not declared as an activation destination at creation time. */}
                  {["PROVIDER", "CONSUMER", "PARTNER"].map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
                <div className="hint">
                  Must be an alias declared as an activation destination when the collaboration was
                  created.
                </div>
              </div>
              <div className="field">
                <label>Segment name</label>
                <input value={segment} onChange={(e) => setSegment(e.target.value)}
                       placeholder="q3_high_value_overlap" />
                {!segmentValid ? (
                  <div className="hint" style={{ color: "var(--err)" }}>
                    Letters, digits, underscores and hyphens only — spaces are rejected by the API.
                  </div>
                ) : null}
              </div>
            </div>
            <div className="field">
              <label>Filter (optional)</label>
              <input value={where} onChange={(e) => setWhere(e.target.value)}
                     placeholder="p1.REGION = 'JKT'" />
            </div>
          </Card>

          <Card>
            <label className="checkbox-row">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              I confirm {activationColumns.length} column(s) may be sent to <strong>{destination || "…"}</strong>
            </label>
            <button
              className="primary"
              style={{ marginTop: 12 }}
              onClick={submit}
              disabled={busy || !confirmed || !segment || !segmentValid || !destination || !activationColumns.length}
            >
              {busy ? "Activating…" : "Activate"}
            </button>
            {busy ? <div style={{ marginTop: 10 }}><Spinner label="Building and delivering the segment…" /></div> : null}
          </Card>
        </>
      ) : null}

      {done ? (
        <Alert kind="ok" title="Activation complete">
          <p style={{ marginTop: 0 }}>
            Segment <code>{done.segment_name}</code> sent to <code>{done.destination}</code>.
            {done.batch_id ? <> Batch <code>{done.batch_id}</code>.</> : null}
          </p>
          <p style={{ marginBottom: 0 }}>
            <strong>Not finished yet.</strong> The recipient must import the segment on the{" "}
            <strong>Activation Inbox</strong> page. Until then the payload sits as a VARIANT column
            inside a share and no one can use it.
          </p>
        </Alert>
      ) : null}
    </>
  );
}
