"use client";

import { useEffect, useState } from "react";

import { healthCheck, registerStandardTemplates } from "@/lib/facade";
import type { FacadeResult, HealthCheckData } from "@/lib/types";

import {
  Alert,
  Card,
  ErrorPanel,
  HealthCheckList,
  PageHeader,
  Spinner,
} from "@/components/ui";

export default function HealthPage() {
  const [result, setResult] = useState<FacadeResult<HealthCheckData> | null>(null);
  const [loading, setLoading] = useState(true);
  const [fixing, setFixing] = useState(false);
  const [fixMsg, setFixMsg] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setResult(await healthCheck());
    setLoading(false);
  }

  useEffect(() => {
    run();
  }, []);

  async function registerTemplates() {
    setFixing(true);
    setFixMsg(null);
    const r = await registerStandardTemplates();
    setFixMsg(
      r.ok
        ? `Registered: ${r.data.templates.join(", ")}`
        : `Failed: ${r.error.cause}`,
    );
    setFixing(false);
    await run();
  }

  const templatesMissing =
    result?.ok &&
    result.data.checks.some(
      (c) => c.name === "Standard overlap templates" && c.status === "fail",
    );

  return (
    <>
      <PageHeader
        title="Health Check"
        sub="Verify prerequisites before using the console. Run this in every participating account."
      />

      <div className="flex" style={{ marginBottom: 16 }}>
        <button className="primary" onClick={run} disabled={loading}>
          {loading ? "Checking…" : "Re-run health check"}
        </button>
        {loading ? <Spinner /> : null}
      </div>

      {result && !result.ok ? <ErrorPanel error={result.error} raw={result.error_raw} /> : null}

      {result?.ok ? (
        <>
          {result.data.ready ? (
            <Alert kind="ok" title="Ready">
              All blocking prerequisites are met.
            </Alert>
          ) : (
            <Alert kind="err" title="Blocking issues">
              {result.data.blocking_failures.join(", ")}
            </Alert>
          )}

          {templatesMissing ? (
            <Alert kind="warn" title="Standard templates are not registered">
              <p style={{ marginTop: 0 }}>
                <code>standard_audience_overlap_v0</code> and{" "}
                <code>standard_audience_overlap_activation_v0</code> are <strong>not</strong>{" "}
                installed automatically with Data Clean Rooms. They must be registered once per
                account, in every participating account.
              </p>
              <button className="primary" onClick={registerTemplates} disabled={fixing}>
                {fixing ? "Registering…" : "Register standard templates"}
              </button>
              {fixMsg ? <div className="hint" style={{ marginTop: 8 }}>{fixMsg}</div> : null}
            </Alert>
          ) : null}

          <Card title="Checks">
            <HealthCheckList checks={result.data.checks} />
          </Card>

          <Card title="About the 'DCR privileges' item">
            <p style={{ marginTop: 0 }}>
              This one reports <span className="badge info">i</span> rather than a pass, and that is
              expected. DCR&apos;s own <code>ADMIN.CHECK_PRIVILEGES</code> procedure issues a{" "}
              <code>USE</code> statement internally, and Snowflake rejects that inside a nested
              stored procedure. The read privileges are proven by the other checks succeeding.
            </p>
            <p className="hint">To verify explicitly, run this in a worksheet:</p>
            <pre>{`USE ROLE DCR_CONSOLE_ROLE;
CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.CHECK_PRIVILEGES(
  ['CREATE COLLABORATION','JOIN COLLABORATION','REVIEW COLLABORATION',
   'VIEW COLLABORATIONS','REGISTER DATA OFFERING','REGISTER TEMPLATE']);`}</pre>
          </Card>
        </>
      ) : null}
    </>
  );
}
