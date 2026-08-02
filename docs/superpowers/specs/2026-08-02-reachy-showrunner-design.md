# Reachy Showrunner — Design

**Date:** 2026-08-02
**Status:** Architecture approved; modules pending review
**Episodes served:** BL-06, BL-08, BL-09, BL-10, (BL-07 in Phase 3)

## Problem

Make the Reachy Mini perform stand-up. It reads a document the operator supplies,
turns the status in that document into a comedy set, and delivers it live — staying
in character when people heckle.

The operator needs control over two things: the **data** (what the robot understood
from the document, before any jokes get written) and the **runtime** (loading a doc,
reviewing and vetoing material, tuning the set, triggering the performance).

## Decisions

| Question | Decision |
|---|---|
| Interaction model | On-demand party trick. Live, heckle-able. The realtime loop stays intact. |
| Document source | Bring-your-own. Any doc the operator supplies. |
| Bit structure | Pre-build a set list in a non-realtime pass; deliver it live. |
| Realtime backend | Unchanged. Hugging Face, as Pollen ships it. **No model swap.** |
| Set-list intelligence | Claude — Opus 5 for writing, Sonnet 5 for extraction. |
| Fork the app? | **No, not in Phase 1 or 2.** |

### Integration constraint (verified against upstream @ 648092b)

The conversation app has remote MCP tool support, but **it cannot be pointed at a
localhost server.** Verified in the source, not assumed:

- `mcp_client.py` defines `_LOCAL_HTTP_HOSTS = {"127.0.0.1", "localhost", "::1"}`
  and a generic `validate_mcp_url` that permits plain HTTP for those hosts —
  **but nothing in `src/` calls it.** The capability exists in the client and is
  never exposed by the app.
- The only construction site for `RemoteMcpServerConfig` in `src/` is
  `tool_spaces.py:518`, reached via `build_remote_client`, which calls
  `validate_space_mcp_url` unconditionally (line 514).
- `validate_space_mcp_url` requires `https`, a hostname ending `.hf.space`, port
  443, path exactly `/gradio_api/mcp/`, and no query or fragment.
- `read_installed_tool_spaces` re-validates on read (line 284), so hand-editing the
  installed-spaces manifest does not bypass it either.

**Consequence:** native MCP integration requires the showrunner to be a deployed HF
Space. Local development therefore integrates a different way — see Phase 1.

### Why still not fork

Both control surfaces we need (runtime, data) live entirely in our own service.
Phase 1 bridges to it with a ~40-line external tool; Phase 2 uses the native MCP
path once deployed. Neither requires touching upstream, so we avoid an ongoing
rebase burden for no gain.

**BL-06 is titled "forking the conversation app" and Phases 1–2 do not fork it.**
Retitle the episode, or shoot the fork at Phase 3 where it is genuinely warranted.
Do not fork to make a title true.

## Architecture

```
┌─ Reachy Mini (reachy-mini.local:8000) ──────────────────┐
│  reachy_mini_conversation_app                            │
│    profile: comedian  (external profile, no fork)        │
│    realtime loop ──► HF backend  (untouched)             │
│                                                          │
│    Phase 1:  external_tools/showrunner_bridge.py ──┐     │
│    Phase 2:  mcp_client ── tool_spaces ────────┐   │     │
└────────────────────────────────────────────────┼───┼─────┘
                              MCP over HTTPS ────┘   │ HTTP/JSON
                              (*.hf.space only)      │ (localhost)
┌────────────────────────────────────────────────────▼─────┐
│  SHOWRUNNER  (reachy-mini-stack/showrunner/)              │
│                                                           │
│    core:                                                  │
│      ingest   doc ─► facts             [Claude Sonnet 5]  │
│      writer   facts ─► set list        [Claude Opus 5]    │
│      state    pure state machine                          │
│                                                           │
│    adapters (thin, over state):                           │
│      rest     FastAPI routes      ─► Phase 1 bridge       │
│      mcp      Gradio /gradio_api/mcp/ ─► Phase 2 Space    │
│      console  Gradio UI                                   │
└───────────────────────────────────────────────────────────┘
```

The showrunner **never talks to the robot**. It has no robot dependency and
therefore no robot failure mode. The entire comedy pipeline is developable and
testable with the robot switched off.

### Phasing

- **Phase 1 — local, no fork.** Showrunner runs on localhost. A bridge tool in
  `external_content/external_tools/` HTTP-POSTs to it. Comedian profile in
  `external_content/external_profiles/`. Delivers BL-06, BL-08, BL-09.
- **Phase 2 — publish, still no fork.** Same core deployed as an HF Space; its
  Gradio MCP endpoint matches `validate_space_mcp_url`, so it installs from the
  app's Tools UI. **The bridge tool is deleted.** Delivers BL-10.
- **Phase 3 — fork, only if BL-07 demands it.** In-loop mic→motor timing is the one
  thing neither integration path provides; a remote tool can only time itself.
  Narrow diff against `huggingface_realtime.py`.

## Modules

### `ingest` — document → facts

Claude (Sonnet 5) extraction. A deterministic parser is not viable against
bring-your-own documents.

Produces `StatusDoc`:

- `title: str`
- `facts: list[Fact]` — `id`, `name`, `state` (on_track | late | blocked | done |
  unknown), `owner: str | None`, `note: str`, `date: str | None`, `included: bool`
- `excerpts: list[str]` — **verbatim lines from the source**
- `meta: dict` — counts, date range

Verbatim excerpts are load-bearing. The comedy is usually in the literal phrasing;
an extractor that emits only `state: blocked` has discarded the joke.

### `writer` — facts → set list

Claude (Opus 5), structured output. Consumes only facts where `included is True`.

Produces `SetList`:

- `opener: str`
- `beats: list[Beat]` — 4–6, operator-configurable
- `closer: str`
- `callbacks: list[Callback]` — planted references between beats

`Beat`:

- `id: str`
- `premise: str` — the true thing from the document
- `angle: str` — the comic take
- `act_out: str | None` — optional physical bit
- `punch: str`
- `tags: list[str]` — follow-up punches
- `source_fact_id: str` — traceability back to the document
- `move_hint: MoveHint` — robot move to hit on the punch (`play_emotion` name,
  `move_head` direction, or antenna beat)

`move_hint` authors the physical timing rather than leaving it to improvisation,
and is what makes **BL-09** ("Motion on the beat — why a robot beats a speaker")
nearly free.

**Two calls, not one.** Splitting extraction from writing is what delivers the
"control the data" requirement: the console shows what was understood *before* jokes
exist, the operator vetoes or edits facts, and the set regenerates **without
re-parsing**. A single combined call is faster and cheaper and offers no say.

The writer prompt carries the persona (Ian Bagg — crowd work, conversational, warm
but willing to be sharp) and a guardrail block: punch at process and situations, not
at individuals; no private information; PG-13 by default, controlled by the `edge`
knob.

### `state` — state machine

`IDLE → DOC_LOADED → FACTS_READY → SET_READY → PERFORMING → DONE`

Knobs: `beat_count`, `edge` (clean | pg13 | blue), `pace`, `persona_notes`.
Cursor: current beat index, delivered beat ids, heckle count.

Pure. No I/O. Exhaustively testable.

### Adapters

Three thin adapters over `state`, sharing one set of tool functions:

- **`rest`** — FastAPI routes (`POST /tools/<name>`). Phase 1 only.
- **`mcp`** — Gradio's built-in MCP server at `/gradio_api/mcp/`. Phase 2.
- **`console`** — Gradio UI, mounted on the same FastAPI app.

Defining the tool functions once and exposing them through all three keeps Phase 1
and Phase 2 behaviourally identical, so the migration is a config change rather
than a rewrite.

Console screens:

1. **Load** — paste, upload, or URL
2. **Facts** — extracted facts as a table; toggle `included`, edit inline
3. **Knobs** — beat count, edge, pace, persona notes
4. **Set** — generated set list; per-beat veto and regenerate
5. **Go** — arm the set; live cursor as the robot performs

### Tool surface

Three tools, deliberately minimal:

| Tool | Purpose |
|---|---|
| `get_set_list()` | Returns the whole arc in one call at "go" |
| `get_fact(query)` | Look up a document fact when heckled |
| `mark_beat(id)` | Fire-and-forget; lets the console follow along |

`get_set_list()` returns everything at once rather than drip-feeding beats. A
`next_beat()` design costs a network round-trip per punchline — the worst possible
place to spend latency — and denies the model the full arc it needs for callbacks to
land.

### `showrunner_bridge.py` — Phase 1 only

An external tool file, ~40 lines, subclassing `Tool` from
`reachy_mini_conversation_app.tools.core_tools`. Exposes the three tools above by
HTTP-POSTing to the local showrunner. Returns `{"error": ...}` on any failure.
Deleted at Phase 2. Deliberately throwaway; no logic beyond transport.

## Data flow

```
doc ──[Claude extract]──► StatusDoc ──[operator veto/edit]──► [Claude write] ──► SetList
                                                                                   │
                                                                 [operator veto/regen]
                                                                                   │
                                                                                 ARMED
                                                                                   │
robot: get_set_list() ──► performs ──► mark_beat() ──► console follows
                     └──► heckle ──► get_fact() ──► riffs in character
```

## Error handling

**Tools return `{"error": ...}` and never raise.** An exception propagating into the
conversation loop kills the show. This is upstream's documented rule and it is
absolute.

| Failure | Behaviour |
|---|---|
| Claude call fails | Console surfaces the error; prior state preserved |
| Structured output invalid | Retry once with the validation error appended; then fail visibly |
| `get_set_list()` with nothing armed | Returns a graceful "no set"; the profile prompt tells the comedian to cover with crowd work |
| `get_fact` finds nothing | Returns empty result, not an error; persona improvises |
| Showrunner unreachable (Phase 1) | Bridge returns `{"error": ...}`; persona covers |
| Robot unreachable | Not applicable — the showrunner never contacts the robot |

A comedian whose writer did not deliver is a bit, not a crash.

## Testing

| Module | Approach |
|---|---|
| `ingest` | Golden-file tests across doc shapes: markdown table (`btpc-leadgen/content/EPISODES.md` is a good fixture), bulleted status, prose email, tracker export. Claude mocked; a few live tests behind a marker. |
| `writer` | Schema and property tests — N beats requested yields N beats; every beat traces to an *included* fact. Quality is not unit-testable, so a `--dry-run` CLI prints a set for human review. |
| `state` | Exhaustive transition tests. Pure, so cheap. |
| `rest` / `mcp` | Contract tests asserting both adapters return identical payloads for the same state. Assert dict shape and no-raise on malformed input. |
| End-to-end | Script loads a fixture doc, builds a set, prints it. **This is the primary dev loop.** |
| Robot | Last step, deliberately. |

## Out of scope

Console authentication; set history or persistence; multi-user; local/on-device
models; any fork of the conversation app; audio or TTS in the showrunner; streaming
set generation.

## Configuration

- `ANTHROPIC_API_KEY` — required by the showrunner
- `SHOWRUNNER_URL` — read by the Phase 1 bridge tool; defaults to
  `http://127.0.0.1:7861`
- `REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY` — points the app at the comedian profile
- `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY` — points the app at the bridge tool
- `AUTOLOAD_EXTERNAL_TOOLS=1` — optional; loads external tools regardless of profile

## Risks

- **Upstream may tighten or change the external-tools loader**, breaking the Phase 1
  bridge. Mitigation: the bridge is throwaway and Phase 2 removes it entirely.
- **`move_hint` may not reliably fire.** The realtime model chooses whether to call
  `play_emotion` at the punch; the set list can only suggest. If hit rate is poor,
  the profile prompt needs strengthening before BL-09 is shootable.
- **Set quality is unverifiable by tests.** Requires human review via the dry-run
  CLI before any shoot.
