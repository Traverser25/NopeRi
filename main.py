"""
main.py -- NopeRi API demo / sandbox

Uncomment whichever section you want to try.
Credentials are read from .env (NAUKRI_USERNAME, PASSWORD).

This file is NOT the production runner -- use apply_agent.py for that.
"""

import os
import time

from colorama import Fore, Style, init
from dotenv import load_dotenv

from src.client.naukri_client import NaukriLoginClient
from src.client.job_client import NaukriJobClient

load_dotenv()
init(autoreset=True)


if __name__ == "__main__":

    # -- 1. Login ----------------------------------------------------------
    # Authenticates and stores session + bearer token.
    username = os.getenv("NAUKRI_USERNAME", "")
    password = os.getenv("PASSWORD", "")

    client = NaukriLoginClient(username, password)
    client.login()
    print(f"{Fore.GREEN}Logged in as {Fore.YELLOW}{username}{Style.RESET_ALL}\n")

    jc = NaukriJobClient(client)

    # -- 2. Resume upload --------------------------------------------------
    # Uploads a PDF resume to your profile.
    #
    # print(client.update_resume(r"C:/Users/HP/Downloads/my_resume.pdf"))

    # -- 3. Profile update -------------------------------------------------
    # Both fields are optional; pass only what you want to change.
    #
    # print(client.update_profile(
    #     headline="Software Engineer with 2 years of backend experience in Node.js and Python."
    # ))
    # print(client.update_profile(summary="Your summary here."))

    # -- 4. Recommended jobs -----------------------------------------------
    # Fetches personalised listings based on your Naukri profile.
    #
    # jobs = jc.get_recommended_jobs()

    # -- 5. Job search + apply ---------------------------------------------
    print("Searching jobs...")
    jobs = jc.search_jobs(keyword="Node.js developer", location="Hyderabad", experience=2)

    if not jobs:
        print(f"{Fore.YELLOW}No jobs found.{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}Found {len(jobs)} jobs{Style.RESET_ALL}\n")

        for job in jobs:
            print(f"{Fore.CYAN}{'─' * 50}{Style.RESET_ALL}")
            print(f"  Title   : {Fore.YELLOW}{job.title}{Style.RESET_ALL}")
            print(f"  Company : {Fore.YELLOW}{job.company}{Style.RESET_ALL}")
            print(f"  Job ID  : {Fore.YELLOW}{job.job_id}{Style.RESET_ALL}")
            print(f"  Tags    : {Fore.YELLOW}{job.tags}{Style.RESET_ALL}")

            mandatory = job.tags[:2] if job.tags else []
            optional  = job.tags[2:] if len(job.tags) > 2 else []

            try:
                result     = jc.apply_job(job, mandatory_skills=mandatory,
                                          optional_skills=optional, source="search")
                job_result = (result.get("jobs") or [{}])[0]

                if job_result.get("questionnaire"):
                    print(f"{Fore.YELLOW}  Skipped -- questionnaire required{Style.RESET_ALL}")
                    continue

                print(f"{Fore.GREEN}  Applied successfully{Style.RESET_ALL}")

            except Exception as e:
                print(f"{Fore.RED}  Failed: {e}{Style.RESET_ALL}")

            time.sleep(3)

    # -- 6. Paginated job scrape -------------------------------------------
    # Loops through search pages until you quit.
    #
    # page = 1
    # while True:
    #     job_list = jc.search_jobs("Node.js", location="Hyderabad", experience=1, page=page)
    #     for i, job in enumerate(job_list, start=1):
    #         print(f"{i}. {job.title} -- {job.company}")
    #     if input("Press Enter for next page, q to quit: ").strip().lower() == "q":
    #         break
    #     page += 1
