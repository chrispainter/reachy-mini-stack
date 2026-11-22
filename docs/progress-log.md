# Progress log

## 2026-11-22

Kiko can speak through Reachy's realtime voice. `PERSONA_NAME=kiko` selects that persona; the
default stays Reachy. `ask_kiko` posts the request to the household Grok Bot routine webhook and
polls an n8n mailbox for a short spoken reply. Lists and notes still go to Hermes. The relay
workflow is in the repo and inactive. Nothing was deployed, and the robot was not touched.

Voice tests: 189 passed. Showrunner tests: 70 passed, 2 deselected (`not live`).
