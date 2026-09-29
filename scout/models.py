import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["experience", "project", "achievement", "skill", "education", "preference"]


class BackgroundItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64)
    category: Category
    title: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=3000)
    quote: str = Field(default="", max_length=6000)


class Profile(BaseModel):
    name: str = Field(default="", max_length=100)
    roles: list[str] = Field(default_factory=list, max_length=12)
    skills: list[str] = Field(default_factory=list, max_length=40)
    locations: list[str] = Field(default_factory=list, max_length=20)
    remote: Literal["any", "remote", "onsite"] = "any"
    seniority: Literal["any", "junior", "mid", "senior", "lead"] = "any"
    interests: list[str] = Field(default_factory=list, max_length=20)
    excluded: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=3000)
    background: list[BackgroundItem] = Field(default_factory=list, max_length=60)

    @field_validator("roles", "skills", "locations", "interests", "excluded")
    @classmethod
    def clean_terms(cls, values):
        if any(len(v) > 120 for v in values):
            raise ValueError("Keep each term under 120 characters")
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))


class Source(BaseModel):
    provider: Literal["greenhouse", "lever", "ashby"]
    board: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=100)

    @field_validator("board")
    @classmethod
    def board_slug(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use the board identifier, not a URL")
        return value


class Decision(BaseModel):
    status: Literal["new", "saved", "dismissed"]
    reason: str = Field(default="", max_length=300)


class Evidence(BaseModel):
    claim: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=8, max_length=700)


class Review(BaseModel):
    fit: Literal["strong", "possible", "weak"]
    summary: str = Field(min_length=1, max_length=1200)
    evidence: list[Evidence] = Field(min_length=1, max_length=6)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    profile_version: str
    job_version: str
