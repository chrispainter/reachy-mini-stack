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
