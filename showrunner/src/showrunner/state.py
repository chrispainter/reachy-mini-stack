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
