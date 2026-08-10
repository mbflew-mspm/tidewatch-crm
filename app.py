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
    rows = ""
    for m in d["months"]:
        ty, ly, lyf = m["ty"], m["ly_same_time"], m["ly_final"]
        p = m["pickup"][14]
        occ_d = round(ty["occ_pct"] - ly["occ_pct"], 1)
        rp_d = round(ty["revpar"] - ly["revpar"], 2)
        cls = "up" if rp_d >= 0 else "down"
        arrow = "▲" if rp_d >= 0 else "▼"
        rows += f"""<tr>
          <td class="mo">{m['month']}<span class="dim"> · {m['days_out']}d out</span></td>
          <td class="num">{ty['occ_pct']}%<span class="dim"> vs {ly['occ_pct']}%</span></td>
          <td class="num dim">{lyf['occ_pct']}%</td>
          <td class="num">${ty['revpar']:.2f}<span class="dim"> vs ${ly['revpar']:.2f}</span></td>
          <td class="num {cls}">{arrow} {abs(rp_d):.2f}</td>
          <td class="num">{p['nights']}<span class="dim"> / {p['ly_nights']}</span></td></tr>"""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tidewatch Pace</title>
<style>
  :root {{ --bg:#f6f6f4; --card:#fff; --ink:#23221f; --dim:#6c6a64; --line:#e7e5df;
           --accent:#1D9E75; --red:#c0392b; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          background:var(--bg); color:var(--ink); margin:0; padding:24px; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:20px; font-weight:600; margin:0 0 2px; }}
  .sub {{ color:var(--dim); font-size:13px; margin-bottom:20px; }}
  a.back {{ font-size:13px; color:var(--dim); text-decoration:none; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card);
           border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:14px; }}
  th {{ text-align:right; font-weight:500; color:var(--dim); font-size:12px;
        padding:10px 12px; border-bottom:1px solid var(--line); }}
  th:first-child {{ text-align:left; }}
  td {{ padding:12px; border-bottom:1px solid var(--line); }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ text-align:right; white-space:nowrap; }} .dim {{ color:var(--dim); font-size:12px; }}
  .mo {{ font-weight:500; white-space:nowrap; }}
  .up {{ color:var(--accent); font-weight:600; }} .down {{ color:var(--red); font-weight:600; }}
  .foot {{ color:var(--dim); font-size:12px; margin-top:16px; line-height:1.6; }}
</style></head><body><div class="wrap">
  <a class="back" href="/">← scoreboard</a>
  <h1>Booking pace</h1>
  <div class="sub">On-the-books vs same time last year (equal days-to-arrival) ·
    {d['active_units']} active units · as of {d['as_of']}</div>
  <table>
    <thead><tr><th>Stay month</th><th>Occ vs LY@</th><th>LY final</th>
      <th>RevPAR vs LY@</th><th>RevPAR Δ</th><th>Pickup 14d (nts, TY/LY)</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=6 class="dim">No pace data yet — run pace.py.</td></tr>'}</tbody>
  </table>
  <div class="foot">"vs LY@" = last year's on-the-books at the same days-out, rebuilt from
  booked-on dates. {' '.join(d['caveats'])}</div>
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
