"""
Locate Naukri's MNJ (profile) JS bundle.

The profile page is an app shell; it only references app_vNNN.min.js. That app
bundle carries a version map like  _c={app:"_v470",mnj:"_v323",...}  and the
resume uploader's formKey lives in mnj_vNNN.min.js. Hardcoding the mnj version
breaks whenever Naukri ships (mnj_v299 404s as of Sep 2026).
"""
import re

STATIC_JS_BASE = "https://static.naukimg.com/s/5/105/j/"
APP_JS_RE = re.compile(r'src="((?:https?:)?//static\.naukimg\.com/s/5/105/j/app_v\d+\.min\.js)"')
MNJ_VERSION_RE = re.compile(r'\bmnj\s*:\s*"(_v\d+)"')
# last-known-good versions, newest first, tried only if discovery fails
MNJ_FALLBACK_VERSIONS = ("_v323", "_v299")


def app_js_url(profile_html: str) -> str | None:
    m = APP_JS_RE.search(profile_html)
    if not m:
        return None
    url = m.group(1)
    return "https:" + url if url.startswith("//") else url


def mnj_version_from_app_js(app_js: str) -> str | None:
    m = MNJ_VERSION_RE.search(app_js)
    return m.group(1) if m else None


def mnj_url(version: str) -> str:
    return f"{STATIC_JS_BASE}mnj{version}.min.js"


def candidate_mnj_urls(profile_html: str, fetch_text) -> list[str]:
    """Discovered URL first, then fallbacks. `fetch_text(url) -> str` does the I/O."""
    urls: list[str] = []
    app_url = app_js_url(profile_html)
    if app_url:
        try:
            ver = mnj_version_from_app_js(fetch_text(app_url))
            if ver:
                urls.append(mnj_url(ver))
        except Exception:  # noqa: BLE001
            pass
    for ver in MNJ_FALLBACK_VERSIONS:
        u = mnj_url(ver)
        if u not in urls:
            urls.append(u)
    return urls
