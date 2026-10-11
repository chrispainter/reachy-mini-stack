"""gpt-live-1 transcripts carry no turn boundaries, and its delegation event carries no task
text. The request is what the person said since the robot last spoke."""


class TurnSegmenter:
    def __init__(self, max_chars: int = 500) -> None:
        self._max = max_chars
        self._current = ""
        self._robot_spoke = False

    def on_user_text(self, delta: str) -> None:
        if self._robot_spoke:  # the person has started a new turn
            self._current = ""
            self._robot_spoke = False
        self._current = (self._current + delta)[-self._max:]

    def on_robot_text(self, delta: str) -> None:
        if delta.strip():
            self._robot_spoke = True

    def request(self) -> str:
        return self._current.strip()
