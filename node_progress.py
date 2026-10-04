"""ComfyUI progress plus optional descriptive frontend status."""
import json
import time

from comfy.utils import ProgressBar


class NodeProgress:
    def __init__(self, node_id=None):
        self.bar = ProgressBar(1000, node_id=node_id)
        self.node_id = node_id
        self.started = time.monotonic()
        self.last_sent = 0
        self.value = 0
        self.details = {}

    def update(self, value=None, phase=None, fraction=None, indeterminate=False, **details):
        previous_phase = self.details.get("phase")
        self.details.update(details)
        if phase:
            self.details["phase"] = phase
        if value is not None:
            self.value = max(self.value, min(1000, int(value)))
            self.bar.update_absolute(self.value)
        now = time.monotonic()
        if phase != previous_phase or now - self.last_sent >= 0.5 or phase in ("complete", "error"):
            self.last_sent = now
            try:
                from server import PromptServer
                server = PromptServer.instance
                if self.node_id is not None and server is not None:
                    server.send_sync("maxine_eye_contact.progress", {
                        **self.details, "node": str(self.node_id), "value": self.value,
                        "fraction": fraction, "indeterminate": indeterminate,
                        "elapsed": round(now - self.started),
                    }, sid=server.client_id)
            except (ImportError, AttributeError):
                pass  # API-only and CPU-test execution need no browser instance.

    def scan(self, start, end, phase, total=None):
        def callback(count, declared):
            expected = total or declared
            ratio = min(count / expected, 0.99) if expected else None
            self.update(start + (end - start) * (ratio or 0), phase,
                        fraction=ratio, indeterminate=ratio is None, scanned_frames=count)
        return callback

    def ffmpeg(self, path, frames, start, end, phase):
        def callback():
            current = 0
            try:
                with path.open("rb") as status:
                    status.seek(0, 2)
                    status.seek(max(0, status.tell() - 65536))
                    for line in status.read().decode("utf-8", "replace").splitlines():
                        if line.startswith("frame="):
                            current = int(line.split("=", 1)[1])
            except (OSError, ValueError):
                pass
            ratio = min(current / frames, 0.99) if frames else None
            self.update(start + (end - start) * (ratio or 0), phase,
                        fraction=ratio, indeterminate=ratio is None, stage_frames=current)
        return callback

    def inference(self, path, total):
        return self.stream_frames(path, total, 200, 800, "processing")

    def stream_frames(self, path, total, start, end, phase):
        def callback():
            try:
                status = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                status = {}
            count = status.get("frames")
            ratio = min(count / total, 0.99) if count is not None and total else None
            self.update(start + (end - start) * (ratio or 0), phase, fraction=ratio,
                        indeterminate=ratio is None, frames=count, total_frames=total,
                        matched_frames=status.get("matched_frames"),
                        sent_bytes=status.get("sent_bytes", 0),
                        total_bytes=status.get("total_bytes", 0),
                        received_bytes=status.get("received_bytes", 0))
        return callback
