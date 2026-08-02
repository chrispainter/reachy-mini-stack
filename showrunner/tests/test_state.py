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
