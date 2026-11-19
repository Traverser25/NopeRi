
from dataclasses import dataclass, field
import time
from typing import Any, Dict


@dataclass
class NaukriSession:
    bearer_token: str
    cookies: dict
    login_time: float = field(default_factory=time.time)

@dataclass
class FileValidationResult:
    file_key: str
    raw_response: dict
    was_key_remapped: bool

@dataclass
class ResumeUpdateResult:
    profile_id: str
    raw_response: dict
    status_code: int


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    location: str
    experience: str
    salary: str
    posted_date: str
    apply_link: str
    description: str = ""
    tags: list = field(default_factory=list)
    company_apply: bool = False  # applying redirects to the company's own site

@dataclass
class ProfileUpdateResult:
    profile_id: str
    response: Dict[str, Any]
    status_code: int


@dataclass
class ApplicationStatus:
    status_id: int
    status_value: str
    date_time: str

@dataclass
class ApplicationHistory:
    job_id: str
    job_title: str
    company: str
    location: str
    apply_type: str
    is_open: bool
    ars_score: int
    star_rating: str
    job_type: str
    statuses: list[ApplicationStatus]
    company_rating: float = None
    logo_path: str = None