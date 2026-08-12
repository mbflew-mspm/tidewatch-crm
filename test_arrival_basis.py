#!/usr/bin/env python3
"""THE test: can the API reproduce Streamline's Revenue Pacing numbers with
NO manual calibration, using arrival-month attribution (full booking value
credited to the arrival month, bookings created <= the as-of cutoff)?

14 ground-truth values from Matt's two report exports. If this matches, the
manual-feed problem is dead: my 'modification bias' was actually a
counting-method difference all along."""
import datetime
import sqlite3

A25 = datetime.date(2025, 8, 12)
A26 = datetime.date(2026, 8, 12)
SL = {
    (2025, 8): (422318.57, A25), (2025, 9): (220044.01, A25),
    (2025, 10): (139298.31, A25), (2025, 11): (62925.93, A25),
    (2025, 12): (43264.88, A25),
    (2026, 1): (16119.44, A25), (2026, 2): (30158.41, A25),
    (2026, 8): (468289.12, A26), (2026, 9): (211252.97, A26),
    (2026, 10): (163560.08, A26), (2026, 11): (93629.79, A26),
    (2026, 12): (22206.46, A26),
    (2027, 1): (34032.02, A26), (2027, 2): (32000.90, A26),
}

c = sqlite3.connect("tidewatch.db")


def pd(s):
    try:
        return datetime.datetime.strptime(str(s).split()[0], "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


rows = []
for sd, ed, cd, pt, pr in c.execute(
        """SELECT startdate, enddate, creation_date, price_total, price_rent
           FROM pace_reservations
           WHERE type_name NOT IN ('INQR','OWN','MaintenanceBlock')
             AND (status_code IS NULL OR status_code != 9)"""):
    s, e, b = pd(sd), pd(ed), pd(cd)
    if s and e and b and e > s:
        rows.append((s, e, b, float(pt or 0), float(pr or 0), (e - s).days))

print(f"{'month':<9}{'SL truth':>12}{'arrival-basis':>14}{'ratio':>7}"
      f"{'prorated':>12}{'ratio':>7}")
tot_err_arr = tot_err_pro = n = 0
for (y, m), (sl_val, cutoff) in sorted(SL.items()):
    mf = datetime.date(y, m, 1)
    nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
    arr = pro = 0.0
    for s, e, b, pt, pr, dn in rows:
        if b > cutoff:
            continue
        if mf <= s < nxt:              # arrival-month attribution
            arr += pt
        lo, hi = max(s, mf), min(e, nxt)
        if (hi - lo).days > 0:         # per-night proration
            pro += pt / dn * (hi - lo).days
    ra = arr / sl_val if sl_val else 0
    rp = pro / sl_val if sl_val else 0
    tot_err_arr += abs(1 - ra)
    tot_err_pro += abs(1 - rp)
    n += 1
    print(f"{y}-{m:02d}{sl_val:>12,.0f}{arr:>14,.0f}{ra:>7.2f}{pro:>12,.0f}{rp:>7.2f}")
print(f"\nmean abs error: arrival-basis {100*tot_err_arr/n:.1f}%   "
      f"prorated {100*tot_err_pro/n:.1f}%")
