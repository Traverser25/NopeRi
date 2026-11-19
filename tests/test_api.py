"""
Change-detection smoke tests for NopeRi.

Run:  pytest tests/ -v
Run (skip live network):  pytest tests/ -v -m "not live"

Live tests need NAUKRI_USERNAME + PASSWORD in .env.
They are skipped automatically when credentials are absent.

Purpose: fail fast when Naukri changes their API shape.
Live tests share one login to keep the request count low — bursts trigger
Naukri's reCAPTCHA gate on job details.
"""
import os

import httpcloak
import pytest
from dotenv import load_dotenv

from src.client.job_client import NaukriJobClient
from src.client.naukri_client import NaukriLoginClient
from src.utils.nkparam_generator import generate_nkparam
from src.utils.vid_generator import generate_vid

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

_HAS_CREDS = bool(os.getenv("NAUKRI_USERNAME")) and bool(os.getenv("PASSWORD"))
live = pytest.mark.skipif(not _HAS_CREDS, reason="NAUKRI_USERNAME / PASSWORD not in .env")


# ---------------------------------------------------------------------------
# Offline
# ---------------------------------------------------------------------------

def test_vid_token_generates():
    vid = generate_vid()
    assert isinstance(vid, str) and len(vid) > 10, "vid token looks wrong"


def test_nkparam_differs_per_call():
    assert generate_nkparam("srp") != generate_nkparam("srp")


def test_parse_job_reads_company_apply_flag():
    jc = object.__new__(NaukriJobClient)
    assert jc._parse_job({"jobId": "1", "companyApplyJob": True}).company_apply is True
    assert jc._parse_job({"jobId": "2"}).company_apply is False


def test_httpcloak_cookie_copy_behaviour_still_holds():
    # Guards the from_browser_cookies fix: item assignment on .cookies is lost.
    s = httpcloak.Session(preset="chrome-latest", timeout=30)
    s.cookies["probe"] = "x"
    assert s.cookies.get("probe") is None
    s.set_cookie("probe", "x", domain=".naukri.com")
    assert s.cookies.get("probe") == "x"


def test_from_browser_cookies_sets_session_cookies(monkeypatch):
    monkeypatch.setattr(NaukriLoginClient, "get_form_key2", lambda self: "fk")
    client = NaukriLoginClient.from_browser_cookies("token-at", "token-rt")
    assert client.session.cookies.get("nauk_at") == "token-at"
    assert client.session.cookies.get("nauk_rt") == "token-rt"
    assert client.naukri_session.bearer_token == "token-at"


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    c = NaukriLoginClient(os.getenv("NAUKRI_USERNAME"), os.getenv("PASSWORD"))
    c.login()
    return c


@pytest.fixture(scope="module")
def jc(client):
    return NaukriJobClient(client)


@pytest.fixture(scope="module")
def search_results(jc):
    return jc.search_jobs("python developer", "", page=1, job_age=7, experience=3)


@live
def test_login_returns_nauk_at(client):
    nauk_at = client.session.cookies.get("nauk_at")
    assert nauk_at, "nauk_at cookie missing after login — BotGuard may have changed"
    assert len(nauk_at) > 20, "nauk_at suspiciously short"


@live
def test_job_search_returns_parsed_jobs(search_results):
    assert search_results, "Job search returned 0 results — endpoint or nkparam may have changed"
    job = search_results[0]
    assert job.job_id and job.title != "N/A" and job.company != "N/A", f"unexpected job: {job}"


@live
def test_recommended_jobs_parse(jc):
    jobs = jc.get_recommended_jobs()
    if not jobs:
        pytest.skip("No recommended jobs returned (empty feed is not a failure)")
    assert jobs[0].job_id and jobs[0].title != "N/A"


@live
def test_job_details_v4_shape(jc, search_results):
    details = jc.get_job_details(search_results[0].job_id)["jobDetails"]
    assert details.get("jobId") == search_results[0].job_id
    assert details.get("title"), "jobDetails missing title"


@live
def test_company_apply_flag_matches_job_details(jc, search_results):
    # The agent trusts the search flag instead of calling job details; check they agree.
    sample = [j for j in search_results if j.company_apply][:2] + [j for j in search_results if not j.company_apply][:2]
    assert sample, "no jobs to compare"
    for job in sample:
        assert jc.is_external_apply(job.job_id) == job.company_apply, f"flag mismatch for {job.job_id}"


@live
def test_cookie_session_can_fetch_job_details(client, search_results):
    cookie_client = NaukriLoginClient.from_browser_cookies(
        client.session.cookies.get("nauk_at"), client.session.cookies.get("nauk_rt") or ""
    )
    details = NaukriJobClient(cookie_client).get_job_details(search_results[0].job_id)
    assert details["jobDetails"].get("jobId") == search_results[0].job_id
