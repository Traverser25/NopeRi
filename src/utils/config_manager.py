"""
config_manager.py — Single source of truth for all NopeRi configuration.

Reads / writes:
  config.json      — user profile, AI settings, search queries
  veto.json        — veto title + company lists
  user_prompt.md   — global AI profile description injected into the scoring prompt
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path("config.json")
VETO_PATH   = Path("veto.json")
PROMPT_PATH = Path("user_prompt.md")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "profile": {
        "role_focus":        "backend",
        "experience_years":  2,
        "tech_stack":        ["Node.js", "Python", "MongoDB", "REST APIs", "AWS", "Docker"],
        "locations":         ["Bangalore", "Hyderabad"],
        "apply_remote":      True,
        "current_ctc":       "5",
        "expected_ctc":      "7",
        "notice_days":       30,
        "resume_path":       "",   # absolute path to PDF; used by cron profile updater
    },
    "ai": {
        "provider":          "openai",   # "openai" | "openrouter"
        "model":             "gpt-4o-mini",
        "score_threshold":   50,
        "daily_apply_limit": 50,
        "ai_score_limit":    300,
        "batch_size":        50,
    },
    "search": {
        "job_age":           2,
        "pages_per_query":   1,
    },
    "queries": [
        {"keyword": "Node.js backend developer", "location": "Bangalore"},
        {"keyword": "Python Developer",          "location": ""},
        {"keyword": "Node.js Developer",         "location": ""},
        {"keyword": "python backend developer",  "location": "Pune"},
    ],
    "cron": {
        "profile_update": {
            "enabled":        True,
            "interval_hours": 6,      # bump profile every N hours
        },
        "apply": {
            "enabled":   True,
            "schedule":  "08:00",     # HH:MM in timezone below
            "days":      "mon-fri",   # APScheduler day_of_week string
            "timezone":  "Asia/Kolkata",
        },
    },
    "questionnaire": {
        "skip_ai": False,             # set True to disable AI calls (uses cache + common_qa only)
        "common_qa": [],              # user-defined patterns: [{"question": "...", "answer": "..."}]
    },
    "telegram": {
        "enabled": False,             # set True + add TELEGRAM_BOT_TOKEN/CHAT_ID to .env
        "alerts": {
            "on_apply":           True,
            "on_failure":         True,
            "on_run_summary":     True,
            "on_questionnaire":   False,
            "on_error":           True,
            "on_scheduler_start": True,
        },
    },
}

DEFAULT_VETO: dict = {
    "titles": [
        "walk-in", "walkin", "walk in",
        "android developer", "ios developer", "flutter developer",
        "frontend developer", "front-end developer",
        "principal engineer", "staff engineer", "architect",
        "vp of", "head of engineering", "head of technology",
        "founder", "tutor", "trainer",
        "data scientist", "ml engineer", "data engineer", "intern", "internship",
        "engineering manager", "etl engineer", "prompt engineer",
        "analyst", "associate is engineer", "infra engineer",
        "observability engineer", "manager",
    ],
    "companies": [
        "accenture", "wipro", "infosys", "tcs", "cognizant",
        "capgemini", "hcl", "tech mahindra", "mphasis", "hexaware",
        "ltimindtree", "persistent", "birlasoft",
    ],
}

DEFAULT_PROMPT = """\
## My Profile

- **Role focus:** Backend developer
- **Experience:** 2 years, backend-focused
- **Core stack:** Node.js, Python, MongoDB, REST APIs, AWS
- **Also know:** Docker, CI/CD, automation, Selenium, Playwright, web scraping,
  n8n, LangChain, RAG, vector DBs, FastAPI, Flask, Express
- **Looking for:** SDE1 / junior-mid backend or fullstack-backend roles
- **Prefers:** startups, product companies, AI/automation work, remote/hybrid
- **Will NOT do:** pure frontend, mobile, ML research, data science, DevOps-only

## Scoring Preference

- Prioritize roles where Node.js or Python is a mandatory/primary tag
- Backend + startup + 0-3 yrs experience → score 80+
- Fullstack with Node.js or Python backend is fine
- Pure frontend, mobile, ML → score 0-15
"""


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Loads, caches, and saves all NopeRi configuration files."""

    def __init__(self) -> None:
        self._config: dict | None = None
        self._veto:   dict | None = None

    # ── config.json ──────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Load config.json, deep-merging with defaults so new keys always exist."""
        if not CONFIG_PATH.exists():
            return DEFAULT_CONFIG.copy()
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, data)

    def save(self, config: dict) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    @property
    def config(self) -> dict:
        if self._config is None:
            self._config = self.load()
        return self._config

    # ── veto.json ─────────────────────────────────────────────────────────────

    def load_veto(self) -> dict:
        if not VETO_PATH.exists():
            self.save_veto(DEFAULT_VETO)
            return DEFAULT_VETO.copy()
        with open(VETO_PATH, encoding="utf-8") as f:
            return json.load(f)

    def save_veto(self, veto: dict) -> None:
        with open(VETO_PATH, "w", encoding="utf-8") as f:
            json.dump(veto, f, indent=2)

    @property
    def veto(self) -> dict:
        if self._veto is None:
            self._veto = self.load_veto()
        return self._veto

    # ── user_prompt.md ────────────────────────────────────────────────────────

    def load_prompt(self) -> str:
        """Read user_prompt.md, creating a default if it doesn't exist."""
        if not PROMPT_PATH.exists():
            with open(PROMPT_PATH, "w", encoding="utf-8") as f:
                f.write(DEFAULT_PROMPT)
        with open(PROMPT_PATH, encoding="utf-8") as f:
            return f.read().strip()

    def generate_prompt_from_config(self, config: dict) -> str:
        """Generate user_prompt.md body from wizard config values."""
        p     = config.get("profile", {})
        role  = p.get("role_focus", "backend").title()
        exp   = p.get("experience_years", 2)
        stack = p.get("tech_stack", [])
        locs  = p.get("locations", [])

        stack_str = ", ".join(stack) if stack else "Node.js, Python"
        loc_str   = (
            ", ".join(locs) + (" and remote" if p.get("apply_remote") else "")
            if locs else "open to all"
        )
        primary = stack[0] if stack else "Node.js"

        return (
            f"## My Profile\n\n"
            f"- **Role focus:** {role} developer\n"
            f"- **Experience:** {exp} year{'s' if exp != 1 else ''}, {role.lower()}-focused\n"
            f"- **Core stack:** {stack_str}\n"
            f"- **Preferred locations:** {loc_str}\n"
            f"- **Looking for:** SDE1 / junior-mid {role.lower()} or fullstack-backend roles\n"
            f"- **Prefers:** startups, product companies, AI/automation work, remote/hybrid\n"
            f"- **Will NOT do:** pure frontend, mobile, ML research, data science\n\n"
            f"## Scoring Preference\n\n"
            f"- Prioritize roles where {primary} is a mandatory/primary tag\n"
            f"- {role} + startup + 0-{exp + 1} yrs experience → score 80+\n"
            f"- Fullstack with {role.lower()} focus is fine\n"
            f"- Pure frontend, mobile, ML → score 0-15\n"
        )

    # ── Device fingerprint ───────────────────────────────────────────────────

    def get_vid(self) -> str:
        """Return the visitor-ID sent as the `vid` header on Naukri login."""
        env_vid = os.getenv("NAUKRI_VID", "")
        if env_vid:
            return env_vid
        import secrets, base64
        return base64.b64encode(secrets.token_bytes(48)).decode()

    # ── AI provider helpers ───────────────────────────────────────────────────

    def get_ai_url(self) -> str:
        if self.config["ai"].get("provider") == "openrouter":
            return "https://openrouter.ai/api/v1/chat/completions"
        return "https://api.openai.com/v1/chat/completions"

    def get_ai_key(self) -> str:
        if self.config["ai"].get("provider") == "openrouter":
            return os.getenv("OPENROUTER_API_KEY", "")
        return os.getenv("OPEN_API_KEY", "")

    def get_ai_headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.get_ai_key()}",
            "Content-Type":  "application/json",
        }
        if self.config["ai"].get("provider") == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/Traverser25/NopeRi"
            headers["X-Title"]      = "NopeRi"
        return headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
