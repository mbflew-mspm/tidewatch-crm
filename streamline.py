"""
Streamline VRS API client for Tidewatch — built for *durable* access.

Two things make access "always on":
  1. Fixed IP — this module is meant to run on a host with one static outbound
     IP that's allow-listed in Streamline once (see render.yaml). Location of
     the operator no longer matters.
  2. Token auto-renewal — Streamline tokens expire every 90 days. Every call
     auto-detects an expired-token response, calls RenewExpiredToken, persists
     the new pair via TokenStore, and retries once. No manual rotation, no
     lockout.

Stdlib only (urllib) so it has zero external dependencies and runs anywhere —
imported by both the CLI (audit_streamline.py) and the service (app.py).
"""

import json
import os
import time
import datetime
import urllib.request
import urllib.error

ENDPOINT = "https://web.streamlinevrs.com/api/json"
RATE_DELAY_SEC = 0.8
TIMEOUT_SEC = 30

# Codes/keywords that mean "token expired, renew it". The exact Streamline code
# is not yet confirmed against the apidocs, so we match defensively: any code in
# this (env-overridable) set, OR a description mentioning an expired token.
# TODO: confirm the real expired-token code from the audit/apidocs and pin it.
_EXPIRED_CODES = set(
    c.strip() for c in os.environ.get("STREAMLINE_TOKEN_EXPIRED_CODES", "").split(",") if c.strip()
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_token_expired(code, desc):
    if code in _EXPIRED_CODES:
        return True
    d = (desc or "").lower()
    return "token" in d and ("expire" in d or "expired" in d or "invalid" in d)


class TokenStore:
    """File-backed token store, seeded from env on first run.

    On a host the file lives on a persistent disk (see render.yaml), so renewed
    tokens survive restarts and deploys. Falls back to the env seed if no file.
    """

    def __init__(self, path, seed_key, seed_secret):
        self.path = path
        self._key = seed_key
        self._secret = seed_secret
        self._updated = None
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            if d.get("token_key") and d.get("token_secret"):
                self._key, self._secret = d["token_key"], d["token_secret"]
                self._updated = d.get("updated")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def current(self):
        return self._key, self._secret

    def status(self):
        return {
            "token_key_prefix": (self._key[:6] + "…") if self._key else None,
            "last_renewed": self._updated,
            "store_path": self.path,
        }

    def update(self, key, secret):
        self._key, self._secret = key, secret
        self._updated = _now()
        self._persist()

    def _persist(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"token_key": self._key, "token_secret": self._secret, "updated": self._updated}, f)
        os.replace(tmp, self.path)


class StreamlineClient:
    def __init__(self, store):
        self.store = store

    def _post(self, body):
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.URLError as e:
            return {"status": {"code": "TRANSPORT", "description": str(e)}}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"status": {"code": "NONJSON", "description": raw[:300]}}

    def call(self, method, params=None, _allow_renew=True):
        params = dict(params or {})
        key, secret = self.store.current()
        body = {"methodName": method, "params": {"token_key": key, "token_secret": secret, **params}}
        parsed = self._post(body)
        status = parsed.get("status", {}) or {}
        if _allow_renew and _is_token_expired(str(status.get("code", "")), status.get("description")):
            self.renew()
            return self.call(method, params, _allow_renew=False)
        return parsed

    def renew(self):
        """Renew expired tokens and persist the new pair.

        NOTE: method name, param names, and response shape are best-effort and
        must be confirmed against the apidocs — they're isolated here so there's
        exactly one place to fix once verified.
        """
        key, secret = self.store.current()
        body = {"methodName": "RenewExpiredToken", "params": {"token_key": key, "token_secret": secret}}
        parsed = self._post(body)
        data = parsed.get("data", {}) or {}
        new_key = data.get("token_key") or data.get("new_token_key")
        new_secret = (data.get("token_secret") or data.get("token_secret_key")
                      or data.get("new_token_secret"))
        if not new_key or not new_secret:
            raise RuntimeError(f"RenewExpiredToken returned no new tokens: {parsed.get('status')}")
        self.store.update(new_key, new_secret)
        return {"renewed": True, "token_key_prefix": new_key[:6] + "…", "at": _now()}


# --------------------------------------------------------------------------
# Read-only capability audit (shared by CLI and /audit endpoint).
# --------------------------------------------------------------------------
PROBES = [
    {"group": "core", "method": "GetPropertyList", "params": {},
     "note": "Connectivity + master unit list."},
    {"group": "core", "method": "GetPropertyInfo", "params": {}, "needs": ["property_id"],
     "note": "Per-unit detail."},
    {"group": "reservations", "method": "GetReservationList", "params": {},
     "note": "Bookings — needed to attribute closed-won to a rep."},
    {"group": "reservations", "method": "GetReservationInfo", "params": {}, "needs": ["reservation_id"],
     "note": "Single reservation detail (look for a rep/owner/agent field — the #5 linchpin)."},
    {"group": "leads", "method": "GetLeadList", "params": {},
     "note": "Do open sales leads/inquiries exist in the API?"},
    {"group": "leads", "method": "GetInquiryList", "params": {},
     "note": "Alt name for inbound inquiries."},
    {"group": "leads", "method": "GetReservationInquiries", "params": {},
     "note": "Inquiry-stage reservations (pre-booking)."},
    {"group": "leads", "method": "GetContactList", "params": {},
     "note": "Guest/contact records."},
    {"group": "users", "method": "GetUserList", "params": {},
     "note": "Reservationists/agents — needed to map ownership to a person (#5)."},
    {"group": "messaging", "method": "GetMessageList", "params": {},
     "note": "Confirms whether a messaging API exists (Enso says it does not)."},
    {"group": "messaging", "method": "GetReservationMessages", "params": {}, "needs": ["reservation_id"],
     "note": "Message thread tied to a reservation."},
    {"group": "quotes", "method": "GetPropertyAvailability", "params": {}, "needs": ["property_id"],
     "note": "Availability."},
    {"group": "quotes", "method": "GetPropertyRates", "params": {}, "needs": ["property_id"],
     "note": "Rates."},
    {"group": "changes", "method": "GetReservationsChanged", "params": {},
     "note": "Delta sync — avoids hitting the 100/min cap."},
]


def _classify(parsed):
    status = (parsed or {}).get("status", {}) or {}
    code = str(status.get("code", ""))
    desc = status.get("description", "")
    data = (parsed or {}).get("data")
    if code == "E0012":
        verdict = "IP_BLOCKED"
    elif code.startswith("E"):
        verdict = "ERROR"
    elif code in ("TRANSPORT", "NONJSON"):
        verdict = "TRANSPORT_ERR"
    elif data not in (None, "", [], {}):
        verdict = "OK_HAS_DATA"
    else:
        verdict = "OK_EMPTY"
    return verdict, code, desc, data


def _extract_id(data, *keys):
    def walk(node, depth=0):
        if depth > 6:
            return None
        if isinstance(node, dict):
            for k in keys:
                if k in node and node[k] not in (None, "", "0"):
                    return node[k]
            for v in node.values():
                got = walk(v, depth + 1)
                if got:
                    return got
        elif isinstance(node, list):
            for v in node:
                got = walk(v, depth + 1)
                if got:
                    return got
        return None
    return walk(data)


def run_audit(client):
    discovered = {}
    results = []
    for probe in PROBES:
        params = dict(probe.get("params", {}))
        missing = [n for n in probe.get("needs", []) if n not in discovered]
        meta = {"group": probe["group"], "method": probe["method"], "note": probe["note"]}
        if missing:
            results.append({**meta, "verdict": "SKIPPED_NEED", "detail": f"needs {missing}"})
            continue
        for n in probe.get("needs", []):
            params[n] = discovered[n]

        parsed = client.call(probe["method"], params)
        time.sleep(RATE_DELAY_SEC)
        verdict, code, desc, data = _classify(parsed)
        results.append({**meta, "verdict": verdict, "code": code, "detail": desc})

        if verdict == "OK_HAS_DATA":
            for key, names in (("property_id", ("id", "property_id", "propertyID")),
                               ("reservation_id", ("id", "reservation_id", "reservationID")),
                               ("contact_id", ("id", "contact_id", "contactID"))):
                if key not in discovered:
                    val = _extract_id(data, *names)
                    if val:
                        discovered[key] = val
        if verdict == "IP_BLOCKED":
            results[-1]["detail"] = desc + "  <-- allow-list this IP in PartnerX and re-run"
            break
    return {"discovered": discovered, "results": results}


def print_report(result):
    icon = {"OK_HAS_DATA": "[DATA]", "OK_EMPTY": "[ ok ]", "ERROR": "[ERR ]",
            "IP_BLOCKED": "[IP! ]", "SKIPPED_NEED": "[skip]", "TRANSPORT_ERR": "[NET ]"}
    print("\n" + "=" * 78)
    print(" STREAMLINE VRS API -- READ-ONLY CAPABILITY AUDIT")
    print("=" * 78)
    last = None
    for r in result["results"]:
        if r["group"] != last:
            print(f"\n## {r['group'].upper()}")
            last = r["group"]
        tag = icon.get(r["verdict"], "[????]")
        line = f"  {tag} {r['method']:<26} {r.get('code','')}"
        if r.get("detail"):
            line += f"  {r['detail'][:60]}"
        print(line)
        print(f"         -> {r['note']}")
    print("\n Discovered sample ids:", result["discovered"] or "(none)")
    print("=" * 78 + "\n")
