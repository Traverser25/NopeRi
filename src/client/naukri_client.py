import logging
import random
import time
import functools
from io import BytesIO
from src.client.session import build_session
from src.config.constants import *
from src.exceptions.exceptions import *
from src.models.models import *
from src.utils.extractors import extract_form_key2, extract_all_js_urls
import requests
from src.utils.request_helper import with_exponential_retry
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_handler)


# ------------------------------------------------------------------
# IMPORTANT — IP / HOSTING ADVICE (read before deploying)
#################################
# Naukri actively fingerprints the IP of every login and API request.
# Through testing, certain hosting environments consistently trigger
# MFA challenges or outright bans:
#
#   AVOID:
#     - Microsoft Azure (any region)     → flagged heavily, MFA on first req
#     - GitHub Actions / CI runners      → Azure-backed IPs, same result
#     - Google Cloud (some regions)      → increasingly flagged
#     - Any datacenter IP on known CIDR  → Naukri blocks entire ranges
#
#   WORKS RELIABLY:
#     - AWS (residential NAT gateway or EC2 with Elastic IP)
#     - Home broadband / personal IP     → most reliable, zero flags
#     - Mobile hotspot                   → works, good for testing
#     - Residential proxy                → works if clean IP
#
# WHY:
#   Naukri's fraud/bot detection checks whether the IP belongs to a
#   known cloud/datacenter ASN. Azure and GitHub Actions share the
#   same Microsoft AS8075 IP ranges — Naukri recognises these
#   immediately and forces MFA, effectively breaking any headless
#   client. AWS consumer-facing IPs (especially us-east-1 NAT) are
#   less aggressively flagged, but a home server or residential IP
#   is the gold standard.
#
# RECOMMENDATION FOR AGENTS / SCHEDULED WORKERS:
#   - Run the harvester (nk_param_getter.py) and the job client
#     from a home server, a Raspberry Pi, or an AWS EC2 instance
#     with a dedicated Elastic IP (not a shared NAT).
#   - If you must use cloud, attach a residential proxy to the
#     requests session in src/client/session.py:
#
#   - Never run from GitHub Actions — the IP pool is fully burned
#     for Naukri and will MFA-block on every single run.
#
# NOTE:
#   Your login Bearer token and session cookies are tied to the IP
#   that logged in. Switching IPs mid-session will invalidate the
#   session and force a re-login, which may itself trigger MFA.
#   Keep the same IP for the full session lifetime.
# ------------------------------------------------------------------

DEFAULT_HEADERS = {
    "accept": "application/json",
    "appid": "105",
    "clientid": "d3skt0p",
    "content-type": "application/json",
    "referer": "https://www.naukri.com/nlogin/login",
    "systemid": "jobseeker",
    "x-requested-with": "XMLHttpRequest",
}

UPLOAD_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "appid": "105",
    "origin": "https://www.naukri.com",
    "referer": "https://www.naukri.com/",
    "systemid": "fileupload",
}

OTP_HEADERS = {
  "accept": "application/json",
  "appid": "100",
  "content-type": "application/json",
  "referer": "https://www.naukri.com/nlogin/login?URL=//www.naukri.com/mnjuser/recommendedjobs",
  "sec-ch-ua": "\"Chromium\";v=\"146\", \"Not-A.Brand\";v=\"24\", \"Google Chrome\";v=\"146\"",
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": "\"Windows\"",
  "systemid": "jobseeker",
  "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
  "x-requested-with": "XMLHttpRequest"
}

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NaukriLoginClient:

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = build_session()
        self.naukri_session = None
        self.profile_id = None
        self.cache = {}

    def _build_headers(self, auth=False, extra=None):
        headers = DEFAULT_HEADERS.copy()
        if auth:
            if not self.naukri_session:
                raise NaukriAuthError("Login required")
            headers["authorization"] = f"Bearer {self.naukri_session.bearer_token}"
            headers["systemid"] = "Naukri"
        if extra:
            headers.update(extra)
        return headers

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    @with_exponential_retry(label="login")
    def _login_request(self):
        """Raw login HTTP call (separated so the decorator wraps only I/O)."""
        return self.session.post(
            LOGIN_URL,
            headers=self._build_headers(),
            json={"username": self.username, "password": self.password},
        )

    def login(self):
        res = self._login_request()

        if not res.ok:
            print(res.content)
            raise NaukriAuthError("Login failed")

        token = None
        for cookie in self.session.cookies:
            if cookie.name == "nauk_at":
                token = cookie.value

        if not token:
            raise NaukriAuthError("No token")

        self.naukri_session = NaukriSession(token, self.session.cookies)

        try:
            self.cache["form_key"] = self.get_form_key2()
        except Exception:
            pass

        return self.naukri_session

    # ------------------------------------------------------------------
    # form_key helpers
    # ------------------------------------------------------------------
 



    @with_exponential_retry(label="verify_otp")
    def _verify_otp_request(self, username: str, otp: str, is_mobile: bool):
        payload = {
            "username": username,
            "token": otp,

            "flowId": "login",
            "isLoginByEmail": not is_mobile,
            "isLoginByMobile": is_mobile,
        }
        return self.session.post(
            OTP_VERIFY_URL,
            headers=OTP_HEADERS,
            json=payload,
        )

    def verify_otp(self, otp: str, username: str = None, is_mobile: bool = True):
        """
        Verify an OTP challenge issued by Naukri during login.

        Args:
            otp:        The 6-digit OTP received via SMS/email.
            username:   Phone number (if is_mobile=True) or email. Defaults
                        to the username supplied at client construction.
            is_mobile:  True if username is a mobile number (default),
                        False for email-based OTP.

        Returns:
            NaukriSession with the bearer token extracted from cookies.

        Raises:
            NaukriAuthError: On HTTP error or missing token in response.
        """
        target = username or self.username
        res = self._verify_otp_request(target, otp, is_mobile)

        if not res.ok:
            logger.error("OTP verification failed: %s %s", res.status_code, res.text)
            raise NaukriAuthError(f"OTP verification failed ({res.status_code})")

        token = self.session.cookies.get("nauk_at")
        if not token:
            # Some flows return the token in the JSON body instead
            try:
                token = res.json().get("authToken") or res.json().get("token")
            except Exception:
                pass

        if not token:
            raise NaukriAuthError("OTP verified but no auth token received")

        self.naukri_session = NaukriSession(token, self.session.cookies)

        try:
            self.cache["form_key"] = self.get_form_key2()
        except Exception:
            pass

        return self.naukri_session


    @with_exponential_retry(label="send_otp")
    def _send_otp_request(self, username: str, is_mobile: bool):
        payload = {
            "username": username,
            "flowId": "login",
            "isLoginByEmail": not is_mobile,
            "isLoginByMobile": is_mobile,
        }
        otp_header=self._build_headers()
        otp_header["appid"]="100"
        return self.session.post(
            OTP_SEND_URL,
            headers=otp_header,
            json=payload,
        )

    def send_otp(self, username: str = None, is_mobile: bool = True):
        """
        Trigger Naukri to send an OTP to the user's phone/email.

        Args:
            username:   Phone number or email. Defaults to the username
                        supplied at client construction.
            is_mobile:  True for SMS OTP (default), False for email OTP.

        Returns:
            dict: Parsed JSON response from Naukri (contains flowId, etc.)

        Raises:
            NaukriAuthError: If the request fails.
        """
        target = username or self.username
        res = self._send_otp_request(target, is_mobile)

        if not res.ok:
            logger.error("Send OTP failed: %s %s", res.status_code, res.text)
            raise NaukriAuthError(f"Failed to send OTP ({res.status_code})")

        try:
            return res.json()
        except Exception:
            return {}



    @with_exponential_retry(label="get_form_key")
    def _fetch_profile_html(self):
        return self.session.get(PROFILE_URL)

    @with_exponential_retry(label="get_js")
    def _fetch_js(self, js_url):
        return self.session.get(js_url)

    def get_form_key(self):
        if not self.naukri_session:
            raise NaukriAuthError("Login first")

        res = self._fetch_profile_html()
        html = res.text

        match = APP_JS_PATTERN.search(html)
        if not match:
            raise NaukriParseError("JS not found")

        js_url = match.group(1)
        if js_url.startswith("//"):
            js_url = "https:" + js_url

        js = self._fetch_js(js_url).text

        for pattern in FORM_KEY_PATTERNS:
            m = pattern.search(js)
            if m:
                return m.group(1)

        raise NaukriParseError("form key not found")

    @with_exponential_retry(label="get_profile_html_v2")
    def _fetch_profile_html_auth(self):
        return self.session.get(PROFILE_URL, headers=self._build_headers(auth=True))

    def get_form_key2(self):
        if not self.naukri_session:
            raise NaukriAuthError("Login first")

        if "form_key" in self.cache:
            return self.cache["form_key"]

        res = self._fetch_profile_html_auth()
        html = res.text
        js_urls = extract_all_js_urls(html)

        for js_url in js_urls:
            if "mnj" not in js_url:
                continue
            if js_url.startswith("//"):
                js_url = "https:" + js_url
            try:
                js_content = self._fetch_js(js_url).text
                key = extract_form_key2(js_content)
                if key:
                    self.cache["form_key"] = key
                    return key
            except Exception:
                continue

        try:
            fallback_url = "https://static.naukimg.com/s/5/105/j/mnj_v299.min.js"
            js_content = self._fetch_js(fallback_url).text
            key = extract_form_key2(js_content)
            if key:
                self.cache["form_key"] = key
                return key
        except Exception:
            pass

        raise NaukriParseError("formKey2 not found")

    # ------------------------------------------------------------------
    # Profile ID
    # ------------------------------------------------------------------

    @with_exponential_retry(label="fetch_profile_id")
    def _fetch_dashboard(self):
        return self.session.get(DASHBOARD_URL, headers=self._build_headers(auth=True))

    def fetch_profile_id(self):
        if self.profile_id:
            return self.profile_id

        res = self._fetch_dashboard()
        data = res.json()

        pid = data.get("profileId") or data.get("dashBoard", {}).get("profileId")
        if not pid:
            raise NaukriParseError("profile id missing")

        self.profile_id = pid
        return pid

    # ------------------------------------------------------------------
    # File validation / resume upload
    # ------------------------------------------------------------------

    @with_exponential_retry(label="validate_file")
    def _validate_file_request(self, filename, file_bytes, form_key, file_key):
        return requests.post(
            FILE_VALIDATION_URL,
            headers=UPLOAD_HEADERS,
            files={"file": (filename, BytesIO(file_bytes), "application/pdf")},
            data={
                "formKey": form_key,
                "fileName": filename,
                "uploadCallback": "true",
                "fileKey": file_key,
            },
        )

    def validate_file(self, file):
        if not self.naukri_session:
            raise NaukriAuthError("Login first")

        form_key = self.get_form_key2()
        file_key = "U" + self.generate_file_key(13)

        if isinstance(file, str):
            filename = file.split("/")[-1]
            with open(file, "rb") as f:
                file_bytes = f.read()
        else:
            file_bytes = file.read()
            filename = getattr(file, "name", "resume.pdf")

        res = self._validate_file_request(filename, file_bytes, form_key, file_key)

        if not res.ok:
            print(res.request.headers.get("Content-Type"))
            print(res.text)
            raise NaukriUploadError("File validation failed")

        try:
            resp_json = res.json()
        except Exception:
            return [file_key, form_key]

        if file_key not in resp_json:
            return [next(iter(resp_json)), form_key]

        return [file_key, form_key]

    @with_exponential_retry(label="update_resume")
    def _update_resume_request(self, url, headers, payload):
        return self.session.post(url, headers=headers, json=payload)

    def update_resume(self, resume_file):
        pid = self.fetch_profile_id()
        url = RESUME_UPDATE_URL_TEMPLATE.format(profile_id=pid)
        file_key, form_key = self.validate_file(resume_file)

        headers = self._build_headers(
            auth=True,
            extra={
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "en-US,en;q=0.9",
                "content-type": "application/json",
                "origin": "https://www.naukri.com",
                "referer": "https://www.naukri.com/mnjuser/profile",
                "systemid": "105",
                "x-http-method-override": "PUT",
            },
        )

        payload = {"textCV": {"formKey": form_key, "fileKey": file_key}}
        res = self._update_resume_request(url, headers, payload)
        return ResumeUpdateResult(pid, res.json(), res.status_code)

    # ------------------------------------------------------------------
    # Profile update
    # ------------------------------------------------------------------

    @with_exponential_retry(label="update_profile")
    def _update_profile_request(self, headers, payload):
        return self.session.post(PROFILE_UPDATE_URL, headers=headers, json=payload)

    def update_profile(self, headline: str = None, name: str = None, summary: str = None):
        pid = self.fetch_profile_id()

        headers = self._build_headers(
            auth=True,
            extra={
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "en-US,en;q=0.9",
                "origin": "https://www.naukri.com",
                "referer": "https://www.naukri.com/mnjuser/profile?id=&altresid",
                "systemid": "105",
                "x-http-method-override": "PUT",
                "x-requested-with": "XMLHttpRequest",
            },
        )

        profile_fields = {}
        if headline is not None:
            profile_fields["resumeHeadline"] = headline
        if name is not None:
            profile_fields["name"] = name
        if summary is not None:
            profile_fields["summary"] = summary

        if not profile_fields:
            raise ValueError("At least one field must be provided")

        payload = {"profile": profile_fields, "profileId": pid}
        res = self._update_profile_request(headers, payload)
        return ProfileUpdateResult(pid, res.json(), res.status_code)
    


       

    @with_exponential_retry(label="fetch_history")
    def _fetch_history_request(self, page_size, days, page_number, mobile=False):
        headers = {
            "accept": "application/json",
            "appid": "135" if mobile else "107",
            "systemid": "135" if mobile else "107",
            "content-type": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "referer": "https://www.naukri.com/apply/historypage" if mobile else "https://www.naukri.com/myapply/historypage",
            "authorization": f"Bearer {self.naukri_session.bearer_token}",
        }
        if mobile:
            headers["clientid"] = "m0b5"

        params = {
            "pageSize": page_size,
            "days": days,
            "pageNumber": page_number,
        }
        if not mobile:
            params["filterInfo"] = 2

        return self.session.get(HISTORY_URL, headers=headers, params=params)

    def get_application_history(self, page_size=10, days=90, page_number=1, mobile=False):
        """
        Fetch job application history.
        
        Args:
            page_size:    Number of results per page (default 10)
            days:         How far back to look (default 90)
            page_number:  Page number (default 1)
            mobile:       Use mobile headers (default False)
        """
        if not self.naukri_session:
            raise NaukriAuthError("Login first")

        res = self._fetch_history_request(page_size, days, page_number, mobile)

        if not res.ok:
            raise NaukriParseError(f"Failed to fetch history: {res.status_code}")

        return res.json()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    
    def generate_file_key(self, length):
        chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return "".join(random.choice(chars) for _ in range(length))
    

    def parse_history(self, raw: dict) -> list[ApplicationHistory]:
        results = []
        for item in raw.get("applyDetails", []):
            statuses = [
                ApplicationStatus(
                    status_id=s["statusId"],
                    status_value=s["statusValue"],
                    date_time=s["dateTime"],
                )
                for s in item.get("status", [])
            ]
            rating = item.get("companyRating", {})
            results.append(ApplicationHistory(
                job_id=item["jobId"],
                job_title=item["jobTitle"],
                company=item["company"],
                location=item["location"],
                apply_type=item["applyType"],
                is_open=item["isOpen"] == "true",
                ars_score=item.get("arsScore", 0),
                star_rating=item.get("starRating", "0"),
                job_type=item.get("jobType", ""),
                statuses=statuses,
                company_rating=float(rating["AggregateRating"]) if rating else None,
                logo_path=item.get("logoPath"),
            ))
        return results
