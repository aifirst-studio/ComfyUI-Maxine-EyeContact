"""Small atomic status file shared with the isolated gRPC worker."""
import json
import os
from pathlib import Path
import threading
import time


class ProgressWriter:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.state = {"sent_bytes": 0, "received_bytes": 0, "frames": None}
        self.lock = threading.Lock()
        self.updated = 0

    def update(self, force=False, **values):
        if self.path is None:
            return
        with self.lock:
            self.state.update(values)
            now = time.monotonic()
            if not force and now - self.updated < 0.25:
                return
            temporary = self.path.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps(self.state), encoding="utf-8")
                os.replace(temporary, self.path)
                self.updated = now
            except OSError:
                # Display problems must not abort video correction.
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
