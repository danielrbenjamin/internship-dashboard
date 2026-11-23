
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["shortlisted", "preparing", "ready", "applied", "interview", "offer", "closed"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Search(Input):
    name: str = Field(min_length=1, max_length=80)
    keywords: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=100)
    term: str = Field(default="", max_length=80)
    preferred: str = Field(default="", max_length=200)
    alerts: bool = True


class ScoringWeights(Input):
    saved_search: int = Field(50, ge=0, le=100)
    watchlist: int = Field(50, ge=0, le=100)
    search_detail: int = Field(15, ge=0, le=100)
    search_detail_cap: int = Field(50, ge=0, le=100)
    skill: int = Field(10, ge=0, le=100)
    skill_cap: int = Field(30, ge=0, le=100)


class OwnerSettings(Input):
    watchlist: list[str] = Field(default_factory=list, max_length=60)
    searches: list[Search] = Field(default_factory=list, max_length=30)
    experience: str = Field(default="", max_length=24000)
    skills: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=60)
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)
    referral_school: str = Field(default="", max_length=120)
    referral_experience: str = Field(default="", max_length=240)
    referral_priority: Literal["team", "school", "experience"] = "team"
    cover_repo: str = Field(default="",max_length=160,pattern=r"^([\w.-]+/[\w.-]+)?$")
    cover_branch: str = Field(default="main",min_length=1,max_length=100)
    cover_entry: str = Field(default="cover-letter.tex",min_length=5,max_length=200)
    resume_repo: str = Field(default="", max_length=160, pattern=r"^([\w.-]+/[\w.-]+)?$")
    resume_branch: str = Field(default="main", min_length=1, max_length=100)
    resume_entry: str = Field(default="main.tex", min_length=5, max_length=200)


class ApplicationUpdate(Input):
    status: Status
    notes: str = Field(default="", max_length=15000)
    deadline: date | None = None
    submitted_version: str | None = Field(default=None, max_length=64)


class Edit(Input):
    model_config = ConfigDict(str_strip_whitespace=False)

    source_file: str | None = Field(default=None, max_length=200)
    before: str = Field(min_length=2, max_length=4000)
    after: str = Field(max_length=4000)


class CoverLetter(Input):
    content: str = Field(min_length=1, max_length=12000)


class Requirement(Input):
    field: str = Field(min_length=1, max_length=80)
    classification: Literal["mandatory", "preferred", "unknown"]
    requirement: str = Field(max_length=2000)
    quote: str = Field(max_length=2000)


class Assessment(Input):
    verdict: Literal["apply", "review", "skip"] = "review"
    match_score: int | None = Field(default=None, ge=0, le=100)
    recruiter_read: str = Field(default="", max_length=2000)
    interview_questions: list[str] = Field(default_factory=list, max_length=6)
    engineering_fit: str = Field(max_length=4000)
    assessment: list[Requirement] = Field(max_length=30)
    edits: list[Edit] = Field(max_length=15)
    cover_letter: str = Field(default="", max_length=12000)


class ProjectChanges(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    # An unchanged copy lets the editor recompile old PDFs without replacing a saved artifact.
    files: dict[str, str] = Field(max_length=100)
    created: list[str] = Field(default_factory=list,max_length=100)
