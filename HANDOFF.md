# TIDEWATCH SALES INTELLIGENCE — PROJECT HANDOFF

_Last updated 2026-08-13. This document is the single source of truth for taking over
this project. Read all of it before acting. NO SECRETS live in this file (public repo) —
credential locations are referenced, values come from Matt or the server._

## Who / what
- Owner: Matt Flewelling (matt@beaufort.rent), TideWatch Vacations LLC — ~157-unit
  vacation rental manager in Beaufort SC. PMS: **Streamline VRS** (staying on it, ever).
- Mission: reservationist sales tracking + booking-pace leading indicators, replacing
  three dead hand-entered scorecard columns, with everything as automatic as possible.

## Live infrastructure (all built, all running)
- **Server:** DigitalOcean droplet `161.35.122.5` (Ubuntu 24.04, $6/mo). Its static IP is
  allowlisted in Streamline PartnerX — **the Streamline API only answers calls made FROM
  this droplet.** Code lives at `/opt/tidewatch-crm` (a clone of this repo).
  Access = SSH as root; Matt authorizes new SSH keys by appending to
  `~/.ssh/authorized_keys` (ask him; he's done it before via the DO web console).
- **Services (systemd):** `tidewatch` (uvicorn `app:app` on 127.0.0.1:8080),
  `caddy` (auto-HTTPS reverse proxy).
- **Cron:** `*/30 * * * * run_sync.sh` (incremental lead/booking sync),
  `15 9 * * * run_pace.sh` (daily pace pull + true snapshot).
- **URLs:**
  - Scoreboard (login-protected): `https://161-35-122-5.sslip.io` — per-rep bookings,
    revenue, close rate, period tabs. HTTP Basic; user + password in
    `/opt/tidewatch-crm/app.env` (`DASH_USER` / `DASH_PASSWORD`).
  - Public pace page (no login, plain-English): `https://pace.161-35-122-5.sslip.io`
  - Scorecard data feed: `https://pace.161-35-122-5.sslip.io/scorecard-history.csv` —
    weekly rows consumed by Matt's Google Sheet scorecard
    (spreadsheet id `1SYhUTVp6aNbhhAOtXxLUF4L42zHEfg_8nxiCvFmchb8`, `PaceData` tab has
    `=IMPORTDATA(...)`, three scorecard columns VLOOKUP from it).
- **Secrets:** all in `/opt/tidewatch-crm/app.env` on the droplet (Streamline token
  key/secret, dashboard password, admin token). Streamline tokens expire every 90 days —
  `streamline.py` auto-renews via `RenewExpiredToken` and persists to `tokens.json`.
  ⚠️ Pending task: rotate all of these (they passed through chat transcripts), and
  consider making this repo private again (it contains no secrets, but still).

## Code map (all in this repo)
- `streamline.py` — API client (token auto-renew, rate limiting) + read-only audit.
- `sync.py` — leads/bookings sync into SQLite `tidewatch.db` (INQR + STA lists → detail).
- `metrics.py` — per-rep scoreboard math (period-scoped).
- `pace.py` — the pace engine: pulls all reservations via `GetReservationsFiltered` with
  `return_full=1` (month windows), computes occupancy/RevPAR/pickup/channel pace,
  **SL_ASOF calibration anchors**, per-month fleet derivation, scorecard CSV, daily
  snapshots (`pace_snapshots`).
- `app.py` — FastAPI: scoreboard, `/pace` public host middleware, JSON APIs, CSV.
- `TOUCHES_BUILD.md` + `streamline-lead-nurture-research.md` — the designed-but-unbuilt
  10-touch lead nurture sequence and how Streamline's trigger system works.
- `PLAN.md`, `DESIGN.md` — history/decisions. Various `test_*.py` / investigation scripts.

## HARD-WON FACTS — do not re-derive, do not re-litigate
1. **Streamline API surface** (fully enumerated from partner.streamlinevrs.com/apidocs):
   groups = Tokens, Reservations, Property Info, Availability, Owners, Resorts,
   WorkOrders, General, Housekeeping. **There are NO endpoints for: reports, messaging,
   lead-owner/agent on unbooked leads, transaction/folio history, or as-of historical
   values.** `show_payments_folio_history` returns nothing on this account (tested).
2. **Data model:** leads ARE reservations with `type_name='INQR'` (`status_id` 9).
   `status_code 9 = cancelled` (verified, ~$0 avg); `status_code 8 = normal
   confirmed/completed` (do NOT treat 8 as cancelled). `maketype_name 'A'` = rep-created
   booking, `'I'` = guest self-booked online. `price_nightly` = rent subtotal (rent only);
   `price_total` = guest total incl. fees/taxes. `sales_agent_name` populates reliably
   only on booked reservations — per-rep close rate on open/lost leads is NOT possible
   from the API (that job is moving to LeadSimple).
3. **OTA inquiries (Airbnb/Vrbo pre-booking messages) are NOT in the API** — only booked
   OTA reservations are. Website inquiries are (INQR).
4. **GetPropertyList is unstable** — returned 157 unique Actives one call, a duplicated
   199-row list another. Count unique ids; never store a fleet count < 10 (guards exist).
5. **Fleet/occupancy:** per-month live-unit counts are derived from calendar activity
   (~170 summer 2025 → 157 now); occupancy = booked ÷ (live units × days − owner/
   maintenance blocked nights) — this reproduces Streamline's RevMax occupancy levels.
6. **Pacing money numbers:** Streamline's **Revenue Pacing Report** (Reports → Revenue
   Pacing; dual "Sales as" cutoffs) is the ONLY authoritative source of "on the books as
   of date X" dollars. The API **cannot** reproduce it (tested against 14 ground-truth
   values; no counting method matches its future months). `pace.py` therefore calibrates
   both years' money to per-month anchors in `SL_ASOF` (each = (dollars, anchor_date),
   expiring after 150 days of drift). Occupancy/nights/channels/pickup need NO calibration.
7. **The calibration is temporary:** `pace_snapshots` has captured true daily on-the-books
   values since 2026-08-10. From Aug 2027, last-year baselines come from our own snapshots
   and ALL Streamline-report dependence ends.
8. Browser-tooling quirk (this machine): the Claude-in-Chrome bridge is domain-blocked
   from `admin.streamlinevrs.com` and `zapier.com`; `partner.streamlinevrs.com` works.

## THE TASK IN FLIGHT (start here)
**Automate the monthly calibration-anchor refresh.** Decision tree, already agreed with Matt:
1. **Route 1 (preferred):** Check whether Streamline supports scheduled/auto-emailed
   reports (in the admin UI: Reports area — look for "Scheduled Reports" or a
   schedule/auto-send option, esp. on the Revenue Pacing Report). If YES → have it email
   the Revenue Pacing report monthly (default "Sales as" dates = today/today−1yr,
   checkboxes all unchecked, Date Range pairs 2025/2026 AND 2026/2027) → build an
   ingester that parses the emailed export and updates `SL_ASOF` in `pace.py` on the
   droplet → zero manual steps forever.
2. **Route 2 (if no scheduling):** 30-minute feasibility spike of a headless login bot
   (Playwright on the droplet) using a dedicated least-privilege Streamline user Matt
   creates. If login is scriptable, cron it to run/export/parse the report itself.
   If captcha/MFA blocks it, stop.
3. **Route 3 (fallback):** accept ~monthly manual screenshot → paste anchors, until
   snapshots make it moot in Aug 2027.

## Backlog (agreed, in priority order after the task above)
1. **10-touch lead-nurture sequence in Streamline** — fully designed in
   `TOUCHES_BUILD.md`; build = Streamline UI config (Documents + triggers + delays +
   stop conditions), test on ONE lead before enabling broadly.
2. **LeadSimple integration:** a Streamline trigger "Forward to Leadsimple" exists
   (Category Lead, event New System Lead) and an email Document was drafted (recipient
   `new-deala01a8f9bd5@newlead.leadsimple.com`, kept in Draft) — finish, test with one
   lead, confirm LeadSimple parses it. Reps Rosa Wingate, Deb Fulmer, Mary Posadas (+ JC
   Cuppia) have LeadSimple accounts. A Zapier zap for lead-desk-schedule-based
   assignment was started but is unfinished (LeadSimple native routing couldn't do
   schedule-based assignment).
3. **Rotate secrets** (Streamline token secret via PartnerX, dashboard password,
   admin token) and consider making this repo private.
4. Monthly: refresh `SL_ASOF` anchors (until #1 automates it). Jan/Feb-2027 anchors exist;
   later months need report pulls spanning 2027.

## Working with Matt — read this twice
- **Act, don't ask.** Do the reversible thing, show the result. Option menus every turn
  infuriate him. One decisive recommendation when a choice is genuinely his.
- **Never claim something is verified unless you personally tested it.** He has caught
  overclaiming multiple times and it torched trust. Sample sizes matter. Say "I don't
  know yet" plainly.
- **Lead with the answer**, then evidence. Short over long. He's sharp on data
  definitions (he caught the open-booking-window flaw, the rate-vs-occupancy
  decomposition, and the as-of cutoff nuance himself).
- **Gate expensive work on cheap verifiable facts first** ("make sure this works before
  we waste any time" is a direct quote).
- His screenshots are excellent ground truth — ask for one when a UI blocks you.
- Reps: Rosa Wingate, Deb Fulmer, Mary Posadas, JC Cuppia (JC questions data — his
  challenges have twice exposed real bugs; take them seriously).
