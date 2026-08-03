"""Shared Claude client. One place to own model choice and refusal handling."""

import os
from pathlib import Path
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

# .../showrunner/src/showrunner/claude.py -> .../showrunner/
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PACKAGE_ROOT / ".env"

# load_dotenv never overrides an already-exported variable, so an env var set
# in the shell still wins over the file.
load_dotenv(ENV_FILE)
load_dotenv()  # also honour a .env in the working directory

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class RefusalError(RuntimeError):
    """Claude's safety classifiers declined the request."""


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Put it in "
                f"{ENV_FILE} (gitignored) or export it in your shell."
            )
        _client = anthropic.Anthropic()
    return _client


def call_claude(
    *,
    system: str,
    user: str,
    output_format: type[T],
    effort: str = "high",
) -> T:
    """One structured-output call. Raises RefusalError on a policy decline.

    No temperature/top_p/top_k — Opus 5 rejects them with a 400.
    max_tokens covers thinking plus response text, so it is set generously.
    """
    response = get_client().messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user}],
        output_format=output_format,
    )
    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", "") or "no explanation"
        raise RefusalError(f"Claude declined the request: {detail}")
    if response.parsed_output is None:
        raise RuntimeError(f"no parsed output (stop_reason={response.stop_reason})")
    return response.parsed_output
