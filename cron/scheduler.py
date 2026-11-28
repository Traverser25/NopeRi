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
  NAUKRI_USERNAME (or NUSERNAME), PASSWORD
  OPEN_API_KEY  or  OPENROUTER_API_KEY
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (optional)
  RESUME_PATH                            (optional — also settable in config.json)
"""
from __future__ import annotations

import json
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


def sync_scheduler_jobs(sched: BlockingScheduler, config: dict) -> list[str]:
    """Dynamically add, reschedule, or unschedule jobs on a running scheduler."""
    cron_cfg = config.get("cron", {})
    tz       = cron_cfg.get("apply", {}).get("timezone", "Asia/Kolkata")
    job_names: list[str] = []

    # ── Profile updater ───────────────────────────────────────────────────────
    pu_cfg = cron_cfg.get("profile_update", {})
    existing_pu = sched.get_job("profile_update")
    if pu_cfg.get("enabled", True):
        interval_h = pu_cfg.get("interval_hours", 6)
        trigger = IntervalTrigger(hours=interval_h, timezone=tz)
        if existing_pu:
            sched.reschedule_job("profile_update", trigger=trigger)
        else:
            sched.add_job(
                job_profile_update,
                trigger=trigger,
                id="profile_update",
                replace_existing=True,
                misfire_grace_time=300,
            )
        label = f"Profile update  every {interval_h}h"
        job_names.append(label)
        logger.info("Synced: %s", label)
    elif existing_pu:
        sched.remove_job("profile_update")
        logger.info("Unscheduled: Profile update (disabled in config)")

    # ── Apply agent ───────────────────────────────────────────────────────────
    ap_cfg = cron_cfg.get("apply", {})
    existing_ap = sched.get_job("apply_agent")
    if ap_cfg.get("enabled", True):
        schedule_str = ap_cfg.get("schedule", "08:00")
        days         = ap_cfg.get("days", "mon-fri")
        hour, minute = _parse_schedule(schedule_str)
        day_of_week = ",".join(days) if isinstance(days, list) else days
        trigger = CronTrigger(
            hour=hour, minute=minute,
            day_of_week=day_of_week,
            timezone=tz,
        )
        if existing_ap:
            sched.reschedule_job("apply_agent", trigger=trigger)
        else:
            sched.add_job(
                job_apply_agent,
                trigger=trigger,
                id="apply_agent",
                replace_existing=True,
                misfire_grace_time=600,
            )
        label = f"Apply agent     {schedule_str} {tz} ({day_of_week})"
        job_names.append(label)
        logger.info("Synced: %s", label)
    elif existing_ap:
        sched.remove_job("apply_agent")
        logger.info("Unscheduled: Apply agent (disabled in config)")

    return job_names


_LAST_CONFIG_MTIME: float = 0.0
_LAST_CRON_STATE: str = ""


def _check_config_change(sched: BlockingScheduler) -> None:
    """Lightweight disk-watcher that reloads schedules whenever config.json changes."""
    global _LAST_CONFIG_MTIME, _LAST_CRON_STATE
    from src.utils.config_manager import CONFIG_PATH
    if not CONFIG_PATH.exists():
        return
    try:
        mtime = CONFIG_PATH.stat().st_mtime
        if mtime != _LAST_CONFIG_MTIME:
            _LAST_CONFIG_MTIME = mtime
            cfg = ConfigManager()
            cron_str = json.dumps(cfg.config.get("cron", {}), sort_keys=True)
            if cron_str != _LAST_CRON_STATE:
                _LAST_CRON_STATE = cron_str
                labels = sync_scheduler_jobs(sched, cfg.config)
                logger.info("Detected config.json change on disk. Schedules updated on the fly: %s", labels)
    except Exception as e:
        logger.debug("Config watch error: %s", e)


def build_scheduler(config: dict) -> tuple[BlockingScheduler, list[str]]:
    global _LAST_CONFIG_MTIME, _LAST_CRON_STATE
    from src.utils.config_manager import CONFIG_PATH
    if CONFIG_PATH.exists():
        try:
            _LAST_CONFIG_MTIME = CONFIG_PATH.stat().st_mtime
        except Exception:
            pass
    _LAST_CRON_STATE = json.dumps(config.get("cron", {}), sort_keys=True)

    cron_cfg = config.get("cron", {})
    tz       = cron_cfg.get("apply", {}).get("timezone", "Asia/Kolkata")
    sched    = BlockingScheduler(timezone=tz)
    job_names = sync_scheduler_jobs(sched, config)

    # Watch config.json every 15 seconds to update cron triggers on the fly
    sched.add_job(
        _check_config_change,
        args=[sched],
        trigger=IntervalTrigger(seconds=15, timezone=tz),
        id="config_watcher",
        replace_existing=True,
        misfire_grace_time=30,
    )

    return sched, job_names


# ---------------------------------------------------------------------------
# Status banner
# ---------------------------------------------------------------------------

def _print_banner(sched: BlockingScheduler, job_names: list[str]) -> None:
    print(f"\n{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{Style.BRIGHT}NopeRi Scheduler{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
    for job in sched.get_jobs():
        nxt = getattr(job, "next_run_time", None) or "on scheduler start"
        print(
            f"  {Fore.WHITE}●{Style.RESET_ALL}  {job.name or job.id}"
            f"  {Fore.CYAN}next: {nxt}{Style.RESET_ALL}"
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

    # Start web dashboard & setup wizard on 0.0.0.0:8765
    try:
        import threading
        from src.utils.dashboard_server import start_dashboard_server
        web_thread = threading.Thread(
            target=start_dashboard_server,
            kwargs={"host": "0.0.0.0", "port": 8765, "scheduler": sched},
            daemon=True
        )
        web_thread.start()
        logger.info("Dashboard & Setup web UI started on http://0.0.0.0:8765")
    except Exception as e:
        logger.warning("Could not start dashboard web server: %s", e)

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user.")
        if tg_on:
            alert_scheduler_stopped()


if __name__ == "__main__":
    main()
