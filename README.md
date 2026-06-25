# tidewatch-crm

Durable integration layer for Tidewatch Vacations on top of **Streamline (PMS)**
and **Enso Connect (guest comms + upsells)**. See **[DESIGN.md](DESIGN.md)** for the
architecture and decisions.

## Goal of this code
**Always-on access to the Streamline API, independent of anyone's location**, plus a
read-only capability audit. Two durability problems, both solved here:

1. **IP allow-listing** — Streamline only accepts calls from allow-listed IPs, and a
   laptop's IP changes by location. → Run on a host with one **static outbound IP**,
   allow-list it once.
2. **90-day token expiry** — tokens die every 90 days. → The client auto-detects an
   expired-token response, calls `RenewExpiredToken`, persists the new pair, and
   retries. No manual rotation, no lockout. (`streamline.py`)

## Files
- `streamline.py` — stdlib-only client (auto-renew + token store) + the audit. Shared.
- `app.py` — FastAPI worker exposing `/health`, `/ip`, `/token`, `/token/renew`, `/audit`.
- `audit_streamline.py` — local CLI runner for the read-only audit.
- `render.yaml` — one-click Render deploy (static IP + persistent token disk).

## Deploy the always-on worker (Render)
1. Push this folder to a Git repo and create a **Render Web Service** from it
   (`render.yaml` is picked up automatically). Use the **Starter** plan or higher —
   free instances sleep and don't get a static IP.
2. In the Render dashboard set the secrets: `STREAMLINE_TOKEN_KEY`,
   `STREAMLINE_TOKEN_SECRET`. (`ADMIN_TOKEN` is auto-generated.)
3. After it deploys, get the IP to allow-list — either from Render's **Outbound IPs**
   (Connect tab) or just hit the endpoint:
   ```
   curl https://<your-service>.onrender.com/ip
   ```
4. Add that IP in PartnerX → Administration → **Allowed IPs**. Wait ~15s.
5. Run the audit through the worker:
   ```
   curl -H "Authorization: Bearer $ADMIN_TOKEN" https://<your-service>.onrender.com/audit
   ```
That IP is now permanent — Italy, US, anywhere, the worker is what talks to Streamline.

## Run the audit locally (quick one-off)
Requires the calling machine's IP to be allow-listed (laptop IPs rotate — the worker
above is the durable answer).
```
cp .env.example .env          # paste tokens
set -a; source .env; set +a
python3 audit_streamline.py
```

## Security
- Secrets live in env / Render secrets, never in source. `.env` and `tokens.json` are git-ignored.
- Admin endpoints require `Authorization: Bearer $ADMIN_TOKEN`.
