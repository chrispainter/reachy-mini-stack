"""REST adapter. Phase 1 only — the bridge tool talks to this."""

from typing import Any

from fastapi import FastAPI, Request

from showrunner import tools
from showrunner.claude import RefusalError
from showrunner.ingest import extract_facts
from showrunner.models import Knobs
from showrunner.state import Show
from showrunner.writer import write_setlist

# Process-wide show, shared with the Gradio console mounted on the same app.
SHOW = Show()


def create_app(show: Show | None = None) -> FastAPI:
    active = show if show is not None else SHOW
    app = FastAPI(title="Reachy Showrunner")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "phase": active.phase.value}

    @app.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if name == "get_set_list":
            return tools.get_set_list(active)
        if name == "get_fact":
            return tools.get_fact(active, body.get("query", ""))
        if name == "mark_beat":
            return tools.mark_beat(active, body.get("beat_id", ""))
        return {"error": f"unknown tool: {name}"}

    # Operator endpoints mirror the console so a set can be prepared from a
    # script — needed for headless robot testing and for repeatable takes.
    @app.post("/operator/load")
    async def operator_load(request: Request) -> dict[str, Any]:
        body = await _json(request)
        raw = body.get("document", "")
        if not isinstance(raw, str) or not raw.strip():
            return {"error": "document is required"}
        try:
            active.load_document(raw)
            doc = extract_facts(raw)
            active.set_facts(doc)
        except RefusalError as exc:
            active.reset()
            return {"error": f"declined: {exc}"}
        except (ValueError, RuntimeError) as exc:
            active.reset()
            return {"error": str(exc)}
        return {
            "status": "ok",
            "title": doc.title,
            "facts": [f.model_dump() for f in doc.facts],
        }

    @app.post("/operator/write")
    async def operator_write(request: Request) -> dict[str, Any]:
        body = await _json(request)
        if active.status_doc is None:
            return {"error": "load a document first"}
        try:
            knobs = Knobs(
                beat_count=int(body.get("beat_count", active.knobs.beat_count)),
                edge=body.get("edge", active.knobs.edge),
                persona_notes=body.get("persona_notes", ""),
            )
            active.knobs = knobs
            setlist = write_setlist(active.status_doc, knobs)
            active.set_setlist(setlist)
        except RefusalError as exc:
            return {"error": f"declined: {exc}"}
        except (ValueError, RuntimeError) as exc:
            return {"error": str(exc)}
        return {"status": "ok", "beats": len(setlist.beats), "setlist": setlist.model_dump()}

    @app.post("/operator/arm")
    async def operator_arm() -> dict[str, Any]:
        if active.setlist is None:
            return {"error": "no set to arm"}
        active.arm()
        return {"status": "ok", "phase": active.phase.value}

    @app.post("/operator/reset")
    async def operator_reset() -> dict[str, Any]:
        active.reset()
        return {"status": "ok", "phase": active.phase.value}

    return app


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def build_app() -> FastAPI:
    """The full Phase 1 server: REST tools plus the operator console at /."""
    import gradio as gr

    from showrunner.console import build_console

    fastapi_app = create_app(SHOW)
    return gr.mount_gradio_app(fastapi_app, build_console(SHOW), path="/")


app = create_app()
