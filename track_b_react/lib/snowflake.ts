/**
 * Snowflake query helper. Call from any server component or route handler:
 *   const rows = await querySnowflake("SELECT ...")
 *   const rows = await querySnowflake("SELECT ...", { callersRights: true })
 *
 * Auth is auto-detected (in priority order):
 *   1. SPCS token file (/snowflake/session/token) — read fresh on every call
 *   2. SNOWFLAKE_USER + SNOWFLAKE_PASSWORD env vars — password auth (local dev)
 *   3. ~/.snowflake/config.toml default connection — zero-config local dev
 *
 * Connection pooling:
 *   Owner's rights: single pool per process, recreated when the service token rotates.
 *   Caller's rights: one pool per user+role (keyed by combined token), all drained
 *     when the service token rotates.
 *   Local dev pools (password / toml) are shared and never rotated.
 *
 * SPCS caller's rights helpers:
 *   queryWithToken(query, token) — runs a query with an explicit OAuth token.
 *   getServiceToken() — reads the SPCS service token from /snowflake/session/token.
 *   buildCallerRightsToken(callerUserToken) — combines service + caller tokens.
 *
 * Cleanup:
 *   closePool() — drains and destroys all active pools on shutdown.
 */

import { headers } from "next/headers"
import fs from "fs"
import path from "path"
import os from "os"
import snowflake from "snowflake-sdk"

snowflake.configure({ logLevel: "ERROR" })

const SPCS_TOKEN_PATH = "/snowflake/session/token"

// --- Connection pool configuration ---

const POOL_CONFIG = {
  min: 0, // Start with no connections (lazy init)
  max: 10, // Scale up to 10 concurrent connections
}

// Owner's rights: single pool, recreated when the service token rotates.
let ownersPool: ReturnType<typeof snowflake.createPool> | null = null
let ownersPoolToken = ""

// Caller's rights: one pool per combined token (user+role), keyed by combined token.
// All pools are drained when the service token rotates.
const callersPool = new Map<string, ReturnType<typeof snowflake.createPool>>()
let callersServiceToken = ""

// Local dev pools.
let passwordPool: ReturnType<typeof snowflake.createPool> | null = null
let tomlPool: ReturnType<typeof snowflake.createPool> | null = null

function baseConfig(): snowflake.ConnectionOptions {
  const application = "SnowflakeAppsDeploy"
  // `account` is typed as required, but inside SPCS it arrives from the
  // environment (or is implied by the OAuth token and accessUrl), so it is
  // genuinely optional while assembling this object. Build it loosely and cast
  // once at the end rather than inventing a placeholder account name.
  const base: Partial<snowflake.ConnectionOptions> = { application }
  if (process.env.SNOWFLAKE_ACCOUNT) base.account = process.env.SNOWFLAKE_ACCOUNT
  if (process.env.SNOWFLAKE_WAREHOUSE) base.warehouse = process.env.SNOWFLAKE_WAREHOUSE
  if (process.env.SNOWFLAKE_ACCOUNT_URL) base.accessUrl = process.env.SNOWFLAKE_ACCOUNT_URL
  // SNOWFLAKE_HOST is commonly injected by eval/CI frameworks
  if (!base.accessUrl && process.env.SNOWFLAKE_HOST) {
    base.accessUrl = `https://${process.env.SNOWFLAKE_HOST}`
  }
  if (process.env.SNOWFLAKE_ROLE) base.role = process.env.SNOWFLAKE_ROLE
  if (process.env.SNOWFLAKE_DATABASE) base.database = process.env.SNOWFLAKE_DATABASE
  if (process.env.SNOWFLAKE_SCHEMA) base.schema = process.env.SNOWFLAKE_SCHEMA
  return base as snowflake.ConnectionOptions
}

// --- ~/.snowflake/connections.toml + config.toml reader ---

interface TomlConnection {
  account?: string
  user?: string
  password?: string
  host?: string
  port?: string | number
  warehouse?: string
  database?: string
  schema?: string
  region?: string
  role?: string
  authenticator?: string
  protocol?: string
  [key: string]: unknown
}

let _tomlConfigCache: { defaultName: string; connections: Record<string, TomlConnection> } | null | undefined

function normalizeConnectionsToml(doc: Record<string, any>): Record<string, TomlConnection> {
  const result: Record<string, TomlConnection> = {}
  for (const [key, val] of Object.entries(doc)) {
    if (key === "default_connection_name" || key === "connections") continue
    if (typeof val === "object" && val !== null && !Array.isArray(val)) {
      result[key] = val as TomlConnection
    }
  }
  if (typeof doc.connections === "object" && doc.connections !== null && !Array.isArray(doc.connections)) {
    Object.assign(result, doc.connections as Record<string, TomlConnection>)
  }
  return result
}

/**
 * Resolve a Snowflake connection from local TOML config files.
 *
 * Tries two file layouts (in order):
 *   1. ~/.snowflake/connections.toml — supports both nested ([connections.name])
 *      and legacy (top-level [name]) formats; nested wins on conflict.
 *   2. ~/.snowflake/config.toml — connections nested under [connections.*] sections.
 *
 * Both files may contain a `default_connection_name` key. The env var
 * SNOWFLAKE_CONNECTION_NAME takes priority over either.
 *
 * Result is cached for the lifetime of the process.
 */
export function readTomlDefaultConnection(): TomlConnection | null {
  if (_tomlConfigCache === undefined) {
    _tomlConfigCache = null // mark as attempted
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { parse } = require("smol-toml") as { parse: (s: string) => Record<string, any> }
      const snowDir = process.env.SNOWFLAKE_HOME ?? path.join(os.homedir(), ".snowflake")

      let defaultName = ""
      let connections: Record<string, TomlConnection> = {}

      // connections.toml: top-level sections are connections
      const connPath = path.join(snowDir, "connections.toml")
      if (fs.existsSync(connPath)) {
        const doc = parse(fs.readFileSync(connPath, "utf8"))
        if (typeof doc.default_connection_name === "string") defaultName = doc.default_connection_name
        connections = normalizeConnectionsToml(doc)
      }

      // config.toml: connections nested under [connections.*], also has default_connection_name
      const configPath = path.join(snowDir, "config.toml")
      if (fs.existsSync(configPath)) {
        const doc = parse(fs.readFileSync(configPath, "utf8"))
        if (!defaultName && typeof doc.default_connection_name === "string") {
          defaultName = doc.default_connection_name
        }
        // Only use config.toml connections if connections.toml had none
        if (Object.keys(connections).length === 0) {
          connections = (doc.connections ?? {}) as Record<string, TomlConnection>
        }
      }

      // General SNOWFLAKE_<KEY> env vars overlay on every toml connection (spec §3.B)
      const envOverlay: Partial<TomlConnection> = {}
      const CONN_KEYS = new Set(["account","user","password","database","schema","role","warehouse","protocol","host","port","region","authenticator"])
      for (const [k, v] of Object.entries(process.env)) {
        if (!k.startsWith("SNOWFLAKE_") || k === "SNOWFLAKE_CONNECTION_NAME" || k === "SNOWFLAKE_HOME") continue
        const field = k.slice("SNOWFLAKE_".length).toLowerCase()
        if (CONN_KEYS.has(field)) (envOverlay as Record<string, string>)[field] = v!
      }
      if (Object.keys(envOverlay).length > 0) {
        for (const name of Object.keys(connections)) {
          connections[name] = { ...connections[name], ...envOverlay }
        }
      }

      // SNOWFLAKE_CONNECTION_NAME overrides file-level default
      if (process.env.SNOWFLAKE_CONNECTION_NAME) {
        defaultName = process.env.SNOWFLAKE_CONNECTION_NAME
      }

      _tomlConfigCache = { defaultName, connections }
    } catch {
      // parse error or smol-toml not installed — silently skip
      return null
    }
  }

  if (!_tomlConfigCache) return null

  const { defaultName, connections } = _tomlConfigCache
  const names = Object.keys(connections)
  if (names.length === 0) return null

  const conn = (defaultName && connections[defaultName]) || connections[names[0]]
  return conn ?? null
}

/** Reset the connection config cache. Exported for testing only. */
export function resetTomlConfigCache() {
  _tomlConfigCache = undefined
}

function tomlConnectionConfig(conn: TomlConnection): snowflake.ConnectionOptions {
  // Use SDK's normalizeConnectionOptions for snake_case -> camelCase + key aliases
  // Type assertion needed until @types/snowflake-sdk includes normalizeConnectionOptions
  const normalize = (snowflake as unknown as { normalizeConnectionOptions: (o: Record<string, unknown>) => snowflake.ConnectionOptions }).normalizeConnectionOptions
  const normalized = normalize(conn as Record<string, unknown>)
  // SDK doesn't handle host/port/protocol -> accessUrl, so we do it here
  if (conn.host && !normalized.accessUrl) {
    const protocol = conn.protocol ?? "https"
    const port = conn.port ? `:${conn.port}` : ""
    normalized.accessUrl = `${protocol}://${conn.host}${port}`
  }
  return normalized
}

// --- Pool helpers ---

function getOwnersPool(serviceToken: string): ReturnType<typeof snowflake.createPool> {
  if (ownersPool && ownersPoolToken !== serviceToken) {
    ownersPool.drain()
    ownersPool = null
  }
  if (!ownersPool) {
    ownersPool = snowflake.createPool(
      { ...baseConfig(), authenticator: "OAUTH", token: serviceToken },
      POOL_CONFIG,
    )
    ownersPoolToken = serviceToken
  }
  return ownersPool
}

function getCallersPool(combinedToken: string, serviceToken: string): ReturnType<typeof snowflake.createPool> {
  // Service token rotated — all combined tokens are stale, drain everything.
  if (callersServiceToken !== serviceToken) {
    for (const pool of callersPool.values()) pool.drain()
    callersPool.clear()
    callersServiceToken = serviceToken
  }
  if (!callersPool.has(combinedToken)) {
    callersPool.set(
      combinedToken,
      snowflake.createPool(
        { ...baseConfig(), authenticator: "OAUTH", token: combinedToken },
        POOL_CONFIG,
      ),
    )
  }
  return callersPool.get(combinedToken)!
}

function getPasswordPool(): ReturnType<typeof snowflake.createPool> {
  if (!passwordPool) {
    passwordPool = snowflake.createPool(
      {
        ...baseConfig(),
        username: process.env.SNOWFLAKE_USER,
        password: process.env.SNOWFLAKE_PASSWORD,
      },
      POOL_CONFIG,
    )
  }
  return passwordPool
}

function getTomlPool(conn: TomlConnection): ReturnType<typeof snowflake.createPool> {
  if (!tomlPool) {
    tomlPool = snowflake.createPool({ ...tomlConnectionConfig(conn), ...baseConfig() }, POOL_CONFIG)
  }
  return tomlPool
}

function queryWithPool(
  pool: ReturnType<typeof snowflake.createPool>,
  query: string,
  binds?: any[],
): Promise<Record<string, any>[]> {
  return pool.use(async (conn) => {
    return new Promise<Record<string, any>[]>((res, rej) => {
      conn.execute({
        sqlText: query,
        binds: binds as any,
        complete: (err, _stmt, rows) => {
          if (err) {
            const sdkErr = err as any
            const parts = [sdkErr.message]
            if (sdkErr.data?.message && sdkErr.data.message !== sdkErr.message) parts.push(sdkErr.data.message)
            if (sdkErr.cause) parts.push(String(sdkErr.cause))
            const queryId = sdkErr.data?.queryId ?? sdkErr.queryId
            if (queryId) parts.push(`[queryId: ${queryId}]`)
            rej(new Error(`Query failed: ${parts.join(" | ")}`))
          } else {
            res((rows ?? []) as Record<string, any>[])
          }
        },
      })
    })
  })
}

// --- One-shot connection helper (used for per-request tokens) ---

function connectAndQuery(config: snowflake.ConnectionOptions, query: string): Promise<Record<string, any>[]> {
  const conn = snowflake.createConnection(config)
  return new Promise((resolve, reject) => {
    conn.connect((err) => {
      if (err) return reject(new Error(`Snowflake connection failed: ${err.message}`))
      conn.execute({
        sqlText: query,
        complete: (err, _stmt, rows) => {
          conn.destroy(() => {})
          if (err) {
            const sdkErr = err as any
            const parts = [sdkErr.message]
            if (sdkErr.data?.message && sdkErr.data.message !== sdkErr.message) parts.push(sdkErr.data.message)
            if (sdkErr.cause) parts.push(String(sdkErr.cause))
            const queryId = sdkErr.data?.queryId ?? sdkErr.queryId
            if (queryId) parts.push(`[queryId: ${queryId}]`)
            reject(new Error(`Query failed: ${parts.join(" | ")}`))
          } else {
            resolve((rows ?? []) as Record<string, any>[])
          }
        },
      })
    })
  })
}

interface QueryOptions {
  callersRights?: boolean
  binds?: any[]
}

export async function querySnowflake(query: string, options: QueryOptions = {}): Promise<Record<string, any>[]> {
  const { callersRights = false, binds } = options
  const serviceToken = getServiceToken()

  if (serviceToken) {
    if (callersRights) {
      const callerToken = (await headers()).get("sf-context-current-user-token") ?? ""
      if (!callerToken) {
        throw new Error(
          "No sf-context-current-user-token header. Ensure executeAsCaller is set in app.yml.",
        )
      }
      const combinedToken = serviceToken + "." + callerToken
      return queryWithPool(getCallersPool(combinedToken, serviceToken), query, binds)
    }
    return queryWithPool(getOwnersPool(serviceToken), query, binds)
  }

  // Local dev: no SPCS token, so caller's rights is not possible.
  if (callersRights) {
    console.warn("[snowflake] useCallersRights=true has no effect outside SPCS — using local dev credentials")
  }

  // Explicit env vars: password auth via pooled connections
  if (process.env.SNOWFLAKE_USER && process.env.SNOWFLAKE_PASSWORD) {
    return queryWithPool(getPasswordPool(), query, binds)
  }

  // ~/.snowflake/connections.toml or config.toml: use the default connection (local dev)
  const tomlConn = readTomlDefaultConnection()
  if (tomlConn) {
    return queryWithPool(getTomlPool(tomlConn), query, binds)
  }

  throw new Error(
    "No Snowflake credentials found. Provide one of:\n" +
    "  1. SPCS token file at /snowflake/session/token\n" +
    "  2. SNOWFLAKE_USER + SNOWFLAKE_PASSWORD env vars\n" +
    "  3. ~/.snowflake/config.toml with a default connection"
  )
}

// --- SPCS caller's rights helpers ---

export function getServiceToken(): string {
  try {
    return fs.readFileSync(SPCS_TOKEN_PATH, "utf8").trim()
  } catch {
    return ""
  }
}

export function buildCallerRightsToken(callerUserToken: string): string {
  const serviceToken = getServiceToken()
  if (!serviceToken) {
    throw new Error("No SPCS service token available at " + SPCS_TOKEN_PATH)
  }
  return serviceToken + "." + callerUserToken
}

/**
 * Run a query using an explicit OAuth token (for service-rights or caller's-rights).
 * Creates a fresh connection each time since the token may differ per request.
 */
export async function queryWithToken(query: string, token: string): Promise<Record<string, any>[]> {
  return connectAndQuery({ ...baseConfig(), authenticator: "OAUTH", token }, query)
}

// --- Pool lifecycle ---

/**
 * Gracefully drain and destroy all active connection pools.
 * Call during server shutdown for clean resource cleanup.
 */
export async function closePool(): Promise<void> {
  const drainPromises: Promise<void>[] = []

  if (ownersPool) {
    const p = ownersPool
    ownersPool = null
    ownersPoolToken = ""
    drainPromises.push(p.drain())
  }

  for (const pool of callersPool.values()) {
    drainPromises.push(pool.drain())
  }
  callersPool.clear()

  if (passwordPool) {
    const p = passwordPool
    passwordPool = null
    drainPromises.push(p.drain())
  }

  if (tomlPool) {
    const p = tomlPool
    tomlPool = null
    drainPromises.push(p.drain())
  }

  await Promise.all(drainPromises)
}
