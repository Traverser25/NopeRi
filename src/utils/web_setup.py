"""
web_setup.py — Browser-based first-run setup wizard for NopeRi.

5-step wizard:
  1. Account  — skipped automatically when NAUKRI_USERNAME + PASSWORD are in .env
  2. Profile  — role, stack, locations, CTC
  3. AI       — provider, model, API key (written to .env), threshold
  4. Automate — Ubuntu crontab entry + Telegram
  5. Done     — summary

Scheduling: Ubuntu/Linux crontab only. Windows not supported.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 8765

# ---------------------------------------------------------------------------
# Embedded HTML wizard
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NopeRi Setup</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* ── Tokens ─────────────────────────────────────────────────── */
:root {
  --bg:       #0d1117;
  --surf:     #161b22;
  --surf2:    #1c2128;
  --border:   #30363d;
  --accent:   #58a6ff;
  --accent-d: #1f6feb;
  --ok:       #3fb950;
  --err:      #f85149;
  --warn:     #d29922;
  --fg:       #c9d1d9;
  --fg-m:     #8b949e;
  --tag:      #1b2a3d;
  color-scheme: dark;
}

/* ── Reset ──────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0 }
html { font-size: 15px; -webkit-text-size-adjust: 100% }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: 'Inter', system-ui, sans-serif;
  line-height: 1.6;
  min-height: 100vh;
  padding: 28px max(16px, env(safe-area-inset-left, 16px)) 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* ── Header ─────────────────────────────────────────────────── */
.logo {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 500;
  color: #fff;
  margin-bottom: 4px;
  letter-spacing: -.3px;
}
.logo em { color: var(--accent); font-style: normal }
.tagline { font-size: 13px; color: var(--fg-m); margin-bottom: 28px; text-align: center }

/* ── Progress ───────────────────────────────────────────────── */
.steps {
  display: flex;
  width: 100%;
  max-width: 540px;
  margin-bottom: 28px;
  position: relative;
}
.step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  z-index: 1;
}
.step::before {
  content: '';
  position: absolute;
  top: 13px;
  left: calc(-50% + 14px);
  right: calc(50% + 14px);
  height: 2px;
  background: var(--border);
  z-index: 0;
}
.step:first-child::before { display: none }
.step.done::before { background: var(--accent) }
.step.active::before { background: var(--accent) }

.step-dot {
  width: 26px; height: 26px;
  border-radius: 50%;
  border: 2px solid var(--border);
  background: var(--surf);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--fg-m);
  position: relative;
  z-index: 1;
  transition: border-color .2s, background .2s, color .2s;
}
.step.active .step-dot {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--surf);
}
.step.done .step-dot {
  border-color: var(--accent);
  background: var(--accent);
  color: #0d1117;
}
.step-label {
  font-size: 10px;
  color: var(--fg-m);
  margin-top: 5px;
  text-align: center;
  letter-spacing: .2px;
}
.step.active .step-label { color: var(--accent) }

/* ── Card ───────────────────────────────────────────────────── */
.card {
  width: 100%;
  max-width: 540px;
  background: var(--surf);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}
.card-head {
  padding: 20px 22px 14px;
  border-bottom: 1px solid var(--border);
}
.card-head h2 { font-size: 16px; font-weight: 600; color: #fff }
.card-head p  { font-size: 12px; color: var(--fg-m); margin-top: 3px }
.card-body    { padding: 22px }
.card-foot {
  padding: 14px 22px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

/* ── Sections ───────────────────────────────────────────────── */
section { display: none; width: 100%; max-width: 540px; flex-direction: column; gap: 14px }
section.active { display: flex }

/* ── Tabs ───────────────────────────────────────────────────── */
.tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 18px; gap: 2px }
.tab {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--fg-m);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color .15s, border-color .15s;
  white-space: nowrap;
}
.tab.active { color: var(--accent); border-color: var(--accent) }
.tab-panel { display: none }
.tab-panel.active { display: block }

/* ── Form elements ──────────────────────────────────────────── */
.field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px }
.field:last-child { margin-bottom: 0 }

.label {
  font-size: 12px;
  font-weight: 500;
  color: var(--fg-m);
  letter-spacing: .3px;
  text-transform: uppercase;
}

/* 16px prevents iOS auto-zoom on focus */
input[type=text],
input[type=email],
input[type=password],
input[type=number],
select,
textarea {
  width: 100%;
  padding: 10px 14px;
  background: var(--surf2);
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--fg);
  font-size: 16px;
  font-family: inherit;
  outline: none;
  appearance: none;
  -webkit-appearance: none;
  transition: border-color .15s;
  min-height: 44px;
}
input:focus, select:focus, textarea:focus { border-color: var(--accent) }
textarea {
  resize: vertical;
  min-height: 72px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}
.hint { font-size: 12px; color: var(--fg-m) }

/* ── Grid ───────────────────────────────────────────────────── */
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px }
@media (max-width: 440px) { .g2 { grid-template-columns: 1fr } }

/* ── Radio opts ─────────────────────────────────────────────── */
.radio-group { display: grid; grid-template-columns: 1fr 1fr; gap: 8px }
@media (max-width: 440px) { .radio-group { grid-template-columns: 1fr } }
.radio-opt {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  background: var(--surf2);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color .15s, background .15s;
  min-height: 44px;
}
.radio-opt:hover { border-color: var(--fg-m) }
.radio-opt.sel   { border-color: var(--accent); background: var(--tag) }
.radio-opt input { accent-color: var(--accent); flex-shrink: 0 }
.radio-opt span  { font-size: 13px; font-weight: 500 }
.radio-opt small { font-size: 11px; color: var(--fg-m); display: block; line-height: 1.3 }

/* ── Toggle ─────────────────────────────────────────────────── */
.trow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  gap: 12px;
}
.trow-label strong { font-size: 14px; font-weight: 500 }
.trow-label small  { font-size: 12px; color: var(--fg-m); display: block }
.toggle { position: relative; width: 42px; height: 24px; flex-shrink: 0 }
.toggle input { opacity: 0; width: 0; height: 0 }
.knob {
  position: absolute;
  inset: 0;
  background: var(--border);
  border-radius: 24px;
  cursor: pointer;
  transition: background .2s;
}
.knob::before {
  content: '';
  position: absolute;
  width: 18px; height: 18px;
  left: 3px; top: 3px;
  background: #fff;
  border-radius: 50%;
  transition: transform .2s;
}
input:checked ~ .knob { background: var(--accent) }
input:checked ~ .knob::before { transform: translateX(18px) }

/* ── Tags ───────────────────────────────────────────────────── */
.tags-box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
  background: var(--surf2);
  border: 1px solid var(--border);
  border-radius: 7px;
  cursor: text;
  min-height: 46px;
  transition: border-color .15s;
}
.tags-box:focus-within { border-color: var(--accent) }
.chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  background: var(--tag);
  border: 1px solid var(--accent-d);
  border-radius: 4px;
  font-size: 12px;
  color: var(--accent);
}
.chip-x { cursor: pointer; color: var(--fg-m); font-size: 15px; line-height: 1 }
.chip-x:hover { color: var(--err) }
.tags-inp {
  background: transparent;
  border: none;
  outline: none;
  color: var(--fg);
  font-size: 14px;
  min-width: 80px;
  flex: 1;
  min-height: 28px;
}

/* ── Range ──────────────────────────────────────────────────── */
.range-row { display: flex; align-items: center; gap: 12px }
input[type=range] { flex: 1; accent-color: var(--accent); height: 4px }
.range-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  color: var(--accent);
  min-width: 36px;
  text-align: right;
}

/* ── Eye toggle ─────────────────────────────────────────────── */
.pw-wrap { position: relative }
.pw-wrap input { padding-right: 42px }
.pw-eye {
  position: absolute;
  right: 12px; top: 50%;
  transform: translateY(-50%);
  cursor: pointer;
  color: var(--fg-m);
  user-select: none;
  font-size: 16px;
  line-height: 1;
  padding: 4px;
}

/* ── Status ─────────────────────────────────────────────────── */
.msg {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 11px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}
.msg.ok   { background: #0a1f12; border: 1px solid #1e5934; color: var(--ok) }
.msg.err  { background: #1f0a0a; border: 1px solid #5a1e1e; color: var(--err) }
.msg.info { background: #0a1420; border: 1px solid #1e3d5a; color: var(--accent) }
.msg.warn { background: #1a1505; border: 1px solid #5a4210; color: var(--warn) }
.msg[hidden] { display: none !important }
.spin {
  width: 14px; height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .6s linear infinite;
  flex-shrink: 0;
  margin-top: 1px;
}
@keyframes spin { to { transform: rotate(360deg) } }

/* ── Buttons ────────────────────────────────────────────────── */
.btn {
  padding: 10px 20px;
  border-radius: 7px;
  font-size: 14px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: opacity .15s, background .15s;
  min-height: 44px;
  white-space: nowrap;
}
.btn:disabled { opacity: .4; cursor: not-allowed }
.btn-primary  { background: var(--accent); color: #0d1117 }
.btn-primary:not(:disabled):hover  { background: #79b8ff }
.btn-ghost    { background: transparent; color: var(--fg-m); border: 1px solid var(--border) }
.btn-ghost:not(:disabled):hover    { border-color: var(--fg-m); color: var(--fg) }
.btn-ok       { background: var(--ok);   color: #0d1117 }
.btn-ok:not(:disabled):hover       { opacity: .85 }
.btn-sm { padding: 7px 14px; font-size: 12px; min-height: 36px; border-radius: 6px }

/* ── Badge (account confirmed) ──────────────────────────────── */
.badge {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: #0a1f12;
  border: 1px solid #1e5934;
  border-radius: 8px;
  color: var(--ok);
  font-size: 13px;
}
.badge-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--ok);
  flex-shrink: 0;
  margin-top: 5px;
}

/* ── Divider ────────────────────────────────────────────────── */
.sep {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--fg-m);
  text-transform: uppercase;
  letter-spacing: .5px;
  margin: 6px 0 2px;
}
.sep::before, .sep::after { content: ''; flex: 1; height: 1px; background: var(--border) }

/* ── Collapsible ────────────────────────────────────────────── */
.collapser { overflow: hidden; transition: max-height .3s ease }
.collapser.shut { max-height: 0 }
.collapser.open { max-height: 700px }

/* ── Day buttons ────────────────────────────────────────────── */
.day-row { display: flex; gap: 6px; flex-wrap: wrap }
.day-btn {
  padding: 7px 11px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--border);
  background: var(--surf2);
  color: var(--fg-m);
  cursor: pointer;
  transition: border-color .15s, background .15s, color .15s;
  min-height: 36px;
}
.day-btn.on { border-color: var(--accent); background: var(--tag); color: var(--accent) }

/* ── Cron code block ────────────────────────────────────────── */
.code-block {
  position: relative;
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 12px 14px;
  padding-right: 70px;
}
.code-block code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--fg);
  white-space: pre-wrap;
  word-break: break-all;
  display: block;
  line-height: 1.6;
}
.copy-btn {
  position: absolute;
  top: 8px; right: 8px;
  background: var(--surf2);
  border: 1px solid var(--border);
  color: var(--fg-m);
  font-size: 11px;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: border-color .15s, color .15s;
}
.copy-btn:hover { border-color: var(--fg); color: var(--fg) }
.copy-btn.copied { color: var(--ok); border-color: var(--ok) }

/* ── Summary (step 5) ───────────────────────────────────────── */
.sum { display: flex; flex-direction: column; gap: 7px }
.sum-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 12px;
  background: var(--surf2);
  border-radius: 7px;
  font-size: 13px;
}
.sum-row .k { color: var(--fg-m); flex-shrink: 0 }
.sum-row .v { color: #fff; font-weight: 500; text-align: right }

/* ── Done art ───────────────────────────────────────────────── */
.done-hero { text-align: center; padding: 12px 0 6px }
.done-hero .emo { font-size: 42px; margin-bottom: 10px }
.done-hero h3 { font-size: 17px; font-weight: 600; color: #fff }
.done-hero p  { font-size: 13px; color: var(--fg-m); margin-top: 4px }
</style>
</head>
<body>

<div class="logo">Nope<em>Ri</em></div>
<div class="tagline">Let's get you set up &mdash; takes about 2 minutes.</div>

<!-- Progress -->
<div class="steps" id="steps">
  <div class="step active" data-s="1"><div class="step-dot">1</div><div class="step-label">Account</div></div>
  <div class="step"        data-s="2"><div class="step-dot">2</div><div class="step-label">Profile</div></div>
  <div class="step"        data-s="3"><div class="step-dot">3</div><div class="step-label">AI</div></div>
  <div class="step"        data-s="4"><div class="step-dot">4</div><div class="step-label">Automate</div></div>
  <div class="step"        data-s="5"><div class="step-dot">5</div><div class="step-label">Done</div></div>
</div>

<!-- ══════════════════════════════════════════
     STEP 1 — ACCOUNT
══════════════════════════════════════════ -->
<section id="s1" class="active">
  <div class="card">
    <div class="card-head">
      <h2>Naukri Account</h2>
      <p>Your credentials stay on this machine and are only sent to Naukri.</p>
    </div>
    <div class="card-body">
      <div id="acct-badge" hidden></div>
      <div id="acct-tabs">
        <div class="tabs">
          <div class="tab active" data-tab="login">Password login</div>
          <div class="tab"        data-tab="cookies">Paste cookies</div>
        </div>
        <div class="tab-panel active" id="tab-login">
          <div class="field">
            <div class="label">Email</div>
            <input type="email" id="email" placeholder="you@example.com" autocomplete="email">
          </div>
          <div class="field">
            <div class="label">Password</div>
            <div class="pw-wrap">
              <input type="password" id="password" placeholder="&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;" autocomplete="current-password">
              <span class="pw-eye" id="pw-eye">&#128065;</span>
            </div>
          </div>
          <button class="btn btn-primary" id="btn-login" style="width:100%">Connect to Naukri</button>
          <div class="msg info" id="login-msg" hidden></div>
        </div>
        <div class="tab-panel" id="tab-cookies">
          <p style="font-size:12px;color:var(--fg-m);margin-bottom:14px">Use when CAPTCHA blocks password login.<br>
          Chrome &rarr; DevTools &rarr; Application &rarr; Cookies &rarr; naukri.com &rarr; copy <code style="color:var(--accent)">nauk_at</code></p>
          <div class="field">
            <div class="label">nauk_at <span style="color:var(--err)">*</span></div>
            <textarea id="nauk_at" placeholder="Paste nauk_at value&#8230;" style="min-height:56px"></textarea>
          </div>
          <div class="field">
            <div class="label">nauk_rt <span style="color:var(--fg-m);font-weight:400">(optional)</span></div>
            <input type="text" id="nauk_rt" placeholder="nauk_rt value">
          </div>
          <button class="btn btn-primary" id="btn-cookies" style="width:100%">Save Cookies</button>
          <div class="msg info" id="cookies-msg" hidden></div>
        </div>
      </div>
    </div>
    <div class="card-foot">
      <span style="font-size:12px;color:var(--fg-m)" id="acct-hint">Login or paste cookies to continue.</span>
      <button class="btn btn-primary" id="s1-next" disabled>Next &rarr;</button>
    </div>
  </div>
</section>

<!-- ══════════════════════════════════════════
     STEP 2 — PROFILE
══════════════════════════════════════════ -->
<section id="s2">
  <div class="card">
    <div class="card-head">
      <h2>Your Profile</h2>
      <p>Shapes search queries and AI scoring criteria.</p>
    </div>
    <div class="card-body">
      <div class="field">
        <div class="label">Role Focus</div>
        <div class="radio-group" id="role-group">
          <label class="radio-opt sel"><input type="radio" name="role" value="backend" checked><div><span>Backend</span><small>Node.js, Python, Go&hellip;</small></div></label>
          <label class="radio-opt"><input type="radio" name="role" value="fullstack"><div><span>Fullstack</span><small>Backend-leaning</small></div></label>
          <label class="radio-opt"><input type="radio" name="role" value="frontend"><div><span>Frontend</span><small>React, Next.js&hellip;</small></div></label>
          <label class="radio-opt"><input type="radio" name="role" value="devops"><div><span>DevOps / Cloud</span><small>AWS, K8s&hellip;</small></div></label>
        </div>
      </div>
      <div class="g2">
        <div class="field"><div class="label">Experience (years)</div><input type="number" id="exp-years" value="2" min="0" max="40"></div>
        <div class="field"><div class="label">Notice Period (days)</div><input type="number" id="notice-days" value="30" min="0" max="180"></div>
      </div>
      <div class="field">
        <div class="label">Tech Stack</div>
        <div class="tags-box" id="stack-box"><input class="tags-inp" id="stack-inp" placeholder="Type + Enter to add&hellip;"></div>
        <div class="hint">Press Enter or comma after each technology.</div>
      </div>
      <div class="field">
        <div class="label">Preferred Locations</div>
        <input type="text" id="locations" placeholder="Bangalore, Hyderabad, Mumbai">
        <div class="hint">Comma-separated. Leave blank for All India.</div>
      </div>
      <div class="trow">
        <div class="trow-label"><strong>Include remote jobs</strong></div>
        <label class="toggle"><input type="checkbox" id="apply-remote" checked><span class="knob"></span></label>
      </div>
      <div class="g2" style="margin-top:4px">
        <div class="field"><div class="label">Current CTC (LPA)</div><input type="text" id="current-ctc" value="5"></div>
        <div class="field"><div class="label">Expected CTC (LPA)</div><input type="text" id="expected-ctc" value="7"></div>
      </div>
    </div>
    <div class="card-foot">
      <button class="btn btn-ghost" id="s2-back">&larr; Back</button>
      <button class="btn btn-primary" id="s2-next">Next &rarr;</button>
    </div>
  </div>
</section>

<!-- ══════════════════════════════════════════
     STEP 3 — AI
══════════════════════════════════════════ -->
<section id="s3">
  <div class="card">
    <div class="card-head">
      <h2>AI Scoring</h2>
      <p>Scores each job 0&ndash;100 before applying. No key = all jobs go through.</p>
    </div>
    <div class="card-body">
      <div class="field">
        <div class="label">Provider</div>
        <div class="radio-group" id="provider-group">
          <label class="radio-opt sel"><input type="radio" name="provider" value="openrouter" checked><div><span>OpenRouter</span><small>All models, one key</small></div></label>
          <label class="radio-opt"><input type="radio" name="provider" value="openai"><div><span>OpenAI direct</span><small>GPT-4o / mini</small></div></label>
        </div>
      </div>
      <div class="field"><div class="label">Model</div><select id="model-select"></select></div>
      <div class="field">
        <div class="label" id="key-lbl">API Key &nbsp;<span style="font-weight:400;color:var(--fg-m)">(saved to .env &mdash; never to config.json)</span></div>
        <div class="badge" id="key-found-badge" hidden>
          <div class="badge-dot"></div>
          <div><strong id="key-found-text">Key already set in .env</strong><div style="font-size:12px;margin-top:2px;opacity:.8">No need to re-enter. Leave blank to keep the existing key.</div></div>
        </div>
        <div class="pw-wrap" id="key-input-wrap">
          <input type="password" id="api-key" placeholder="sk-or-&hellip;">
          <span class="pw-eye" id="key-eye">&#128065;</span>
        </div>
        <div class="hint">Leave blank to skip AI scoring.</div>
      </div>
      <div class="field">
        <div class="label">Min Score to Apply</div>
        <div class="range-row">
          <input type="range" id="score-thr" min="0" max="100" value="50">
          <span class="range-num" id="thr-val">50</span>
        </div>
        <div class="hint">Jobs below this score are skipped. Only active when a key is set.</div>
      </div>
      <div class="field">
        <div class="label">Max Applications per Run</div>
        <input type="number" id="daily-limit" value="50" min="1" max="500">
      </div>

      <div class="sep" style="margin-top:4px">Questionnaire AI</div>
      <div class="trow">
        <div class="trow-label">
          <strong>Skip AI for questionnaires</strong>
          <small>Uses cache + common patterns only. No API calls per question.</small>
        </div>
        <label class="toggle"><input type="checkbox" id="skip-qa-ai"><span class="knob"></span></label>
      </div>
      <div class="field">
        <div class="label">Custom Q&amp;A patterns &nbsp;<span style="font-weight:400;color:var(--fg-m)">optional &mdash; added before AI is called</span></div>
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <input type="text" id="qa-q" placeholder="Question (partial match works)" style="flex:2">
          <input type="text" id="qa-a" placeholder="Answer" style="flex:1">
          <button class="btn btn-ghost btn-sm" id="qa-add" style="flex-shrink:0">Add</button>
        </div>
        <div id="qa-list" style="display:flex;flex-direction:column;gap:6px"></div>
        <div class="hint">10 common patterns pre-loaded &mdash; delete any that don&rsquo;t apply to you. Matched case-insensitively against any question containing this text.</div>
      </div>
    </div>
    <div class="card-foot">
      <button class="btn btn-ghost" id="s3-back">&larr; Back</button>
      <button class="btn btn-primary" id="s3-next">Next &rarr;</button>
    </div>
  </div>
</section>

<!-- ══════════════════════════════════════════
     STEP 4 — AUTOMATE
══════════════════════════════════════════ -->
<section id="s4">
  <div class="card">
    <div class="card-head">
      <h2>Automation</h2>
      <p>Schedule the agent with crontab (Ubuntu/Linux) and get Telegram alerts. Both are optional.</p>
    </div>
    <div class="card-body">

      <!-- Cron -->
      <div class="sep">Scheduled runs</div>
      <div class="trow">
        <div class="trow-label">
          <strong>Auto-run the agent</strong>
          <small>Generates a crontab entry for Ubuntu/Linux &mdash; no background Python process needed.</small>
        </div>
        <label class="toggle"><input type="checkbox" id="cron-enable"><span class="knob"></span></label>
      </div>

      <div class="collapser shut" id="cron-block">
        <div style="padding-top:14px;display:flex;flex-direction:column;gap:14px">

          <div class="g2">
            <div class="field">
              <div class="label">Run at (HH:MM)</div>
              <input type="text" id="cron-time" value="08:00" placeholder="08:00" style="font-family:'JetBrains Mono',monospace">
            </div>
            <div class="field">
              <div class="label">Timezone</div>
              <select id="cron-tz">
                <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
                <option value="UTC">UTC</option>
                <option value="America/New_York">America/New_York (ET)</option>
                <option value="America/Los_Angeles">America/Los_Angeles (PT)</option>
                <option value="Europe/London">Europe/London (GMT/BST)</option>
              </select>
            </div>
          </div>

          <div class="field">
            <div class="label">Days</div>
            <div class="day-row" id="day-row">
              <div class="day-btn on" data-d="mon">Mon</div>
              <div class="day-btn on" data-d="tue">Tue</div>
              <div class="day-btn on" data-d="wed">Wed</div>
              <div class="day-btn on" data-d="thu">Thu</div>
              <div class="day-btn on" data-d="fri">Fri</div>
              <div class="day-btn"    data-d="sat">Sat</div>
              <div class="day-btn"    data-d="sun">Sun</div>
            </div>
          </div>

          <!-- Crontab line (Ubuntu / Linux only) -->
          <div style="display:flex;flex-direction:column;gap:10px">
            <div class="label">Add to crontab &nbsp;<span style="font-weight:400;color:var(--fg-m)">(Ubuntu / Linux)</span></div>
            <div class="code-block">
              <code id="cron-code"></code>
              <button class="copy-btn" id="copy-cron">Copy</button>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <button class="btn btn-primary btn-sm" id="btn-install-cron">Install automatically</button>
              <span style="font-size:12px;color:var(--fg-m)">or run <code style="color:var(--accent)">crontab -e</code> and paste the line</span>
            </div>
            <div class="msg" id="cron-install-msg" hidden></div>
          </div>

        </div>
      </div>

      <!-- Telegram -->
      <div class="sep" style="margin-top:16px">Telegram alerts</div>
      <div class="trow">
        <div class="trow-label">
          <strong>Send Telegram notifications</strong>
          <small>Get a message when a job is applied to or when a run finishes.</small>
        </div>
        <label class="toggle"><input type="checkbox" id="tg-enable"><span class="knob"></span></label>
      </div>
      <div class="collapser shut" id="tg-block">
        <div style="padding-top:14px;display:flex;flex-direction:column;gap:14px">
          <div class="msg warn" style="display:flex">
            <span>Token and Chat ID are saved to <strong>.env</strong> only &mdash; never to config.json.</span>
          </div>
          <div class="field">
            <div class="label">Bot Token <span style="color:var(--err)">*</span></div>
            <div class="pw-wrap">
              <input type="password" id="tg-token" placeholder="123456:ABC-DEF&hellip;">
              <span class="pw-eye" id="tg-eye">&#128065;</span>
            </div>
            <div class="hint">Create a bot at <strong>@BotFather</strong> on Telegram.</div>
          </div>
          <div class="field">
            <div class="label">Chat ID <span style="color:var(--err)">*</span></div>
            <input type="text" id="tg-chat" placeholder="Your numeric chat ID">
            <div class="hint">Message <strong>@userinfobot</strong> on Telegram to find yours.</div>
          </div>
        </div>
      </div>

    </div>
    <div class="card-foot">
      <button class="btn btn-ghost" id="s4-back">&larr; Back</button>
      <button class="btn btn-primary" id="s4-next">Next &rarr;</button>
    </div>
  </div>
</section>

<!-- ══════════════════════════════════════════
     STEP 5 — DONE
══════════════════════════════════════════ -->
<section id="s5">
  <div class="card">
    <div class="card-head">
      <h2>All set!</h2>
      <p>Review and save to write <code>config.json</code> and close this window.</p>
    </div>
    <div class="card-body">
      <div class="done-hero">
        <div class="emo">&#x1F680;</div>
        <h3>Ready to launch</h3>
        <p>NopeRi will search and apply to jobs matching your profile.</p>
      </div>
      <div class="sum" id="summary" style="margin-top:20px"></div>
    </div>
    <div class="card-foot">
      <button class="btn btn-ghost" id="s5-back">&larr; Back</button>
      <button class="btn btn-ok" id="btn-save">Save &amp; Close</button>
    </div>
  </div>
  <div class="msg ok" id="save-msg" hidden></div>
</section>

<script>
const API = 'http://localhost:8765';

let step          = 1;
let accountDone   = false;
let accountType   = '';    // 'login' | 'cookies' | 'env'
let storedSession = {};
let serverEnv     = {};    // from /api/config _env block

const MODELS = {
  openrouter: [
    {v:'anthropic/claude-3.5-haiku',            l:'claude-3.5-haiku — fast + cheap'},
    {v:'anthropic/claude-3.5-sonnet',           l:'claude-3.5-sonnet — balanced'},
    {v:'anthropic/claude-sonnet-4-5',           l:'claude-sonnet-4-5 — latest'},
    {v:'openai/gpt-4o-mini',                    l:'gpt-4o-mini — cheapest'},
    {v:'openai/gpt-4o',                         l:'gpt-4o'},
    {v:'google/gemini-2.0-flash-001',           l:'gemini-2.0-flash'},
    {v:'meta-llama/llama-3.1-8b-instruct:free', l:'llama-3.1-8b — FREE'},
    {v:'google/gemma-3-4b-it:free',             l:'gemma-3-4b — FREE'},
  ],
  openai: [
    {v:'gpt-4o-mini', l:'gpt-4o-mini — cheapest'},
    {v:'gpt-4o',      l:'gpt-4o'},
  ],
};

// ── Navigation ──────────────────────────────────────────────────────────────
function goTo(n) {
  document.getElementById('s' + step).classList.remove('active');
  document.querySelectorAll('.step').forEach(el => {
    const s = +el.dataset.s;
    el.classList.toggle('done',   s < n);
    el.classList.toggle('active', s === n);
  });
  step = n;
  document.getElementById('s' + n).classList.add('active');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function setMsg(el, html, type) {
  el.innerHTML = html;
  el.className = 'msg ' + type;
  el.hidden = false;
}

function post(path, body) {
  return fetch(API + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(r => r.json());
}

// ── Collapsible ──────────────────────────────────────────────────────────────
function collapseOn(cbId, blockId) {
  document.getElementById(cbId).addEventListener('change', e => {
    const b = document.getElementById(blockId);
    b.classList.toggle('open',  e.target.checked);
    b.classList.toggle('shut', !e.target.checked);
  });
}
collapseOn('cron-enable', 'cron-block');
collapseOn('tg-enable',   'tg-block');

// ── Day toggles ──────────────────────────────────────────────────────────────
document.querySelectorAll('.day-btn').forEach(b => {
  b.addEventListener('click', () => {
    b.classList.toggle('on');
    updateCronCmd();
  });
});

// ── Radio helpers ────────────────────────────────────────────────────────────
function wireRadioGroup(groupId) {
  document.querySelectorAll(`#${groupId} .radio-opt`).forEach(opt => {
    opt.addEventListener('click', () => {
      document.querySelectorAll(`#${groupId} .radio-opt`).forEach(o => o.classList.remove('sel'));
      opt.classList.add('sel');
    });
  });
}
wireRadioGroup('role-group');
wireRadioGroup('provider-group');

// ── Cron command builder ──────────────────────────────────────────────────────
function activeDays() {
  return [...document.querySelectorAll('.day-btn.on')].map(b => b.dataset.d);
}

function toCronExpr(timeStr, days) {
  const [h, m] = (timeStr || '08:00').split(':').map(Number);
  const dayMap  = {sun:0, mon:1, tue:2, wed:3, thu:4, fri:5, sat:6};
  const nums    = days.map(d => dayMap[d]).sort((a,b) => a-b);
  let   dExpr;
  if (nums.length === 7)                                    dExpr = '*';
  else if (JSON.stringify(nums) === JSON.stringify([1,2,3,4,5])) dExpr = '1-5';
  else                                                       dExpr = nums.join(',');
  return `${m} ${h} * * ${dExpr}`;
}

function updateCronCmd() {
  const time = document.getElementById('cron-time').value || '08:00';
  const days = activeDays();
  const cwd  = serverEnv.cwd    || '/path/to/NopeRi';
  const py   = serverEnv.python || 'python3';
  const expr = toCronExpr(time, days);
  document.getElementById('cron-code').textContent =
    `${expr} cd "${cwd}" && "${py}" apply_agent.py >> "${cwd}/noperi.log" 2>&1`;
}

document.getElementById('cron-time').addEventListener('input', updateCronCmd);

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
  });
}

document.getElementById('copy-cron').addEventListener('click', () => {
  copyText(document.getElementById('cron-code').textContent,
           document.getElementById('copy-cron'));
});

document.getElementById('btn-install-cron').addEventListener('click', async () => {
  const btn = document.getElementById('btn-install-cron');
  const msg = document.getElementById('cron-install-msg');
  const line = document.getElementById('cron-code').textContent.trim();
  btn.disabled = true; btn.textContent = 'Installing…';
  try {
    const res = await post('/api/install-cron', {cron_line: line});
    if (res.ok) {
      setMsg(msg, '&#x2713; Crontab entry installed. Run <code>crontab -l</code> to verify.', 'ok');
      btn.textContent = 'Installed';
    } else {
      setMsg(msg, '&#x2715; ' + (res.error || 'Install failed.'), 'err');
      btn.disabled = false; btn.textContent = 'Install automatically';
    }
  } catch(e) {
    setMsg(msg, '&#x2715; Server error.', 'err');
    btn.disabled = false; btn.textContent = 'Install automatically';
  }
});

// ── Step 1: Account ───────────────────────────────────────────────────────────
document.querySelectorAll('#acct-tabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#acct-tabs .tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

document.getElementById('pw-eye').addEventListener('click', () => {
  const i = document.getElementById('password');
  i.type = i.type === 'password' ? 'text' : 'password';
});

function markAcctDone(title, detail) {
  accountDone = true;
  const b = document.getElementById('acct-badge');
  b.innerHTML = '<div class="badge-dot"></div><div><strong>' + title + '</strong>'
    + (detail ? '<div style="font-size:12px;margin-top:2px;opacity:.8">' + detail + '</div>' : '') + '</div>';
  b.className = 'badge';
  b.hidden = false;
  document.getElementById('acct-tabs').style.display = 'none';
  document.getElementById('s1-next').disabled = false;
  document.getElementById('acct-hint').textContent = '';
}

document.getElementById('btn-login').addEventListener('click', async () => {
  const btn   = document.getElementById('btn-login');
  const msg   = document.getElementById('login-msg');
  const email = document.getElementById('email').value.trim();
  const pw    = document.getElementById('password').value;
  if (!email || !pw) { setMsg(msg, 'Please enter email and password.', 'err'); return; }
  btn.disabled = true; btn.textContent = 'Connecting…';
  msg.innerHTML = '<span class="spin"></span>&nbsp; Logging in to Naukri…';
  msg.className = 'msg info'; msg.hidden = false;
  try {
    const res = await post('/api/login', {email, password: pw});
    if (res.ok) {
      storedSession = {nauk_at: res.nauk_at, nauk_rt: res.nauk_rt || ''};
      accountType = 'login';
      markAcctDone('Connected as ' + email);
      msg.hidden = true;
    } else {
      setMsg(msg, '&#x2715; ' + (res.error || 'Login failed — check credentials.'), 'err');
      btn.disabled = false; btn.textContent = 'Connect to Naukri';
    }
  } catch(e) {
    setMsg(msg, '&#x2715; Could not reach setup server.', 'err');
    btn.disabled = false; btn.textContent = 'Connect to Naukri';
  }
});

document.getElementById('btn-cookies').addEventListener('click', async () => {
  const btn = document.getElementById('btn-cookies');
  const msg = document.getElementById('cookies-msg');
  const at  = document.getElementById('nauk_at').value.trim();
  const rt  = document.getElementById('nauk_rt').value.trim();
  if (!at) { setMsg(msg, 'nauk_at is required.', 'err'); return; }
  btn.disabled = true; btn.textContent = 'Saving…';
  msg.innerHTML = '<span class="spin"></span>&nbsp; Saving…';
  msg.className = 'msg info'; msg.hidden = false;
  try {
    const res = await post('/api/cookies', {nauk_at: at, nauk_rt: rt});
    if (res.ok) {
      storedSession = {nauk_at: at, nauk_rt: rt};
      accountType = 'cookies';
      markAcctDone('Session cookies saved', 'Re-authenticate any time from --setup');
      msg.hidden = true;
    } else {
      setMsg(msg, '&#x2715; ' + (res.error || 'Failed.'), 'err');
      btn.disabled = false; btn.textContent = 'Save Cookies';
    }
  } catch(e) {
    setMsg(msg, '&#x2715; Server error.', 'err');
    btn.disabled = false; btn.textContent = 'Save Cookies';
  }
});

document.getElementById('s1-next').addEventListener('click', () => goTo(2));

// ── Step 2: Tags ──────────────────────────────────────────────────────────────
const defStack = ['Node.js','Python','MongoDB','REST APIs','AWS','Docker'];
const tagSet   = new Set(defStack);

function renderTags() {
  const box = document.getElementById('stack-box');
  const inp = document.getElementById('stack-inp');
  box.querySelectorAll('.chip').forEach(c => c.remove());
  [...tagSet].forEach(t => {
    const el = document.createElement('span');
    el.className = 'chip';
    el.innerHTML = t + '<span class="chip-x" data-t="' + t + '">×</span>';
    box.insertBefore(el, inp);
  });
}
document.getElementById('stack-box').addEventListener('click', e => {
  if (e.target.classList.contains('chip-x')) {
    tagSet.delete(e.target.dataset.t); renderTags();
  } else {
    document.getElementById('stack-inp').focus();
  }
});
document.getElementById('stack-inp').addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    const v = e.target.value.replace(',','').trim();
    if (v) { tagSet.add(v); renderTags(); e.target.value = ''; }
  } else if (e.key === 'Backspace' && !e.target.value && tagSet.size) {
    const last = [...tagSet].pop(); tagSet.delete(last); renderTags();
  }
});
renderTags();

document.getElementById('s2-back').addEventListener('click', () => goTo(1));
document.getElementById('s2-next').addEventListener('click', () => goTo(3));

// ── Step 3: AI ────────────────────────────────────────────────────────────────
function reloadModels() {
  const prov = document.querySelector('input[name="provider"]:checked').value;
  const sel  = document.getElementById('model-select');
  sel.innerHTML = '';
  MODELS[prov].forEach(m => {
    const o = document.createElement('option');
    o.value = m.v; o.textContent = m.l; sel.appendChild(o);
  });
  const envKey = prov === 'openrouter' ? 'OPENROUTER_API_KEY' : 'OPEN_API_KEY';
  document.getElementById('key-lbl').innerHTML =
    'API Key &nbsp;<span style="font-weight:400;color:var(--fg-m)">(' + envKey + ' &mdash; saved to .env)</span>';
}
document.querySelectorAll('input[name="provider"]').forEach(r => r.addEventListener('change', reloadModels));
document.getElementById('key-eye').addEventListener('click', () => {
  const i = document.getElementById('api-key'); i.type = i.type === 'password' ? 'text' : 'password';
});
document.getElementById('score-thr').addEventListener('input', e => {
  document.getElementById('thr-val').textContent = e.target.value;
});
reloadModels();
// ── Custom Q&A ────────────────────────────────────────────────────────────────
const _qa = [];

function renderQA() {
  const list = document.getElementById('qa-list');
  list.innerHTML = '';
  _qa.forEach((item, i) => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;background:var(--surf2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:13px';
    row.innerHTML = '<span style="flex:2;color:var(--fg)">' + item.question + '</span>'
      + '<span style="color:var(--fg-m)">&rarr;</span>'
      + '<span style="flex:1;color:var(--accent)">' + item.answer + '</span>'
      + '<span style="cursor:pointer;color:var(--fg-m);font-size:16px;padding:0 4px" data-i="'+i+'">&times;</span>';
    row.querySelector('[data-i]').addEventListener('click', e => {
      _qa.splice(+e.target.dataset.i, 1); renderQA();
    });
    list.appendChild(row);
  });
}

document.getElementById('qa-add').addEventListener('click', () => {
  const q = document.getElementById('qa-q').value.trim();
  const a = document.getElementById('qa-a').value.trim();
  if (!q || !a) return;
  _qa.push({question: q, answer: a});
  renderQA();
  document.getElementById('qa-q').value = '';
  document.getElementById('qa-a').value = '';
  document.getElementById('qa-q').focus();
});
['qa-q','qa-a'].forEach(id => {
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('qa-add').click();
  });
});

document.getElementById('s3-back').addEventListener('click', () => goTo(3-1));
document.getElementById('s3-next').addEventListener('click', () => goTo(4));

// ── Step 4: Automate ──────────────────────────────────────────────────────────
document.getElementById('tg-eye').addEventListener('click', () => {
  const i = document.getElementById('tg-token'); i.type = i.type === 'password' ? 'text' : 'password';
});
document.getElementById('s4-back').addEventListener('click', () => goTo(3));
document.getElementById('s4-next').addEventListener('click', () => { buildSummary(); goTo(5); });

// ── Step 5: Save ──────────────────────────────────────────────────────────────
function buildSummary() {
  const role     = document.querySelector('input[name="role"]:checked').value;
  const exp      = document.getElementById('exp-years').value;
  const stack    = [...tagSet].join(', ') || '—';
  const locs     = document.getElementById('locations').value.trim() || 'All India';
  const remote   = document.getElementById('apply-remote').checked ? 'Yes' : 'No';
  const provider = document.querySelector('input[name="provider"]:checked').value;
  const model    = document.getElementById('model-select').value.split('/').pop();
  const hasKey   = !!document.getElementById('api-key').value.trim();
  const thr      = document.getElementById('score-thr').value;
  const limit    = document.getElementById('daily-limit').value;
  const cronOn   = document.getElementById('cron-enable').checked;
  const cronTime = document.getElementById('cron-time').value || '08:00';
  const tgOn     = document.getElementById('tg-enable').checked;
  const acct     = accountType === 'login' ? 'Logged in'
                 : accountType === 'cookies' ? 'Cookies saved'
                 : 'Using .env credentials';
  const rows = [
    ['Account',    acct],
    ['Role',       role.charAt(0).toUpperCase() + role.slice(1)],
    ['Experience', exp + ' year(s)'],
    ['Tech stack', stack.length > 46 ? stack.slice(0,44)+'…' : stack],
    ['Locations',  locs],
    ['Remote',     remote],
    ['AI',         provider + ' / ' + model],
    ['API key',    hasKey ? 'Set (saved to .env)' : 'Not set'],
    ['Min score',  thr + ' / 100'],
    ['Max applies',limit + ' per run'],
    ['Scheduled',  cronOn ? cronTime + ' (crontab)' : 'Off — manual only'],
    ['Telegram',   tgOn ? 'Enabled' : 'Off'],
  ];
  document.getElementById('summary').innerHTML = rows
    .map(([k,v]) => '<div class="sum-row"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>')
    .join('');
}

document.getElementById('s5-back').addEventListener('click', () => goTo(4));

document.getElementById('btn-save').addEventListener('click', async () => {
  const btn  = document.getElementById('btn-save');
  const msg  = document.getElementById('save-msg');
  btn.disabled = true; btn.textContent = 'Saving…';

  const role     = document.querySelector('input[name="role"]:checked').value;
  const locs     = document.getElementById('locations').value.split(',').map(s => s.trim()).filter(Boolean);
  const provider = document.querySelector('input[name="provider"]:checked').value;
  const model    = document.getElementById('model-select').value;
  const cronOn   = document.getElementById('cron-enable').checked;
  const cronTime = document.getElementById('cron-time').value || '08:00';
  const cronTz   = document.getElementById('cron-tz').value;
  const days     = activeDays();
  const tgOn     = document.getElementById('tg-enable').checked;
  const apiKey   = document.getElementById('api-key').value.trim();
  const tgToken  = document.getElementById('tg-token').value.trim();
  const tgChat   = document.getElementById('tg-chat').value.trim();

  const qMap = {
    backend:   [['Node.js backend developer','{l}'],['Python backend developer','{l}'],['Node.js Developer',''],['Python Developer','']],
    fullstack: [['Full Stack Developer Node.js','{l}'],['Fullstack Engineer Python','{l}'],['MERN Stack Developer','{l}'],['Node.js Full Stack','']],
    frontend:  [['React Developer','{l}'],['Frontend Engineer','{l}'],['Next.js Developer','{l}'],['TypeScript Developer','']],
    devops:    [['DevOps Engineer','{l}'],['Cloud Engineer AWS','{l}'],['Site Reliability Engineer','{l}'],['Platform Engineer','']],
  };
  const pLoc = locs[0] || '';
  const queries = (qMap[role]||qMap.backend).map(([kw,lt]) => ({keyword:kw, location: lt==='{l}' ? pLoc : lt}));

  const env_vars = {};
  if (apiKey) env_vars[provider==='openrouter' ? 'OPENROUTER_API_KEY' : 'OPEN_API_KEY'] = apiKey;
  if (tgToken) env_vars['TELEGRAM_BOT_TOKEN'] = tgToken;
  if (tgChat)  env_vars['TELEGRAM_CHAT_ID']   = tgChat;

  const config = {
    questionnaire: {
      skip_ai:   document.getElementById('skip-qa-ai').checked,
      common_qa: _qa.slice(),
    },
    profile: {
      role_focus:       role,
      experience_years: parseInt(document.getElementById('exp-years').value)||2,
      tech_stack:       [...tagSet],
      locations:        locs,
      apply_remote:     document.getElementById('apply-remote').checked,
      current_ctc:      document.getElementById('current-ctc').value.trim()||'5',
      expected_ctc:     document.getElementById('expected-ctc').value.trim()||'7',
      notice_days:      parseInt(document.getElementById('notice-days').value)||30,
    },
    ai: {
      provider,
      model,
      score_threshold:   parseInt(document.getElementById('score-thr').value),
      daily_apply_limit: parseInt(document.getElementById('daily-limit').value)||50,
    },
    cron: {
      apply: {
        enabled:  cronOn,
        schedule: cronTime,
        days:     days.join(',') || 'mon-fri',
        timezone: cronTz,
      },
    },
    telegram: { enabled: tgOn },
    queries,
    session: storedSession,
    env_vars,
  };

  try {
    const res = await post('/api/save', config);
    if (res.ok) {
      setMsg(msg, '&#x2713; config.json saved — you can close this tab.', 'ok');
      btn.textContent = '&#x2713; Saved'; btn.className = 'btn btn-ghost';
      setTimeout(() => fetch(API+'/api/done', {method:'POST'}).catch(()=>{}), 800);
    } else {
      setMsg(msg, '&#x2715; ' + (res.error||'Save failed.'), 'err');
      btn.disabled = false; btn.textContent = 'Save & Close';
    }
  } catch(e) {
    setMsg(msg, '&#x2715; Server error.', 'err');
    btn.disabled = false; btn.textContent = 'Save & Close';
  }
});

// ── Boot: pre-fill from existing config ──────────────────────────────────────
fetch(API + '/api/config')
  .then(r => r.json())
  .then(cfg => {
    const p  = cfg.profile  || {};
    const ai = cfg.ai       || {};
    const s  = cfg.session  || {};
    const env = cfg._env    || {};

    serverEnv = env;
    updateCronCmd();

    // AI key already in .env → show badge, keep input but collapse it
    if (env.has_ai_key) {
      const label = {openrouter: 'OpenRouter', openai: 'OpenAI'}[env.ai_key_provider] || 'AI';
      document.getElementById('key-found-text').textContent = label + ' key already set in .env';
      document.getElementById('key-found-badge').hidden = false;
    }

    // Auto-skip account step
    if (env.has_credentials) {
      storedSession = s.nauk_at ? s : {};
      accountType = 'env';
      markAcctDone('Credentials found in .env',
        'NAUKRI_USERNAME and PASSWORD are set — login step skipped.');
      goTo(2);
    } else if (s.nauk_at) {
      storedSession = s;
      accountType = 'cookies';
      markAcctDone('Stored session found', 'Proceed or re-authenticate above.');
    }

    // Pre-fill profile
    if (p.experience_years) document.getElementById('exp-years').value  = p.experience_years;
    if (p.notice_days)      document.getElementById('notice-days').value = p.notice_days;
    if (p.current_ctc)      document.getElementById('current-ctc').value = p.current_ctc;
    if (p.expected_ctc)     document.getElementById('expected-ctc').value = p.expected_ctc;
    if (p.apply_remote !== undefined) document.getElementById('apply-remote').checked = p.apply_remote;
    if (p.locations && p.locations.length)
      document.getElementById('locations').value = p.locations.join(', ');
    if (p.role_focus) {
      const r = document.querySelector('input[name="role"][value="'+p.role_focus+'"]');
      if (r) { r.checked = true; r.closest('.radio-opt').classList.add('sel'); }
    }
    if (p.tech_stack && p.tech_stack.length) {
      tagSet.clear(); p.tech_stack.forEach(t => tagSet.add(t)); renderTags();
    }

    // Pre-fill AI
    if (ai.provider) {
      const r = document.querySelector('input[name="provider"][value="'+ai.provider+'"]');
      if (r) { r.checked = true; r.closest('.radio-opt').classList.add('sel'); reloadModels(); }
    }
    if (ai.score_threshold !== undefined) {
      document.getElementById('score-thr').value = ai.score_threshold;
      document.getElementById('thr-val').textContent = ai.score_threshold;
    }
    if (ai.daily_apply_limit) document.getElementById('daily-limit').value = ai.daily_apply_limit;
    if (ai.model) {
      setTimeout(() => {
        const o = document.querySelector('#model-select option[value="'+ai.model+'"]');
        if (o) document.getElementById('model-select').value = ai.model;
      }, 60);
    }

    // Pre-fill cron
    const cr = ((cfg.cron||{}).apply)||{};
    if (cr.enabled) {
      document.getElementById('cron-enable').checked = true;
      document.getElementById('cron-block').classList.replace('shut','open');
    }
    if (cr.schedule) document.getElementById('cron-time').value = cr.schedule;
    if (cr.timezone) document.getElementById('cron-tz').value = cr.timezone;
    if (cr.days) {
      const dl = cr.days.split(',').map(d => d.trim());
      document.querySelectorAll('.day-btn').forEach(b => b.classList.toggle('on', dl.includes(b.dataset.d)));
    }
    updateCronCmd();

    // Pre-fill questionnaire
    const qa = ((cfg.questionnaire||{}).common_qa)||[];
    if (qa.length) {
      qa.forEach(p => _qa.push(p));
    } else {
      // First-time: seed 10 common patterns
      [
        {question: 'rotational shifts',          answer: 'No'},
        {question: 'work on weekends',            answer: 'No'},
        {question: 'night shift',                 answer: 'No'},
        {question: 'bond or service agreement',   answer: 'No'},
        {question: 'contract or freelance',       answer: 'No'},
        {question: 'valid passport',              answer: 'Yes'},
        {question: 'background verification',     answer: 'Yes'},
        {question: 'drug test',                   answer: 'Yes'},
        {question: 'currently employed',          answer: 'Yes'},
        {question: 'willing to travel',           answer: 'No'},
      ].forEach(p => _qa.push(p));
    }
    renderQA();
    if ((cfg.questionnaire||{}).skip_ai)
      document.getElementById('skip-qa-ai').checked = true;

    // Pre-fill telegram
    if ((cfg.telegram||{}).enabled) {
      document.getElementById('tg-enable').checked = true;
      document.getElementById('tg-block').classList.replace('shut','open');
    }
  })
  .catch(() => {});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    _shutdown_event: threading.Event = None

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._html(_HTML)
        elif self.path == '/api/config':
            self._get_config()
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        body = self._body()
        if   self.path == '/api/login':        self._login(body)
        elif self.path == '/api/cookies':      self._cookies(body)
        elif self.path == '/api/save':         self._save(body)
        elif self.path == '/api/install-cron': self._install_cron(body)
        elif self.path == '/api/done':
            self._json({'ok': True})
            threading.Thread(target=self._shutdown_event.set, daemon=True).start()
        else:
            self._json({'error': 'not found'}, 404)

    # ── handlers ───────────────────────────────────────────────────────────

    def _get_config(self):
        from src.utils.config_manager import ConfigManager
        cfg = ConfigManager()
        try:
            data = cfg.load()
        except Exception:
            data = {}

        has_or  = bool(os.getenv('OPENROUTER_API_KEY'))
        has_oai = bool(os.getenv('OPEN_API_KEY'))
        data['_env'] = {
            'has_credentials': bool(os.getenv('NAUKRI_USERNAME')) and bool(os.getenv('PASSWORD')),
            'has_ai_key':      has_or or has_oai,
            'ai_key_provider': 'openrouter' if has_or else ('openai' if has_oai else ''),
            'cwd':             str(Path.cwd()),
            'python':          sys.executable,
        }
        self._json(data)

    def _login(self, body: dict):
        email    = body.get('email', '').strip()
        password = body.get('password', '').strip()
        if not email or not password:
            self._json({'ok': False, 'error': 'Email and password required.'})
            return
        try:
            from src.client.naukri_client import NaukriLoginClient
            client = NaukriLoginClient(email, password)
            client.login()
            nauk_at = str(client.session.cookies.get('nauk_at', ''))
            nauk_rt = str(client.session.cookies.get('nauk_rt', ''))
            self._store_session(nauk_at, nauk_rt)
            self._json({'ok': True, 'nauk_at': nauk_at, 'nauk_rt': nauk_rt})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def _cookies(self, body: dict):
        nauk_at = body.get('nauk_at', '').strip()
        nauk_rt = body.get('nauk_rt', '').strip()
        if not nauk_at:
            self._json({'ok': False, 'error': 'nauk_at is required.'})
            return
        try:
            self._store_session(nauk_at, nauk_rt)
            self._json({'ok': True})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def _save(self, body: dict):
        from src.utils.config_manager import ConfigManager, _deep_merge, PROMPT_PATH
        env_vars = body.pop('env_vars', {})
        self._write_env(env_vars)
        cfg = ConfigManager()
        try:
            merged = _deep_merge(cfg.load(), body)
            cfg.save(merged)
            if not PROMPT_PATH.exists():
                PROMPT_PATH.write_text(cfg.generate_prompt_from_config(merged), encoding='utf-8')
            self._json({'ok': True})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def _install_cron(self, body: dict):
        """Install a crontab entry on Linux / macOS."""
        if sys.platform not in ('linux', 'darwin') and not sys.platform.startswith('linux'):
            self._json({'ok': False, 'error': 'Automatic install only supported on Linux / macOS.'})
            return
        cron_line = body.get('cron_line', '').strip()
        if not cron_line:
            self._json({'ok': False, 'error': 'No cron line provided.'})
            return
        try:
            # Read existing crontab (ignore error when none exists)
            existing = subprocess.run(
                ['crontab', '-l'],
                capture_output=True, text=True,
            ).stdout

            # Avoid duplicates: strip any old NopeRi line
            lines = [l for l in existing.splitlines()
                     if 'apply_agent.py' not in l and l.strip()]
            lines.append(cron_line)
            new_crontab = '\n'.join(lines) + '\n'

            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.crontab', delete=False, encoding='utf-8'
            ) as f:
                f.write(new_crontab)
                tmp = f.name

            result = subprocess.run(['crontab', tmp], capture_output=True, text=True)
            Path(tmp).unlink(missing_ok=True)

            if result.returncode == 0:
                self._json({'ok': True})
            else:
                self._json({'ok': False, 'error': result.stderr or 'crontab command failed'})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _write_env(env_vars: dict) -> None:
        if not env_vars:
            return
        env_path = Path('.env')
        try:
            from dotenv import set_key
            if not env_path.exists():
                env_path.touch()
            for key, val in env_vars.items():
                if val and str(val).strip():
                    set_key(str(env_path), key, str(val).strip())
        except ImportError:
            existing: dict[str, str] = {}
            if env_path.exists():
                for line in env_path.read_text(encoding='utf-8').splitlines():
                    if '=' in line and not line.startswith('#'):
                        k, _, v = line.partition('=')
                        existing[k.strip()] = v.strip()
            for key, val in env_vars.items():
                if val and str(val).strip():
                    existing[key] = str(val).strip()
            env_path.write_text(
                '\n'.join(f'{k}={v}' for k, v in existing.items()) + '\n',
                encoding='utf-8',
            )

    @staticmethod
    def _store_session(nauk_at: str, nauk_rt: str):
        from src.utils.config_manager import ConfigManager, _deep_merge
        cfg  = ConfigManager()
        data = _deep_merge(cfg.load(), {'session': {'nauk_at': nauk_at, 'nauk_rt': nauk_rt}})
        cfg.save(data)

    def _body(self) -> dict:
        length = int(self.headers.get('Content-Length', 0))
        raw    = self.rfile.read(length) if length else b'{}'
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _html(self, html: str):
        data = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch(port: int = PORT) -> None:
    """
    Start the setup wizard.
    Opens http://localhost:<port>, blocks until the user saves and closes.
    """
    done = threading.Event()
    _Handler._shutdown_event = done

    server = HTTPServer(('localhost', port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f'http://localhost:{port}'
    print(f'\n  NopeRi Setup  ->  opening {url}')
    print('  Complete the setup in your browser, then return here.\n')
    webbrowser.open(url)

    done.wait()
    server.shutdown()
    print('  Setup complete — continuing…\n')
