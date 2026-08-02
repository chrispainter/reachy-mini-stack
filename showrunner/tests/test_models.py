from showrunner.models import Beat, Fact, Knobs, SetList, StatusDoc


def test_fact_defaults_to_included():
    fact = Fact(id="f1", name="Auth rewrite", state="blocked", note="waiting on legal")
    assert fact.included is True
    assert fact.owner is None


def test_statusdoc_included_facts_filters_excluded():
    doc = StatusDoc(
        title="Q3",
        facts=[
            Fact(id="f1", name="A", state="late", note="", included=True),
            Fact(id="f2", name="B", state="done", note="", included=False),
        ],
        excerpts=[],
    )
    assert [f.id for f in doc.included_facts()] == ["f1"]


def test_setlist_beat_ids_are_unique():
    beats = [
        Beat(id="b1", premise="p", angle="a", punch="x", source_fact_id="f1"),
        Beat(id="b2", premise="p", angle="a", punch="y", source_fact_id="f1"),
    ]
    setlist = SetList(opener="hi", beats=beats, closer="bye")
    assert setlist.beat_ids() == ["b1", "b2"]


def test_knobs_defaults():
    knobs = Knobs()
    assert knobs.beat_count == 5
    assert knobs.edge == "pg13"
