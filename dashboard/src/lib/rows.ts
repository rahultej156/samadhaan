import "server-only";

import { Pool, types } from "pg";

import { supabaseAdmin } from "@/lib/supabase";

/* Make node-postgres hand back exactly the shapes PostgREST does, so the two
   transports are interchangeable and the types in data.ts stay true:
     timestamptz/timestamp -> ISO 8601 string   (pg default: Date)
     date                  -> "YYYY-MM-DD"      (pg default: Date)
     int8                  -> number            (pg default: string)
   numeric stays a string in both, which is correct: money must not go through
   a float. */
/* Postgres writes `2026-11-14 06:03:16.35+00`: a space instead of `T` and a
   two-digit offset, both of which the JS Date constructor rejects. Repair the
   string rather than wrap pg's own parser, which is itself replaced here. */
function timestampToIso(raw: unknown, assumeUtc: boolean): unknown {
  if (typeof raw !== "string") return raw;
  let text = raw.replace(" ", "T");
  text = text.replace(/([+-]\d{2})$/, "$1:00");
  if (assumeUtc && !/[+-]\d{2}:\d{2}$|Z$/.test(text)) text += "Z";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? raw : date.toISOString();
}

types.setTypeParser(1184, (raw: string) => timestampToIso(raw, false)); // timestamptz
types.setTypeParser(1114, (raw: string) => timestampToIso(raw, true)); // timestamp
types.setTypeParser(1082, (raw: string) => raw); // date, kept as YYYY-MM-DD
types.setTypeParser(20, (raw: string) => Number(raw)); // int8 (the view's counts)

/**
 * One read primitive, two transports.
 *
 * The intended transport is @supabase/supabase-js with the service-role key,
 * which bypasses RLS. RLS is on with zero policies, so an anon/publishable key
 * gets `42501 permission denied` on every table — and the key currently sitting
 * in SUPABASE_SERVICE_ROLE_KEY is a publishable key (`sb_publishable_…`), not a
 * secret one. Rather than grant anon SELECT (which would publish merchant PII
 * to anyone who loads the page — exactly what db/schema.sql refuses to do), we
 * fall back to the Postgres session pooler with DATABASE_URL, which is the same
 * credential the FastAPI backend uses.
 *
 * Drop a real secret key (`sb_secret_…` or the service_role JWT) into
 * SUPABASE_SERVICE_ROLE_KEY and this switches to PostgREST on the next boot,
 * no code change.
 *
 * Either way the read happens on the server. Nothing but rendered rows ever
 * reaches the browser.
 */

export type RowSpec = {
  /** Table or view name. Always a literal from our own code. */
  table: string;
  /** Column list, or "*". Always a literal from our own code. */
  columns?: string;
  /** Equality filter: [column, value]. The value is parameterised. */
  eq?: [string, string];
  order?: { column: string; ascending?: boolean };
  limit?: number;
};

type Transport = "rest" | "pg";

let transport: Transport | null = null;
let pool: Pool | null = null;

function pgPool(): Pool {
  if (pool) return pool;
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) throw new Error("DATABASE_URL is not set");
  pool = new Pool({
    connectionString,
    max: 4,
    // The Supabase pooler presents a cert chain Node does not trust out of the
    // box, so the connection is encrypted but the chain is not verified — the
    // same posture as the FastAPI backend's `sslmode=require`. The proper fix
    // is to ship Supabase's `prod-ca-2021.crt` and pass it as `ca`; that is a
    // post-hackathon job, and it only matters once this runs outside localhost.
    ssl: { rejectUnauthorized: false },
    application_name: "samadhan-dashboard",
  });
  return pool;
}

function isPermissionDenied(message: string): boolean {
  return /permission denied|42501/i.test(message);
}

async function viaRest<T>(spec: RowSpec): Promise<T[]> {
  let query = supabaseAdmin()
    .from(spec.table)
    .select(spec.columns ?? "*");

  if (spec.eq) query = query.eq(spec.eq[0], spec.eq[1]);
  if (spec.order) {
    query = query.order(spec.order.column, { ascending: spec.order.ascending ?? true });
  }
  if (spec.limit) query = query.limit(spec.limit);

  const { data, error } = await query;
  if (error) throw new Error(error.message);
  return (data ?? []) as T[];
}

async function viaPg<T>(spec: RowSpec): Promise<T[]> {
  const parts = [`select ${spec.columns ?? "*"} from public.${spec.table}`];
  const params: string[] = [];

  if (spec.eq) {
    params.push(spec.eq[1]);
    parts.push(`where ${spec.eq[0]} = $1`);
  }
  if (spec.order) {
    parts.push(`order by ${spec.order.column} ${spec.order.ascending === false ? "desc" : "asc"}`);
  }
  if (spec.limit) parts.push(`limit ${Number(spec.limit)}`);

  const result = await pgPool().query(parts.join(" "), params);
  return result.rows as T[];
}

/** Read rows. Picks a transport on the first call and sticks with it. */
export async function selectRows<T>(spec: RowSpec): Promise<T[]> {
  if (transport === "pg") return viaPg<T>(spec);

  try {
    const rows = await viaRest<T>(spec);
    transport = "rest";
    return rows;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!isPermissionDenied(message) || !process.env.DATABASE_URL) {
      throw new Error(
        `${spec.table}: ${message}` +
          (isPermissionDenied(message)
            ? " — SUPABASE_SERVICE_ROLE_KEY looks like a publishable key, and no DATABASE_URL is set to fall back to."
            : ""),
      );
    }
    transport = "pg";
    return viaPg<T>(spec);
  }
}

export async function selectOne<T>(spec: RowSpec): Promise<T | null> {
  const rows = await selectRows<T>({ ...spec, limit: spec.limit ?? 1 });
  return rows[0] ?? null;
}

/** Which transport ended up being used, for the footer badge. */
export function activeTransport(): Transport | null {
  return transport;
}
