# Progress log

## 2026-11-22

Kiko can speak through Reachy's realtime voice. `PERSONA_NAME=kiko` selects that persona; the
default stays Reachy. `ask_kiko` posts the request to the household Grok Bot routine webhook and
polls an n8n mailbox for a short spoken reply. Lists and notes still go to Hermes. The relay
workflow is in the repo and inactive. Nothing was deployed, and the robot was not touched.

Voice tests: 189 passed. Showrunner tests: 70 passed, 2 deselected (`not live`).

The spoken cap is `KIKO_MAX_WORDS`, default 150, instead of a fixed 60 words. A longer reply is
cut at a sentence boundary when one sits inside the budget, then Reachy adds "The rest is in the
app." The Grok Bot routine is asked for a conversational answer around that length, with the full
detail left in the app. `deploy-voice.sh` carries `KIKO_MAX_WORDS` when that line is present.

Voice tests after the cap change: 193 passed. Showrunner tests: 70 passed, 2 deselected (`not live`).

The live mailbox is `https://buildflows.cloud/webhook/kiko-result` (workflow `kikoRsltRelay01`,
name `Kiko result relay`). It uses two n8n Header Auth credentials, not container env, so n8n did
not need a restart. A wrong or missing key is HTTP 403 text `Authorization data is wrong!`.
Reachy treats 401 and 403 as auth failure, stops polling, logs `delegation_error` with `auth`,
and says Kiko will follow up in the app. The keys stay in `/root/kiko-relay-secrets.env` (mode
600). The robot's `KIKO_RESULT_KEY` matches `KIKO_RELAY_GET_KEY`.

Voice tests after the auth change: 196 passed. Showrunner tests: 70 passed, 2 deselected (`not live`).
