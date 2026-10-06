"""One JSON object per line, so runs can be summarised and compared later."""

import json
import time


class JsonlLog:
    def __init__(self, path: str) -> None:
        self._path = path

    def write(self, event: str, **fields) -> None:
        record = {"event": event, "ts": time.time(), **fields}
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
