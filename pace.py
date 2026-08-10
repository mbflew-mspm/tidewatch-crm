#!/usr/bin/env python3
"""
Tidewatch pace tracker — RevPAR & occupancy pace at equal days-to-arrival.

The problem it solves: comparing a future month's occupancy today against that
month's FINAL number last year is comparing an unfinished number to a finished
one, and absolute nights/revenue move with unit count. Fix: compare "on the
books as of today" vs "on the books at the same date last year", normalized per
available unit-night (occupancy %, RevPAR).

How last year's same-time reading is reconstructed: every reservation carries a
creation_date (booked-on). "October last year at 61 days out" = October-2025
stays whose creation_date <= (today - 365 days). Known limitation: bookings
that were on the books then but later cancelled are not counted, which slightly
understates last year's pace. Going forward, run this daily (cron) and it also
stores TRUE snapshots in pace_snapshots, so next year needs no reconstruction.

Modes:
  python3 pace.py pull       # refresh reservations for the window into SQLite
  python3 pace.py report     # print the pace report (text)
  python3 pace.py            # pull + report + save today's snapshot

Scope decisions (v1, deliberate):
  - Demand = all channels, type OWN (owner blocks) excluded, status_code 8
    (cancelled) excluded, INQR (inquiries) excluded.
  - Revenue = price_total prorated per night across the stay's months.
  - Available unit-nights = CURRENT active unit count x days in month, for both
    years (flagged in output; unit-count history isn't in the API).
"""

import datetime
import json
import os
import sqlite3
import time

from streamline import StreamlineClient, TokenStore

DB_PATH = os.environ.get("DB_PATH", "tidewatch.db")
MONTHS_AHEAD = int(os.environ.get("PACE_MONTHS_AHEAD", "6"))
PICKUP_DAYS = (7, 14)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pace_reservations (
  confirmation_id INTEGER PRIMARY KEY,
  type_name TEXT, status_code INTEGER, unit_id INTEGER,
  creation_date TEXT, startdate TEXT, enddate TEXT,
  days_number INTEGER, price_total REAL, hear_about TEXT,
  pulled_at TEXT
);
CREATE TABLE IF NOT EXISTS pace_snapshots (
  as_of TEXT, stay_month TEXT, days_out INTEGER,
  nights REAL, revenue REAL, occ_pct REAL, revpar REAL,
  PRIMARY KEY (as_of, stay_month)
);
CREATE TABLE IF NOT EXISTS pace_state (k TEXT PRIMARY KEY, v TEXT);
"""


def _data(p):
    d = p.get("data")
    if isinstance(d, dict):
        return d
    r = p.get("Response")
    return r.get("data", {}) if isinstance(r, dict) else {}


def _s(v):
    """Streamline returns {} for empty values; coerce to None/str."""
    if v is None or isinstance(v, (dict, list)):
        return None
    return str(v)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pdate(s):
    if not s:
        return None
    s = str(s).split()[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _month_add(d, n):
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return datetime.date(y, m, 1)


def _days_in_month(first):
    return (_month_add(first, 1) - first).days


# ---------------------------------------------------------------- pull
def pull(client, conn):
    """Refresh all reservations arriving from Jan 1 last year through the end
    of the analysis horizon, one month-window list call at a time."""
    today = datetime.date.today()
    start = datetime.date(today.year - 1, 1, 1)
    end = _month_add(datetime.date(today.year, today.month, 1), MONTHS_AHEAD + 1)
    n_windows = 0
    n_rows = 0
    cur = start
    while cur < end:
        nxt = _month_add(cur, 1)
        parsed = client.call("GetReservationsFiltered", {
            "arriving_after": (cur - datetime.timedelta(days=1)).isoformat(),
            "arriving_before": nxt.isoformat(),
            "return_full": "1",
        })
        rows = _data(parsed).get("reservations")
        if isinstance(rows, dict):
            rows = rows.get("reservation") or [rows]
        rows = rows or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            conn.execute(
                """INSERT INTO pace_reservations
                   (confirmation_id, type_name, status_code, unit_id, creation_date,
                    startdate, enddate, days_number, price_total, hear_about, pulled_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(confirmation_id) DO UPDATE SET
                    type_name=excluded.type_name, status_code=excluded.status_code,
                    unit_id=excluded.unit_id, creation_date=excluded.creation_date,
                    startdate=excluded.startdate, enddate=excluded.enddate,
                    days_number=excluded.days_number, price_total=excluded.price_total,
                    hear_about=excluded.hear_about, pulled_at=excluded.pulled_at""",
                (_num(r.get("confirmation_id")), _s(r.get("type_name")),
                 _num(r.get("status_code")), _num(r.get("unit_id")),
                 _s(r.get("creation_date")), _s(r.get("startdate")), _s(r.get("enddate")),
                 _num(r.get("days_number")), _num(r.get("price_total")),
                 _s(r.get("hear_about_name")),
                 datetime.datetime.now(datetime.timezone.utc).isoformat()))
            n_rows += 1
        conn.commit()
        n_windows += 1
        time.sleep(0.8)
        cur = nxt

    props = _data(client.call("GetPropertyList", {})).get("property") or []
    active = sum(1 for p in props if isinstance(p, dict) and _s(p.get("status_name")) == "Active")
    conn.execute("INSERT INTO pace_state(k,v) VALUES('active_units',?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(active or len(props)),))
    conn.execute("INSERT INTO pace_state(k,v) VALUES('last_pull',?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
    conn.commit()
    print(f"pull: {n_windows} month-windows, {n_rows} reservation rows upserted, "
          f"{active} active units")


# ---------------------------------------------------------------- compute
def _load(conn):
    """Demand bookings only: no inquiries, no owner blocks, no cancelled."""
    out = []
    for cid, tn, sc, cd, sd, ed, dn, pt in conn.execute(
            """SELECT confirmation_id, type_name, status_code, creation_date,
                      startdate, enddate, days_number, price_total
               FROM pace_reservations
               WHERE type_name NOT IN ('INQR','OWN')
                 AND (status_code IS NULL OR status_code != 8)"""):
        booked = _pdate(cd)
        s, e = _pdate(sd), _pdate(ed)
        if not (booked and s and e) or e <= s:
            continue
        nights = (e - s).days
        rate = (pt or 0) / nights if nights else 0
        out.append((booked, s, e, rate))
    return out


def _month_slice(res, month_first, cutoff, created_after=None):
    """Nights + prorated revenue falling inside stay-month, from bookings
    created on/before cutoff (and optionally after created_after)."""
    m_end = _month_add(month_first, 1)
    nights = 0
    revenue = 0.0
    for booked, s, e, rate in res:
        if booked > cutoff:
            continue
        if created_after and booked <= created_after:
            continue
        lo, hi = max(s, month_first), min(e, m_end)
        n = (hi - lo).days
        if n > 0:
            nights += n
            revenue += n * rate
    return nights, revenue


def compute(conn, as_of=None):
    as_of = as_of or datetime.date.today()
    res = _load(conn)
    st = dict(conn.execute("SELECT k, v FROM pace_state").fetchall())
    units = int(st.get("active_units", 0) or 0) or 1
    ly_as_of = as_of - datetime.timedelta(days=365)

    months = []
    this_month = datetime.date(as_of.year, as_of.month, 1)
    for i in range(0, MONTHS_AHEAD + 1):
        mf = _month_add(this_month, i)
        mf_ly = datetime.date(mf.year - 1, mf.month, 1)
        avail = units * _days_in_month(mf)
        avail_ly = units * _days_in_month(mf_ly)
        days_out = (mf - as_of).days

        n_ty, r_ty = _month_slice(res, mf, as_of)
        n_ly, r_ly = _month_slice(res, mf_ly, ly_as_of)
        n_lyf, r_lyf = _month_slice(res, mf_ly, as_of)  # LY final (all bookings)
        pickups = {}
        for pd in PICKUP_DAYS:
            pn, pr = _month_slice(res, mf, as_of,
                                  created_after=as_of - datetime.timedelta(days=pd))
            ln, lr = _month_slice(res, mf_ly, ly_as_of,
                                  created_after=ly_as_of - datetime.timedelta(days=pd))
            pickups[pd] = {"nights": pn, "revenue": round(pr),
                           "ly_nights": ln, "ly_revenue": round(lr)}

        months.append({
            "month": mf.isoformat()[:7],
            "days_out": days_out,
            "ty": {"nights": n_ty, "revenue": round(r_ty),
                   "occ_pct": round(100 * n_ty / avail, 1),
                   "revpar": round(r_ty / avail, 2)},
            "ly_same_time": {"nights": n_ly, "revenue": round(r_ly),
                             "occ_pct": round(100 * n_ly / avail_ly, 1),
                             "revpar": round(r_ly / avail_ly, 2)},
            "ly_final": {"occ_pct": round(100 * n_lyf / avail_ly, 1),
                         "revpar": round(r_lyf / avail_ly, 2)},
            "pickup": pickups,
        })
    return {
        "as_of": as_of.isoformat(),
        "active_units": units,
        "last_pull": st.get("last_pull"),
        "caveats": [
            "Denominator uses CURRENT active unit count for both years.",
            "Last-year same-time is reconstructed from booked-on dates; bookings that later cancelled aren't counted (slightly understates LY pace).",
            "Revenue = price_total (incl. fees) prorated per night.",
        ],
        "months": months,
    }


def snapshot(conn, report):
    for m in report["months"]:
        conn.execute(
            """INSERT INTO pace_snapshots
               (as_of, stay_month, days_out, nights, revenue, occ_pct, revpar)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(as_of, stay_month) DO UPDATE SET
                days_out=excluded.days_out, nights=excluded.nights,
                revenue=excluded.revenue, occ_pct=excluded.occ_pct,
                revpar=excluded.revpar""",
            (report["as_of"], m["month"], m["days_out"], m["ty"]["nights"],
             m["ty"]["revenue"], m["ty"]["occ_pct"], m["ty"]["revpar"]))
    conn.commit()


def print_report(rep):
    print(f"\nPACE  as of {rep['as_of']}  ·  {rep['active_units']} active units")
    print(f"{'month':<9}{'d.out':>6}{'occ TY':>8}{'occ LY@':>9}{'LY fin':>8}"
          f"{'RevPAR TY':>11}{'LY@':>8}{'pickup14 TY/LY (nts)':>22}")
    for m in rep["months"]:
        p = m["pickup"][14]
        print(f"{m['month']:<9}{m['days_out']:>6}{m['ty']['occ_pct']:>7}%"
              f"{m['ly_same_time']['occ_pct']:>8}%{m['ly_final']['occ_pct']:>7}%"
              f"{m['ty']['revpar']:>11}{m['ly_same_time']['revpar']:>8}"
              f"{str(p['nights'])+'/'+str(p['ly_nights']):>22}")
    print("\nCaveats: " + " ".join(rep["caveats"]))


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    if mode in ("pull", "all"):
        client = StreamlineClient(TokenStore(
            os.environ.get("TOKEN_STORE_PATH", "tokens.json"),
            os.environ["STREAMLINE_TOKEN_KEY"], os.environ["STREAMLINE_TOKEN_SECRET"]))
        pull(client, conn)
    rep = compute(conn)
    if mode in ("all",):
        snapshot(conn, rep)
    if mode == "json":
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)
    conn.close()


if __name__ == "__main__":
    main()
