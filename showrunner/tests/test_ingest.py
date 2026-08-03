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
    # The extractor chooses which field each detail lands in, and reuses the
    # document's own ids when it has them (BL-03 rather than f2). Assert on the
    # whole record — pinning a detail to one field tests the extractor's
    # layout choices, not whether it read the document.
    blob = " ".join(f.model_dump_json() for f in doc.facts).lower()
    assert "bl-03" in blob
    assert "wifi" in blob
