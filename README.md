<p align="center">
  <img src="assests/logo2.svg" alt="naukri-api-client" width="680"/>
</p>

# Noperi

A lightweight and Selenium-free Python API client for Naukri.com, designed to help you update your profile, upload your resume, search jobs, and apply to jobs (easy apply) programmatically.

---

**Status:** 🟢 Working (Last tested: May 2026)

---

## ✨ Features

| Feature | Status |
|---|---|
| Login & session management (Bearer token) | ✅ Working |
| Resume upload (PDF) | ✅ Working |
| Profile update (headline, name, summary) | ✅ Working |
| Recommended jobs feed | ✅ Working |
| `nkparam` token harvester (Selenium utility) | ✅ Working |
| `nkparam` token generator (pure API, no Selenium) | ✅ Working |
| Job search (`/jobapi/v3/search`) | ✅ Working |
| Job details  (`jobapi/v1/job/`) | ✅ Working |
| One-click job apply | ✅ Working |
| Job questionnaire while applying| ✅ Working Partially (harcoded answer) |
| OTP login/MFA | 🚧 Under development |


> **Updated on April 13 2026**  
> **No Selenium required** for core features.  
> The `nkparam` token is generated via API.  
> Selenium-based harvester is kept only as a backup utility.

> **No Selenium required** for features 1–4. The Selenium script is only needed as a helper to harvest fresh `nkparam` tokens for the search endpoint.

---

## 🗂️ Project Structure

```
naukri-api-client/
├── main.py                     # Entry point — demo of all features
├── nkPool.txt                  # Pool of captured nkparam tokens
├── .env                        # Credentials 
├── src/
│   ├── client/
│   │   ├── naukri_client.py    # Core auth + profile + resume client
│   │   ├── job_client.py       # Recommended jobs + search + apply
│   │   └── session.py          # requests.Session factory
│   ├── config/
│   │   └── constants.py        # URLs, regex patterns, app IDs
│   ├── exceptions/
│   │   └── exceptions.py       # Custom exception classes
│   ├── models/
│   │   └── models.py           # Dataclasses: Job, NaukriSession, etc.
│   └── utils/
│       ├── extractors.py       # HTML / JS parsing helpers
│       └── request_helper.py   # Exponential-retry decorator
        ├── get_Nkparam.py      # Selenium helper to harvest nkparam tokens
        ├── nkparam_generator.py   #generate nkparam tokens 
```

---

## ⚠️ IP & Hosting Advice

Naukri fingerprints IPs for every request. Many cloud providers trigger MFA or get blocked.

**Avoid:**
- Azure (all regions)
- GitHub Actions / CI
- Some Google Cloud regions
- Datacenter IP ranges

**Works:**
- AWS (EC2 with Elastic IP)
- Home broadband / personal IP (best)
- Mobile hotspot (testing)
- Residential proxy

**Note:**
- Sessions are IP-bound — changing IP will invalidate login
- Avoid GitHub Actions completely (IP pool is flagged)




## ⚙️ Installation

**Requirements:** Python 3.10+

```bash
git clone https://github.com/Traverser25/NopeRi.git
cd Noperi
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
USERNAME=your_naukri_email@example.com
PASSWORD=your_naukri_password
```

---
## 🚀 Quick Start 
        you can simply run `main.py` also

        ```python
        from src.client.naukri_client import NaukriLoginClient
        from src.client.job_client import NaukriJobClient
        from dotenv import load_dotenv
        import os
        import time

        load_dotenv()

        # 1. Login
        client = NaukriLoginClient(os.getenv("USERNAME"), os.getenv("PASSWORD"))
        client.login()

        # 2. Upload resume
        client.update_resume("path/to/your_resume.pdf")

        # 3. Update profile headline
        client.update_profile(headline="Backend Engineer | Python · Node.js · AWS")

        # 4. Update profile summary
        client.update_profile(summary="Experienced engineer with 2+ years building scalable APIs.")

        # 5. Job client
        jc = NaukriJobClient(client)

        # 6. Fetch recommended jobs
        jobs = jc.get_recommended_jobs()
        for job in jobs:
            print(job.title, "—", job.company)

        # 7. Search jobs
        jobs = jc.search_jobs(keyword="Node.js developer", location="Hyderabad", experience=2)

        # 8. Apply to jobs (easy apply)
        for job in jobs:
            mandatory = job.tags[:2] if job.tags else []
            optional  = job.tags[2:] if len(job.tags) > 2 else []

            try:
                result = jc.apply_job(
                    job,
                    mandatory_skills=mandatory,
                    optional_skills=optional,
                    source="recommended"
                )

                job_result = (result.get("jobs") or [{}])[0]

                # Skip jobs with questionnaire
                if job_result.get("questionnaire"):
                    print("Skipped (questionnaire required):", job.title)
                    continue

                print("Applied:", job.title)

            except Exception as e:
                print("Failed:", job.title, "|", e)

            time.sleep(2)




---

## 📖 API Reference

### `NaukriLoginClient`

| Method | Description |
|---|---|
| `login()` | Authenticates and stores the Bearer token + session cookies |
| `update_resume(file)` | Uploads a PDF resume; accepts a file path (`str`) or a file-like object |
| `update_profile(headline, name, summary)` | Updates one or more profile fields (all arguments are optional) |
| `fetch_profile_id()` | Returns your Naukri profile ID (cached after first call) |
| `get_form_key2()` | Extracts the internal `formKey` from Naukri's JS bundle (cached) |

### `NaukriJobClient`

| Method | Description |
|---|---|
| `get_recommended_jobs()` | Returns a list of `Job` objects personalised to your profile |
| `search_jobs(keyword, location, page, experience, ...)` | Returns job results using the search endpoint |
| `apply_job(job)` | Applies to a job programmatically |

### `Job` model

```python
@dataclass
class Job:
    job_id:      str
    title:       str
    company:     str
    location:    str
    experience:  str
    salary:      str
    posted_date: str
    apply_link:  str
    description: str
    tags:        list[str]
```

---

## 🔑 The `nkparam` Problem (and Current Solution)

Naukri's job-search endpoint (`/jobapi/v3/search`) requires a request header called `nkparam`.  
This is not just a random token — it is essentially an **encrypted/signature key** generated using:
- current timestamp (time-based salt)
- session-related data
- page/context-specific parameters

The logic exists inside Naukri’s obfuscated JavaScript bundle, which makes it hard to reverse directly.

If `nkparam` is missing or invalid, the API returns `403 Forbidden`.

---

### ✅ Current Solution

We now generate `nkparam` directly via API logic (no browser required).


---

### 🧰 Fallback (Optional)

A Selenium-based harvester is still available as a backup:

**`nk_param_getter.py`**
- Opens Chrome
- Captures network requests
- Extracts valid `nkparam`
- Stores in `nkPool.txt`




---

## 🤖 Automated Job Application Agent

For a fully automated, AI-powered job application workflow, use:

```bash
python apply_agent.py
```

The agent is built on top of `NaukriLoginClient` and `NaukriJobClient`, so all authentication, session management, cookies, and token handling are already taken care of automatically.

---

### ✨ What the Agent Does

The workflow runs end-to-end automatically:

1. Logs into Naukri using your `.env` credentials
2. Searches jobs using curated backend-focused keywords
3. Scores each job using an AI model (`OpenAI`)
4. Automatically applies to jobs that pass the score threshold
5. Handles basic job questionnaires using predefined answers
6. Skips external company-site applications
7. Prevents duplicate applications using a local CSV log
8. Displays a colored terminal dashboard with live progress

---

### ⚙️ Prerequisites

Add your OpenAI API key to the `.env` file:

```env
OPEN_API_KEY=your-openai-api-key
```

Your `.env` should now look like:

```env
USERNAME=your_naukri_email@example.com
PASSWORD=your_naukri_password
OPEN_API_KEY=your-openai-api-key
```

---

### 🧠 Default Search Strategy

The agent fetches jobs using curated backend-development queries such as:

- Node.js Developer
- Python Backend Developer
- Backend Engineer
- API Developer
- Full Stack Developer

It also filters using:
- Experience level
- Job freshness
- Multiple result pages

---

### 🔧 Configuration

You can customize the behaviour directly inside `apply_agent.py`:

| Variable | Purpose |
|---|---|
| `BQUERIES` | List of job search keywords |
| `EXPERIENCE_LEVELS` | Experience filters |
| `PAGES` | Number of search-result pages |
| `JOB_AGE` | Max age of jobs to consider |
| `SCORE_THRESHOLD` | Minimum AI score required before applying |

---

### 📂 Application Tracking

The agent keeps track of already-applied jobs using:

```bash
applied_jobs.csv
```

This ensures:
- No duplicate applications
- Safe repeated runs
- Persistent local history

---

### 🖥️ Terminal Dashboard

The agent displays a live terminal dashboard showing:

- Login status
- Jobs fetched
- AI evaluation score
- Apply success/failure
- Questionnaire detection
- Final application summary

Example:

```text
[FETCH] Backend Engineer — Hyderabad
[AI SCORE] 8.7/10
[APPLY] Success
```

---

 External company-site applications | ❌ Skipped intentionally |

---

### 💡 Example Workflow

```bash
python apply_agent.py
```

Typical flow:

```text
Login Successful
Fetching Jobs...
Scoring with AI...
Applying...
Saved to applied_jobs.csv
Run Complete
```

---

## ⚠️ Disclaimer

This project is intended for personal automation of your **own** Naukri account. Use responsibly and in accordance with [Naukri's Terms of Service](https://www.naukri.com/termsAndConditions). The authors are not affiliated with Naukri / InfoEdge India Ltd.

---

## 🛣️ Roadmap

- [x] Complete job-search endpoint integration
- [x] Complete one-click job-apply flow

- [ ] Add async support (`httpx` / `aiohttp`)
- [ ] CLI interface

---

## 🤝 Contributing

    Pull requests are welcome!
    If you can help implement or improve OTP/MFA login automation, feel free to open an issue or PR  this is the main remaining piece for a fully seamless client.
---
