# Household agent: Reachy is the face, Hermes is the brain

Anyone in the house talks to Reachy. Reachy handles conversation, presence and
motion itself, and hands real work to a Hermes Agent running on the Pi.

```
 person ──voice──► Reachy Mini Wireless (onboard conversation app, "household" profile)
                     │  realtime voice: Hugging Face backend (needs HF sign-in on the robot)
                     │  own tools: emotions, head, camera, dance, weather, time, web search, memory
                     │
                     └─ ask_home_agent ──HTTP, bearer key, LAN only──► Hermes Agent (Docker on reachy-pi:8642)
                                                                        model: OpenAI (gpt-5.4-mini)
                                                                        memory, skills, cron, sessions
```

The tool runs in the app's background tool manager, so Reachy keeps talking
while Hermes works and speaks the answer when it lands.

## Layout

| Path | What |
|---|---|
| `robot-profile/household/` | Conversation-app profile: `instructions.txt`, `tools.txt`, and the `ask_home_agent.py` bridge tool |
| `hermes/` | `docker-compose.yml`, `config.yaml` (model, approvals) and `SOUL.md` (persona, spoken-reply rules, hard safety rules) |
| `deploy/deploy-pi.sh` | Deploys or updates Hermes on the Pi |
| `deploy/deploy-robot.sh` | Installs the profile on the robot, wires it to Hermes, restarts the app |

## Deploy (from the Mac)

```bash
household/deploy/deploy-pi.sh      # Hermes on the Pi
household/deploy/deploy-robot.sh   # profile + tool on the robot, then restart the app
```

Both are idempotent. Re-run `deploy-robot.sh` after updating the conversation
app from the Reachy Mini Control app, because the update wipes the app's
instance directory where the profile lives.

## Where secrets live (never in git)

- Pi: `~/.config/household/agent.env` (mode 600) holds `OPENAI_API_KEY` and
  `API_SERVER_KEY`; compose passes them in through `env_file`.
- Robot: the app instance `.env` holds `HOME_AGENT_URL` and `HOME_AGENT_KEY`.
- Robot: the Hugging Face sign-in. The OAuth token expires (about 30 days), and an
  expired token makes Reachy go silent with `401 Unauthorized` from
  `pollen-robotics-reachy-mini-realtime-url.hf.space` in the logs. To fix it, sign in
  again from the Reachy Mini Control app, or open
  `http://reachy-mini.local:8000/api/hf-auth/oauth/begin`.

## Safety model

- Hermes is reachable on the LAN only, and every request needs the bearer key.
- API-server sessions count as unattended: `approvals.unattended_mode: deny`
  refuses risky shell commands outright.
- `SOUL.md` and the robot profile both require a spoken yes before anything
  outward-facing (messages, purchases, bookings, sharing personal details).
- Hermes runs inside a container, so its terminal tool can't touch the Pi's host
  filesystem.

## Operating it

```bash
# Hermes logs / health
ssh behindtheproduct@reachy-pi.local 'docker logs -f hermes'
curl http://reachy-pi.local:8642/health

# Robot app logs
ssh pollen@reachy-mini.local 'journalctl -u reachy-mini-daemon -f | grep -v onnxruntime'

# Restart the robot app
curl -X POST http://reachy-mini.local:8000/api/apps/restart-current-app
```

Change the model in `hermes/config.yaml`, then re-run `deploy-pi.sh`.
