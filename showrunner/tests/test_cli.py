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
