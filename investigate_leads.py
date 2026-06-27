#!/usr/bin/env python3
"""Investigate the real lead model: channels (type_name), lead status, and whether
a lead-owner/lead-agent field is exposed by the API. Read-only."""
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

ids = _data(c.call("GetReservationsFiltered", {"modified_since": "2026-06-01"})).get("confirmation_id") or []
print(f"recent (modified since 2026-06-01): {len(ids)} reservations")

combos = collections.Counter()
lead_agent_fields = {}
sample = None
for cid in ids[:30]:
    r = _data(c.call("GetReservationInfo",
                     {"confirmation_id": cid, "show_agents_referrer_information": "1"})).get("reservation") or {}
    time.sleep(0.7)
    if not r:
        continue
    if sample is None:
        sample = r
    combos[(r.get("type_name"), r.get("status_id"), r.get("lead_status_id"))] += 1
    for k, v in r.items():
        if ("lead" in k.lower() or "agent" in k.lower()):
            lead_agent_fields.setdefault(k, v)

print("\n(type_name, status_id, lead_status_id) -> count:")
for combo, n in combos.most_common():
    print(f"  {combo}: {n}")

print("\nAll lead/agent-related fields on a reservation + sample value:")
for k, v in sorted(lead_agent_fields.items()):
    print(f"  {k} = {v!r}")
