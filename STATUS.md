# STATUS

Updated 2026-11-22. See `docs/progress-log.md`.

## Deployed

Not deployed. The Kiko voice path is a review-only branch stacked on the Grok voice engine.
The robot was not contacted, and the n8n workflow was not imported or activated.

## Tested

- `python3 -m pytest voice/tests` — 193 passed.
- `(cd showrunner && python3 -m pytest tests/ -m "not live")` — 70 passed, 2 deselected.
- A laptop-only mailbox on `127.0.0.1` (not the robot): a bad bearer is 401, a POST stores speech,
  a GET returns it and deletes it, and the next GET is 404. The voice client, pointed at that
  mailbox, posted `{job_id, text, from, reply_to}` and spoke a long reply cut to the word cap,
  with "The rest is in the app." when the reply was longer. `KIKO_MAX_WORDS` defaults to 150.

## Open

- The owner imports `voice/relay/kiko-relay.n8n.json` and leaves it inactive until they choose to activate it.
- The owner creates the Grok Bot webhook routine and puts the keys in `~/reachy-voice/voice.env` (mode 600).
- The on-robot smoke test has not been run.
- A Grok Bot routine may not have a shell `curl` or an env var named `KIKO_RELAY_POST_KEY`. The prompt allows an HTTP tool with the same request. Confirm that on the Bot before the first real job.

## Next

- Import the relay, set `KIKO_RELAY_POST_KEY` and `KIKO_RELAY_GET_KEY` in n8n, and activate only when ready.
- Create the routine from `docs/kiko-relay.md`. Copy the panel URL and key into `voice.env`.
- Set `PERSONA_NAME=kiko` and the `KIKO_*` lines, then from the Mac run `voice/deploy/deploy-voice.sh`.
- Smoke: "Hey Jarvis", then "ask Kiko what's on my calendar today".
