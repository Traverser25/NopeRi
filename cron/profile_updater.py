"""
profile_updater.py — Standalone job: bump Naukri profile + optionally re-upload resume.

Why this matters:
  Naukri's recruiter search sorts by "last modified". Updating the headline
  every few hours keeps your profile near the top of search results even
  without a resume change. Combined with a fresh resume upload it's the
  single highest-impact passive signal you can send.

Run standalone:
  python cron/profile_updater.py

Or called automatically by cron/scheduler.py on the configured interval.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Allow imports from project root when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.client.naukri_client import NaukriLoginClient
from src.utils.config_manager import ConfigManager
from cron.telegram_alert import alert_profile_updated, alert_error

load_dotenv()
logger = logging.getLogger(__name__)


def _build_headline(profile: dict) -> str:
    """Generate a headline string from config profile values."""
    if custom := (profile.get("resume_headline") or profile.get("headline")):
        return custom.strip()
    role  = profile.get("role_focus", "backend").title()
    exp   = profile.get("experience_years", 2)
    stack = profile.get("tech_stack", [])

    # Take up to 3 primary stack items for the headline
    stack_short = " · ".join(stack[:3]) if stack else "Python · Node.js · AWS"
    return f"{role} Engineer | {exp}+ YOE | {stack_short}"


def run_profile_update(cfg: ConfigManager | None = None) -> bool:
    """
    Login, update the profile headline, and optionally upload a resume.
    Returns True on success, False on any error.
    """
    if cfg is None:
        cfg = ConfigManager()

    config  = cfg.config
    profile = config.get("profile", {})

    session = config.get("session", {})
    nauk_at = session.get("nauk_at", "")
    resume_path = profile.get("resume_path", "").strip()

    try:
        if nauk_at:
            client = NaukriLoginClient.from_browser_cookies(nauk_at, session.get("nauk_rt", ""))
            logger.info("Profile updater: resumed session from stored cookies")
        else:
            username = os.getenv("NAUKRI_USERNAME") or os.getenv("NUSERNAME", "")
            password = os.getenv("PASSWORD", "")

            if not username or not password:
                logger.error("NAUKRI_USERNAME (or NUSERNAME) or PASSWORD not set in environment")
                alert_error("Profile updater: credentials missing")
                return False

            client = NaukriLoginClient(username, password)
            client.login()
            logger.info("Profile updater: logged in as %s", username)

            # Persist fresh session cookies to avoid future login challenges
            if client.session and client.session.cookies:
                c_at = client.session.cookies.get("nauk_at")
                c_rt = client.session.cookies.get("nauk_rt")
                if c_at:
                    config.setdefault("session", {})["nauk_at"] = str(c_at)
                    if c_rt:
                        config["session"]["nauk_rt"] = str(c_rt)
                    try:
                        cfg.save(config)
                    except Exception:
                        pass

        # Always bump the headline — cheap and effective
        headline = _build_headline(profile)
        client.update_profile(headline=headline)
        logger.info("Headline updated: %s", headline)

        # Resume upload (only if path is configured and file exists)
        if resume_path:
            resolved_resume_path = (
                resume_path
                if os.path.isabs(resume_path)
                else str(Path(__file__).parent.parent / resume_path)
            )
            if os.path.exists(resolved_resume_path):
                import re, shutil
                from datetime import datetime

                base, ext = os.path.splitext(os.path.basename(resolved_resume_path))
                # Strip existing date pattern to avoid chaining dates on recurring runs
                base_clean = re.sub(r'_\d{1,2}_[A-Za-z]{3}_\d{4}$|_\d{4}[-_]\d{2}[-_]\d{2}$', '', base)
                date_str = datetime.now().strftime("%d_%b_%Y")
                dated_filename = f"{base_clean}_{date_str}{ext}"
                dated_path = os.path.join(os.path.dirname(resolved_resume_path), dated_filename)

                shutil.copy2(resolved_resume_path, dated_path)
                client.update_resume(dated_path)
                logger.info("Resume uploaded with fresh date: %s", dated_filename)
            else:
                logger.warning("Resume path not found: %s", resolved_resume_path)

        tg_cfg = config.get("telegram", {})
        if tg_cfg.get("enabled"):
            alert_profile_updated(headline)

        return True

    except Exception as exc:
        logger.error("Profile update failed: %s", exc)
        tg_cfg = config.get("telegram", {})
        if tg_cfg.get("enabled") and tg_cfg.get("alerts", {}).get("on_error", True):
            alert_error(f"Profile update failed: {exc}")
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    success = run_profile_update()
    sys.exit(0 if success else 1)
