"""
telegram_alert.py — Fire-and-forget Telegram notifications for NopeRi.

Uses the raw Bot API over requests (no extra library needed).
Activated only when both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env,
AND config.json has  telegram.enabled = true.

Silence individual alert types in config.json under telegram.alerts.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")

def _chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "")

def _is_ready() -> bool:
    return bool(_bot_token() and _chat_id())


def send(text: str) -> bool:
    """
    Send a Markdown message to the configured Telegram chat.
    Returns True on success, False on any failure (never raises).
    """
    if not _is_ready():
        return False
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{_bot_token()}/sendMessage",
            json={
                "chat_id":    _chat_id(),
                "text":       text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        if not res.ok:
            logger.debug("Telegram send failed: %s %s", res.status_code, res.text[:100])
        return res.ok
    except Exception as exc:
        logger.debug("Telegram send error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Typed alert helpers  — import and call these from your code
# ---------------------------------------------------------------------------

def alert_run_started(mode: str = "manual") -> bool:
    ts = datetime.now().strftime("%d %b %Y  %H:%M")
    return send(f"🚀 *NopeRi started* `[{mode}]`\n_{ts}_")


def alert_apply(job_title: str, company: str, score: int | None, job_id: str) -> bool:
    score_str = f"{score}/100" if score is not None else "?"
    return send(
        f"✅ *Applied*\n"
        f"*{job_title}*\n"
        f"_{company}_\n"
        f"Score: `{score_str}`  |  ID: `{job_id}`"
    )


def alert_failed(job_title: str, company: str, error: str) -> bool:
    return send(
        f"❌ *Apply failed*\n"
        f"*{job_title}*  _{company}_\n"
        f"`{str(error)[:200]}`"
    )


def alert_questionnaire(job_title: str, company: str) -> bool:
    return send(
        f"📝 *Questionnaire handled*\n"
        f"*{job_title}*  _{company}_"
    )


def alert_run_summary(
    total_found:  int,
    applied:      int,
    skipped_ext:  int,
    skipped_dup:  int,
    failed:       int,
) -> bool:
    ts = datetime.now().strftime("%d %b  %H:%M")
    return send(
        f"📊 *Run Summary*  _{ts}_\n"
        f"Found `{total_found}` jobs\n"
        f"✅ Applied: `{applied}`\n"
        f"⏭ Skipped ext: `{skipped_ext}`  |  dup: `{skipped_dup}`\n"
        f"❌ Failed: `{failed}`"
    )


def alert_profile_updated(headline: str = "") -> bool:
    ts   = datetime.now().strftime("%d %b  %H:%M")
    body = f"\n_{headline}_" if headline else ""
    return send(f"👤 *Profile updated*  _{ts}_{body}")


def alert_error(message: str) -> bool:
    return send(f"🚨 *NopeRi error*\n`{str(message)[:300]}`")


def alert_scheduler_started(job_names: list[str]) -> bool:
    jobs_str = "\n".join(f"  • {n}" for n in job_names)
    return send(f"🕐 *Scheduler running*\n{jobs_str}")


def alert_scheduler_stopped() -> bool:
    return send("⏹ *Scheduler stopped*")
