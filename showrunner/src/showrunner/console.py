"""Gradio operator console. Mounted on the same FastAPI app as the REST adapter."""

import gradio as gr

from showrunner.claude import RefusalError
from showrunner.cli import format_setlist
from showrunner.ingest import extract_facts
from showrunner.models import Knobs
from showrunner.state import Show
from showrunner.writer import write_setlist


def facts_table(show: Show) -> list[list]:
    if show.status_doc is None:
        return []
    return [
        [f.included, f.id, f.name, f.state, f.owner or "", f.note]
        for f in show.status_doc.facts
    ]


def do_load(raw: str, show: Show) -> tuple[str, list[list]]:
    if not raw or not raw.strip():
        return "Paste a document first.", facts_table(show)
    try:
        show.load_document(raw)
        doc = extract_facts(raw)
        show.set_facts(doc)
    except RefusalError as exc:
        show.reset()
        return f"Claude declined the document: {exc}", []
    except (ValueError, RuntimeError) as exc:
        show.reset()
        return f"Could not read that document: {exc}", []
    n = len(doc.facts)
    return f"Extracted {n} fact{'s' if n != 1 else ''} from “{doc.title}”.", facts_table(show)


def apply_fact_edits(rows: list[list], show: Show) -> str:
    """Push include/exclude checkboxes from the table back into the show."""
    if show.status_doc is None:
        return "Nothing loaded."
    for row in rows or []:
        if len(row) >= 2:
            show.toggle_fact(str(row[1]), included=bool(row[0]))
    kept = len(show.status_doc.included_facts())
    return f"{kept} fact{'s' if kept != 1 else ''} included."


def do_write(beats: int, edge: str, notes: str, show: Show) -> tuple[str, str]:
    if show.status_doc is None:
        return "Load a document first.", ""
    knobs = Knobs(beat_count=int(beats), edge=edge, persona_notes=notes or "")
    show.knobs = knobs
    try:
        setlist = write_setlist(show.status_doc, knobs)
        show.set_setlist(setlist)
    except RefusalError as exc:
        return f"Claude declined to write that set: {exc}", ""
    except (ValueError, RuntimeError) as exc:
        return f"Could not write a set: {exc}", ""
    n = len(setlist.beats)
    rendered = format_setlist(show.status_doc, setlist)
    return f"Wrote {n} beat{'s' if n != 1 else ''}.", rendered


def do_arm(show: Show) -> str:
    if show.setlist is None:
        return "No set to arm — write one first."
    show.arm()
    return "Armed. The robot can now call get_set_list."


def live_status(show: Show) -> str:
    if show.setlist is None:
        return f"Phase: {show.phase.value}"
    return (
        f"Phase: {show.phase.value} — "
        f"{len(show.delivered)}/{len(show.setlist.beats)} beats delivered"
    )


def build_console(show: Show) -> gr.Blocks:
    with gr.Blocks(title="Reachy Showrunner") as console:
        gr.Markdown("# Reachy Showrunner")

        with gr.Tab("1 · Load"):
            raw = gr.Textbox(label="Document", lines=18, placeholder="Paste any status document…")
            load_btn = gr.Button("Extract facts", variant="primary")
            load_status = gr.Markdown()

        with gr.Tab("2 · Facts"):
            table = gr.Dataframe(
                headers=["include", "id", "name", "state", "owner", "note"],
                datatype=["bool", "str", "str", "str", "str", "str"],
                label="Extracted facts — untick anything you don't want joked about",
            )
            apply_btn = gr.Button("Apply")
            facts_status = gr.Markdown()

        with gr.Tab("3 · Set"):
            beats = gr.Slider(3, 8, value=5, step=1, label="Beats")
            edge = gr.Radio(["clean", "pg13", "blue"], value="pg13", label="Edge")
            notes = gr.Textbox(label="Extra direction (optional)", lines=2)
            write_btn = gr.Button("Write the set", variant="primary")
            write_status = gr.Markdown()
            rendered = gr.Textbox(label="Set list", lines=24)

        with gr.Tab("4 · Go"):
            arm_btn = gr.Button("Arm the set", variant="primary")
            arm_status = gr.Markdown()
            live = gr.Markdown()
            gr.Timer(2.0).tick(lambda: live_status(show), outputs=live)

        load_btn.click(lambda r: do_load(r, show), inputs=raw, outputs=[load_status, table])
        apply_btn.click(lambda rows: apply_fact_edits(rows, show), inputs=table, outputs=facts_status)
        write_btn.click(
            lambda b, e, n: do_write(b, e, n, show),
            inputs=[beats, edge, notes],
            outputs=[write_status, rendered],
        )
        arm_btn.click(lambda: do_arm(show), outputs=arm_status)

    return console
