"""REST adapter. Phase 1 only — the bridge tool talks to this."""

from typing import Any

from fastapi import FastAPI, Request

from showrunner import tools
from showrunner.state import Show

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

    return app


def build_app() -> FastAPI:
    """The full Phase 1 server: REST tools plus the operator console at /."""
    import gradio as gr

    from showrunner.console import build_console

    fastapi_app = create_app(SHOW)
    return gr.mount_gradio_app(fastapi_app, build_console(SHOW), path="/")


app = create_app()
