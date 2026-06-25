"""
Tidewatch Streamline worker — the always-on, fixed-IP front door to Streamline.

Deploy this on a host with a static outbound IP (see render.yaml), allow-list
that one IP in PartnerX once, and every Streamline call routes through here
regardless of where the team is. Tokens auto-renew (see streamline.py).

Endpoints:
  GET  /health        — liveness (open)
  GET  /ip            — this server's egress IP, i.e. the IP to allow-list (open)
  GET  /token         — token status: key prefix + last renewal (open, no secrets)
  POST /token/renew   — force a token renewal (admin)
  GET  /audit         — run the read-only capability audit (admin)

Admin endpoints require  Authorization: Bearer $ADMIN_TOKEN.
"""

import os
import urllib.request

from fastapi import FastAPI, Header, HTTPException

from streamline import StreamlineClient, TokenStore, run_audit

store = TokenStore(
    os.environ.get("TOKEN_STORE_PATH", "tokens.json"),
    os.environ.get("STREAMLINE_TOKEN_KEY", ""),
    os.environ.get("STREAMLINE_TOKEN_SECRET", ""),
)
client = StreamlineClient(store)
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

app = FastAPI(title="Tidewatch Streamline Worker")


def _require_admin(authorization):
    if not ADMIN_TOKEN or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ip")
def ip():
    with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
        return {"egress_ip": r.read().decode("utf-8").strip(),
                "note": "allow-list this IP in PartnerX -> Administration -> Allowed IPs"}


@app.get("/token")
def token():
    return store.status()


@app.post("/token/renew")
def token_renew(authorization: str = Header(default=None)):
    _require_admin(authorization)
    return client.renew()


@app.get("/audit")
def audit(authorization: str = Header(default=None)):
    _require_admin(authorization)
    return run_audit(client)
