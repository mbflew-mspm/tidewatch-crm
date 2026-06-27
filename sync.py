#!/usr/bin/env python3
"""
Tidewatch sync engine — pulls the reservation pipeline from Streamline into a
local SQLite cache, so the scoreboard reads from cache (not the API per request,
per Streamline's 100/min guidance).

Flow:
  1. GetReservationsFiltered  -> list of confirmation_ids (the pipeline)
  2. GetReservationInfo (per id, throttled, with agent + commission flags)
     -> sales agent, status, dates, commission, guest, raw record
  3. upsert into SQLite

Run:
  STREAMLINE_TOKEN_KEY=... STREAMLINE_TOKEN_SECRET=... python3 sync.py
Env:
  DB_PATH            (default tidewatch.db)
  SYNC_ARRIVING_AFTER(default today-365, YYYY-MM-DD) — pipeline window
  SYNC_LIMIT         (default 80) — max detail fetches this run (rate-friendly)
"""

import datetime
import json
import os
import sqlite3
import time

from streamline import StreamlineClient, TokenStore

DB_PATH = os.environ.get("DB_PATH", "tidewatch.db")
LIMIT = int(os.environ.get("SYNC_LIMIT", "100000"))
SKIP_CACHED = os.environ.get("SKIP_CACHED", "1") == "1"
DETAIL_FLAGS = {
    "show_agents_referrer_information": "1",
    "show_commission_information": "1",
    "show_payments_folio_history": "1",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS reservations (
  confirmation_id        INTEGER PRIMARY KEY,
  reservation_id         INTEGER,
  sales_agent            TEXT,
  status_code            INTEGER,
  status_id              INTEGER,
  lead_status_id         INTEGER,
  type_name              TEXT,
  startdate              TEXT,
  enddate                TEXT,
  creation_date          TEXT,
  last_updated           TEXT,
  guest_name             TEXT,
  email                  TEXT,
  phone                  TEXT,
  client_id              INTEGER,
  unit_name              TEXT,
  revenue                REAL,
  mgmt_commission_amount REAL,
  source                 TEXT,
  raw_json               TEXT,
  synced_at              TEXT
);
CREATE TABLE IF NOT EXISTS sync_state (k TEXT PRIMARY KEY, v TEXT);
"""


def _data(parsed):
    """Unwrap Streamline's {data:...} or {Response:{data:...}} envelope."""
    if not isinstance(parsed, dict):
        return {}
    if isinstance(parsed.get("data"), (dict, list)):
        return parsed["data"]
    resp = parsed.get("Response")
    if isinstance(resp, dict) and isinstance(resp.get("data"), (dict, list)):
        return resp["data"]
    return {}


def _g(d, *names, default=None):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def fetch_pipeline(client, method, params):
    parsed = client.call(method, params)
    data = _data(parsed)
    ids = data.get("confirmation_id") if isinstance(data, dict) else None
    if isinstance(ids, list):
        return [i for i in ids if i]
    return [ids] if ids else []


def fetch_detail(client, cid):
    parsed = client.call("GetReservationInfo", {"confirmation_id": cid, **DETAIL_FLAGS})
    data = _data(parsed)
    res = data.get("reservation") if isinstance(data, dict) else None
    return res if isinstance(res, dict) else None


def upsert(conn, res):
    name = " ".join(x for x in [_g(res, "first_name"), _g(res, "last_name")] if x) or None
    row = (
        _g(res, "confirmation_id"),
        _g(res, "id", "reservation_id"),
        _g(res, "sales_agent_name", "commissioned_agent_name"),
        _g(res, "status_code"),
        _g(res, "status_id"),
        _g(res, "lead_status_id"),
        _g(res, "type_name", "maketype_name"),
        _g(res, "startdate"),
        _g(res, "enddate"),
        _g(res, "creation_date"),
        _g(res, "last_updated"),
        name,
        _g(res, "email"),
        _g(res, "phone", "mobile_phone"),
        _g(res, "client_id"),
        _g(res, "unit_name"),
        _num(_g(res, "price_total")),
        _num(_g(res, "management_commission_amount")),
        _g(res, "hear_about_name", "source"),
        json.dumps(res)[:8000],
        datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    conn.execute(
        """INSERT INTO reservations
           (confirmation_id, reservation_id, sales_agent, status_code, status_id, lead_status_id,
            type_name, startdate, enddate, creation_date, last_updated, guest_name, email, phone,
            client_id, unit_name, revenue, mgmt_commission_amount, source, raw_json, synced_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(confirmation_id) DO UPDATE SET
            reservation_id=excluded.reservation_id, sales_agent=excluded.sales_agent,
            status_code=excluded.status_code, status_id=excluded.status_id,
            lead_status_id=excluded.lead_status_id, type_name=excluded.type_name,
            startdate=excluded.startdate, enddate=excluded.enddate,
            creation_date=excluded.creation_date, last_updated=excluded.last_updated,
            guest_name=excluded.guest_name, email=excluded.email, phone=excluded.phone,
            client_id=excluded.client_id, unit_name=excluded.unit_name, revenue=excluded.revenue,
            mgmt_commission_amount=excluded.mgmt_commission_amount, source=excluded.source,
            raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
        row,
    )


def run_incremental(client, conn):
    """Cheap refresh: only NEW inquiries + reservations changed since yesterday."""
    since = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    inq_ids = fetch_pipeline(client, "GetReservations", {"type_name": "INQR"})
    have = {r[0] for r in conn.execute("SELECT confirmation_id FROM reservations")}
    new_inq = [c for c in inq_ids if c not in have]
    changed = fetch_pipeline(client, "GetReservationsFiltered", {"modified_since": since})
    todo = list(dict.fromkeys(new_inq + changed))[:500]
    print(f"Incremental: {len(new_inq)} new inquiries, {len(changed)} changed since {since}; "
          f"fetching {len(todo)}", flush=True)
    n = 0
    for cid in todo:
        res = fetch_detail(client, cid)
        time.sleep(0.8)
        if res:
            upsert(conn, res)
            n += 1
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k, v in (("inquiries_total", str(len(inq_ids))), ("last_sync", now)):
        conn.execute("INSERT INTO sync_state(k,v) VALUES(?,?) "
                     "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    conn.commit()
    print(f"Incremental done: {n} upserted at {now}", flush=True)


def main():
    if not os.environ.get("STREAMLINE_TOKEN_KEY"):
        raise SystemExit("Missing STREAMLINE_TOKEN_KEY / STREAMLINE_TOKEN_SECRET")
    arriving_after = os.environ.get(
        "SYNC_ARRIVING_AFTER",
        (datetime.date.today() - datetime.timedelta(days=365)).isoformat(),
    )
    client = StreamlineClient(TokenStore(
        os.environ.get("TOKEN_STORE_PATH", "tokens.json"),
        os.environ["STREAMLINE_TOKEN_KEY"], os.environ["STREAMLINE_TOKEN_SECRET"]))

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    if os.environ.get("SYNC_MODE") == "incremental":
        run_incremental(client, conn)
        conn.close()
        return

    print("Listing inquiry funnel: GetReservations(type_name=INQR) ...")
    inq_ids = fetch_pipeline(client, "GetReservations", {"type_name": "INQR"})
    print(f"  -> {len(inq_ids)} inquiries")
    print("Listing direct bookings: GetReservations(type_name=STA) ...")
    sta_ids = fetch_pipeline(client, "GetReservations", {"type_name": "STA"})
    print(f"  -> {len(sta_ids)} direct (STA) reservations")

    for k, v in (("inquiries_total", len(inq_ids)), ("direct_total", len(sta_ids))):
        conn.execute("INSERT INTO sync_state(k,v) VALUES(?,?) "
                     "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    all_ids = list(dict.fromkeys(inq_ids + sta_ids))
    if SKIP_CACHED:
        have = {r[0] for r in conn.execute("SELECT confirmation_id FROM reservations")}
        all_ids = [c for c in all_ids if c not in have]
    todo = all_ids[:LIMIT]
    print(f"Fetching detail for {len(todo)} new reservations ...", flush=True)
    fetched = 0
    for i, cid in enumerate(todo, 1):
        res = fetch_detail(client, cid)
        time.sleep(0.8)  # under 100/min
        if res:
            upsert(conn, res)
            fetched += 1
        if i % 100 == 0:
            conn.commit()
            print(f"  ...{i}/{len(todo)} fetched", flush=True)

    conn.commit()
    conn.execute("INSERT INTO sync_state(k,v) VALUES('last_sync',?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
    conn.commit()

    print(f"\nStored {fetched} reservations in {DB_PATH}.\n")
    inq = conn.execute("SELECT COUNT(*) FROM reservations WHERE type_name='INQR'").fetchone()[0]
    direct = conn.execute("SELECT COUNT(*) FROM reservations "
                          "WHERE type_name!='INQR' AND sales_agent IS NOT NULL").fetchone()[0]
    ota = conn.execute("SELECT COUNT(*) FROM reservations "
                       "WHERE type_name!='INQR' AND sales_agent IS NULL").fetchone()[0]
    print("Cached mix:")
    print(f"  inquiries (INQR):            {inq}")
    print(f"  rep-worked bookings:         {direct}")
    print(f"  OTA self-bookings (no rep):  {ota}")

    print("\nPer-reservationist (rep-worked bookings):")
    for agent, n, rev, comm in conn.execute(
            """SELECT sales_agent, COUNT(*) n, ROUND(SUM(COALESCE(revenue,0)),0) rev,
                      ROUND(SUM(COALESCE(mgmt_commission_amount,0)),0) comm
               FROM reservations WHERE sales_agent IS NOT NULL AND type_name!='INQR'
               GROUP BY sales_agent ORDER BY rev DESC"""):
        print(f"  {agent:<22} {n:>3} bookings   ${rev:,.0f} rev   ${comm:,.0f} comm")
    conn.close()


if __name__ == "__main__":
    main()
