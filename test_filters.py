#!/usr/bin/env python3
"""Probe how to LIST the inquiry funnel (INQR / status_id 9) via the API."""
import os
from streamline import StreamlineClient, TokenStore


def _data(p):
    d = p.get("data")
    if isinstance(d, dict):
        return d
    r = p.get("Response")
    return r.get("data", {}) if isinstance(r, dict) else {}


def _count(p):
    ids = _data(p).get("confirmation_id")
    n = len(ids) if isinstance(ids, list) else (1 if ids else 0)
    return n, (p.get("status") or {}).get("code")


c = StreamlineClient(TokenStore("tokens.json",
                                os.environ["STREAMLINE_TOKEN_KEY"],
                                os.environ["STREAMLINE_TOKEN_SECRET"]))
tests = [
    ("GetReservations", {}),
    ("GetReservations", {"type_name": "INQR"}),
    ("GetReservationsFiltered", {"status_code": "0"}),
    ("GetReservationsFiltered", {"status_code": "9"}),
    ("GetReservationsFiltered", {"return_full": "1", "type_name": "INQR"}),
    ("GetReservationsFiltered", {"converted_since": "2026-01-01"}),
    ("GetReservationsFiltered", {"modified_since": "2026-06-20"}),
]
for m, params in tests:
    n, code = _count(c.call(m, params))
    print(f"{m} {params} -> {n} ids  (code {code})")
