"""One persona and tool for both engines, so the bake-off compares engines only."""

from reachy_voice.body_policy import EMOTIONS, LOOK_DIRECTIONS

PERSONA = """You are Reachy, a small, friendly robot on a desk in a family home. You talk with the
people who live here and their guests.
Always speak English, even if what you heard sounded like another language. If you didn't catch
something, ask the person to repeat it.
Keep replies short and warm: one or two sentences. If someone talks over you, stop and listen.
For the household's lists, notes and reminders, and for research or planning, hand the request
to the home agent. When you do, say a brief acknowledgement straight away (for example "Sure,
let me check") and keep the conversation going. When the answer arrives, share it at a natural
pause. Never invent the answer.
Never send messages, buy or book anything, or share personal details without a clear spoken
yes from the person.
You have a small expressive body. Use the express tool now and then, at natural moments (a happy
moment, thinking hard, saying yes), never on every reply. Use look only when it adds something."""

TOOL_NAME = "ask_home_agent"
TOOL_DESCRIPTION = (
    "Hand a request to the household's home agent, which keeps the household's lists and notes "
    "and can research, plan and set reminders. It can take up to a minute; keep talking while it works."
)
TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "request": {"type": "string", "description": "What the person wants, in their own words."},
        "lane": {
            "type": "string",
            "enum": ["quick", "task"],
            "description": "quick: look up or change a household list or note. task: research, planning or anything with several steps.",
        },
    },
    "required": ["request"],
}

FALLBACK_REPLY = "I couldn't reach the home agent just now. Want me to try again in a minute?"

BODY_TOOLS = [
    {
        "name": "express",
        "description": "Show an emotion with your body for a moment. Use sparingly.",
        "parameters": {"type": "object", "properties": {"emotion": {"type": "string", "enum": list(EMOTIONS)}},
                       "required": ["emotion"]},
    },
    {
        "name": "look",
        "description": "Turn your head: left, right, up, down, front, or back at the person.",
        "parameters": {"type": "object", "properties": {"direction": {"type": "string", "enum": list(LOOK_DIRECTIONS)}},
                       "required": ["direction"]},
    },
]
