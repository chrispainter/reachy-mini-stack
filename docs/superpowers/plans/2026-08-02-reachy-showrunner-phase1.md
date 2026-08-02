# Reachy Showrunner — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a showrunner service that turns an operator-supplied document into a structured comedy set, exposes it to the Reachy Mini conversation app over HTTP, and is fully testable with the robot switched off.

**Architecture:** A standalone Python package in `showrunner/`. A pure core (`models`, `state`) plus two Claude-backed stages (`ingest`, `writer`), surfaced through three thin adapters (`tools` → REST, Gradio console, CLI). The conversation app reaches it in Phase 1 via a throwaway external-tool HTTP bridge. The showrunner never contacts the robot.

**Tech Stack:** Python 3.13, `anthropic` SDK (Claude Opus 5), Pydantic v2, FastAPI + uvicorn, Gradio, pytest, httpx.

## Global Constraints

- **Model: `claude-opus-5`** for both Claude stages. Exact string, no date suffix.
- **Never send `temperature`, `top_p`, or `top_k`.** Removed on Opus 5 — any of them returns a 400. Variety comes from prompt wording only.
- **Thinking is ON by default on Opus 5.** `max_tokens` caps thinking + response text together. Use `max_tokens=16000` on both Claude calls so a set list cannot truncate mid-beat.
- **Check `response.stop_reason == "refusal"` before reading content** on every Claude call. Opus 5 safety classifiers return HTTP 200 with an empty or partial `content`.
- **Tools return `{"error": ...}` and never raise.** An exception propagating into the conversation loop kills the show.
- **Repo:** `/Users/painter/palettepal/reachy-mini-stack`. All paths below are relative to it.
- **No robot access before Task 8.** Every earlier task must pass with the robot powered off.
- **Spec:** `docs/superpowers/specs/2026-08-02-reachy-showrunner-design.md`

## File Structure

| File | Responsibility |
|---|---|
| `showrunner/pyproject.toml` | Package metadata, deps, pytest config |
| `showrunner/.env.example` | `ANTHROPIC_API_KEY`, `SHOWRUNNER_URL` |
| `showrunner/src/showrunner/models.py` | Pydantic models: `Fact`, `StatusDoc`, `Beat`, `SetList`, `Knobs` |
| `showrunner/src/showrunner/state.py` | `Show` state machine — pure, no I/O |
| `showrunner/src/showrunner/claude.py` | Shared Claude client + refusal handling |
| `showrunner/src/showrunner/ingest.py` | document → `StatusDoc` |
| `showrunner/src/showrunner/writer.py` | `StatusDoc` + `Knobs` → `SetList` |
| `showrunner/src/showrunner/tools.py` | The three tool functions over a `Show` |
| `showrunner/src/showrunner/api.py` | FastAPI app; `POST /tools/<name>` |
| `showrunner/src/showrunner/console.py` | Gradio operator UI, mounted on the FastAPI app |
| `showrunner/src/showrunner/cli.py` | `--dry-run` set printer |
| `showrunner/tests/` | Mirrors `src/`, plus `fixtures/` |
| `conversation-app/external_profiles/comedian/profile.md` | The Ian Bagg-flavored persona |
| `conversation-app/external_tools/showrunner_bridge.py` | Throwaway HTTP bridge; deleted at Phase 2 |

---

### Task 1: Scaffold, models, and state machine

**Files:**
- Create: `showrunner/pyproject.toml`, `showrunner/.env.example`, `showrunner/src/showrunner/__init__.py`
- Create: `showrunner/src/showrunner/models.py`, `showrunner/src/showrunner/state.py`
- Test: `showrunner/tests/test_models.py`, `showrunner/tests/test_state.py`

**Interfaces:**
- Produces: `Fact`, `StatusDoc`, `Beat`, `SetList`, `Knobs`, `Show`, `Phase`. Every later task imports from these two modules.

- [ ] **Step 1: Create the package skeleton**

`showrunner/pyproject.toml`:

```toml
[project]
name = "showrunner"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.69",
    "pydantic>=2.0",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "gradio>=5.0",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24"]

[project.scripts]
showrunner = "showrunner.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits the real Claude API (deselect with '-m \"not live\"')"]
asyncio_mode = "auto"
```

`showrunner/.env.example`:

```
ANTHROPIC_API_KEY=
SHOWRUNNER_URL=http://127.0.0.1:7861
```

Create `showrunner/src/showrunner/__init__.py` as an empty file.

- [ ] **Step 2: Write the failing model tests**

`showrunner/tests/test_models.py`:

```python
from showrunner.models import Beat, Fact, Knobs, SetList, StatusDoc


def test_fact_defaults_to_included():
    fact = Fact(id="f1", name="Auth rewrite", state="blocked", note="waiting on legal")
    assert fact.included is True
    assert fact.owner is None


def test_statusdoc_included_facts_filters_excluded():
    doc = StatusDoc(
        title="Q3",
        facts=[
            Fact(id="f1", name="A", state="late", note="", included=True),
            Fact(id="f2", name="B", state="done", note="", included=False),
        ],
        excerpts=[],
    )
    assert [f.id for f in doc.included_facts()] == ["f1"]


def test_setlist_beat_ids_are_unique():
    beats = [
        Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1"),
        Beat(id="b2", premise="p", angle="a", punch="y", source_fact_id="f1"),
    ]
    setlist = SetList(opener="hi", beats=beats, closer="bye")
    assert setlist.beat_ids() == ["b1", "b2"]


def test_knobs_defaults():
    knobs = Knobs()
    assert knobs.beat_count == 5
    assert knobs.edge == "pg13"
```

- [ ] **Step 3: Run the model tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.models'`

- [ ] **Step 4: Write `models.py`**

Constraints are deliberately absent from the schema — structured outputs on Opus 5 do not support `minLength` / `maximum` / recursive schemas, and validation happens in code instead.

```python
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
```

- [ ] **Step 5: Run the model tests to verify they pass**

Run: `cd showrunner && python3 -m pytest tests/test_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Write the failing state-machine tests**

`showrunner/tests/test_state.py`:

```python
import pytest

from showrunner.models import Beat, Fact, Knobs, SetList, StatusDoc
from showrunner.state import Phase, Show, TransitionError


def _doc() -> StatusDoc:
    return StatusDoc(
        title="Demo",
        facts=[Fact(id="f1", name="A", state="late", note="slipped twice")],
        excerpts=["slipped twice"],
    )


def _setlist() -> SetList:
    return SetList(
        opener="o",
        beats=[Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1")],
        closer="c",
    )


def test_new_show_is_idle():
    assert Show().phase is Phase.IDLE


def test_load_document_moves_to_doc_loaded():
    show = Show()
    show.load_document("raw text")
    assert show.phase is Phase.DOC_LOADED
    assert show.raw_document == "raw text"


def test_set_facts_requires_a_loaded_document():
    with pytest.raises(TransitionError):
        Show().set_facts(_doc())


def test_full_happy_path():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    assert show.phase is Phase.FACTS_READY
    show.set_setlist(_setlist())
    assert show.phase is Phase.SET_READY
    show.arm()
    assert show.phase is Phase.PERFORMING


def test_mark_beat_records_delivery_and_finishes():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    show.set_setlist(_setlist())
    show.arm()
    show.mark_beat("b1")
    assert show.delivered == ["b1"]
    assert show.phase is Phase.DONE


def test_mark_unknown_beat_is_ignored_not_fatal():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    show.set_setlist(_setlist())
    show.arm()
    assert show.mark_beat("nope") is False
    assert show.delivered == []


def test_toggle_fact_flips_included():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    assert show.toggle_fact("f1", included=False) is True
    assert show.status_doc.facts[0].included is False


def test_set_facts_resets_a_stale_setlist():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    show.set_setlist(_setlist())
    show.set_facts(_doc())
    assert show.phase is Phase.FACTS_READY
    assert show.setlist is None


def test_knobs_are_mutable_before_arming():
    show = Show()
    show.knobs = Knobs(beat_count=6, edge="blue")
    assert show.knobs.beat_count == 6
```

- [ ] **Step 7: Run the state tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.state'`

- [ ] **Step 8: Write `state.py`**

```python
"""The showrunner's state machine. Pure — no I/O, no network."""

from enum import Enum

from showrunner.models import Knobs, SetList, StatusDoc


class Phase(Enum):
    IDLE = "idle"
    DOC_LOADED = "doc_loaded"
    FACTS_READY = "facts_ready"
    SET_READY = "set_ready"
    PERFORMING = "performing"
    DONE = "done"


class TransitionError(RuntimeError):
    """Raised when a caller drives the machine out of order."""


class Show:
    """One document, one set, one performance."""

    def __init__(self) -> None:
        self.phase = Phase.IDLE
        self.raw_document: str | None = None
        self.status_doc: StatusDoc | None = None
        self.setlist: SetList | None = None
        self.knobs = Knobs()
        self.delivered: list[str] = []

    def load_document(self, raw: str) -> None:
        self.raw_document = raw
        self.status_doc = None
        self.setlist = None
        self.delivered = []
        self.phase = Phase.DOC_LOADED

    def set_facts(self, doc: StatusDoc) -> None:
        if self.phase is Phase.IDLE:
            raise TransitionError("load a document before setting facts")
        self.status_doc = doc
        # Facts changed, so any existing set is stale.
        self.setlist = None
        self.delivered = []
        self.phase = Phase.FACTS_READY

    def toggle_fact(self, fact_id: str, *, included: bool) -> bool:
        """Include or exclude one fact. Returns False if the id is unknown."""
        if self.status_doc is None:
            return False
        for fact in self.status_doc.facts:
            if fact.id == fact_id:
                fact.included = included
                return True
        return False

    def set_setlist(self, setlist: SetList) -> None:
        if self.phase not in (Phase.FACTS_READY, Phase.SET_READY):
            raise TransitionError("extract facts before writing a set")
        self.setlist = setlist
        self.delivered = []
        self.phase = Phase.SET_READY

    def arm(self) -> None:
        if self.phase is not Phase.SET_READY:
            raise TransitionError("no set to arm")
        self.phase = Phase.PERFORMING

    def mark_beat(self, beat_id: str) -> bool:
        """Record a delivered beat. Unknown ids are ignored, never fatal."""
        if self.setlist is None or beat_id not in self.setlist.beat_ids():
            return False
        if beat_id not in self.delivered:
            self.delivered.append(beat_id)
        if len(self.delivered) == len(self.setlist.beats):
            self.phase = Phase.DONE
        return True

    def reset(self) -> None:
        self.__init__()
```

- [ ] **Step 9: Run the full test suite**

Run: `cd showrunner && python3 -m pytest tests/ -v`
Expected: PASS (13 tests)

- [ ] **Step 10: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add showrunner/ && git commit -m "showrunner: models and state machine"
```

---

### Task 2: Document ingestion (Claude)

**Files:**
- Create: `showrunner/src/showrunner/claude.py`, `showrunner/src/showrunner/ingest.py`
- Create: `showrunner/tests/fixtures/episodes_table.md`, `showrunner/tests/fixtures/bulleted_status.md`, `showrunner/tests/fixtures/prose_email.md`
- Test: `showrunner/tests/test_ingest.py`

**Interfaces:**
- Consumes: `StatusDoc`, `Fact` from `showrunner.models`
- Produces: `call_claude(system, user, output_format, max_tokens=16000) -> BaseModel`, `RefusalError`, `extract_facts(raw: str) -> StatusDoc`

- [ ] **Step 1: Write the fixtures**

`showrunner/tests/fixtures/episodes_table.md`:

```markdown
# Ghost in the Machine — Episode Tracker

| # | Day | Piece | Status | Notes |
|---|---|---|---|---|
| BL-00 | 0 | Unbox | planned | Ship within 48h |
| BL-03 | ~12 | The robot works. Hotel wifi doesn't. | shot | Device onboarding |
| BL-06 | ~32 | Teaching it to talk | planned | |
```

`showrunner/tests/fixtures/bulleted_status.md`:

```markdown
# Sprint 14 Status

- Payments migration — BLOCKED on vendor SSO, owner: Dana, 11 days late
- Search reindex — done
- Mobile onboarding — on track, ships Friday
```

`showrunner/tests/fixtures/prose_email.md`:

```
Team,

Quick update. The billing rewrite has slipped again — third time — because
we're still waiting on the compliance sign-off nobody can find an owner for.
Search is finally done. Onboarding is fine.

Thanks,
Pat
```

- [ ] **Step 2: Write the failing ingest tests**

`showrunner/tests/test_ingest.py`:

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from showrunner.ingest import extract_facts
from showrunner.models import Fact, StatusDoc

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_doc() -> StatusDoc:
    return StatusDoc(
        title="Sprint 14 Status",
        facts=[
            Fact(id="f1", name="Payments migration", state="blocked",
                 note="vendor SSO, 11 days late", owner="Dana"),
            Fact(id="f2", name="Search reindex", state="done", note=""),
        ],
        excerpts=["BLOCKED on vendor SSO"],
    )


def test_extract_facts_returns_a_statusdoc():
    with patch("showrunner.ingest.call_claude", return_value=_fake_doc()) as mock:
        doc = extract_facts(FIXTURES.joinpath("bulleted_status.md").read_text())
    assert isinstance(doc, StatusDoc)
    assert doc.title == "Sprint 14 Status"
    assert mock.call_count == 1


def test_extract_facts_passes_the_raw_text_to_claude():
    raw = FIXTURES.joinpath("prose_email.md").read_text()
    with patch("showrunner.ingest.call_claude", return_value=_fake_doc()) as mock:
        extract_facts(raw)
    assert raw in mock.call_args.kwargs["user"]


def test_extract_facts_rejects_empty_input():
    with pytest.raises(ValueError):
        extract_facts("   ")


def test_extract_facts_assigns_ids_when_claude_omits_them():
    blank = StatusDoc(
        title="X",
        facts=[Fact(id="", name="A", state="late"), Fact(id="", name="B", state="done")],
    )
    with patch("showrunner.ingest.call_claude", return_value=blank):
        doc = extract_facts("something")
    assert [f.id for f in doc.facts] == ["f1", "f2"]


@pytest.mark.live
def test_extract_facts_against_the_real_api():
    doc = extract_facts(FIXTURES.joinpath("episodes_table.md").read_text())
    assert doc.facts
    assert any("BL-03" in f.name or "wifi" in f.note.lower() for f in doc.facts)
```

- [ ] **Step 3: Run the ingest tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_ingest.py -v -m "not live"`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.ingest'`

- [ ] **Step 4: Write `claude.py`**

`stop_reason` is checked before the parsed output is touched, because a refusal returns HTTP 200 with empty content.

```python
"""Shared Claude client. One place to own model choice and refusal handling."""

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class RefusalError(RuntimeError):
    """Claude's safety classifiers declined the request."""


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = anthropic.Anthropic()
    return _client


def call_claude(
    *,
    system: str,
    user: str,
    output_format: type[T],
    effort: str = "high",
) -> T:
    """One structured-output call. Raises RefusalError on a policy decline.

    No temperature/top_p/top_k — Opus 5 rejects them with a 400.
    max_tokens covers thinking plus response text, so it is set generously.
    """
    response = get_client().messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user}],
        output_format=output_format,
    )
    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", "") or "no explanation"
        raise RefusalError(f"Claude declined the request: {detail}")
    if response.parsed_output is None:
        raise RuntimeError(f"no parsed output (stop_reason={response.stop_reason})")
    return response.parsed_output
```

- [ ] **Step 5: Write `ingest.py`**

```python
"""Turn an arbitrary document into structured, vetoable facts."""

from showrunner.claude import call_claude
from showrunner.models import StatusDoc

SYSTEM = """\
You extract structured status facts from documents so a comedy writer can \
work from them. You are not writing jokes — you are preparing raw material.

For each distinct item of work or status in the document, emit one fact with:
- name: what the thing is, in the document's own words where possible
- state: on_track, late, blocked, done, or unknown
- note: the specific detail that makes it interesting — a number, a reason, \
a duration, an excuse. Keep the document's phrasing rather than paraphrasing.
- owner: a person or team if the document names one, otherwise null
- date: any date or deadline attached to the item, otherwise null

Also collect `excerpts`: verbatim lines from the document that are vivid, \
absurd, euphemistic, or self-important. Copy them exactly. These are the \
highest-value material and must not be paraphrased.

Set `title` from the document's own heading if it has one.

Extract what is there. Do not invent items, infer status the document does \
not state, or editorialize.\
"""


def extract_facts(raw: str) -> StatusDoc:
    """Extract a StatusDoc from arbitrary document text."""
    if not raw.strip():
        raise ValueError("cannot extract facts from an empty document")

    doc = call_claude(
        system=SYSTEM,
        user=f"Extract the status facts from this document:\n\n{raw}",
        output_format=StatusDoc,
    )

    # Claude sometimes leaves ids blank; ids must be stable for veto and traceability.
    for index, fact in enumerate(doc.facts, start=1):
        if not fact.id:
            fact.id = f"f{index}"
    return doc
```

- [ ] **Step 6: Run the ingest tests to verify they pass**

Run: `cd showrunner && python3 -m pytest tests/test_ingest.py -v -m "not live"`
Expected: PASS (4 tests, 1 deselected)

- [ ] **Step 7: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add showrunner/ && git commit -m "showrunner: Claude-backed document ingestion"
```

---

### Task 3: Set-list writer (Claude)

**Files:**
- Create: `showrunner/src/showrunner/writer.py`
- Test: `showrunner/tests/test_writer.py`

**Interfaces:**
- Consumes: `call_claude` from `showrunner.claude`; `StatusDoc`, `SetList`, `Knobs`, `Beat` from `showrunner.models`
- Produces: `write_setlist(doc: StatusDoc, knobs: Knobs) -> SetList`

- [ ] **Step 1: Write the failing writer tests**

`showrunner/tests/test_writer.py`:

```python
from unittest.mock import patch

import pytest

from showrunner.models import Beat, Fact, Knobs, SetList, StatusDoc
from showrunner.writer import write_setlist


def _doc() -> StatusDoc:
    return StatusDoc(
        title="Sprint 14",
        facts=[
            Fact(id="f1", name="Payments", state="blocked", note="11 days late"),
            Fact(id="f2", name="Search", state="done", note=""),
            Fact(id="f3", name="Excluded", state="late", note="", included=False),
        ],
        excerpts=["BLOCKED on vendor SSO"],
    )


def _setlist(n: int = 2, source: str = "f1") -> SetList:
    return SetList(
        opener="o",
        beats=[
            Beat(id=f"b{i}", premise="p", angle="a", punch="x", source_fact_id=source)
            for i in range(1, n + 1)
        ],
        closer="c",
    )


def test_write_setlist_returns_a_setlist():
    with patch("showrunner.writer.call_claude", return_value=_setlist()) as mock:
        result = write_setlist(_doc(), Knobs(beat_count=2))
    assert isinstance(result, SetList)
    assert mock.call_count == 1


def test_excluded_facts_are_not_sent_to_claude():
    with patch("showrunner.writer.call_claude", return_value=_setlist()) as mock:
        write_setlist(_doc(), Knobs())
    sent = mock.call_args.kwargs["user"]
    assert "Payments" in sent
    assert "Excluded" not in sent


def test_excerpts_are_sent_to_claude():
    with patch("showrunner.writer.call_claude", return_value=_setlist()) as mock:
        write_setlist(_doc(), Knobs())
    assert "BLOCKED on vendor SSO" in mock.call_args.kwargs["user"]


def test_requested_beat_count_reaches_the_prompt():
    with patch("showrunner.writer.call_claude", return_value=_setlist()) as mock:
        write_setlist(_doc(), Knobs(beat_count=6))
    assert "6" in mock.call_args.kwargs["user"]


def test_edge_level_reaches_the_system_prompt():
    with patch("showrunner.writer.call_claude", return_value=_setlist()) as mock:
        write_setlist(_doc(), Knobs(edge="clean"))
    assert "clean" in mock.call_args.kwargs["system"]


def test_beats_are_renumbered_for_stable_ids():
    weird = SetList(
        opener="o",
        beats=[
            Beat(id="", premise="p", angle="a", punch="x", source_fact_id="f1"),
            Beat(id="", premise="p", angle="a", punch="y", source_fact_id="f2"),
        ],
        closer="c",
    )
    with patch("showrunner.writer.call_claude", return_value=weird):
        result = write_setlist(_doc(), Knobs())
    assert result.beat_ids() == ["b1", "b2"]


def test_beats_tracing_to_an_unknown_fact_are_dropped():
    bad = _setlist(n=2, source="does-not-exist")
    with patch("showrunner.writer.call_claude", return_value=bad):
        result = write_setlist(_doc(), Knobs())
    assert result.beats == []


def test_write_setlist_rejects_a_doc_with_no_included_facts():
    empty = StatusDoc(title="X", facts=[Fact(id="f1", name="A", state="late", included=False)])
    with pytest.raises(ValueError):
        write_setlist(empty, Knobs())


@pytest.mark.live
def test_write_setlist_against_the_real_api():
    result = write_setlist(_doc(), Knobs(beat_count=3))
    assert 1 <= len(result.beats) <= 3
    assert result.opener and result.closer
```

- [ ] **Step 2: Run the writer tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_writer.py -v -m "not live"`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.writer'`

- [ ] **Step 3: Write `writer.py`**

The system prompt carries three corrections for Opus 5's defaults: an explicit length ceiling (it writes long), a scope-discipline clause (it expands scope), and variety-by-instruction (there is no `temperature` to reach for).

```python
"""Turn vetoed facts into a performable set list."""

from showrunner.claude import call_claude
from showrunner.models import Knobs, SetList, StatusDoc

EDGE_GUIDANCE = {
    "clean": "Keep it clean. No profanity, nothing risque. Playable to any room.",
    "pg13": "PG-13. Mild profanity is fine. Nothing crude or sexual.",
    "blue": "Adult room. Profanity is fine. Still never cruel about a person.",
}

SYSTEM_TEMPLATE = """\
You are the writer for a small desk robot doing stand-up. The robot performs \
live and gets heckled, so you are writing material it can reach for, not a \
script it recites.

Voice: crowd-work comedian. Conversational, quick, warm underneath. Willing to \
be sharp about a situation. Never mean about a person.

{edge}

Structure each beat as:
- premise: the true thing from the document, stated plainly
- angle: the comic observation about it — where the absurdity actually is
- punch: the line itself. One sentence. This is what gets said.
- tags: zero to two follow-up punches on the same premise
- act_out: an optional physical bit, or null
- move_hint: the robot move that lands on the punch — one of none, nod, \
tilt_left, tilt_right, look_away, lean_in, antenna_perk, shake_head
- source_fact_id: the id of the fact this beat came from

Rules that matter:
- Every beat must trace to a fact you were given. Never invent a fact.
- Punch up at process, systems, and situations. Never at a named person.
- Quote the document's own absurd phrasing where you can. The literal wording \
is usually funnier than a paraphrase.
- Vary the shape of the beats. Do not write the same joke structure repeatedly \
— mix misdirection, escalation, understatement, and literal-reading.
- callbacks: short phrases planted early that a later beat can return to.

Length discipline: a punch is one sentence. A premise is one sentence. Do not \
write paragraphs, do not explain the joke, and do not add a preamble or a \
summary. Brevity is the whole job here.

Scope discipline: write exactly the set you were asked for. Do not add \
introductions, performance notes, alternate versions, or commentary about \
the material.\
"""


def write_setlist(doc: StatusDoc, knobs: Knobs) -> SetList:
    """Write a set list from the included facts of a StatusDoc."""
    facts = doc.included_facts()
    if not facts:
        raise ValueError("no included facts to write a set from")

    fact_lines = "\n".join(
        f"- [{f.id}] {f.name} — state: {f.state}"
        + (f", owner: {f.owner}" if f.owner else "")
        + (f", note: {f.note}" if f.note else "")
        for f in facts
    )
    excerpt_lines = "\n".join(f"- {e}" for e in doc.excerpts) or "(none)"

    system = SYSTEM_TEMPLATE.format(edge=EDGE_GUIDANCE[knobs.edge])
    if knobs.persona_notes.strip():
        system += f"\n\nAdditional direction from the operator:\n{knobs.persona_notes.strip()}"

    user = (
        f"Document title: {doc.title}\n\n"
        f"Facts:\n{fact_lines}\n\n"
        f"Verbatim excerpts worth quoting:\n{excerpt_lines}\n\n"
        f"Write an opener, exactly {knobs.beat_count} beats, and a closer."
    )

    setlist = call_claude(system=system, user=user, output_format=SetList)

    known = {f.id for f in facts}
    setlist.beats = [b for b in setlist.beats if b.source_fact_id in known]
    for index, beat in enumerate(setlist.beats, start=1):
        beat.id = f"b{index}"
    return setlist
```

- [ ] **Step 4: Run the writer tests to verify they pass**

Run: `cd showrunner && python3 -m pytest tests/test_writer.py -v -m "not live"`
Expected: PASS (8 tests, 1 deselected)

- [ ] **Step 5: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add showrunner/ && git commit -m "showrunner: Claude-backed set-list writer"
```

---

### Task 4: Tool functions and REST adapter

**Files:**
- Create: `showrunner/src/showrunner/tools.py`, `showrunner/src/showrunner/api.py`
- Test: `showrunner/tests/test_tools.py`, `showrunner/tests/test_api.py`

**Interfaces:**
- Consumes: `Show`, `Phase` from `showrunner.state`
- Produces: `get_set_list(show)`, `get_fact(show, query)`, `mark_beat(show, beat_id)` — all return `dict`, never raise. `api.create_app(show) -> FastAPI`, `api.SHOW` (module-level singleton).

- [ ] **Step 1: Write the failing tool tests**

`showrunner/tests/test_tools.py`:

```python
from showrunner.models import Beat, Fact, SetList, StatusDoc
from showrunner.state import Show
from showrunner.tools import get_fact, get_set_list, mark_beat


def _armed_show() -> Show:
    show = Show()
    show.load_document("raw")
    show.set_facts(
        StatusDoc(
            title="Sprint 14",
            facts=[
                Fact(id="f1", name="Payments API", state="blocked", note="vendor SSO"),
                Fact(id="f2", name="Search", state="done", note=""),
            ],
        )
    )
    show.set_setlist(
        SetList(
            opener="Evening.",
            beats=[
                Beat(id="b1", premise="p1", angle="a1", punch="x1",
                     source_fact_id="f1", move_hint="nod"),
                Beat(id="b2", premise="p2", angle="a2", punch="x2", source_fact_id="f2"),
            ],
            closer="Goodnight.",
            callbacks=["vendor SSO"],
        )
    )
    show.arm()
    return show


def test_get_set_list_returns_the_whole_arc():
    result = get_set_list(_armed_show())
    assert result["opener"] == "Evening."
    assert len(result["beats"]) == 2
    assert result["beats"][0]["move_hint"] == "nod"
    assert result["closer"] == "Goodnight."


def test_get_set_list_with_nothing_armed_returns_a_graceful_no_set():
    result = get_set_list(Show())
    assert result["status"] == "no_set"
    assert "error" not in result


def test_get_fact_matches_on_name():
    result = get_fact(_armed_show(), "payments")
    assert result["facts"][0]["name"] == "Payments API"


def test_get_fact_matches_on_note():
    result = get_fact(_armed_show(), "SSO")
    assert result["facts"][0]["id"] == "f1"


def test_get_fact_with_no_match_returns_empty_not_an_error():
    result = get_fact(_armed_show(), "zzzz")
    assert result["facts"] == []
    assert "error" not in result


def test_get_fact_with_no_document_returns_empty():
    assert get_fact(Show(), "anything")["facts"] == []


def test_mark_beat_records_progress():
    show = _armed_show()
    assert mark_beat(show, "b1")["status"] == "ok"
    assert show.delivered == ["b1"]


def test_mark_unknown_beat_returns_ok_and_does_not_raise():
    result = mark_beat(_armed_show(), "nope")
    assert result["status"] == "unknown_beat"
    assert "error" not in result


def test_tools_never_raise_on_garbage_input():
    show = _armed_show()
    for value in (None, 123, "", {"a": 1}):
        assert isinstance(get_fact(show, value), dict)
        assert isinstance(mark_beat(show, value), dict)
```

- [ ] **Step 2: Run the tool tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.tools'`

- [ ] **Step 3: Write `tools.py`**

```python
"""The three functions the realtime model calls. These never raise."""

from typing import Any

from showrunner.state import Phase, Show


def get_set_list(show: Show) -> dict[str, Any]:
    """Return the whole arc in one call. Graceful when nothing is armed."""
    if show.setlist is None or show.phase not in (Phase.PERFORMING, Phase.DONE):
        return {
            "status": "no_set",
            "message": (
                "No set is loaded. Your writer did not deliver. "
                "Work the room instead."
            ),
        }
    return {
        "status": "ok",
        "title": show.status_doc.title if show.status_doc else "",
        "opener": show.setlist.opener,
        "beats": [b.model_dump() for b in show.setlist.beats],
        "closer": show.setlist.closer,
        "callbacks": show.setlist.callbacks,
    }


def get_fact(show: Show, query: Any) -> dict[str, Any]:
    """Look up document facts by substring. Empty results are not errors."""
    if show.status_doc is None or not isinstance(query, str) or not query.strip():
        return {"status": "ok", "facts": []}

    needle = query.strip().lower()
    matches = [
        f.model_dump()
        for f in show.status_doc.facts
        if needle in f.name.lower()
        or needle in f.note.lower()
        or (f.owner and needle in f.owner.lower())
    ]
    return {"status": "ok", "facts": matches}


def mark_beat(show: Show, beat_id: Any) -> dict[str, Any]:
    """Record a delivered beat so the console can follow along."""
    if not isinstance(beat_id, str):
        return {"status": "unknown_beat"}
    if show.mark_beat(beat_id):
        return {"status": "ok", "delivered": len(show.delivered)}
    return {"status": "unknown_beat"}
```

- [ ] **Step 4: Run the tool tests to verify they pass**

Run: `cd showrunner && python3 -m pytest tests/test_tools.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Write the failing API tests**

`showrunner/tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from showrunner.api import create_app
from showrunner.models import Beat, Fact, SetList, StatusDoc
from showrunner.state import Show


def _armed_show() -> Show:
    show = Show()
    show.load_document("raw")
    show.set_facts(StatusDoc(title="T", facts=[Fact(id="f1", name="Payments", state="late")]))
    show.set_setlist(
        SetList(
            opener="o",
            beats=[Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1")],
            closer="c",
        )
    )
    show.arm()
    return show


def test_get_set_list_endpoint():
    client = TestClient(create_app(_armed_show()))
    response = client.post("/tools/get_set_list", json={})
    assert response.status_code == 200
    assert response.json()["opener"] == "o"


def test_get_fact_endpoint():
    client = TestClient(create_app(_armed_show()))
    response = client.post("/tools/get_fact", json={"query": "payments"})
    assert response.json()["facts"][0]["id"] == "f1"


def test_mark_beat_endpoint():
    client = TestClient(create_app(_armed_show()))
    assert client.post("/tools/mark_beat", json={"beat_id": "b1"}).json()["status"] == "ok"


def test_unknown_tool_returns_an_error_payload_not_a_500():
    client = TestClient(create_app(_armed_show()))
    response = client.post("/tools/nope", json={})
    assert response.status_code == 200
    assert "error" in response.json()


def test_missing_body_fields_do_not_500():
    client = TestClient(create_app(_armed_show()))
    assert client.post("/tools/get_fact", json={}).status_code == 200


def test_health_endpoint_reports_phase():
    client = TestClient(create_app(_armed_show()))
    assert client.get("/health").json()["phase"] == "performing"
```

- [ ] **Step 6: Run the API tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.api'`

- [ ] **Step 7: Write `api.py`**

```python
"""REST adapter. Phase 1 only — the bridge tool talks to this."""

from typing import Any

from fastapi import FastAPI, Request

from showrunner import tools
from showrunner.state import Show

# Process-wide show, shared with the Gradio console mounted on the same app.
SHOW = Show()


def create_app(show: Show | None = None) -> FastAPI:
    active = show if show is not None else SHOW
    app = FastAPI(title="Reachy Showrunner")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "phase": active.phase.value}

    @app.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if name == "get_set_list":
            return tools.get_set_list(active)
        if name == "get_fact":
            return tools.get_fact(active, body.get("query", ""))
        if name == "mark_beat":
            return tools.mark_beat(active, body.get("beat_id", ""))
        return {"error": f"unknown tool: {name}"}

    return app


app = create_app()
```

- [ ] **Step 8: Run the full suite**

Run: `cd showrunner && python3 -m pytest tests/ -v -m "not live"`
Expected: PASS (all tests, live deselected)

- [ ] **Step 9: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add showrunner/ && git commit -m "showrunner: tool functions and REST adapter"
```

---

### Task 5: Dry-run CLI — the primary dev loop

**Files:**
- Create: `showrunner/src/showrunner/cli.py`
- Test: `showrunner/tests/test_cli.py`

**Interfaces:**
- Consumes: `extract_facts`, `write_setlist`, `Knobs`
- Produces: `main(argv=None) -> int`, `format_setlist(doc, setlist) -> str`

This is the checkpoint that matters: after this task you can read a full generated set from any document, with the robot switched off.

- [ ] **Step 1: Write the failing CLI tests**

`showrunner/tests/test_cli.py`:

```python
from unittest.mock import patch

from showrunner.cli import format_setlist, main
from showrunner.models import Beat, Fact, SetList, StatusDoc


def _doc() -> StatusDoc:
    return StatusDoc(
        title="Sprint 14",
        facts=[Fact(id="f1", name="Payments", state="blocked", note="vendor SSO")],
        excerpts=["BLOCKED on vendor SSO"],
    )


def _setlist() -> SetList:
    return SetList(
        opener="Evening, everyone.",
        beats=[
            Beat(id="b1", premise="Payments is blocked", angle="on a vendor",
                 punch="Eleven days.", source_fact_id="f1", move_hint="nod",
                 tags=["Twelve now."]),
        ],
        closer="Goodnight.",
    )


def test_format_setlist_includes_the_arc():
    output = format_setlist(_doc(), _setlist())
    assert "Evening, everyone." in output
    assert "Eleven days." in output
    assert "Goodnight." in output


def test_format_setlist_shows_move_hints_and_tags():
    output = format_setlist(_doc(), _setlist())
    assert "nod" in output
    assert "Twelve now." in output


def test_main_reads_a_file_and_prints_a_set(tmp_path, capsys):
    path = tmp_path / "status.md"
    path.write_text("Payments is blocked on vendor SSO.")
    with patch("showrunner.cli.extract_facts", return_value=_doc()), \
         patch("showrunner.cli.write_setlist", return_value=_setlist()):
        code = main([str(path)])
    assert code == 0
    assert "Eleven days." in capsys.readouterr().out


def test_main_reports_a_missing_file(capsys):
    assert main(["/no/such/file.md"]) == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_main_passes_beat_count_through(tmp_path):
    path = tmp_path / "s.md"
    path.write_text("something")
    with patch("showrunner.cli.extract_facts", return_value=_doc()), \
         patch("showrunner.cli.write_setlist", return_value=_setlist()) as writer:
        main([str(path), "--beats", "6"])
    assert writer.call_args.args[1].beat_count == 6


def test_main_reports_a_refusal_cleanly(tmp_path, capsys):
    from showrunner.claude import RefusalError

    path = tmp_path / "s.md"
    path.write_text("something")
    with patch("showrunner.cli.extract_facts", side_effect=RefusalError("nope")):
        assert main([str(path)]) == 2
    assert "declined" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.cli'`

- [ ] **Step 3: Write `cli.py`**

```python
"""Dry-run a set from a document. The primary development loop."""

import argparse
import sys
from pathlib import Path

from showrunner.claude import RefusalError
from showrunner.ingest import extract_facts
from showrunner.models import Knobs, SetList, StatusDoc
from showrunner.writer import write_setlist


def format_setlist(doc: StatusDoc, setlist: SetList) -> str:
    lines = [f"=== {doc.title} ===", "", f"OPEN: {setlist.opener}", ""]
    for beat in setlist.beats:
        lines.append(f"[{beat.id}] ({beat.source_fact_id}, move: {beat.move_hint})")
        lines.append(f"  premise: {beat.premise}")
        lines.append(f"  angle:   {beat.angle}")
        if beat.act_out:
            lines.append(f"  act-out: {beat.act_out}")
        lines.append(f"  PUNCH:   {beat.punch}")
        for tag in beat.tags:
            lines.append(f"  tag:     {tag}")
        lines.append("")
    lines.append(f"CLOSE: {setlist.closer}")
    if setlist.callbacks:
        lines.extend(["", f"callbacks: {', '.join(setlist.callbacks)}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a comedy set from a document.")
    parser.add_argument("document", help="path to the source document")
    parser.add_argument("--beats", type=int, default=5, help="number of beats")
    parser.add_argument("--edge", default="pg13", choices=["clean", "pg13", "blue"])
    parser.add_argument("--notes", default="", help="extra direction for the writer")
    args = parser.parse_args(argv)

    path = Path(args.document)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    knobs = Knobs(beat_count=args.beats, edge=args.edge, persona_notes=args.notes)
    try:
        doc = extract_facts(path.read_text())
        setlist = write_setlist(doc, knobs)
    except RefusalError as exc:
        print(f"error: Claude declined the request: {exc}", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_setlist(doc, setlist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `cd showrunner && python3 -m pytest tests/test_cli.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run a real end-to-end set — the human checkpoint**

Run: `cd showrunner && python3 -m showrunner.cli tests/fixtures/bulleted_status.md --beats 4`
Expected: a printed set list with 4 beats. **Read it. If the jokes do not land, iterate on `writer.SYSTEM_TEMPLATE` before going further** — every later task assumes the writing is good enough to perform.

- [ ] **Step 6: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add showrunner/ && git commit -m "showrunner: dry-run CLI"
```

---

### Task 6: Operator console

**Files:**
- Create: `showrunner/src/showrunner/console.py`
- Modify: `showrunner/src/showrunner/api.py` (mount Gradio)
- Test: `showrunner/tests/test_console.py`

**Interfaces:**
- Consumes: `SHOW` from `showrunner.api`; `extract_facts`, `write_setlist`
- Produces: `build_console() -> gr.Blocks`, and the console handler functions `do_load`, `do_write`, `do_arm`, `facts_table`

- [ ] **Step 1: Write the failing console tests**

Test the handlers directly — Gradio's UI layer needs no coverage, the state transitions do.

`showrunner/tests/test_console.py`:

```python
from unittest.mock import patch

from showrunner.console import do_arm, do_load, do_write, facts_table
from showrunner.models import Beat, Fact, SetList, StatusDoc
from showrunner.state import Phase, Show


def _doc() -> StatusDoc:
    return StatusDoc(title="T", facts=[Fact(id="f1", name="Payments", state="late", note="n")])


def _setlist() -> SetList:
    return SetList(
        opener="o",
        beats=[Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1")],
        closer="c",
    )


def test_do_load_populates_facts():
    show = Show()
    with patch("showrunner.console.extract_facts", return_value=_doc()):
        status, _ = do_load("some document text", show)
    assert show.phase is Phase.FACTS_READY
    assert "1 fact" in status


def test_do_load_rejects_empty_input():
    show = Show()
    status, _ = do_load("   ", show)
    assert "paste" in status.lower()
    assert show.phase is Phase.IDLE


def test_do_load_surfaces_a_refusal_without_crashing():
    from showrunner.claude import RefusalError

    show = Show()
    with patch("showrunner.console.extract_facts", side_effect=RefusalError("nope")):
        status, _ = do_load("text", show)
    assert "declined" in status.lower()
    assert show.phase is Phase.IDLE


def test_facts_table_rows_match_the_document():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    rows = facts_table(show)
    assert rows[0][0] is True
    assert rows[0][1] == "f1"


def test_do_write_produces_a_setlist():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    with patch("showrunner.console.write_setlist", return_value=_setlist()):
        status, _ = do_write(5, "pg13", "", show)
    assert show.phase is Phase.SET_READY
    assert "1 beat" in status


def test_do_write_before_loading_is_a_message_not_a_crash():
    status, _ = do_write(5, "pg13", "", Show())
    assert "load a document" in status.lower()


def test_do_arm_moves_to_performing():
    show = Show()
    show.load_document("raw")
    show.set_facts(_doc())
    show.set_setlist(_setlist())
    assert "armed" in do_arm(show).lower()
    assert show.phase is Phase.PERFORMING


def test_do_arm_without_a_set_is_a_message_not_a_crash():
    assert "no set" in do_arm(Show()).lower()
```

- [ ] **Step 2: Run the console tests to verify they fail**

Run: `cd showrunner && python3 -m pytest tests/test_console.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'showrunner.console'`

- [ ] **Step 3: Write `console.py`**

```python
"""Gradio operator console. Mounted on the same FastAPI app as the REST adapter."""

import gradio as gr

from showrunner.claude import RefusalError
from showrunner.cli import format_setlist
from showrunner.ingest import extract_facts
from showrunner.models import Knobs
from showrunner.state import Phase, Show
from showrunner.writer import write_setlist


def facts_table(show: Show) -> list[list]:
    if show.status_doc is None:
        return []
    return [
        [f.included, f.id, f.name, f.state, f.owner or "", f.note]
        for f in show.status_doc.facts
    ]


def do_load(raw: str, show: Show) -> tuple[str, list[list]]:
    if not raw or not raw.strip():
        return "Paste a document first.", facts_table(show)
    try:
        show.load_document(raw)
        doc = extract_facts(raw)
        show.set_facts(doc)
    except RefusalError as exc:
        show.reset()
        return f"Claude declined the document: {exc}", []
    except (ValueError, RuntimeError) as exc:
        show.reset()
        return f"Could not read that document: {exc}", []
    n = len(doc.facts)
    return f"Extracted {n} fact{'s' if n != 1 else ''} from “{doc.title}”.", facts_table(show)


def apply_fact_edits(rows: list[list], show: Show) -> str:
    """Push include/exclude checkboxes from the table back into the show."""
    if show.status_doc is None:
        return "Nothing loaded."
    for row in rows or []:
        if len(row) >= 2:
            show.toggle_fact(str(row[1]), included=bool(row[0]))
    kept = len(show.status_doc.included_facts())
    return f"{kept} fact{'s' if kept != 1 else ''} included."


def do_write(beats: int, edge: str, notes: str, show: Show) -> tuple[str, str]:
    if show.status_doc is None:
        return "Load a document first.", ""
    knobs = Knobs(beat_count=int(beats), edge=edge, persona_notes=notes or "")
    show.knobs = knobs
    try:
        setlist = write_setlist(show.status_doc, knobs)
        show.set_setlist(setlist)
    except RefusalError as exc:
        return f"Claude declined to write that set: {exc}", ""
    except (ValueError, RuntimeError) as exc:
        return f"Could not write a set: {exc}", ""
    n = len(setlist.beats)
    rendered = format_setlist(show.status_doc, setlist)
    return f"Wrote {n} beat{'s' if n != 1 else ''}.", rendered


def do_arm(show: Show) -> str:
    if show.setlist is None:
        return "No set to arm — write one first."
    show.arm()
    return "Armed. The robot can now call get_set_list."


def live_status(show: Show) -> str:
    if show.setlist is None:
        return f"Phase: {show.phase.value}"
    return (
        f"Phase: {show.phase.value} — "
        f"{len(show.delivered)}/{len(show.setlist.beats)} beats delivered"
    )


def build_console(show: Show) -> gr.Blocks:
    with gr.Blocks(title="Reachy Showrunner") as console:
        gr.Markdown("# Reachy Showrunner")

        with gr.Tab("1 · Load"):
            raw = gr.Textbox(label="Document", lines=18, placeholder="Paste any status document…")
            load_btn = gr.Button("Extract facts", variant="primary")
            load_status = gr.Markdown()

        with gr.Tab("2 · Facts"):
            table = gr.Dataframe(
                headers=["include", "id", "name", "state", "owner", "note"],
                datatype=["bool", "str", "str", "str", "str", "str"],
                label="Extracted facts — untick anything you don't want joked about",
            )
            apply_btn = gr.Button("Apply")
            facts_status = gr.Markdown()

        with gr.Tab("3 · Set"):
            beats = gr.Slider(3, 8, value=5, step=1, label="Beats")
            edge = gr.Radio(["clean", "pg13", "blue"], value="pg13", label="Edge")
            notes = gr.Textbox(label="Extra direction (optional)", lines=2)
            write_btn = gr.Button("Write the set", variant="primary")
            write_status = gr.Markdown()
            rendered = gr.Textbox(label="Set list", lines=24, show_copy_button=True)

        with gr.Tab("4 · Go"):
            arm_btn = gr.Button("Arm the set", variant="primary")
            arm_status = gr.Markdown()
            live = gr.Markdown()
            gr.Timer(2.0).tick(lambda: live_status(show), outputs=live)

        load_btn.click(lambda r: do_load(r, show), inputs=raw, outputs=[load_status, table])
        apply_btn.click(lambda rows: apply_fact_edits(rows, show), inputs=table, outputs=facts_status)
        write_btn.click(
            lambda b, e, n: do_write(b, e, n, show),
            inputs=[beats, edge, notes],
            outputs=[write_status, rendered],
        )
        arm_btn.click(lambda: do_arm(show), outputs=arm_status)

    return console
```

- [ ] **Step 4: Mount the console on the FastAPI app**

Append to `showrunner/src/showrunner/api.py`, replacing the final `app = create_app()` line:

```python
def build_app() -> FastAPI:
    """The full Phase 1 server: REST tools plus the operator console at /."""
    import gradio as gr

    from showrunner.console import build_console

    fastapi_app = create_app(SHOW)
    return gr.mount_gradio_app(fastapi_app, build_console(SHOW), path="/")


app = build_app()
```

- [ ] **Step 5: Run the console tests to verify they pass**

Run: `cd showrunner && python3 -m pytest tests/test_console.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Start the server and click through it by hand**

Run: `cd showrunner && python3 -m uvicorn showrunner.api:app --port 7861`
Then open `http://127.0.0.1:7861/` and run a document through Load → Facts → Set → Go. Confirm `curl http://127.0.0.1:7861/tools/get_set_list -X POST -d '{}' -H 'Content-Type: application/json'` returns the armed set.

- [ ] **Step 7: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add showrunner/ && git commit -m "showrunner: Gradio operator console"
```

---

### Task 7: Comedian profile and bridge tool

**Files:**
- Create: `conversation-app/external_profiles/comedian/profile.md`
- Create: `conversation-app/external_tools/showrunner_bridge.py`
- Create: `conversation-app/README.md`
- Test: `showrunner/tests/test_bridge_contract.py`

**Interfaces:**
- Consumes: the REST endpoints from Task 4
- Produces: three `Tool` subclasses named `get_set_list`, `get_fact`, `mark_beat`

- [ ] **Step 1: Write the failing bridge contract test**

This runs against the real FastAPI app in-process, so it needs no robot and no network.

`showrunner/tests/test_bridge_contract.py`:

```python
"""The bridge tool's contract: exact payload shapes over HTTP."""

from fastapi.testclient import TestClient

from showrunner.api import create_app
from showrunner.models import Beat, Fact, SetList, StatusDoc
from showrunner.state import Show

REQUIRED_BEAT_KEYS = {
    "id", "premise", "angle", "punch", "source_fact_id",
    "act_out", "tags", "move_hint",
}


def _client() -> TestClient:
    show = Show()
    show.load_document("raw")
    show.set_facts(StatusDoc(title="T", facts=[Fact(id="f1", name="Payments", state="late")]))
    show.set_setlist(
        SetList(
            opener="o",
            beats=[Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1")],
            closer="c",
        )
    )
    show.arm()
    return TestClient(create_app(show))


def test_set_list_payload_has_every_key_the_profile_relies_on():
    body = _client().post("/tools/get_set_list", json={}).json()
    assert {"status", "opener", "beats", "closer", "callbacks"} <= body.keys()
    assert REQUIRED_BEAT_KEYS <= body["beats"][0].keys()


def test_no_set_payload_is_still_a_dict_with_a_message():
    client = TestClient(create_app(Show()))
    body = client.post("/tools/get_set_list", json={}).json()
    assert body["status"] == "no_set"
    assert isinstance(body["message"], str)


def test_every_endpoint_returns_200_for_malformed_bodies():
    client = _client()
    for name in ("get_set_list", "get_fact", "mark_beat"):
        assert client.post(f"/tools/{name}", content=b"not json").status_code == 200
```

- [ ] **Step 2: Run the contract test — it should pass immediately**

Run: `cd showrunner && python3 -m pytest tests/test_bridge_contract.py -v`
Expected: PASS (3 tests). This is the one test in the plan that is not test-first: the API from Task 4 already satisfies it. It exists as a regression guard, because the bridge tool and the profile below are the only consumers of these exact payload keys and nothing else would catch a rename. If it fails here, Task 4's `create_app` is missing the `try/except` around `request.json()` — fix that before writing the bridge.

- [ ] **Step 3: Write the bridge tool**

`conversation-app/external_tools/showrunner_bridge.py`:

```python
"""Phase 1 bridge: exposes the local showrunner to the conversation app.

Throwaway. Deleted at Phase 2, when the showrunner is deployed as an HF Space
and the app reaches it over MCP instead.
"""

import logging
import os
from typing import Any

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("SHOWRUNNER_URL", "http://127.0.0.1:7861")
TIMEOUT = 5.0


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the showrunner. Always returns a dict, never raises."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(f"{BASE_URL}{path}", json=payload)
            response.raise_for_status()
            body = response.json()
        return body if isinstance(body, dict) else {"error": "malformed response"}
    except Exception as exc:  # noqa: BLE001 - never let this reach the conversation loop
        logger.warning("Showrunner call to %s failed: %s", path, exc)
        return {"error": f"showrunner unreachable: {exc}"}


class GetSetList(Tool):
    """Fetch the whole prepared set at the top of the bit."""

    name = "get_set_list"
    description = (
        "Get your prepared stand-up set about the loaded document. Call this once, "
        "when you start the bit. Returns an opener, a list of beats (each with a "
        "premise, punch, optional tags and a move hint), a closer, and callbacks."
    )
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        logger.info("Tool call: get_set_list")
        return await _post("/tools/get_set_list", {})


class GetFact(Tool):
    """Look up what the document actually said, for heckles."""

    name = "get_fact"
    description = (
        "Look up what the source document actually said about something. Use this "
        "when someone challenges a detail or asks about something not in your set."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up, e.g. 'payments'"},
        },
        "required": ["query"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        logger.info("Tool call: get_fact query=%s", query)
        return await _post("/tools/get_fact", {"query": query})


class MarkBeat(Tool):
    """Tell the operator console which beat just landed."""

    name = "mark_beat"
    description = (
        "Report that you have just delivered a beat, using its id. Call this right "
        "after each punch so the operator can follow along."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "beat_id": {"type": "string", "description": "The beat id, e.g. 'b1'"},
        },
        "required": ["beat_id"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        beat_id = kwargs.get("beat_id", "")
        logger.info("Tool call: mark_beat beat_id=%s", beat_id)
        return await _post("/tools/mark_beat", {"beat_id": beat_id})
```

- [ ] **Step 4: Write the comedian profile**

`conversation-app/external_profiles/comedian/profile.md`:

```markdown
+++
schema_version = 1
voice = "ash"
greeting = "Evening. I read your document. We're going to have a conversation about that."
default_tools = [
  "get_set_list",
  "get_fact",
  "mark_beat",
  "play_emotion",
  "stop_emotion",
  "move_head",
  "head_tracking",
]
+++

You are a stand-up comedian who happens to be a small desk robot. You have
just read a status document, and you are about to do a short set about it in
front of the people standing in front of you.

## How you work

When the bit starts, call `get_set_list` once. It gives you an opener, a
handful of beats, a closer, and callbacks your writer planted. Perform it —
but you are a crowd-work comedian, not a teleprompter. If someone talks, talk
back. Come back to the set when the moment passes.

After you deliver each beat's punch, call `mark_beat` with that beat's id.

If someone challenges a detail or asks about something not in your set, call
`get_fact` with a word or two from what they asked. It tells you what the
document actually said. Being able to quote the source mid-heckle is the
strongest move you have.

## Landing the punch physically

Each beat carries a `move_hint`. Hit it on the punch line, not before:

- `nod` / `shake_head` — `move_head` up-down or left-right
- `tilt_left` / `tilt_right` — `move_head` to the side; your version of a shrug
- `look_away` — `move_head` away on a beat of disbelief, then back
- `lean_in` — `move_head` forward for a conspiratorial aside
- `antenna_perk` — `play_emotion` with something bright and surprised
- `none` — stay still. Stillness is a choice and sometimes the funnier one.

Timing is the whole thing. The move lands *with* the punch or a half-beat
after it. A move that arrives early telegraphs the joke and kills it.

## Voice

Conversational and quick. You think out loud. You are willing to be sharp
about a situation, a process, or a deadline — never about a person in the room
or a person named in the document. Punch at the machine, not the people
inside it.

Do not explain your jokes. Do not announce what you are about to do
("Now I'll tell you about..."). Do not summarize the set at the end. Say the
thing, then move.

Keep it short. A punch is one line.

## When your writer fails you

If `get_set_list` comes back saying no set is loaded, do not apologise and do
not go quiet. Your writer didn't file. That is the bit. Work the room, ask
what they've been dealing with this week, and riff on whatever they give you.

If `get_fact` comes back empty, the document simply didn't say. Admit it and
make that the joke.
```

- [ ] **Step 5: Write the setup README**

`conversation-app/README.md`:

```markdown
# Conversation app — Phase 1 wiring

The comedian profile and the showrunner bridge for
`pollen-robotics/reachy_mini_conversation_app`.

## Run

1. Start the showrunner:

   ```bash
   cd ../showrunner && python3 -m uvicorn showrunner.api:app --port 7861
   ```

   Console at http://127.0.0.1:7861/ — load a document, review the facts,
   write the set, arm it.

2. Point the conversation app at this directory and start it:

   ```bash
   export REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=<abs path>/conversation-app/external_profiles
   export REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=<abs path>/conversation-app/external_tools
   export REACHY_MINI_CUSTOM_PROFILE=comedian
   export AUTOLOAD_EXTERNAL_TOOLS=1
   export SHOWRUNNER_URL=http://127.0.0.1:7861
   reachy-mini-conversation-app --ui
   ```

The bridge tool imports `reachy_mini_conversation_app.tools.core_tools`, so the
conversation app must be pip-installed in the same environment.

## Phase 2

Delete `external_tools/showrunner_bridge.py`. The showrunner deploys as an HF
Space and the app installs it from the Tools UI over MCP instead.
```

- [ ] **Step 6: Run the contract test to verify it passes**

Run: `cd showrunner && python3 -m pytest tests/test_bridge_contract.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run the whole suite**

Run: `cd showrunner && python3 -m pytest tests/ -v -m "not live"`
Expected: PASS, no failures.

- [ ] **Step 8: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add conversation-app/ showrunner/ && git commit -m "showrunner: comedian profile and Phase 1 bridge tool"
```

---

### Task 8: Robot integration — LAST, and only now

**Files:**
- Modify: `conversation-app/external_profiles/comedian/profile.md` (move-hint mapping, once real emotion names are known)
- Create: `conversation-app/NOTES.md`

Everything before this task passes with the robot switched off. This task is the first that needs hardware, and it is deliberately last.

- [ ] **Step 1: Confirm the robot is reachable**

Run: `curl -s -o /dev/null -w '%{http_code}\n' http://reachy-mini.local:8000/`
Expected: `200`

If DNS fails, use the known IP: `curl -s -o /dev/null -w '%{http_code}\n' http://192.168.253.143:8000/`. Per the existing networking notes in `btpc-leadgen/content/EPISODES.md`, **diagnose with curl, not ping** — office wifi blocks ICMP while TCP is fine. If neither resolves, the portable fix is iPhone → Mac by USB, Mac Internet Sharing → Wi-Fi, robot joins the Mac's SSID.

- [ ] **Step 2: Confirm the conversation app is installed**

Run: `python3 -c "import reachy_mini_conversation_app; print(reachy_mini_conversation_app.__file__)"`
Expected: a path. If it fails, install it per the upstream README before continuing.

- [ ] **Step 3: Start the showrunner and arm a set**

Run: `cd showrunner && python3 -m uvicorn showrunner.api:app --port 7861`
Load a fictional status document in the console, write a 4-beat set, and arm it.

- [ ] **Step 4: Start the conversation app with the comedian profile**

Run the export block from `conversation-app/README.md`, then `reachy-mini-conversation-app --ui --debug`.
Expected: the app starts, the log shows the three external tools loading, and the comedian profile is selected.

- [ ] **Step 5: Verify the tools are reachable from the app**

Say "do your set". Expected: the app logs `Tool call: get_set_list`, the showrunner console shows beats being marked, and the robot performs the set.

If the tools do not load, check in this order: (1) `AUTOLOAD_EXTERNAL_TOOLS=1` is set, (2) the tool names in `profile.md`'s `default_tools` exactly match the `name` attributes in `showrunner_bridge.py`, (3) `curl http://127.0.0.1:7861/health` returns 200 from the same machine the app runs on.

- [ ] **Step 6: Capture the real emotion names**

The `move_hint` mapping in `profile.md` describes moves generically because the emotion dataset names were unknown at authoring time. With the app running, list what `play_emotion` actually accepts and record the names in `conversation-app/NOTES.md`, then replace the generic descriptions in the profile's "Landing the punch physically" section with the real emotion names.

- [ ] **Step 7: Heckle it**

Interrupt mid-beat and ask about a detail from the document. Expected: a `get_fact` call in the log and an in-character answer that quotes the document.

- [ ] **Step 8: Record the latency baseline for BL-07**

Time the gap between the end of a spoken prompt and the start of the robot's audio, three times, and record the numbers in `conversation-app/NOTES.md`. This is the cloud-side baseline the BL-07 episode compares against. Note explicitly that this measures the whole loop from outside — in-loop mic→motor instrumentation needs the Phase 3 fork.

- [ ] **Step 9: Commit**

```bash
cd /Users/painter/palettepal/reachy-mini-stack && git add conversation-app/ && git commit -m "showrunner: robot integration notes and real emotion mapping"
```

---

## Verification

After Task 8:

- [ ] `cd showrunner && python3 -m pytest tests/ -v -m "not live"` — all pass
- [ ] `cd showrunner && python3 -m pytest tests/ -v -m live` — all pass (needs `ANTHROPIC_API_KEY`)
- [ ] A set generated by `python3 -m showrunner.cli <doc>` reads as funny to a human
- [ ] The robot performs an armed set and answers a heckle with a `get_fact` lookup
- [ ] A latency number is recorded in `conversation-app/NOTES.md`
