# Tidewatch — 10-Touch Lead Sequence: Streamline Build Spec

Turns the CRM Touch Sequence playbook into exact Streamline configuration, using the
lead-nurture research (`streamline-lead-nurture-research.md`).

## How it maps to Streamline
- **Automated emails & texts** → **Documents** (Communication → Manage Documents) with
  content + merge tags, attached to a **Trigger** (Communication → Manage Triggers) with a
  **delay**.
- **Calls** → **Scheduled Follow-Up tasks** (Lead → Communication tab → Add Note → check
  "Schedule Follow Up"), assigned to the lead's agent with a due date/time. (Auto-creation
  on trigger isn't supported, per research — calls are rep tasks.)
- **Stop on book / not-interested** → add a trigger **condition** "lead not in Booked/Dead"
  (Create Trigger wizard supports ALL/ANY conditions), plus the manual "Do not send lead
  trigger" checkbox as backup.

## Merge-tag mapping (playbook variable → Streamline tag)
| Playbook | Streamline tag |
|---|---|
| [First Name] | `{reservations.first_name}` |
| [Property Name] | `{location_units.name}` |
| [Amount] | `{reservations.bundled_total}` |
| [Booking Link] | `{reservations.book_now_button}` |
| [Your Name] (the rep) | `{reservations.lead_agent_first_name}` |
| [Company] | `{companies.name}` |
| [Dates] | confirm exact arrival/departure date tags in the View Tags panel |
| [Phone] (rep's direct #) | ⚠️ no tag found — use a per-rep value or the company number (open item) |

## The sequence (trigger event + delay)
Delays are hours from lead creation (Streamline's "Lead Created X hours" event).

| # | Day | Channel | Build as | Trigger / delay |
|---|---|---|---|---|
| 1 | 0 | Call | Scheduled task | On new lead, due immediately |
| 2 | 0 | Text | SMS Document | `New System Lead`, delay 0 |
| 3 | 0 | Email | Email Document | `New System Lead`, delay ~10 min |
| 4 | 1 | Call | Scheduled task | due +1 day (morning) |
| 5 | 1 | Text | SMS Document | `Lead Created X hours`, ~28h |
| 6 | 2 | Email | Email Document | ~48h |
| 7 | 2 | Text | SMS Document | ~54h |
| 8 | 3 | Call | Scheduled task | due +3 days |
| 9 | 5 | Email | Email Document | ~120h |
| 10 | 7 | Text | SMS Document | ~168h |
| 11 | 300 | Email/Text | Document | ~7200h (⚠️ confirm Streamline allows a delay this long; may need a separate mechanism) |

## Ready-to-paste templates (tags substituted)

**Touch 2 — SMS (immediate):**
> Hi {reservations.first_name}, this is {reservations.lead_agent_first_name} from TideWatch. Sending the full details on {location_units.name} to your email now. Questions? Just text me here.

**Touch 3 — Email (within 10 min):**
Subject: Your vacation rental details from TideWatch
> Hi {reservations.first_name},
> Thanks for reaching out about your trip. Here are the details for the property you asked about:
> Property: {location_units.name}
> Total: {reservations.bundled_total}
> You can view the full listing and book here: {reservations.book_now_button}
> If you have any questions about the property, the area, or anything else about your trip, I'm happy to help — reply here anytime.
> {reservations.lead_agent_first_name}, TideWatch Vacations

**Touch 5 — SMS (Day 1):**
> Hi {reservations.first_name}, just making sure you got everything you needed on {location_units.name}. Want me to pull a couple of other options for your dates? Just say the word. — {reservations.lead_agent_first_name}, TideWatch

**Touch 6 — Email (Day 2):**
Subject: A few more options for your trip
> Hi {reservations.first_name},
> I wanted to follow up with a couple of other properties that could work well for your dates. Availability for your dates is starting to fill in — I'm not rushing you, just want you to have the full picture. Reply and I'll help you narrow it down.
> {reservations.lead_agent_first_name}, TideWatch Vacations
> *(Only keep the availability line if it's genuinely true.)*

**Touch 7 — SMS (Day 2):**
> Hi {reservations.first_name}, I know planning takes time. Want me to put together a quick side-by-side of the best options for your dates? Just let me know. — {reservations.lead_agent_first_name}

**Touch 9 — Email (Day 5):**
Subject: Still here if you need us
> Hi {reservations.first_name},
> Trip planning doesn't always go in a straight line. If your dates shifted, your group changed, or you're looking at a different area, I'm happy to start fresh and help you find the right fit. And if you've already booked elsewhere, no hard feelings — hope you have a great trip. Either way, we're here whenever you need us.
> {reservations.lead_agent_first_name}, TideWatch Vacations

**Touch 10 — SMS (Day 7):**
> Hi {reservations.first_name}, this is {reservations.lead_agent_first_name} from TideWatch. If your trip plans come together down the road or you're looking at different dates, reach out anytime — always happy to help. Hope to hear from you.

**Touch 11 — 300-day reactivation (email or SMS):** short warm re-engagement; reuse Touch 10 tone.

**Calls (Touches 1, 4, 8):** rep tasks, not templates — reps use the call scripts from the
playbook. Create via Schedule Follow Up, assigned to the lead's agent, due Day 0 / Day 1 / Day 3.

## Build order (recommended)
1. Create the **email Documents** first (3, 6, 9) — highest value, fully automatable.
2. Add the **SMS Documents** (2, 5, 7, 10).
3. Attach **triggers + delays** to each; add the "not Booked/Dead" stop condition.
4. Set up the **call follow-up tasks** convention for reps (Touches 1, 4, 8).
5. **Test with ONE real lead** end-to-end before enabling for all.

## Open items to confirm in Streamline
- Exact **date** merge tags ([Dates]).
- A merge tag (or workaround) for the **rep's direct phone** ([Phone]).
- Whether the **delay** field supports multi-day / 300-day offsets, or needs multiple triggers.
- Whether SMS sending is enabled on the account (Use for Mobile toggle).
