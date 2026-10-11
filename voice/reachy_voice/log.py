"""One JSON object per line: the raw material for latency and bake-off analysis."""

import json
import os
import time


class JsonlLog:
    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def write(self, event: str, **fields) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, "ts": time.time(), **fields}) + "\n")
