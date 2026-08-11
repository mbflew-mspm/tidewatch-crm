#!/usr/bin/env python3
"""Reconcile JC's 'August gross income is ahead' with the pace page's 'August
slightly behind': compute Aug 2026 vs Aug 2025 on several bases. Read-only."""
import datetime
import sqlite3

c = sqlite3.connect("tidewatch.db")


def pd(s):
    try:
        return datetime.datetime.strptime(str(s).split()[0], "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


rows = []
for sd, ed, cd, pt, tn in c.execute(
        """SELECT startdate, enddate, creation_date, price_total, type_name
           FROM pace_reservations
           WHERE type_name NOT IN ('INQR','OWN','MaintenanceBlock')
             AND (status_code IS NULL OR status_code != 9)"""):
    s, e, b = pd(sd), pd(ed), pd(cd)
    if s and e and b and e > s:
        rows.append((s, e, b, float(pt or 0), (e - s).days))

today = datetime.date(2026, 8, 11)
ly_today = today - datetime.timedelta(days=365)


def stay_month_revenue(y, cutoff):
    mf, nxt = datetime.date(y, 8, 1), datetime.date(y, 9, 1)
    rev = nights = 0
    for s, e, b, pt, dn in rows:
        if b > cutoff:
            continue
        lo, hi = max(s, mf), min(e, nxt)
        n = (hi - lo).days
        if n > 0:
            nights += n
            rev += pt / dn * n
    return rev, nights


def booked_in_window(y):
    """Full value of bookings MADE Aug 1-11 of year y (any stay dates)."""
    w0, w1 = datetime.date(y, 8, 1), datetime.date(y, 8, 11)
    rev = cnt = 0
    for s, e, b, pt, dn in rows:
        if w0 <= b <= w1:
            rev += pt
            cnt += 1
    return rev, cnt


a_ty, n_ty = stay_month_revenue(2026, today)
a_ly, n_ly = stay_month_revenue(2025, ly_today)
a_lyf, n_lyf = stay_month_revenue(2025, datetime.date(2026, 8, 11))
c_ty, k_ty = booked_in_window(2026)
c_ly, k_ly = booked_in_window(2025)

print("AUGUST STAYS — revenue on the books for August stay-nights (prorated):")
print(f"  Aug 2026 as of 8/11/26:   ${a_ty:>10,.0f}   ({n_ty} nights)")
print(f"  Aug 2025 as of 8/11/25:   ${a_ly:>10,.0f}   ({n_ly} nights)")
print(f"  Aug 2025 final:           ${a_lyf:>10,.0f}   ({n_lyf} nights)")
print()
print("SALES MADE Aug 1-11 — full value of bookings created in the window:")
print(f"  2026: ${c_ty:>10,.0f}  ({k_ty} bookings)")
print(f"  2025: ${c_ly:>10,.0f}  ({k_ly} bookings)")
