"""Data models shared across the showrunner."""

from typing import Literal

from pydantic import BaseModel, Field

FactState = Literal["on_track", "late", "blocked", "done", "unknown"]
MoveHint = Literal[
    "none", "nod", "tilt_left", "tilt_right",
    "look_away", "lean_in", "antenna_perk", "shake_head",
]
Edge = Literal["clean", "pg13", "blue"]


class Fact(BaseModel):
    """One extracted claim from the source document."""

    id: str
    name: str
    state: FactState
    note: str = ""
    owner: str | None = None
    date: str | None = None
    included: bool = True


class StatusDoc(BaseModel):
    """Normalized view of the operator's document."""

    title: str
    facts: list[Fact]
    excerpts: list[str] = Field(default_factory=list)

    def included_facts(self) -> list[Fact]:
        return [f for f in self.facts if f.included]


class Beat(BaseModel):
    """One unit of the set: a premise, a take on it, and a punch."""

    id: str
    premise: str
    angle: str
    punch: str
    source_fact_id: str
    act_out: str | None = None
    tags: list[str] = Field(default_factory=list)
    move_hint: MoveHint = "none"


class SetList(BaseModel):
    """The full arc the comedian performs."""

    opener: str
    beats: list[Beat]
    closer: str
    callbacks: list[str] = Field(default_factory=list)

    def beat_ids(self) -> list[str]:
        return [b.id for b in self.beats]


class Knobs(BaseModel):
    """Operator-tunable set parameters."""

    beat_count: int = 5
    edge: Edge = "pg13"
    persona_notes: str = ""
