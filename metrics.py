#!/usr/bin/env python3
"""
Reservationist scoreboard from the local cache (tidewatch.db), with period scoping.

Scope = rep-worked business:
  - inquiries = type_name='INQR' (the lead pool, incl. open + lost)
  - bookings  = sales_agent set and type_name != 'INQR'
  - OTA self-bookings (no sales_agent) excluded.

Period filters on creation_date (when the reservation/inquiry was created):
  month | quarter | year | all

Close rate (period) = rep bookings created in period
                      / (rep bookings + inquiries created in period)
i.e. "of the leads received this period, the share that booked." Labeled as such.
"""
import datetime
import json
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "tidewatch.db")


def _parse_date(s):
    if not s:
        return None
    s = str(s).split()[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _period_start(period):
    t = datetime.date.today()
    if period == "month":
        return t.replace(day=1)
    if period == "quarter":
        return t.replace(month=((t.month - 1) // 3) * 3 + 1, day=1)
    if period == "year":
        return t.replace(month=1, day=1)
    return None  # all-time


def compute(conn, period="all"):
    start = _period_start(period)
    rows = conn.execute(
        "SELECT sales_agent, type_name, revenue, creation_date, source FROM reservations"
    ).fetchall()

    reps, sources, inquiries = {}, {}, 0
    for agent, type_name, revenue, cd, source in rows:
        if start is not None:
            d = _parse_date(cd)
            if d is None or d < start:
                continue
        if type_name == "INQR":
            inquiries += 1
            key = source or "(unknown)"
            sources[key] = sources.get(key, 0) + 1
        elif agent:
            r = reps.setdefault(agent, {"agent": agent, "bookings": 0, "revenue": 0.0})
            r["bookings"] += 1
            r["revenue"] += float(revenue or 0)

    per_rep = sorted(reps.values(), key=lambda x: -x["revenue"])
    for r in per_rep:
        r["revenue"] = round(r["revenue"])
        r["avg_booking"] = round(r["revenue"] / r["bookings"]) if r["bookings"] else 0

    rep_bookings = sum(r["bookings"] for r in per_rep)
    rep_revenue = sum(r["revenue"] for r in per_rep)
    denom = rep_bookings + inquiries
    close = round(100 * rep_bookings / denom, 1) if denom else 0
    src = sorted(({"source": k, "count": v} for k, v in sources.items()),
                 key=lambda x: -x["count"])[:8]
    st = dict(conn.execute("SELECT k, v FROM sync_state").fetchall())

    return {
        "period": period,
        "funnel": {
            "inquiries_open": inquiries,
            "rep_bookings": rep_bookings,
            "rep_revenue": rep_revenue,
            "team_close_rate_pct": close,
        },
        "per_rep": per_rep,
        "sources": src,
        "last_sync": st.get("last_sync"),
    }


def main():
    period = "all"
    for a in sys.argv[1:]:
        if a in ("month", "quarter", "year", "all"):
            period = a
    conn = sqlite3.connect(DB_PATH)
    result = compute(conn, period)
    conn.close()
    if "--text" in sys.argv:
        f = result["funnel"]
        print(f"[{period}] inquiries {f['inquiries_open']} | bookings {f['rep_bookings']} "
              f"| revenue ${f['rep_revenue']:,.0f} | close {f['team_close_rate_pct']}%")
        for r in result["per_rep"]:
            print(f"  {r['agent']:<22} {r['bookings']:>4} bk  ${r['revenue']:,.0f}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
