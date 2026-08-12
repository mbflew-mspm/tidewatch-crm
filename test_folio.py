#!/usr/bin/env python3
"""Can folio history reconstruct a booking's value AS OF a past date?
Test: for Aug-2025 stays, sum folio charges dated <= 8/12/2025 and compare
with the booking's current price_total. If the dated sums are meaningfully
lower for late-modified bookings, folio dates give us true as-of values."""
import datetime
import json
import os
import sqlite3
import time

from streamline import StreamlineClient, TokenStore


def _data(p):
    d = p.get("data")
    if isinstance(d, dict):
        return d
    r = p.get("Response")
    return r.get("data", {}) if isinstance(r, dict) else {}


def _pd(s):
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(str(s).split()[0], fmt).date()
        except (ValueError, AttributeError):
            pass
    return None


c = StreamlineClient(TokenStore("tokens.json",
                                os.environ["STREAMLINE_TOKEN_KEY"],
                                os.environ["STREAMLINE_TOKEN_SECRET"]))
db = sqlite3.connect("tidewatch.db")
cutoff = datetime.date(2025, 8, 12)

ids = [r[0] for r in db.execute(
    """SELECT confirmation_id FROM pace_reservations
       WHERE type_name NOT IN ('INQR','OWN','MaintenanceBlock')
         AND (status_code IS NULL OR status_code != 9)
         AND substr(startdate,7,4)='2025' AND substr(startdate,1,2) IN ('07','08')
         AND substr(enddate,7,4)='2025' AND substr(enddate,1,2)='08'
       ORDER BY price_total DESC LIMIT 40""")]
print(f"testing {len(ids)} Aug-2025 stays")

dumped = False
tot_now = tot_asof = 0.0
n_dated = n_undated = 0
for cid in ids:
    r = _data(c.call("GetReservationInfo", {
        "confirmation_id": cid, "show_payments_folio_history": "1",
        "show_taxes_and_fees": "1"})).get("reservation") or {}
    time.sleep(0.7)
    if not r:
        continue
    if not dumped:
        keys = [k for k in r if "folio" in k.lower() or "payment" in k.lower()
                or "charge" in k.lower() or "history" in k.lower()]
        print("folio-ish keys:", keys)
        for k in keys:
            print(f"--- {k} sample:", json.dumps(r[k])[:900])
        dumped = True
    price_now = float(r.get("price_total") or 0)
    hist = r.get("payments_folio_history") or r.get("folio_history") or {}
    items = hist
    if isinstance(hist, dict):
        for v in hist.values():
            if isinstance(v, list):
                items = v
                break
    asof = 0.0
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            d = _pd(it.get("date") or it.get("creation_date") or it.get("applied_date"))
            amt = it.get("amount") or it.get("charge_value") or it.get("value") or 0
            try:
                amt = float(amt)
            except (TypeError, ValueError):
                amt = 0
            if amt > 0 and it.get("type_id") != 2:  # skip payments if typed
                if d and d <= cutoff:
                    asof += amt
                    n_dated += 1
                elif not d:
                    n_undated += 1
    tot_now += price_now
    tot_asof += asof

print(f"\ncurrent price_total sum:      ${tot_now:,.0f}")
print(f"folio charges dated <= 8/12/25: ${tot_asof:,.0f}")
print(f"dated items {n_dated}, undated {n_undated}")
