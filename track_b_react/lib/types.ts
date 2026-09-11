/**
 * DCR Console — shared types.
 *
 * These mirror the envelope returned by DCR_CONSOLE.APP.INVOKE. Keeping them in
 * one place means a change to the facade contract surfaces as a TypeScript error
 * rather than a runtime surprise.
 */

/** Decoded, actionable error produced by dcr_errors.decode_error. */
export interface DcrError {
  code: string;
  title: string;
  cause: string;
  remediation: string;
  /** Ready-to-run fix. Powers the one-click "Grant and retry" affordance. */
  sql_fix: string | null;
  retryable: boolean;
  severity: "blocked" | "error" | "warning";
  /** Present for INVALID_INPUT so the UI can highlight the offending field. */
  field?: string;
}

/** Uniform envelope for every facade operation. */
export type FacadeResult<T = unknown> =
  | { ok: true; operation: string; data: T; duration_ms: number }
  | {
      ok: false;
      operation: string;
      error: DcrError;
      error_raw?: string;
      duration_ms: number;
    };

// --- Module 0: health -------------------------------------------------------

export interface HealthCheckItem {
  name: string;
  status: "ok" | "fail" | "warn" | "info";
  detail: string;
  fix: string | null;
  blocking: boolean;
}

export interface HealthCheckData {
  account: string | null;
  ready: boolean;
  checks: HealthCheckItem[];
  blocking_failures: string[];
}

// --- Module 1: my data ------------------------------------------------------

export interface ColumnInfo {
  name: string;
  data_type: string;
  suggested_category: string;
  suggested_column_type: string | null;
  category: string;
  column_type: string | null;
  activation_allowed: boolean;
  exposed_name_preview: string;
}

export interface DescribeColumnsData {
  fqn: string;
  columns: ColumnInfo[];
  column_types: string[];
  categories: string[];
}

/** What the user actually configured for one column. */
export interface ColumnConfig {
  name: string;
  category: string;
  column_type: string | null;
  activation_allowed: boolean;
}

export interface ResolvedColumn extends ColumnConfig {
  /** Name the column has in the SHARED view. Differs from `name` for join_standard. */
  exposed_name: string;
  is_join_key: boolean;
}

export interface RegisterOfferingData {
  offering_id: string;
  datasets: { alias: string; data_object_fqn: string; columns: ResolvedColumn[] }[];
}

export interface DataObjectItem {
  name: string;
  kind: string;
  row_count: number | null;
  fqn: string;
}

export interface ListDataObjectsData {
  level: "database" | "schema" | "object";
  database?: string;
  schema?: string;
  items: string[] | DataObjectItem[];
}

// --- Module 2/3: collaborations --------------------------------------------

export interface CollaborationSummary {
  source_name: string | null;
  /** NULL means a pending invitation that has not been reviewed and joined. */
  local_name: string | null;
  owner_account: string | null;
  updated_on: string | null;
  spec: string | null;
  is_owner: boolean;
}

export interface ListCollaborationsData {
  account: string;
  joined: CollaborationSummary[];
  invited: CollaborationSummary[];
}

// --- Module 4: link + preflight --------------------------------------------

export interface OfferingRef {
  view_name: string;
  offering_id: string;
  shared_by: string;
  shared_with: string;
  /** column_type aliases. MUST be used in join clauses, not the source names. */
  join_columns: string[];
  analysis_columns: string[];
  activation_columns: string[];
}

export interface CollaborationDetail {
  collaboration: string;
  partner_offerings: OfferingRef[];
  my_offerings: OfferingRef[];
  templates: string[];
  has_overlap_template: boolean;
  has_activation_template: boolean;

  /** This account's alias and roles inside the collaboration.
   *
   * Present so the UI can offer only the link operation that is legal here.
   * LINK_DATA_OFFERING attempted by a pure analysis runner fails with
   * ProviderNotServingAnalysisRunner, which reads like a fault rather than
   * "that operation belongs to the other side". May be absent if role
   * detection failed, in which case show both and let DCR arbitrate.
   */
  my_alias?: string | null;
  my_roles?: string[];
  is_data_provider?: boolean;
  is_analysis_runner?: boolean;
  is_owner?: boolean;
  serves_runners?: string[];
}

export interface PreflightData {
  can_run_overlap: boolean;
  can_activate: boolean;
  blockers: string[];
  warnings: string[];
  common_join_keys: string[];
  activatable_columns: string[];
  detail: CollaborationDetail | null;
}

// --- Module 5: overlap ------------------------------------------------------

/** One equality in a waterfall level. Names must be EXPOSED column names. */
export interface MatchKey {
  provider: string;
  consumer: string;
}

/** Ordered waterfall: levels tried in sequence (OR), keys within a level ANDed. */
export type MatchLevels = MatchKey[][];

export interface OverlapConfig {
  source_tables: string[];
  my_tables: string[];
  match_levels: MatchLevels;
  count_column?: string[];
  my_where_clause?: string;
  source_where_clause?: string;
  my_group_by?: string[];
  source_group_by?: string[];
}

export interface OverlapSummary {
  matched: number;
  unmatched: number | null;
  total: number | null;
  match_rate: number | null;
  privacy_suppressed: boolean;
}

export interface OverlapLevel {
  level: number | null;
  metric_type: string | null;
  count: number | null;
  total: number | null;
  match_criteria: string | null;
}

export interface OverlapData {
  from_cache: boolean;
  computed_at?: string;
  cache_key: string;
  join_clauses: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  summary?: OverlapSummary;
  levels?: OverlapLevel[];
}

// --- Module 6/7: activation + import ---------------------------------------

export interface ActivationConfig extends OverlapConfig {
  /** MUST be alias-qualified: p1.COL for partner data, c1.COL for your own. */
  activation_columns: string[];
  destination: string;
  segment_name: string;
  where_clause?: string;
  allowed_destinations?: string[];
}

export interface ActivationData {
  batch_id: string | null;
  results_table: string | null;
  segment_name: string;
  destination: string;
  activation_columns: string[];
}

export interface ImportState {
  import_id: string;
  target_fqn: string;
  status: "PENDING" | "IMPORTING" | "READY" | "FAILED";
  expected_rows: number | null;
  imported_rows: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ActivationBatch {
  batch_id: string;
  segment_name: string | null;
  status: string | null;
  updated_on: string | null;
  raw: Record<string, unknown>;
  import: ImportState | null;
  imported: boolean;

  /** How the batch reached this account.
   *
   *   "shared"  listed by VIEW_ACTIVATIONS, sent from another account, still
   *             needs PROCESS_ACTIVATION.
   *   "arrived" listed by VIEW_ACTIVATIONS and its rows are already present.
   *   "local"   activated to this account by this account. VIEW_ACTIVATIONS
   *             never lists these, because there is no cross-account share to
   *             process — the rows land straight in SEGMENT_RECORDS.
   */
  delivery?: "shared" | "arrived" | "local";

  /** Rows currently present in SEGMENT_RECORDS for this batch, if known. */
  available_rows?: number | null;
}

export interface ImportProgressData {
  import_id: string;
  status: string;
  target_fqn: string;
  expected_rows: number | null;
  imported_rows: number | null;
  /** The ONLY genuine percentage in the app: rows landed / rows expected. */
  percent_complete: number | null;
  started_at: string | null;
  finished_at: string | null;
  error_raw: string | null;
}

// --- App RBAC --------------------------------------------------------------

export type AppRole = "VIEWER" | "ANALYST" | "ACTIVATOR" | "BUILDER";

export interface AppRoleData {
  username: string;
  app_role: AppRole;
  can_view: boolean;
  can_run_overlap: boolean;
  can_activate: boolean;
  can_build: boolean;
}
