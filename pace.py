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
  - Demand = all channels; excluded: INQR (inquiries), OWN + MaintenanceBlock
    (blocks, not guest demand), status_code 9 (cancelled — verified: ~$0 avg
    revenue across all types; status 8 is the normal confirmed/completed state).
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
  days_number INTEGER, price_total REAL, price_rent REAL, hear_about TEXT,
  maketype TEXT,
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
                    startdate, enddate, days_number, price_total, price_rent,
                    hear_about, maketype, pulled_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(confirmation_id) DO UPDATE SET
                    type_name=excluded.type_name, status_code=excluded.status_code,
                    unit_id=excluded.unit_id, creation_date=excluded.creation_date,
                    startdate=excluded.startdate, enddate=excluded.enddate,
                    days_number=excluded.days_number, price_total=excluded.price_total,
                    price_rent=excluded.price_rent,
                    hear_about=excluded.hear_about, maketype=excluded.maketype,
                    pulled_at=excluded.pulled_at""",
                (_num(r.get("confirmation_id")), _s(r.get("type_name")),
                 _num(r.get("status_code")), _num(r.get("unit_id")),
                 _s(r.get("creation_date")), _s(r.get("startdate")), _s(r.get("enddate")),
                 _num(r.get("days_number")), _num(r.get("price_total")),
                 _num(r.get("price_nightly")),  # rent subtotal (rent-only, no fees/taxes)
                 _s(r.get("hear_about_name")), _s(r.get("maketype_name")),
                 datetime.datetime.now(datetime.timezone.utc).isoformat()))
            n_rows += 1
        conn.commit()
        n_windows += 1
        time.sleep(0.8)
        cur = nxt

    props = _data(client.call("GetPropertyList", {})).get("property") or []
    # Count UNIQUE ids — the API has returned inflated/duplicated lists on
    # some calls (157 one pull, 199 another for the same fleet).
    active_ids = {p.get("id") for p in props if isinstance(p, dict)
                  and _s(p.get("status_name")) == "Active" and p.get("id")}
    active = len(active_ids) or len({p.get("id") for p in props
                                     if isinstance(p, dict) and p.get("id")})
    if active >= 10:
        # Only store a sane value; a failed/empty property call must NEVER
        # overwrite the last good unit count (a bad denominator poisons
        # every percentage on the page).
        conn.execute("INSERT INTO pace_state(k,v) VALUES('active_units',?) "
                     "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(active),))
    else:
        print(f"WARNING: GetPropertyList returned {active} units — keeping last good count")
    conn.execute("INSERT INTO pace_state(k,v) VALUES('last_pull',?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
    conn.commit()
    print(f"pull: {n_windows} month-windows, {n_rows} reservation rows upserted, "
          f"{active} active units")


# ---------------------------------------------------------------- compute
OTA_TYPES = {"SC-ABnB", "HAFamOLB", "SC-Booking.com", "HomeToGo", "BOOST (PDWTA)", "PGO"}

# Calibration to Streamline's own Revenue Pacing Report ("Sales as 08/12/2025",
# from Matt's export on 2026-08-12). Our last-year reconstruction only sees each
# booking's FINAL value, so modifications made after the as-of date inflate our
# baseline; these are the true on-the-books values per stay month. We anchor a
# per-month correction ratio (Streamline / our reconstruction at the same
# cutoff) and apply it to the reconstructed LY revenue.
SL_ASOF_LY = {
    (2025, 8): 422318.57, (2025, 9): 220044.01, (2025, 10): 139298.31,
    (2025, 11): 62925.93, (2025, 12): 43264.88,
}
SL_ANCHOR = datetime.date(2025, 8, 12)


def _calibration_ratio(res, mf_ly):
    """Correction ratio for one last-year stay month; (1.0, False) if we have
    no Streamline anchor for it."""
    key = (mf_ly.year, mf_ly.month)
    if key not in SL_ASOF_LY:
        return 1.0, False
    _n, mine = _month_slice(res, mf_ly, SL_ANCHOR)
    if mine <= 0:
        return 1.0, False
    ratio = SL_ASOF_LY[key] / mine
    return min(max(ratio, 0.5), 1.2), True


def _bucket(type_name, maketype):
    """Who produced the booking: our reservationists ('team'), guests
    self-booking the website ('web'), or the OTA channels ('ota')."""
    if (type_name or "") in OTA_TYPES:
        return "ota"
    if (maketype or "").upper().startswith("A"):  # 'A' = Admin Reservation (rep-made)
        return "team"
    return "web"


def _fleet_index(conn):
    """Per-month fleet reality, derived from the calendar itself:
    for each stay-month, the set of units with ANY non-cancelled record
    (booking or block) touching it, plus the owner/maintenance blocked nights.
    Validated against the hand-kept scorecard (169-170 derived vs 171-172
    recorded for Jun 2025) and RevMax occupancy levels."""
    idx = {}
    for sd, ed, u, tn in conn.execute(
            """SELECT startdate, enddate, unit_id, type_name FROM pace_reservations
               WHERE type_name != 'INQR'
                 AND (status_code IS NULL OR status_code != 9)"""):
        s, e = _pdate(sd), _pdate(ed)
        if not (s and e and u) or e <= s:
            continue
        mf = datetime.date(s.year, s.month, 1)
        while mf < e:
            nxt = _month_add(mf, 1)
            n = (min(e, nxt) - max(s, mf)).days
            if n > 0:
                slot = idx.setdefault(mf, {"units": set(), "blocked": 0})
                slot["units"].add(u)
                if tn in ("OWN", "MaintenanceBlock"):
                    slot["blocked"] += n
            mf = nxt
    return idx


def _avail_nights(fleet, month_first, active_now, today):
    """Rentable (available) nights for one month: live units x days, minus
    blocked nights. Past months use the derived fleet (final truth); current/
    future months floor the fleet at today's active count, since units with no
    activity recorded *yet* are still listed and available."""
    slot = fleet.get(month_first, {"units": set(), "blocked": 0})
    derived = len(slot["units"])
    cur_month = datetime.date(today.year, today.month, 1)
    live = max(derived, active_now) if month_first >= cur_month else (derived or active_now)
    return max(live * _days_in_month(month_first) - slot["blocked"], 1), live


def _load(conn):
    """Demand bookings only: no inquiries, no owner blocks, no cancelled."""
    out = []
    for tn, sc, cd, sd, ed, pt, mk in conn.execute(
            """SELECT type_name, status_code, creation_date,
                      startdate, enddate, price_total, maketype
               FROM pace_reservations
               WHERE type_name NOT IN ('INQR','OWN','MaintenanceBlock')
                 AND (status_code IS NULL OR status_code != 9)"""):
        booked = _pdate(cd)
        s, e = _pdate(sd), _pdate(ed)
        if not (booked and s and e) or e <= s:
            continue
        nights = (e - s).days
        rate = (pt or 0) / nights if nights else 0
        out.append((booked, s, e, rate, _bucket(tn, mk)))
    return out


def _month_slice(res, month_first, cutoff, created_after=None, bucket=None):
    """Nights + prorated revenue falling inside stay-month, from bookings
    created on/before cutoff (and optionally after created_after)."""
    m_end = _month_add(month_first, 1)
    nights = 0
    revenue = 0.0
    for booked, s, e, rate, bk in res:
        if booked > cutoff:
            continue
        if created_after and booked <= created_after:
            continue
        if bucket and bk != bucket:
            continue
        lo, hi = max(s, month_first), min(e, m_end)
        n = (hi - lo).days
        if n > 0:
            nights += n
            revenue += n * rate
    return nights, revenue


def _units(conn, st):
    """Active-unit count with a belt-and-suspenders fallback: if the stored
    value is missing/absurd, approximate the fleet as the distinct units with
    a stay in the last 12 months — never divide by 1."""
    units = int(st.get("active_units", 0) or 0)
    if units >= 10:
        return units
    row = conn.execute(
        "SELECT COUNT(DISTINCT unit_id) FROM pace_reservations "
        "WHERE type_name NOT IN ('INQR','OWN','MaintenanceBlock')").fetchone()
    return (row[0] if row and row[0] else 0) or 150


def compute(conn, as_of=None):
    as_of = as_of or datetime.date.today()
    res = _load(conn)
    st = dict(conn.execute("SELECT k, v FROM pace_state").fetchall())
    units = _units(conn, st)
    fleet = _fleet_index(conn)
    today = datetime.date.today()
    ly_as_of = as_of - datetime.timedelta(days=365)

    months = []
    this_month = datetime.date(as_of.year, as_of.month, 1)
    for i in range(0, MONTHS_AHEAD + 1):
        mf = _month_add(this_month, i)
        mf_ly = datetime.date(mf.year - 1, mf.month, 1)
        avail, live_ty = _avail_nights(fleet, mf, units, today)
        avail_ly, live_ly = _avail_nights(fleet, mf_ly, units, today)
        days_out = (mf - as_of).days

        n_ty, r_ty = _month_slice(res, mf, as_of)
        n_ly, r_ly = _month_slice(res, mf_ly, ly_as_of)
        ratio, calibrated = _calibration_ratio(res, mf_ly)
        r_ly *= ratio
        n_lyf, r_lyf = _month_slice(res, mf_ly, as_of)  # LY final (all bookings)
        pickups = {}
        for pd in PICKUP_DAYS:
            pn, pr = _month_slice(res, mf, as_of,
                                  created_after=as_of - datetime.timedelta(days=pd))
            ln, lr = _month_slice(res, mf_ly, ly_as_of,
                                  created_after=ly_as_of - datetime.timedelta(days=pd))
            pickups[pd] = {"nights": pn, "revenue": round(pr),
                           "ly_nights": ln, "ly_revenue": round(lr)}

        channels = {}
        for b in ("team", "web", "ota"):
            bn, _br = _month_slice(res, mf, as_of, bucket=b)
            bln, _blr = _month_slice(res, mf_ly, ly_as_of, bucket=b)
            channels[b] = {"nights": bn, "ly_nights": bln}

        months.append({
            "month": mf.isoformat()[:7],
            "days_out": days_out,
            "ty": {"nights": n_ty, "revenue": round(r_ty),
                   "occ_pct": round(100 * n_ty / avail, 1),
                   "revpar": round(r_ty / avail, 2),
                   "adr": round(r_ty / n_ty) if n_ty else 0},
            "ly_same_time": {"nights": n_ly, "revenue": round(r_ly),
                             "occ_pct": round(100 * n_ly / avail_ly, 1),
                             "revpar": round(r_ly / avail_ly, 2),
                             "adr": round(r_ly / n_ly) if n_ly else 0},
            "ly_final": {"occ_pct": round(100 * n_lyf / avail_ly, 1),
                         "revpar": round(r_lyf / avail_ly, 2)},
            "pickup": pickups,
            "channels": channels,
            "live_units": {"ty": live_ty, "ly": live_ly},
            "ly_calibrated": calibrated,
        })
    return {
        "as_of": as_of.isoformat(),
        "active_units": units,
        "last_pull": st.get("last_pull"),
        "caveats": [
            "Money = the homes' GROSS booking revenue (guest total incl. fees), not TideWatch's commission income.",
            "Available nights = each month's own live-unit count (derived from calendar activity, per year) minus owner/maintenance-blocked nights.",
            "Last-year same-time is reconstructed from booked-on dates; money baselines for Aug-Dec 2025 are calibrated to Streamline's Revenue Pacing report (as-of 8/12/2025).",
        ],
        "months": months,
    }


def _window_slice(res, w_start, w_end, cutoff):
    """Nights + prorated revenue inside [w_start, w_end) from bookings
    created on/before cutoff."""
    nights = 0
    revenue = 0.0
    for booked, s, e, rate, _bk in res:
        if booked > cutoff:
            continue
        lo, hi = max(s, w_start), min(e, w_end)
        n = (hi - lo).days
        if n > 0:
            nights += n
            revenue += n * rate
    return nights, revenue


def scorecard_metrics(res, fleet, units, as_of, today):
    """The three scorecard numbers for one as-of date, over the window
    'current month + next two months' (matches the old H/I columns):
      occ_ty   — occupancy % on the books for the window (of available nights)
      occ_ly   — same window last year, as of the same date last year
      pace_pct — RevPAR pace: TY per-available-night revenue / LY same-time, x100
    """
    w_start = datetime.date(as_of.year, as_of.month, 1)
    w_end = _month_add(w_start, 3)
    ly_start = datetime.date(w_start.year - 1, w_start.month, 1)
    ly_end = _month_add(ly_start, 3)
    ly_as_of = as_of - datetime.timedelta(days=365)

    avail = avail_ly = 0
    n_ly = r_ly = 0
    for i in range(3):
        a, _ = _avail_nights(fleet, _month_add(w_start, i), units, today)
        al, _ = _avail_nights(fleet, _month_add(ly_start, i), units, today)
        avail += a
        avail_ly += al
        mly = _month_add(ly_start, i)
        n_m, r_m = _month_slice(res, mly, ly_as_of)
        ratio, _cal = _calibration_ratio(res, mly)
        n_ly += n_m
        r_ly += r_m * ratio
    n_ty, r_ty = _window_slice(res, w_start, w_end, as_of)

    revpar_ty = r_ty / avail if avail else 0
    revpar_ly = r_ly / avail_ly if avail_ly else 0
    return {
        "occ_ty": round(100 * n_ty / avail, 1) if avail else 0,
        "occ_ly": round(100 * n_ly / avail_ly, 1) if avail_ly else 0,
        "pace_pct": round(100 * revpar_ty / revpar_ly, 1) if revpar_ly else None,
    }


def scorecard_history_csv(conn):
    """One row per Wednesday (the scorecard's weekly cadence) from Jan 2026 to
    today. Starts 2026 because the LY comparison needs stay data back to Jan
    2025, which is where our pull begins."""
    res = _load(conn)
    st = dict(conn.execute("SELECT k, v FROM pace_state").fetchall())
    units = _units(conn, st)
    fleet = _fleet_index(conn)
    today = datetime.date.today()
    d = datetime.date(2026, 1, 1)
    while d.weekday() != 2:  # Wednesday
        d += datetime.timedelta(days=1)
    lines = ["Week,Occupancy booked next 3 months,Same point last year,"
             "Pace vs last year"]
    while d <= today:
        m = scorecard_metrics(res, fleet, units, d, today)
        # Values carry their own % sign so Sheets parses them as true
        # percentages — user-applied percent formatting can't inflate them.
        pace = f"{m['pace_pct']}%" if m['pace_pct'] is not None else ""
        lines.append(f"{d.strftime('%m/%d/%Y')},{m['occ_ty']}%,{m['occ_ly']}%,{pace}")
        d += datetime.timedelta(days=7)
    return "\n".join(lines) + "\n"


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
    for mig in ("ALTER TABLE pace_reservations ADD COLUMN maketype TEXT",
                "ALTER TABLE pace_reservations ADD COLUMN price_rent REAL"):
        try:  # migrations for tables created before these columns existed
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass
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
