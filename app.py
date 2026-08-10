"""
Tidewatch worker + hosted scoreboard.

Always-on, fixed-IP front door to Streamline AND the reservationist dashboard.

Endpoints:
  GET  /            -> the scoreboard (HTML, login-protected)
  GET  /api/metrics -> scoreboard JSON (login-protected)
  GET  /health      -> liveness (open)
  GET  /ip          -> this server's egress IP (open)
  GET  /token       -> token status, no secrets (open)
  POST /token/renew -> force token renewal (admin bearer)
  GET  /audit       -> read-only capability audit (admin bearer)

Login: HTTP Basic, user `DASH_USER` (default 'tidewatch') + password `DASH_PASSWORD`.
Admin endpoints: Authorization: Bearer $ADMIN_TOKEN.
"""

import os
import secrets
import sqlite3
import urllib.request

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import metrics
import pace
from streamline import StreamlineClient, TokenStore

DB_PATH = os.environ.get("DB_PATH", "tidewatch.db")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
DASH_USER = os.environ.get("DASH_USER", "tidewatch")
DASH_PASSWORD = os.environ.get("DASH_PASSWORD", "")

store = TokenStore(os.environ.get("TOKEN_STORE_PATH", "tokens.json"),
                   os.environ.get("STREAMLINE_TOKEN_KEY", ""),
                   os.environ.get("STREAMLINE_TOKEN_SECRET", ""))
client = StreamlineClient(store)
app = FastAPI(title="Tidewatch Sales Intelligence")
security = HTTPBasic()


def require_login(creds: HTTPBasicCredentials = Depends(security)):
    if not DASH_PASSWORD:
        raise HTTPException(503, "Dashboard password not configured (set DASH_PASSWORD).")
    ok = (secrets.compare_digest(creds.username, DASH_USER)
          and secrets.compare_digest(creds.password, DASH_PASSWORD))
    if not ok:
        raise HTTPException(401, "Unauthorized", {"WWW-Authenticate": "Basic"})
    return True


def require_admin(authorization):
    if not ADMIN_TOKEN or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(401, "unauthorized")


def _metrics(period="all"):
    conn = sqlite3.connect(DB_PATH)
    try:
        return metrics.compute(conn, period)
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ip")
def ip():
    with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
        return {"egress_ip": r.read().decode("utf-8").strip()}


@app.get("/token")
def token():
    return store.status()


@app.post("/token/renew")
def token_renew(authorization: str = Header(default=None)):
    require_admin(authorization)
    return client.renew()


@app.get("/audit")
def audit(authorization: str = Header(default=None)):
    require_admin(authorization)
    from streamline import run_audit
    return run_audit(client)


@app.get("/api/metrics")
def api_metrics(period: str = "all", _: bool = Depends(require_login)):
    return JSONResponse(_metrics(period))


@app.get("/", response_class=HTMLResponse)
def dashboard(period: str = "all", _: bool = Depends(require_login)):
    return HTMLResponse(render_dashboard(_metrics(period)))


@app.get("/api/pace")
def api_pace(_: bool = Depends(require_login)):
    conn = sqlite3.connect(DB_PATH)
    try:
        return JSONResponse(pace.compute(conn))
    finally:
        conn.close()


@app.get("/pace", response_class=HTMLResponse)
def pace_page(_: bool = Depends(require_login)):
    conn = sqlite3.connect(DB_PATH)
    try:
        return HTMLResponse(render_pace(pace.compute(conn)))
    finally:
        conn.close()


def render_pace(d):
    import datetime as _dt
    rows = ""
    ahead = behind = 0
    for m in d["months"]:
        ty, ly, lyf = m["ty"], m["ly_same_time"], m["ly_final"]
        p = m["pickup"][14]
        rp_d = round(ty["revpar"] - ly["revpar"], 2)
        is_ahead = rp_d >= 0
        ahead += 1 if is_ahead else 0
        behind += 0 if is_ahead else 1
        y, mo = (int(x) for x in m["month"].split("-"))
        month_name = _dt.date(y, mo, 1).strftime("%B %Y")
        when = "already started" if m["days_out"] <= 0 else f"starts in {m['days_out']} days"
        badge = ('<span class="badge up">▲ Ahead of last year</span>' if is_ahead
                 else '<span class="badge down">▼ Behind last year</span>')
        rows += f"""<tr>
          <td class="mo">{month_name}<br><span class="dim">{when}</span></td>
          <td>{badge}</td>
          <td class="num">{ty['occ_pct']}% full<br><span class="dim">last year now: {ly['occ_pct']}%</span></td>
          <td class="num">${ty['revpar']:.0f}<br><span class="dim">last year now: ${ly['revpar']:.0f}</span></td>
          <td class="num dim">{lyf['occ_pct']}% full</td>
          <td class="num">{p['nights']} nights<br><span class="dim">last year: {p['ly_nights']}</span></td></tr>"""

    total = ahead + behind
    verdict_cls = "up" if ahead >= behind else "down"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tidewatch Booking Pace</title>
<style>
  :root {{ --bg:#f6f6f4; --card:#fff; --ink:#23221f; --dim:#6c6a64; --line:#e7e5df;
           --accent:#1D9E75; --red:#c0392b; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          background:var(--bg); color:var(--ink); margin:0; padding:24px; }}
  .wrap {{ max-width:940px; margin:0 auto; }}
  h1 {{ font-size:20px; font-weight:600; margin:0 0 2px; }}
  .sub {{ color:var(--dim); font-size:14px; margin-bottom:16px; }}
  a.back {{ font-size:13px; color:var(--dim); text-decoration:none; }}
  .verdict {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
              padding:14px 18px; font-size:15px; margin-bottom:18px; }}
  .verdict b.up {{ color:var(--accent); }} .verdict b.down {{ color:var(--red); }}
  table {{ width:100%; border-collapse:collapse; background:var(--card);
           border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:14px; }}
  th {{ text-align:right; font-weight:500; color:var(--dim); font-size:12px;
        padding:10px 12px; border-bottom:1px solid var(--line); }}
  th:first-child, th:nth-child(2) {{ text-align:left; }}
  td {{ padding:12px; border-bottom:1px solid var(--line); vertical-align:top; }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ text-align:right; white-space:nowrap; }} .dim {{ color:var(--dim); font-size:12px; }}
  .mo {{ font-weight:500; white-space:nowrap; }}
  .badge {{ font-size:12px; font-weight:600; padding:4px 10px; border-radius:999px; white-space:nowrap; }}
  .badge.up {{ background:#e2f4ec; color:var(--accent); }}
  .badge.down {{ background:#fae8e5; color:var(--red); }}
  .explain {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
              padding:20px 24px; margin-top:24px; font-size:14px; line-height:1.7; }}
  .explain h2 {{ font-size:15px; margin:18px 0 6px; }}
  .explain h2:first-child {{ margin-top:0; }}
  .explain p {{ margin:6px 0; }}
  .explain li {{ margin:4px 0; }}
</style></head><body><div class="wrap">
  <a class="back" href="/">← back to scoreboard</a>
  <h1>Booking pace — are we ahead of last year?</h1>
  <div class="sub">Updated {d['as_of']} · compares today's bookings with the same point in time last year</div>

  <div class="verdict">Right now we are <b class="{verdict_cls}">ahead of last year in
  {ahead} of {total} months</b> (measured by money earned per home, per night).</div>

  <table>
    <thead><tr>
      <th>Month</th><th>Are we ahead?</th><th>How full is it<br>booked so far?</th>
      <th>Money per home,<br>per night</th><th>Where last year<br>ended up</th>
      <th>New bookings,<br>last 2 weeks</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=6 class="dim">No data yet.</td></tr>'}</tbody>
  </table>

  <div class="explain">
    <h2>What is this page?</h2>
    <p>Every row is a month people can stay with us. For each one we ask a single question:
    <b>do we have more business booked for that month than we had at this exact point last
    year?</b> If yes, we're "ahead." If no, we're "behind."</p>

    <h2>Why compare with "the same time last year"?</h2>
    <p>Here's the trap this page avoids. Say it's August and you look at October. October
    only looks 13% full — scary! But October isn't done filling up; most people haven't
    booked their October trip yet. Comparing today's October with how October
    <i>finished</i> last year is unfair — it's comparing a cake that's still baking with one
    that's done. The fair question is: <b>last year, on this same date in August, how full
    was October then?</b> If we're fuller now than we were then, we're genuinely winning,
    even if the number itself looks small.</p>

    <h2>What each column means</h2>
    <ul>
      <li><b>Are we ahead?</b> — Green ▲ means we're making more money per home per night
        than at this point last year. Red ▼ means less.</li>
      <li><b>How full is it booked so far?</b> — Out of all the nights we could possibly
        rent that month (every home × every night), the percent already booked. The small
        gray number is where we stood at this same point last year.</li>
      <li><b>Money per home, per night</b> — Total booking money for the month, divided by
        every home and every night we have. This is the fairest single number: it can't be
        fooled by us adding or removing homes, and it captures both "how full" and "at what
        price." (Hotels call this RevPAR.)</li>
      <li><b>Where last year ended up</b> — How full that month <i>finally</i> got last
        year once all the bookings were in. It shows how much filling usually happens late,
        so a small number today isn't alarming.</li>
      <li><b>New bookings, last 2 weeks</b> — How many nights got booked for that month in
        just the past 14 days, next to the same 14-day window last year. This is our speed:
        even a month that's behind can be catching up fast.</li>
    </ul>

    <h2>Things to keep in mind</h2>
    <ul>
      <li>We divide by today's count of {d['active_units']} active homes for both years. If
        our home count changed a lot since last year, the percentages shift a little — but
        the ahead/behind comparison stays fair because both years use the same divisor.</li>
      <li>Last year's "at this point" numbers are rebuilt from each booking's booked-on
        date. Bookings that existed then but cancelled later aren't counted, so last year
        may look slightly weaker than it really was.</li>
      <li>"Money" here is the guest's total booking price, including fees, spread evenly
        across the nights of the stay.</li>
      <li>This page refreshes automatically every morning.</li>
    </ul>
  </div>
</div></body></html>"""


def _money(n):
    try:
        return "${:,.0f}".format(float(n or 0))
    except (TypeError, ValueError):
        return "$0"


def render_dashboard(d):
    f = d.get("funnel", {})
    reps = d.get("per_rep", [])
    sources = d.get("sources", [])
    max_rev = max([r.get("revenue", 0) for r in reps], default=1) or 1
    avg = (f.get("rep_revenue", 0) / f["rep_bookings"]) if f.get("rep_bookings") else 0
    periods = [("month", "This month"), ("quarter", "This quarter"),
               ("year", "This year"), ("all", "All time")]
    cur = d.get("period", "all")
    tabs = "".join(f'<a href="/?period={p}" class="tab{" on" if cur == p else ""}">{lbl}</a>'
                   for p, lbl in periods)
    plabel = dict(periods).get(cur, "All time")

    rows = ""
    for i, r in enumerate(reps):
        initials = "".join(p[0] for p in str(r["agent"]).split()[:2]).upper()
        w = int(100 * r.get("revenue", 0) / max_rev)
        cr = f"{r['close_rate']}%" if r.get("close_rate") is not None else "—"
        rows += f"""<tr>
          <td class="rep"><span class="av">{initials}</span>{r['agent']}</td>
          <td class="num">{r['bookings']}</td>
          <td><div class="bar"><div class="fill" style="width:{w}%"></div></div></td>
          <td class="num">{_money(r['revenue'])}</td>
          <td class="num dim">{_money(r['avg_booking'])}</td>
          <td class="num">{cr}</td></tr>"""

    src = "".join(f"<li><span>{s['source']}</span><b>{s['count']}</b></li>" for s in sources)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tidewatch Sales Intelligence</title>
<style>
  :root {{ --bg:#f6f6f4; --card:#fff; --ink:#23221f; --dim:#6c6a64; --line:#e7e5df; --accent:#1D9E75; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; background:var(--bg);
          color:var(--ink); margin:0; padding:24px; }}
  .wrap {{ max-width:840px; margin:0 auto; }}
  h1 {{ font-size:20px; font-weight:600; margin:0 0 2px; }}
  .sub {{ color:var(--dim); font-size:13px; margin-bottom:20px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }}
  .c {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
  .c .l {{ font-size:12px; color:var(--dim); }}
  .c .v {{ font-size:24px; font-weight:600; margin-top:4px; }}
  .c .h {{ font-size:12px; color:var(--dim); margin-top:2px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line);
           border-radius:12px; overflow:hidden; font-size:14px; }}
  th {{ text-align:right; font-weight:500; color:var(--dim); font-size:12px; padding:10px 12px; border-bottom:1px solid var(--line); }}
  th:first-child {{ text-align:left; }}
  td {{ padding:12px; border-bottom:1px solid var(--line); }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ text-align:right; }} .dim {{ color:var(--dim); }}
  .rep {{ display:flex; align-items:center; gap:10px; font-weight:500; }}
  .av {{ width:28px; height:28px; border-radius:50%; background:#e6f1fb; color:#185fa5; display:flex;
         align-items:center; justify-content:center; font-size:11px; font-weight:600; }}
  .bar {{ background:#eee; border-radius:6px; height:8px; min-width:80px; }}
  .fill {{ background:var(--accent); height:8px; border-radius:6px; }}
  h2 {{ font-size:13px; color:var(--dim); font-weight:500; margin:24px 0 8px; }}
  ul.src {{ list-style:none; padding:0; margin:0; background:var(--card); border:1px solid var(--line); border-radius:12px; }}
  ul.src li {{ display:flex; justify-content:space-between; padding:10px 14px; border-bottom:1px solid var(--line); font-size:14px; }}
  ul.src li:last-child {{ border-bottom:none; }}
  .foot {{ color:var(--dim); font-size:12px; margin-top:20px; }}
  .tabs {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:18px; }}
  .tab {{ padding:6px 12px; border:1px solid var(--line); border-radius:8px; font-size:13px;
          color:var(--dim); text-decoration:none; background:var(--card); }}
  .tab.on {{ color:#fff; background:var(--accent); border-color:var(--accent); }}
</style></head><body><div class="wrap">
  <h1>Tidewatch sales intelligence</h1>
  <div class="sub">Reservationist scoreboard · rep-worked business · {plabel} · last sync {str(d.get('last_sync') or '')[:19].replace('T',' ')} UTC · <a href="/pace" style="color:var(--accent);text-decoration:none;">booking pace →</a></div>
  <div class="tabs">{tabs}</div>
  <div class="cards">
    <div class="c"><div class="l">Rep-worked revenue</div><div class="v">{_money(f.get('rep_revenue'))}</div><div class="h">{f.get('rep_bookings',0)} bookings</div></div>
    <div class="c"><div class="l">Avg booking value</div><div class="v">{_money(avg)}</div><div class="h">across reps</div></div>
    <div class="c"><div class="l">Open inquiries</div><div class="v">{f.get('inquiries_open',0)}</div><div class="h">lead pool</div></div>
    <div class="c"><div class="l">Close rate</div><div class="v">{f.get('team_close_rate_pct',0)}%</div><div class="h">booked vs leads received</div></div>
  </div>
  <h2>Reservationist leaderboard · by revenue</h2>
  <table><thead><tr><th>Rep</th><th>Bookings</th><th>Revenue</th><th></th><th>Avg</th><th>Close</th></tr></thead>
  <tbody>{rows or '<tr><td colspan=6 class="dim">No data yet — sync running.</td></tr>'}</tbody></table>
  <div class="foot">Per-rep close rate shows only where a rep's own leads are attributed in Streamline; "—" means their open/lost leads aren't tagged to them yet (fixable with consistent lead assignment).</div>
  <h2>Top lead sources (inquiries)</h2>
  <ul class="src">{src or '<li class="dim">No data yet.</li>'}</ul>
  <div class="foot">Live from Streamline. Backfill in progress — numbers grow as the sync completes.</div>
</div></body></html>"""
