#!/usr/bin/env python3
"""Derive per-month live-unit counts and occupancy (gross vs net-of-blocks)
from pace_reservations. Read-only analysis."""
import datetime
import sqlite3

c = sqlite3.connect("tidewatch.db")


def pd(s):
    try:
        return datetime.datetime.strptime(str(s).split()[0], "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


rows = c.execute("""SELECT startdate, enddate, unit_id, type_name
                    FROM pace_reservations
                    WHERE (status_code IS NULL OR status_code != 9)""").fetchall()
parsed = []
for sd, ed, u, tn in rows:
    s, e = pd(sd), pd(ed)
    if s and e and e > s and u:
        parsed.append((s, e, u, tn))


def month_stats(y, m):
    mf = datetime.date(y, m, 1)
    nm = datetime.date(y + (m == 12), m % 12 + 1, 1)
    days = (nm - mf).days
    units_any = set()
    booked = blocked = 0
    for s, e, u, tn in parsed:
        lo, hi = max(s, mf), min(e, nm)
        n = (hi - lo).days
        if n <= 0:
            continue
        units_any.add(u)
        if tn in ("OWN", "MaintenanceBlock"):
            blocked += n
        elif tn != "INQR":
            booked += n
    gross = len(units_any) * days
    net = gross - blocked
    return (len(units_any), booked, blocked,
            round(100 * booked / gross) if gross else 0,
            round(100 * booked / net) if net else 0)


print(f"{'month':<9}{'live units':>11}{'booked':>9}{'blocked':>9}{'occ gross':>11}{'occ net':>9}")
months = [(2025, m) for m in range(6, 13)] + [(2026, m) for m in range(1, 9)]
for y, m in months:
    u, b, bl, og, on = month_stats(y, m)
    print(f"{y}-{m:02d}{u:>10}{b:>10}{bl:>9}{og:>10}%{on:>8}%")
