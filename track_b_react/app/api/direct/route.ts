/**
 * POST /api/direct — REVIEW + JOIN using the caller's identity.
 *
 * WHY CALLER'S RIGHTS
 * COLLABORATION.JOIN accepts legal terms via SYSTEM$ACCEPT_LEGAL_TERMS.
 * Snowflake requires the acting user to have first_name, last_name and email.
 *
 *   - Owner's rights uses an SPCS managed service identity, which is NOT a user
 *     object. It has no profile and cannot be given one. JOIN fails at install.
 *   - Caller's rights uses the person who logged into the app. They have a
 *     profile. But they also need SAMOOHA_APP_ROLE, which is why this is the
 *     ONLY route that uses caller's rights: granting SAMOOHA_APP_ROLE is
 *     necessary for joining, but the facade still protects every other operation.
 *
 * PREREQUISITE
 * Every user who will join through this app needs:
 *   1. SAMOOHA_APP_ROLE granted to their user
 *   2. first_name, last_name, email set on their profile
 * Without these, the error is clear (USER_PROFILE_INCOMPLETE or privilege error)
 * rather than a 504 gateway timeout.
 *
 * OWNERSHIP CONSEQUENCE
 * The role that runs JOIN owns the created objects (SFDCR_<collab> and
 * SFDCR_LOCAL_<collab>). With caller's rights, those objects are owned by the
 * caller's active role — which may differ from the app's role. If that causes
 * privilege issues on later operations, run 91_grants/adopt_joined_collaboration.sql.
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

  // Both REVIEW and JOIN use caller's rights so the person's identity and
  // profile are visible to DCR.
  const callerOpts = { callersRights: true };

  try {
    await querySnowflake(`CALL ${DCR}.REVIEW(?, ?, ?)`, {
      ...callerOpts,
      binds: [source, owner, local],
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
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
              "finish it by leaving again, then a fresh invitation reappears.\n\n" +
              "If the error mentions privileges: the user joining needs SAMOOHA_APP_ROLE. " +
              "Grant it with: GRANT ROLE SAMOOHA_APP_ROLE TO USER <username>;",
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
    await querySnowflake(`CALL ${DCR}.JOIN(?)`, { ...callerOpts, binds: [local] });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    const profileMissing = /first\/last name/i.test(message) || /090655/i.test(message);
    const needsGrant = /ReferenceUsage/i.test(message);
    const shareMatch = message.match(/TO SHARE ([A-Za-z_][\w$]*)/i);
    const dbMatch = message.match(/database '([^']+)'/i);
    const needsRole = /not authorized/i.test(message) || /Insufficient privileges/i.test(message);

    let code = "JOIN_FAILED";
    let title = "Join failed";
    let remediation = "Check the collaboration status. If a previous join failed, call REVIEW again then JOIN.";
    let sql_fix: string | null = null;
    let severity = "error";

    if (profileMissing) {
      code = "USER_PROFILE_INCOMPLETE";
      title = "Your user profile is incomplete";
      remediation =
        "Joining accepts legal terms, so your profile must have first_name, last_name and email. " +
        "Ask an admin to set them, or run ALTER USER yourself, then retry.";
      sql_fix = "ALTER USER <your_username> SET first_name='…', last_name='…', email='…';";
      severity = "blocked";
    } else if (needsGrant) {
      code = "REFERENCE_USAGE_MISSING";
      title = "A grant is missing on the shared database";
      remediation =
        "This is expected the first time a database is shared into a clean room. " +
        "Apply the grant as ACCOUNTADMIN and retry. Do NOT grant to " +
        "SAMOOHA_BY_SNOWFLAKE_APP_SHARE — that belongs to the deprecated v1 interface.";
      sql_fix = needsGrant && shareMatch && dbMatch
        ? `GRANT REFERENCE_USAGE ON DATABASE ${dbMatch[1]} TO SHARE ${shareMatch[1]};`
        : null;
      severity = "blocked";
    } else if (needsRole) {
      code = "MISSING_DCR_ROLE";
      title = "You need SAMOOHA_APP_ROLE to join";
      remediation = "Ask an admin to grant it. This is needed only for joining — all other operations go through the facade.";
      sql_fix = "GRANT ROLE SAMOOHA_APP_ROLE TO USER <your_username>;";
      severity = "blocked";
    }

    return NextResponse.json(
      {
        ok: false,
        operation: "JOIN_COLLABORATION",
        error: { code, title, cause: message, remediation, sql_fix, retryable: true, severity },
        error_raw: message,
        duration_ms: Date.now() - started,
      },
      { status: 200 },
    );
  }

  // JOIN is asynchronous. Report the current state and let the client poll.
  let status: Record<string, unknown>[] = [];
  try {
    // GET_STATUS is safe through owner's rights — no caller identity needed.
    status = await querySnowflake(`CALL ${DCR}.GET_STATUS(?)`, { binds: [local] });
  } catch {
    /* status is informational */
  }

  const states = status.map((r) => String(r.STATUS ?? "").trim().toUpperCase());
  const joined = states.length > 0 && states.every((st) => st === "JOINED");

  return NextResponse.json({
    ok: true,
    operation: "JOIN_COLLABORATION",
    data: { local_name: local, joined, status },
    duration_ms: Date.now() - started,
  });
}
