"""Owner-managed subscription switch, persisted independently of credentials."""
import json
import threading
from functools import lru_cache
from pathlib import Path

from horsie.data_storage import data_path, write_json


class ControlError(Exception):
    pass


class ChatGPTControls:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.state = dict(enabled=True)
        self.storage_ok = True
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if type(raw.get("enabled")) is not bool:
                    raise ValueError("Invalid controls")
                self.state = {key: raw[key] for key in self.state}
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            self.state["enabled"] = False
            self.storage_ok = False

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def update(self, **changes):
        with self.lock:
            candidate = {**self.state, **changes}
            try:
                write_json(self.path, candidate)
            except OSError as error:
                # A failed off write still stops this process immediately.
                if changes.get("enabled") is False:
                    self.state["enabled"] = False
                self.storage_ok = False
                raise ControlError("Could not save ChatGPT settings. ChatGPT is paused; check storage.") from error
            self.state = candidate
            self.storage_ok = True

    def report(self):
        state = self.snapshot()
        return (f"ChatGPT requests: {'ON' if state['enabled'] and self.storage_ok else 'OFF'}. "
                "Only used after Groq backups fail.")


@lru_cache(maxsize=4)
def controls_for(path):
    return ChatGPTControls(path)


def controls():
    return controls_for(str(data_path("HORSE_CHATGPT_CONTROLS_FILE", "horse_chatgpt_controls.json")))
