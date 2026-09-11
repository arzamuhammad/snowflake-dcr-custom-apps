/**
 * DCR Console — browser-side facade client.
 *
 * Every DCR interaction goes through /api/facade, which proxies to
 * DCR_CONSOLE.APP.INVOKE. The one exception is JOIN, which cannot run inside a
 * stored procedure (it calls SYSTEM$ACCEPT_LEGAL_TERMS, and Snowflake rejects
 * side-effecting functions in nested context) and therefore goes through
 * /api/direct instead. See lib/types.ts for the response contract.
 */

import type {
  ActivationBatch,
  ActivationConfig,
  ActivationData,
  AppRoleData,
  CollaborationDetail,
  DescribeColumnsData,
  FacadeResult,
  HealthCheckData,
  ImportProgressData,
  ListCollaborationsData,
  ListDataObjectsData,
  OverlapConfig,
  OverlapData,
  PreflightData,
  RegisterOfferingData,
} from "./types";

async function post<T>(path: string, body: unknown): Promise<FacadeResult<T>> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  // A non-2xx from our own route is a transport/proxy failure, not a DCR error.
  // Shape it like a facade error so callers have exactly one error contract.
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      detail = j?.error?.cause ?? j?.message ?? detail;
    } catch {
      /* body was not JSON */
    }
    return {
      ok: false,
      operation: "TRANSPORT",
      error: {
        code: "TRANSPORT_ERROR",
        title: "Could not reach the application backend",
        cause: detail,
        remediation:
          "Reload the page. If it persists, the service may be restarting — check `snow app events`.",
        sql_fix: null,
        retryable: true,
        severity: "error",
      },
      duration_ms: 0,
    };
  }

  return (await res.json()) as FacadeResult<T>;
}

/** Call a whitelisted facade operation. */
export function invoke<T = unknown>(
  operation: string,
  payload: Record<string, unknown> = {},
): Promise<FacadeResult<T>> {
  return post<T>("/api/facade", { operation, payload });
}

// ---------------------------------------------------------------------------
// Typed wrappers. Thin on purpose: the value is the type, not the abstraction.
// ---------------------------------------------------------------------------

export const healthCheck = () => invoke<HealthCheckData>("HEALTH_CHECK");

export const registerStandardTemplates = () =>
  invoke<{ templates: string[] }>("REGISTER_STANDARD_TEMPLATES");

export const listDataObjects = (database?: string, schema?: string) =>
  invoke<ListDataObjectsData>("LIST_DATA_OBJECTS", { database, schema });

export const describeColumns = (fqn: string) =>
  invoke<DescribeColumnsData>("DESCRIBE_COLUMNS", { fqn });

export const registerOffering = (config: Record<string, unknown>) =>
  invoke<RegisterOfferingData>("REGISTER_OFFERING", { config });

export const listOfferings = () =>
  invoke<{ offerings: Record<string, string>[] }>("LIST_OFFERINGS");

export const unregisterOffering = (offering_id: string) =>
  invoke<{ offering_id: string }>("UNREGISTER_OFFERING", { offering_id });

export const createCollaboration = (
  config: Record<string, unknown>,
  auto_join_warehouse?: string,
) => invoke<{ collaboration_name: string }>("CREATE_COLLABORATION", { config, auto_join_warehouse });

export const listCollaborations = () =>
  invoke<ListCollaborationsData>("LIST_COLLABORATIONS");

export const getStatus = (collaboration: string) =>
  invoke<{ status: Record<string, unknown>[] }>("GET_STATUS", { collaboration });

/**
 * Advance the owner towards JOINED.
 *
 * Necessary because auto-join is best effort: the task can fail while INITIALIZE
 * reports success, leaving the collaboration stuck at CREATED with the failure
 * buried in the status DETAILS blob.
 *
 * NOT CALLED BY THE UI. It cannot help from a deployed app, because the JOIN it
 * performs needs an identifiable user — see reviewAndJoin below for the full
 * reasoning. Retained for scripted use by an operator who has the privileges.
 */
export const ensureJoined = (collaboration: string) =>
  invoke<{ action: string; joined: boolean; keep_polling: boolean }>("ENSURE_JOINED", {
    collaboration,
  });

export const getCollaborationDetail = (collaboration: string) =>
  invoke<CollaborationDetail>("GET_COLLABORATION_DETAIL", { collaboration });

export const preflight = (collaboration: string) =>
  invoke<PreflightData>("PREFLIGHT", { collaboration });

/**
 * Link data into a collaboration.
 *
 * `mode` distinguishes the two operations that both look like "linking data":
 *   partner -> LINK_DATA_OFFERING       (a provider shares its data TO runners; p1)
 *   local   -> LINK_LOCAL_DATA_OFFERING (a runner attaches its OWN table; c1)
 *
 * Omitting the local link is the single most common reason an overlap cannot run,
 * and the official Snowsight UI does not expose it at all.
 */
export const linkData = (
  collaboration: string,
  offering_id: string,
  mode: "partner" | "local",
  runners?: string[],
) => invoke<{ mode: string }>("LINK_DATA", { collaboration, offering_id, mode, runners });

export const unlinkData = (
  collaboration: string,
  offering_id: string,
  mode: "partner" | "local",
  runners?: string[],
) => invoke<{ mode: string }>("UNLINK_DATA", { collaboration, offering_id, mode, runners });

export const runOverlap = (
  collaboration: string,
  config: OverlapConfig,
  use_cache = true,
) => invoke<OverlapData>("RUN_OVERLAP", { collaboration, config, use_cache });

export const runActivation = (collaboration: string, config: ActivationConfig) =>
  invoke<ActivationData>("RUN_ACTIVATION", { collaboration, config });

export const listActivations = (collaboration: string) =>
  invoke<{ activations: ActivationBatch[] }>("LIST_ACTIVATIONS", { collaboration });

export const importActivation = (args: {
  collaboration: string;
  batch_id: string;
  target_fqn: string;
  activation_columns?: string[];
  expected_rows?: number;
}) =>
  invoke<{ import_id: string; imported_rows: number; target_fqn: string }>(
    "IMPORT_ACTIVATION",
    args,
  );

export const getImportProgress = (import_id: string) =>
  invoke<ImportProgressData>("GET_IMPORT_PROGRESS", { import_id });

export const activityHistory = (collaboration: string) =>
  invoke<{
    dcr_history: Record<string, unknown>[];
    console_history: Record<string, unknown>[];
  }>("ACTIVITY_HISTORY", { collaboration });

export const listUpdateRequests = (collaboration: string) =>
  invoke<{ requests: Record<string, unknown>[] }>("LIST_UPDATE_REQUESTS", { collaboration });

export const approveUpdateRequest = (collaboration: string, request_id: string) =>
  invoke<{ result: string }>("APPROVE_UPDATE_REQUEST", { collaboration, request_id });

export const rejectUpdateRequest = (
  collaboration: string,
  request_id: string,
  reason: string,
) => invoke<{ result: string }>("REJECT_UPDATE_REQUEST", { collaboration, request_id, reason });

export const addTemplate = (collaboration: string, template_id: string, runners: string[]) =>
  invoke<{ template_id: string }>("ADD_TEMPLATE", { collaboration, template_id, runners });

/** Irreversible. Teardown removes the collaboration for ALL participants. */
export const teardownOrLeave = (collaboration: string, mode: "teardown" | "leave") =>
  invoke<{ two_call_completed: boolean }>("TEARDOWN_OR_LEAVE", { collaboration, mode });

export const getAppRole = (username?: string) =>
  invoke<AppRoleData>("GET_APP_ROLE", { username });

export const setAppRole = (username: string, app_role: string, notes?: string) =>
  invoke<{ app_role: string }>("SET_APP_ROLE", { username, app_role, notes });

// ---------------------------------------------------------------------------
// Session-level operations. These CANNOT go through the facade.
// ---------------------------------------------------------------------------

/**
 * REVIEW then JOIN, executed at session level.
 *
 * JOIN installs the clean room application, which calls
 * SYSTEM$ACCEPT_LEGAL_TERMS. Snowflake refuses side-effecting functions inside a
 * stored procedure, so this bypasses DCR_CONSOLE.APP.INVOKE by design.
 *
 * NOT CALLED BY THE UI, deliberately — and not dead code either. Accepting legal
 * terms additionally requires the acting user to have first_name, last_name and
 * email. A deployed app has neither option available: owner's rights acts as an
 * SPCS managed service identity, which is not a user object and cannot be given
 * a profile, while caller's rights acts as a business user who deliberately does
 * not hold SAMOOHA_APP_ROLE. So the Invitations page shows copy-ready SQL
 * instead, and this stays as a working path for an operator who holds both the
 * profile and the privileges.
 *
 * Consequence worth knowing if you do use it: the role that runs JOIN OWNS the
 * objects the join creates (SFDCR_<collab> and SFDCR_LOCAL_<collab>), which
 * determines who can link and run later.
 */
export const reviewAndJoin = (args: {
  source_name: string;
  owner_account: string;
  local_name: string;
}) => post<{ joined: boolean; status: Record<string, unknown>[] }>("/api/direct", args);
