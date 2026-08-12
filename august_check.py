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
for sd, ed, cd, pt, pr, tn in c.execute(
        """SELECT startdate, enddate, creation_date, price_total, price_rent, type_name
           FROM pace_reservations
           WHERE type_name NOT IN ('INQR','OWN','MaintenanceBlock')
             AND (status_code IS NULL OR status_code != 9)"""):
    s, e, b = pd(sd), pd(ed), pd(cd)
    if s and e and b and e > s:
        rows.append((s, e, b, float(pt or 0), float(pr or 0), (e - s).days))

today = datetime.date(2026, 8, 11)
ly_today = today - datetime.timedelta(days=365)


def stay_month_revenue(y, cutoff):
    mf, nxt = datetime.date(y, 8, 1), datetime.date(y, 9, 1)
    rev = rent = nights = 0
    for s, e, b, pt, pr, dn in rows:
        if b > cutoff:
            continue
        lo, hi = max(s, mf), min(e, nxt)
        n = (hi - lo).days
        if n > 0:
            nights += n
            rev += pt / dn * n
            rent += pr / dn * n
    return rev, rent, nights


a_ty, r_ty, n_ty = stay_month_revenue(2026, today)
a_ly, r_ly, n_ly = stay_month_revenue(2025, ly_today)

print("AUGUST STAYS on the books (prorated), guest-total vs RENT-ONLY:")
print(f"  Aug 2026 as of 8/11/26:  total ${a_ty:>9,.0f}   RENT ${r_ty:>9,.0f}   ({n_ty} nights)")
print(f"  Aug 2025 as of 8/11/25:  total ${a_ly:>9,.0f}   RENT ${r_ly:>9,.0f}   ({n_ly} nights)")
print(f"  YoY:  total {100*a_ty/a_ly - 100:+.1f}%   RENT {100*r_ty/r_ly - 100:+.1f}%")
print()
print("sanity: rent share of total  TY "
      f"{100*r_ty/a_ty:.0f}%   LY {100*r_ly/a_ly:.0f}%")
