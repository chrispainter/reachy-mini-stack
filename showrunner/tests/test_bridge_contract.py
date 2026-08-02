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
