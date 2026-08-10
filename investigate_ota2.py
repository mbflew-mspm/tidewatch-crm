#!/usr/bin/env python3
"""Properly check whether OTA (Airbnb/Vrbo) INQUIRIES exist as API records.
Sample broadly across the whole list + look explicitly for inquiry-status (9)."""
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

for t in ["SC-ABnB", "HAFamOLB"]:
    ids = _data(c.call("GetReservations", {"type_name": t})).get("confirmation_id") or []
    n = len(ids)
    step = max(1, n // 50)
    idx = sorted(set(range(0, n, step)) | set(range(max(0, n - 30), n)))
    samp = [ids[i] for i in idx][:90]
    st = collections.Counter()
    inquiries = []
    for cid in samp:
        r = _data(c.call("GetReservationInfo", {"confirmation_id": cid})).get("reservation") or {}
        time.sleep(0.4)
        sid = r.get("status_id")
        st[sid] += 1
        if sid == 9:
            inquiries.append((cid, r.get("creation_date"), r.get("hear_about_name")))
    print(f"{t}: total={n}, sampled={len(samp)} spread across the full list")
    print(f"  status_id distribution: {dict(st)}")
    print(f"  INQUIRY-status (9) found: {len(inquiries)}  {inquiries[:5]}")
    print()
