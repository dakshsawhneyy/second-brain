"""Card schema v1, taxonomy constants and validation helpers."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOPICS: frozenset[str] = frozenset(
    {
        "ai/claude-tips", "ai/agents", "ai/llm-engineering", "ai/tools", "ai/news",
        "infra/devops", "infra/sre", "infra/platform", "infra/cloud", "infra/security-finops",
        "business/startup-stories", "business/product", "business/saas-pricing", "business/money",
        "marketing/audience", "marketing/sales", "marketing/positioning",
        "growth/habits", "growth/focus", "growth/mindset", "growth/health",
        "career/remote-jobs", "career/strategy", "career/engineering",
        "work/software-building", "work/content-creation", "work/admin-setup",
        "noise/entertainment",
        "uncertain",
    }
)
FORMATS: frozenset[str] = frozenset(
    {"tip", "tutorial", "podcast", "talk", "news", "case-study", "opinion", "review"}
)
CARD_TYPES: tuple[str, ...] = (
    "consumed", "thought", "decided", "acted", "produced", "experiment", "friction", "book", "link",
    "commitment", "checkin",
)

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def validate_topic(t: str) -> str:
    """Return t if it is a known topic id, else 'uncertain'."""
    return t if t in TOPICS else "uncertain"


def _check_topic(t: str) -> str:
    if t not in TOPICS:
        raise ValueError(f"unknown topic: {t!r}")
    return t


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Topic(_Strict):
    primary: str
    secondary: list[str] = Field(default_factory=list, max_length=2)

    @field_validator("primary")
    @classmethod
    def _primary_known(cls, v: str) -> str:
        return _check_topic(v)

    @field_validator("secondary")
    @classmethod
    def _secondary_known(cls, v: list[str]) -> list[str]:
        for t in v:
            _check_topic(t)
        return v


class KeyPoint(_Strict):
    text: str
    topic: str
    t: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("topic")
    @classmethod
    def _topic_known(cls, v: str) -> str:
        return _check_topic(v)


class Relevance(_Strict):
    bet_job: int = Field(ge=0, le=10)
    bet_product: int = Field(ge=0, le=10)
    actionability: int = Field(ge=0, le=10)
    novelty: int = Field(ge=0, le=10)
    quality: int = Field(ge=0, le=10)
    score: int = Field(ge=0, le=100)


class Action(_Strict):
    text: str
    status: Literal["open", "done", "later", "skipped"] = "open"


class Provenance(_Strict):
    transcript: Literal["captions", "whisper", "none", "n/a"] = "n/a"
    model: str | None = None
    processed_at: datetime | None = None


class UserSignals(_Strict):
    rating: int | None = Field(default=None, ge=1, le=5)
    acted: bool | None = None


class MentorMeta(_Strict):
    """Extra fields of a mentor `commitment` / `checkin` card (additive: old cards stay valid)."""
    day: date                                           # mentor day (04:00 to 03:59), Asia/Kolkata
    item: int | None = Field(default=None, ge=1, le=3)  # position within the day's commitments
    status: Literal["open", "kept", "missed", "dropped"] = "open"
    evidence: Literal["claimed", "corroborated", "verified"] | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=10)
    bet: Literal["job", "product", "other"] = "other"
    when: str | None = Field(default=None, max_length=80)         # the if-then cue: "10:00", "before noon"
    first_action: str | None = Field(default=None, max_length=200)
    miss_category: str | None = None
    reason: str | None = Field(default=None, max_length=300)
    vague: bool = False
    late: bool = False
    auto_closed: bool = False
    carried_from: str | None = None


class Card(_Strict):
    schema_version: Literal["card.v1"] = "card.v1"
    id: str
    source: str
    type: Literal["consumed", "thought", "decided", "acted", "produced", "experiment", "friction", "book", "link",
                  "commitment", "checkin"]
    title: str
    url: str | None = None
    channel: str | None = None
    consumed_at: datetime
    topic: Topic
    format: str | None = None
    relevance: Relevance | None = None
    key_points: list[KeyPoint] = Field(default_factory=list)
    action: Action | None = None
    visibility: Literal["private", "publishable"] = "private"
    tier: Literal["hot", "warm", "cold"] = "hot"
    provenance: Provenance = Field(default_factory=Provenance)
    user: UserSignals = Field(default_factory=UserSignals)
    mentor: MentorMeta | None = None
    reply_to: str | None = Field(default=None, max_length=400)  # the message this one was a reply to
    derived_from: list[str] = Field(default_factory=list, max_length=200)  # ids of the cards a digest was built from

    @model_validator(mode="after")
    def _mentor_cards_stay_private(self):
        if self.mentor is not None and self.visibility != "private":
            raise ValueError("mentor cards must be private")
        if self.type in ("commitment", "checkin") and self.mentor is None:
            raise ValueError(f"a {self.type} card needs mentor metadata")
        return self

    @field_validator("id")
    @classmethod
    def _id_safe(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9_-]{1,100}")
        return v

    @field_validator("consumed_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("consumed_at must be timezone-aware")
        return v

    @field_validator("format")
    @classmethod
    def _format_known(cls, v: str | None) -> str | None:
        if v is not None and v not in FORMATS:
            raise ValueError(f"unknown format: {v!r}")
        return v


class Tombstone(_Strict):
    id: str
    source: str
    title: str
    url: str | None = None
    date: date
    topic: str
    score: int = Field(ge=0, le=100)

    @field_validator("id")
    @classmethod
    def _id_safe(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9_-]{1,100}")
        return v


def export_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(Card.model_json_schema(), indent=2), encoding="utf-8")
