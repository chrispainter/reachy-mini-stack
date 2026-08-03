"""Operator endpoints — the scriptable path used for robot testing."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from showrunner.api import create_app
from showrunner.claude import RefusalError
from showrunner.models import Beat, Fact, SetList, StatusDoc
from showrunner.state import Phase, Show


def _doc() -> StatusDoc:
    return StatusDoc(
        title="Sprint 14",
        facts=[Fact(id="f1", name="Payments", state="blocked", note="11 days late")],
        excerpts=["BLOCKED on vendor SSO"],
    )


def _setlist() -> SetList:
    return SetList(
        opener="o",
        beats=[Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1")],
        closer="c",
    )


def test_load_extracts_and_returns_facts():
    show = Show()
    client = TestClient(create_app(show))
    with patch("showrunner.api.extract_facts", return_value=_doc()):
        body = client.post("/operator/load", json={"document": "text"}).json()
    assert body["status"] == "ok"
    assert body["facts"][0]["id"] == "f1"
    assert show.phase is Phase.FACTS_READY


def test_load_requires_a_document():
    client = TestClient(create_app(Show()))
    assert "error" in client.post("/operator/load", json={}).json()


def test_load_surfaces_a_refusal_as_an_error_payload():
    show = Show()
    client = TestClient(create_app(show))
    with patch("showrunner.api.extract_facts", side_effect=RefusalError("nope")):
        body = client.post("/operator/load", json={"document": "text"}).json()
    assert "declined" in body["error"]
    assert show.phase is Phase.IDLE


def test_write_before_load_is_an_error_not_a_crash():
    client = TestClient(create_app(Show()))
    assert client.post("/operator/write", json={}).json()["error"] == "load a document first"


def test_full_load_write_arm_sequence():
    show = Show()
    client = TestClient(create_app(show))
    with patch("showrunner.api.extract_facts", return_value=_doc()):
        client.post("/operator/load", json={"document": "text"})
    with patch("showrunner.api.write_setlist", return_value=_setlist()):
        write = client.post("/operator/write", json={"beat_count": 4, "edge": "pg13"}).json()
    assert write["beats"] == 1
    arm = client.post("/operator/arm").json()
    assert arm["phase"] == "performing"
    # The robot-facing tool now returns the armed set.
    assert client.post("/tools/get_set_list", json={}).json()["status"] == "ok"


def test_arm_without_a_set_is_an_error():
    client = TestClient(create_app(Show()))
    assert "error" in client.post("/operator/arm").json()


def test_reset_returns_to_idle():
    show = Show()
    client = TestClient(create_app(show))
    with patch("showrunner.api.extract_facts", return_value=_doc()):
        client.post("/operator/load", json={"document": "text"})
    assert client.post("/operator/reset").json()["phase"] == "idle"


def test_write_honours_the_requested_beat_count():
    show = Show()
    client = TestClient(create_app(show))
    with patch("showrunner.api.extract_facts", return_value=_doc()):
        client.post("/operator/load", json={"document": "text"})
    with patch("showrunner.api.write_setlist", return_value=_setlist()) as writer:
        client.post("/operator/write", json={"beat_count": 7})
    assert writer.call_args.args[1].beat_count == 7
