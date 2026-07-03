#!/usr/bin/env python3
"""Do OTA (Airbnb/Vrbo/Booking) *inquiries* surface as lead records in the API,
or only bookings? Check each OTA type's status mix. Read-only."""
import collections
import os
import time

from streamline import StreamlineClient, TokenStore


def _data(p):
    d = p.get("data")
    if isinstance(d, dict):
        return d
    r = p.get("Response")
    return r.get("data", {}) if isinstance(r, dict) else {}


c = StreamlineClient(TokenStore("tokens.json",
                                os.environ["STREAMLINE_TOKEN_KEY"],
                                os.environ["STREAMLINE_TOKEN_SECRET"]))

# status_id 9 = inquiry (from earlier record inspection). Sample each OTA type
# and see if any records are inquiry-status vs all booked.
for t in ["INQR", "SC-ABnB", "HAFamOLB", "SC-Vrbo", "SC-Booking.com", "HomeToGo"]:
    ids = _data(c.call("GetReservations", {"type_name": t})).get("confirmation_id") or []
    statuses = collections.Counter()
    travelagents = collections.Counter()
    for cid in ids[:20]:
        r = _data(c.call("GetReservationInfo", {"confirmation_id": cid})).get("reservation") or {}
        time.sleep(0.5)
        statuses[r.get("status_id")] += 1
        travelagents[r.get("travelagent_name")] += 1
    print(f"type_name={t!r}: {len(ids)} total | status_id sample={dict(statuses)} | "
          f"travelagent={dict(travelagents)}")
