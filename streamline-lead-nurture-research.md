# Streamline VRS — Lead-Nurture Automation Research
**Account:** Flewelling BFT Rentals  
**Researched:** June 2026  
**Status:** Read-only exploration — nothing created or modified

---

## 1. Where Triggers Are Configured

There are two trigger systems in Streamline:

### A. Manage Triggers (NEW!) — Primary System
**Path:** Top nav → Communication → Manage Triggers (NEW!)  
**URL:** `admin.streamlinevrs.com/#/communication/manage_triggers`

- 231 total triggers across all categories
- Filter by type: **Any Triggers / Custom Triggers / Legacy Triggers**
- Search by name — searching "Lead" returns 17 Lead-category triggers
- Each trigger links to one or more **Documents** (email/SMS templates)
- Trigger detail shows: category, event, linked documents, active/inactive status

### B. Custom Triggers (Legacy)
**Path:** Top nav → Communication → (scroll down) → Custom Triggers  
**URL:** `admin.streamlinevrs.com/#/general_custom_triggers.html`

- Older interface; 3 existing custom triggers (all Reservation category)
- Still functional; supports Lead category
- Edit page: `admin.streamlinevrs.com/edit_custom_trigger.html?trigger_id=XXXX`

---

## 2. Lead Trigger Events

Found via the Custom Trigger editor (Category = Lead). **22 Lead events** available:

| # | Event Name |
|---|-----------|
| 1 | New Hot Lead |
| 2 | New Work Lead |
| 3 | New Cold Lead |
| 4 | X hours from creation |
| 5 | **Lead Created X hours** ← primary drip delay event |
| 6 | **New System Lead** ← primary "inquiry created" event |
| 7 | Email quote Sent |
| 8 | Leads Dates Unavailable |
| 9 | Assigned lead agent is modified |
| 10 | Assigned lead agent is changed |
| 11 | Email Error Flag Attached |
| 12 | Flag Turned On |
| 13 | Flag Never Selected |
| 14 | Bounce has been received |
| 15 | Housekeeping event 1 |
| 16 | Housekeeping event 2 |
| 17 | Housekeeping event 3 |
| 18 | Custom Unit Email |
| 19 | Owner Statement event 1 |
| 20 | Owner Statement event 2 |
| 21 | Owner Statement event 3 |
| 22 | Owner Statement event 4 |

**Most useful for lead nurture:**
- `New System Lead` — fires when a new inquiry comes in
- `Lead Created X hours` — fires X hours after lead creation (use for drip sequence)
- `New Hot Lead` / `New Work Lead` — fires when lead is moved to that queue

### Timing / Delay
- A **"Set Delay"** button exists on the Triggers & Delay tab of each Document
- Button was present but modal did not open during read-only session — exact delay unit options (hours vs. days) unconfirmed
- The event name "Lead Created X hours" strongly implies **hour-based offsets**
- Multiple triggers can be chained to one document, and multiple documents can be created with different delays

### Create Trigger Wizard
**Path:** Manage Triggers → "+ Create Trigger" button  
- 4-step wizard: General Info → ALL conditions → ANY conditions → Create
- Supports multiple AND/ANY condition logic
- Category and event selected in step 1

---

## 3. Email & SMS Support

**Both Email and SMS are supported** in Document templates.

**Path:** Communication → Manage Documents (NEW!) → open any document → **Content tab**

Content tab has **4 channel sub-tabs:**

| Tab | Status |
|-----|--------|
| Email | ✅ Full drag-and-drop builder |
| SMS | ✅ Tab present (confirmed in DOM) |
| Push | ✅ Tab present |
| OTA | ✅ Tab present |

Email builder blocks available: Columns, Button, Divider, Heading, Paragraph, Image, Video, Social, Menu, HTML, Table, Timer

Document-level settings (General tab) confirm:
- `Use for Email System` ✅
- `Use for Lead Management` ✅
- `Use for Mobile` toggle (controls SMS/Push sending)

---

## 4. Merge Fields (Template Tags)

**Path:** Document editor → Content tab → **"View Tags"** button (opens searchable panel)

### Key Merge Tags for Lead Nurture

| Tag | Description |
|-----|-------------|
| `{reservations.first_name}` | Guest / Client First Name |
| `{client.first_name}` | Client First Name (alternate) |
| `{location_units.name}` | Unit / Property Name |
| `{reservations.check_in_time}` | Check-In Date/Time |
| `{reservations.property_check_in...}` | Property Check-In Time |
| `{reservations.property_check_o...}` | Property Check-Out Time |
| `{reservations.bundled_total}` | Total Price (bundled) |
| `{reservations.price_paidsum}` | Total Paid |
| `{reservations.firstnight_cost}` | First Night Cost |
| `{reservations.book_now_button}` | **Booking Button** (HTML link) |
| `{reservations.email_quote_price...}` | Email Quote Price Line |
| `{reservations.lead_agent_first_...}` | Lead Agent First Name |
| `{companies.name}` | Company / Brand Name |

> Full tag library is searchable in the View Tags panel. Many more tags exist for dates, property details, rates, etc.

---

## 5. Reservationist Tasks for Leads

### Where Tasks Live
Tasks/follow-ups for leads are managed in two places:

**A. CRM → My Dash**  
`admin.streamlinevrs.com/#/general_crm.html`  
- Shows **"My Tasks Today"** and **"My Tasks Future"** counters per agent
- Leaderboard of agent activity

**B. Legacy Lead Interface — TODO LIST**  
`admin.streamlinevrs.com/reservation_tasks.html?reservation_id=XXXX#main_url=ds_leads_todo.html`  
- Full task list with columns: Status, Agent, Date, Time, Lead Name, Phone, Email, Unit, Notes
- Filter by: Task Type, Agent, Status (Open / Closed / Deleted)
- **"Check to Close"** column — checkbox to mark a task complete

### How to Create a Task (Schedule Follow Up)
**Path:** CRM → Leads → click a lead → Communication tab → **Add Note** → check **"Schedule Follow Up"**

Reveals the following fields:

| Field | Options |
|-------|---------|
| **Schedule Type** (Agent) | TEAM, Cuppia JC, Fulmer Deb, Posadas Mary, Wingate Rosa |
| **Schedule Date** | Date picker |
| **Schedule Time** | Time field (e.g. 05:00 AM) |
| **On Date Move to** | Select Queue / New / Hot / Work / Cold |

✅ **Can be assigned to a specific agent** — yes  
✅ **Can be given a due date and time** — yes  
✅ **Can be marked complete** — yes (Check to Close in TODO LIST)  
⚠️ **Auto-created by trigger** — NOT confirmed. Task creation appears to be manual only. No automated task-creation-on-trigger-fire was found.

---

## 6. Stopping Automations (Lead Books or Goes Dead)

There is **no fully automatic stop** found. Stopping requires a manual action, but only one click:

### Option A — Move to "Booked" Queue
- Queue named **"Booked"** exists (status = Completed Lead)
- Moving a lead to the Booked queue logically ends the lead lifecycle
- **How:** CRM → Leads → select lead → Action Item(s) → Move to Another Queue → Booked

### Option B — "Do Not Send Lead Trigger" Checkbox
- Found on the lead's Communication tab → Settings section
- **Lead Status** dropdown + **"Do not send lead trigger"** checkbox
- Checking this box suppresses all trigger-based sends for that specific lead
- **How:** Open lead → Communication tab → check "Do not send lead trigger" → Update Changes

### Option C — D_EMAILS Flag
- Found on lead's **Flags tab**
- Flag name: `D_EMAILS` (Disable Emails)
- Disables all email sends for that reservation/lead
- More of a hard kill-switch than a graceful stop

### Summary Table

| Method | Stops Email | Stops SMS | Automatic? |
|--------|-------------|-----------|-----------|
| Move to Booked queue | Depends on trigger config | Depends | Manual (1 click) |
| "Do not send lead trigger" checkbox | ✅ | ✅ | Manual (1 click) |
| D_EMAILS flag | ✅ Email only | ❌ | Manual |

---

## 7. Gaps & Unknowns

| Item | Status |
|------|--------|
| Set Delay modal — exact units (hours vs. days) | ⚠️ Unconfirmed — modal didn't open |
| Auto-creation of tasks when trigger fires | ⚠️ Not found — appears manual only |
| SMS content editing (builder UI blocked SMS tab) | ⚠️ Confirmed tab exists; content editor not fully explored |
| Whether trigger conditions can filter by property/unit | ⚠️ Properties tab exists on Document — may limit by property type |
| Whether "Lead Created X hours" supports >24 hour delays (days) | ⚠️ Name says "hours" — may need multiple triggers for multi-day drip |

---

## 8. Recommended Build Path (When Ready)

1. **Plan your sequence** — e.g., Touch 1 (immediate), Touch 2 (24h), Touch 3 (72h), Touch 4 (7 days)
2. **Create Documents** — Communication → Manage Documents → + New Document
   - Set Type = Communication
   - Check "Use for Email System" + "Use for Lead Management"
   - Write Email content with merge tags
   - Write SMS content in SMS tab
3. **Attach Triggers with Delays** — on each Document's Triggers & Delay tab
   - Use `New System Lead` for Touch 1 (immediate)
   - Use `Lead Created X hours` with increasing delays for Touches 2–4
4. **Agent Follow-Up Tasks** — manually create via Add Note → Schedule Follow Up on each new lead
   - Assign to specific agent
   - Set due date/time
   - Set queue move on due date (e.g., move to Hot)
5. **Stop on Conversion** — when lead books, either:
   - Move to Booked queue, OR
   - Check "Do not send lead trigger" on the lead

---

*Explored read-only. Nothing created or modified during research session.*
