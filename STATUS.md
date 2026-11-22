# STATUS

Updated 2026-11-22. See `docs/progress-log.md`.

## Deployed

The result mailbox is live at `https://buildflows.cloud/webhook/kiko-result` (workflow
`kikoRsltRelay01`, name `Kiko result relay`). Auth is two Header Auth credentials, not container
env. The keys are in `/root/kiko-relay-secrets.env` (mode 600). The voice service on the robot
has not been updated from this branch, and the robot was not contacted for this change.

## Tested

- `python3 -m pytest voice/tests` — 196 passed.
- `(cd showrunner && python3 -m pytest tests/ -m "not live")` — 70 passed, 2 deselected.
- A laptop-only mailbox on `127.0.0.1` (not the robot) now expects a bad bearer to be 403 text
  `Authorization data is wrong!`, then a stored POST, a GET that returns and deletes, and a
  following 404. The voice client stops polling on 401 and 403.

## Open

- The Grok Bot webhook routine still has to be created, and `voice.env` on the robot still needs
  `PERSONA_NAME=kiko`, `KIKO_RESULT_URL`, and `KIKO_RESULT_KEY` (the same value as
  `KIKO_RELAY_GET_KEY`), mode 600.
- The on-robot smoke test has not been run.
- A Grok Bot routine may not have a shell `curl` or an env var named `KIKO_RELAY_POST_KEY`. The prompt allows an HTTP tool with the same request. Confirm that on the Bot before the first real job.

## Next

- Create the routine from `docs/kiko-relay.md`. Copy the panel URL and key into `voice.env`.
- Set `KIKO_RESULT_URL` to `https://buildflows.cloud/webhook/kiko-result` and `KIKO_RESULT_KEY` to
  the GET key. Then from the Mac run `voice/deploy/deploy-voice.sh`.
- Smoke: "Hey Jarvis", then "ask Kiko what's on my calendar today".
