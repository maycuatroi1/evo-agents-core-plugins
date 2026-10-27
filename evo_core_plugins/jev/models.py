"""The API of the plugin jev as Pydantic models, each named ``Jev...`` in the hub's OpenAPI document.

A question is of one of three types, as the System One API has them: ``choice`` (criteria: each option and what it
means), ``noul`` (a number from 0 to 1, how much it is a yes; criteria optional: what true and false mean) and
``score`` (criteria: the ordered levels, from 2 to 10).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

QUESTION_NAME = r"^[A-Za-z][A-Za-z0-9_]{0,39}$"
MAX_QUESTIONS = 20
MAX_OPTIONS = 50
MAX_INSTRUCTIONS = 4000
MAX_CRITERION = 1000

Name = Annotated[str, StringConstraints(pattern=QUESTION_NAME)]
Words = Annotated[str, StringConstraints(max_length=MAX_CRITERION)]


class JevQuestion(BaseModel):
    type: Literal["choice", "noul", "score"]
    instructions: Annotated[str, StringConstraints(max_length=MAX_INSTRUCTIONS)] | None = None
    criteria: dict[str, Words] | list[Words] | None = None

    @model_validator(mode="after")
    def _criteria_fit_the_type(self):
        found = self.criteria
        if self.type == "choice":
            if not isinstance(found, dict) or not 2 <= len(found) <= MAX_OPTIONS:
                raise ValueError(f"a choice's criteria is an object of 2 to {MAX_OPTIONS} options, each with its words")
        elif self.type == "score":
            if not isinstance(found, list) or not 2 <= len(found) <= 10:
                raise ValueError("a score's criteria is a list of 2 to 10 levels, lowest first")
        elif found is not None and (not isinstance(found, dict) or set(found) - {"true", "false"}):
            raise ValueError("a noul's criteria, when given, is an object with the keys true and false")
        return self


class JevAskIn(BaseModel):
    state: str | dict | list = Field(description="what the questions are about: text, or JSON")
    questions: Annotated[dict[Name, JevQuestion], Field(min_length=1, max_length=MAX_QUESTIONS)]


class JevFeature(BaseModel):
    name: str
    mode: str
    threshold: float | None = None
    noul_yes: float | None = None
    noul_no: float | None = None
    cap: int | None = None
    applied_today: int | None = None


class JevStatus(BaseModel):
    project: str
    enabled: bool
    configured: bool
    key_set: bool
    model: str | None
    base_url: str
    sink: str
    sink_declared: bool
    price_usd_per_million_tokens: float
    daily_usd: float
    spent_today_usd: float
    features: list[JevFeature]
    problems: list[str]


class JevAnswer(BaseModel):
    type: Literal["choice", "noul", "score"]
    choice: str | None = None
    noul: float | None = None
    score: float | None = None
    confidence: float | None = None
    legend: str | None = None
    probabilities: dict | list | None = None


class JevAsked(BaseModel):
    project: str
    model: str
    input_tokens: int
    cost_usd: float
    answers: dict[str, JevAnswer]


class JevWindow(BaseModel):
    calls: int
    failed: int
    input_tokens: int
    cost_usd: float
    by_feature: list[dict]


class JevUsage(BaseModel):
    project: str
    model: str | None
    price_usd_per_million_tokens: float
    daily_usd: float
    spent_today_usd: float
    last_24h: JevWindow
    last_7d: JevWindow


class JevUndo(BaseModel):
    command: str
    method: str
    path: str


class JevAct(BaseModel):
    id: int
    kind: str
    feature: str
    target: str
    outcome: str
    model: str
    confidence: float | None
    applied: bool
    undone: bool
    undone_at: datetime | None
    created_at: datetime
    undo: JevUndo | None


class JevActs(BaseModel):
    project: str
    acts: list[JevAct]


class JevMatch(BaseModel):
    id: int
    day: date
    evidence: str
    candidate: str
    model: str
    confidence: float
    state: Literal["match", "suggestion"]
    created_at: datetime


class JevMatches(BaseModel):
    project: str
    matches: list[JevMatch]
