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
