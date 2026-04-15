
from src.client.naukri_client import NaukriLoginClient
from src.client.job_client import NaukriJobClient
from dotenv import load_dotenv
from colorama import Fore, Style, init
import os
import random
load_dotenv()
import time 

init(autoreset=True)

if __name__ == "__main__":
    # ---------------------------------------------------------------
    # Load credentials from .env file
    # (NAUKRI_USERNAME and NAUKRI_PASSWORD must be set)
    # ---------------------------------------------------------------
    username = os.getenv("NAUKRI_USERNAME")
    password = os.getenv("NAUKRI_PASSWORD")

    # ---------------------------------------------------------------
    # 1. Login — authenticates and stores session + bearer token
    # ---------------------------------------------------------------
    client = NaukriLoginClient(username, password)
    client.login()
    # # ---------------------------------------------------------------
    # # 2. Resume upload — uploads a new PDF resume to your profile,provide the file path 
    # # ---------------------------------------------------------------
    # print(client.update_resume(r"C:/Users/HP/Downloads/my_resume2.pdf"))

    # # ---------------------------------------------------------------
    # # 3. Profile update — update headline and summary independently
    # #    Both fields are optional, pass only what you want to change
    # # ---------------------------------------------------------------
    # print(client.update_profile(headline="Software Engineer with 2.3 years of experience in backend development using Node.js, Python, AWS, SQL, and NoSQL."
    # ))

    # print(client.update_profile(summary="this is my summary"))

    # # ---------------------------------------------------------------
    # # 4. Misc — fetch profile ID and form key (mostly for debugging)
    # # ---------------------------------------------------------------
    # # print(client.fetch_profile_id())
    # # print(client.get_form_key2())

    # # ---------------------------------------------------------------
    # # 5. Recommended jobs — fetches personalised job listings
    # #    based on your Naukri profile
    # # ---------------------------------------------------------------
    jc = NaukriJobClient(client)

    # Load your skills from .env
    my_skills = [s.strip().lower() for s in os.getenv("MY_SKILLS", "").split(",") if s.strip()]

    # Load already-applied job IDs
    APPLIED_FILE = "applied_jobs.txt"
    if os.path.exists(APPLIED_FILE):
        with open(APPLIED_FILE, "r") as f:
            applied_ids = set(line.strip() for line in f if line.strip())
    else:
        applied_ids = set()

    print("Searching jobs...")    
    jobs = jc.search_jobs(keyword="Node.js developer", location="Hyderabad", experience=2)

    if not jobs:
        print(f"{Fore.YELLOW}  No jobs found.{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}Found {len(jobs)} jobs{Style.RESET_ALL}")

        for job in jobs:
            print(f"\n{Fore.CYAN}{'─'*50}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}  Title   : {Fore.YELLOW}{job.title}")
            print(f"{Fore.WHITE}  Company : {Fore.YELLOW}{job.company}")
            print(f"{Fore.WHITE}  Job ID  : {Fore.YELLOW}{job.job_id}")
            print(f"{Fore.WHITE}  Tags    : {Fore.YELLOW}{job.tags}")

            # Skip already-applied jobs
            if job.job_id in applied_ids:
                print(f"{Fore.YELLOW}  ⏭ Skipped — already applied{Style.RESET_ALL}")
                continue

            # Filter: only apply if at least 1 job tag matches your skills
            job_tags_lower = [t.lower() for t in job.tags]
            matching = [t for t in job_tags_lower if t in my_skills]

            if not matching:
                print(f"{Fore.YELLOW}  ⏭ Skipped — no skill match{Style.RESET_ALL}")
                continue

            print(f"{Fore.GREEN}  ✓ Matched skills: {matching}{Style.RESET_ALL}")

            # Only claim skills you actually have
            mandatory = [s for s in job.tags[:2] if s.lower() in my_skills]
            optional  = [s for s in job.tags[2:] if s.lower() in my_skills]

            try:
                result = jc.apply_job(job, mandatory_skills=mandatory, optional_skills=optional, source="recommended")

                # Check questionnaire
                job_result = (result.get("jobs") or [{}])[0]
                if job_result.get("questionnaire"):
                    print(f"{Fore.YELLOW}   Skipped — questionnaire required{Style.RESET_ALL}")
                    continue

                print(f"{Fore.GREEN}  ✅ Applied successfully!{Style.RESET_ALL}")

                # Track this job as applied
                applied_ids.add(job.job_id)
                with open(APPLIED_FILE, "a") as f:
                    f.write(job.job_id + "\n")

            except Exception as e:
                print(f"{Fore.RED}   Failed: {e}{Style.RESET_ALL}")
            
            time.sleep(random.uniform(8, 15))  # rate limit to avoid account flagging






    # --------------------------------------------------------------- 
    # 6. scrap the jobs,example
    #     
    # ---------------------------------------------------------------
    # i = 1
    # while True:
    #     job_list = jc.search_jobs("Node.js", location="Hyderabad", experience=1, page=i)
    #     for count, job in enumerate(job_list):
    #         print(count + 1, ":-", job.title, " :- ", job.company)
        
    #     breaker = input("enter anything for next page, q to quit: ")
    #     if breaker.strip().lower() == "q":
    #         break
    #     i += 1