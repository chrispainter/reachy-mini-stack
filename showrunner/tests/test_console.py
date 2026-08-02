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
