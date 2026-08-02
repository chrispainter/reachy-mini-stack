"""Turn an arbitrary document into structured, vetoable facts."""

from showrunner.claude import call_claude
from showrunner.models import StatusDoc

SYSTEM = """\
You extract structured status facts from documents so a comedy writer can \
work from them. You are not writing jokes — you are preparing raw material.

For each distinct item of work or status in the document, emit one fact with:
- name: what the thing is, in the document's own words where possible
- state: on_track, late, blocked, done, or unknown
- note: the specific detail that makes it interesting — a number, a reason, \
a duration, an excuse. Keep the document's phrasing rather than paraphrasing.
- owner: a person or team if the document names one, otherwise null
- date: any date or deadline attached to the item, otherwise null

Also collect `excerpts`: verbatim lines from the document that are vivid, \
absurd, euphemistic, or self-important. Copy them exactly. These are the \
highest-value material and must not be paraphrased.

Set `title` from the document's own heading if it has one.

Extract what is there. Do not invent items, infer status the document does \
not state, or editorialize.\
"""


def extract_facts(raw: str) -> StatusDoc:
    """Extract a StatusDoc from arbitrary document text."""
    if not raw.strip():
        raise ValueError("cannot extract facts from an empty document")

    doc = call_claude(
        system=SYSTEM,
        user=f"Extract the status facts from this document:\n\n{raw}",
        output_format=StatusDoc,
    )

    # Claude sometimes leaves ids blank; ids must be stable for veto and traceability.
    for index, fact in enumerate(doc.facts, start=1):
        if not fact.id:
            fact.id = f"f{index}"
    return doc
