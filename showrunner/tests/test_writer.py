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


def test_a_single_beat_tracing_to_an_unknown_fact_is_dropped():
    mixed = SetList(
        opener="o",
        beats=[
            Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1"),
            Beat(id="b2", premise="p", angle="a", punch="y", source_fact_id="ghost"),
        ],
        closer="c",
    )
    with patch("showrunner.writer.call_claude", return_value=mixed):
        result = write_setlist(_doc(), Knobs())
    assert [b.source_fact_id for b in result.beats] == ["f1"]


def test_all_beats_tracing_to_unknown_facts_raises_rather_than_going_silent():
    bad = _setlist(n=2, source="does-not-exist")
    with patch("showrunner.writer.call_claude", return_value=bad):
        with pytest.raises(RuntimeError, match="unknown fact id"):
            write_setlist(_doc(), Knobs())


def test_write_setlist_rejects_a_doc_with_no_included_facts():
    empty = StatusDoc(title="X", facts=[Fact(id="f1", name="A", state="late", included=False)])
    with pytest.raises(ValueError):
        write_setlist(empty, Knobs())


@pytest.mark.live
def test_write_setlist_against_the_real_api():
    """Assert the invariants, not the beat count — this call is sampled."""
    doc = _doc()
    result = write_setlist(doc, Knobs(beat_count=3))
    assert result.opener and result.closer
    assert result.beats
    included = {f.id for f in doc.included_facts()}
    assert all(b.source_fact_id in included for b in result.beats)
    assert all(b.punch.strip() for b in result.beats)
    assert result.beat_ids() == [f"b{i}" for i in range(1, len(result.beats) + 1)]
