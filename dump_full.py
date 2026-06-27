#!/usr/bin/env python3
"""Dump the COMPLETE GetReservationInfo record (every flag on) for a few open
leads — named and unnamed — to find any field that carries the lead owner."""
import json
import os
import sqlite3

from streamline import StreamlineClient, TokenStore

FLAGS = {k: "1" for k in [
    "return_address", "return_flags", "show_owner_charges", "show_taxes_and_fees",
    "show_commission_information", "return_payments", "return_additional_fields",
    "show_payments_folio_history", "include_security_deposit", "return_housekeeping_schedule",
    "show_agents_referrer_information", "show_cancellation_reason", "return_happystays_code",
    "show_guest_feedback_url", "show_exclusions", "show_payment_comments"]}


def _data(p):
    d = p.get("data")
    if isinstance(d, dict):
        return d
    r = p.get("Response")
    return r.get("data", {}) if isinstance(r, dict) else {}


c = StreamlineClient(TokenStore("tokens.json",
                                os.environ["STREAMLINE_TOKEN_KEY"],
                                os.environ["STREAMLINE_TOKEN_SECRET"]))
db = sqlite3.connect("tidewatch.db")
named = [r[0] for r in db.execute(
    "SELECT confirmation_id FROM reservations WHERE type_name='INQR' AND sales_agent IS NOT NULL LIMIT 1")]
unnamed = [r[0] for r in db.execute(
    "SELECT confirmation_id FROM reservations WHERE type_name='INQR' AND sales_agent IS NULL LIMIT 2")]

for label, cid in [("NAMED", named[0] if named else None)] + [("UNNAMED", x) for x in unnamed]:
    if not cid:
        continue
    res = _data(c.call("GetReservationInfo", {"confirmation_id": cid, **FLAGS})).get("reservation") or {}
    print(f"\n===== {label} lead, confirmation_id {cid} — full record =====")
    print(json.dumps(res, indent=1)[:4500])
