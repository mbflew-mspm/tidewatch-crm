# Tidewatch Vacations — Sales CRM Integration: Design & Decisions

_Last updated: 2026-06-21_

## Goal
Give Tidewatch reservationists one workflow to **capture, follow up on, and close
booking leads**, and give management **per-reservationist sales stats**. Reps must be
able to **email, text, and call** leads, two-way **guest messaging** must work
(Vrbo/OTA messages currently arrive via email through Streamline), and the system must
connect to **Mailchimp**.

## Where things stand
- Reservationists already work inside **Streamline VRS's built-in CRM**.
- **Vrbo + all OTA two-way messaging is native to Streamline** (that's where guest
  conversations and bookings actually happen).
- A **HubSpot** account was created (tier TBD — recommendation below).
- Streamline API access is set up: `POST https://web.streamlinevrs.com/api/json`,
  JSON, read+write, **100 req/min**, tokens rotate every 90 days, **IP-allowlisted**.

---

## Decision 1 — System of record: **Option A** (start here)

We are NOT building a CRM from scratch and NOT moving reps out of Streamline on day one.

**Option A (recommended): Streamline = operational CRM, HubSpot/Mailchimp = sales-intel + marketing layer.**
- Reps keep working leads and messaging guests **in Streamline** — because that's where
  Vrbo/OTA messaging and booking conversion already live. We do not make them flip apps
  to answer a guest.
- A **sync worker** mirrors Streamline data (leads, stages, reservations, rep ownership,
  outcomes) into our own store and pushes it to the reporting/marketing layer.
- All **non-OTA leads** (website forms, phone) get pushed **into** Streamline via the API
  so "all leads are in the CRM" holds true.
- **Sales stats** come from the synced data (a dashboard we control), not from a tool reps
  have to live in.

**Option B (only if the audit proves it): HubSpot becomes the front-end CRM.**
- Viable **only if the Streamline API supports two-way guest messaging (read AND send)**.
  If it can't send, reps would have to bounce back to Streamline to reply — the worst of
  both worlds. The `messaging` probes in `audit_streamline.py` decide this.

> The audit is the gate between A and B. We commit to A now and revisit B only on green
> messaging results.

---

## Decision 2 — Hosting: fixed-IP worker

Streamline allowlists by IP, and our calling environment's IP rotates (and changes by
location while traveling). So the sync worker runs on a **host with one fixed outbound IP
that we allowlist once**.

- **Recommended:** a small always-on worker on **Render** (already in use elsewhere),
  using its **static outbound IP** for the region. Allowlist that IP in PartnerX once;
  the IP issue never recurs, including in production.
- The **audit itself runs from this host**, so location/travel is irrelevant.
- Respect Streamline's guidance: **cache locally, sync incrementally** (use the
  change-tracking methods) rather than calling the API per user action.

---

## Decision 3 — HubSpot tier: **don't pay per-seat yet**

Honest take given Option A: under A, reps do **not** live in HubSpot, so paying
~$90–100/seat/mo for **Sales Hub Professional** (the tier needed for sequences + rep
leaderboards) buys little at first.

**Recommendation:**
1. **Keep HubSpot on the Free tier** for now as a contact store / staging ground.
2. **Build rep sales stats from the Streamline sync** (we own that data) — a lightweight
   dashboard, not a HubSpot seat cost.
3. **Connect Mailchimp directly** for guest email nurture (native Mailchimp; HubSpot not
   required in the path).
4. **Calling/texting:** decide per rep need — Streamline-native where possible, or a
   dedicated tool (Twilio/Kixie/Salesmsg) wired to the lead record.
5. **Only upgrade to Sales Hub Professional** if you later decide to move reps into HubSpot
   (Option B) and want its sequences + reporting. That's a deliberate, post-audit choice —
   not a default.

This avoids per-seat spend on a tool that, under Option A, duplicates what Streamline + a
custom dashboard already give you.

---

## Integration components (Option A)
1. **Sync worker** (Render, fixed IP) — pulls Streamline leads/reservations/contacts on a
   schedule via change-tracking; caches locally.
2. **Lead intake** — website/phone leads → `NewContact`/`NewReservation` into Streamline.
3. **Stats dashboard** — per-reservationist capture → follow-up → close metrics off the
   synced data.
4. **Mailchimp sync** — guests/leads → audiences/tags for nurture.
5. **(Later, if Option B)** message mirror: Streamline ⇄ HubSpot inbox.

## Open questions the audit (`audit_streamline.py`) resolves
- Do **leads/inquiries** exist as API objects (read + create)? → intake design
- Is **guest messaging** exposed, and can we **send** (not just read)? → A vs B
- Are **quotes/availability** queryable? → can reps quote without leaving the CRM
- Is there **change-tracking** for incremental sync? → how we respect the 100/min cap
- What's the real **status/field shape**? → the local data model

## Next steps
1. Stand up the Render worker (fixed IP) and allowlist its IP in PartnerX (one time).
2. Run `audit_streamline.py` from that host; cross-check method names vs the
   [apidocs](https://partner.streamlinevrs.com/apidocs) and fix any guessed names.
3. Read the audit → confirm Option A scope (or open the Option B question).
4. Build the sync worker + intake + stats dashboard.
