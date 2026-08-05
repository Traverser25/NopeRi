

#==========================outdated=============================



import requests
import json
from io import BytesIO
from datetime import datetime
import os
import random
import re

# ================== CONFIG (GLOBAL) ==================
username = ""   # os.environ.get("USER")
password = ""   # os.environ.get("PASS")
file_id = ""    # Google Drive file ID
form_key = ""   # Extract manually from network tab
filename = ""   # Optional override (else auto-generated)


# ================== UTIL ==================
def generate_file_key(length):
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return ''.join(random.choice(chars) for _ in range(length))


# ================== LOGIN CLIENT ==================
class NaukriLoginClient:
    LOGIN_URL = "https://www.naukri.com/central-login-services/v1/login"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()

    def _get_headers(self):
        return {
            "accept": "application/json",
            "appid": "105",
            "clientid": "d3skt0p",
            "content-type": "application/json",
            "referer": "https://www.naukri.com/nlogin/login",
            "systemid": "jobseeker",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "XMLHttpRequest",
        }

    def _get_payload(self):
        return {
            "username": self.username,
            "password": self.password
        }

    def login(self):
        response = self.session.post(
            self.LOGIN_URL,
            headers=self._get_headers(),
            json=self._get_payload()
        )
        response.raise_for_status()
        print("Login status:", response.status_code)
        return response

    def get_cookies(self):
        return self.session.cookies.get_dict()

    def get_bearer_token(self):
        return self.get_cookies().get("nauk_at")

    def fetch_profile_id(self):
        resp = self.session.get(
            "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/dashboard",
            headers={
                "accept": "application/json",
                "appid": "105",
                "clientid": "d3skt0p",
                "systemid": "Naukri",
                "user-agent": "Mozilla/5.0",
                "authorization": f"Bearer {self.get_bearer_token()}",
            },
        )

        resp.raise_for_status()
        data = resp.json()

        profile_id = data.get("dashBoard", {}).get("profileId") or data.get("profileId")

        if not profile_id:
            raise Exception("Profile ID not found")

        print("Profile ID:", profile_id)
        return profile_id

    def build_required_cookies(self):
        cookies = self.get_cookies()

        result = {
            "test": "naukri.com",
            "is_login": "1"
        }

        for key in ["nauk_rt", "nauk_sid", "MYNAUKRI[UNID]"]:
            if cookies.get(key):
                result[key] = cookies[key]

        return result


# ================== MAIN ==================
def update_resume() -> dict:
    """
    Uses global config variables only.
    """

    # ---- VALIDATION ----
    if not username or not password:
        return {"success": False, "error": "Username/password missing"}

    if not file_id:
        return {"success": False, "error": "file_id missing"}

    if not form_key:
        return {"success": False, "error": "form_key missing"}

    # ---- FILENAME ----
    today = datetime.now()
    final_filename = filename or f"resume_{today.strftime('%d_%B_%Y').lower()}.pdf"

    FILE_KEY = "U" + generate_file_key(13)

    # ---- LOGIN ----
    client = NaukriLoginClient(username, password)

    try:
        client.login()
    except Exception as e:
        return {"success": False, "error": f"Login failed: {e}"}

    token = client.get_bearer_token()

    if not token:
        return {"success": False, "error": "Bearer token missing"}

    cookies = client.build_required_cookies()

    # ---- DOWNLOAD ----
    drive_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    try:
        res = requests.get(drive_url)
        res.raise_for_status()
    except Exception as e:
        return {"success": False, "error": f"Download failed: {e}"}

    if res.content[:4] != b'%PDF':
        return {"success": False, "error": "Invalid PDF"}

    # ---- UPLOAD ----
    upload_resp = requests.post(
        "https://filevalidation.naukri.com/file",
        headers={
            "accept": "application/json",
            "appid": "105",
            "origin": "https://www.naukri.com",
            "referer": "https://www.naukri.com/",
            "systemid": "fileupload",
            "user-agent": "Mozilla/5.0",
        },
        files={"file": (final_filename, BytesIO(res.content), "application/pdf")},
        data={
            "formKey": form_key,
            "fileName": final_filename,
            "uploadCallback": "true",
            "fileKey": FILE_KEY,
        }
    )

    try:
        upload_resp.raise_for_status()
    except Exception as e:
        return {"success": False, "error": f"Upload failed: {e}"}

    # ---- PARSE FILE KEY ----
    try:
        upload_json = upload_resp.json()
        if FILE_KEY not in upload_json:
            FILE_KEY = next(iter(upload_json.keys()))
    except Exception:
        pass

    # ---- PROFILE UPDATE ----
    profile_id = client.fetch_profile_id()

    profile_url = f"https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/profiles/{profile_id}/advResume"

    payload = {
        "textCV": {
            "formKey": form_key,
            "fileKey": FILE_KEY,
            "textCvContent": None
        }
    }

    try:
        resp = client.session.post(
            profile_url,
            headers={
                "accept": "application/json",
                "appid": "105",
                "systemid": "Naukri",
                "clientid": "d3skt0p",
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "origin": "https://www.naukri.com",
                "referer": "https://www.naukri.com/",
                "user-agent": "Mozilla/5.0",
                "x-http-method-override": "PUT",
            },
            cookies=cookies,
            data=json.dumps(payload)
        )

        resp.raise_for_status()

    except Exception as e:
        return {"success": False, "error": f"Profile update failed: {e}"}

    return {
        "success": True,
        "file_key": FILE_KEY,
        "message": "Resume updated successfully"
    }


# ================== HANDLER ==================
def handler(event, context):
    print("Cron job started")

    return {
        "status": update_resume(),
        "message": "Cron executed successfully"
    }


# ================== RUN ==================
print(handler("event", "context"))
