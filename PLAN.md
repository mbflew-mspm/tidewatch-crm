# Tidewatch Sales CRM — Build Plan (v1, fact-based)

_Date: 2026-06-26 · Status: draft pending two confirmations (Streamline apidocs + a Streamline demo)_

## The decision
**Streamline-first.** Use Streamline's native CRM, automations, unified inbox, and
per-agent reporting as the backbone. Add custom build or an external tool **only** for
confirmed gaps. No Enso, no HubSpot in the core — both would add cost and (for HubSpot)
a fragile OTA-email inbox to replicate things Streamline appears to already do.

Why this changed: research into Streamline's *native* capabilities (not just its API)
showed it already covers most of the five non-negotiables. Confidence note: most claims
below are from Streamline's own pages (Hotel Tech Report has 0 independent reviews; one
StayFi review). The four ★ items must be confirmed in a vendor demo before we commit.

## Capability matrix

| # | Need | Native in Streamline? | Gap / action |
|---|------|----------------------|--------------|
| 1 | One inbox, all guest comms | **Partly** — native unified inbox shows Airbnb + Vrbo | ★ Confirm **two-way reply** + **Booking.com**. If weak → shared-email tool (HelpScout/Front) over relay emails as fallback |
| 2 | CRM touches, automated + manual rep tasks | **Yes** — lead queues, Communication Center automations, per-agent tasks/KPIs | Confirm manual task assignment UX; configure |
| 3 | Texting, calling, email, Mailchimp | **Partly** — email/comms native; calling via StreamPhone add-on | Confirm native SMS; Mailchimp via API/Zapier; price StreamPhone vs external dialer (OpenPhone) |
| 4 | Gap-night / early-late / accessory upsells | **Mostly** — early/late checkout, add-ons, payments, portal all native | ★ Confirm **gap-night offer to existing guest** + ★ **in-portal buy-and-pay** flow. Build the gap-night trigger via native automations if supported |
| 5 | Reservationist tracking, close rate, pipeline | **Largely** — per-agent revenue, goals, leaderboard, conversion-coaching reports | ★ Confirm **staged per-agent funnel**; confirm whether it's enough. If not → custom dashboard (but see API limit below) |

## The hard constraint (confirmed)
Streamline's Open API exposes **only 6 data categories: Property, Reservations,
Calendars/Availability, Owners, Maintenance, Pricing.** No messaging API. Leads/CRM/users
appear **not** API-exposed — which is why `GetLeadList`/`GetContactList`/`GetUserList`
returned `E0014`. Implication: the native CRM/per-agent metrics are **UI-only**. We can
read reservations + guests (`GetReservationInfo`, `GetClientInfo`, `GetAllReservationsByEmail`)
via API, but a custom #5 dashboard likely **cannot** pull the lead funnel or per-agent
metrics programmatically — so we should lean on Streamline's built-in reporting for #5,
not rebuild it.

## What this means for "build"
- **Mostly configuration, not construction.** Turn on / set up Streamline's CRM, lead
  queues, automation triggers, upsell add-ons, guest portal, and per-agent reporting.
- **Custom build, only if confirmed needed:**
  - Gap-night upsell logic, *if* native automations can't detect+offer it.
  - A lead-intake bridge to push website/phone leads into Streamline (uses the API — but
    only if lead-create methods exist; otherwise via Streamline's own web-inquiry forms).
  - A thin reporting export *only if* native per-agent reporting is insufficient (limited
    by the API not exposing CRM data — would rely on Streamline's report exports).
- **External tool, only as fallback:** a shared-email inbox (HelpScout/Front) if
  Streamline's native inbox isn't two-way or omits Booking.com.

## Cost picture (rough)
- **Streamline-first:** largely within the Streamline subscription you already pay; add
  StreamPhone (calling) and payment processing fees if used. Lowest incremental cost.
- vs **Enso:** ~$1,020/mo + upsell txn fees.
- vs **HubSpot:** ~$270–540/mo (Sales Hub Pro, 3–6 seats) + $1,500 onboarding + a fully
  custom Streamline→HubSpot sync + a fragile OTA-email inbox. SMS would need Marketing Hub
  Pro + add-on (~$800+/mo).

## What closes the remaining unknowns (no more guessing)
1. **Streamline apidocs** — get the full method list (confirms exactly what's API-exposed,
   especially any lead/CRM/user/write methods). _Owner: Matt (share docs or grant browser access)._
2. **Read+write scope request** — clear `E0014`; then re-run the audit. _Owner: Matt sends; Claude runs._
3. **Streamline demo / support session** — confirm the four ★ items below. _Owner: Matt books; Claude supplies checklist._

### Demo confirmation checklist (the ★ items)
1. Unified inbox: is it **two-way** (reply to guest from Streamline), and does it include
   **Booking.com** (Airbnb + Vrbo already shown)?
2. Upsells: can Streamline **auto-detect a gap night** and offer an existing guest to extend?
3. Upsells: can a guest **select and pay for** an upgrade (early check-in, add-on) in the
   Happy Stays portal end-to-end?
4. Reporting: is there a **staged per-agent conversion funnel** (new→quoted→won/lost), or
   only per-agent revenue/goals? Are per-agent metrics **exportable / API-reachable**?
5. Channels: native **SMS**? **StreamPhone** calling price? **Mailchimp** sync path?

## Sequence
1. Matt: send scope request + get apidocs to Claude + book Streamline demo (checklist above).
2. Claude: re-audit once scopes land; map the confirmed API surface.
3. Together: run the demo, check off the ★ items.
4. Claude: finalize the build spec — exact config steps + the (small) custom pieces.
5. Build → test against one dummy lead/reservation → roll out.
