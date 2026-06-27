#!/usr/bin/env python3
"""Decode key stage fields for specific confirmation_ids → map status_code to a
stage (inquiry / quoted / booked / lost). Read-only.

  python3 inspect_ids.py 50475 50427 50376
"""
import os
import sys

from streamline import StreamlineClient, TokenStore


def _data(p):
    d = p.get("data")
    if isinstance(d, dict):
        return d
    r = p.get("Response")
    return r.get("data", {}) if isinstance(r, dict) else {}


def main():
    c = StreamlineClient(TokenStore("tokens.json",
                                    os.environ["STREAMLINE_TOKEN_KEY"],
                                    os.environ["STREAMLINE_TOKEN_SECRET"]))
    ids = sys.argv[1:] or ["50475", "50427", "50376"]
    for cid in ids:
        p = c.call("GetReservationInfo", {"confirmation_id": cid,
                                          "show_agents_referrer_information": "1"})
        r = _data(p).get("reservation") or {}
        if not r:
            print(f"{cid}: {p.get('status')}")
            continue
        print(f"{cid}: status_code={r.get('status_code')} status_id={r.get('status_id')} "
              f"lead_status_id={r.get('lead_status_id')} type={r.get('type_name')} "
              f"made={r.get('maketype_name')} agent={r.get('sales_agent_name')} "
              f"total={r.get('price_total')} created={r.get('creation_date')}")


if __name__ == "__main__":
    main()
