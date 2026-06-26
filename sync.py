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
LIMIT = int(os.environ.get("SYNC_LIMIT", "80"))
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
  lead_status_id         INTEGER,
  startdate              TEXT,
  enddate                TEXT,
  creation_date          TEXT,
  email                  TEXT,
  client_id              INTEGER,
  mgmt_commission_amount REAL,
  mgmt_commission_pct    REAL,
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


def fetch_pipeline(client, arriving_after):
    parsed = client.call("GetReservationsFiltered", {"arriving_after": arriving_after})
    data = _data(parsed)
    ids = data.get("confirmation_id") if isinstance(data, dict) else None
    if isinstance(ids, list):
        return [i for i in ids if i]
    if ids:
        return [ids]
    return []


def fetch_detail(client, cid):
    parsed = client.call("GetReservationInfo", {"confirmation_id": cid, **DETAIL_FLAGS})
    data = _data(parsed)
    res = data.get("reservation") if isinstance(data, dict) else None
    return res if isinstance(res, dict) else None


def upsert(conn, res):
    row = (
        _g(res, "confirmation_id"),
        _g(res, "id", "reservation_id"),
        _g(res, "sales_agent_name", "commissioned_agent_name"),
        _g(res, "status_code"),
        _g(res, "lead_status_id"),
        _g(res, "startdate"),
        _g(res, "enddate"),
        _g(res, "creation_date"),
        _g(res, "email"),
        _g(res, "client_id"),
        _g(res, "management_commission_amount"),
        _g(res, "management_commission_percent"),
        _g(res, "hear_about_name", "source", "referrer_url"),
        json.dumps(res)[:8000],
        datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    conn.execute(
        """INSERT INTO reservations
           (confirmation_id, reservation_id, sales_agent, status_code, lead_status_id,
            startdate, enddate, creation_date, email, client_id,
            mgmt_commission_amount, mgmt_commission_pct, source, raw_json, synced_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(confirmation_id) DO UPDATE SET
            reservation_id=excluded.reservation_id, sales_agent=excluded.sales_agent,
            status_code=excluded.status_code, lead_status_id=excluded.lead_status_id,
            startdate=excluded.startdate, enddate=excluded.enddate,
            creation_date=excluded.creation_date, email=excluded.email,
            client_id=excluded.client_id, mgmt_commission_amount=excluded.mgmt_commission_amount,
            mgmt_commission_pct=excluded.mgmt_commission_pct, source=excluded.source,
            raw_json=excluded.raw_json, synced_at=excluded.synced_at""",
        row,
    )


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

    print(f"Pipeline: GetReservationsFiltered(arriving_after={arriving_after}) ...")
    cids = fetch_pipeline(client, arriving_after)
    print(f"  -> {len(cids)} reservations in pipeline; fetching detail for up to {LIMIT}")

    fetched = 0
    field_keys_dumped = False
    for cid in cids[:LIMIT]:
        res = fetch_detail(client, cid)
        time.sleep(0.8)  # under 100/min
        if not res:
            continue
        if not field_keys_dumped:
            print("  FIELDS AVAILABLE on a reservation:", sorted(res.keys()))
            field_keys_dumped = True
        upsert(conn, res)
        fetched += 1

    conn.commit()
    conn.execute("INSERT INTO sync_state(k,v) VALUES('last_sync',?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
    conn.commit()

    print(f"\nStored {fetched} reservations in {DB_PATH}.\n")
    print("Per-reservationist snapshot (cached rows):")
    q = conn.execute(
        """SELECT COALESCE(sales_agent,'(unassigned)') agent, COUNT(*) n,
                  ROUND(SUM(COALESCE(mgmt_commission_amount,0)),0) commission
           FROM reservations GROUP BY agent ORDER BY n DESC""")
    for agent, n, commission in q.fetchall():
        print(f"  {agent:<22} {n:>4} reservations   commission ${commission:,.0f}")
    print("\nBy status_code:")
    for sc, n in conn.execute(
            "SELECT status_code, COUNT(*) FROM reservations GROUP BY status_code ORDER BY 2 DESC"):
        print(f"  status_code {sc}: {n}")
    conn.close()


if __name__ == "__main__":
    main()
