"""
scheduler.py — NopeRi cron daemon (APScheduler 3.x)

Runs two background jobs:
  1. Profile updater  — bumps headline + re-uploads resume on an interval
  2. Apply agent      — full search → score → apply on a daily cron schedule

Usage:
  python cron/scheduler.py

Config (edit config.json or run  python apply_agent.py --setup):

  cron.profile_update.enabled        true / false
  cron.profile_update.interval_hours 6
  cron.apply.enabled                 true / false
  cron.apply.schedule                "08:00"   (HH:MM)
  cron.apply.days                    "mon-fri"
  cron.apply.timezone                "Asia/Kolkata"

Environment (.env):
  USERNAME, PASSWORD
  OPEN_API_KEY  or  OPENROUTER_API_KEY
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (optional)
  RESUME_PATH                            (optional — also settable in config.json)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow project-root imports when run as  python cron/scheduler.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from colorama import Fore, Style, init
from dotenv import load_dotenv

load_dotenv()
init(autoreset=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
except ImportError:
    print(
        f"{Fore.RED}APScheduler not installed.{Style.RESET_ALL}\n"
        f"Run:  pip install \"apscheduler>=3.10,<4\""
    )
    sys.exit(1)

from src.utils.config_manager import ConfigManager
from src.utils.dbhandler import AppliedJobsDB
from cron.telegram_alert import (
    alert_scheduler_started,
    alert_scheduler_stopped,
    alert_error,
    send as tg_send,
)


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

def job_profile_update() -> None:
    logger.info("── Profile update starting ──")
    try:
        from cron.profile_updater import run_profile_update
        run_profile_update()
        logger.info("── Profile update done ──")
    except Exception as exc:
        logger.error("Profile update error: %s", exc)
        cfg = ConfigManager()
        if cfg.config.get("telegram", {}).get("enabled"):
            alert_error(f"Profile update error: {exc}")


def job_apply_agent() -> None:
    logger.info("── Apply run starting ──")
    try:
        from apply_agent import run_agent
        cfg = ConfigManager()
        db  = AppliedJobsDB()
        stats = run_agent(cfg, db)
        logger.info(
            "── Apply run done  applied=%d  failed=%d  skipped=%d ──",
            stats["applied"], stats["failed"],
            stats["skipped_ext"] + stats["skipped_dup"],
        )
    except Exception as exc:
        logger.error("Apply run error: %s", exc)
        cfg = ConfigManager()
        if cfg.config.get("telegram", {}).get("enabled"):
            alert_error(f"Apply run error: {exc}")


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def _parse_schedule(schedule_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute) ints."""
    try:
        h, m = schedule_str.strip().split(":")
        return int(h), int(m)
    except Exception:
        logger.warning("Invalid schedule '%s', defaulting to 08:00", schedule_str)
        return 8, 0


def build_scheduler(config: dict) -> tuple[BlockingScheduler, list[str]]:
    cron_cfg = config.get("cron", {})
    tz       = cron_cfg.get("apply", {}).get("timezone", "Asia/Kolkata")
    sched    = BlockingScheduler(timezone=tz)
    job_names: list[str] = []

    # ── Profile updater ───────────────────────────────────────────────────────
    pu_cfg = cron_cfg.get("profile_update", {})
    if pu_cfg.get("enabled", True):
        interval_h = pu_cfg.get("interval_hours", 6)
        sched.add_job(
            job_profile_update,
            trigger=IntervalTrigger(hours=interval_h, timezone=tz),
            id="profile_update",
            replace_existing=True,
            misfire_grace_time=300,
        )
        label = f"Profile update  every {interval_h}h"
        job_names.append(label)
        logger.info("Scheduled: %s", label)

    # ── Apply agent ───────────────────────────────────────────────────────────
    ap_cfg = cron_cfg.get("apply", {})
    if ap_cfg.get("enabled", True):
        schedule_str = ap_cfg.get("schedule", "08:00")
        days         = ap_cfg.get("days", "mon-fri")
        hour, minute = _parse_schedule(schedule_str)

        # days can be a list ["mon","wed"] or a string "mon-fri"
        day_of_week = ",".join(days) if isinstance(days, list) else days

        sched.add_job(
            job_apply_agent,
            trigger=CronTrigger(
                hour=hour, minute=minute,
                day_of_week=day_of_week,
                timezone=tz,
            ),
            id="apply_agent",
            replace_existing=True,
            misfire_grace_time=600,
        )
        label = f"Apply agent     {schedule_str} {tz} ({day_of_week})"
        job_names.append(label)
        logger.info("Scheduled: %s", label)

    return sched, job_names


# ---------------------------------------------------------------------------
# Status banner
# ---------------------------------------------------------------------------

def _print_banner(sched: BlockingScheduler, job_names: list[str]) -> None:
    print(f"\n{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{Style.BRIGHT}NopeRi Scheduler{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
    for job in sched.get_jobs():
        print(
            f"  {Fore.WHITE}●{Style.RESET_ALL}  {job.name or job.id}"
            f"  {Fore.CYAN}next: {job.next_run_time}{Style.RESET_ALL}"
        )
    print(f"\n  {Fore.WHITE}Ctrl+C to stop.{Style.RESET_ALL}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg    = ConfigManager()
    config = cfg.config

    sched, job_names = build_scheduler(config)

    if not sched.get_jobs():
        print(
            f"{Fore.YELLOW}  No jobs scheduled.{Style.RESET_ALL}\n"
            f"  Check the {Fore.CYAN}cron{Style.RESET_ALL} section in config.json\n"
            f"  or re-run  {Fore.CYAN}python apply_agent.py --setup{Style.RESET_ALL}"
        )
        return

    _print_banner(sched, job_names)

    tg_on = config.get("telegram", {}).get("enabled", False)
    if tg_on:
        alert_scheduler_started(job_names)

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user.")
        if tg_on:
            alert_scheduler_stopped()


if __name__ == "__main__":
    main()
