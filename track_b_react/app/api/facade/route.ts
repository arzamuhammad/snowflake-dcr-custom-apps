/**
 * POST /api/facade — proxy to DCR_CONSOLE.APP.INVOKE.
 *
 * Runs with owner's rights so business users never need DCR privileges. The
 * caller's identity is passed to the facade as `ui_track` metadata for the audit
 * trail; authority still rests entirely with DCR's own privilege model.
 *
 * The operation name is NOT validated here on purpose: the facade holds an
 * explicit whitelist and returns UNKNOWN_OPERATION for anything outside it, so
 * there is one authoritative list rather than two that can drift apart.
 */

import { NextResponse } from "next/server";

import { querySnowflake } from "@/lib/snowflake";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Body {
  operation?: string;
  payload?: Record<string, unknown>;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        ok: false,
        operation: "UNKNOWN",
        error: {
          code: "INVALID_REQUEST",
          title: "Request body is not valid JSON",
          cause: "The request could not be parsed.",
          remediation: "This is a client bug; reload the page.",
          sql_fix: null,
          retryable: false,
          severity: "error",
        },
        duration_ms: 0,
      },
      { status: 400 },
    );
  }

  const operation = String(body.operation ?? "").trim();
  if (!operation) {
    return NextResponse.json(
      {
        ok: false,
        operation: "UNKNOWN",
        error: {
          code: "MISSING_OPERATION",
          title: "No operation specified",
          cause: "The request did not name a facade operation.",
          remediation: "Include an `operation` field.",
          sql_fix: null,
          retryable: false,
          severity: "error",
        },
        duration_ms: 0,
      },
      { status: 400 },
    );
  }

  // Strip undefined so optional arguments are genuinely absent rather than null:
  // the facade treats null as "supplied but empty" for required-argument checks.
  const payload: Record<string, unknown> = { ui_track: "react" };
  for (const [k, v] of Object.entries(body.payload ?? {})) {
    if (v !== undefined) payload[k] = v;
  }

  try {
    const rows = await querySnowflake(
      "CALL DCR_CONSOLE.APP.INVOKE(?, PARSE_JSON(?))",
      { binds: [operation, JSON.stringify(payload)] },
    );

    const raw = rows.length ? Object.values(rows[0])[0] : null;
    const result = typeof raw === "string" ? JSON.parse(raw) : raw;

    return NextResponse.json(result ?? { ok: false, operation, error: null });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return NextResponse.json(
      {
        ok: false,
        operation,
        error: {
          code: "FACADE_CALL_FAILED",
          title: "The facade procedure could not be called",
          cause: message,
          remediation:
            "Confirm DCR_CONSOLE.APP.INVOKE exists and the service role has USAGE on it. " +
            "Run: CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL);",
          sql_fix: null,
          retryable: true,
          severity: "blocked",
        },
        error_raw: message,
        duration_ms: 0,
      },
      { status: 200 },
    );
  }
}
