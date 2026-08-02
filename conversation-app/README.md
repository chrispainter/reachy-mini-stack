# Conversation app — Phase 1 wiring

The comedian profile and the showrunner bridge for
[`pollen-robotics/reachy_mini_conversation_app`](https://github.com/pollen-robotics/reachy_mini_conversation_app).

## Run

1. Start the showrunner:

   ```bash
   cd ../showrunner && ../.venv/bin/python -m uvicorn showrunner.api:build_app --factory --port 7861
   ```

   `build_app` is a factory so the Gradio import stays out of the module-level
   `app`, which the tests and any REST-only use import directly.

   Console at http://127.0.0.1:7861/ — load a document, review the facts,
   write the set, arm it.

2. Point the conversation app at this directory and start it:

   ```bash
   export REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=<abs path>/conversation-app/external_profiles
   export REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=<abs path>/conversation-app/external_tools
   export REACHY_MINI_CUSTOM_PROFILE=comedian
   export AUTOLOAD_EXTERNAL_TOOLS=1
   export SHOWRUNNER_URL=http://127.0.0.1:7861
   reachy-mini-conversation-app --ui
   ```

The bridge tool imports `reachy_mini_conversation_app.tools.core_tools`, so the
conversation app must be pip-installed in the same environment it runs from.

## Why a bridge instead of MCP

The conversation app has first-class remote MCP support, but it cannot be
pointed at localhost. `tool_spaces.validate_space_mcp_url` requires an HTTPS
host ending `.hf.space` on port 443 with the exact path `/gradio_api/mcp/`, and
it guards the only place `RemoteMcpServerConfig` is constructed. The installed-
spaces manifest is re-validated on read, so hand-editing it doesn't help either.
`mcp_client.py` does allow plain HTTP for localhost — but nothing in the app
calls that code path.

So local development bridges over plain HTTP instead.

## Phase 2

Delete `external_tools/showrunner_bridge.py`. The showrunner deploys as an HF
Space, its Gradio MCP endpoint matches the validator, and the app installs it
from the Tools UI over MCP.
