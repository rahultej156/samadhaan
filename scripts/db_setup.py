"""
Apply the schema, seed the demo data, and verify both.

    py scripts/db_setup.py            # schema + seed + verify
    py scripts/db_setup.py --seed     # re-seed only (the demo reset)
    py scripts/db_setup.py --verify   # check only, change nothing

Reads DATABASE_URL from backend/.env. Never prints the connection string.

Verification is the point of this script, not the applying. It checks that the
seeded numbers match what contracts.md promises the agent will say out loud,
and that the anon key cannot read anything.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402  (needs the path set first)

try:
    import psycopg
except ImportError:
    sys.exit("psycopg is not installed. Run: pip install -r backend/requirements.txt")


SCHEMA = ROOT / "db" / "schema.sql"
SEED = ROOT / "db" / "seed.sql"


def safe_target(dsn: str) -> str:
    """Describe where we are connecting without revealing the password."""
    try:
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        host = info.get("host", "?")
        port = info.get("port", "?")
        db = info.get("dbname", "?")
        user = info.get("user", "?")
        return f"{user}@{host}:{port}/{db}"
    except Exception:
        return "(could not parse DSN)"


def connect() -> psycopg.Connection:
    if not config.DATABASE_URL:
        sys.exit("DATABASE_URL is empty. Fill in backend/.env first.")

    print(f"connecting to {safe_target(config.DATABASE_URL)}")
    started = time.perf_counter()
    # autocommit so the .sql files' own BEGIN/COMMIT govern the transaction.
    conn = psycopg.connect(config.DATABASE_URL, connect_timeout=15, autocommit=True)
    print(f"  connected in {(time.perf_counter() - started) * 1000:.0f} ms")

    with conn.cursor() as cur:
        t = time.perf_counter()
        cur.execute("select version(), current_database(), inet_server_addr()")
        row = cur.fetchone()
        warm = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        cur.execute("select 1")
        cur.fetchone()
        print(f"  server     : {row[0].split(' on ')[0]}")
        print(f"  database   : {row[1]}")
        print(f"  first query: {warm:.0f} ms")
        print(f"  warm query : {(time.perf_counter() - t) * 1000:.0f} ms")
    return conn


def apply_file(conn: psycopg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    print(f"\napplying {path.relative_to(ROOT)} ({len(sql):,} bytes)")
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql)
    print(f"  done in {(time.perf_counter() - started) * 1000:.0f} ms")


def verify(conn: psycopg.Connection) -> bool:
    ok = True

    print("\n" + "=" * 72)
    print("TABLES")
    print("=" * 72)
    with conn.cursor() as cur:
        cur.execute(
            """
            select table_name
              from information_schema.tables
             where table_schema = 'public' and table_type = 'BASE TABLE'
             order by table_name
            """
        )
        tables = [r[0] for r in cur.fetchall()]
    print(f"  {len(tables)} tables: {', '.join(tables)}")
    if len(tables) != 16:
        print(f"  !! expected 16 tables, found {len(tables)}")
        ok = False

    print("\n" + "=" * 72)
    print("SEEDED DATA vs WHAT contracts.md PROMISES THE AGENT WILL SAY")
    print("=" * 72)
    with conn.cursor() as cur:
        cur.execute(
            """
            select m.merchant_code,
                   m.shop_name,
                   m.shop_status,
                   m.shop_closed_on,
                   count(i.id)                                    as invoices,
                   coalesce(sum(i.amount), 0)                     as total_billed,
                   coalesce(sum(i.amount) filter (
                       where m.shop_closed_on is not null
                         and i.charged_on > m.shop_closed_on), 0)  as after_closure,
                   p.promised_monthly_amount,
                   p.billed_monthly_amount,
                   s.amount_on_hold,
                   extract(day from now() - d.last_heartbeat_at)::int as device_silent_days
              from merchants m
              left join invoices    i on i.merchant_id = m.id
              left join plans       p on p.merchant_id = m.id
              left join settlements s on s.merchant_id = m.id
              left join devices     d on d.merchant_id = m.id
             group by m.merchant_code, m.shop_name, m.shop_status, m.shop_closed_on,
                      p.promised_monthly_amount, p.billed_monthly_amount,
                      s.amount_on_hold, d.last_heartbeat_at
             order by m.merchant_code
            """
        )
        rows = cur.fetchall()

    expectations = {
        "M1": ("16 invoices, 1000 charged after closure", lambda r: r[4] == 16 and float(r[6]) == 1000.0),
        "M2": ("868 overcharge (7 x 124)", lambda r: r[4] == 7 and float(r[8] - r[7]) * r[4] == 868.0),
        "M3": ("14200 on hold", lambda r: float(r[9] or 0) == 14200.0),
        "M4": ("device silent ~11 days", lambda r: (r[10] or 0) in (10, 11)),
    }

    for r in rows:
        code = r[0]
        print(f"\n  {code}  {r[1]}")
        print(f"      status           : {r[2]}" + (f", closed {r[3]}" if r[3] else ""))
        print(f"      invoices         : {r[4]}  total ₹{r[5]}")
        if r[3]:
            print(f"      after closure    : ₹{r[6]}")
        if r[7] is not None:
            overcharge = (r[8] - r[7]) * r[4]
            print(f"      promised ₹{r[7]} vs billed ₹{r[8]}  ->  overcharge ₹{overcharge}")
        if float(r[9] or 0):
            print(f"      settlement hold  : ₹{r[9]}")
        if r[10] is not None:
            print(f"      device silent    : {r[10]} days")

        if code in expectations:
            label, check = expectations[code]
            try:
                passed = check(r)
            except Exception:
                passed = False
            print(f"      expect {label:<40} {'OK' if passed else 'MISMATCH'}")
            if not passed:
                ok = False

    print("\n" + "=" * 72)
    print("SECURITY — both must be empty, or the anon key can read our data")
    print("=" * 72)
    with conn.cursor() as cur:
        cur.execute("select tablename, policyname from pg_policies where schemaname = 'public'")
        policies = cur.fetchall()
        cur.execute(
            """
            select table_name, privilege_type
              from information_schema.role_table_grants
             where grantee in ('anon', 'authenticated') and table_schema = 'public'
             order by table_name
            """
        )
        grants = cur.fetchall()

    print(f"  RLS policies on public : {len(policies)}")
    if policies:
        for t, p in policies[:10]:
            print(f"      !! {t}.{p}")
        ok = False
    print(f"  anon/authenticated grants : {len(grants)}")
    if grants:
        for t, p in grants[:10]:
            print(f"      !! {t} {p}")
        ok = False

    with conn.cursor() as cur:
        cur.execute(
            """
            select count(*) from pg_class c
              join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
            """
        )
        rls_on = cur.fetchone()[0]
    print(f"  tables with RLS enabled   : {rls_on} of {len(tables)}")
    if rls_on != len(tables):
        print("      !! some tables have RLS off")
        ok = False

    print("\n" + "=" * 72)
    print("REFERENCE NUMBERS the agent will read out")
    print("=" * 72)
    with conn.cursor() as cur:
        cur.execute(
            """
            select 'SMD-' || last_value, 'RF-' || (select last_value from refund_ref_seq),
                   'PU-'  || (select last_value from pickup_ref_seq),
                   'CN-'  || (select last_value from credit_ref_seq)
              from case_ref_seq
            """
        )
        print("  next: case {}, refund {}, pickup {}, credit note {}".format(*cur.fetchone()))

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — see !! lines above"))
    return ok


def main() -> None:
    args = set(sys.argv[1:])
    conn = connect()
    try:
        if not args or args == {"--schema"}:
            apply_file(conn, SCHEMA)
            apply_file(conn, SEED)
        elif "--seed" in args:
            apply_file(conn, SEED)
        elif "--verify" in args:
            pass
        else:
            sys.exit(f"unknown arguments: {' '.join(sorted(args))}")

        ok = verify(conn)
    finally:
        conn.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
