"""The three functions the realtime model calls. These never raise."""

from typing import Any

from showrunner.state import Phase, Show


def get_set_list(show: Show) -> dict[str, Any]:
    """Return the whole arc in one call. Graceful when nothing is armed."""
    if show.setlist is None or show.phase not in (Phase.PERFORMING, Phase.DONE):
        return {
            "status": "no_set",
            "message": (
                "No set is loaded. Your writer did not deliver. "
                "Work the room instead."
            ),
        }
    return {
        "status": "ok",
        "title": show.status_doc.title if show.status_doc else "",
        "opener": show.setlist.opener,
        "beats": [b.model_dump() for b in show.setlist.beats],
        "closer": show.setlist.closer,
        "callbacks": show.setlist.callbacks,
    }


def get_fact(show: Show, query: Any) -> dict[str, Any]:
    """Look up document facts by substring. Empty results are not errors."""
    if show.status_doc is None or not isinstance(query, str) or not query.strip():
        return {"status": "ok", "facts": []}

    needle = query.strip().lower()
    matches = [
        f.model_dump()
        for f in show.status_doc.facts
        if needle in f.name.lower()
        or needle in f.note.lower()
        or (f.owner and needle in f.owner.lower())
    ]
    return {"status": "ok", "facts": matches}


def mark_beat(show: Show, beat_id: Any) -> dict[str, Any]:
    """Record a delivered beat so the console can follow along."""
    if not isinstance(beat_id, str):
        return {"status": "unknown_beat"}
    if show.mark_beat(beat_id):
        return {"status": "ok", "delivered": len(show.delivered)}
    return {"status": "unknown_beat"}
