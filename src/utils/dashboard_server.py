"""
dashboard_server.py — Web dashboard and settings server for NopeRi.

Exposes:
  GET  /                          Live dashboard (stats, charts, recent jobs, action triggers)
  GET  /dashboard                 Alias for /
  GET  /setup                     Web configuration wizard
  GET  /api/config                Config JSON + environment status
  POST /api/save                  Save config.json
  POST /api/login                 Test Naukri credentials
  POST /api/cookies               Test Naukri session cookies
  POST /api/trigger-profile-update Trigger headline bump + CV re-upload in background
  POST /api/trigger-apply         Trigger job search + AI scoring + apply in background
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from src.utils.web_setup import _HTML, _Handler as _SetupBaseHandler

logger = logging.getLogger(__name__)


def get_dashboard_html(db_path: str = "applied_jobs.db") -> str:
    total = 0
    by_day, top_co, recent = [], [], []
    high, mid, low, no_sc = 0, 0, 0, 0

    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM applied_jobs")
            total = (cur.fetchone() or [0])[0]

            if total > 0:
                cur.execute("""
                    SELECT substr(applied_at,1,10) day, COUNT(*) n
                    FROM applied_jobs GROUP BY day ORDER BY day DESC LIMIT 30
                """)
                by_day = list(reversed(cur.fetchall()))

                cur.execute("""
                    SELECT company, COUNT(*) n FROM applied_jobs
                    WHERE company != '' GROUP BY company ORDER BY n DESC LIMIT 8
                """)
                top_co = cur.fetchall()

                cur.execute("""
                    SELECT
                        SUM(CASE WHEN ai_score >= 70 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ai_score >= 50 AND ai_score < 70 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ai_score IS NOT NULL AND ai_score < 50 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ai_score IS NULL THEN 1 ELSE 0 END)
                    FROM applied_jobs
                """)
                high, mid, low, no_sc = cur.fetchone() or (0, 0, 0, 0)

                cur.execute("""
                    SELECT title, company, ai_score, applied_at FROM applied_jobs
                    ORDER BY applied_at DESC LIMIT 30
                """)
                recent = [
                    {"title": r[0] or "", "company": r[1] or "", "score": r[2], "date": (r[3] or "")[:19]}
                    for r in cur.fetchall()
                ]
            conn.close()
        except Exception as e:
            logger.error("Error reading database for dashboard: %s", e)

    days_js   = json.dumps([d for d, _ in by_day])
    counts_js = json.dumps([n for _, n in by_day])
    comp_js   = json.dumps([c for c, _ in top_co])
    comp_n_js = json.dumps([n for _, n in top_co])
    recent_js = json.dumps(recent)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NopeRi — Dashboard</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{{--bg:#0d1117;--surf:#161b22;--surf2:#1c2128;--border:#30363d;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922;--err:#f85149;--fg:#c9d1d9;--fg-m:#8b949e;color-scheme:dark}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:var(--bg);color:var(--fg);font-family:'Inter',sans-serif;font-size:14px;line-height:1.6}}
body{{padding:24px max(16px,4vw) 64px}}
.top-nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;border-bottom:1px solid var(--border);padding-bottom:16px;flex-wrap:wrap;gap:12px}}
.logo{{font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:600;color:#fff}}
.logo em{{color:var(--accent);font-style:normal}}
.nav-actions{{display:flex;align-items:center;gap:10px}}
.btn{{display:inline-flex;align-items:center;padding:7px 14px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;border:1px solid var(--border);background:var(--surf2);color:var(--fg);text-decoration:none;transition:all .15s}}
.btn:hover{{border-color:var(--accent);color:#fff}}
.btn-primary{{background:#238636;border-color:#2ea043;color:#fff}}
.btn-primary:hover{{background:#2ea043}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}}
.stat{{background:var(--surf);border:1px solid var(--border);border-radius:8px;padding:16px 20px}}
.stat .val{{font-size:28px;font-weight:600;font-family:'JetBrains Mono',monospace;margin-bottom:2px}}
.stat .lbl{{font-size:12px;color:var(--fg-m)}}
.charts{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}}
@media(max-width:768px){{.charts{{grid-template-columns:1fr}}}}
.chart-box{{background:var(--surf);border:1px solid var(--border);border-radius:8px;padding:20px}}
.chart-box h3{{font-size:13px;color:var(--fg-m);margin-bottom:16px;text-transform:uppercase;letter-spacing:.5px}}
table{{width:100%;border-collapse:collapse;background:var(--surf);border:1px solid var(--border);border-radius:8px;overflow:hidden}}
th{{text-align:left;padding:12px 14px;font-size:12px;color:var(--fg-m);text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid var(--border);background:var(--surf2)}}
td{{padding:12px 14px;border-bottom:1px solid var(--border);font-size:13px}}
tr:last-child td{{border-bottom:none}}
.pill{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;font-family:'JetBrains Mono',monospace}}
.pill.hi{{background:#0a1f12;color:var(--ok)}}
.pill.mid{{background:#1a1505;color:var(--warn)}}
.pill.lo{{background:#1f0a0a;color:var(--err)}}
.pill.ns{{background:var(--surf2);color:var(--fg-m)}}
.toast{{position:fixed;bottom:24px;right:24px;background:#238636;color:#fff;padding:12px 20px;border-radius:6px;font-weight:500;box-shadow:0 8px 24px rgba(0,0,0,.5);display:none;z-index:999}}
</style>
</head>
<body>
<div class="top-nav">
  <div class="logo">Nope<em>Ri</em> &mdash; Automation Dashboard</div>
  <div class="nav-actions">
    <button class="btn" onclick="triggerAction('/api/trigger-profile-update', 'CV & Headline Update Triggered!')">🔄 Bump Profile Now</button>
    <button class="btn btn-primary" onclick="triggerAction('/api/trigger-apply', 'Apply Agent Triggered in Background!')">🚀 Run Apply Agent Now</button>
    <a href="/setup" class="btn">⚙️ Settings</a>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="val" style="color:var(--accent)">{total}</div><div class="lbl">Total Applied</div></div>
  <div class="stat"><div class="val" style="color:var(--ok)">{high or 0}</div><div class="lbl">Score &ge;70</div></div>
  <div class="stat"><div class="val" style="color:var(--warn)">{mid or 0}</div><div class="lbl">Score 50&ndash;69</div></div>
  <div class="stat"><div class="val" style="color:var(--err)">{low or 0}</div><div class="lbl">Score &lt;50</div></div>
  <div class="stat"><div class="val" style="color:var(--fg-m)">{no_sc or 0}</div><div class="lbl">No Score</div></div>
</div>

<div class="charts">
  <div class="chart-box"><h3>Applications per Day (Last 30)</h3><canvas id="cDay"></canvas></div>
  <div class="chart-box"><h3>Top Target Companies</h3><canvas id="cCo"></canvas></div>
</div>

<table>
  <thead><tr><th>Title</th><th>Company</th><th>AI Fit Score</th><th>Applied At</th></tr></thead>
  <tbody id="rows">
    {"" if total > 0 else "<tr><td colspan='4' style='text-align:center;padding:32px;color:var(--fg-m)'>No applications on record yet. Scheduler runs daily at 08:00 AM IST.</td></tr>"}
  </tbody>
</table>

<div class="toast" id="toast"></div>

<script>
const days={days_js},counts={counts_js},comps={comp_js},compN={comp_n_js},recent={recent_js};
const opt={{responsive:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8b949e',maxRotation:45}},grid:{{color:'#30363d'}}}},y:{{ticks:{{color:'#8b949e'}},grid:{{color:'#30363d'}}}}}}}};
if(days.length) new Chart(document.getElementById('cDay'),{{type:'bar',data:{{labels:days,datasets:[{{data:counts,backgroundColor:'#1f6feb',borderRadius:4}}]}},options:opt}});
if(comps.length) new Chart(document.getElementById('cCo'),{{type:'bar',data:{{labels:comps,datasets:[{{data:compN,backgroundColor:'#388bfd',borderRadius:4}}]}},options:{{...opt,indexAxis:'y'}}}});

const tb=document.getElementById('rows');
if(recent.length) {{
  tb.innerHTML = '';
  recent.forEach(r=>{{
    const sc=r.score;
    const cls=sc==null?'ns':sc>=70?'hi':sc>=50?'mid':'lo';
    const sv=sc==null?'—':sc;
    tb.innerHTML+=`<tr><td><strong>${{r.title}}</strong></td><td style="color:#d29922">${{r.company}}</td><td><span class="pill ${{cls}}">${{sv}}/100</span></td><td style="color:#8b949e">${{r.date}}</td></tr>`;
  }});
}}

function triggerAction(url, msg) {{
  fetch(url, {{method:'POST'}})
    .then(r=>r.json())
    .then(data=>{{
      showToast(msg);
      setTimeout(()=>location.reload(), 3000);
    }})
    .catch(err=>showToast('Error: ' + err));
}}

function showToast(text) {{
  const t = document.getElementById('toast');
  t.innerText = text;
  t.style.display = 'block';
  setTimeout(()=>{{t.style.display='none'}}, 4000);
}}
</script>
</body>
</html>"""


class DashboardHandler(_SetupBaseHandler):
    """Unified HTTP handler for both the Dashboard and the Setup Wizard."""

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        if clean_path in ("/", "/dashboard"):
            self._html(get_dashboard_html())
        elif clean_path == "/setup":
            self._html(_HTML)
        elif clean_path == "/api/config":
            self._get_config()
        elif clean_path == "/api/stats":
            self._get_stats()
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        clean_path = self.path.split("?")[0]
        if clean_path == "/api/trigger-profile-update":
            threading.Thread(target=self._run_profile_updater, daemon=True).start()
            self._json({"ok": True, "message": "Profile update triggered in background."})
        elif clean_path == "/api/trigger-apply":
            threading.Thread(target=self._run_apply_agent, daemon=True).start()
            self._json({"ok": True, "message": "Apply agent triggered in background."})
        else:
            super().do_POST()

    def _get_stats(self):
        from src.utils.dbhandler import AppliedJobsDB
        db = AppliedJobsDB()
        self._json({"total": db.total()})

    @staticmethod
    def _run_profile_updater():
        try:
            from cron.profile_updater import run_profile_update
            logger.info("Manual profile update triggered via web dashboard")
            run_profile_update()
        except Exception as e:
            logger.error("Web-triggered profile update error: %s", e)

    @staticmethod
    def _run_apply_agent():
        try:
            from apply_agent import run_agent
            from src.utils.config_manager import ConfigManager
            from src.utils.dbhandler import AppliedJobsDB
            logger.info("Manual apply agent triggered via web dashboard")
            cfg = ConfigManager()
            db = AppliedJobsDB()
            run_agent(cfg, db)
        except Exception as e:
            logger.error("Web-triggered apply agent error: %s", e)


def start_dashboard_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    """Start the dashboard HTTP server."""
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    logger.info("Web dashboard server running at http://%s:%d", host, port)
    server.serve_forever()
