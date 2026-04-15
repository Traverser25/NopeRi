"""
NopeRi TUI — Interactive terminal UI for Naukri job search & apply.
Run:  python tui.py

Search works WITHOUT login (unauthenticated).
Apply requires login.
"""

import base64
import os
import threading
import time
import random
from dotenv import load_dotenv
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Log, Static,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOB_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"

_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALrlQ+djR0RjJwBF1xuisHmdFv334MIm
K6LgzJhmLhN7B5yuEyaKoasgXQk3+OQglsOaBxEJ0j5PcTL3nbOvt80CAwEAAQ==
-----END PUBLIC KEY-----"""

# Minimum gap between search requests (seconds) — anti-ban
_MIN_SEARCH_GAP  = 4.0
# Minimum gap between apply requests — on top of client-side 8-15s
_MIN_APPLY_GAP   = 3.0

# ---------------------------------------------------------------------------
# nkparam generator (inline, no external module needed)
# ---------------------------------------------------------------------------

_rsa_cipher = PKCS1_v1_5.new(RSA.import_key(_PUBLIC_KEY))

def _make_nkparam() -> str:
    ts        = int(time.time() * 1000)
    plaintext = f"v0|{ts}|121_srp".encode()
    return base64.b64encode(_rsa_cipher.encrypt(plaintext)).decode()


# ---------------------------------------------------------------------------
# Unauthenticated session (Chrome fingerprint)
# ---------------------------------------------------------------------------

def _anon_session():
    import httpcloak
    return httpcloak.Session(preset="chrome-latest", timeout=30)


def _search_headers() -> dict:
    return {
        "authority":        "www.naukri.com",
        "accept":           "application/json",
        "accept-encoding":  "gzip, deflate, br, zstd",
        "accept-language":  "en-US,en;q=0.9",
        "appid":            "109",
        "systemid":         "jobseeker",
        "clientid":         "d3skt0p",
        "gid":              "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
        "x-requested-with": "XMLHttpRequest",
        "referer":          "https://www.naukri.com/",
        "nkparam":          _make_nkparam(),
    }


# ---------------------------------------------------------------------------
# Raw search (no login)
# ---------------------------------------------------------------------------

def _raw_search(keyword: str, location: str, experience: int,
                job_age: int, results_per_page: int) -> list[dict]:
    kw_slug = keyword.strip().lower().replace(".", "-dot-").replace(" ", "-").replace("+", "-").strip("-")
    loc_slug = location.strip().lower().replace(" ", "-")
    seo_key  = f"{kw_slug}-jobs-in-{loc_slug}-1" if loc_slug else f"{kw_slug}-jobs-1"

    params = {
        "noOfResults":    results_per_page,
        "urlType":        "search_by_keyword",
        "searchType":     "adv",
        "keyword":        keyword,
        "k":              keyword,
        "pageNo":         1,
        "experience":     experience,
        "jobAge":         job_age,
        "nignbevent_src": "jobsearchDeskGNB",
        "seoKey":         seo_key,
        "src":            "jobsearchDesk",
    }
    if location.strip():
        params["location"] = location

    session = _anon_session()
    resp    = session.get(JOB_SEARCH_URL, headers=_search_headers(), params=params)

    if resp.status_code == 403:
        raise RuntimeError("403 — nkparam rejected (Naukri may have changed signing)")
    if not resp.ok:
        raise RuntimeError(f"Search failed: {resp.status_code}")

    data = resp.json()
    raw  = data.get("jobDetails") or data.get("jobs") or []

    jobs = []
    for r in raw:
        exp = sal = loc = ""
        for item in r.get("placeholders", []):
            t = item.get("type")
            if t == "experience": exp = item.get("label", "")
            elif t == "salary":   sal = item.get("label", "")
            elif t == "location": loc = item.get("label", "")
        jd_url = r.get("jdURL", "")
        jobs.append({
            "job_id":     str(r.get("jobId") or r.get("id") or ""),
            "title":      r.get("title") or r.get("jobTitle") or "N/A",
            "company":    r.get("companyName") or "N/A",
            "experience": exp or r.get("experienceText") or "N/A",
            "location":   loc,
            "salary":     sal or "Not disclosed",
            "skills":     [s.strip() for s in r.get("tagsAndSkills", "").split(",") if s.strip()],
            "posted":     r.get("footerPlaceholderLabel") or "N/A",
            "url":        f"https://www.naukri.com{jd_url}" if jd_url else "",
            "description": r.get("jobDescription") or "",
            "_raw":       r,
        })
    return jobs


# ---------------------------------------------------------------------------
# Thread helper
# ---------------------------------------------------------------------------

def run_bg(app, fn, *args, on_done=None, on_err=None):
    import traceback as _tb
    def _worker():
        try:
            result = fn(*args)
            if on_done:
                app.call_from_thread(on_done, result)
        except Exception as exc:
            tb_str = _tb.format_exc()   # capture while still in worker thread
            if on_err:
                app.call_from_thread(on_err, exc, tb_str)
    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Login modal
# ---------------------------------------------------------------------------

class LoginScreen(ModalScreen):

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Label("Naukri Login", id="login-title")
            yield Input(placeholder="Email / Phone", id="inp-user")
            yield Input(placeholder="Password", id="inp-pass", password=True)
            yield Label("", id="login-err")
            with Horizontal(id="login-btns"):
                yield Button("Login", variant="success", id="btn-do-login")
                yield Button("Cancel", variant="error",   id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        u = self.query_one("#inp-user", Input).value.strip()
        p = self.query_one("#inp-pass", Input).value.strip()
        if not u or not p:
            self.query_one("#login-err", Label).update("Username and password required")
            return
        self.dismiss((u, p))


# ---------------------------------------------------------------------------
# OTP modal
# ---------------------------------------------------------------------------

class OTPScreen(ModalScreen):

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Label("OTP Required", id="login-title")
            yield Label("Naukri sent an OTP to your phone/email.", id="login-err")
            yield Input(placeholder="Enter 6-digit OTP", id="inp-otp")
            with Horizontal(id="login-btns"):
                yield Button("Verify", variant="success", id="btn-verify")
                yield Button("Cancel", variant="error",   id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        otp = self.query_one("#inp-otp", Input).value.strip()
        if not otp:
            return
        self.dismiss(otp)


# ---------------------------------------------------------------------------
# Main TUI
# ---------------------------------------------------------------------------

class NaukriTUI(App):

    CSS = """
    /* Login modal */
    #login-box {
        width: 64;
        height: auto;
        margin: 4 8;
        padding: 2 3;
        border: heavy $accent;
        background: $surface;
    }
    #login-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #login-err {
        color: $error;
        height: 1;
        margin-bottom: 1;
    }
    #login-btns {
        margin-top: 1;
        align: center middle;
    }
    #login-btns Button { margin: 0 1; }

    /* Sidebar */
    #sidebar {
        width: 26;
        padding: 1;
        border-right: solid $accent;
    }
    #sidebar Button {
        width: 100%;
        margin-bottom: 1;
    }
    #auth-status {
        text-style: bold;
        margin-bottom: 1;
        text-align: center;
    }

    /* Main area */
    #main-area { padding: 0 1; }

    /* Search bar */
    #search-bar {
        height: 3;
        margin-bottom: 1;
    }
    #search-bar Input   { width: 1fr; margin-right: 1; }
    #inp-exp, #inp-age  { width: 10; }
    #btn-search         { width: 12; }

    /* Table */
    #job-table { height: 1fr; }

    /* Apply bar */
    #apply-bar {
        height: 3;
        margin-top: 1;
        align: left middle;
    }
    #apply-bar Button { margin-right: 1; }
    #apply-bar Label  { color: $text-muted; }

    /* Log */
    #log-panel {
        height: 10;
        border-top: solid $accent;
    }

    /* Status */
    #status-line {
        dock: bottom;
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    """

    TITLE = "NopeRi — Naukri TUI"
    BINDINGS = [
        Binding("q", "quit",         "Quit"),
        Binding("l", "do_login",     "Login"),
        Binding("s", "focus_search", "Search"),
        Binding("a", "apply_row",    "Apply"),
    ]

    def __init__(self):
        super().__init__()
        self._client   = None   # NaukriLoginClient (set after login)
        self._jc       = None   # NaukriJobClient
        self._jobs:   list = []
        self._daily_applied: int = 0
        self._last_search_ts: float = 0.0
        self._last_apply_ts:  float = 0.0

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("[ not logged in ]", id="auth-status")
                yield Button("Login",           id="nav-login",   variant="primary")
                yield Button("Logout",          id="nav-logout",  variant="error")
                yield Button("Recommended",     id="nav-recom",   variant="default")
                yield Button("Upload Resume",   id="nav-resume",  variant="default")
                yield Button("Update Profile",  id="nav-profile", variant="warning")
            with Vertical(id="main-area"):
                with Horizontal(id="search-bar"):
                    yield Input(placeholder="Keyword",      id="inp-kw")
                    yield Input(placeholder="Location",     id="inp-loc")
                    yield Input(placeholder="Exp (yrs)",    id="inp-exp",  value="1")
                    yield Input(placeholder="Age (days)",   id="inp-age",  value="7")
                    yield Button("Search",                  id="btn-search", variant="success")
                with VerticalScroll():
                    yield DataTable(id="job-table")
                with Horizontal(id="apply-bar"):
                    yield Button("Apply Selected  [A]", id="btn-apply", variant="success")
                    yield Button("Open URL",            id="btn-url",   variant="default")
                    yield Label("Select a row then press Apply", id="apply-hint")
                yield Log(id="log-panel", highlight=True)
        yield Static("Ready — search works without login", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#job-table", DataTable)
        t.add_columns("#", "Title", "Company", "Exp", "Location", "Salary", "Skills", "Posted")
        t.cursor_type = "row"
        self._log("NopeRi ready. Search is unauthenticated — no login needed.")
        self._log("Login only required for Apply / Recommended / Resume upload.")
        self._log(f"Rate limit: >{_MIN_SEARCH_GAP}s between searches, >{_MIN_APPLY_GAP}s between applies.")

    # ---------------------------------------------------------------- helpers

    def _status(self, msg: str) -> None:
        self.query_one("#status-line", Static).update(msg)

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.query_one("#log-panel", Log).write_line(f"[{ts}] {msg}")

    def _set_auth_label(self, text: str) -> None:
        self.query_one("#auth-status", Label).update(text)

    def _selected_job(self):
        t   = self.query_one("#job-table", DataTable)
        idx = t.cursor_row
        if 0 <= idx < len(self._jobs):
            return self._jobs[idx], idx
        return None, -1

    # ------------------------------------------------------------------ login

    def _do_logout(self) -> None:
        self._client = None
        self._jc     = None
        self._daily_applied = 0
        self._set_auth_label("[ not logged in ]")
        self._status("Logged out")
        self._log("Session cleared — logged out.")

    def action_do_login(self) -> None:
        self.push_screen(LoginScreen(), callback=self._on_login_creds)

    def _on_login_creds(self, creds) -> None:
        if not creds:
            return
        username, password = creds
        self._status("Logging in…")
        self._log(f"Logging in as {username}…")

        from src.client.naukri_client import NaukriLoginClient
        from src.client.job_client import NaukriJobClient

        client = NaukriLoginClient(username, password)

        def _do():
            client.login()
            return client

        def _done(c):
            self._client = c
            self._jc     = NaukriJobClient(c)
            self._set_auth_label(f"[{username[:16]}]")
            self._status("Logged in")
            self._log("Login OK — apply, recommended, and resume upload now available.")

        def _err(e, tb=""):
            err = str(e)
            self._status(f"Login failed: {e}")
            self._log(f"Login error: {err}")
            # OTP flow
            if "otp" in err.lower() or "mfa" in err.lower() or "challenge" in err.lower():
                self._log("OTP challenge detected — opening OTP dialog.")
                self.push_screen(OTPScreen(), callback=lambda otp: self._on_otp(otp, client))

        run_bg(self, _do, on_done=_done, on_err=_err)

    def _on_otp(self, otp, client) -> None:
        if not otp:
            return
        from src.client.job_client import NaukriJobClient

        def _do():
            client.verify_otp(otp)
            return client

        def _done(c):
            self._client = c
            self._jc     = NaukriJobClient(c)
            self._set_auth_label("[OTP verified]")
            self._status("Logged in via OTP")
            self._log("OTP verified — session ready.")

        def _err(e, tb=""):
            self._status(f"OTP failed: {e}")
            self._log(f"OTP error: {e}")

        run_bg(self, _do, on_done=_done, on_err=_err)

    # ----------------------------------------------------------------- search

    def action_focus_search(self) -> None:
        self.query_one("#inp-kw", Input).focus()

    def _do_search(self) -> None:
        kw  = self.query_one("#inp-kw",  Input).value.strip()
        loc = self.query_one("#inp-loc", Input).value.strip()
        try:
            exp = int(self.query_one("#inp-exp", Input).value.strip() or "0")
        except ValueError:
            exp = 0
        try:
            age = int(self.query_one("#inp-age", Input).value.strip() or "7")
        except ValueError:
            age = 7

        if not kw:
            self._log("Enter a keyword first.")
            return

        # Rate-limit guard
        elapsed = time.monotonic() - self._last_search_ts
        if elapsed < _MIN_SEARCH_GAP:
            wait = _MIN_SEARCH_GAP - elapsed
            self._log(f"Rate limit: wait {wait:.1f}s before next search.")
            self._status(f"Please wait {wait:.1f}s…")
            return

        self._last_search_ts = time.monotonic()
        self._status(f"Searching '{kw}' in '{loc or 'All India'}'…")
        self._log(f"Search: keyword={kw}  location={loc}  exp={exp}yr  age={age}d")

        def _do():
            # small jitter before request
            time.sleep(random.uniform(0.5, 1.5))
            return _raw_search(kw, loc, exp, age, results_per_page=20)

        def _done(jobs):
            self._jobs = jobs or []
            self._populate_table(self._jobs)
            self._status(f"Found {len(self._jobs)} jobs for '{kw}'")
            self._log(f"Search returned {len(self._jobs)} jobs.")

        def _err(e, tb=""):
            self._status(f"Search error: {e}")
            self._log(f"Search error: {e}")

        run_bg(self, _do, on_done=_done, on_err=_err)

    def _populate_table(self, jobs: list) -> None:
        t = self.query_one("#job-table", DataTable)
        t.clear()
        for i, j in enumerate(jobs, 1):
            skills = j.get("skills") or []
            if not isinstance(skills, list):
                skills = []
            skills_str = ", ".join(str(s) for s in skills[:4]) if skills else "—"
            t.add_row(
                str(i),
                str(j.get("title")    or "")[:42],
                str(j.get("company")  or "")[:22],
                str(j.get("experience") or "")[:12],
                str(j.get("location") or "")[:18],
                str(j.get("salary")   or "")[:18],
                skills_str[:35],
                str(j.get("posted")   or "")[:14],
            )

    # ----------------------------------------------------------- recommended

    def _do_recommended(self) -> None:
        if not self._jc:
            self._log("Login required for recommended jobs.")
            self._status("Not logged in — press L")
            return
        self._status("Fetching recommended jobs…")
        self._log("Fetching recommended jobs…")

        def _do():
            time.sleep(random.uniform(1.0, 2.5))
            from src.config.constants import RECOMMENDED_JOBS_URL
            raw_resp = self._jc._session.post(
                RECOMMENDED_JOBS_URL,
                headers=self._jc._client._build_headers(auth=True),
                json={"clusterId": None, "src": "recommClusterApi",
                      "clusterSplitDate": self._jc._cluster_dates()},
            )
            if not raw_resp.ok:
                raise RuntimeError(f"Recommended API {raw_resp.status_code}")
            raw_data = raw_resp.json()
            raw_list = raw_data.get("jobDetails") or []
            if isinstance(raw_list, dict):
                raw_list = list(raw_list.values())

            result = []
            for r in raw_list:
                if not isinstance(r, dict):
                    continue
                exp = sal = loc = ""
                for item in r.get("placeholders") or []:
                    if not isinstance(item, dict):
                        continue
                    t = item.get("type", "")
                    if t == "experience": exp = str(item.get("label") or "")
                    elif t == "salary":   sal = str(item.get("label") or "")
                    elif t == "location": loc = str(item.get("label") or "")
                tags_raw = r.get("tagsAndSkills") or ""
                skills = [s.strip() for s in str(tags_raw).split(",") if s.strip()] if tags_raw else []
                jd_url = str(r.get("jdURL") or "")
                result.append({
                    "job_id":      str(r.get("jobId") or r.get("id") or ""),
                    "title":       str(r.get("title") or r.get("jobTitle") or "N/A"),
                    "company":     str(r.get("companyName") or "N/A"),
                    "experience":  exp or str(r.get("experienceText") or r.get("experience") or "N/A"),
                    "location":    loc,
                    "salary":      sal or str(r.get("salaryDetail") or r.get("salary") or "Not disclosed"),
                    "skills":      skills,
                    "posted":      str(r.get("footerPlaceholderLabel") or r.get("postedDate") or "N/A"),
                    "url":         f"https://www.naukri.com{jd_url}" if jd_url else "",
                    "description": str(r.get("jobDescription") or ""),
                })
            return result

        def _done(jobs):
            self._jobs = jobs
            self._populate_table(self._jobs)
            self._status(f"Recommended: {len(self._jobs)} jobs")
            self._log(f"Recommended jobs loaded: {len(self._jobs)}")

        def _err(e, tb=""):
            self._status(f"Recommended error: {e}")
            self._log(f"Recommended error: {e}")
            if tb:
                for line in tb.splitlines():
                    self._log(f"  {line}")

        run_bg(self, _do, on_done=_done, on_err=_err)

    # -------------------------------------------------------------- apply

    def action_apply_row(self) -> None:
        self._apply_selected()

    def _apply_selected(self) -> None:
        if not self._jc:
            self._log("Login required to apply.")
            self._status("Not logged in — press L")
            return

        job, idx = self._selected_job()
        if job is None:
            self._log("No job selected.")
            return

        # Rate-limit guard
        elapsed = time.monotonic() - self._last_apply_ts
        if elapsed < _MIN_APPLY_GAP:
            wait = _MIN_APPLY_GAP - elapsed
            self._log(f"Rate limit: wait {wait:.1f}s before next apply.")
            self._status(f"Please wait {wait:.1f}s…")
            return

        self._last_apply_ts = time.monotonic()
        self._status(f"Applying to {job['title']}…")
        self._log(f"Applying: {job['title']} @ {job['company']}  (id={job['job_id']})")

        from src.models.models import Job

        job_obj = Job(
            job_id      = job["job_id"],
            title       = job["title"],
            company     = job["company"],
            location    = job["location"],
            experience  = job["experience"],
            salary      = job["salary"],
            posted_date = job["posted"],
            apply_link  = job["url"],
            description = job.get("description", ""),
            tags        = job["skills"],
        )

        def _do():
            time.sleep(random.uniform(1.0, 2.0))   # extra jitter before apply
            return self._jc.apply_job(job_obj, source="search")

        def _done(resp):
            self._daily_applied += 1
            quota = resp.get("quotaDetails", {})
            daily = quota.get("dailyApplied", self._daily_applied)
            limit = quota.get("dailyQuota", 50)
            job_resp = (resp.get("jobs") or [{}])[0]

            if job_resp.get("questionnaire"):
                self._log(f"Applied (questionnaire pending): {job['title']} @ {job['company']}")
            else:
                self._log(f"Applied OK: {job['title']} @ {job['company']}")

            self._status(f"Applied OK — daily: {daily}/{limit}")

        def _err(e, tb=""):
            err = str(e)
            self._log(f"Apply failed: {err}")
            self._status(f"Apply failed: {err[:60]}")

        run_bg(self, _do, on_done=_done, on_err=_err)

    # ---------------------------------------------------------- resume upload

    def _do_resume_upload(self) -> None:
        if not self._client:
            self._log("Login required for resume upload.")
            self._status("Not logged in — press L")
            return
        path = self.query_one("#inp-kw", Input).value.strip()
        if not path or not path.lower().endswith(".pdf"):
            self._log("Put the PDF file path in the keyword box, then click Upload Resume.")
            return

        self._status(f"Uploading {path}…")
        self._log(f"Resume upload: {path}")

        def _do():
            return self._client.update_resume(path)

        def _done(r):
            self._log(f"Resume uploaded OK: {r}")
            self._status("Resume uploaded")

        def _err(e, tb=""):
            self._log(f"Resume upload failed: {e}")
            self._status(f"Upload failed: {e}")

        run_bg(self, _do, on_done=_done, on_err=_err)

    # -------------------------------------------------------- profile update

    def _do_profile_update(self) -> None:
        if not self._client:
            self._log("Login required for profile update.")
            self._status("Not logged in — press L")
            return

        # Ban-risk warning
        self._log("[WARNING] Profile update is a high-ban-risk action.")
        self._log("Naukri flags accounts that update headline/resume repeatedly.")
        self._log("Use sparingly — max 1-2 times per day.")

        headline = self.query_one("#inp-kw", Input).value.strip()
        if not headline:
            self._log("Put the new headline in the keyword box, then click Update Profile.")
            return

        self._status("Updating profile…")

        def _do():
            time.sleep(random.uniform(2.0, 4.0))
            return self._client.update_profile(headline=headline)

        def _done(r):
            self._log("Profile updated OK.")
            self._status("Profile updated")

        def _err(e, tb=""):
            self._log(f"Profile update failed: {e}")
            self._status(f"Update failed: {e}")

        run_bg(self, _do, on_done=_done, on_err=_err)

    # ---------------------------------------------------------- open URL

    def _open_url(self) -> None:
        job, _ = self._selected_job()
        if not job:
            self._log("No job selected.")
            return
        url = job.get("url", "")
        if url:
            import webbrowser
            webbrowser.open(url)
            self._log(f"Opened: {url}")

    # -------------------------------------------------------- button router

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if   bid == "nav-login":   self.action_do_login()
        elif bid == "nav-logout":  self._do_logout()
        elif bid == "btn-search":  self._do_search()
        elif bid == "nav-recom":   self._do_recommended()
        elif bid == "nav-resume":  self._do_resume_upload()
        elif bid == "nav-profile": self._do_profile_update()
        elif bid == "btn-apply":   self._apply_selected()
        elif bid == "btn-url":     self._open_url()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        job, idx = self._selected_job()
        if job:
            skills = ", ".join(job["skills"][:6]) if job["skills"] else "none"
            self._log(f"Selected [{idx+1}] {job['title']} @ {job['company']} | skills: {skills}")
            self.query_one("#apply-hint", Label).update(
                f"{job['title'][:40]} @ {job['company'][:20]}"
            )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    NaukriTUI().run()
