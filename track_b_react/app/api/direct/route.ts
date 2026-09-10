/**
 * POST /api/direct — REVIEW + JOIN at session level.
 *
 * WHY THIS ROUTE EXISTS
 * COLLABORATION.JOIN installs the clean room application, which calls
 * SYSTEM$ACCEPT_LEGAL_TERMS. Snowflake rejects side-effecting functions inside a
 * stored procedure:
 *
 *   090237 (42601): Query called from a stored procedure contains a function
 *   with side effects [SYSTEM$ACCEPT_LEGAL_TERMS].
 *
 * So this is the one operation that cannot be wrapped by DCR_CONSOLE.APP.INVOKE.
 * It is issued as a top-level statement instead. Verified on DCR 17.5.
 *
 * IMPORTANT OWNERSHIP CONSEQUENCE
 * The role that runs JOIN owns the objects the join creates — SFDCR_<collab>
 * (application) and SFDCR_LOCAL_<collab> (database of local views). Having the
 * app perform the JOIN keeps ownership with the app's role. If an admin joins
 * from a worksheet under a different role instead, the app cannot operate on the
 * collaboration and needs 91_grants/adopt_joined_collaboration.sql.
 */

import { NextResponse } from "next/server";

import { querySnowflake } from "@/lib/snowflake";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** DCR names are identifiers; reject anything that is not one rather than quoting. */
const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ACCOUNT = /^[A-Za-z0-9][\w-]*\.[A-Za-z0-9][\w-]*$/;

function fail(code: string, title: string, cause: string, remediation: string, status = 200) {
  return NextResponse.json(
    {
      ok: false,
      operation: "JOIN_COLLABORATION",
      error: { code, title, cause, remediation, sql_fix: null, retryable: false, severity: "error" },
      duration_ms: 0,
    },
    { status },
  );
}

export async function POST(request: Request) {
  const started = Date.now();

  let body: { source_name?: string; owner_account?: string; local_name?: string };
  try {
    body = await request.json();
  } catch {
    return fail("INVALID_REQUEST", "Request body is not valid JSON", "Could not parse.", "Reload the page.", 400);
  }

  const source = String(body.source_name ?? "");
  const owner = String(body.owner_account ?? "");
  const local = String(body.local_name ?? source);

  if (!NAME.test(source)) {
    return fail("INVALID_INPUT", "Invalid collaboration name",
      `'${source}' is not a valid identifier.`,
      "Use the SOURCE_NAME value shown on the invitation.");
  }
  if (!NAME.test(local)) {
    return fail("INVALID_INPUT", "Invalid local name",
      `'${local}' is not a valid identifier.`,
      "Use letters, digits and underscores only.");
  }
  if (!ACCOUNT.test(owner)) {
    return fail("INVALID_INPUT", "Invalid account identifier",
      `'${owner}' is not an ORG.ACCOUNT identifier.`,
      "An account locator or Snowsight URL will not work here.");
  }

  const DCR = "SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.COLLABORATION";

  try {
    // REVIEW records acceptance of the collaboration terms under a local name.
    await querySnowflake(`CALL ${DCR}.REVIEW(?, ?, ?)`, {
      binds: [source, owner, local],
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    // Already reviewed/joined, or a LEAVE is stuck at LOCAL_DROP_PENDING.
    const benign = /already/i.test(message) || /InvitationNotFound/i.test(message);
    if (!benign) {
      return NextResponse.json(
        {
          ok: false,
          operation: "JOIN_COLLABORATION",
          error: {
            code: "REVIEW_FAILED",
            title: "Could not review the invitation",
            cause: message,
            remediation:
              "If a previous Leave was interrupted, the state may be LOCAL_DROP_PENDING — " +
              "finish it by leaving again, then a fresh invitation reappears.",
            sql_fix: null,
            retryable: true,
            severity: "error",
          },
          error_raw: message,
          duration_ms: Date.now() - started,
        },
        { status: 200 },
      );
    }
  }

  try {
    await querySnowflake(`CALL ${DCR}.JOIN(?)`, { binds: [local] });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    const needsGrant = /ReferenceUsage/i.test(message);
    const shareMatch = message.match(/TO SHARE ([A-Za-z_][\w$]*)/i);
    const dbMatch = message.match(/database '([^']+)'/i);

    return NextResponse.json(
      {
        ok: false,
        operation: "JOIN_COLLABORATION",
        error: {
          code: needsGrant ? "REFERENCE_USAGE_MISSING" : "JOIN_FAILED",
          title: needsGrant ? "A grant is missing on the shared database" : "Join failed",
          cause: message,
          remediation: needsGrant
            ? "This is expected the first time a database is shared into a clean room. " +
              "Apply the grant as ACCOUNTADMIN and retry. Do NOT grant to " +
              "SAMOOHA_BY_SNOWFLAKE_APP_SHARE — that named share belongs to the deprecated " +
              "v1 interface and does not exist here."
            : "Check the collaboration status. If a previous join failed, the owner may need " +
              "to tear down and recreate.",
          sql_fix:
            needsGrant && shareMatch && dbMatch
              ? `GRANT REFERENCE_USAGE ON DATABASE ${dbMatch[1]} TO SHARE ${shareMatch[1]};`
              : null,
          retryable: true,
          severity: needsGrant ? "blocked" : "error",
        },
        error_raw: message,
        duration_ms: Date.now() - started,
      },
      { status: 200 },
    );
  }

  // JOIN is asynchronous. Report the current state and let the client poll
  // rather than holding the request open for minutes.
  let status: Record<string, unknown>[] = [];
  try {
    status = await querySnowflake(`CALL ${DCR}.GET_STATUS(?)`, { binds: [local] });
  } catch {
    /* status is informational */
  }

  const joined = JSON.stringify(status).toUpperCase().includes("JOINED");

  return NextResponse.json({
    ok: true,
    operation: "JOIN_COLLABORATION",
    data: { local_name: local, joined, status },
    duration_ms: Date.now() - started,
  });
}
