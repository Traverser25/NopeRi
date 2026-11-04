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

    username    = os.getenv("USERNAME", "")
    password    = os.getenv("PASSWORD", "")
    resume_path = profile.get("resume_path", "").strip()

    if not username or not password:
        logger.error("USERNAME or PASSWORD not set in environment")
        alert_error("Profile updater: credentials missing")
        return False

    try:
        client = NaukriLoginClient(username, password)
        client.login()
        logger.info("Profile updater: logged in as %s", username)

        # Always bump the headline — cheap and effective
        headline = _build_headline(profile)
        client.update_profile(headline=headline)
        logger.info("Headline updated: %s", headline)

        # Resume upload (only if path is configured and file exists)
        if resume_path:
            if os.path.exists(resume_path):
                client.update_resume(resume_path)
                logger.info("Resume uploaded: %s", resume_path)
            else:
                logger.warning("Resume path not found: %s", resume_path)

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
