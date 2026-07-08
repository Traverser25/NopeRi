import logging
from datetime import datetime

from src.models.models import Job
from src.client.naukri_client import NaukriLoginClient
from src.exceptions.exceptions import NaukriAuthError, NaukriParseError
from src.utils.request_helper import with_exponential_retry
from src.utils.nkparam_generator import generate_nkparam
from src.config.constants import RECOMMENDED_JOBS_URL, JOB_SEARCH_URL, APPLY_JOB_URL
import json
from typing import Optional


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
)
logger.addHandler(_handler)


APPLY_SRC_MAP = {
    "recommended": ("drecomm_apply", "--drecomm_apply-1-F-0-1--{sid}-"),
    "search":      ("srp",           "--srp-1-F-0-1--{sid}-"),
}


# ----------------------------------------------------------------------------------
# NaukriJobClient
#
# A thin client over Naukri's internal APIs using an authenticated session from
# NaukriLoginClient. Handles job search, recommendations, and apply workflows.
#
# Responsibilities:
#   - Build correct headers (authenticated and non-authenticated)
#   - Generate SEO-style keys for the search endpoint
#   - Attach the required nkparam header
#   - Parse raw API responses into the Job model
#   - Normalize inconsistent fields (placeholders, tags, etc.)
#   - Handle common failure cases (403, 406, malformed JSON)
# ----------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------
# nkparam header
#
# nkparam is a signed request header required by the Naukri search API. It is
# generated inside their obfuscated frontend JS and validated server-side.
# A missing or invalid token results in a 403 response.
#
# It is not tied to the login session directly, but to how the frontend signs
# outgoing requests.
# ----------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------
# Supported nkparam modes
#
# 1. Generator mode (default)
#    Uses generate_nkparam("srp") to produce a fresh token per request.
#    Preferred when the generator logic is working correctly.
#
# 2. Pool mode (optional)
#    Uses a list of pre-captured tokens (self.pool), rotated via pool_idx.
#    Useful as a fallback if the generator breaks.
#
# Toggle via:
#    NaukriJobClient(login_client, use_pool=True)
# ----------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------
# Token pool notes
#
# Naukri's search endpoint (/jobapi/v3/search) requires a signed nkparam header.
# This token is generated inside Naukri's obfuscated JS bundle and changes each
# browser session. Without a valid token the API returns 403 Forbidden.
#
# Harvesting tokens:
#   1. Run: python get_Nkparam.py
#      Opens Chrome, captures nkparam from network logs, appends to nkPool.txt.
#   2. Collect roughly 100 tokens for light usage, ~1000 for heavy usage.
#
# Using the pool:
#   self.pool = open("nkPool.txt").read().splitlines()
#
# Token expiry:
#   Tokens typically last a few hours. On 403, rotate to the next token.
#   If all tokens fail, regenerate the pool.
#
# Note: do not commit nkPool.txt. Add it to .gitignore.
# ----------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------
# Design notes
#
# - All helpers live inside the class, no module-level globals.
# - _get_nkparam() abstracts which token source is used.
# - The search path only requires a valid nkparam.
# - The rest of the client is a standard request / parse layer.
# ----------------------------------------------------------------------------------


class NaukriJobClient:

    def __init__(self, login_client: NaukriLoginClient, use_pool: bool = False):
        if not login_client.session:
            raise NaukriAuthError("Login required")

        self._session = login_client.session
        self._client = login_client

        self.pool_idx = 0
        self.use_pool = use_pool

        # Seed pool with one pre-captured token as a baseline fallback.
        self.pool = [
            "sa9chfJkrXEpn3Zt7rAPaAOb6gAWNSFzzmPQEc6tLSMzytUGPxrGDqiKJyjvBAHGIYPhbDRBDHMad071ZRZlZA=="
        ]

    # ----------------------------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------------------------

    def _parse_job(self, raw: dict) -> Job:
        # Extract location from the placeholders list if present.
        location = next(
            (p["label"] for p in raw.get("placeholders", []) if p.get("type") == "location"),
            "N/A",
        )
        return Job(
            job_id=str(raw.get("jobId") or raw.get("id") or ""),
            title=raw.get("title") or raw.get("jobTitle") or "N/A",
            company=raw.get("companyName") or raw.get("company") or "N/A",
            location=location,
            experience=raw.get("experienceText") or raw.get("experience") or "N/A",
            salary=raw.get("salaryDetail") or raw.get("salary") or "Not disclosed",
            posted_date=raw.get("footerPlaceholderLabel") or raw.get("postedDate") or "N/A",
            apply_link=raw.get("jdURL") or f"https://www.naukri.com/job-listings-{raw.get('jobId', '')}",
            description=raw.get("jobDescription") or "",
            tags=(
                [t.strip() for t in raw.get("tagsAndSkills", "").split(",")]
                if raw.get("tagsAndSkills")
                else []
            ),
        )

    def _cluster_dates(self) -> dict:
        # Returns a dict of current UTC timestamps used by the recommended jobs payload.
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return {
            "apply":        now,
            "preference":   now,
            "profile":      now,
            "similar_jobs": now,
        }

    def _headers(self):
        return self._client._build_headers(auth=True)

    def _build_seo_key(self, keyword: str, location: str, page: int) -> str:
        # Produces the seoKey param expected by the search endpoint.
        # Example: "python-developer-jobs-in-bangalore-2"
        kw_slug = (
            keyword.strip().lower()
            .replace(".", "-dot-")
            .replace(" ", "-")
            .replace("+", "-")
            .strip("-")
        )

        if location.strip():
            loc_slug = location.strip().lower().replace(" ", "-")
            return f"{kw_slug}-jobs-in-{loc_slug}-{page}"

        return f"{kw_slug}-jobs-{page}"

    def format_jobs(self, raw_jobs: list) -> list[dict]:
        # Converts raw job dicts from the API into a flat, readable structure.
        formatted = []

        for job in raw_jobs:
            exp = sal = loc = ""

            for item in job.get("placeholders", []):
                t = item.get("type")
                if t == "experience":
                    exp = item.get("label")
                elif t == "salary":
                    sal = item.get("label")
                elif t == "location":
                    loc = item.get("label")

            formatted.append({
                "title":    job.get("title"),
                "company":  job.get("companyName"),
                "experience": exp,
                "location": loc,
                "salary":   sal,
                "skills":   job.get("tagsAndSkills", "").split(","),
                "job_url":  "https://www.naukri.com" + job.get("jdURL", ""),
                "posted":   job.get("footerPlaceholderLabel"),
            })

        return formatted

    def _get_nkparam(self) -> str:
        # Returns a token from the pool (pool mode) or generates a fresh one.
        if self.use_pool:
            token = self.pool[self.pool_idx % len(self.pool)]
            self.pool_idx += 1
            return token
        return generate_nkparam("srp")

    def _search_headers(self) -> dict:
        # Builds headers for the search endpoint. Uses non-auth base headers
        # and adds the appid, gid, and nkparam fields required by the search API.
        headers = self._client._build_headers(auth=False)
        headers.update({
            "authority":       "www.naukri.com",
            "accept":          "application/json",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "appid":           "109",
            "gid":             "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
            "nkparam":         self._get_nkparam(),
        })
        return headers

    # ----------------------------------------------------------------------------------
    # Job details
    # ----------------------------------------------------------------------------------

    def get_job_details(self, job_id: str, sid: str = "") -> dict:
        if not job_id:
            raise ValueError("job_id is required")

        if not sid:
            sid = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "0000000"

        url = f"https://www.naukri.com/jobapi/v1/job/{job_id}"

        params = {
            "microsite": "y",
            "src":       "jobsearchDesk",
            "sid":       sid,
            "xp":        "1",
            "px":        "1",
        }

        headers = self._client._build_headers(auth=True)
        headers["nkparam"] = self._get_nkparam()
        headers.update({
            "appid":          "121",
            "systemid":       "Naukri",
            "clientid":       "d3skt0p",
            "accept":         "application/json",
            "referer":        "https://www.naukri.com/",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        })

        logger.debug("Fetching job details for job_id=%s sid=%s", job_id, sid)

        res = self._session.get(url, headers=headers, params=params)

        if res.status_code in (401, 403):
            try:
                msg = res.json().get("message", "Auth failed")
            except Exception:
                msg = res.text
            raise NaukriAuthError(msg)

        if not res.ok:
            raise NaukriParseError(f"Job details fetch failed: {res.status_code} — {res.text}")

        try:
            return res.json()
        except Exception:
            raise NaukriParseError(f"Invalid JSON response: {res.text}")

    def is_external_apply(self, job_id: str, sid: str = "") -> bool:
        # Returns True if the job redirects to an external company URL for apply.
        data = self.get_job_details(job_id, sid)
        return data.get("job", {}).get("responseManager") == "companyUrl"

    # ----------------------------------------------------------------------------------
    # Apply job
    # ----------------------------------------------------------------------------------

    def apply_job(
        self,
        job: Job,
        mandatory_skills: list[str] = None,
        optional_skills:  list[str] = None,
        sid:    str = "",
        source: str = "recommended",
    ) -> dict:
        url = APPLY_JOB_URL

        if not job.job_id:
            raise ValueError("Invalid job_id")

        if not sid:
            sid = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "0000000"

        apply_src, logstr_template = APPLY_SRC_MAP.get(source, APPLY_SRC_MAP["recommended"])
        logstr = logstr_template.format(sid=sid)

        payload = {
            "strJobsarr":       [job.job_id],
            "logstr":           logstr,
            "flowtype":         "show",
            "crossdomain":      True,
            "jquery":           1,
            "rdxMsgId":         "",
            "chatBotSDK":       True,
            "mandatory_skills": mandatory_skills or [],
            "optional_skills":  optional_skills or [],
            "applyTypeId":      "107",
            "closebtn":         "y",
            "applySrc":         apply_src,
            "sid":              sid,
            "mid":              "",
        }

        headers = self._client._build_headers(auth=True)
        headers.update({
            "appid":     "121",
            "systemid":  "jobseeker",
            "clientid":  "d3skt0p",
            "accept":    "application/json",
        })

        logger.debug("Applying to job_id=%s sid=%s", job.job_id, sid)

        res = self._session.post(url, headers=headers, json=payload)

        if res.status_code in (401, 403):
            try:
                msg = res.json().get("message", "Auth failed")
            except Exception:
                msg = res.text
            raise NaukriAuthError(msg)

        if not res.ok:
            raise NaukriParseError(f"Apply failed: {res.status_code} — {res.text}")

        try:
            return res.json()
        except Exception:
            raise NaukriParseError(f"Invalid JSON response: {res.text}")

    # ----------------------------------------------------------------------------------
    # Apply job with questionnaire answers
    # ----------------------------------------------------------------------------------

    def handle_static_questionnaire_and_apply(
        self,
        job,
        questionnaire,
        sid,
        mandatory_skills=None,
        optional_skills=None,
        source="recommended",
    ) -> dict:

        # Static profile values used when generating questionnaire answers.
        # Update these to match the candidate's actual profile.
        PROFILE = {
            "current_ctc":  "5",
            "expected_ctc": "7",
            "exp_total":    "2",
            "exp_node":     "2",
            "exp_python":   "1",
            "notice_days":  30,
            "skills": [
                "node", "docker", "kubernetes",
                "aws", "ci/cd", "jenkins", "terraform",
            ],
        }

        def build_smart_answers(questionnaire: list, profile: dict) -> dict:
            answers = {}

            def pick_yes(options: dict) -> str:
                # Prefer any option whose label contains "yes".
                for k, v in options.items():
                    if "yes" in v.lower():
                        return k
                return list(options.keys())[0]

            def pick_notice(options: dict, notice_days: int) -> str:
                # Match the closest notice period bucket to notice_days.
                for k, v in options.items():
                    val = v.lower()
                    if "15" in val and notice_days <= 15:
                        return k
                    if "1 month" in val and notice_days <= 30:
                        return k
                    if "2 month" in val and notice_days <= 60:
                        return k
                return list(options.keys())[0]

            for q in questionnaire:
                qid   = q["questionId"]
                qtext = (q.get("questionName") or "").lower()
                qtype = (q.get("questionType") or "").lower()
                options = q.get("answerOption") or {}

                if qtype == "text box":
                    if "current ctc" in qtext:
                        ans = profile["current_ctc"]
                    elif "expected ctc" in qtext:
                        ans = profile["expected_ctc"]
                    elif "experience" in qtext:
                        if "node" in qtext:
                            ans = profile["exp_node"]
                        elif "python" in qtext:
                            ans = profile["exp_python"]
                        else:
                            ans = profile["exp_total"]
                    elif "notice" in qtext:
                        ans = str(profile["notice_days"])
                    else:
                        ans = "1"

                else:
                    if options:
                        if "notice" in qtext:
                            key = pick_notice(options, profile["notice_days"])
                        elif any(skill in qtext for skill in profile["skills"]):
                            key = pick_yes(options)
                        elif any(x in qtext for x in ["do you", "have you", "experience"]):
                            key = pick_yes(options)
                        else:
                            key = list(options.keys())[0]

                        # Option-type answers must always be wrapped in a list.
                        ans = [key]
                    else:
                        ans = "1"

                answers[qid] = ans

            return answers

        answers = build_smart_answers(questionnaire, PROFILE)
        logger.debug("Generated answers: %s", answers)

        apply_src, logstr_template = APPLY_SRC_MAP.get(source, APPLY_SRC_MAP["recommended"])
        logstr = logstr_template.format(sid=sid)

        payload = {
            "strJobsarr":       [job.job_id],
            "logstr":           logstr,
            "flowtype":         "show",
            "crossdomain":      True,
            "jquery":           1,
            "rdxMsgId":         "",
            "chatBotSDK":       True,
            "mandatory_skills": mandatory_skills or [],
            "optional_skills":  optional_skills or [],
            "applyTypeId":      "107",
            "closebtn":         "y",
            "applySrc":         apply_src,
            "sid":              sid,
            "mid":              "",
            "applyData": {
                job.job_id: {
                    "answers": answers,
                }
            },
        }

        headers = self._client._build_headers(auth=True)
        res = self._session.post(APPLY_JOB_URL, headers=headers, json=payload)

        if not res.ok:
            logger.debug("Apply failed: %s", res.text)
            return {"success": False, "error": res.text}

        try:
            return res.json()
        except Exception:
            return {"success": False, "error": "Invalid JSON response"}

    # ----------------------------------------------------------------------------------
    # Recommended jobs
    # ----------------------------------------------------------------------------------

    def get_recommended_jobs(self) -> list[Job]:
        url = RECOMMENDED_JOBS_URL
        res = self._session.post(
            url,
            headers=self._headers(),
            json={
                "clusterId":       None,
                "src":             "recommClusterApi",
                "clusterSplitDate": self._cluster_dates(),
            },
        )

        if not res.ok:
            raise NaukriParseError(f"Recommended jobs fetch failed: {res.status_code}")

        data = res.json()
        raw_jobs = data.get("jobDetails") or []
        print(raw_jobs[:5])
        return [self._parse_job(j) for j in raw_jobs]

    # ----------------------------------------------------------------------------------
    # Job filtering helpers (used by search_jobs)
    # ----------------------------------------------------------------------------------

    def _filter_jobs_by_skip_keywords(self, jobs: list[Job] , skip_keywords: Optional[list[str]]) -> list[Job]:
        """
        Filter out jobs whose tags contain any skip keywords.

        Args:
            jobs: List of Job objects to filter

        Returns:
            Filtered list of Job objects
        """
        # Pre-lowercase once to avoid repeated conversions inside the loop
        skip_keywords = [kw.lower() for kw in skip_keywords]

        filtered = []
        for job in jobs:
            if not job.tags:
                filtered.append(job)
                continue

            lowered_tags = [(tag, tag.lower()) for tag in job.tags]

            match = next(
                (
                    (tag, kw)
                    for tag, tag_lower in lowered_tags
                    for kw in skip_keywords
                    if kw in tag_lower
                ),
                None,
            )

            if not match:
                filtered.append(job)
            
       
        logger.info(
            f"Skipping jobs with that matches skip keywords/job tags"
        )

        return filtered

    # ----------------------------------------------------------------------------------
    # Search jobs
    # ----------------------------------------------------------------------------------

    def search_jobs(
        self,
        keyword:          str,
        location:         str = "",
        page:             int = 2,
        job_age:          int = 3,
        experience:       int = 2,
        results_per_page: int = 20,
        lat_long:         str = "",
        skip_keywords:    Optional[list[str]] = None,
    ) -> list[Job]:

        url     = JOB_SEARCH_URL
        seo_key = self._build_seo_key(keyword, location, page)

        params = {
            "noOfResults":    results_per_page,
            "urlType":        "search_by_keyword",
            "searchType":     "adv",
            "keyword":        keyword,
            "k":              keyword,
            "pageNo":         page,
            "experience":     experience,
            "jobAge":         job_age,
            "nignbevent_src": "jobsearchDeskGNB",
            "seoKey":         seo_key,
            "src":            "jobsearchDesk",
            "latLong":        lat_long,
        }

        res = self._session.get(url, headers=self._search_headers(), params=params)

        if res.status_code == 403:
            raise NaukriAuthError("403 Forbidden — nkparam token likely expired")

        if res.status_code == 406:
            logger.debug("406 Validation error: %s", res.text)
            return []

        if not res.ok:
            raise NaukriParseError(f"Search failed: {res.status_code} — {res.text}")

        data     = res.json()
        raw_jobs = data.get("jobDetails") or data.get("jobs") or []

        # format_jobs is called here for side-effect logging/debugging purposes.
        self.format_jobs(raw_jobs)

        if not raw_jobs:
            logger.debug("No jobs returned for keyword=%r page=%d", keyword, page)
            return []

        jobs = [self._parse_job(j) for j in raw_jobs]
        if skip_keywords is not None:
            jobs = self._filter_jobs_by_skip_keywords(jobs,skip_keywords)

        return jobs