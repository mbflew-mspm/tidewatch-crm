#!/usr/bin/env python3
"""
Compute the reservationist scoreboard from the local cache (tidewatch.db).

Scope = rep-worked business:
  - inquiries  = reservations with type_name='INQR' (the lead pool)
  - bookings   = reservations with a sales_agent and type_name != 'INQR'
  - OTA self-bookings (no sales_agent) are excluded from rep metrics.

Outputs JSON (default) or a text summary (--text).
"""
import json
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "tidewatch.db")


def compute(conn):
    st = dict(conn.execute("SELECT k, v FROM sync_state").fetchall())
    inquiries_total = int(st.get("inquiries_total", 0) or 0)

    per_rep = []
    for agent, n, rev, avg in conn.execute(
            """SELECT sales_agent, COUNT(*) n,
                      ROUND(SUM(COALESCE(revenue,0)),0) rev,
                      ROUND(AVG(COALESCE(revenue,0)),0) avg
               FROM reservations
               WHERE sales_agent IS NOT NULL AND type_name!='INQR'
               GROUP BY sales_agent ORDER BY rev DESC"""):
        per_rep.append({"agent": agent, "bookings": n, "revenue": rev, "avg_booking": avg})

    rep_bookings = sum(r["bookings"] for r in per_rep)
    rep_revenue = sum(r["revenue"] for r in per_rep)
    # Team close rate (rough): rep-worked bookings vs the open inquiry pool.
    close_rate = round(100 * rep_bookings / (rep_bookings + inquiries_total), 1) if (rep_bookings + inquiries_total) else 0

    sources = [
        {"source": s or "(unknown)", "count": n}
        for s, n in conn.execute(
            """SELECT source, COUNT(*) FROM reservations
               WHERE type_name='INQR' GROUP BY source ORDER BY 2 DESC LIMIT 8""")
    ]

    cached = dict(conn.execute(
        """SELECT CASE WHEN type_name='INQR' THEN 'inquiries'
                       WHEN sales_agent IS NOT NULL THEN 'rep_bookings'
                       ELSE 'ota_bookings' END bucket, COUNT(*)
           FROM reservations GROUP BY bucket""").fetchall())

    return {
        "funnel": {
            "inquiries_open": inquiries_total,
            "rep_bookings": rep_bookings,
            "rep_revenue": rep_revenue,
            "team_close_rate_pct": close_rate,
        },
        "per_rep": per_rep,
        "sources": sources,
        "cached_counts": cached,
        "last_sync": st.get("last_sync"),
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    result = compute(conn)
    conn.close()
    if "--text" in sys.argv:
        f = result["funnel"]
        print(f"Inquiries(open) {f['inquiries_open']} | rep bookings {f['rep_bookings']} "
              f"| rep revenue ${f['rep_revenue']:,.0f} | close {f['team_close_rate_pct']}%")
        for r in result["per_rep"]:
            print(f"  {r['agent']:<22} {r['bookings']:>3} bk  ${r['revenue']:,.0f}  avg ${r['avg_booking']:,.0f}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
