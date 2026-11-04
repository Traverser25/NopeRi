import re

# -- Auth --
LOGIN_URL       = "https://www.naukri.com/central-login-services/v1/login"
OTP_VERIFY_URL  = "https://www.naukri.com/central-login-services/v0/otp-login"
OTP_SEND_URL    = "https://www.naukri.com/central-login-services/v1/otp"

# -- Profile --
PROFILE_URL         = "https://www.naukri.com/mnjuser/profile"
PROFILE_UPDATE_URL  = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v1/users/self/fullprofiles"
DASHBOARD_URL       = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/dashboard"
FILE_VALIDATION_URL = "https://filevalidation.naukri.com/file"
RESUME_UPDATE_URL_TEMPLATE = (
    "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services"
    "/v0/users/self/profiles/{profile_id}/advResume"
)

# -- Jobs --
JOB_SEARCH_URL       = "https://www.naukri.com/jobapi/v3/search"
RECOMMENDED_JOBS_URL = "https://www.naukri.com/jobapi/v2/search/recom-jobs"
APPLY_JOB_URL        = "https://www.naukri.com/cloudgateway-workflow/workflow-services/apply-workflow/v1/apply"
HISTORY_URL          = "https://www.naukri.com/cloudgateway-apply/whtma-services/v0/applyapi/v5/history"

# -- RSA public key (used for nkparam / form-key operations) --
PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALrlQ+djR0RjJwBF1xuisHmdFv334MIm\n"
    "K6LgzJhmLhN7B5yuEyaKoasgXQk3+OQglsOaBxEJ0j5PcTL3nbOvt80CAwEAAQ==\n"
    "-----END PUBLIC KEY-----"
)

# -- Form-key extraction patterns --
FORM_KEY_PATTERNS = [
    re.compile(r'formKey\s*[:=]\s*["\']([A-Za-z0-9]{8,})["\']'),
    re.compile(r'"formKey"\s*:\s*"([A-Za-z0-9]{8,})"'),
]

APP_JS_PATTERN = re.compile(r'<script[^>]+src="([^"]*app_v\d+\.min\.js[^"]*)"')
